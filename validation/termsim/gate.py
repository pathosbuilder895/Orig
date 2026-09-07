"""Three-valued TermSim gates over deployment metrics.

All bars here are PROVISIONAL (same convention as the typicality
thresholds): they exist to catch regressions on identical scripts, not to
certify absolute rates — TermSim's personas are corpus-derived synthetic
students and its honesty header says exactly that.
"""
from __future__ import annotations

# The fused compression channel's measured baseline-volume confound (C1,
# 2026-08 fix pass; reproduced by tests/test_fusion_confound.py): distance
# 0.799 at 3 baselines -> 0.730 at 48, i.e. -0.0016 score units per
# accumulated baseline, independent of anything about the submission. T-3's
# bound is calibrated BELOW that magnitude so this known-bad channel fails
# the gate when wired in — it is the gate's registered failure witness.
FUSED_COMPRESSION_SLOPE = -0.0016
GROWTH_SLOPE_BOUND = 0.001


def _result(passed: bool | None, reason: str) -> dict:
    verdict = "uninformative" if passed is None else ("pass" if passed else "fail")
    return {"verdict": verdict, "passed": passed is True, "reason": reason}


def evaluate_t1(schedule_rate, escalate_rate, n) -> dict:
    """Honest-term action budget: schedule <=10%, escalate <=2% (provisional)."""
    if n < 8:
        return _result(None, "need at least 8 honest students")
    return _result(schedule_rate <= 0.10 and escalate_rate <= 0.02,
                   "honest-term action budget")


def evaluate_t2(caught_rate, n) -> dict:
    """GHOST caught-by-term-end >=60% at monitor+ (provisional)."""
    if n < 5:
        return _result(None, "need at least 5 ghost scenarios")
    return _result(caught_rate >= 0.60, "ghost detection floor")


def evaluate_t3(growth_slope, n, bound=GROWTH_SLOPE_BOUND) -> dict:
    """Baseline-growth neutrality: |slope| below the fused-confound magnitude.

    The bound is deliberately tighter than the measured fused compression
    slope (see FUSED_COMPRESSION_SLOPE) — a score that moves as fast as the
    known-bad channel purely because the baseline grew is exactly what this
    gate exists to refuse.
    """
    if n < 5:
        return _result(None, "need at least 5 accreting honest students")
    return _result(abs(growth_slope) < bound, "baseline-growth neutrality")


def evaluate_t4(coldstart_rate, honest_rate, n) -> dict:
    """Cold-start parity: coldstart honest-term rate <=2x HONEST's (provisional)."""
    if n < 8:
        return _result(None, "need at least 8 cold-start students")
    return _result(coldstart_rate <= 2 * max(honest_rate, 1 / n), "cold-start parity")
