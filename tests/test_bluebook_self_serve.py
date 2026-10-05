"""Bluebook as a standalone, public self-serve product (2026-09).

Spec: docs/superpowers/specs/2026-09-17-bluebook-standalone-backend-design.md
(Sections 1-4 and the 2026-09-28 amendment). Grouped by concern:

* product entitlement and the middleware gate
* teacher signup, invites, student accounts, password change
* rosters, exam windows, course and exam CRUD
* the student dashboard routes
* submissions: text, warnings, shaping, export, caps
* launch links carrying an exam id, and FERPA erasure of the new rows
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from original import bluebook_rules as rules
from original import invites as invites_mod
from original import principal as principal_mod
from original import student_auth
from original import users as users_mod
from original.repository import get_repository

PW = "s3cret-passw0rd"
GUARD = "test-guard-token"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


@pytest.fixture(autouse=True)
def _isolate(store_reset, live_app):
    import original.api as api

    api._login_attempts.clear()
    principal_mod.invalidate_tenant_cache()
    yield
    api._login_attempts.clear()
    principal_mod.invalidate_tenant_cache()


@pytest.fixture
def api_mod(live_app):
    import original.api

    return original.api


@pytest.fixture
def guarded(api_mod, monkeypatch):
    monkeypatch.setattr(api_mod, "_GUARD_DESTRUCTIVE", True)
    monkeypatch.setattr(api_mod, "_MAINTENANCE_TOKEN", GUARD)


def _signup(client, email="teach@school.edu", name="Ms Teach") -> dict:
    r = client.post(
        "/auth/signup", json={"email": email, "password": PW, "name": name, "accept_terms": True}
    )
    assert r.status_code == 201, r.text
    return r.json()


def _operator(tenant="ops") -> dict:
    return _auth(principal_mod.mint_principal_token("op-1", "operator", tenant))


def _course(client, token, name="Ethics 101") -> str:
    r = client.post(
        "/bluebook/courses", json={"name": name, "code": "ETH101"}, headers=_auth(token)
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _exam(client, token, **fields) -> dict:
    body = {"title": "Midterm", "status": "ACTIVE", "prompt": "Discuss virtue.", **fields}
    r = client.post("/bluebook/exams", json=body, headers=_auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def _add_students(client, token, course_id, *emails) -> list[dict]:
    r = client.post(
        f"/bluebook/courses/{course_id}/students",
        json={"students": [{"email": e, "name": e.split("@")[0]} for e in emails]},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    return r.json()["students"]


def _token_of(invite_path: str) -> str:
    return parse_qs(urlparse(invite_path).query)["invite"][0]


def _student(client, teacher_token, course_id, email="stu@school.edu") -> dict:
    """Add, redeem, and return the student's login payload."""
    row = _add_students(client, teacher_token, course_id, email)[0]
    r = client.post(
        "/auth/invite/redeem", json={"token": _token_of(row["invite_path"]), "password": PW}
    )
    assert r.status_code == 200, r.text
    return r.json()


def _seal(client, token, exam_id, student_id, **extra) -> dict:
    body = {"exam_id": exam_id, "student_id": student_id, "word_count": 3, **extra}
    r = client.post("/bluebook/submissions", json=body, headers=_auth(token))
    assert r.status_code == 201, r.text
    return r.json()


# ── Entitlement and the product gate ──────────────────────────────────────────


def test_signup_creates_a_private_bluebook_only_workspace(live_client):
    out = _signup(live_client)
    assert out["role"] == "professor"
    assert out["products"] == ["bluebook"]
    tenant = get_repository().get_tenant(out["tenant_id"])
    assert tenant["products"] == ["bluebook"]
    assert tenant["environment"] == "production"
    assert tenant["meta"]["plan"] == rules.SELF_SERVE_PLAN
    assert out["tenant_id"].startswith("t-")
    me = live_client.get("/auth/me", headers=_auth(out["token"])).json()
    assert me["products"] == ["bluebook"]


def test_two_signups_get_separate_workspaces(live_client):
    a = _signup(live_client, "a@x.edu")
    b = _signup(live_client, "b@x.edu")
    assert a["tenant_id"] != b["tenant_id"]


@pytest.mark.parametrize(
    "body,code",
    [
        ({"email": "no-at-sign", "password": PW}, 422),
        ({"email": "t@x.edu", "password": "short"}, 422),
        ({"email": "t@x.edu", "password": "x" * 2000}, 422),
    ],
)
def test_signup_validation(live_client, body, code):
    assert live_client.post("/auth/signup", json={**body, "accept_terms": True}).status_code == code


def test_signup_duplicate_email_is_409(live_client):
    _signup(live_client, "dup@x.edu")
    r = live_client.post(
        "/auth/signup", json={"email": "DUP@x.edu", "password": PW, "accept_terms": True}
    )
    assert r.status_code == 409


def test_signup_is_throttled_per_ip(live_client):
    codes = [
        live_client.post(
            "/auth/signup", json={"email": f"s{i}@x.edu", "password": PW, "accept_terms": True}
        ).status_code
        for i in range(11)
    ]
    assert codes[:10] == [201] * 10
    assert codes[10] == 429


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/students"),
        ("GET", "/admin/audit"),
        ("GET", "/baseline-requests/pending"),
        ("POST", "/students/x:y/score"),
        ("GET", "/me/voice"),
    ],
)
def test_bluebook_only_teacher_cannot_reach_original(live_client, method, path):
    out = _signup(live_client)
    r = live_client.request(method, path, headers=_auth(out["token"]))
    assert r.status_code == 403
    assert "Original" in r.json()["detail"]


def test_bluebook_only_student_cannot_write_a_baseline_to_themselves(live_client):
    """No seal carve-out for a tenant without Original: self-serve students
    are never profiled, not even through the seal-time calls."""
    t = _signup(live_client)
    s = _student(live_client, t["token"], _course(live_client, t["token"]))
    r = live_client.post(
        f"/students/{s['student_id']}/baseline",
        json={"text": "word " * 60, "assignment": "a"},
        headers=_auth(s["token"]),
    )
    assert r.status_code == 403


def test_original_only_tenant_cannot_reach_bluebook(live_client, principal_headers):
    get_repository().put_tenant("orig-only", "Orig Only", environment="pilot")
    get_repository().set_tenant_products("orig-only", ["original"])
    principal_mod.invalidate_tenant_cache()
    h = principal_headers("p1", "professor", "orig-only")
    assert live_client.get("/bluebook/exams", headers=h).status_code == 403
    assert live_client.get("/students", headers=h).status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/bluebook/students/orig-only:jane",
        # A dotted final segment used to be mistaken for a static SPA file and
        # skipped the gate, reaching the handler (404 "student not found").
        "/bluebook/students/orig-only:jane.doe",
        "/bluebook/courses/c1/students/orig-only:jane.doe",
    ],
)
def test_original_only_tenant_gated_on_dotted_student_ids(live_client, principal_headers, path):
    get_repository().put_tenant("orig-only", "Orig Only", environment="pilot")
    get_repository().set_tenant_products("orig-only", ["original"])
    principal_mod.invalidate_tenant_cache()
    h = principal_headers("p1", "professor", "orig-only")
    r = live_client.delete(path, headers=h)
    assert r.status_code == 403
    assert "does not include Bluebook" in r.json()["detail"]


@pytest.mark.parametrize(
    "path,product",
    [
        ("/bluebook", None),
        ("/bluebook/", None),
        ("/bluebook/bluebook.bundle.js", None),
        ("/bluebook/index.html", None),
        ("/bluebook/parked.html", None),
        ("/bluebook/vendor/react.production.min.js", None),
        ("/bluebook/fonts/Garamond.WOFF2", None),
        # Dots in a path param are not file extensions: registered API routes
        # are gated whatever their last segment looks like.
        ("/bluebook/students/t:jane.doe", "bluebook"),
        ("/bluebook/students/t:jane.doe@school.edu", "bluebook"),
        ("/bluebook/courses/c1/students/t:jane.doe", "bluebook"),
        ("/bluebook/courses/c1/students/t:jane.doe/invite", "bluebook"),
        ("/bluebook/exams/exam.v2", "bluebook"),
        ("/bluebook/exams/x.html", "bluebook"),
        ("/bluebook/me/submissions/s.1", "bluebook"),
        # Unknown dotted paths without a static extension stay gated too.
        ("/bluebook/unknown/thing.doe", "bluebook"),
        ("/bluebook/me", "bluebook"),
        ("/bluebook/exams", "bluebook"),
        ("/bluebook/exams/abc/export", "bluebook"),
        ("/proctor/park/status", "bluebook"),
        ("/students", "original"),
        ("/students/a:b/score", "original"),
        ("/baseline-requests", "original"),
        ("/admin/audit", "original"),
        ("/auth/login", None),
        ("/tenants", None),
        ("/health", None),
    ],
)
def test_required_product_classifies_paths(api_mod, path, product):
    """Bluebook's static SPA files sit under /bluebook/ with the API; only
    the API is gated, so sign-in screens load before any tenant is known."""
    assert api_mod._required_product(path) == product


def test_operator_bypasses_the_gate(live_client):
    out = _signup(live_client)
    r = live_client.get(f"/tenants/{out['tenant_id']}", headers=_operator())
    assert r.status_code == 200
    assert live_client.get("/students", headers=_operator()).status_code == 200


def test_unknown_tenant_holds_every_product():
    assert principal_mod.tenant_products("never-registered") == principal_mod.ALL_PRODUCTS
    assert principal_mod.tenant_products(None) == principal_mod.ALL_PRODUCTS


class _FlakyTenants:
    """A repository whose get_tenant answers from ``records``, or raises while
    ``down`` is set (Postgres's get_tenant swallows the error and returns None
    instead, which tenant_products must treat the same way)."""

    def __init__(self):
        self.records: dict[str, dict] = {}
        self.down = False
        self.calls = 0

    def get_tenant(self, tenant_id):
        self.calls += 1
        if self.down:
            raise RuntimeError("db down")
        return self.records.get(tenant_id)


@pytest.fixture
def flaky_products(monkeypatch):
    """tenant_products on a real deploy, over a fake repository and clock."""
    import original.repository as repo_mod

    repo = _FlakyTenants()
    now = [1000.0]
    monkeypatch.setattr(repo_mod, "get_repository", lambda: repo)
    monkeypatch.setattr(principal_mod, "_clock", lambda: now[0])
    monkeypatch.setattr(principal_mod, "_is_real_deploy", lambda: True)
    principal_mod.invalidate_tenant_cache()
    return repo, now


BLUEBOOK_ONLY = frozenset({"bluebook"})


def _product_warnings(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == "original.principal" and r.levelno == logging.WARNING
    ]


def test_tenant_products_lookup_failure_on_a_real_deploy_is_bluebook_only(flaky_products, caplog):
    """A database error must never grant Original: with nothing cached, a real
    deploy falls back to Bluebook alone and says so once in the log."""
    repo, _ = flaky_products
    repo.down = True
    with caplog.at_level(logging.WARNING, logger="original.principal"):
        assert principal_mod.tenant_products("x-tenant") == BLUEBOOK_ONLY
        # Inside the retry window: no second lookup, no second warning.
        assert principal_mod.tenant_products("x-tenant") == BLUEBOOK_ONLY
    assert repo.calls == 1
    assert _product_warnings(caplog) == [
        "tenant products lookup failed for x-tenant; using bluebook only"
    ]


def test_tenant_products_missing_record_on_a_real_deploy_is_bluebook_only(flaky_products):
    """Postgres's get_tenant returns None on a database error, so a missing
    record cannot be told apart from a failed lookup."""
    repo, _ = flaky_products
    assert principal_mod.tenant_products("never-registered") == BLUEBOOK_ONLY


def test_tenant_products_record_without_products_still_holds_both(flaky_products):
    """Unchanged: a row that predates the products column holds both."""
    repo, _ = flaky_products
    repo.records = {
        "old-a": {"tenant_id": "old-a", "products": []},
        "old-b": {"tenant_id": "old-b"},
    }
    assert principal_mod.tenant_products("old-a") == principal_mod.ALL_PRODUCTS
    assert principal_mod.tenant_products("old-b") == principal_mod.ALL_PRODUCTS


def test_tenant_products_keeps_the_last_known_value_when_a_refresh_fails(flaky_products, caplog):
    repo, now = flaky_products
    repo.records = {
        "bb-only": {"tenant_id": "bb-only", "products": ["bluebook"]},
        "both": {"tenant_id": "both", "products": ["bluebook", "original"]},
    }
    assert principal_mod.tenant_products("bb-only") == BLUEBOOK_ONLY
    assert principal_mod.tenant_products("both") == principal_mod.ALL_PRODUCTS
    now[0] += 31  # both cache entries have expired
    repo.down = True
    with caplog.at_level(logging.WARNING, logger="original.principal"):
        assert principal_mod.tenant_products("bb-only") == BLUEBOOK_ONLY
        assert principal_mod.tenant_products("both") == principal_mod.ALL_PRODUCTS
    assert _product_warnings(caplog) == [
        "tenant products lookup failed for bb-only; using last known",
        "tenant products lookup failed for both; using last known",
    ]
    # A refresh that finds no record keeps the last known value too.
    repo.down = False
    repo.records = {}
    now[0] += 6
    assert principal_mod.tenant_products("both") == principal_mod.ALL_PRODUCTS


def test_tenant_products_does_not_call_a_cached_fallback_last_known(flaky_products, caplog):
    """A cached fallback is not a "last known" value: with nothing ever read
    successfully, repeated failures keep saying "bluebook only"."""
    repo, now = flaky_products
    repo.down = True
    with caplog.at_level(logging.WARNING, logger="original.principal"):
        assert principal_mod.tenant_products("never-read") == BLUEBOOK_ONLY
        now[0] += 6  # the fallback has expired; the lookup fails again
        assert principal_mod.tenant_products("never-read") == BLUEBOOK_ONLY
    assert _product_warnings(caplog) == [
        "tenant products lookup failed for never-read; using bluebook only"
    ] * 2


def test_tenant_products_retries_a_failed_lookup_after_five_seconds(flaky_products):
    repo, now = flaky_products
    repo.down = True
    assert principal_mod.tenant_products("retry-t") == BLUEBOOK_ONLY
    repo.down = False
    repo.records = {"retry-t": {"tenant_id": "retry-t", "products": ["bluebook", "original"]}}
    now[0] += 4
    assert principal_mod.tenant_products("retry-t") == BLUEBOOK_ONLY
    now[0] += 2
    assert principal_mod.tenant_products("retry-t") == principal_mod.ALL_PRODUCTS
    # A healthy answer is cached for the full 30 seconds again.
    calls = repo.calls
    repo.down = True
    now[0] += 29
    assert principal_mod.tenant_products("retry-t") == principal_mod.ALL_PRODUCTS
    assert repo.calls == calls


def test_tenant_products_demo_tenant_never_looks_up(flaky_products):
    repo, _ = flaky_products
    repo.down = True
    assert principal_mod.tenant_products(principal_mod.DEMO_TENANT) == principal_mod.ALL_PRODUCTS
    assert principal_mod.tenant_products("") == principal_mod.ALL_PRODUCTS
    assert principal_mod.tenant_products(None) == principal_mod.ALL_PRODUCTS
    assert repo.calls == 0


def test_tenant_products_lookup_failure_in_the_demo_keeps_every_product(
    flaky_products, monkeypatch, caplog
):
    """Off a real deploy the demo sandbox depends on unregistered tenants
    holding every product, so a failed lookup still resolves to both."""
    repo, _ = flaky_products
    monkeypatch.setattr(principal_mod, "_is_real_deploy", lambda: False)
    repo.down = True
    with caplog.at_level(logging.WARNING, logger="original.principal"):
        assert principal_mod.tenant_products("x-tenant") == principal_mod.ALL_PRODUCTS
    assert _product_warnings(caplog) == [
        "tenant products lookup failed for x-tenant; using all (demo)"
    ]


def test_tenant_products_cache_expires_after_30_seconds(monkeypatch):
    """An operator script run in another process (Render's shell) changes the
    products row but cannot clear this process's cache, so the entry must
    expire on its own for the change to reach the gate without a restart."""
    repo = get_repository()
    repo.put_tenant("ttl-t", "TTL", environment="pilot")
    repo.set_tenant_products("ttl-t", ["bluebook"])
    now = [1000.0]
    monkeypatch.setattr(principal_mod, "_clock", lambda: now[0])
    assert principal_mod.tenant_products("ttl-t") == frozenset({"bluebook"})
    # Another process's write: the repository changes, the cache is untouched.
    repo.set_tenant_products("ttl-t", ["bluebook", "original"])
    now[0] += 29
    assert principal_mod.tenant_products("ttl-t") == frozenset({"bluebook"})
    now[0] += 2
    assert principal_mod.tenant_products("ttl-t") == frozenset({"bluebook", "original"})
    # invalidate_tenant_cache() still clears it at once.
    repo.set_tenant_products("ttl-t", ["bluebook"])
    principal_mod.invalidate_tenant_cache()
    assert principal_mod.tenant_products("ttl-t") == frozenset({"bluebook"})


def test_patch_tenant_products_upgrades_and_is_operator_only(live_client, guarded):
    t = _signup(live_client)
    tid = t["tenant_id"]
    h = {**_operator(), "X-Guard-Token": GUARD}
    # A teacher cannot upgrade their own workspace.
    r = live_client.patch(
        f"/tenants/{tid}",
        json={"products": ["bluebook", "original"]},
        headers={**_auth(t["token"]), "X-Guard-Token": GUARD},
    )
    assert r.status_code == 403
    assert live_client.get("/students", headers=_auth(t["token"])).status_code == 403
    r = live_client.patch(f"/tenants/{tid}", json={"products": ["bluebook", "original"]}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["products"] == ["bluebook", "original"]
    # The gate sees the change immediately (cache invalidated).
    assert live_client.get("/students", headers=_auth(t["token"])).status_code == 200


@pytest.mark.parametrize("products", [[], ["bogus"], ["original", "nope"]])
def test_patch_tenant_products_validation(live_client, guarded, products):
    t = _signup(live_client)
    h = {**_operator(), "X-Guard-Token": GUARD}
    r = live_client.patch(f"/tenants/{t['tenant_id']}", json={"products": products}, headers=h)
    assert r.status_code == 422


def test_patch_unknown_tenant_is_404(live_client, guarded):
    h = {**_operator(), "X-Guard-Token": GUARD}
    r = live_client.patch("/tenants/nope", json={"products": ["bluebook"]}, headers=h)
    assert r.status_code == 404


def test_create_tenant_requires_a_slug_and_accepts_products(live_client):
    bad = live_client.post("/tenants", json={"tenant_id": "Not A Slug", "name": "X"})
    assert bad.status_code == 422
    ok = live_client.post(
        "/tenants", json={"tenant_id": "bb-school", "name": "BB", "products": ["bluebook"]}
    )
    assert ok.status_code == 201, ok.text
    assert get_repository().get_tenant("bb-school")["products"] == ["bluebook"]
    bad_products = live_client.post(
        "/tenants", json={"tenant_id": "bb2", "name": "BB", "products": ["x"]}
    )
    assert bad_products.status_code == 422


def test_new_tenant_on_a_real_deploy_defaults_to_bluebook_only(live_client, guarded, pilot_env):
    """An operator provisioning an institution without naming products must
    not silently hand it Original (an unset product list means every product)."""
    h = {**_operator(), "X-Guard-Token": GUARD}
    r = live_client.post(
        "/tenants",
        json={"tenant_id": "new-sem", "name": "New", "environment": "pilot"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert get_repository().get_tenant("new-sem")["products"] == ["bluebook"]
    # Re-registering an existing tenant leaves its products alone.
    get_repository().set_tenant_products("new-sem", ["bluebook", "original"])
    live_client.post(
        "/tenants",
        json={"tenant_id": "new-sem", "name": "New", "environment": "pilot"},
        headers=h,
    )
    assert get_repository().get_tenant("new-sem")["products"] == ["bluebook", "original"]


def test_teacher_lists_only_their_own_tenant(live_client):
    a = _signup(live_client, "a@x.edu")
    _signup(live_client, "b@x.edu")
    listed = live_client.get("/tenants", headers=_auth(a["token"])).json()
    assert [t["tenant_id"] for t in listed] == [a["tenant_id"]]
    everyone = live_client.get("/tenants", headers=_operator()).json()
    assert len(everyone) >= 2


# ── Accounts, invites, passwords ──────────────────────────────────────────────


def test_invited_student_cannot_sign_in_until_redeemed(live_client):
    t = _signup(live_client)
    course = _course(live_client, t["token"])
    row = _add_students(live_client, t["token"], course, "stu@school.edu")[0]
    assert row["state"] == "invited"
    assert row["account"] == "created"
    assert row["invite_path"].startswith(invites_mod.INVITE_PATH)
    r = live_client.post("/auth/login", json={"email": "stu@school.edu", "password": "!invited"})
    assert r.status_code == 401


def test_redeem_sets_password_enrols_and_signs_in(live_client):
    t = _signup(live_client)
    course = _course(live_client, t["token"])
    s = _student(live_client, t["token"], course)
    assert s["role"] == "student"
    assert s["student_id"] == student_auth.derive_student_id(t["tenant_id"], "stu@school.edu")
    assert s["products"] == ["bluebook"]
    login = live_client.post("/auth/login", json={"email": "stu@school.edu", "password": PW})
    assert login.status_code == 200
    body = login.json()
    assert body["role"] == "student" and body["student_id"] == s["student_id"]
    assert student_auth.verify_session(body["token"])["sid"] == s["student_id"]
    me = live_client.get("/bluebook/me", headers=_auth(body["token"])).json()
    assert [c["course_id"] for c in me["courses"]] == [course]
    assert me["has_account"] is True


def test_student_invite_needs_no_terms(live_client):
    """Only an invited professor accepts the teacher terms on redeem; a
    student's set-password call is unchanged (no accept_terms)."""
    t = _signup(live_client)
    _student(live_client, t["token"], _course(live_client, t["token"]))
    item = get_repository().list_audit(action="invite_redeem", tenant_id=t["tenant_id"])
    assert "terms_version" not in item["items"][0]["details"]


def test_invite_is_single_use(live_client):
    t = _signup(live_client)
    row = _add_students(live_client, t["token"], _course(live_client, t["token"]), "s@x.edu")[0]
    tok = _token_of(row["invite_path"])
    assert (
        live_client.post("/auth/invite/redeem", json={"token": tok, "password": PW}).status_code
        == 200
    )
    again = live_client.post("/auth/invite/redeem", json={"token": tok, "password": PW})
    assert again.status_code == 400


def test_reissue_voids_the_previous_link(live_client):
    t = _signup(live_client)
    course = _course(live_client, t["token"])
    row = _add_students(live_client, t["token"], course, "s@x.edu")[0]
    r = live_client.post(
        f"/bluebook/courses/{course}/students/{row['student_id']}/invite", headers=_auth(t["token"])
    )
    assert r.status_code == 200
    old = live_client.post(
        "/auth/invite/redeem", json={"token": _token_of(row["invite_path"]), "password": PW}
    )
    assert old.status_code == 400
    new = live_client.post(
        "/auth/invite/redeem", json={"token": _token_of(r.json()["invite_path"]), "password": PW}
    )
    assert new.status_code == 200


def test_expired_invite_is_rejected(live_client, monkeypatch):
    monkeypatch.setattr(invites_mod, "INVITE_TTL", timedelta(seconds=-1))
    t = _signup(live_client)
    row = _add_students(live_client, t["token"], _course(live_client, t["token"]), "s@x.edu")[0]
    r = live_client.post(
        "/auth/invite/redeem", json={"token": _token_of(row["invite_path"]), "password": PW}
    )
    assert r.status_code == 400


@pytest.mark.parametrize("token", ["", "garbage", "x" * 40])
def test_unknown_invite_token_is_uniform_400(live_client, token):
    r = live_client.post("/auth/invite/redeem", json={"token": token, "password": PW})
    assert r.status_code == 400
    assert "invalid, expired, or already used" in r.json()["detail"]


def test_short_password_does_not_burn_the_invite(live_client):
    t = _signup(live_client)
    row = _add_students(live_client, t["token"], _course(live_client, t["token"]), "s@x.edu")[0]
    tok = _token_of(row["invite_path"])
    assert (
        live_client.post("/auth/invite/redeem", json={"token": tok, "password": "x"}).status_code
        == 422
    )
    assert (
        live_client.post("/auth/invite/redeem", json={"token": tok, "password": PW}).status_code
        == 200
    )


def test_invite_redemption_is_throttled(live_client):
    codes = [
        live_client.post(
            "/auth/invite/redeem", json={"token": f"bad{i}", "password": PW}
        ).status_code
        for i in range(11)
    ]
    assert codes[:10] == [400] * 10
    assert codes[10] == 429


def test_password_change(live_client):
    t = _signup(live_client, "pw@x.edu")
    h = _auth(t["token"])
    wrong = live_client.post(
        "/auth/password",
        json={"current_password": "nope-nope", "new_password": "n3w-passw0rd"},
        headers=h,
    )
    assert wrong.status_code == 401
    short = live_client.post(
        "/auth/password", json={"current_password": PW, "new_password": "x"}, headers=h
    )
    assert short.status_code == 422
    ok = live_client.post(
        "/auth/password", json={"current_password": PW, "new_password": "n3w-passw0rd"}, headers=h
    )
    assert ok.status_code == 200
    assert (
        live_client.post(
            "/auth/login", json={"email": "pw@x.edu", "password": "n3w-passw0rd"}
        ).status_code
        == 200
    )


def test_password_change_needs_an_account(live_client):
    assert (
        live_client.post(
            "/auth/password", json={"current_password": PW, "new_password": PW}
        ).status_code
        == 401
    )
    # A launch-link student has a session but no account row.
    sid = student_auth.derive_student_id("acme", "link@acme.edu")
    r = live_client.post(
        "/auth/password",
        json={"current_password": PW, "new_password": PW},
        headers=_auth(student_auth.mint_session(sid)),
    )
    assert r.status_code == 401


def test_operator_reset_link_for_a_teacher(live_client, guarded):
    t = _signup(live_client, "lost@x.edu")
    uid = get_repository().get_user_by_email("lost@x.edu")["user_id"]
    h = {**_operator(), "X-Guard-Token": GUARD}
    r = live_client.post(f"/admin/users/{uid}/reset-link", headers=h)
    assert r.status_code == 200, r.text
    tok = _token_of(r.json()["invite_path"])
    redeemed = live_client.post(
        "/auth/invite/redeem", json={"token": tok, "password": "fresh-passw0rd"}
    )
    assert redeemed.status_code == 200
    assert redeemed.json()["role"] == "professor"
    assert redeemed.json()["tenant_id"] == t["tenant_id"]


def test_operator_reset_link_refuses_students_and_non_operators(live_client, guarded):
    t = _signup(live_client)
    s = _student(live_client, t["token"], _course(live_client, t["token"]))
    h = {**_operator(), "X-Guard-Token": GUARD}
    assert (
        live_client.post(f"/admin/users/{s['student_id']}/reset-link", headers=h).status_code == 404
    )
    assert live_client.post("/admin/users/nobody/reset-link", headers=h).status_code == 404
    as_teacher = {**_auth(t["token"]), "X-Guard-Token": GUARD}
    uid = get_repository().get_user_by_email("teach@school.edu")["user_id"]
    # Bluebook-only teachers are stopped by the product gate on /admin/*.
    assert live_client.post(f"/admin/users/{uid}/reset-link", headers=as_teacher).status_code == 403


def test_non_operator_staff_cannot_mint_reset_links(live_client, guarded, principal_headers):
    get_repository().put_tenant("both", "Both", environment="pilot")
    h = {**principal_headers("p1", "professor", "both"), "X-Guard-Token": GUARD}
    assert live_client.post("/admin/users/anyone/reset-link", headers=h).status_code == 403


# ── Rosters ───────────────────────────────────────────────────────────────────


def test_roster_reports_bad_rows_without_stopping(live_client):
    t = _signup(live_client)
    course = _course(live_client, t["token"])
    r = live_client.post(
        f"/bluebook/courses/{course}/students",
        json={
            "students": [
                {"email": "good@x.edu"},
                {"email": "GOOD@x.edu"},  # duplicate after normalising
                {"email": "not-an-email"},
                {"email": "teach@school.edu"},  # the teacher's own login
            ]
        },
        headers=_auth(t["token"]),
    )
    assert r.status_code == 200
    rows = r.json()["students"]
    assert len(rows) == 3
    assert rows[0]["email"] == "good@x.edu" and rows[0]["state"] == "invited"
    assert "error" in rows[1] and "error" in rows[2]


def test_roster_batch_bounds(live_client, monkeypatch):
    t = _signup(live_client)
    course = _course(live_client, t["token"])
    assert (
        live_client.post(
            f"/bluebook/courses/{course}/students", json={"students": []}, headers=_auth(t["token"])
        ).status_code
        == 422
    )
    monkeypatch.setattr(rules, "MAX_ROSTER_BATCH", 1)
    r = live_client.post(
        f"/bluebook/courses/{course}/students",
        json={"students": [{"email": "a@x.edu"}, {"email": "b@x.edu"}]},
        headers=_auth(t["token"]),
    )
    assert r.status_code == 422


def test_roster_is_tenant_scoped(live_client):
    a = _signup(live_client, "a@x.edu")
    b = _signup(live_client, "b@x.edu")
    course = _course(live_client, a["token"])
    r = live_client.post(
        f"/bluebook/courses/{course}/students",
        json={"students": [{"email": "s@x.edu"}]},
        headers=_auth(b["token"]),
    )
    assert r.status_code == 404
    assert (
        live_client.get(
            f"/bluebook/courses/{course}/students", headers=_auth(b["token"])
        ).status_code
        == 404
    )


def test_roster_list_remove_and_rejoin(live_client):
    t = _signup(live_client)
    course = _course(live_client, t["token"])
    s = _student(live_client, t["token"], course, "active@x.edu")
    _add_students(live_client, t["token"], course, "pending@x.edu")
    rows = live_client.get(
        f"/bluebook/courses/{course}/students", headers=_auth(t["token"])
    ).json()["students"]
    states = {r["email"]: r["state"] for r in rows}
    assert states == {"active@x.edu": "active", "pending@x.edu": "invited"}
    pending = next(r for r in rows if r["state"] == "invited")
    assert pending["invite_expires_at"]
    # Re-adding an active student issues no link.
    again = _add_students(live_client, t["token"], course, "active@x.edu")[0]
    assert again["account"] == "existing" and again["invite_path"] is None
    h = _auth(t["token"])
    assert (
        live_client.delete(
            f"/bluebook/courses/{course}/students/{s['student_id']}", headers=h
        ).status_code
        == 200
    )
    assert (
        live_client.delete(
            f"/bluebook/courses/{course}/students/{s['student_id']}", headers=h
        ).status_code
        == 404
    )
    reissue = live_client.post(
        f"/bluebook/courses/{course}/students/{s['student_id']}/invite", headers=h
    )
    assert reissue.status_code == 404


def test_roster_creates_original_profile_only_when_tenant_has_original(
    live_client, principal_headers
):
    t = _signup(live_client)
    course = _course(live_client, t["token"])
    row = _add_students(live_client, t["token"], course, "bb@x.edu")[0]
    assert get_repository().get(row["student_id"]) is None

    get_repository().put_tenant("both-school", "Both", environment="pilot")
    principal_mod.invalidate_tenant_cache()
    h = principal_headers("p1", "professor", "both-school")
    c2 = live_client.post("/bluebook/courses", json={"name": "C"}, headers=h).json()["id"]
    r = live_client.post(
        f"/bluebook/courses/{c2}/students", json={"students": [{"email": "o@x.edu"}]}, headers=h
    )
    sid = r.json()["students"][0]["student_id"]
    assert get_repository().get(sid) is not None
    assert live_client.get(f"/students/{sid}", headers=h).status_code == 200


def test_launch_link_enrolment_shows_as_link_state(live_client):
    t = _signup(live_client)
    course = _course(live_client, t["token"])
    exam = _exam(live_client, t["token"], course_id=course)
    sid = student_auth.derive_student_id(t["tenant_id"], "linkonly@x.edu")
    tok = student_auth.mint_launch_token(sid, t["tenant_id"], exam="Midterm", exam_id=exam["id"])
    r = live_client.get(f"/bluebook/launch?t={tok}")
    assert r.status_code == 200
    assert "exam_id=" + exam["id"] in r.text
    rows = live_client.get(
        f"/bluebook/courses/{course}/students", headers=_auth(t["token"])
    ).json()["students"]
    assert rows == [
        {"student_id": sid, "email": None, "name": None, "state": "link", "invite_expires_at": None}
    ]


def test_launch_link_tells_the_page_which_products_the_workspace_holds(live_client):
    """Without original_products the SPA assumes Original, calls the gated
    /students routes, gets 403 and never seals the submission."""
    t = _signup(live_client)
    sid = student_auth.derive_student_id(t["tenant_id"], "linkonly@x.edu")
    tok = student_auth.mint_launch_token(sid, t["tenant_id"], exam="Midterm")
    page = live_client.get(f"/bluebook/launch?t={tok}").text
    stored = re.search(r'setItem\("original_products",("[^)]*")\)', page)
    assert stored is not None
    assert json.loads(json.loads(stored.group(1))) == ["bluebook"]


def test_launch_token_without_exam_id_is_unchanged():
    tok = student_auth.mint_launch_token("a:b", "a", exam="E")
    assert "eid" not in student_auth.verify_launch_token(tok)


# ── Free-tier caps ────────────────────────────────────────────────────────────


def test_student_cap(live_client, monkeypatch):
    monkeypatch.setattr(rules, "MAX_ENROLLED_STUDENTS", 2)
    t = _signup(live_client)
    course = _course(live_client, t["token"])
    _add_students(live_client, t["token"], course, "a@x.edu", "b@x.edu")
    # Re-adding existing students does not count against the cap.
    _add_students(live_client, t["token"], course, "a@x.edu")
    r = live_client.post(
        f"/bluebook/courses/{course}/students",
        json={"students": [{"email": "c@x.edu"}]},
        headers=_auth(t["token"]),
    )
    assert r.status_code == 403


def test_exam_cap(live_client, monkeypatch):
    monkeypatch.setattr(rules, "MAX_EXAMS", 1)
    t = _signup(live_client)
    _exam(live_client, t["token"])
    r = live_client.post("/bluebook/exams", json={"title": "Two"}, headers=_auth(t["token"]))
    assert r.status_code == 403


def test_submission_cap(live_client, monkeypatch):
    monkeypatch.setattr(rules, "MAX_SUBMISSIONS_PER_MONTH", 1)
    t = _signup(live_client)
    exam = _exam(live_client, t["token"])
    _seal(live_client, t["token"], exam["id"], "")
    r = live_client.post(
        "/bluebook/submissions",
        json={"exam_id": exam["id"], "word_count": 1},
        headers=_auth(t["token"]),
    )
    assert r.status_code == 403


def test_caps_do_not_apply_to_operator_tenants(live_client, monkeypatch, principal_headers):
    monkeypatch.setattr(rules, "MAX_EXAMS", 0)
    get_repository().put_tenant("school", "School", environment="pilot")
    h = principal_headers("p1", "professor", "school")
    assert live_client.post("/bluebook/exams", json={"title": "T"}, headers=h).status_code == 201


# ── Exams, windows, courses ───────────────────────────────────────────────────

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "exam,expected",
    [
        ({"status": "DRAFT"}, rules.DRAFT),
        ({"status": None}, rules.DRAFT),
        ({"status": "ACTIVE"}, rules.OPEN),
        ({"status": "CLOSED"}, rules.CLOSED),
        ({"status": "archived"}, rules.CLOSED),
        ({"status": "ACTIVE", "opens_at": _iso(NOW + timedelta(hours=1))}, rules.UPCOMING),
        ({"status": "ACTIVE", "opens_at": _iso(NOW - timedelta(hours=1))}, rules.OPEN),
        ({"status": "ACTIVE", "closes_at": _iso(NOW)}, rules.CLOSED),
        ({"status": "ACTIVE", "closes_at": _iso(NOW + timedelta(seconds=1))}, rules.OPEN),
        (
            {
                "status": "ACTIVE",
                "opens_at": _iso(NOW - timedelta(hours=2)),
                "closes_at": _iso(NOW - timedelta(hours=1)),
            },
            rules.CLOSED,
        ),
    ],
)
def test_exam_state(exam, expected):
    assert rules.exam_state(exam, NOW) == expected


def test_session_seconds_clipped_by_close():
    exam = {"duration": 90, "closes_at": _iso(NOW + timedelta(minutes=30))}
    assert rules.session_seconds(exam, NOW) == 30 * 60
    assert rules.session_seconds({"duration": 90}, NOW) == 90 * 60
    assert rules.session_seconds({"duration": "junk"}, NOW) == 90 * 60
    assert rules.session_seconds({"duration": 90, "closes_at": _iso(NOW)}, NOW) == 60


def test_parse_instant():
    assert rules.parse_instant("") is None
    assert rules.parse_instant("2026-09-28T12:00:00Z") == NOW
    assert rules.parse_instant("2026-09-28T12:00:00") == NOW  # naive = UTC
    assert rules.parse_instant(NOW) == NOW
    with pytest.raises(ValueError):
        rules.parse_instant("tomorrow")


def test_create_exam_validation(live_client):
    a = _signup(live_client, "a@x.edu")
    b = _signup(live_client, "b@x.edu")
    other_course = _course(live_client, b["token"])
    h = _auth(a["token"])
    assert (
        live_client.post(
            "/bluebook/exams", json={"title": "T", "course_id": other_course}, headers=h
        ).status_code
        == 422
    )
    assert (
        live_client.post(
            "/bluebook/exams", json={"title": "T", "opens_at": "soon"}, headers=h
        ).status_code
        == 422
    )
    r = live_client.post(
        "/bluebook/exams",
        json={"title": "T", "opens_at": _iso(NOW), "closes_at": _iso(NOW - timedelta(hours=1))},
        headers=h,
    )
    assert r.status_code == 422


def test_exam_patch_and_delete(live_client):
    t = _signup(live_client)
    h = _auth(t["token"])
    course = _course(live_client, t["token"])
    exam = _exam(live_client, t["token"], status="DRAFT")
    r = live_client.patch(
        f"/bluebook/exams/{exam['id']}",
        json={
            "title": "Final",
            "status": "active",
            "course_id": course,
            "opens_at": _iso(NOW),
            "closes_at": _iso(NOW + timedelta(days=1)),
            "duration": 45,
            "prompt": "New prompt",
            "minWords": 10,
            "maxWords": 20,
            "course": "ETH",
            "conditions": {"blockCopy": True},
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    got = r.json()
    assert (got["title"], got["status"], got["course_id"], got["duration"]) == (
        "Final",
        "ACTIVE",
        course,
        45,
    )
    assert got["opens_at"].startswith("2026-09-28T12:00:00")
    # null clears the window and the course
    cleared = live_client.patch(
        f"/bluebook/exams/{exam['id']}",
        json={"opens_at": None, "closes_at": None, "course_id": None},
        headers=h,
    ).json()
    assert (cleared["opens_at"], cleared["closes_at"], cleared["course_id"]) == (None, None, None)
    assert (
        live_client.patch(
            f"/bluebook/exams/{exam['id']}", json={"title": " "}, headers=h
        ).status_code
        == 422
    )
    assert (
        live_client.patch(
            f"/bluebook/exams/{exam['id']}", json={"course_id": "nope"}, headers=h
        ).status_code
        == 422
    )
    assert live_client.delete(f"/bluebook/exams/{exam['id']}", headers=h).status_code == 200
    assert live_client.delete(f"/bluebook/exams/{exam['id']}", headers=h).status_code == 404


def test_exam_with_submissions_cannot_be_deleted(live_client):
    t = _signup(live_client)
    exam = _exam(live_client, t["token"])
    _seal(live_client, t["token"], exam["id"], "")
    assert (
        live_client.delete(f"/bluebook/exams/{exam['id']}", headers=_auth(t["token"])).status_code
        == 409
    )


def test_other_tenant_cannot_touch_an_exam(live_client):
    a = _signup(live_client, "a@x.edu")
    b = _signup(live_client, "b@x.edu")
    exam = _exam(live_client, a["token"])
    hb = _auth(b["token"])
    assert (
        live_client.patch(
            f"/bluebook/exams/{exam['id']}", json={"title": "X"}, headers=hb
        ).status_code
        == 404
    )
    assert live_client.delete(f"/bluebook/exams/{exam['id']}", headers=hb).status_code == 404
    assert live_client.get(f"/bluebook/exams/{exam['id']}/export", headers=hb).status_code == 404


def test_course_patch_and_delete(live_client):
    t = _signup(live_client)
    h = _auth(t["token"])
    course = _course(live_client, t["token"])
    r = live_client.patch(
        f"/bluebook/courses/{course}",
        json={"name": "Renamed", "code": "R1", "term": "Fall", "status": "archived"},
        headers=h,
    )
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["status"]) == ("Renamed", "ARCHIVED")
    assert (
        live_client.patch(f"/bluebook/courses/{course}", json={"name": ""}, headers=h).status_code
        == 422
    )
    exam = _exam(live_client, t["token"], course_id=course)
    assert live_client.delete(f"/bluebook/courses/{course}", headers=h).status_code == 409
    live_client.delete(f"/bluebook/exams/{exam['id']}", headers=h)
    _add_students(live_client, t["token"], course, "s@x.edu")
    assert live_client.delete(f"/bluebook/courses/{course}", headers=h).status_code == 200
    assert get_repository().list_enrollments_for_course(course) == []
    assert live_client.delete(f"/bluebook/courses/{course}", headers=h).status_code == 404


def test_list_counts_are_computed(live_client):
    t = _signup(live_client)
    h = _auth(t["token"])
    course = _course(live_client, t["token"])
    exam = _exam(live_client, t["token"], course_id=course)
    _add_students(live_client, t["token"], course, "a@x.edu", "b@x.edu")
    _seal(live_client, t["token"], exam["id"], "")
    exams = live_client.get("/bluebook/exams", headers=h).json()["exams"]
    assert exams[0]["submissions"] == 1
    courses = live_client.get("/bluebook/courses", headers=h).json()["courses"]
    assert (courses[0]["students"], courses[0]["exams"]) == (2, 1)


# ── Student dashboard ─────────────────────────────────────────────────────────


@pytest.fixture
def classroom(live_client):
    t = _signup(live_client)
    course = _course(live_client, t["token"])
    other_course = _course(live_client, t["token"], "Other")
    s = _student(live_client, t["token"], course)
    now = datetime.now(UTC)
    exams = {
        "open": _exam(
            live_client,
            t["token"],
            title="Open",
            course_id=course,
            closes_at=_iso(now + timedelta(minutes=20)),
        ),
        "upcoming": _exam(
            live_client,
            t["token"],
            title="Soon",
            course_id=course,
            opens_at=_iso(now + timedelta(days=1)),
        ),
        "closed": _exam(
            live_client,
            t["token"],
            title="Past",
            course_id=course,
            closes_at=_iso(now - timedelta(minutes=1)),
        ),
        "draft": _exam(live_client, t["token"], title="Draft", course_id=course, status="DRAFT"),
        "other": _exam(live_client, t["token"], title="Other", course_id=other_course),
        "workspace": _exam(live_client, t["token"], title="Everyone"),
    }
    return {"teacher": t, "student": s, "course": course, "exams": exams}


def test_me_requires_a_student(live_client, classroom):
    assert live_client.get("/bluebook/me").status_code == 401
    assert (
        live_client.get("/bluebook/me", headers=_auth(classroom["teacher"]["token"])).status_code
        == 403
    )


def test_my_exams_lists_what_the_student_may_see(live_client, classroom):
    h = _auth(classroom["student"]["token"])
    exams = {
        e["title"]: e for e in live_client.get("/bluebook/me/exams", headers=h).json()["exams"]
    }
    assert set(exams) == {"Open", "Soon", "Past", "Everyone"}
    assert exams["Open"]["state"] == "open"
    assert exams["Soon"]["state"] == "upcoming"
    assert exams["Past"]["state"] == "closed"
    assert "prompt" not in exams["Open"]


def test_my_exam_withholds_the_prompt_until_open(live_client, classroom):
    h = _auth(classroom["student"]["token"])
    ex = classroom["exams"]
    assert (
        live_client.get(f"/bluebook/me/exams/{ex['upcoming']['id']}", headers=h).json()["prompt"]
        is None
    )
    assert (
        live_client.get(f"/bluebook/me/exams/{ex['open']['id']}", headers=h).json()["prompt"]
        == "Discuss virtue."
    )
    for key in ("draft", "other"):
        assert live_client.get(f"/bluebook/me/exams/{ex[key]['id']}", headers=h).status_code == 404


def test_my_exam_is_tenant_scoped(live_client, classroom):
    other = _signup(live_client, "other@x.edu")
    foreign = _exam(live_client, other["token"])
    h = _auth(classroom["student"]["token"])
    assert live_client.get(f"/bluebook/me/exams/{foreign['id']}", headers=h).status_code == 404


def test_start_pins_a_clipped_deadline_and_no_proctor_token(live_client, classroom):
    h = _auth(classroom["student"]["token"])
    ex = classroom["exams"]
    r = live_client.post(f"/bluebook/me/exams/{ex['open']['id']}/start", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["duration_seconds"] <= 20 * 60
    assert body["proctor_token"] is None  # Bluebook-only: never profiled
    assert body["exam"]["prompt"] == "Discuss virtue."
    again = live_client.post(f"/bluebook/me/exams/{ex['open']['id']}/start", headers=h).json()
    assert again["deadline_at"] == body["deadline_at"]
    assert (
        live_client.post(f"/bluebook/me/exams/{ex['upcoming']['id']}/start", headers=h).status_code
        == 409
    )
    assert (
        live_client.post(f"/bluebook/me/exams/{ex['closed']['id']}/start", headers=h).status_code
        == 409
    )
    listed = {
        e["title"]: e for e in live_client.get("/bluebook/me/exams", headers=h).json()["exams"]
    }
    assert listed["Open"]["session"]["deadline_at"] == body["deadline_at"]


def test_start_after_submitting_is_409(live_client, classroom):
    s = classroom["student"]
    ex = classroom["exams"]["open"]
    _seal(live_client, s["token"], ex["id"], s["student_id"], text="done")
    r = live_client.post(f"/bluebook/me/exams/{ex['id']}/start", headers=_auth(s["token"]))
    assert r.status_code == 409


def test_start_mints_a_proctor_token_when_tenant_has_original(live_client, principal_headers):
    get_repository().put_tenant("both-school", "Both", environment="pilot")
    principal_mod.invalidate_tenant_cache()
    h = principal_headers("p1", "professor", "both-school")
    course = live_client.post("/bluebook/courses", json={"name": "C"}, headers=h).json()["id"]
    exam = live_client.post(
        "/bluebook/exams", json={"title": "T", "status": "ACTIVE", "course_id": course}, headers=h
    ).json()
    row = live_client.post(
        f"/bluebook/courses/{course}/students", json={"students": [{"email": "s@x.edu"}]}, headers=h
    ).json()["students"][0]
    s = live_client.post(
        "/auth/invite/redeem", json={"token": _token_of(row["invite_path"]), "password": PW}
    ).json()
    r = live_client.post(f"/bluebook/me/exams/{exam['id']}/start", headers=_auth(s["token"]))
    assert r.status_code == 200
    assert student_auth.verify_proctor_attestation(r.json()["proctor_token"], s["student_id"])


# ── Submissions ───────────────────────────────────────────────────────────────


def test_seal_stores_text_and_warnings_and_strips_scores(live_client, classroom):
    s = classroom["student"]
    t = classroom["teacher"]
    ex = classroom["exams"]["open"]
    warnings = [{"type": "tab_switch", "at": "2026-09-28T12:01:00Z"}, {"type": "fullscreen_exit"}]
    out = _seal(
        live_client,
        s["token"],
        ex["id"],
        s["student_id"],
        text="=HYPERLINK(evil) my essay",
        warnings=warnings,
        stylometric=88,
        ai_score=12,
    )
    sub_id = out["id"]

    mine = live_client.get("/bluebook/me/submissions", headers=_auth(s["token"])).json()[
        "submissions"
    ]
    assert [m["id"] for m in mine] == [sub_id]
    assert "stylometric" not in mine[0] and "text" not in mine[0]
    detail = live_client.get(f"/bluebook/me/submissions/{sub_id}", headers=_auth(s["token"])).json()
    assert detail["text"].endswith("my essay")

    teacher = live_client.get(f"/bluebook/submissions/{sub_id}", headers=_auth(t["token"])).json()
    assert teacher["warnings"] == warnings
    assert teacher["text"].endswith("my essay")
    assert "stylometric" not in teacher and "aiScore" not in teacher
    stored = get_repository().get_bluebook_submission(sub_id)
    assert stored["stylometric"] is None and stored["aiScore"] is None

    listed = live_client.get("/bluebook/submissions", headers=_auth(t["token"])).json()[
        "submissions"
    ]
    assert "stylometric" not in listed[0]

    csv_resp = live_client.get(f"/bluebook/exams/{ex['id']}/export", headers=_auth(t["token"]))
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(csv_resp.text)))
    assert rows[0]["email"] == "stu@school.edu"
    assert rows[0]["warning_count"] == "2"
    assert rows[0]["text"].startswith("'=")  # formula injection neutralised


def test_scores_kept_for_tenants_with_original(live_client, principal_headers):
    get_repository().put_tenant("both-school", "Both", environment="pilot")
    principal_mod.invalidate_tenant_cache()
    h = principal_headers("p1", "professor", "both-school")
    r = live_client.post(
        "/bluebook/submissions", json={"word_count": 1, "stylometric": 70, "ai_score": 5}, headers=h
    )
    sub = live_client.get(f"/bluebook/submissions/{r.json()['id']}", headers=h).json()
    assert (sub["stylometric"], sub["aiScore"]) == (70, 5)


def test_other_students_submission_is_404(live_client, classroom):
    t = classroom["teacher"]
    s = classroom["student"]
    other = _student(live_client, t["token"], classroom["course"], "other@x.edu")
    out = _seal(
        live_client, other["token"], classroom["exams"]["open"]["id"], other["student_id"], text="x"
    )
    assert (
        live_client.get(
            f"/bluebook/me/submissions/{out['id']}", headers=_auth(s["token"])
        ).status_code
        == 404
    )
    stranger = _signup(live_client, "stranger@x.edu")
    assert (
        live_client.get(
            f"/bluebook/submissions/{out['id']}", headers=_auth(stranger["token"])
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "warnings",
    ["not-a-list", [{"at": "x"}], [{"type": 3}], ["x"]],
)
def test_bad_warnings_are_422(live_client, warnings):
    t = _signup(live_client)
    r = live_client.post(
        "/bluebook/submissions", json={"warnings": warnings}, headers=_auth(t["token"])
    )
    assert r.status_code == 422


def test_too_many_warnings_is_422(monkeypatch):
    monkeypatch.setattr(rules, "MAX_WARNINGS", 1)
    with pytest.raises(ValueError):
        rules.clean_warnings([{"type": "a"}, {"type": "b"}])
    assert rules.clean_warnings(None) == []


def test_overlong_text_is_413(live_client, monkeypatch):
    monkeypatch.setattr(rules, "MAX_TEXT_CHARS", 5)
    t = _signup(live_client)
    r = live_client.post(
        "/bluebook/submissions", json={"text": "123456"}, headers=_auth(t["token"])
    )
    assert r.status_code == 413


def test_csv_escapes_every_formula_prefix():
    subs = [
        {
            "id": "1",
            "student_id": "",
            "candidate": "@cmd",
            "text": "+1",
            "status": "-x",
            "created_at": None,
        }
    ]
    out = list(csv.reader(io.StringIO(rules.submissions_csv(subs, {}))))
    row = dict(zip(out[0], out[1], strict=True))
    assert (row["name"], row["text"], row["status"]) == ("'@cmd", "'+1", "'-x")


def test_is_self_serve():
    assert rules.is_self_serve({"meta": {"plan": "self_serve"}})
    assert not rules.is_self_serve({"meta": {}})
    assert not rules.is_self_serve(None)


# ── Erasure ───────────────────────────────────────────────────────────────────


def test_delete_student_purges_account_invites_and_roster(live_client, principal_headers):
    get_repository().put_tenant("both-school", "Both", environment="pilot")
    principal_mod.invalidate_tenant_cache()
    h = principal_headers("p1", "professor", "both-school")
    course = live_client.post("/bluebook/courses", json={"name": "C"}, headers=h).json()["id"]
    sid = live_client.post(
        f"/bluebook/courses/{course}/students",
        json={"students": [{"email": "gone@x.edu"}]},
        headers=h,
    ).json()["students"][0]["student_id"]
    repo = get_repository()
    assert repo.get_user(sid) and repo.latest_invite_for_user(sid)
    assert repo.delete_student(sid) is True
    assert repo.get_user(sid) is None
    assert repo.latest_invite_for_user(sid) is None
    assert repo.list_enrollments_for_student(sid) == []
    # The teacher's own login row is untouched.
    assert repo.get_user("p1") is None or repo.get_user("p1")["role"] != "student"


def _erase(client, student_id, headers):
    return client.delete(f"/bluebook/students/{student_id}", headers=headers)


def test_teacher_erases_a_bluebook_only_student_and_their_work(live_client, classroom):
    t, s = classroom["teacher"], classroom["student"]
    sid, h = s["student_id"], _auth(t["token"])
    ex = classroom["exams"]["open"]
    live_client.post(f"/bluebook/me/exams/{ex['id']}/start", headers=_auth(s["token"]))
    _seal(live_client, s["token"], ex["id"], sid, text="my own words")
    repo = get_repository()
    assert repo.get(sid) is None  # Bluebook-only: never profiled
    assert repo.list_bluebook_submissions_for_student(sid)

    r = _erase(live_client, sid, h)
    assert r.status_code == 200, r.text
    assert r.json() == {"erased": sid}

    assert repo.get_user(sid) is None
    assert repo.latest_invite_for_user(sid) is None
    assert repo.list_enrollments_for_student(sid) == []
    assert repo.list_bluebook_submissions_for_student(sid) == []
    assert repo.get_bluebook_session(ex["id"], sid) is None
    roster = live_client.get(f"/bluebook/courses/{classroom['course']}/students", headers=h)
    assert roster.json()["students"] == []
    login = live_client.post("/auth/login", json={"email": "stu@school.edu", "password": PW})
    assert login.status_code == 401
    # Exactly one row survives: the erasure receipt, naming the teacher.
    audit = repo.list_audit(student_id=sid)["items"]
    assert [(a["action"], a["result"], a["actor"]) for a in audit] == [
        ("bluebook_student_erase", "ok", get_repository().get_user_by_email(t["email"])["user_id"])
    ]
    # Erasing again finds nothing and keeps the receipt.
    assert _erase(live_client, sid, h).status_code == 404
    assert repo.list_audit(student_id=sid, action="bluebook_student_erase")["total"] == 2


def test_erasure_is_tenant_scoped(live_client, classroom):
    sid = classroom["student"]["student_id"]
    other = _signup(live_client, "other@x.edu")
    assert _erase(live_client, sid, _auth(other["token"])).status_code == 404
    assert get_repository().get_user(sid) is not None
    # A flat id belongs to no workspace, so staff cannot reach it either.
    assert _erase(live_client, "flat-id", _auth(other["token"])).status_code == 404


def test_operator_may_erase_across_workspaces(live_client, classroom):
    sid = classroom["student"]["student_id"]
    assert _erase(live_client, sid, _operator()).status_code == 200
    assert get_repository().get_user(sid) is None


def test_students_cannot_erase(live_client, classroom):
    s = classroom["student"]
    assert _erase(live_client, s["student_id"], _auth(s["token"])).status_code == 403
    assert get_repository().get_user(s["student_id"]) is not None


def test_unknown_student_is_404_and_audited(live_client):
    t = _signup(live_client)
    ghost = f"{t['tenant_id']}:ghost"
    assert _erase(live_client, ghost, _auth(t["token"])).status_code == 404
    items = get_repository().list_audit(student_id=ghost)["items"]
    assert [(a["action"], a["result"]) for a in items] == [("bluebook_student_erase", "not_found")]


def test_student_with_an_original_profile_is_refused(live_client, principal_headers):
    get_repository().put_tenant("both-school", "Both", environment="pilot")
    principal_mod.invalidate_tenant_cache()
    h = principal_headers("p1", "professor", "both-school")
    course = live_client.post("/bluebook/courses", json={"name": "C"}, headers=h).json()["id"]
    sid = _add_students(live_client, h["Authorization"][7:], course, "kept@x.edu")[0]["student_id"]
    assert get_repository().get(sid) is not None
    r = _erase(live_client, sid, h)
    assert r.status_code == 409
    assert "Original" in r.json()["detail"]
    assert get_repository().get_user(sid) is not None


def test_erased_students_old_session_is_revoked(live_client, classroom):
    """A student session is stateless, so erasure alone left it valid until
    expiry: the erased student could still sign in to the dashboard, start a
    sitting, and seal a submission, recreating rows for an erased identity."""
    t, s = classroom["teacher"], classroom["student"]
    sid, old = s["student_id"], _auth(s["token"])
    ex = classroom["exams"]["open"]
    assert student_auth.verify_session(s["token"])["acct"] == 1
    assert live_client.get("/bluebook/me", headers=old).status_code == 200
    assert _erase(live_client, sid, _auth(t["token"])).status_code == 200

    # Still correctly signed and unexpired, but the account is gone.
    assert student_auth.verify_session(s["token"]) is not None
    assert live_client.get("/bluebook/me", headers=old).status_code == 401
    assert live_client.get("/student-auth/me", headers=old).status_code == 401
    start = live_client.post(f"/bluebook/me/exams/{ex['id']}/start", headers=old)
    assert start.status_code == 401
    seal = live_client.post(
        "/bluebook/submissions",
        json={"exam_id": ex["id"], "student_id": sid, "word_count": 3, "text": "back again"},
        headers=old,
    )
    assert seal.status_code == 401
    repo = get_repository()
    assert repo.list_bluebook_submissions_for_student(sid) == []
    assert repo.get_bluebook_session(ex["id"], sid) is None


def test_launch_link_session_has_no_account_and_still_works(live_client):
    """Launch-link students have no users row by design: their session must
    not be mistaken for an erased account's."""
    t = _signup(live_client)
    course = _course(live_client, t["token"])
    exam = _exam(live_client, t["token"], course_id=course)
    sid = student_auth.derive_student_id(t["tenant_id"], "linkonly@x.edu")
    tok = student_auth.mint_launch_token(sid, t["tenant_id"], exam="Midterm", exam_id=exam["id"])
    page = live_client.get(f"/bluebook/launch?t={tok}").text
    session = re.search(r'setItem\("original_session_token","([^"]+)"\)', page).group(1)
    assert "acct" not in student_auth.verify_session(session)
    assert get_repository().get_user(sid) is None

    me = live_client.get("/bluebook/me", headers=_auth(session))
    assert me.status_code == 200
    assert me.json()["has_account"] is False
    assert (
        live_client.post(
            f"/bluebook/me/exams/{exam['id']}/start", headers=_auth(session)
        ).status_code
        == 200
    )
    _seal(live_client, session, exam["id"], sid, text="sat via a link")


def test_revoked_principal_matches_nothing():
    p = principal_mod.REVOKED
    assert not p.is_demo and not p.products
    with pytest.raises(principal_mod.TenantAccessError):
        principal_mod.assert_student_access(p, "acme:someone")
    with pytest.raises(principal_mod.TenantAccessError):
        principal_mod.assert_tenant_access(p, "acme")


def test_account_session_lookup_failure_fails_closed(monkeypatch):
    class Broken:
        def get_user(self, _):
            raise RuntimeError("db down")

    monkeypatch.setattr("original.repository.get_repository", lambda: Broken())
    assert principal_mod._account_session_live("acme:x") is False


def test_account_claim_on_a_non_student_row_is_revoked(live_client):
    """An ``acct`` session whose sid names a staff row is not a live student
    account (it cannot be minted legitimately, but must not authenticate)."""
    t = _signup(live_client)
    staff_id = get_repository().get_user_by_email(t["email"])["user_id"]
    forged = student_auth.mint_session(staff_id, account=True)
    assert live_client.get("/bluebook/me", headers=_auth(forged)).status_code == 401


def test_invited_hash_never_verifies():
    assert users_mod.verify_password("!invited", users_mod.INVITED_PASSWORD_HASH) is False
    assert users_mod.is_activated({"password_hash": "pbkdf2_sha256$1$aa$bb"})
    assert not users_mod.is_activated({"password_hash": users_mod.INVITED_PASSWORD_HASH})


# ── Edge branches ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw", ["not json", "[]", "{}", None, '["bluebook"]'])
def test_stored_products_parse_falls_back_to_both(raw):
    from original import store

    expected = ["bluebook"] if raw == '["bluebook"]' else ["original", "bluebook"]
    assert store._parse_products(raw) == expected


def test_clean_warnings_rejects_a_non_list():
    with pytest.raises(ValueError):
        rules.clean_warnings("tab_hidden")


def test_redeem_handles_naive_expiry_and_a_lost_race(monkeypatch):
    repo = get_repository()
    repo.put_tenant("inv-t", "Inv", environment="pilot")
    repo.put_invite(
        {
            "invite_id": "naive",
            "tenant_id": "inv-t",
            "user_id": "inv-t:ann",
            "course_id": None,
            "token_hash": invites_mod.token_hash("tok-naive"),
            "created_by": "p",
            "created_at": "2026-01-01T00:00:00",
            "expires_at": "2099-01-01T00:00:00",  # no offset: read as UTC
        }
    )
    # Another request redeemed it between our read and our write. (Patched
    # per call rather than undone: monkeypatch.undo() would also revert the
    # store_reset fixture's database redirect.)
    real = type(repo).redeem_invite
    calls = []

    def racing(self, invite_id):
        calls.append(invite_id)
        return False if len(calls) == 1 else real(self, invite_id)

    monkeypatch.setattr(type(repo), "redeem_invite", racing)
    assert invites_mod.redeem("tok-naive") is None
    assert invites_mod.redeem("tok-naive")["invite_id"] == "naive"


def test_demo_sandbox_reads_only_demo_submissions(live_client):
    """Off a real deploy the anonymous demo is a staff principal scoped to
    the demo tenant: it may read demo rows, never another tenant's."""
    own = live_client.post("/bluebook/submissions", json={"word_count": 1, "text": "demo"})
    assert own.status_code == 201
    assert live_client.get(f"/bluebook/submissions/{own.json()['id']}").json()["text"] == "demo"
    t = _signup(live_client)
    theirs = live_client.post(
        "/bluebook/submissions", json={"word_count": 1}, headers=_auth(t["token"])
    ).json()["id"]
    assert live_client.get(f"/bluebook/submissions/{theirs}").status_code == 404


def test_can_touch_without_a_principal_is_false():
    from types import SimpleNamespace

    from original.routers import bluebook as bb

    assert bb._can_touch(SimpleNamespace(state=SimpleNamespace()), "any") is False


def test_signup_closed_refuses_and_creates_nothing(live_client, monkeypatch):
    monkeypatch.setenv("SELF_SERVE_SIGNUP", "0")
    r = live_client.post(
        "/auth/signup",
        json={"email": "closed@school.edu", "password": PW, "name": "C", "accept_terms": True},
    )
    assert r.status_code == 403
    assert "invitation-only" in r.json()["detail"]
    assert get_repository().get_user_by_email("closed@school.edu") is None


def test_health_reports_whether_signup_is_open(live_client, monkeypatch):
    monkeypatch.delenv("SELF_SERVE_SIGNUP", raising=False)
    assert live_client.get("/health").json()["signup_open"] is True
    monkeypatch.setenv("SELF_SERVE_SIGNUP", "0")
    assert live_client.get("/health").json()["signup_open"] is False


# ── Submissions never cross a workspace boundary ─────────────────────────────


def test_staff_cannot_seal_against_another_workspaces_exam(live_client):
    a = _signup(live_client, "a@x.edu")
    b = _signup(live_client, "b@x.edu")
    exam_b = _exam(live_client, b["token"])

    r = live_client.post(
        "/bluebook/submissions",
        json={"exam_id": exam_b["id"], "word_count": 1, "text": "mine"},
        headers=_auth(a["token"]),
    )

    assert r.status_code == 404
    assert r.json()["detail"] == "exam not found"
    assert get_repository().list_bluebook_submissions_for_exam(exam_b["id"]) == []


def test_a_student_cannot_seal_against_another_workspaces_exam(live_client):
    a = _signup(live_client, "a@x.edu")
    b = _signup(live_client, "b@x.edu")
    stu_a = _student(live_client, a["token"], _course(live_client, a["token"]))
    exam_b = _exam(live_client, b["token"])

    r = live_client.post(
        "/bluebook/submissions",
        json={"exam_id": exam_b["id"], "student_id": stu_a["student_id"], "word_count": 1},
        headers=_auth(stu_a["token"]),
    )

    assert r.status_code == 404
    assert get_repository().list_bluebook_submissions_for_exam(exam_b["id"]) == []


def test_staff_cannot_seal_for_another_workspaces_student(live_client):
    a = _signup(live_client, "a@x.edu")
    b = _signup(live_client, "b@x.edu")
    stu_b = _student(live_client, b["token"], _course(live_client, b["token"]))
    exam_a = _exam(live_client, a["token"])

    r = live_client.post(
        "/bluebook/submissions",
        json={"exam_id": exam_a["id"], "student_id": stu_b["student_id"], "word_count": 1},
        headers=_auth(a["token"]),
    )

    assert r.status_code == 403
    assert r.json()["detail"] == "Cross-tenant access denied."
    assert get_repository().list_bluebook_submissions_for_exam(exam_a["id"]) == []


def test_staff_can_still_seal_for_their_own_student_and_for_an_unstored_exam(live_client):
    a = _signup(live_client, "a@x.edu")
    stu = _student(live_client, a["token"], _course(live_client, a["token"]))
    exam = _exam(live_client, a["token"])

    own = live_client.post(
        "/bluebook/submissions",
        json={"exam_id": exam["id"], "student_id": stu["student_id"], "word_count": 1},
        headers=_auth(a["token"]),
    )
    unstored = live_client.post(
        "/bluebook/submissions",
        json={"exam_id": "sample-exam-not-in-the-repository", "word_count": 1},
        headers=_auth(a["token"]),
    )

    assert (own.status_code, unstored.status_code) == (201, 201)


def _plant_foreign_row(exam_id, tenant_id, student_id, text):
    """A row for ``exam_id`` that belongs to another workspace, written straight
    into the repository (the seal route no longer produces one)."""
    get_repository().put_bluebook_submission(
        {
            "id": "foreignrow000001",
            "exam_id": exam_id,
            "tenant_id": tenant_id,
            "student_id": student_id,
            "candidate": "Foreign Candidate",
            "exam_title": "Midterm",
            "text": text,
            "answers": [text],
            "warnings": [],
            "word_count": 5,
            "time_min": 1,
            "status": "SUBMITTED",
            "submission_uuid": "foreign-row-uuid",
            "late": 0,
        }
    )


def test_a_foreign_row_on_my_exam_is_not_exported_or_shown_live(live_client):
    a = _signup(live_client, "a@x.edu")
    b = _signup(live_client, "b@x.edu")
    exam_a = _exam(live_client, a["token"])
    _seal(live_client, a["token"], exam_a["id"], "", text="my own sealed words")
    _plant_foreign_row(exam_a["id"], b["tenant_id"], f"{b['tenant_id']}:outsider", "SECRET-OF-B")
    h = _auth(a["token"])

    export = live_client.get(f"/bluebook/exams/{exam_a['id']}/export", headers=h)
    live = live_client.get(f"/bluebook/exams/{exam_a['id']}/live", headers=h)

    assert export.status_code == 200
    assert "my own sealed words" in export.text
    assert "SECRET-OF-B" not in export.text and "Foreign Candidate" not in export.text
    assert len(list(csv.DictReader(io.StringIO(export.text)))) == 1
    assert live.status_code == 200
    assert "outsider" not in live.text and "Foreign Candidate" not in live.text
    audit = get_repository().list_audit(action="bluebook_export")["items"][0]
    assert audit["details"]["rows"] == 1
