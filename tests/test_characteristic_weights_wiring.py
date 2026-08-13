"""
CHARACTERISTIC_WEIGHTS production-wiring test (students_scoring.py).

The characteristic factor is sigma_null / baseline_std, so the mechanism is
dead without the same-tenant impostor pool. students_scoring.py therefore
builds that pool when

    null_model == "impostor" OR characteristic_weights != "off"

and the second half of that condition is the whole reason the flag is not
inert on a plain production deploy (demo mode sets NULL_MODEL=impostor; a
bare deploy does not). Nothing else covers it: tests/test_flag_matrix.py
re-implements the wiring in its own helper, and score() itself is happy to
abstain silently. Revert the `or` clause and the flag goes quietly inert on
every non-demo deployment with a fully green suite — the exact failure mode
CLAUDE.md records for GENRE_INVARIANT_WEIGHTS_ENABLED, arriving through the
wiring instead of the classifier.

These tests drive the real HTTP endpoint, so they also cover the hand-rolled
_to_response copies that carry the audit fields out to the API response.
"""

import numpy as np
import pytest
from fastapi.testclient import TestClient

import run  # repo-root launcher
from original import principal as pr
from original.constants import FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState
from original.repository import get_repository

app = run.load_legacy_demo_app()
client = TestClient(app)

# null_pool floors: >= 3 contributing peers and >= 5 pooled vectors.
_N_PEERS = 3
_PEER_SAMPLES = 2


def _auth(token: str):
    return {"Authorization": f"Bearer {token}"}


def _seed(student_id: str, n: int) -> None:
    rng = np.random.default_rng(abs(hash(student_id)) % (2**31))
    state = StudentState(student_id=student_id)
    for i in range(n):
        state.add_sample(
            BaselineSample(
                text=f"seed sample {i} for {student_id}",
                vector=np.clip(rng.normal(0.5, 0.08, FEATURE_DIM), 0.0, 1.0),
                provenance="instructor_verified",
                auth_weight=1.0,
                assignment=f"a{i}",
            )
        )
    get_repository().put(state)


@pytest.fixture
def charw_tenant():
    """A fresh pilot tenant holding one scored student and enough peers to
    clear null_pool's cold-start floors."""
    client.post(
        "/tenants",
        json={"tenant_id": "charw", "name": "Characteristic Seminary", "environment": "pilot"},
    )
    _seed("charw:scored_student", 5)
    for k in range(_N_PEERS):
        _seed(f"charw:peer{k}", _PEER_SAMPLES)
    return pr.mint_principal_token("prof_charw", "professor", "charw")


def _score(token: str, sid: str = "charw:scored_student"):
    r = client.post(
        f"/students/{sid}/score",
        json={
            "text": (
                "A short new submission written for the characteristic-weighting "
                "wiring check, long enough to produce a usable feature vector."
            )
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_pool_is_built_for_characteristic_weights_without_null_model(charw_tenant, monkeypatch):
    """NULL_MODEL unset (the bare-deploy default) + CHARACTERISTIC_WEIGHTS=shadow.

    characteristic_mode is None whenever the mechanism ABSTAINED, and the
    only abstention reachable here is a missing impostor pool — so
    characteristic_mode == "shadow" in the response is exactly the assertion
    that the `or characteristic_weights != "off"` clause ran.
    """
    monkeypatch.delenv("NULL_MODEL", raising=False)
    monkeypatch.setenv("CHARACTERISTIC_WEIGHTS", "shadow")

    body = _score(charw_tenant)

    assert body["characteristic_mode"] == "shadow", (
        "the impostor pool was not built — CHARACTERISTIC_WEIGHTS is inert on "
        "any deploy that has not also set NULL_MODEL=impostor"
    )
    assert body["characteristic_factor_dispersion"] is not None
    assert body["characteristic_deviation_preview"] is not None
    # Shadow stays attach-only end to end: the llr route is gated on
    # null_model independently, so handing score() a pool changes nothing else.
    assert body["characteristic_weighting_applied"] is False
    assert body["authorship"]["llr_deviation_score"] is None


def test_pool_is_not_built_when_both_flags_are_off(charw_tenant, monkeypatch):
    """The condition must stay a condition. Spying on the builder is what
    separates 'the `or` clause works' from 'the pool is now built
    unconditionally', which would put a full all_states() scan on every
    scoring request of every flags-off deployment."""
    monkeypatch.delenv("NULL_MODEL", raising=False)
    monkeypatch.delenv("CHARACTERISTIC_WEIGHTS", raising=False)

    calls: list[str] = []
    real = __import__("original.quantum.null_pool", fromlist=["build_impostor_stats"])
    original_builder = real.build_impostor_stats

    def _spy(claimed_student_id, states):
        calls.append(claimed_student_id)
        return original_builder(claimed_student_id, states)

    monkeypatch.setattr(real, "build_impostor_stats", _spy)

    body = _score(charw_tenant)

    assert calls == []
    assert body["characteristic_mode"] is None
    assert body["characteristic_weighting_applied"] is False


def test_pool_is_still_built_for_the_null_model_alone(charw_tenant, monkeypatch):
    """The other half of the `or`: NULL_MODEL=impostor with the new flag off
    must keep building the pool exactly as it did before."""
    monkeypatch.setenv("NULL_MODEL", "impostor")
    monkeypatch.delenv("CHARACTERISTIC_WEIGHTS", raising=False)

    body = _score(charw_tenant)

    assert body["authorship"]["llr_deviation_score"] is not None
    assert body["characteristic_mode"] is None
