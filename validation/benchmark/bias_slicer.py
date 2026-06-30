"""
bias_slicer.py — group results by manifest field, compute per-group metrics.

The doc/calibration audit (docs/calibration/norm_bounds_calibration_2026-03-17.md)
already warned that Tier 1 features pose **high bias risk** for non-native
English speakers: NNE-simulated texts scored 0.45–0.61 on lexical diversity
vs native 0.64–0.76. We need a permanent check that surfaces that risk in
every benchmark report.

This module groups a ``CalibrationReport.results`` list by manifest fields
(``native_english``, ``ai_provider``, ``theological_tradition``, plus
length buckets) and reports per-group:

  - sample count
  - mean deviation score
  - AUC within the group (vs out-of-group baseline)
  - false-positive rate (how often this group's AUTHENTIC essays get flagged)

A healthy system has roughly equal per-group AUCs. Big spreads = bias to
investigate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

from .metrics import arrays_from_results


@dataclass(frozen=True)
class BiasSlice:
    """One slice of the bias audit."""
    field: str          # "native_english" | "ai_provider" | "theological_tradition" | "word_count_bucket"
    value: str          # the group value (e.g. "true", "claude", "Reformed", "1000-2000")
    count: int
    mean_deviation: float
    std_deviation: float
    auc_in_group: float    # AUC computed on essays IN this group only
    false_positive_rate: float   # P(deviation>=0.55 | authentic AND in this group)


# ── Slicers (one per field) ──────────────────────────────────────────────────

def _value_of(entry, field: str) -> Optional[str]:
    """Pull a manifest field off a ScoringResult, normalised to a string."""
    # ScoringResult doesn't carry every manifest field on it directly. The
    # bias slicer therefore takes a separate ``manifest_lookup`` parameter
    # in slice_by(); _value_of pulls from there.
    raise NotImplementedError   # see slice_by()


def slice_by(
    results,
    field: str,
    *,
    manifest_lookup: Optional[Dict[str, dict]] = None,
    bucketer: Optional[Callable[[object], str]] = None,
    flag_threshold: float = 0.55,
) -> List[BiasSlice]:
    """
    Group ``results`` by ``field`` and compute per-group metrics.

    Args:
        results: list of ScoringResult.
        field: "native_english" | "ai_provider" | "theological_tradition" |
               "word_count_bucket" | any custom field name accessible via
               manifest_lookup.
        manifest_lookup: dict mapping ``filename -> {field: value, …}`` so
               we can look up fields that aren't carried on ScoringResult.
               For ``word_count_bucket`` we use the ScoringResult.word_count
               directly and ignore manifest_lookup.
        bucketer: optional function mapping the raw value → display bucket.
               Used for ``word_count_bucket`` — see WORD_COUNT_BUCKETER.
        flag_threshold: deviation threshold at or above which an essay is
               considered "flagged" by the system. Default 0.55 (the
               "monitor" action threshold).

    Returns:
        Sorted list of BiasSlice, one per group, alphabetical by group value.
    """
    if manifest_lookup is None:
        manifest_lookup = {}

    # Build groups.
    groups: Dict[str, list] = {}
    for r in results:
        if field == "word_count_bucket":
            val = WORD_COUNT_BUCKETER(r.word_count)
        else:
            entry = manifest_lookup.get(r.filename, {})
            raw = entry.get(field)
            if raw is None:
                val = "unknown"
            elif bucketer is not None:
                val = bucketer(raw)
            else:
                val = str(raw).lower() if isinstance(raw, bool) else str(raw)
        groups.setdefault(val, []).append(r)

    # Per-group metrics.
    out: List[BiasSlice] = []
    for value, items in groups.items():
        devs = np.array([r.deviation_score for r in items], dtype=np.float64)
        if devs.size == 0:
            continue
        y_true_g, y_prob_g = arrays_from_results(items)
        auc = _auc(y_true_g, y_prob_g)

        # FPR: fraction of authentic essays flagged in this group
        authentic_mask = y_true_g == 1
        if authentic_mask.any():
            flagged = ((np.asarray([r.deviation_score for r in items], dtype=np.float64) >= flag_threshold) & authentic_mask).sum()
            fpr = float(flagged) / float(authentic_mask.sum())
        else:
            fpr = float("nan")

        out.append(BiasSlice(
            field=field,
            value=value,
            count=int(devs.size),
            mean_deviation=round(float(devs.mean()), 4),
            std_deviation=round(float(devs.std()), 4),
            auc_in_group=round(float(auc), 4),
            false_positive_rate=round(fpr, 4) if not np.isnan(fpr) else float("nan"),
        ))
    out.sort(key=lambda b: b.value)
    return out


# ── Common bucketers ────────────────────────────────────────────────────────

def WORD_COUNT_BUCKETER(wc: int) -> str:
    """Bucket a word count into a coarse range for bias slicing."""
    if wc < 500:    return "<500"
    if wc < 1000:   return "500-1000"
    if wc < 2000:   return "1000-2000"
    if wc < 3000:   return "2000-3000"
    return "3000+"


# ── AUC helper (pure NumPy — sklearn would do, but we keep deps light) ───────

def _auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    """Compute AUC via the trapezoidal rule. Robust to tied scores."""
    if y_true.size == 0 or y_score.size == 0:
        return 0.5
    order = np.argsort(-y_score, kind="mergesort")
    y_sorted = y_true[order]
    P = float(y_sorted.sum())
    N = float(y_sorted.size - P)
    if P == 0 or N == 0:
        return 0.5
    tps = np.cumsum(y_sorted)
    fps = np.cumsum(1 - y_sorted)
    tpr = np.concatenate([[0.0], tps / P])
    fpr = np.concatenate([[0.0], fps / N])
    return float(np.trapz(tpr, fpr))
