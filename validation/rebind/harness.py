"""
Pure harness for G-REBIND: load per-pair records, split them author-disjoint,
pick rebind cut-offs on the derivation split only, and measure catch and
false-alarm rates for ``gate`` and ``rebind`` on any split.

Records come from ``validation/verify/run_null_model.py``'s report.json, under
``extra.pairs`` (one row per scored (claimed author, submission author) pair;
``baseline_author == submission_author`` is a same-author/genuine pair, every
other row a different-author/impostor pair). ``PairRecord.author`` is the
claimed (baseline) author, which is what the split is disjoint on.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from original.constants import ACTION_THRESHOLDS
from original.quantum.scoring import _llr_action_candidates, _rebind_action

_SC_PLUS = frozenset({"schedule_conversation", "escalate"})
MONITOR_OFFSET = 0.15


@dataclass(frozen=True)
class PairRecord:
    author: str
    genuine: bool
    deviation: float
    llr: float
    corpus: str


def load_records(path: Path) -> list[PairRecord]:
    """Read one run_null_model.py report.json into PairRecords."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    pairs = (data.get("extra") or {}).get("pairs")
    if pairs is None:
        raise ValueError(
            f"{path}: no extra.pairs — re-run validation/verify/run_null_model.py "
            "(per-pair records were added for G-REBIND)"
        )
    corpus = str(data.get("label", Path(path).stem))
    return [
        PairRecord(
            author=str(p["baseline_author"]),
            genuine=p["baseline_author"] == p["submission_author"],
            deviation=float(p["deviation"]),
            llr=float(p["llr"]),
            corpus=corpus,
        )
        for p in pairs
    ]


def split_by_author(
    records: list[PairRecord], seed: int, derivation_frac: float = 0.6
) -> tuple[list[PairRecord], list[PairRecord]]:
    """Split by (corpus, author) group; refuse if an author name lands on both
    sides (the same writer filed under two corpora would leak across)."""
    groups = sorted({(r.corpus, r.author) for r in records})
    random.Random(seed).shuffle(groups)
    n_deriv = round(len(groups) * derivation_frac)
    deriv_keys = set(groups[:n_deriv])
    derivation = [r for r in records if (r.corpus, r.author) in deriv_keys]
    holdout = [r for r in records if (r.corpus, r.author) not in deriv_keys]
    shared = {r.author for r in derivation} & {r.author for r in holdout}
    if shared:
        raise ValueError(f"author(s) on both sides of the split: {sorted(shared)}")
    return derivation, holdout


def _lowest_cut(genuine_llr: list[float], candidates: list[float], max_fpr: float) -> float:
    n = len(genuine_llr)
    for c in candidates:
        if sum(1 for g in genuine_llr if g >= c) / n <= max_fpr:
            return c
    raise AssertionError("unreachable: last candidate admits no genuine pair")  # pragma: no cover


def select_thresholds(
    derivation: list[PairRecord], max_fpr: float = 0.05
) -> dict[str, tuple[float, float]]:
    """Cut-offs from the derivation split only. schedule_conversation is the
    lowest llr value with genuine false-alarm rate <= max_fpr; escalate the
    same at max_fpr / 5; monitor sits 0.15 below schedule_conversation."""
    genuine = [r.llr for r in derivation if r.genuine]
    if not genuine:
        raise ValueError("select_thresholds needs at least one genuine record")
    # A cut just above the largest genuine value always admits zero of them.
    above_max = max(genuine) + 1e-9
    candidates = sorted({r.llr for r in derivation} | {above_max})
    sc = _lowest_cut(genuine, candidates, max_fpr)
    esc = _lowest_cut(genuine, candidates, max_fpr / 5)
    mon = max(sc - MONITOR_OFFSET, 0.0)
    return {
        "no_action": (0.0, mon),
        "monitor": (mon, sc),
        "schedule_conversation": (sc, esc),
        "escalate": (esc, max(esc, 1.0)),
    }


def _action(r: PairRecord, mode: str, thresholds) -> str:
    if mode == "rebind":
        return _rebind_action(r.llr, thresholds)
    if mode == "gate":
        base = _rebind_action(r.deviation, ACTION_THRESHOLDS)
        return _llr_action_candidates(base, r.deviation, r.llr)["gate"]
    raise ValueError(f"unknown mode: {mode!r}")


def _share(actions: list[str], hit) -> float | None:
    return sum(1 for a in actions if hit(a)) / len(actions) if actions else None


def rates(records: list[PairRecord], mode: str, thresholds) -> dict:
    gen = [_action(r, mode, thresholds) for r in records if r.genuine]
    imp = [_action(r, mode, thresholds) for r in records if not r.genuine]
    return {
        "catch_sc": _share(imp, lambda a: a in _SC_PLUS),
        "fa_sc": _share(gen, lambda a: a in _SC_PLUS),
        "fa_esc": _share(gen, lambda a: a == "escalate"),
        "n_genuine": len(gen),
        "n_impostor": len(imp),
    }
