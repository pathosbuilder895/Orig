"""
Provenance-authorization tests for POST /students/{id}/baseline.

A baseline sample's ``provenance`` sets its trust weight in the voice profile
(proctored 2.0 / verified 1.0 / canvas 0.8 / unverified 0.5). If a *student*
could self-assert a high-trust provenance, they could inject ghostwritten or
AI-written text as "proctored" ground truth and drag their own baseline toward
the very thing the system exists to flag. This gate proves:

  1. A student token cannot self-assert a trusted provenance — proctored /
     verified / canvas are all downgraded to 'unverified'.
  2. Staff principals (professor/admin/operator) keep the requested provenance.
  3. The anonymous demo principal keeps it too, but ONLY off a real deploy (the
     demo/e2e Bluebook flow posts proctored without a token). On a pilot it is
     an unauthenticated caller and is downgraded like any other — otherwise
     dropping the Authorization header would buy more trust than sending a real
     student session, since the anonymous principal carries a synthetic
     "operator" role.
  4. The legitimate proctored path still lands proctored samples: a student
     token accompanied by a valid server-minted proctor attestation (the
     ``X-Proctor-Attestation`` the LTI exam launch issues) is honored.
  5. An attestation minted for a *different* student does not authorize.
  6. The proctor attestation and the login session token are not interchangeable.
"""

import sys

import pytest
from fastapi.testclient import TestClient

import run  # repo-root launcher
from original import principal as pr
from original import student_auth

# ~130 words — comfortably above any per-sample minimum.
LONG_TEXT = (
    "The doctrine of justification by faith stands at the center of the gospel. "
    "When Paul writes to the Romans, he labors to show that righteousness comes "
    "not by works of the law but through faith alone. A careful reader notices "
    "how the argument unfolds in stages, each building on the last, until the "
    "conclusion becomes unavoidable. The voice here is deliberate and measured, "
    "favoring long subordinate clauses and a vocabulary drawn from systematic "
    "study. Such patterns, repeated across many essays, form a fingerprint as "
    "distinctive as handwriting. The student who writes this way in September "
    "will, absent intervention, write this way in May, and that continuity is "
    "precisely what we set out to measure and to protect with patience and care."
)


def _auth(token: str):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def app():
    return run.load_legacy_demo_app()


@pytest.fixture
def client(app, store_reset):
    return TestClient(app)


@pytest.fixture
def real_deploy(monkeypatch):
    """Flip the loaded app into pilot behaviour without reloading it."""
    monkeypatch.setattr(sys.modules["original._legacy_demo_api"], "_IS_REAL_DEPLOY", True)
    yield


def _post_baseline(client, sid, provenance, *, headers=None):
    return client.post(
        f"/students/{sid}/baseline",
        json={"text": LONG_TEXT, "provenance": provenance, "assignment": "a1"},
        headers=headers or {},
    )


# ── 1. Students cannot self-assert trusted provenance ─────────────────────────


@pytest.mark.parametrize("provenance", ["proctored", "verified", "canvas"])
def test_student_trusted_provenance_downgraded(client, provenance):
    sid = "acme:selfauthor"
    stu = pr.mint_principal_token(sid, "student", "acme")
    r = _post_baseline(client, sid, provenance, headers=_auth(stu))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provenance"] == "unverified", body
    assert body["auth_weight"] == 0.5, body
    assert body["provenance_downgraded"] is True
    assert body["requested_provenance"] == provenance


def test_student_unverified_stays_unverified(client):
    """The self-assertable provenance is untouched — no spurious downgrade flag."""
    sid = "acme:honest"
    stu = pr.mint_principal_token(sid, "student", "acme")
    r = _post_baseline(client, sid, "unverified", headers=_auth(stu))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provenance"] == "unverified"
    assert "provenance_downgraded" not in body


# ── 2. Staff keep the requested provenance ────────────────────────────────────


def test_staff_verified_preserved(client):
    prof = pr.mint_principal_token("prof_acme", "professor", "acme")
    r = _post_baseline(client, "acme:bob", "verified", headers=_auth(prof))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provenance"] == "verified"
    assert body["auth_weight"] == 1.0


def test_staff_proctored_preserved(client):
    op = pr.mint_principal_token("op1", "operator", "platform")
    r = _post_baseline(client, "acme:carol", "proctored", headers=_auth(op))
    assert r.status_code == 200, r.text
    assert r.json()["provenance"] == "proctored"


# ── 3. Anonymous demo principal keeps proctored (demo/e2e flow) ───────────────


def test_demo_anonymous_proctored_preserved(client):
    """No token → demo principal (operator); the demo Bluebook flow posts
    proctored this way and must keep landing proctored samples."""
    r = _post_baseline(client, "demo_flat_student", "proctored")
    assert r.status_code == 200, r.text
    assert r.json()["provenance"] == "proctored"


def test_anonymous_proctored_downgraded_on_real_deploy(client, real_deploy):
    """On a pilot, dropping the Authorization header must NOT out-privilege an
    authenticated student.

    Regression: the anonymous principal defaults to role "operator", which is in
    _STAFF_ROLES, so an unauthenticated POST used to sail through the staff rule
    and land AI text at proctored/2.0 — while the same student's real session
    token was correctly downgraded to unverified/0.5.

    The tenant is provisioned the way a pilot student actually arrives:
    /student-auth/login auto-registers the institution with environment="demo",
    which is precisely what lets the anonymous principal past the isolation
    middleware and reach this gate. An *unregistered* tenant would 403 at the
    middleware instead, hiding the bug.
    """
    lr = client.post(
        "/student-auth/login",
        json={"email": "jane@sod.edu", "institution": "Seminary of Dallas"},
    )
    assert lr.status_code == 200, lr.text
    sid = lr.json()["student_id"]

    r = _post_baseline(client, sid, "proctored")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provenance"] == "unverified"
    assert body["auth_weight"] == 0.5
    assert body["provenance_downgraded"] is True


def test_authenticated_staff_still_preserved_on_real_deploy(client, real_deploy):
    """The real-deploy clamp must bite only the anonymous principal — a genuine
    professor token still keeps the requested provenance."""
    prof = pr.mint_principal_token("prof_x", "professor", "acme")
    r = _post_baseline(client, "acme:kid", "proctored", headers=_auth(prof))
    assert r.status_code == 200, r.text
    assert r.json()["provenance"] == "proctored"


# ── 4. The attested proctored path is honored ─────────────────────────────────


def test_student_with_attestation_lands_proctored(client):
    """A bound student in a real exam carries a student session token PLUS the
    server-minted proctor attestation — the legitimate proctored ingestion."""
    sid = "acme:examtaker"
    stu = pr.mint_principal_token(sid, "student", "acme")
    attest = student_auth.mint_proctor_attestation(sid, "Week 1 Writing Sample")
    headers = {**_auth(stu), "X-Proctor-Attestation": attest}
    r = _post_baseline(client, sid, "proctored", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provenance"] == "proctored", body
    assert body["auth_weight"] == 2.0
    assert "provenance_downgraded" not in body


def test_attestation_for_other_student_does_not_authorize(client):
    """An attestation minted for a different sid must not unlock this student."""
    sid = "acme:victim"
    stu = pr.mint_principal_token(sid, "student", "acme")
    wrong = student_auth.mint_proctor_attestation("acme:someone_else", "exam")
    headers = {**_auth(stu), "X-Proctor-Attestation": wrong}
    r = _post_baseline(client, sid, "proctored", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["provenance"] == "unverified"


# ── 5. Token types are not interchangeable ────────────────────────────────────


def test_proctor_attestation_is_not_a_session():
    sid = "acme:x"
    attest = student_auth.mint_proctor_attestation(sid)
    # A proctor attestation must never authenticate a request as a session.
    assert student_auth.verify_session(attest) is None
    assert student_auth.verify_proctor_attestation(attest, sid) is True


def test_session_token_is_not_an_attestation():
    sid = "acme:x"
    session = student_auth.mint_session(sid, "Ex Ample")
    assert student_auth.verify_proctor_attestation(session, sid) is False
    assert student_auth.verify_session(session) is not None


def test_attestation_signature_is_verified():
    sid = "acme:x"
    forged = student_auth.mint_proctor_attestation(sid)[:-3] + "xxx"
    assert student_auth.verify_proctor_attestation(forged, sid) is False
