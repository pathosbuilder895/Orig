"""The two-mode call site, and the invariant that makes it safe.

Contract:
  both flags off        -> field null, no row
  FUSED_SCORE_SHADOW=1  -> row persisted, field STILL null
  FUSED_SCORE_ENABLED=1 -> row persisted AND field populated
In all three states deviation_score, quantum_fidelity, and the recommended
action are byte-identical.

Response field paths were confirmed against the live OpenAPI schema
(Layer7OutputResponse) rather than guessed: deviation_score and
quantum_fidelity live under the nested "authorship" object, and the
recommended action lives under "recommendation.action" — there are no
top-level deviation_score / quantum_fidelity / recommended_action keys.

_seed_cohort also registers its tenant via POST /tenants (environment=
"demo") before creating any baselines. Anonymous requests resolve to the
demo principal (original/principal.py:resolve_principal), which is only
granted access to student ids whose tenant prefix is unregistered (None),
literally "demo", or registered with environment="demo"
(DEMO_VISIBLE_ENVIRONMENTS). A freshly-generated random tenant slug like
"wire<hex>:alice" is none of those until it is registered, so every
baseline/score call 403s with "Cross-tenant access denied" otherwise.
"""

from __future__ import annotations

import json
import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient

import original.store as store
import run
from original.constants import FEATURE_DIM

client = TestClient(run.load_legacy_demo_app())

_LONG = (
    "However, a reader might ask why these claims have been made; therefore we reply "
    "that the argument is careful and that it is also sound. "
) * 40


@pytest.fixture()
def fixture_artifact(tmp_path, monkeypatch):
    mu, sd, weights = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [1.0, 1.0, 1.0]
    payload = {
        "schema_version": 1,
        "channel_order": ["peer_centered_z", "compression", "function_word_network"],
        "mu": mu, "sd": sd, "weights": weights, "intercept": 0.0,
        "threshold_fa5": 0.5, "threshold_fa1": 1.5,
        "reference_inputs": [[0.1, 0.2, 0.3]],
        "reference_outputs": [float(np.dot([0.1, 0.2, 0.3], weights))],
        "provenance": {"dataset": "unit-test"},
    }
    path = tmp_path / "fused.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setenv("FUSED_SCORE_MODEL_PATH", str(path))
    from original.fusion import reset_for_tests

    reset_for_tests()
    yield
    reset_for_tests()


def _register_tenant(tenant: str) -> None:
    """Register *tenant* as environment="demo" so the anonymous demo
    principal (no auth header) can reach its students. See module docstring."""
    response = client.post(
        "/tenants", json={"tenant_id": tenant, "name": tenant, "environment": "demo"}
    )
    assert response.status_code == 201, response.text


def _seed_cohort(tenant: str) -> str:
    """One claimed student plus twelve peers, each with three long baselines."""
    _register_tenant(tenant)
    claimed = f"{tenant}:alice"
    for name in ["alice"] + [f"peer{i}" for i in range(12)]:
        student_id = f"{tenant}:{name}"
        for index in range(3):
            client.post(
                f"/students/{student_id}/baseline",
                json={"text": _LONG, "provenance": "proctored",
                      "assignment": f"{name}-{index}"},
            )
    return claimed


def _score(student_id: str) -> dict:
    response = client.post(
        f"/students/{student_id}/score",
        json={"text": _LONG, "submission_id": uuid.uuid4().hex},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_flags_off_means_no_field_and_no_row(fixture_artifact, monkeypatch):
    monkeypatch.delenv("FUSED_SCORE_ENABLED", raising=False)
    monkeypatch.delenv("FUSED_SCORE_SHADOW", raising=False)
    student_id = _seed_cohort(f"wire{uuid.uuid4().hex[:6]}")
    body = _score(student_id)
    assert body.get("fused_score") is None
    assert store.get_fused_scores(student_id) == []


def test_shadow_persists_without_attaching(fixture_artifact, monkeypatch):
    monkeypatch.delenv("FUSED_SCORE_ENABLED", raising=False)
    monkeypatch.setenv("FUSED_SCORE_SHADOW", "1")
    student_id = _seed_cohort(f"wire{uuid.uuid4().hex[:6]}")
    body = _score(student_id)
    assert body.get("fused_score") is None
    rows = store.get_fused_scores(student_id)
    assert len(rows) == 1
    assert rows[0]["band"] in {"consistent", "inconclusive", "divergent"}
    assert rows[0]["channels"]


def test_enabled_persists_and_attaches(fixture_artifact, monkeypatch):
    monkeypatch.setenv("FUSED_SCORE_ENABLED", "1")
    monkeypatch.delenv("FUSED_SCORE_SHADOW", raising=False)
    student_id = _seed_cohort(f"wire{uuid.uuid4().hex[:6]}")
    body = _score(student_id)
    attached = body.get("fused_score")
    assert attached is not None
    assert attached["band"] in {"consistent", "inconclusive", "divergent"}
    rows = store.get_fused_scores(student_id)
    assert len(rows) == 1
    # C1, 2026-08 fix pass: every persisted row must carry the baseline
    # volume it was scored against, so the compression channel's confound
    # (see CLAUDE.md's FUSED_SCORE_ENABLED caveat) can be regressed out of
    # the shadow data later.
    assert rows[0]["baseline_samples"] == 3
    assert rows[0]["reference_profiles"] == 8


@pytest.fixture()
def fixture_two_channel_artifact(tmp_path, monkeypatch):
    """Mirrors the shipped artifact's shape: only two of the three channels
    are fused (the ablation dropped function_word_network)."""
    mu, sd, weights = [0.0, 0.0], [1.0, 1.0], [1.0, 1.0]
    payload = {
        "schema_version": 1,
        "channel_order": ["peer_centered_z", "compression"],
        "mu": mu, "sd": sd, "weights": weights, "intercept": 0.0,
        "threshold_fa5": 0.5, "threshold_fa1": 1.5,
        "reference_inputs": [[0.1, 0.2]],
        "reference_outputs": [float(np.dot([0.1, 0.2], weights))],
        "provenance": {"dataset": "unit-test-2ch"},
    }
    path = tmp_path / "fused2.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setenv("FUSED_SCORE_MODEL_PATH", str(path))
    from original.fusion import reset_for_tests

    reset_for_tests()
    yield
    reset_for_tests()


def test_two_channel_artifact_still_persists_three_channel_values(
    fixture_two_channel_artifact, monkeypatch
):
    """I1, 2026-08 fix pass: the shipped artifact only fuses two channels,
    but function_word_network is computed on every call regardless (it costs
    a function-word matrix per reference either way) and must not be thrown
    away before persistence — that data is the only thing that can serve
    the spec's stated reason for keeping the channel ("revisit the ablation
    on real traffic"). The fused log-odds itself must still reflect only the
    two channels the model actually uses.
    """
    monkeypatch.setenv("FUSED_SCORE_ENABLED", "1")
    monkeypatch.delenv("FUSED_SCORE_SHADOW", raising=False)
    student_id = _seed_cohort(f"wire{uuid.uuid4().hex[:6]}")
    body = _score(student_id)
    attached = body.get("fused_score")
    assert attached is not None
    assert set(attached["channels"]) == {"peer_centered_z", "compression"}

    rows = store.get_fused_scores(student_id)
    assert len(rows) == 1
    assert set(rows[0]["channels"]) == {
        "peer_centered_z",
        "compression",
        "function_word_network",
    }


def test_report_only_invariant_across_all_three_flag_states(fixture_artifact, monkeypatch):
    """THE load-bearing test: the primary score never moves."""
    student_id = _seed_cohort(f"wire{uuid.uuid4().hex[:6]}")
    observed = []
    for enabled, shadow in (("0", "0"), ("0", "1"), ("1", "0")):
        monkeypatch.setenv("FUSED_SCORE_ENABLED", enabled)
        monkeypatch.setenv("FUSED_SCORE_SHADOW", shadow)
        body = _score(student_id)
        observed.append(
            (
                body["authorship"]["deviation_score"],
                body["authorship"]["quantum_fidelity"],
                body["recommendation"]["action"],
            )
        )
    assert observed[0] == observed[1] == observed[2], (
        f"fused score changed the primary result: {observed}"
    )


def test_a_persistence_failure_does_not_break_scoring(fixture_artifact, monkeypatch):
    monkeypatch.setenv("FUSED_SCORE_SHADOW", "1")
    monkeypatch.setattr(
        store, "put_fused_score",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    student_id = _seed_cohort(f"wire{uuid.uuid4().hex[:6]}")
    body = _score(student_id)
    assert "authorship" in body and "deviation_score" in body["authorship"]


def test_abstention_persists_nothing(fixture_artifact, monkeypatch):
    """A lone student has no peers, so the expert abstains and writes no row."""
    monkeypatch.setenv("FUSED_SCORE_SHADOW", "1")
    tenant = f"wire{uuid.uuid4().hex[:6]}"
    _register_tenant(tenant)
    student_id = f"{tenant}:solo"
    for index in range(3):
        client.post(
            f"/students/{student_id}/baseline",
            json={"text": _LONG, "provenance": "proctored", "assignment": f"solo-{index}"},
        )
    _score(student_id)
    assert store.get_fused_scores(student_id) == []
