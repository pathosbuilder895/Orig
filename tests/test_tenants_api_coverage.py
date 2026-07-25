"""
tests/test_tenants_api_coverage.py — the /tenants registry contract.

The tenant registry is the root of the ADR-003 isolation model: a tenant's
``environment`` decides whether the anonymous demo principal may read its
students. So the surfaces here are authorization boundaries, not CRUD:

  * the demo-downgrade refusal (409) that stops FERPA data becoming
    anonymously readable;
  * ``assert_tenant_access`` on every read/delete, so a professor of school A
    cannot inspect or bulk-erase school B;
  * the input caps that keep an unbounded meta blob out of the DB.

Every test asserts a specific status/body, so a silently-relaxed check fails.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import run
from original import principal as pr

app = run.load_legacy_demo_app()
client = TestClient(app)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _slug(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


@pytest.fixture
def demo_tenant():
    """A freshly registered demo-environment tenant."""
    tid = _slug("tncov")
    r = client.post("/tenants", json={"tenant_id": tid, "name": "Coverage College"})
    assert r.status_code == 201, r.text
    return tid


# ── POST /tenants: validation contract ───────────────────────────────────────


def test_create_tenant_defaults_to_demo_environment(demo_tenant):
    """Omitting `environment` yields 'demo' — the safe, sandbox-visible default."""
    r = client.get(f"/tenants/{demo_tenant}")
    assert r.status_code == 200, r.text
    assert r.json()["environment"] == "demo"


def test_blank_name_is_rejected_422():
    """A whitespace-only name is rejected after .strip(), not stored blank."""
    r = client.post("/tenants", json={"tenant_id": _slug("blank"), "name": "   "})
    assert r.status_code == 422, r.text
    assert "required" in r.json()["detail"]


def test_blank_tenant_id_is_rejected_422():
    """A whitespace-only tenant_id would create an unaddressable record."""
    r = client.post("/tenants", json={"tenant_id": "   ", "name": "Nameless"})
    assert r.status_code == 422, r.text


def test_overlong_tenant_id_is_rejected_422():
    """tenant_id is capped at 80 chars — it is a key prefix on every student id."""
    r = client.post("/tenants", json={"tenant_id": "x" * 81, "name": "Too Long"})
    assert r.status_code == 422, r.text
    assert "80" in r.json()["detail"]


def test_overlong_name_is_rejected_422():
    """name is capped at 200 chars."""
    r = client.post("/tenants", json={"tenant_id": _slug("longname"), "name": "y" * 201})
    assert r.status_code == 422, r.text
    assert "200" in r.json()["detail"]


def test_unknown_environment_is_rejected_422():
    """Only demo/pilot/production are legal — an unknown label would make
    `tenant_environment()` fail closed for every student in the tenant."""
    r = client.post(
        "/tenants",
        json={"tenant_id": _slug("badenv"), "name": "Bad Env", "environment": "staging"},
    )
    assert r.status_code == 422, r.text
    assert "demo" in r.json()["detail"]


def test_meta_with_more_than_ten_keys_is_rejected_422():
    """The meta cap prevents unbounded JSON storage per tenant."""
    r = client.post(
        "/tenants",
        json={
            "tenant_id": _slug("fatmeta"),
            "name": "Fat Meta",
            "meta": {f"k{i}": "v" for i in range(11)},
        },
    )
    assert r.status_code == 422, r.text
    assert "10 keys" in r.json()["detail"]


def test_meta_values_are_truncated_and_round_trip():
    """Accepted meta is stored and read back, with values clamped to 500 chars.

    Catches both a lost round-trip (meta silently dropped on write) and a lost
    truncation (an unbounded value reaching the DB).
    """
    tid = _slug("meta")
    r = client.post(
        "/tenants",
        json={
            "tenant_id": tid,
            "name": "Meta School",
            "meta": {"contact": "registrar@example.edu", "blurb": "z" * 600},
        },
    )
    assert r.status_code == 201, r.text

    meta = client.get(f"/tenants/{tid}").json()["meta"]
    assert meta["contact"] == "registrar@example.edu"
    assert len(meta["blurb"]) == 500


# ── The demo-downgrade refusal ───────────────────────────────────────────────


def test_pilot_tenant_cannot_be_downgraded_to_demo_409():
    """Downgrading pilot→demo would make FERPA-protected students anonymously
    readable, so it is refused with 409 and the stored record is unchanged."""
    tid = _slug("pilotdown")
    assert (
        client.post(
            "/tenants",
            json={"tenant_id": tid, "name": "Pilot Sem", "environment": "pilot"},
        ).status_code
        == 201
    )

    r = client.post(
        "/tenants", json={"tenant_id": tid, "name": "Pilot Sem", "environment": "demo"}
    )
    assert r.status_code == 409, r.text
    assert "downgrade" in r.json()["detail"]
    # The refusal must not have partially applied.
    assert client.get(f"/tenants/{tid}").json()["environment"] == "pilot"


def test_pilot_tenant_may_still_be_upgraded_to_production():
    """The guard is a *downgrade* guard only — pilot→production stays allowed."""
    tid = _slug("upgrade")
    client.post(
        "/tenants", json={"tenant_id": tid, "name": "Up Sem", "environment": "pilot"}
    )
    r = client.post(
        "/tenants",
        json={"tenant_id": tid, "name": "Up Sem", "environment": "production"},
    )
    assert r.status_code == 201, r.text
    assert client.get(f"/tenants/{tid}").json()["environment"] == "production"


# ── GET /tenants: staff-only ─────────────────────────────────────────────────


def test_list_tenants_rejects_a_student_principal_403():
    """A student session must never enumerate the institution registry.

    `x-demo-role` drives the anonymous principal's role, so this exercises the
    `_require_staff` role check without needing a real student login.
    """
    r = client.get("/tenants", headers={"x-demo-role": "student"})
    assert r.status_code == 403, r.text
    assert "Staff role required." == r.json()["detail"]


def test_list_tenants_filters_by_environment(demo_tenant):
    """?environment=pilot must exclude demo tenants (the operator dashboard
    relies on this to separate live schools from sandboxes)."""
    pilot_id = _slug("pfilter")
    client.post(
        "/tenants",
        json={"tenant_id": pilot_id, "name": "Filtered Pilot", "environment": "pilot"},
    )

    pilot_ids = {t["tenant_id"] for t in client.get("/tenants?environment=pilot").json()}
    assert pilot_id in pilot_ids
    assert demo_tenant not in pilot_ids

    all_ids = {t["tenant_id"] for t in client.get("/tenants").json()}
    assert {pilot_id, demo_tenant} <= all_ids


# ── GET /tenants/{id}: cross-tenant reads ────────────────────────────────────


def test_get_unknown_tenant_404():
    r = client.get("/tenants/no-such-tenant-anywhere")
    assert r.status_code == 404, r.text
    assert "not found" in r.json()["detail"]


def test_professor_can_read_own_tenant_record():
    """A non-super staff principal reads its OWN institution — the settings panel."""
    tid = _slug("ownread")
    client.post(
        "/tenants", json={"tenant_id": tid, "name": "Own School", "environment": "pilot"}
    )
    prof = pr.mint_principal_token("prof_own", "professor", tid)

    r = client.get(f"/tenants/{tid}", headers=_auth(prof))
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Own School"


def test_professor_cannot_read_another_tenant_record_403():
    """Cross-tenant registry read is denied for non-super roles."""
    other = _slug("otherread")
    client.post(
        "/tenants",
        json={"tenant_id": other, "name": "Other School", "environment": "pilot"},
    )
    prof = pr.mint_principal_token("prof_a", "professor", _slug("mine"))

    r = client.get(f"/tenants/{other}", headers=_auth(prof))
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "Cross-tenant access denied."


def test_get_tenant_rejects_student_principal_403():
    """Students never read tenant records, own-tenant or not."""
    r = client.get("/tenants/anything", headers={"x-demo-role": "student"})
    assert r.status_code == 403, r.text


# ── GET /tenants/{id}/stats ──────────────────────────────────────────────────


def test_tenant_stats_unknown_tenant_404():
    """Stats for an unregistered tenant is 404, not an empty-zeros body —
    otherwise a typo'd slug reads as a real but idle school."""
    r = client.get("/tenants/never-registered/stats")
    assert r.status_code == 404, r.text


def test_tenant_stats_counts_only_that_tenants_students():
    """student_count is scoped to the `{tenant}:` id prefix.

    Seeds two tenants and asserts the counts don't bleed — catches a LIKE
    pattern that drops the prefix escape or the tenant filter entirely.
    """
    a, b = _slug("statsa"), _slug("statsb")
    for tid in (a, b):
        client.post(
            "/tenants", json={"tenant_id": tid, "name": tid, "environment": "pilot"}
        )
    tok_a = pr.mint_principal_token("op_a", "operator", a)

    client.post(
        f"/students/{a}:s1/baseline",
        json={"text": _LONG_TEXT, "assignment": "a"},
        headers=_auth(tok_a),
    )
    client.post(
        f"/students/{a}:s2/baseline",
        json={"text": _LONG_TEXT, "assignment": "a"},
        headers=_auth(tok_a),
    )
    client.post(
        f"/students/{b}:s1/baseline",
        json={"text": _LONG_TEXT, "assignment": "a"},
        headers=_auth(tok_a),
    )

    stats_a = client.get(f"/tenants/{a}/stats", headers=_auth(tok_a)).json()
    stats_b = client.get(f"/tenants/{b}/stats", headers=_auth(tok_a)).json()
    assert stats_a["tenant_id"] == a
    assert stats_a["student_count"] == 2
    assert stats_b["student_count"] == 1
    assert stats_a["sample_count"] >= 2


def test_tenant_stats_cross_tenant_denied_403():
    """A professor cannot pull another school's aggregate volume."""
    other = _slug("statsx")
    client.post(
        "/tenants", json={"tenant_id": other, "name": "X", "environment": "pilot"}
    )
    prof = pr.mint_principal_token("prof_x", "professor", _slug("home"))

    r = client.get(f"/tenants/{other}/stats", headers=_auth(prof))
    assert r.status_code == 403, r.text


# ── DELETE /tenants/{id}/students: the bulk-erase boundary ───────────────────


def test_bulk_delete_cross_tenant_denied_403():
    """The gap this endpoint's docstring calls out: a professor of school A
    must not be able to erase school B's entire roster."""
    victim = _slug("victim")
    client.post(
        "/tenants", json={"tenant_id": victim, "name": "Victim", "environment": "pilot"}
    )
    op = pr.mint_principal_token("op", "operator", victim)
    client.post(
        f"/students/{victim}:keep/baseline",
        json={"text": _LONG_TEXT, "assignment": "a"},
        headers=_auth(op),
    )

    attacker = pr.mint_principal_token("prof_evil", "professor", _slug("attacker"))
    r = client.delete(f"/tenants/{victim}/students", headers=_auth(attacker))
    assert r.status_code == 403, r.text

    # And the roster survived.
    assert (
        client.get(f"/students/{victim}:keep", headers=_auth(op)).status_code == 200
    )


def test_bulk_delete_unknown_tenant_404():
    r = client.delete("/tenants/not-a-real-tenant/students")
    assert r.status_code == 404, r.text


def test_bulk_delete_erases_only_the_named_tenants_students():
    """Bulk delete removes every student under `{tenant}:` and nobody else's.

    This is the FERPA erasure path; a broadened id match here would erase a
    neighbouring school.
    """
    target, bystander = _slug("bulkdel"), _slug("bystand")
    for tid in (target, bystander):
        client.post(
            "/tenants", json={"tenant_id": tid, "name": tid, "environment": "pilot"}
        )
    op = pr.mint_principal_token("op_bulk", "operator", target)

    for sid in (f"{target}:one", f"{target}:two", f"{bystander}:safe"):
        client.post(
            f"/students/{sid}/baseline",
            json={"text": _LONG_TEXT, "assignment": "a"},
            headers=_auth(op),
        )

    r = client.delete(f"/tenants/{target}/students", headers=_auth(op))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted_count"] == 2
    assert body["failed_ids"] == []
    assert target in body["message"]

    assert client.get(f"/students/{target}:one", headers=_auth(op)).status_code == 404
    assert client.get(f"/students/{target}:two", headers=_auth(op)).status_code == 404
    assert client.get(f"/students/{bystander}:safe", headers=_auth(op)).status_code == 200


_LONG_TEXT = (
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
