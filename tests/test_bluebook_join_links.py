"""Forwardable course sign-up links (2026-10).

A per-email invite belongs to one student and works once. A course's
sign-up link can be forwarded: anyone who opens it creates their own
student account (with consent) and joins the course. These tests cover the
teacher controls (on, off, replace), the public join, consent, the
existing-account rules, the free-tier cap, and that invites are unchanged.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from original import bluebook_rules as rules
from original import join_links as join_links_mod
from original import principal as principal_mod
from original import student_auth
from original.repository import get_repository

PW = "s3cret-passw0rd"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _isolate(store_reset, live_app):
    import original.api as api

    api._login_attempts.clear()
    principal_mod.invalidate_tenant_cache()
    yield
    api._login_attempts.clear()
    principal_mod.invalidate_tenant_cache()


def _signup(client, email="teach@school.edu", name="Ms Teach") -> dict:
    r = client.post(
        "/auth/signup", json={"email": email, "password": PW, "name": name, "accept_terms": True}
    )
    assert r.status_code == 201, r.text
    return r.json()


def _course(client, token, name="Ethics 101") -> str:
    r = client.post(
        "/bluebook/courses", json={"name": name, "code": "ETH101"}, headers=_auth(token)
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _enable(client, token, course) -> dict:
    r = client.post(f"/bluebook/courses/{course}/join-link", headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _tok(link: dict) -> str:
    return parse_qs(urlparse(link["join_path"]).query)["join"][0]


def _join(client, token, email="new@x.edu", name="New Student", accept=True, pw=PW):
    return client.post(
        "/auth/join",
        json={"token": token, "name": name, "email": email, "password": pw, "accept_terms": accept},
    )


def _roster(client, token, course) -> list[dict]:
    return client.get(f"/bluebook/courses/{course}/students", headers=_auth(token)).json()[
        "students"
    ]


@pytest.fixture
def setup(live_client):
    t = _signup(live_client)
    course = _course(live_client, t["token"])
    return t, course


# ── Teacher controls ──────────────────────────────────────────────────────────


def test_link_is_off_by_default(live_client, setup):
    t, course = setup
    r = live_client.get(f"/bluebook/courses/{course}/join-link", headers=_auth(t["token"]))
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert r.json()["join_url"] is None


def test_enable_returns_an_absolute_link_and_is_idempotent(live_client, setup):
    t, course = setup
    link = _enable(live_client, t["token"], course)
    assert link["enabled"] is True
    assert link["join_path"].startswith("/bluebook/?join=")
    assert link["join_url"].startswith("http")
    assert link["join_url"].endswith(link["join_path"])
    # Seen again later, and a second "turn on" keeps the same link.
    again = live_client.get(f"/bluebook/courses/{course}/join-link", headers=_auth(t["token"]))
    assert again.json()["join_path"] == link["join_path"]
    assert _enable(live_client, t["token"], course)["join_path"] == link["join_path"]


def test_join_url_uses_forwarded_https(live_client, setup):
    t, course = setup
    r = live_client.post(
        f"/bluebook/courses/{course}/join-link",
        headers={**_auth(t["token"]), "X-Forwarded-Proto": "https"},
    )
    assert r.json()["join_url"].startswith("https://")


def test_only_the_token_hash_is_stored(live_client, setup):
    t, course = setup
    link = _enable(live_client, t["token"], course)
    row = get_repository().active_join_link_for_course(course)
    assert row["token_hash"] == join_links_mod.token_hash(_tok(link))
    assert _tok(link) not in str(row)


def test_disable_and_regenerate(live_client, setup):
    t, course = setup
    first = _tok(_enable(live_client, t["token"], course))
    r = live_client.post(
        f"/bluebook/courses/{course}/join-link/regenerate", headers=_auth(t["token"])
    )
    assert r.status_code == 200
    second = _tok(r.json())
    assert second != first
    # The old link is dead; the new one works.
    assert live_client.post("/auth/join/info", json={"token": first}).status_code == 404
    assert _join(live_client, first).status_code == 400
    assert live_client.post("/auth/join/info", json={"token": second}).status_code == 200

    r = live_client.delete(f"/bluebook/courses/{course}/join-link", headers=_auth(t["token"]))
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert _join(live_client, second).status_code == 400
    # Turning it back on makes a fresh link; the disabled one stays dead.
    third = _tok(_enable(live_client, t["token"], course))
    assert third not in (first, second)
    assert live_client.post("/auth/join/info", json={"token": second}).status_code == 404


def test_teacher_controls_are_tenant_scoped(live_client, setup):
    t, course = setup
    other = _signup(live_client, email="other@school.edu")
    for method, path in (
        ("get", f"/bluebook/courses/{course}/join-link"),
        ("post", f"/bluebook/courses/{course}/join-link"),
        ("post", f"/bluebook/courses/{course}/join-link/regenerate"),
        ("delete", f"/bluebook/courses/{course}/join-link"),
    ):
        r = getattr(live_client, method)(path, headers=_auth(other["token"]))
        assert r.status_code == 404, (method, path)


def test_students_cannot_manage_links(live_client, setup):
    t, course = setup
    tok = _tok(_enable(live_client, t["token"], course))
    stu = _join(live_client, tok).json()
    r = live_client.post(f"/bluebook/courses/{course}/join-link", headers=_auth(stu["token"]))
    assert r.status_code in (401, 403, 404)


def test_secret_rotation_asks_for_a_new_link(live_client, setup, monkeypatch):
    t, course = setup
    _enable(live_client, t["token"], course)
    monkeypatch.setenv("SECRET_KEY", "a-different-secret-for-this-test")
    view = join_links_mod.current(course)
    assert view["enabled"] is True and view["join_path"] is None and view["needs_replacing"]
    # "Turn on" replaces a link that can no longer be shown.
    fresh = join_links_mod.enable(t["tenant_id"], course, "x")
    assert fresh["join_path"] and not fresh["needs_replacing"]


def test_deleting_the_course_deletes_its_link(live_client, setup):
    t, course = setup
    tok = _tok(_enable(live_client, t["token"], course))
    assert live_client.delete(
        f"/bluebook/courses/{course}", headers=_auth(t["token"])
    ).status_code in (
        200,
        204,
    )
    assert get_repository().get_join_link_by_hash(join_links_mod.token_hash(tok)) is None
    assert live_client.post("/auth/join/info", json={"token": tok}).status_code == 404


# ── Public join ───────────────────────────────────────────────────────────────


def test_info_shows_course_and_teacher(live_client, setup):
    t, course = setup
    tok = _tok(_enable(live_client, t["token"], course))
    r = live_client.post("/auth/join/info", json={"token": tok})
    assert r.status_code == 200
    assert r.json() == {
        "course_name": "Ethics 101",
        "course_code": "ETH101",
        "teacher_name": "Ms Teach",
    }


@pytest.mark.parametrize("token", ["", "nope", "x" * 500])
def test_unknown_token_is_uniform(live_client, token):
    assert live_client.post("/auth/join/info", json={"token": token}).status_code == 404
    assert _join(live_client, token).status_code == 400


def test_join_creates_enrols_and_signs_in(live_client, setup):
    t, course = setup
    tok = _tok(_enable(live_client, t["token"], course))
    r = _join(live_client, tok, email="Ada@X.edu", name="Ada L")
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["role"] == "student"
    sid = student_auth.derive_student_id(t["tenant_id"], "ada@x.edu")
    me = live_client.get("/bluebook/me", headers=_auth(out["token"])).json()
    assert me["student_id"] == sid
    assert [c["course_id"] for c in me["courses"]] == [course]
    rows = _roster(live_client, t["token"], course)
    assert [(r["email"], r["name"], r["state"]) for r in rows] == [("ada@x.edu", "Ada L", "active")]
    # The password works for a normal sign-in afterwards.
    assert (
        live_client.post("/auth/login", json={"email": "ada@x.edu", "password": PW}).status_code
        == 200
    )
    # Forwarding works: a second person uses the same link.
    assert _join(live_client, tok, email="grace@x.edu", name="Grace").status_code == 201
    assert len(_roster(live_client, t["token"], course)) == 2
    audit = get_repository().list_audit(tenant_id=t["tenant_id"], action="join_link_signup")[
        "items"
    ]
    assert audit and audit[0]["details"]["terms_version"]


def test_consent_is_required_and_nothing_is_created_without_it(live_client, setup):
    t, course = setup
    tok = _tok(_enable(live_client, t["token"], course))
    r = _join(live_client, tok, accept=False)
    assert r.status_code == 422
    assert "student notice" in r.json()["detail"]
    assert get_repository().get_user_by_email("new@x.edu") is None
    assert _roster(live_client, t["token"], course) == []


@pytest.mark.parametrize(
    "fields,code",
    [
        ({"name": ""}, 422),
        ({"email": "not-an-email"}, 422),
        ({"pw": "short"}, 422),
    ],
)
def test_join_validation(live_client, setup, fields, code):
    t, course = setup
    tok = _tok(_enable(live_client, t["token"], course))
    assert _join(live_client, tok, **fields).status_code == code
    assert _roster(live_client, t["token"], course) == []


def test_active_account_is_never_taken_over(live_client, setup):
    t, course = setup
    tok = _tok(_enable(live_client, t["token"], course))
    assert _join(live_client, tok, email="ada@x.edu").status_code == 201
    r = _join(live_client, tok, email="ada@x.edu", pw="a-different-password")
    assert r.status_code == 409
    assert "Sign in" in r.json()["detail"]

    # The original password still works; the new one does not.
    def login(pw):
        return live_client.post("/auth/login", json={"email": "ada@x.edu", "password": pw})

    assert login(PW).status_code == 200
    assert login("a-different-password").status_code == 401


def test_teacher_email_is_never_taken_over(live_client, setup):
    t, course = setup
    tok = _tok(_enable(live_client, t["token"], course))
    r = _join(live_client, tok, email="teach@school.edu", pw="another-password")
    assert r.status_code == 409
    assert (
        live_client.post(
            "/auth/login", json={"email": "teach@school.edu", "password": PW}
        ).status_code
        == 200
    )


def test_email_from_another_workspace_is_refused(live_client, setup):
    t, course = setup
    other = _signup(live_client, email="other@school.edu")
    oc = _course(live_client, other["token"], name="Other")
    live_client.post(
        f"/bluebook/courses/{oc}/students",
        json={"students": [{"email": "shared@x.edu"}]},
        headers=_auth(other["token"]),
    )
    tok = _tok(_enable(live_client, t["token"], course))
    r = _join(live_client, tok, email="shared@x.edu")
    assert r.status_code == 409
    assert _roster(live_client, t["token"], course) == []


def test_unactivated_roster_account_is_activated_and_its_invite_voided(live_client, setup):
    t, course = setup
    row = live_client.post(
        f"/bluebook/courses/{course}/students",
        json={"students": [{"email": "added@x.edu", "name": "Added By Teacher"}]},
        headers=_auth(t["token"]),
    ).json()["students"][0]
    invite_token = parse_qs(urlparse(row["invite_path"]).query)["invite"][0]
    tok = _tok(_enable(live_client, t["token"], course))
    r = _join(live_client, tok, email="added@x.edu", name="Typed Name")
    assert r.status_code == 201, r.text
    assert r.json()["tenant_id"] == t["tenant_id"]
    rows = _roster(live_client, t["token"], course)
    assert [(x["student_id"], x["state"]) for x in rows] == [(row["student_id"], "active")]
    # The teacher's one-time link can no longer replace the student's password.
    r = live_client.post(
        "/auth/invite/redeem", json={"token": invite_token, "password": "hijack-pass"}
    )
    assert r.status_code == 400


def test_cap_is_enforced(live_client, setup, monkeypatch):
    monkeypatch.setattr(rules, "MAX_ENROLLED_STUDENTS", 1)
    t, course = setup
    tok = _tok(_enable(live_client, t["token"], course))
    assert _join(live_client, tok, email="a@x.edu").status_code == 201
    r = _join(live_client, tok, email="b@x.edu")
    assert r.status_code == 403
    assert get_repository().get_user_by_email("b@x.edu") is None


def test_join_failures_are_throttled(live_client):
    import original.api as api

    for _ in range(api._LOGIN_MAX_ATTEMPTS):
        _join(live_client, "bad-token")
    assert _join(live_client, "bad-token").status_code == 429


def test_original_tenant_gets_a_profile(live_client, principal_headers):
    get_repository().put_tenant("both-school", "Both", environment="pilot")
    principal_mod.invalidate_tenant_cache()
    h = principal_headers("p1", "professor", "both-school")
    c = live_client.post("/bluebook/courses", json={"name": "C"}, headers=h).json()["id"]
    link = live_client.post(f"/bluebook/courses/{c}/join-link", headers=h).json()
    r = _join(live_client, _tok(link), email="o@x.edu")
    assert r.status_code == 201, r.text
    sid = student_auth.derive_student_id("both-school", "o@x.edu")
    assert get_repository().get(sid) is not None


# ── Signed-in student joins another course ────────────────────────────────────


def test_signed_in_student_joins_with_the_link(live_client, setup):
    t, course = setup
    tok = _tok(_enable(live_client, t["token"], course))
    stu = _join(live_client, tok, email="ada@x.edu").json()
    c2 = _course(live_client, t["token"], name="Logic")
    tok2 = _tok(_enable(live_client, t["token"], c2))
    r = live_client.post("/bluebook/me/join", json={"token": tok2}, headers=_auth(stu["token"]))
    assert r.status_code == 200, r.text
    me = live_client.get("/bluebook/me", headers=_auth(stu["token"])).json()
    assert {c["course_id"] for c in me["courses"]} == {course, c2}
    # A dead link, or a course in another workspace, does not enrol.
    live_client.delete(f"/bluebook/courses/{c2}/join-link", headers=_auth(t["token"]))
    r = live_client.post("/bluebook/me/join", json={"token": tok2}, headers=_auth(stu["token"]))
    assert r.status_code == 404
    other = _signup(live_client, email="other@school.edu")
    oc = _course(live_client, other["token"], name="Other")
    otok = _tok(_enable(live_client, other["token"], oc))
    r = live_client.post("/bluebook/me/join", json={"token": otok}, headers=_auth(stu["token"]))
    assert r.status_code == 403
    assert _roster(live_client, other["token"], oc) == []


def test_me_join_needs_a_student(live_client, setup):
    t, course = setup
    tok = _tok(_enable(live_client, t["token"], course))
    assert live_client.post("/bluebook/me/join", json={"token": tok}).status_code == 401


# ── The per-email invite flow is unchanged ────────────────────────────────────


def test_invite_flow_still_works_with_a_link_on(live_client, setup):
    t, course = setup
    _enable(live_client, t["token"], course)
    row = live_client.post(
        f"/bluebook/courses/{course}/students",
        json={"students": [{"email": "inv@x.edu"}]},
        headers=_auth(t["token"]),
    ).json()["students"][0]
    assert row["invite_path"].startswith("/bluebook/?invite=")
    token = parse_qs(urlparse(row["invite_path"]).query)["invite"][0]
    r = live_client.post("/auth/invite/redeem", json={"token": token, "password": PW})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "student"
    # Single use as before.
    assert (
        live_client.post("/auth/invite/redeem", json={"token": token, "password": PW}).status_code
        == 400
    )
