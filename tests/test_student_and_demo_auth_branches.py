"""
Branch tests for original/routers/auth.py's student + demo surfaces
(student_login, student_me, demo_login) — part 2 task 6.

auth_login / auth_register's own manual-validation arms are covered in
tests/test_staff_auth.py, which already owns the staff-auth idiom for this
router. These three handlers have no existing dedicated coverage, so they get
a fresh file (same pattern Task 5 used for test_app_lifecycle_branches.py).

All HTTP-level via live_client + store_reset. None of these three handlers
call `_throttle_login` (only auth_login does — see routers/_shared.py), so
none of this file needs the login-throttle hygiene the brief warns about.
"""

from __future__ import annotations

from original.repository import SqliteRepository

LOGIN = "/student-auth/login"
ME = "/student-auth/me"
DEMO_LOGIN = "/api/v1/auth/login"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── student_login ──────────────────────────────────────────────────────────


def test_student_login_rejects_empty_email(live_client, store_reset):
    r = live_client.post(LOGIN, json={"email": "", "institution": "Seminary of Dallas"})
    assert r.status_code == 422, r.text
    assert "email" in r.json()["detail"].lower()


def test_student_login_rejects_email_without_at_sign(live_client, store_reset):
    r = live_client.post(LOGIN, json={"email": "not-an-email", "institution": "Sem"})
    assert r.status_code == 422, r.text
    assert "email" in r.json()["detail"].lower()


def test_student_login_rejects_empty_institution(live_client, store_reset):
    r = live_client.post(LOGIN, json={"email": "jane@sod.edu", "institution": "   "})
    assert r.status_code == 422, r.text
    assert "institution" in r.json()["detail"].lower()


def test_student_login_reuses_an_already_registered_institution(
    live_client, store_reset, monkeypatch
):
    """Second login for the same institution must NOT re-provision the tenant
    (the `if not _repo().get_tenant(tenant_id): put_tenant(...)` guard's False
    arm) — asserted both behaviourally (same tenant_id, no error) and via a
    call-count spy on put_tenant so the branch is actually proven, not just
    assumed from the absence of a crash."""
    calls = []
    original_put_tenant = SqliteRepository.put_tenant

    def _spy(self, *args, **kwargs):
        calls.append((args, kwargs))
        return original_put_tenant(self, *args, **kwargs)

    monkeypatch.setattr(SqliteRepository, "put_tenant", _spy)

    first = live_client.post(
        LOGIN, json={"email": "first@sod.edu", "institution": "Seminary of Dallas"}
    )
    assert first.status_code == 200, first.text
    assert len(calls) == 1  # institution auto-provisioned once

    second = live_client.post(
        LOGIN, json={"email": "second@sod.edu", "institution": "Seminary of Dallas"}
    )
    assert second.status_code == 200, second.text
    assert first.json()["tenant_id"] == second.json()["tenant_id"]
    # No second put_tenant call: the tenant already existed.
    assert len(calls) == 1


# ── student_me ────────────────────────────────────────────────────────────


def test_student_me_without_a_token_is_401(live_client, store_reset):
    r = live_client.get(ME)
    assert r.status_code == 401, r.text


def test_student_me_with_an_invalid_token_is_401(live_client, store_reset):
    r = live_client.get(ME, headers=_auth("not-a-real-session-token"))
    assert r.status_code == 401, r.text


def test_student_me_with_a_valid_session_returns_the_student(live_client, store_reset):
    login = live_client.post(
        LOGIN, json={"email": "me@sod.edu", "institution": "Seminary of Dallas", "name": "Jane"}
    )
    assert login.status_code == 200, login.text
    token = login.json()["token"]

    r = live_client.get(ME, headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["student_id"] == login.json()["student_id"]
    assert body["name"] == "Jane"


def test_student_me_accepts_the_x_student_token_header(live_client, store_reset):
    """The Authorization-header path is exercised above; the X-Student-Token
    fallback (used by pages that can't set a bearer header) is the same
    False-arm of the two-way `if` at line 171, exercised separately."""
    login = live_client.post(
        LOGIN, json={"email": "xtoken@sod.edu", "institution": "Seminary of Dallas"}
    )
    token = login.json()["token"]
    r = live_client.get(ME, headers={"X-Student-Token": token})
    assert r.status_code == 200, r.text


# ── demo_login ────────────────────────────────────────────────────────────


def test_demo_login_maintenance_token_grants_admin(live_client, monkeypatch):
    import original.api as api_mod

    monkeypatch.setattr(api_mod, "_MAINTENANCE_TOKEN", "s3cret-ops-token")
    r = live_client.post(
        DEMO_LOGIN, json={"email": "anyone@x.edu", "password": "s3cret-ops-token"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token"] == "maintenance-token"
    assert body["role"] == "admin"


def test_demo_login_wrong_password_does_not_use_the_maintenance_backdoor(
    live_client, monkeypatch
):
    import original.api as api_mod

    monkeypatch.setattr(api_mod, "_MAINTENANCE_TOKEN", "s3cret-ops-token")
    r = live_client.post(DEMO_LOGIN, json={"email": "prof@x.edu", "password": "wrong"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "professor"  # falls through to demo role routing


def test_demo_login_admin_substring_grants_admin_role(live_client, monkeypatch):
    import original.api as api_mod

    monkeypatch.setattr(api_mod, "_MAINTENANCE_TOKEN", "")  # backdoor off
    r = live_client.post(DEMO_LOGIN, json={"email": "administrator@x.edu", "password": "p"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "admin"
    assert body["token"] == "demo-token"


def test_demo_login_student_substring_grants_student_role(live_client, monkeypatch):
    import original.api as api_mod

    monkeypatch.setattr(api_mod, "_MAINTENANCE_TOKEN", "")
    r = live_client.post(DEMO_LOGIN, json={"email": "a.student@x.edu", "password": "p"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "student"
