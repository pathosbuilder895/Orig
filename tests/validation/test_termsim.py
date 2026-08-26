import pytest

from validation.termsim.gate import evaluate_t1, evaluate_t2, evaluate_t3, evaluate_t4
from validation.termsim.metrics import compute
from validation.termsim.script import dumps, generate, script_hash


def test_term_metrics_count_students_not_submissions():
    events = [
        {"kind": "score", "student": "a", "scenario": "HONEST", "week": 1,
         "action": "no_action", "baseline_count": 3, "deviation_score": 0.2},
        {"kind": "score", "student": "a", "scenario": "HONEST", "week": 3,
         "action": "schedule_conversation", "baseline_count": 4, "deviation_score": 0.3},
        {"kind": "score", "student": "b", "scenario": "HONEST", "week": 1,
         "action": "no_action", "baseline_count": 3, "deviation_score": 0.2},
    ]
    out = compute(events)
    assert out["honest_term_flag_probability"]["schedule_conversation"]["rate"] == 0.5
    assert out["honest_term_flag_probability"]["schedule_conversation"]["n"] == 2
    assert out["baseline_growth_slope"]["mean"] == pytest.approx(0.1)


def test_termsim_gate_failure_witnesses_and_power_floors():
    assert evaluate_t1(0.2, 0.0, 8)["verdict"] == "fail"
    assert evaluate_t2(0.2, 5)["verdict"] == "fail"
    assert evaluate_t3(0.03, 5)["verdict"] == "fail"
    assert evaluate_t4(0.5, 0.1, 8)["verdict"] == "fail"
    assert evaluate_t1(0.0, 0.0, 3)["verdict"] == "uninformative"


def test_term_script_is_seeded_and_scenario_constraints_hold():
    first = generate(20260826, cohort_sizes=(8,))
    second = generate(20260826, cohort_sizes=(8,))
    assert dumps(first) == dumps(second)
    assert script_hash(first) == script_hash(second)
    cold = [e for e in first if e["scenario"] == "COLDSTART" and e["kind"] == "baseline"]
    assert len(cold) == 2
    hybrid = [e for e in first if e["scenario"] == "HYBRID" and e["kind"] == "score"]
    assert hybrid and all(e["proxy"] is True for e in hybrid)
    changed = [e for e in first if e.get("onset_week") is not None]
    assert all(5 <= e["onset_week"] <= 9 for e in changed)
