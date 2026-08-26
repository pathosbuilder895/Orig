"""Three-valued TermSim gates over deployment metrics."""
from __future__ import annotations


def _result(passed: bool | None, reason: str) -> dict:
    verdict = "uninformative" if passed is None else ("pass" if passed else "fail")
    return {"verdict": verdict, "passed": passed is True, "reason": reason}


def evaluate_t1(schedule_rate, escalate_rate, n) -> dict:
    if n < 8:
        return _result(None, "need at least 8 honest students")
    return _result(schedule_rate <= 0.10 and escalate_rate <= 0.02,
                   "honest-term action budget")


def evaluate_t2(caught_rate, n) -> dict:
    if n < 5:
        return _result(None, "need at least 5 ghost scenarios")
    return _result(caught_rate >= 0.60, "ghost detection floor")


def evaluate_t3(growth_slope, n, bound=0.01) -> dict:
    if n < 5:
        return _result(None, "need at least 5 accreting honest students")
    return _result(abs(growth_slope) < bound, "baseline-growth neutrality")


def evaluate_t4(coldstart_rate, honest_rate, n) -> dict:
    if n < 8:
        return _result(None, "need at least 8 cold-start students")
    return _result(coldstart_rate <= 2 * max(honest_rate, 1 / n), "cold-start parity")
