import pytest

from validation.termsim.gate import evaluate_t1, evaluate_t2, evaluate_t3, evaluate_t4
from validation.termsim.matrix import cells
from validation.termsim.metrics import compute
from validation.termsim.personas import CorpusTextResolver, build_manifest
from validation.termsim.runner import install_vector_cache, run_events
from validation.termsim.scorecard import HONESTY, build, markdown
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
    assert len(cold) == 16
    assert all(sum(e["student"] == student for e in cold) == 2
               for student in {e["student"] for e in cold})
    hybrid = [e for e in first if e["scenario"] == "HYBRID" and e["kind"] == "score"]
    assert hybrid and all(e["proxy"] is True for e in hybrid)
    changed = [e for e in first if e.get("onset_week") is not None]
    assert all(5 <= e["onset_week"] <= 9 for e in changed)


def test_persona_scripts_swap_sources_and_resolve_committed_text():
    manifest = build_manifest()
    ids = [p["id"] for p in manifest["personas"][:12]]
    events = generate(20260826, cohort_sizes=(8,), persona_ids=ids)
    ghost_after = [e for e in events if e["scenario"] == "GHOST" and e.get("after_onset")]
    transfer = [e for e in events if e["scenario"] == "TRANSFER" and e["kind"] == "score"]
    assert ghost_after and all(e["source_persona"] != e["persona"] for e in ghost_after)
    assert transfer and all(not e["genre_covered_by_baseline"] for e in transfer)
    resolver = CorpusTextResolver(manifest)
    assert len(resolver(events[0]).split()) >= 300


class _CannedResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class _CannedClient:
    """Replays responses shaped exactly like the live Layer7OutputResponse.

    llr_deviation_score lives on authorship, inflation is
    topic_inflation_applied, and drift-gate holds are HTTP 202/409 on the
    baseline route — the fields a top-level .get() silently misses.
    """

    def __init__(self, baseline_statuses):
        self._baseline_statuses = list(baseline_statuses)

    def post(self, url, json=None, headers=None):
        if url == "/tenants":
            return _CannedResponse(201, {})
        if url.endswith("/baseline"):
            status = self._baseline_statuses.pop(0)
            body = {} if status == 200 else {
                "detail": {"status": "pending_review", "drift": {"recommendation": "flag_for_review"}}
            }
            return _CannedResponse(status, body)
        return _CannedResponse(200, {
            "recommendation": {"action": "no_action"},
            "authorship": {"deviation_score": 0.31, "llr_deviation_score": 0.42},
            "typicality_n": 4,
            "topic_distance": 0.12,
            "topic_inflation_applied": True,
            "fused_score": None,
        })


def test_runner_extracts_nested_fields_and_records_drift_holds():
    events = [
        {"tenant": "t", "student": "t:s0", "week": 0, "kind": "baseline",
         "document_index": 0, "scenario": "HONEST", "authenticated": True},
        {"tenant": "t", "student": "t:s0", "week": 0, "kind": "baseline",
         "document_index": 1, "scenario": "HONEST", "authenticated": True},
        {"tenant": "t", "student": "t:s0", "week": 1, "kind": "score",
         "document_index": 2, "scenario": "HONEST"},
    ]
    # Second onboarding upload is held by the drift gate (202) — the run
    # must record the hold and continue, not crash the cell.
    client = _CannedClient(baseline_statuses=[200, 202, 200])
    rows = run_events(client, events, lambda event: "text", accrete=True)
    holds = [r for r in rows if r["kind"] == "baseline"]
    assert [r["drift_gate_held"] for r in holds] == [False, True]
    scored = [r for r in rows if r["kind"] == "score"]
    assert len(scored) == 1
    row = scored[0]
    assert row["llr_deviation_score"] == 0.42
    assert row["null_abstained"] is False
    assert row["inflation_fired"] is True
    assert row["topic_distance"] == 0.12
    # Only the accepted onboarding upload counts toward the baseline.
    assert row["baseline_count"] == 1
    # The accrete re-upload was accepted, so it is recorded as unheld.
    accrete_rows = [r for r in rows if r["kind"] == "accrete"]
    assert [r["drift_gate_held"] for r in accrete_rows] == [False]


def test_runner_uses_live_api(live_client, store_reset):
    events = generate(7, cohort_sizes=(3,), weeks=3, scenarios=("HONEST",))
    # The real feature pipeline needs submission-sized prose; repeated words
    # keep this smoke deterministic and cheap while still crossing its floors.
    def text_for(event):
        return (("Careful writers revise claims with evidence and context. " * 70)
                + str(event["document_index"]))

    rows = run_events(live_client, events, text_for)
    scored = [row for row in rows if row["kind"] == "score"]
    assert len(scored) == 3
    assert all(row["action"] in {"no_action", "monitor", "schedule_conversation", "escalate"}
               for row in scored)
    assert all(row["baseline_count"] == 3 for row in scored)
    uploads = [row for row in rows if row["kind"] == "baseline"]
    assert len(uploads) == 9
    assert all(row["drift_gate_held"] in (True, False) for row in uploads)


def test_vector_cache_warm_and_cold_are_identical(tmp_path, monkeypatch):
    import numpy as np
    from original.features import pipeline
    from original.routers import students_scoring

    calls = []
    expected = np.arange(109, dtype=float)
    monkeypatch.setattr(pipeline, "feature_vector",
                        lambda text, keystroke_data=None: calls.append(text) or expected.copy())
    install_vector_cache(tmp_path)
    cold = students_scoring.feature_vector("same committed document")
    warm = students_scoring.feature_vector("same committed document")
    assert np.array_equal(cold, warm)
    assert calls == ["same committed document"]


def test_standard_matrix_and_scorecard_diff_are_explicit():
    matrix = cells()
    assert set(matrix) == {"baseline", "llr-shadow", "no-context", "topic-inflation",
                           "characteristic-weights", "genre-v2"}
    baseline = compute([])
    changed = compute([])
    baseline["honest_term_flag_probability"]["monitor"].update(rate=0.2, n=10)
    changed["honest_term_flag_probability"]["monitor"].update(rate=0.1, n=10)
    card = build("llr-shadow", 1, changed, matrix["llr-shadow"], baseline)
    assert card["diff_vs_baseline"]["monitor"] == pytest.approx(-0.1)
    assert HONESTY in markdown(card)
