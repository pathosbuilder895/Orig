"""
metrics.py — accuracy + calibration metrics on top of Original's outputs.

These are pure functions over ``(y_true, y_score)`` pairs. Nothing in here
re-computes a deviation, re-weights a feature, or knows about Original's
17-tier taxonomy. The functions consume the same numbers Original would
have returned to a live FastAPI client and report:

  - **Brier score** — mean squared error between predicted probability and
    the binary outcome. Lower is better; 0.0 is perfect, 0.25 is a
    coin-flip predictor that always says 0.5.

  - **Calibration curve (reliability diagram)** — 10 equal-frequency bins
    of predicted probability. For each bin, the mean predicted probability
    and the actual fraction of positives. A perfectly calibrated system
    sits on the diagonal: "70% confident" → 70% correct.

  - **Confusion at threshold** — TP/FP/TN/FN at any chosen threshold.
    Used to produce confusion matrices at the existing action thresholds
    (0.40 / 0.55 / 0.75).

  - **F1 at threshold** — harmonic mean of precision and recall at a
    chosen threshold. Single number that summarises the trade-off at the
    threshold the product will actually use.

CONVENTIONS — careful here:
  - ``y_true`` is 1 if the submission is genuinely from the claimed author
    (the "positive" class is AUTHENTIC, matching the ROC convention used
    in ``validation/calibration.py``).
  - ``y_score`` is the **probability the submission is authentic**. NOT
    the raw deviation_score (which is inverted: low = authentic). The
    canonical y_score for a ScoringResult is its ``.authorship_probability``
    field.

For helpers that derive y_true / y_score directly from a list of
``ScoringResult``, see ``arrays_from_results``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

# Late import — ScoringResult lives in calibration.py which is loaded at the
# top of the runner; this module stays import-cheap.
try:
    from validation.calibration import ScoringResult  # noqa: F401
except Exception:                                      # pragma: no cover
    ScoringResult = None    # type: ignore


# ── Conversion helpers ────────────────────────────────────────────────────────

def arrays_from_results(results) -> Tuple[np.ndarray, np.ndarray]:
    """
    Pull ``y_true`` (authentic = 1) and ``y_score`` (P(authentic)) arrays
    out of a list of ``ScoringResult``.

    Some callers will already have y_true / y_score arrays from a different
    source (e.g. a custom corpus) — they can call the metric functions
    directly with NumPy arrays and skip this helper.
    """
    y_true = np.array(
        [1 if r.is_same_author else 0 for r in results], dtype=np.int8
    )
    y_score = np.array([float(r.authorship_probability) for r in results], dtype=np.float64)
    return y_true, y_score


# ── Brier score ───────────────────────────────────────────────────────────────

def brier_score(y_true: Sequence[int], y_score: Sequence[float]) -> float:
    """
    Mean squared error between predicted probability and binary outcome.

    Perfect predictor: 0.0
    Always-0.5 baseline: 0.25
    Worst case (always-wrong-confident): 1.0
    """
    y_true = np.asarray(y_true, dtype=np.float64)
    y_score = np.asarray(y_score, dtype=np.float64)
    if y_true.shape != y_score.shape:
        raise ValueError(f"shape mismatch: y_true={y_true.shape} y_score={y_score.shape}")
    if y_true.size == 0:
        return float("nan")
    return float(np.mean((y_score - y_true) ** 2))


# ── Calibration curve (reliability diagram) ───────────────────────────────────

@dataclass(frozen=True)
class CalibrationBin:
    """One bin of the reliability diagram."""
    lower: float           # bin lower bound (inclusive)
    upper: float           # bin upper bound (exclusive, except last)
    count: int             # how many samples in this bin
    mean_predicted: float  # mean predicted probability in the bin
    fraction_positive: float  # fraction of those samples that were actually positive


def calibration_curve(
    y_true: Sequence[int],
    y_score: Sequence[float],
    n_bins: int = 10,
) -> List[CalibrationBin]:
    """
    Equal-width bin reliability diagram.

    For each of ``n_bins`` slices of [0, 1], compute the average predicted
    probability and the fraction of samples in the bin that were actually
    positive. Empty bins are omitted.

    A perfectly calibrated predictor sits on the diagonal
    ``mean_predicted == fraction_positive``. Bins above the diagonal are
    UNDER-confident (the predictor said "30%" but reality said 50%); bins
    below the diagonal are OVER-confident.

    Args:
        y_true: 1 for authentic, 0 otherwise.
        y_score: predicted probability of authentic ∈ [0, 1].
        n_bins: number of bins. 10 is the convention in the literature.

    Returns:
        List of CalibrationBin, sorted by ``lower`` ascending. Bins with
        count==0 are omitted from the output.
    """
    y_true = np.asarray(y_true, dtype=np.int8)
    y_score = np.asarray(y_score, dtype=np.float64)
    if y_true.shape != y_score.shape:
        raise ValueError(f"shape mismatch: y_true={y_true.shape} y_score={y_score.shape}")
    if y_true.size == 0:
        return []

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    out: List[CalibrationBin] = []
    for i in range(n_bins):
        lo = float(edges[i])
        hi = float(edges[i + 1])
        # Last bin is inclusive on the upper end so y_score == 1.0 lands in it.
        if i == n_bins - 1:
            mask = (y_score >= lo) & (y_score <= hi)
        else:
            mask = (y_score >= lo) & (y_score < hi)
        n = int(mask.sum())
        if n == 0:
            continue
        out.append(CalibrationBin(
            lower=lo,
            upper=hi,
            count=n,
            mean_predicted=float(y_score[mask].mean()),
            fraction_positive=float(y_true[mask].mean()),
        ))
    return out


# ── Confusion + F1 at a deviation threshold ───────────────────────────────────
#
# These take the RAW deviation_score (not the probability) so they match
# the convention used elsewhere in the codebase ("deviation < threshold →
# predicted authentic"). The thresholds are the action thresholds defined
# in original/constants.py:ACTION_THRESHOLDS.

@dataclass(frozen=True)
class ConfusionAtThreshold:
    """Confusion matrix at a single deviation threshold."""
    threshold: float
    tp: int
    fp: int
    tn: int
    fn: int

    @property
    def precision(self) -> float:
        return self.tp / max(1, self.tp + self.fp)

    @property
    def recall(self) -> float:
        return self.tp / max(1, self.tp + self.fn)

    @property
    def accuracy(self) -> float:
        total = self.tp + self.fp + self.tn + self.fn
        return (self.tp + self.tn) / max(1, total)

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 0.0 if (p + r) == 0 else 2 * p * r / (p + r)


def confusion_at_threshold(
    y_true: Sequence[int],
    deviation: Sequence[float],
    threshold: float,
) -> ConfusionAtThreshold:
    """
    Confusion matrix at a given deviation threshold.

    Decision rule: ``deviation < threshold`` → predicted **authentic**
    (positive class). This mirrors the convention in
    ``validation/calibration.py:_compute_threshold_metrics`` so the new
    metric is comparable with the existing ones.

    Args:
        y_true: 1 for authentic, 0 otherwise.
        deviation: raw deviation scores ∈ [0, 1] (LOW = authentic).
        threshold: deviation threshold below which we PREDICT authentic.
    """
    y_true = np.asarray(y_true, dtype=np.int8)
    dev = np.asarray(deviation, dtype=np.float64)
    pred = (dev < threshold).astype(np.int8)   # 1 = predicted authentic

    tp = int(((pred == 1) & (y_true == 1)).sum())
    fp = int(((pred == 1) & (y_true == 0)).sum())
    tn = int(((pred == 0) & (y_true == 0)).sum())
    fn = int(((pred == 0) & (y_true == 1)).sum())
    return ConfusionAtThreshold(threshold=threshold, tp=tp, fp=fp, tn=tn, fn=fn)


def f1_at_threshold(
    y_true: Sequence[int],
    deviation: Sequence[float],
    threshold: float,
) -> float:
    """F1 score at a deviation threshold. See ``confusion_at_threshold`` for the decision rule."""
    return confusion_at_threshold(y_true, deviation, threshold).f1


# ── Convenience: dictify for JSON reports ─────────────────────────────────────

def metrics_dict(
    y_true: Sequence[int],
    y_score_prob: Sequence[float],
    y_score_dev: Sequence[float],
    thresholds: Optional[Dict[str, float]] = None,
    n_calibration_bins: int = 10,
) -> Dict[str, object]:
    """
    Compute every metric in one call, return a JSON-serializable dict.

    Args:
        y_true: 1 if authentic, 0 otherwise.
        y_score_prob: predicted probability of authentic (for Brier + calibration).
        y_score_dev: raw deviation score (for confusion + F1 at thresholds).
        thresholds: dict of name → deviation threshold. Defaults to the
                    canonical action thresholds.
        n_calibration_bins: bins in the reliability diagram.
    """
    if thresholds is None:
        thresholds = {"no_action": 0.40, "monitor": 0.55, "escalate": 0.75}

    cal = calibration_curve(y_true, y_score_prob, n_bins=n_calibration_bins)
    conf = {
        name: confusion_at_threshold(y_true, y_score_dev, t)
        for name, t in thresholds.items()
    }
    return {
        "brier": brier_score(y_true, y_score_prob),
        "calibration_curve": [
            {
                "lower": b.lower,
                "upper": b.upper,
                "count": b.count,
                "mean_predicted": round(b.mean_predicted, 4),
                "fraction_positive": round(b.fraction_positive, 4),
            }
            for b in cal
        ],
        "threshold_metrics": {
            name: {
                "threshold": c.threshold,
                "tp": c.tp,
                "fp": c.fp,
                "tn": c.tn,
                "fn": c.fn,
                "precision": round(c.precision, 4),
                "recall": round(c.recall, 4),
                "accuracy": round(c.accuracy, 4),
                "f1": round(c.f1, 4),
            }
            for name, c in conf.items()
        },
    }
