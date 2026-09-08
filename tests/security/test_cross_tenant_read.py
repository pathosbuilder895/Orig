"""
tests/security/test_cross_tenant_read.py — "I am staff in B; show me A."

The six rows of docs/testing/04-security-adversarial.md §1.1, one test each.
Every test provisions two real (pilot) tenants via the shared ``two_tenants``
fixture, then calls a read surface as tenant B's staff and checks tenant A's
data never comes back.
"""

from __future__ import annotations

import pytest

from original import baseline_requests, bbook_client

pytestmark = pytest.mark.security


# ── 1. Pending baseline requests ──────────────────────────────────────────────


@pytest.mark.blocker
def test_pending_baseline_requests_scoped(two_tenants, live_client, monkeypatch):
    """T-02: pending baseline requests leak cross-tenant emails and live magic links.

    `GET /baseline-requests/pending` (original/routers/students_baseline.py:
    ``list_pending_baseline_requests``) takes no ``request`` argument and
    returns ``baseline_requests.list_pending()`` completely unscoped — every
    tenant's pending requests, including live magic links, are visible to
    any staff principal of any tenant.
    """
    baseline_requests._reset_cache()

    result = bbook_client.BaselineRequestResult(
        externalRequestId="ext-a-1",
        examId="exam-a-1",
        status="pending",
        expiresAt=None,
        emailDelivered=False,
        magicLink="https://bbook.example/magic/SUPER-SECRET-TOKEN-A",
    )
    monkeypatch.setattr(bbook_client, "is_enabled", lambda: True)
    monkeypatch.setattr(bbook_client, "request_baseline", lambda **kw: result)

    student_a = two_tenants["student_a"]
    r = live_client.post(
        f"/students/{student_a}/request-baseline",
        json={
            "student_email": "alice-secret@sectesta.example",
            "student_name": "Alice A",
        },
        headers=two_tenants["headers_a"],
    )
    assert r.status_code == 200, r.text

    r = live_client.get("/baseline-requests/pending", headers=two_tenants["headers_b"])
    assert r.status_code == 200, r.text
    body = r.json()

    a_prefix = f"{two_tenants['tenant_a']}:"
    leaked_rows = [
        row for row in body["requests"] if str(row.get("student_id", "")).startswith(a_prefix)
    ]
    assert leaked_rows == [], f"tenant B staff can see tenant A's pending requests: {leaked_rows}"

    text = r.text
    assert "alice-secret@sectesta.example" not in text
    assert "SUPER-SECRET-TOKEN-A" not in text


# ── 2. Student roster ─────────────────────────────────────────────────────────


def test_students_listing_never_leaks_by_prefix(two_tenants, live_client):
    """`/students` for tenant B staff must never include tenant A's ids.

    original/routers/students.py:list_students scopes a non-super staff
    principal's roster to ``_repo().list_ids_for_tenant(principal.tenant_id)``
    regardless of any ``tenant_id`` query param — this is the control that
    keeps this test green.
    """
    r = live_client.get("/students", headers=two_tenants["headers_b"])
    assert r.status_code == 200, r.text
    ids = r.json()["students"]
    a_prefix = f"{two_tenants['tenant_a']}:"
    assert not any(sid.startswith(a_prefix) for sid in ids), ids
    # Sanity: the roster isn't vacuously empty — it does see its own tenant.
    assert two_tenants["student_b"] in ids


# ── 3. Tenant stats ────────────────────────────────────────────────────────────


def test_tenant_stats_scoped(two_tenants, live_client):
    """`/tenants/{A}/stats` from B staff must be refused, not answered.

    original/routers/tenants.py:tenant_stats calls
    ``principal_mod.assert_tenant_access`` before touching the repository —
    the control that keeps this test green.
    """
    r = live_client.get(
        f"/tenants/{two_tenants['tenant_a']}/stats", headers=two_tenants["headers_b"]
    )
    assert r.status_code == 403, r.text
    assert "count" not in r.text.lower()


# ── 4. Data inventory ──────────────────────────────────────────────────────────


def test_data_inventory_scoped(two_tenants, live_client):
    """`/students/{A-id}/data-inventory` from B staff must be refused.

    The tenant-isolation middleware's ``extract_scoped_id`` matches any
    ``/students/{id}/...`` path and enforces ``assert_student_access`` before
    the request reaches the handler — the control that keeps this test green.
    """
    r = live_client.get(
        f"/students/{two_tenants['student_a']}/data-inventory",
        headers=two_tenants["headers_b"],
    )
    assert r.status_code == 403, r.text


# ── 5. Sample text ─────────────────────────────────────────────────────────────


def test_sample_text_scoped(two_tenants, live_client):
    """`/students/{A-id}/samples/0/text` from B staff must be refused.

    Same middleware control as the data-inventory test above: the handler
    itself takes no ``request``/principal argument at all, so the
    tenant-isolation middleware is the only thing standing between B and A's
    raw baseline prose.
    """
    r = live_client.get(
        f"/students/{two_tenants['student_a']}/samples/0/text",
        headers=two_tenants["headers_b"],
    )
    assert r.status_code == 403, r.text


# ── 6. Admin audit log ─────────────────────────────────────────────────────────


@pytest.mark.blocker
def test_admin_audit_scoped(two_tenants, live_client):
    """T-63: /admin/audit has no tenant filter, leaking cross-tenant audit rows.

    ⚠️ Provisional id — T-63 is NOT in docs/testing/10-gap-register.md as of
    2026-09-07 (that document only lists T-01 through T-09; §1.1 there names
    only T-02). This is a new finding surfaced while writing this test file,
    not one of this task's two assigned gaps (T-02, T-06). It is marked
    ``blocker`` anyway rather than left as an unmarked red test — Task 3 has
    no mandate to fix `original/`, so it cannot be made green here, and an
    unmarked red test would break every future `-m "not blocker"` run. See
    the task report's Concerns section: the register (and its owning task)
    needs a real T-63 row before this marker is more than a placeholder.

    original/routers/admin.py:list_audit_log calls ``_require_staff`` (any
    staff role, any tenant — no tenant check) and then
    ``_repo().list_audit(student_id=..., action=...)`` with no ``tenant_id``
    parameter at all; ``original/store.py:list_audit`` builds its WHERE
    clause from ``student_id``/``action`` only. A tenant-B professor calling
    with no ``student_id`` filter gets every tenant's audit rows, including
    tenant A's.
    """
    r = live_client.get("/admin/audit", headers=two_tenants["headers_b"])
    assert r.status_code == 200, r.text
    body = r.json()
    a_rows = [
        item for item in body["items"] if item.get("student_id") == two_tenants["student_a"]
    ]
    assert a_rows == [], f"tenant B staff can see tenant A's audit rows: {a_rows}"
