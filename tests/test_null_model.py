"""
Null-model production wiring tests (NULL_MODEL=impostor).

Two layers:
  1. Unit — build_impostor_stats pools ONLY same-tenant peers, never the
     claimed student, and abstains (None) below the cold-start floors.
  2. API — /students/{id}/score attaches authorship.llr_deviation_score
     when the flag is on and a peer pool exists; stays null when the flag
     is off or the tenant is a cold start. deviation_score is NEVER touched
     by the null model. The recommended action is byte-identical to
     flag-off ONLY under llr_action_mode="shadow" (explicit opt-in); the
     default as of 2026-08 is "gate", which CAN downgrade the action one
     severity step on a confidently-genuine llr reading — see
     tests/quantum/test_llr_action_modes.py for that behavior and
     ScoringConfig.llr_action_mode's docstring (quantum/scoring.py) for why.
"""

import numpy as np
import pytest
from fastapi.testclient import TestClient

import run  # repo-root launcher
from original import principal as pr
from original.constants import FEATURE_DIM
from original.quantum.null_pool import (
    MIN_IMPOSTOR_STUDENTS,
    MIN_IMPOSTOR_VECTORS,
    build_impostor_stats,
)
from original.quantum.state import BaselineSample, StudentState

app = run.load_legacy_demo_app()
client = TestClient(app)

# ~140 words — comfortably above any baseline minimum. Per-student suffixes
# below keep the pooled vectors from being identical (sigma would floor).
BASE_TEXT = (
    "The doctrine of justification by faith stands at the center of the gospel. "
    "When Paul writes to the Romans, he labors to show that righteousness comes "
    "not by works of the law but through faith in Christ alone. This conviction "
    "shaped the Reformation and continues to shape pastoral practice today. "
    "A careful reader notices how the argument unfolds in stages, each building "
    "on the last, until the conclusion becomes unavoidable. The voice here is "
    "deliberate and measured, favoring long subordinate clauses and a vocabulary "
    "drawn from systematic theology. Such patterns, repeated across many essays, "
    "form a fingerprint as distinctive as handwriting. The seminary student who "
    "writes this way in September will, absent intervention, write this way in "
    "May, and that continuity is precisely what we set out to measure and to "
    "protect with patience and with care."
)

VARIANTS = [
    " Yet grace, once received, reorders every affection of the heart.",
    " Therefore the church confesses this truth in every generation anew.",
    " Consequently, pastors must teach with clarity, humility, and courage.",
    " Indeed, the history of doctrine bears witness to this same pattern.",
]


def _auth(token: str):
    return {"Authorization": f"Bearer {token}"}


def _mk_state(student_id: str, n_samples: int, seed: int) -> StudentState:
    rng = np.random.RandomState(seed)
    samples = [
        BaselineSample(
            text=f"sample {i}",
            vector=np.clip(rng.normal(0.5, 0.1, FEATURE_DIM), 0.0, 1.0),
            provenance="verified",
            auth_weight=1.0,
        )
        for i in range(n_samples)
    ]
    return StudentState(student_id=student_id, samples=samples)


# ── Unit: pool construction ───────────────────────────────────────────────────


def test_pool_excludes_claimed_student_and_other_tenants():
    states = [
        _mk_state("acme:target", 3, seed=1),
        _mk_state("acme:peer1", 2, seed=2),
        _mk_state("acme:peer2", 2, seed=3),
        _mk_state("acme:peer3", 2, seed=4),
        _mk_state("rival:outsider", 5, seed=5),  # other tenant — never pooled
    ]
    stats = build_impostor_stats("acme:target", states)
    assert stats is not None
    mu, sigma = stats
    assert mu.shape == (FEATURE_DIM,) and sigma.shape == (FEATURE_DIM,)
    assert np.all(sigma >= 0.005)

    # The pooled mean must equal the mean over EXACTLY the 6 peer vectors —
    # proving neither the target's own vectors nor the outsider's entered.
    peer_vecs = [s.vector for st in states[1:4] for s in st.samples]
    np.testing.assert_allclose(mu, np.stack(peer_vecs).mean(axis=0))


def test_pool_abstains_below_student_floor():
    # 2 peers ≥ 5 vectors — still None: MIN_IMPOSTOR_STUDENTS not met.
    states = [
        _mk_state("acme:target", 3, seed=1),
        _mk_state("acme:peer1", 3, seed=2),
        _mk_state("acme:peer2", 3, seed=3),
    ]
    assert MIN_IMPOSTOR_STUDENTS == 3
    assert build_impostor_stats("acme:target", states) is None


def test_pool_abstains_below_vector_floor():
    # 3 peers but only 3 total vectors < MIN_IMPOSTOR_VECTORS.
    states = [
        _mk_state("acme:target", 3, seed=1),
        _mk_state("acme:peer1", 1, seed=2),
        _mk_state("acme:peer2", 1, seed=3),
        _mk_state("acme:peer3", 1, seed=4),
    ]
    assert MIN_IMPOSTOR_VECTORS == 5
    assert build_impostor_stats("acme:target", states) is None


def test_unverified_samples_never_pooled():
    states = [
        _mk_state("acme:target", 3, seed=1),
        _mk_state("acme:peer1", 2, seed=2),
        _mk_state("acme:peer2", 2, seed=3),
        _mk_state("acme:peer3", 2, seed=4),
    ]
    for s in states[1].samples:
        s.auth_weight = 0.0  # unverified — excluded, dropping peer1 entirely
    assert build_impostor_stats("acme:target", states) is None


# ── API: flag-gated attach behaviour ──────────────────────────────────────────


@pytest.fixture(scope="module")
def cohort():
    """Pilot tenant with 4 students × 2 authenticated baselines each."""
    client.post(
        "/tenants",
        json={"tenant_id": "nullpool", "name": "Null Pool Seminary", "environment": "pilot"},
    )
    prof = pr.mint_principal_token("prof_nullpool", "professor", "nullpool")
    for i in range(4):
        sid = f"nullpool:student_{i}"
        for j in range(2):
            r = client.post(
                f"/students/{sid}/baseline",
                json={"text": BASE_TEXT + VARIANTS[i] * (j + 1), "assignment": f"a{j}"},
                headers=_auth(prof),
            )
            assert r.status_code == 200, r.text
    return prof


@pytest.fixture(scope="module")
def lone_student():
    """Pilot tenant with a single student — a cold start by definition."""
    client.post(
        "/tenants",
        json={"tenant_id": "nullsolo", "name": "Null Solo Seminary", "environment": "pilot"},
    )
    prof = pr.mint_principal_token("prof_nullsolo", "professor", "nullsolo")
    for j in range(3):
        r = client.post(
            "/students/nullsolo:only/baseline",
            json={"text": BASE_TEXT + VARIANTS[j], "assignment": f"a{j}"},
            headers=_auth(prof),
        )
        assert r.status_code == 200, r.text
    return prof


def _score(prof: str, sid: str):
    r = client.post(
        f"/students/{sid}/score",
        json={"text": BASE_TEXT + " A closing thought, offered plainly."},
        headers=_auth(prof),
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_flag_off_llr_is_null(cohort, monkeypatch):
    monkeypatch.delenv("NULL_MODEL", raising=False)
    body = _score(cohort, "nullpool:student_0")
    assert body["authorship"]["llr_deviation_score"] is None


def test_flag_on_llr_attached_deviation_score_never_touched(cohort, monkeypatch):
    monkeypatch.delenv("NULL_MODEL", raising=False)
    off = _score(cohort, "nullpool:student_0")

    monkeypatch.setenv("NULL_MODEL", "impostor")
    on = _score(cohort, "nullpool:student_0")

    llr = on["authorship"]["llr_deviation_score"]
    assert llr is not None and 0.0 <= llr <= 1.0
    # deviation_score itself is never touched by the null model, regardless
    # of llr_action_mode — only the recommended action can move, and only
    # under "gate"/"trigger"/"blend". See test_llr_action_modes.py for that.
    assert on["authorship"]["deviation_score"] == off["authorship"]["deviation_score"]


def test_flag_on_with_shadow_mode_action_untouched(cohort, monkeypatch):
    # llr_action_mode="shadow" is the explicit opt-in for the OLD attach-only
    # contract: the recommended action stays byte-identical to flag-off.
    # The default as of 2026-08 is "gate", which does not give this guarantee
    # (see tests/quantum/test_llr_action_modes.py).
    monkeypatch.delenv("NULL_MODEL", raising=False)
    monkeypatch.delenv("LLR_ACTION_MODE", raising=False)
    off = _score(cohort, "nullpool:student_0")

    monkeypatch.setenv("NULL_MODEL", "impostor")
    monkeypatch.setenv("LLR_ACTION_MODE", "shadow")
    on = _score(cohort, "nullpool:student_0")

    assert on["authorship"]["llr_deviation_score"] is not None
    assert on["authorship"]["deviation_score"] == off["authorship"]["deviation_score"]
    assert on["recommendation"]["action"] == off["recommendation"]["action"]


def test_flag_on_cold_start_stays_null(lone_student, monkeypatch):
    monkeypatch.setenv("NULL_MODEL", "impostor")
    body = _score(lone_student, "nullsolo:only")
    assert body["authorship"]["llr_deviation_score"] is None
