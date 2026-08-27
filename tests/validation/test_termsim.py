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
    first = generate(20260826, cohort_sizes=(24,))
    second = generate(20260826, cohort_sizes=(24,))
    assert dumps(first) == dumps(second)
    assert script_hash(first) == script_hash(second)
    # One tenant per cohort, scenarios mixed within it per SCENARIO_PATTERN.
    assert {e["tenant"] for e in first} == {"termsim-cohort-24"}
    cold = [e for e in first if e["scenario"] == "COLDSTART" and e["kind"] == "baseline"]
    # COLDSTART alternates 1/2 onboarding baselines per coldstart ordinal.
    assert len(cold) == 6
    counts = {student: sum(e["student"] == student for e in cold)
              for student in {e["student"] for e in cold}}
    assert sorted(counts.values()) == [1, 1, 2, 2]
    hybrid = [e for e in first if e["scenario"] == "HYBRID" and e["kind"] == "score"]
    assert hybrid and all(e["proxy"] is True for e in hybrid)
    changed = [e for e in first if e.get("onset_week") is not None]
    assert all(5 <= e["onset_week"] <= 9 for e in changed)
    # Home submissions never reuse an onboarding draw from the same pool.
    honest_home = [e for e in first if e["scenario"] == "HONEST"
                   and e["kind"] == "score" and e["doc_role"] == "home"]
    assert honest_home and all(e["doc_number"] >= 3 for e in honest_home)


def test_persona_scripts_swap_sources_and_resolve_committed_text():
    manifest = build_manifest()
    personas = manifest["personas"][:12]
    events = generate(20260826, cohort_sizes=(24,), personas=personas)
    ghost_after = [e for e in events if e["scenario"] == "GHOST" and e.get("after_onset")]
    assert ghost_after and all(e["source_persona"] != e["persona"] for e in ghost_after)
    # TRANSFER is the SAME author writing from a held-out work — never a
    # different persona (that would be GHOST all term, not a transfer).
    transfer = [e for e in events if e["scenario"] == "TRANSFER" and e["kind"] == "score"]
    assert transfer
    assert all(e["source_persona"] == e["persona"] for e in transfer)
    assert all(e["doc_role"] == "away" for e in transfer)
    assert all(not e["genre_covered_by_baseline"] for e in transfer)
    multi = {p["id"] for p in personas if p["n_groups"] >= 2}
    assert all(e["persona"] in multi for e in transfer)
    # HONEST terms contain exactly the scripted mid-term curriculum shift.
    shifts = [e for e in events if e["scenario"] == "HONEST" and e.get("curriculum_shift")]
    assert shifts and all(e["doc_role"] == "away" for e in shifts)
    resolver = CorpusTextResolver(manifest)
    assert len(resolver(events[0]).split()) >= 300


def test_resolver_home_and_away_pools_are_disjoint_for_multiwork_personas():
    manifest = build_manifest()
    resolver = CorpusTextResolver(manifest)
    checked = 0
    for persona in manifest["personas"]:
        if persona["n_groups"] < 2:
            continue
        home, away = resolver._pools(persona)
        assert not set(home) & set(away)
        assert set(home) | set(away) == set(range(persona["n_docs"]))
        checked += 1
    assert checked >= 10


def test_mechanical_paraphrase_is_deterministic_prose():
    from validation.termsim.personas import _mechanical_paraphrase

    text = "First point made. Second point follows; with a caveat. Third — final — point."
    out = _mechanical_paraphrase(text)
    assert out == _mechanical_paraphrase(text)
    assert out != text
    assert sorted(out.replace(",", "").replace(".", "").split()) \
        == sorted(text.replace(";", "").replace(",", "").replace(".", "")
                  .replace("—", "").split())


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
         "doc_number": 0, "scenario": "HONEST", "authenticated": True},
        {"tenant": "t", "student": "t:s0", "week": 0, "kind": "baseline",
         "doc_number": 1, "scenario": "HONEST", "authenticated": True},
        {"tenant": "t", "student": "t:s0", "week": 1, "kind": "score",
         "doc_number": 2, "scenario": "HONEST"},
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
    events = generate(7, cohort_sizes=(4,), weeks=3, scenarios=("HONEST",))
    # The real feature pipeline needs submission-sized prose; repeated words
    # keep this smoke deterministic and cheap while still crossing its floors.
    def text_for(event):
        return (("Careful writers revise claims with evidence and context. " * 70)
                + str(event["doc_number"]))

    rows = run_events(live_client, events, text_for)
    scored = [row for row in rows if row["kind"] == "score"]
    assert len(scored) == 2
    assert all(row["action"] in {"no_action", "monitor", "schedule_conversation", "escalate"}
               for row in scored)
    assert all(row["baseline_count"] == 3 for row in scored)
    uploads = [row for row in rows if row["kind"] == "baseline"]
    assert len(uploads) == 6
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


def test_diff_direction_check_flags_gate_exceeding_shadow():
    from validation.termsim.scorecard import verify_diff_directions

    def cell(rate):
        return {"scenario_term_flag_probability": {"TRANSFER": {
            threshold: {"rate": rate, "n": 10}
            for threshold in ("monitor", "schedule_conversation", "escalate")}}}

    ok = verify_diff_directions({"baseline": cell(0.4), "llr-shadow": cell(0.5)})
    assert ok and all(c["ok"] for c in ok)
    bad = verify_diff_directions({"baseline": cell(0.6), "llr-shadow": cell(0.5)})
    assert bad and all(c["ok"] is False for c in bad)
    assert verify_diff_directions({"baseline": cell(0.4)}) == []


def test_gate_evidence_pools_seeds_without_merging_students(tmp_path):
    import json as json_module
    from validation.termsim.__main__ import pooled_gate_evidence

    for seed in ("seed-1", "seed-2"):
        seed_dir = tmp_path / seed
        seed_dir.mkdir()
        rows = [{"kind": "score", "student": "t:s0", "scenario": "HONEST", "week": 1,
                 "action": "schedule_conversation" if seed == "seed-1" else "no_action",
                 "baseline_count": 3, "deviation_score": 0.5}]
        (seed_dir / "baseline.jsonl").write_text(
            "".join(json_module.dumps(r) + "\n" for r in rows))
    payload = pooled_gate_evidence([tmp_path / "seed-1", tmp_path / "seed-2"])
    honest = payload["metrics"]["honest_term_flag_probability"]["schedule_conversation"]
    # Two seeds' students stay two students: one flagged of two.
    assert honest["n"] == 2
    assert honest["rate"] == 0.5


@pytest.mark.postgres
def test_runner_postgres_smoke(monkeypatch, store_reset):
    """The TermSim runner exercises the real Postgres persistence path.

    Skips (like every postgres-marked test) unless DATABASE_URL points at a
    reachable postgresql:// instance — `bash scripts/local_postgres.sh up`.
    """
    base_url = None
    import os
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("postgresql"):
        base_url = db_url
    if base_url is None:
        pytest.skip("no reachable Postgres — set DATABASE_URL to run this")
    from original.db import postgres_session
    from original.repository import reset_repository
    from validation.termsim.runner import create_postgres_schema, isolated_postgres_url

    try:
        cell_url = isolated_postgres_url(base_url, "pytest_smoke")
    except Exception as error:  # server present in env but unreachable
        pytest.skip(f"Postgres not reachable: {error}")
    monkeypatch.setenv("DATABASE_URL", cell_url)
    monkeypatch.setenv("REPO_BACKEND", "postgres")
    create_postgres_schema()
    reset_repository()
    try:
        from fastapi.testclient import TestClient
        import run as run_module

        client = TestClient(run_module.load_legacy_demo_app())
        events = generate(7, cohort_sizes=(4,), weeks=3, scenarios=("HONEST",))
        text = "Careful writers revise claims with evidence and context. " * 70
        rows = run_events(client, events, lambda event: text + str(event["doc_number"]))
        scored = [row for row in rows if row["kind"] == "score"]
        assert len(scored) == 2
        assert all(row["action"] in {"no_action", "monitor", "schedule_conversation",
                                     "escalate"} for row in scored)
    finally:
        reset_repository()
        postgres_session.reset_engine()
