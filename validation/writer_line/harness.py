"""
Pure harness for G-WRITERLINE: per-pair records carrying deviation, llr and
the claimed writer's leave-one-out deviation reference (``loo_dev``: each
baseline paper's deviation_score against the writer's other papers), z
cut-offs chosen on the derivation split only, and catch / false-alarm rates
for ``gate`` and ``writer_line`` on any split.

Reuses ``validation.rebind.harness`` for the record shape, the author-disjoint
split and the ``gate`` baseline action. ``writer_line`` mode is
``writer_line_action(writer_z(deviation, loo_dev), thresholds)`` followed by
the same one-step gate downgrade production applies; where the writer line
abstains (fewer than WRITER_LINE_MIN_PAPERS loo papers, non-finite input) the
pair falls back to the gate baseline action, as production does.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from original.constants import WRITER_LINE_MIN_PAPERS, WRITER_LINE_STD_FLOOR
from original.quantum.scoring import _llr_action_candidates
from original.quantum.writer_line import writer_line_action, writer_z
from validation.rebind.harness import PairRecord, load_records
from validation.rebind.harness import _action as _rebind_mode_action

_SC_PLUS = frozenset({"schedule_conversation", "escalate"})
# Monitor is placed at twice the schedule_conversation false-alarm budget.
MONITOR_FPR_FACTOR = 2.0


@dataclass(frozen=True)
class WriterPairRecord(PairRecord):
    loo_dev: tuple[float, ...] = ()


def load_writer_records(path: Path) -> list[WriterPairRecord]:
    """Read one run_null_model.py report.json, requiring loo_dev."""
    base = load_records(path)
    pairs = json.loads(Path(path).read_text(encoding="utf-8"))["extra"]["pairs"]
    missing = sum(1 for p in pairs if "loo_dev" not in p)
    if missing:
        raise ValueError(
            f"{path}: {missing} of {len(pairs)} pairs lack loo_dev, so re-run "
            "validation/verify/run_null_model.py (loo_dev was added for "
            "G-WRITERLINE)"
        )
    return [
        WriterPairRecord(
            author=r.author,
            genuine=r.genuine,
            deviation=r.deviation,
            llr=r.llr,
            corpus=r.corpus,
            submission_author=r.submission_author,
            loo_dev=tuple(float(x) for x in p["loo_dev"]),
        )
        for r, p in zip(base, pairs, strict=True)
    ]


def record_z(r: WriterPairRecord) -> float | None:
    return writer_z(r.deviation, list(r.loo_dev))


def _lowest_cut(values: list[float], candidates: list[float], max_fpr: float) -> float:
    n = len(values)
    for c in candidates:
        if sum(1 for v in values if v >= c) / n <= max_fpr:
            return c
    raise AssertionError("unreachable: last candidate admits no genuine value")  # pragma: no cover


def select_z_thresholds(
    derivation: list[WriterPairRecord], max_fpr: float = 0.05
) -> dict[str, tuple[float, float]]:
    """Contiguous z bands from derivation genuine z only. schedule_conversation
    is the lowest z with genuine false-alarm rate <= max_fpr, escalate the same
    at max_fpr / 5, monitor at max_fpr * MONITOR_FPR_FACTOR."""
    genuine = [z for r in derivation if r.genuine and (z := record_z(r)) is not None]
    if not genuine:
        raise ValueError("select_z_thresholds needs at least one genuine record with a z")
    candidates = sorted(set(genuine) | {max(genuine) + 1e-9})
    mon = _lowest_cut(genuine, candidates, max_fpr * MONITOR_FPR_FACTOR)
    sc = _lowest_cut(genuine, candidates, max_fpr)
    esc = _lowest_cut(genuine, candidates, max_fpr / 5)
    return {
        "no_action": (float("-inf"), mon),
        "monitor": (mon, sc),
        "schedule_conversation": (sc, esc),
        "escalate": (esc, float("inf")),
    }


def _action(r: WriterPairRecord, mode: str, thresholds) -> tuple[str, bool]:
    """(action, fell_back)."""
    if mode == "gate":
        return _rebind_mode_action(r, "gate", None), False
    if mode == "writer_line":
        tier = writer_line_action(record_z(r), thresholds)
        if tier is None:
            return _rebind_mode_action(r, "gate", None), True
        return _llr_action_candidates(tier, r.deviation, r.llr)["gate"], False
    raise ValueError(f"unknown mode: {mode!r}")


def _share(actions: list[str], hit) -> float | None:
    return sum(1 for a in actions if hit(a)) / len(actions) if actions else None


def rates(records: list[WriterPairRecord], mode: str, thresholds) -> dict:
    gen = [_action(r, mode, thresholds) for r in records if r.genuine]
    imp = [_action(r, mode, thresholds) for r in records if not r.genuine]
    ga, ia = [a for a, _ in gen], [a for a, _ in imp]
    return {
        "catch_sc": _share(ia, lambda a: a in _SC_PLUS),
        "fa_sc": _share(ga, lambda a: a in _SC_PLUS),
        "fa_esc": _share(ga, lambda a: a == "escalate"),
        "n_genuine": len(ga),
        "n_impostor": len(ia),
        "n_fallback": sum(1 for _, f in gen + imp if f),
    }


def writers_escalate_unreachable(records: list[WriterPairRecord], thresholds) -> dict:
    """Writers whose escalate line (loo_dev mean + esc z * floored loo_dev
    std) sits above every deviation scored against them, so nothing reaches
    escalate (before the gate downgrade)."""
    esc = thresholds["escalate"][0]
    by_writer: dict[str, list[WriterPairRecord]] = {}
    for r in records:
        by_writer.setdefault(r.author, []).append(r)
    unreachable, eligible = [], 0
    for writer, rs in sorted(by_writer.items()):
        loo = rs[0].loo_dev
        if len(loo) < WRITER_LINE_MIN_PAPERS:
            continue
        eligible += 1
        line = float(np.mean(loo)) + esc * max(float(np.std(loo)), WRITER_LINE_STD_FLOOR)
        finite = [r.deviation for r in rs if math.isfinite(r.deviation)]
        if not finite or max(finite) < line:
            unreachable.append(writer)
    return {"count": len(unreachable), "of": eligible, "writers": unreachable}


def _cut_at(values: list[float], max_fpr: float) -> float:
    candidates = sorted(set(values) | {max(values) + 1e-9})
    return _lowest_cut(values, candidates, max_fpr)


def exploratory_split_average(
    records: list[WriterPairRecord], seeds: range = range(200), max_fpr: float = 0.05
) -> dict:
    """EXPLORATORY, not a gate input. For each seed, split author-disjoint,
    cut each continuous score (gate: deviation; writer_line: writer z) at the
    lowest value with derivation genuine false alarms <= max_fpr, then average
    hold-out catch and genuine false-alarm rates at that cut over the seeds.
    Pairs without a writer z are left out of the writer_line arm."""
    from validation.rebind.harness import split_by_author

    scores = {
        "gate": lambda r: r.deviation,
        "writer_line": record_z,
    }
    acc = {m: {"catch": [], "fa": []} for m in scores}
    used = 0
    for seed in seeds:
        derivation, holdout = split_by_author(records, seed=seed)
        rows = {}
        for m, f in scores.items():
            dg = [v for r in derivation if r.genuine and (v := f(r)) is not None]
            hg = [v for r in holdout if r.genuine and (v := f(r)) is not None]
            hi = [v for r in holdout if not r.genuine and (v := f(r)) is not None]
            if not dg or not hg or not hi:
                break
            cut = _cut_at(dg, max_fpr)
            rows[m] = (
                sum(1 for v in hi if v >= cut) / len(hi),
                sum(1 for v in hg if v >= cut) / len(hg),
            )
        else:
            used += 1
            for m, (c, fa) in rows.items():
                acc[m]["catch"].append(c)
                acc[m]["fa"].append(fa)
    return {
        "label": "exploratory (not a gate input)",
        "seeds": [seeds[0], seeds[-1]],
        "n_splits_used": used,
        "max_fpr_derivation": max_fpr,
        **{
            m: {
                "mean_holdout_catch": float(np.mean(a["catch"])) if a["catch"] else None,
                "mean_holdout_fa": float(np.mean(a["fa"])) if a["fa"] else None,
            }
            for m, a in acc.items()
        },
    }
