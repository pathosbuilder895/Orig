"""
Tenant-isolation tests (ADR-003, Phase 1) — the permanent cross-tenant CI gate.

Proves two invariants simultaneously:
  1. The zero-login demo is unchanged: anonymous access to flat-id students works.
  2. Real (pilot/production) tenant data is isolated: a professor of tenant A
     cannot read tenant B, and the anonymous demo cannot read pilot data.
"""

import pytest
from fastapi.testclient import TestClient

import run  # repo-root launcher
from original import principal as pr

# original/api.py is shadowed by the original.api package, so the legacy demo
# app (the one the dashboards talk to, and the one we hardened) is loaded by
# file path — exactly as run.py does at startup.
app = run.load_legacy_demo_app()
client = TestClient(app)

# ~140 words — comfortably above any baseline minimum.
LONG_TEXT = (
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


def _auth(token: str):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module", autouse=True)
def pilot_setup():
    """Register a pilot tenant and seed one pilot student (via its professor)."""
    client.post(
        "/tenants",
        json={"tenant_id": "isoacme", "name": "Iso Acme Seminary", "environment": "pilot"},
    )
    prof = pr.mint_principal_token("prof_acme", "professor", "isoacme")
    r = client.post(
        "/students/isoacme:bob/baseline",
        json={"text": LONG_TEXT, "assignment": "intro-essay"},
        headers=_auth(prof),
    )
    assert r.status_code == 200, r.text
    yield


# ── Invariant 1: the demo still works ─────────────────────────────────────────

def test_demo_flat_student_round_trip():
    """Anonymous demo can create and read a flat-id (sandbox) student."""
    r = client.post(
        "/students/iso_demo_alice/baseline",
        json={"text": LONG_TEXT, "assignment": "a1"},
    )
    assert r.status_code == 200, r.text
    r = client.get("/students/iso_demo_alice")
    assert r.status_code == 200


# ── Invariant 2: real tenants are isolated ────────────────────────────────────

def test_demo_cannot_read_pilot_student():
    """Anonymous demo is denied access to pilot-tenant data."""
    r = client.get("/students/isoacme:bob")
    assert r.status_code == 403


def test_cross_tenant_professor_denied():
    """A professor of another tenant cannot read isoacme's student."""
    other = pr.mint_principal_token("prof_other", "professor", "isoother")
    r = client.get("/students/isoacme:bob", headers=_auth(other))
    assert r.status_code == 403


def test_same_tenant_professor_allowed():
    """The owning tenant's professor can read the student."""
    prof = pr.mint_principal_token("prof_acme", "professor", "isoacme")
    r = client.get("/students/isoacme:bob", headers=_auth(prof))
    assert r.status_code == 200


def test_operator_cross_tenant_allowed():
    """The operator / super-admin role is cross-tenant by design."""
    op = pr.mint_principal_token("op1", "operator", "platform")
    r = client.get("/students/isoacme:bob", headers=_auth(op))
    assert r.status_code == 200


def test_cross_tenant_denied_on_subpath():
    """Isolation covers subpaths (e.g. samples), not just the root resource."""
    other = pr.mint_principal_token("prof_other", "professor", "isoother")
    r = client.get("/students/isoacme:bob/samples/0/text", headers=_auth(other))
    assert r.status_code == 403


def test_list_students_scoped_for_professor():
    """A professor's /students listing is confined to their own tenant."""
    prof = pr.mint_principal_token("prof_acme", "professor", "isoacme")
    r = client.get("/students", headers=_auth(prof))
    assert r.status_code == 200
    ids = r.json()["students"]
    assert ids, "expected at least the seeded pilot student"
    assert all(i.startswith("isoacme:") for i in ids), ids


def test_tampered_principal_token_falls_back_to_demo():
    """A forged token must not grant tenant access (signature check)."""
    forged = pr.mint_principal_token("x", "professor", "isoacme")[:-3] + "xxx"
    r = client.get("/students/isoacme:bob", headers=_auth(forged))
    # forged token → demo principal → pilot data denied
    assert r.status_code == 403
