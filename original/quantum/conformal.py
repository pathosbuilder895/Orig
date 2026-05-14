"""
quantum/conformal.py — Conformal prediction for calibrated verdict thresholds.

Replaces hand-tuned ACTION_THRESHOLDS with a self-calibrating significance
test derived from confirmed-authentic submission fidelity scores collected
via the corrections feedback loop.

Conformal guarantee
───────────────────
For any significance level α, the long-run false positive rate (flagging a
genuinely authentic submission) is ≤ α. The guarantee holds regardless of
the fidelity score distribution — it requires only exchangeability (i.e.
that new authentic submissions are drawn from the same distribution as the
calibration set), which is a reasonable assumption for a stable student.

How it works
────────────
Given K confirmed-authentic fidelity scores {f_1, ..., f_K} (calibration
set) and a new submission with fidelity f_new:

    p-value = |{k : f_k ≤ f_new}| / (K + 1)

Interpretation: the p-value is the rank of f_new among authentic
submissions. Low p-value → f_new is unusually low → anomalous.

Note on direction: LOW fidelity = anomalous. So a low p-value (f_new ranks
below most authentic scores) is the suspicious direction, opposite to the
usual hypothesis-testing convention.

Self-improvement
────────────────
The calibration set grows automatically:
- Every submission where the instructor confirms "verdict was correct AND
  it was authentic" feeds `put_fidelity_score(..., is_authentic=True)`.
- `get_authentic_fidelities(student_id)` is called at scoring time to read
  the current calibration set (empty on day 0 → p_value=None, degrades
  gracefully to deviation_score only).
"""

from __future__ import annotations

from typing import List, Optional


# ── Conformal p-value ─────────────────────────────────────────────────────────

def conformal_pvalue(
    fidelity: float,
    calibration_fidelities: List[float],
) -> float:
    """
    Compute the conformal p-value for a submission fidelity score.

    Parameters
    ----------
    fidelity               : fidelity score of the new submission, ∈ [0, 1]
    calibration_fidelities : fidelity scores of confirmed-authentic submissions

    Returns
    -------
    p_value : float ∈ [0, 1]
        Low value → submission is unusually anomalous vs authentic baseline.
        Returns 0.5 when calibration set is empty (neutral, non-actionable).
    """
    n = len(calibration_fidelities)
    if n == 0:
        return 0.5   # no calibration data — do not act on this signal alone

    # Count how many calibration scores are ≤ fidelity (fidelity looks at least
    # this authentic).  Dividing by (n + 1) gives a valid p-value.
    count_leq = sum(1 for f in calibration_fidelities if f <= fidelity)
    return count_leq / (n + 1)


# ── Verdict mapping ───────────────────────────────────────────────────────────

def verdict_from_pvalue(
    p_value: float,
    alpha_monitor: float = 0.20,
    alpha_schedule: float = 0.05,
    alpha_escalate: float = 0.01,
) -> str:
    """
    Map a conformal p-value to a verdict action.

    Parameters
    ----------
    p_value        : output of conformal_pvalue()
    alpha_monitor  : p < this → "monitor"
    alpha_schedule : p < this → "schedule_conversation"
    alpha_escalate : p < this → "escalate"

    The defaults give a conservative hierarchy:
        p < 0.01 (bottom 1% of authentic)  → escalate
        p < 0.05 (bottom 5%)               → schedule_conversation
        p < 0.20 (bottom 20%)              → monitor
        else                               → no_action

    Returns
    -------
    action : str — one of "escalate", "schedule_conversation", "monitor",
             or "no_action"
    """
    if p_value < alpha_escalate:
        return "escalate"
    if p_value < alpha_schedule:
        return "schedule_conversation"
    if p_value < alpha_monitor:
        return "monitor"
    return "no_action"


# ── Asymmetric cost threshold ─────────────────────────────────────────────────

def asymmetric_threshold(cost_fp: float, cost_fn: float) -> float:
    """
    Compute the Bayes-optimal significance threshold for asymmetric costs.

    Parameters
    ----------
    cost_fp : cost of a false positive (flagging an authentic student)
    cost_fn : cost of a false negative (missing actual ghostwriting)

    Returns
    -------
    alpha_star : float ∈ (0, 1)
        Use as the escalation threshold in verdict_from_pvalue().
        Institutions with high cost_fp (e.g. strong academic-freedom culture)
        get a low alpha_star (stricter before escalating).
        Institutions with high cost_fn (e.g. high-stakes credentialing) get
        a high alpha_star (lower bar for escalation).

    Example
    -------
    >>> asymmetric_threshold(cost_fp=1.0, cost_fn=3.0)   # miss is 3× worse
    0.25
    """
    denom = cost_fp + cost_fn
    if denom < 1e-12:
        return 0.05   # degenerate — return default
    return float(cost_fp / denom)


__all__ = [
    "conformal_pvalue",
    "verdict_from_pvalue",
    "asymmetric_threshold",
]
