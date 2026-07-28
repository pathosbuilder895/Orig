"""
quantum/typicality.py — two-sided conformal typicality for per-student
leave-one-out distance distributions.

Distinct from ``original.quantum.conformal`` (which computes a one-sided
p-value from ``quantum_fidelity`` against an instructor-confirmed feedback
calibration set — a different axis, a different calibration mechanism, and
gated behind ``AMPLITUDE_SCORING_ENABLED``). This module answers: "how
typical is this submission's distance-from-baseline, relative to the
student's own held-out baseline samples?" — on BOTH tails.

Given a student's leave-one-out distance distribution {r_1 … r_N} (each
r_i = the rms_z of baseline sample i against baseline statistics built
from the other N-1 samples) and a submission distance r_sub:

    p_far     = (1 + #{i : r_i >= r_sub}) / (N + 1)   # drift side
    p_central = (1 + #{i : r_i <= r_sub}) / (N + 1)   # too-perfect side

Both are conformal p-values in the standard sense (Vovk et al.): under
exchangeability, uniform on {1/(N+1), ..., 1} for a genuinely-authentic
r_sub. They are complementary, not independent — a single rank position
determines both. The quantization floor 1/(N+1) means neither p-value can
ever fall below that value regardless of how extreme r_sub is; see
docs/superpowers/specs/2026-07-28-two-axis-verification-design.md §5 for
the reachability-vs-N table these thresholds were chosen against.
"""

from __future__ import annotations

# Initial band constants. Provisional — the calibration-gate runner
# (validation/calibration_gate.py, gate G1) re-derives these empirically;
# they are chosen here only so that a+b == 0.05, satisfying G1's ≤5%
# same-author flagged-rate budget by construction. See the spec §4/§5.
NO_ACTION_FAR_THRESHOLD = 0.03
NO_ACTION_CENTRAL_THRESHOLD = 0.02
MONITOR_FAR_THRESHOLD = 0.015
SCHEDULE_FAR_THRESHOLD = 0.005


def p_far(r_sub: float, loo_distances: list[float]) -> float:
    """
    Conformal p-value for the "drift" tail: low p_far means r_sub is
    unusually far from the student's own baseline distances.

    Parameters
    ----------
    r_sub         : the submission's rms_z distance from baseline statistics.
    loo_distances : the student's N leave-one-out distances {r_1 ... r_N}.

    Returns
    -------
    p_far ∈ [1/(N+1), 1.0].
    """
    n = len(loo_distances)
    if n == 0:
        raise ValueError("p_far: loo_distances must be non-empty")
    count_geq = sum(1 for r in loo_distances if r >= r_sub)
    return (1 + count_geq) / (n + 1)


def p_central(r_sub: float, loo_distances: list[float]) -> float:
    """
    Conformal p-value for the "too-perfect" tail: low p_central means
    r_sub is unusually close to the student's own baseline distances —
    the signature of mean-reverting, low-variance text (LLM output,
    cautious forgeries). See defect 2 in the design spec.

    Returns
    -------
    p_central ∈ [1/(N+1), 1.0].
    """
    n = len(loo_distances)
    if n == 0:
        raise ValueError("p_central: loo_distances must be non-empty")
    count_leq = sum(1 for r in loo_distances if r <= r_sub)
    return (1 + count_leq) / (n + 1)


def band_from_p(p_far: float, p_central: float) -> str:
    """
    Map the two-sided typicality p-values to an action band.

    An authentic submission sits near its own median distance, so
    p_far ≈ p_central ≈ 0.5 and this returns "no_action" regardless of N —
    that part of the mapping is correct at every N. The finer drift bands
    (monitor/schedule_conversation/escalate) require N large enough to
    resolve the corresponding threshold (see typicality.py's module
    docstring and spec §5) — below that N, p_far can never fall low enough
    to leave "no_action" via this function alone; escalation at small N
    continues to depend on the separate rms_z >= 3 catastrophic override
    in scoring.py, which this module does not compute.
    """
    if p_central <= NO_ACTION_CENTRAL_THRESHOLD:
        return "schedule_conversation"
    if p_far <= SCHEDULE_FAR_THRESHOLD:
        return "escalate"
    if p_far <= MONITOR_FAR_THRESHOLD:
        return "schedule_conversation"
    if p_far <= NO_ACTION_FAR_THRESHOLD:
        return "monitor"
    return "no_action"


__all__ = ["p_far", "p_central", "band_from_p"]
