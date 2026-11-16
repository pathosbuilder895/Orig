"""
Pure harness for G-WRITERLINE: per-pair records carrying rms_z and the
claimed writer's leave-one-out distances, z cut-offs chosen on the
derivation split only, and catch / false-alarm rates for ``gate`` and
``writer_line`` on any split.

Reuses ``validation.rebind.harness`` for the record shape, the author-disjoint
split and the ``gate`` baseline action. ``writer_line`` mode is
``writer_line_action(writer_z(rms_z, loo), thresholds)``; where that abstains
(fewer than WRITER_LINE_MIN_PAPERS loo papers, non-finite input) the pair
falls back to the gate baseline action, as production does.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from original.constants import WRITER_LINE_MIN_PAPERS, WRITER_LINE_STD_FLOOR
from original.quantum.writer_line import writer_line_action, writer_z
from validation.rebind.harness import PairRecord, load_records
from validation.rebind.harness import _action as _rebind_mode_action

_SC_PLUS = frozenset({"schedule_conversation", "escalate"})
# Monitor is placed at twice the schedule_conversation false-alarm budget.
MONITOR_FPR_FACTOR = 2.0


@dataclass(frozen=True)
class WriterPairRecord(PairRecord):
    rms_z: float = float("nan")
    loo: tuple[float, ...] = ()


def load_writer_records(path: Path) -> list[WriterPairRecord]:
    """Read one run_null_model.py report.json, requiring rms_z and loo."""
    base = load_records(path)
    pairs = json.loads(Path(path).read_text(encoding="utf-8"))["extra"]["pairs"]
    missing = sum(1 for p in pairs if "rms_z" not in p or "loo" not in p)
    if missing:
        raise ValueError(
            f"{path}: {missing} of {len(pairs)} pairs lack rms_z/loo, so re-run "
            "validation/verify/run_null_model.py (rms_z and loo were added for "
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
            rms_z=float(p["rms_z"]),
            loo=tuple(float(x) for x in p["loo"]),
        )
        for r, p in zip(base, pairs, strict=True)
    ]


def record_z(r: WriterPairRecord) -> float | None:
    return writer_z(r.rms_z, list(r.loo))


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
        return tier, False
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
    """Writers whose escalate line (loo mean + esc z * floored loo std) sits
    above every rms_z scored against them, so nothing reaches escalate."""
    esc = thresholds["escalate"][0]
    by_writer: dict[str, list[WriterPairRecord]] = {}
    for r in records:
        by_writer.setdefault(r.author, []).append(r)
    unreachable, eligible = [], 0
    for writer, rs in sorted(by_writer.items()):
        loo = rs[0].loo
        if len(loo) < WRITER_LINE_MIN_PAPERS:
            continue
        eligible += 1
        line = float(np.mean(loo)) + esc * max(float(np.std(loo)), WRITER_LINE_STD_FLOOR)
        finite = [r.rms_z for r in rs if math.isfinite(r.rms_z)]
        if not finite or max(finite) < line:
            unreachable.append(writer)
    return {"count": len(unreachable), "of": eligible, "writers": unreachable}
