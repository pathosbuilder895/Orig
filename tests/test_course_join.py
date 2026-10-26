"""Course join links (2026-10): students join an Original Collections course
by link or code (original/routers/course_join.py).

Grouped by concern:

* the teacher's settings: off by default, on, off, reset, domain limit
* joining: new email, the teacher's roster row for that email, an existing
  account with its own password, and every way a join is refused
* approval: pending students, approve, approve all, decline
* what a pending student can and cannot reach
* rate limits, caps, isolation between teachers, and erasure
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from original import principal as principal_mod
from original.repository import get_repository
from original.routers import _shared
from original.routers import course_join as cj

PW = "s3cret-passw0rd"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _isolate(store_reset, live_app):
    _shared._login_attempts.clear()
    principal_mod.invalidate_tenant_cache()
    yield
    _shared._login_attempts.clear()
    principal_mod.invalidate_tenant_cache()


def _signup(client, email="teach@school.edu", name="Ms Teach") -> dict:
    r = client.post(
        "/auth/signup", json={"email": email, "password": PW, "name": name, "accept_terms": True}
    )
    assert r.status_code == 201, r.text
    return r.json()


def _course(client, token, name="Ethics 101", code="ETH101") -> str:
    r = client.post("/bluebook/courses", json={"name": name, "code": code}, headers=_auth(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _exam(client, token, **fields) -> dict:
    body = {"title": "Midterm", "status": "ACTIVE", "prompt": "Discuss virtue.", **fields}
    r = client.post("/bluebook/exams", json=body, headers=_auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def _settings(client, token, course_id, **fields) -> dict:
    r = client.put(f"/bluebook/courses/{course_id}/join", json=fields, headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _join(client, code, email="ada@school.edu", password=PW, name="Ada", terms=True):
    return client.post(
        f"/auth/join/{code}",
        json={"name": name, "email": email, "password": password, "accept_terms": terms},
    )


def _roster(client, token, course_id) -> list[dict]:
    r = client.get(f"/bluebook/courses/{course_id}/students", headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()["students"]


@pytest.fixture
def teacher(live_client):
    out = _signup(live_client)
    course_id = _course(live_client, out["token"])
    return {"token": out["token"], "tenant": out["tenant_id"], "course": course_id}


@pytest.fixture
def open_course(live_client, teacher):
    """A course with joining switched on; returns teacher info plus its code."""
    s = _settings(live_client, teacher["token"], teacher["course"], enabled=True)
    return {**teacher, "code": s["code"]}


# ── Codes ─────────────────────────────────────────────────────────────────────


def test_codes_never_use_confusable_characters():
    for ch in "O0I1L":
        assert ch not in cj.JOIN_CODE_ALPHABET
    for _ in range(200):
        code = cj.new_code()
        assert len(code) == 6 and set(code) <= set(cj.JOIN_CODE_ALPHABET)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("K7QW3X", "K7QW3X"),
        ("k7q-w3x", "K7QW3X"),
        (" k7q w3x ", "K7QW3X"),
        ("K7QW3", None),  # too short
        ("K7QW3XY", None),  # too long
        ("K7QW30", None),  # 0 is never issued
        ("OOOOOO", None),
        ("", None),
    ],
)
def test_normalize_code(raw, expected):
    assert cj.normalize_code(raw) == expected


# ── Teacher settings ──────────────────────────────────────────────────────────


def test_joining_is_off_until_the_teacher_turns_it_on(live_client, teacher):
    r = live_client.get(
        f"/bluebook/courses/{teacher['course']}/join", headers=_auth(teacher["token"])
    )
    assert r.status_code == 200
    assert r.json() == {
        "enabled": False,
        "code": None,
        "join_path": None,
        "allowed_domain": "",
        "require_approval": False,
    }


def test_turning_joining_on_makes_a_code_and_a_link(live_client, teacher):
    s = _settings(live_client, teacher["token"], teacher["course"], enabled=True)
    assert s["enabled"] is True
    assert cj.normalize_code(s["code"]) == s["code"]
    assert s["join_path"] == f"/bluebook/?join={s['code']}"
    r = live_client.get(f"/auth/join/{s['code']}")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "code": s["code"],
        "course_name": "Ethics 101",
        "course_code": "ETH101",
        "term": "",
        "allowed_domain": "",
        "require_approval": False,
    }


def test_settings_that_leave_a_field_out_keep_it(live_client, open_course):
    t, c = open_course["token"], open_course["course"]
    s = _settings(live_client, t, c, require_approval=True)
    assert (s["enabled"], s["require_approval"], s["code"]) == (True, True, open_course["code"])
    s = _settings(live_client, t, c, allowed_domain="@School.EDU ")
    assert (s["enabled"], s["require_approval"], s["allowed_domain"]) == (True, True, "school.edu")
    s = _settings(live_client, t, c, allowed_domain="")
    assert s["allowed_domain"] == ""


@pytest.mark.parametrize("bad", ["not a domain", "school", "school..edu", "-x.edu", "a@b.edu"])
def test_a_domain_limit_must_be_a_domain(live_client, open_course, bad):
    r = live_client.put(
        f"/bluebook/courses/{open_course['course']}/join",
        json={"allowed_domain": bad},
        headers=_auth(open_course["token"]),
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "Enter a domain like school.edu."


def test_turning_joining_off_stops_the_link_and_on_again_restores_it(live_client, open_course):
    t, c, code = open_course["token"], open_course["course"], open_course["code"]
    off = _settings(live_client, t, c, enabled=False)
    assert (off["enabled"], off["code"]) == (False, code)
    assert live_client.get(f"/auth/join/{code}").status_code == 404
    assert _join(live_client, code).status_code == 404
    on = _settings(live_client, t, c, enabled=True)
    assert on["code"] == code
    assert _join(live_client, code).status_code == 200


def test_reset_kills_the_old_code_and_link(live_client, open_course):
    t, c, old = open_course["token"], open_course["course"], open_course["code"]
    assert _join(live_client, old, email="first@school.edu").status_code == 200
    r = live_client.post(f"/bluebook/courses/{c}/join/reset", headers=_auth(t))
    assert r.status_code == 200, r.text
    new = r.json()["code"]
    assert new != old and r.json()["join_path"] == f"/bluebook/?join={new}"
    assert live_client.get(f"/auth/join/{old}").status_code == 404
    assert _join(live_client, old, email="late@school.edu").status_code == 404
    assert _join(live_client, new, email="second@school.edu").status_code == 200
    # Students who joined with the old code stay on the course.
    emails = {row["email"] for row in _roster(live_client, t, c)}
    assert emails == {"first@school.edu", "second@school.edu"}


def test_reset_before_joining_was_ever_set_gives_a_code_but_stays_off(live_client, teacher):
    r = live_client.post(
        f"/bluebook/courses/{teacher['course']}/join/reset", headers=_auth(teacher["token"])
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is False and r.json()["code"]
    assert live_client.get(f"/auth/join/{r.json()['code']}").status_code == 404


def test_a_drawn_code_another_course_holds_is_drawn_again(live_client, open_course, monkeypatch):
    t = open_course["token"]
    other = _course(live_client, t, name="Logic", code="LOG1")
    drawn = iter([open_course["code"], "ZZZZZZ"])
    monkeypatch.setattr(cj, "new_code", lambda: next(drawn))
    s = _settings(live_client, t, other, enabled=True)
    assert s["code"] == "ZZZZZZ"


def test_giving_up_after_repeated_code_collisions(live_client, open_course, monkeypatch):
    t = open_course["token"]
    other = _course(live_client, t, name="Logic", code="LOG1")
    monkeypatch.setattr(cj, "new_code", lambda: open_course["code"])
    r = live_client.put(f"/bluebook/courses/{other}/join", json={"enabled": True}, headers=_auth(t))
    assert r.status_code == 503
    assert get_repository().get_course_join(other) is None


def test_settings_changes_are_audited(live_client, open_course):
    live_client.post(
        f"/bluebook/courses/{open_course['course']}/join/reset", headers=_auth(open_course["token"])
    )
    actions = [a["action"] for a in get_repository().list_audit(limit=50)["items"]]
    assert "bluebook_join_settings" in actions and "bluebook_join_reset" in actions


# ── Who may change the settings ───────────────────────────────────────────────


def test_another_teacher_cannot_see_or_change_a_course_join(live_client, open_course):
    other = _signup(live_client, email="other@school.edu")
    c = open_course["course"]
    h = _auth(other["token"])
    assert live_client.get(f"/bluebook/courses/{c}/join", headers=h).status_code == 404
    assert (
        live_client.put(
            f"/bluebook/courses/{c}/join", json={"enabled": False}, headers=h
        ).status_code
        == 404
    )
    assert live_client.post(f"/bluebook/courses/{c}/join/reset", headers=h).status_code == 404
    assert (
        live_client.post(f"/bluebook/courses/{c}/join-requests/approve-all", headers=h).status_code
        == 404
    )
    assert live_client.get(f"/auth/join/{open_course['code']}").status_code == 200


def test_a_student_cannot_change_join_settings(live_client, open_course):
    student = _join(live_client, open_course["code"]).json()
    r = live_client.put(
        f"/bluebook/courses/{open_course['course']}/join",
        json={"enabled": False},
        headers=_auth(student["token"]),
    )
    assert r.status_code == 403


# ── Joining ───────────────────────────────────────────────────────────────────


def test_a_new_student_joins_and_lands_in_the_course(live_client, open_course):
    t, c = open_course["token"], open_course["course"]
    exam = _exam(live_client, t, course_id=c)
    r = _join(live_client, open_course["code"], email="Ada@School.edu ")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["role"] == "student" and out["email"] == "ada@school.edu" and out["name"] == "Ada"
    assert out["join"] == {"course_id": c, "course_name": "Ethics 101", "status": "enrolled"}
    me = live_client.get("/bluebook/me", headers=_auth(out["token"])).json()
    assert [x["course_id"] for x in me["courses"]] == [c] and me["pending_courses"] == []
    exams = live_client.get("/bluebook/me/exams", headers=_auth(out["token"])).json()["exams"]
    assert [e["exam_id"] for e in exams] == [exam["id"]]
    [row] = _roster(live_client, t, c)
    assert (row["email"], row["name"], row["state"]) == ("ada@school.edu", "Ada", "active")
    # The password they chose signs them in from now on.
    login = live_client.post("/auth/login", json={"email": "ada@school.edu", "password": PW})
    assert login.status_code == 200 and login.json()["student_id"] == out["student_id"]


def test_a_code_typed_in_lower_case_with_a_hyphen_works(live_client, open_course):
    code = open_course["code"].lower()
    assert _join(live_client, f"{code[:3]}-{code[3:]}").status_code == 200


def test_a_student_with_no_name_gets_their_email_name(live_client, open_course):
    out = _join(live_client, open_course["code"], email="grace@school.edu", name="  ").json()
    assert out["name"] == "grace"


def test_an_email_on_the_roster_is_linked_to_that_row_not_duplicated(live_client, open_course):
    t, c = open_course["token"], open_course["course"]
    r = live_client.post(
        f"/bluebook/courses/{c}/students",
        json={"students": [{"email": "ada@school.edu", "name": "Ada Lovelace"}]},
        headers=_auth(t),
    )
    added = r.json()["students"][0]
    assert added["state"] == "invited"
    out = _join(live_client, open_course["code"], email="ada@school.edu", name="Someone").json()
    assert out["student_id"] == added["student_id"]
    assert out["name"] == "Ada Lovelace"  # the teacher's row is kept as it was
    rows = _roster(live_client, t, c)
    assert [(x["student_id"], x["state"]) for x in rows] == [(added["student_id"], "active")]
    users = [u for u in get_repository().list_users_by_ids([added["student_id"]])]
    assert len(users) == 1
    # The teacher's own invite link still works, so the student it was meant
    # for can always take the account back.
    token = parse_qs(urlparse(added["invite_path"]).query)["invite"][0]
    redeemed = live_client.post(
        "/auth/invite/redeem", json={"token": token, "password": "another-pw-1"}
    )
    assert redeemed.status_code == 200
    bad = live_client.post("/auth/login", json={"email": "ada@school.edu", "password": PW})
    assert bad.status_code == 401


def test_an_existing_account_joins_another_course_with_its_own_password(live_client, open_course):
    t = open_course["token"]
    first = _join(live_client, open_course["code"]).json()
    other = _course(live_client, t, name="Logic", code="LOG1")
    code2 = _settings(live_client, t, other, enabled=True)["code"]
    r = _join(live_client, code2, email="ada@school.edu", password=PW)
    assert r.status_code == 200, r.text
    assert r.json()["student_id"] == first["student_id"]
    me = live_client.get("/bluebook/me", headers=_auth(r.json()["token"])).json()
    assert sorted(x["course_id"] for x in me["courses"]) == sorted([open_course["course"], other])
    # Joining again changes nothing.
    again = _join(live_client, code2, email="ada@school.edu", password=PW)
    assert again.json()["join"]["status"] == "enrolled"
    assert len(_roster(live_client, t, other)) == 1


def test_a_wrong_password_for_an_existing_account_changes_nothing(live_client, open_course):
    first = _join(live_client, open_course["code"]).json()
    other = _course(live_client, open_course["token"], name="Logic", code="LOG1")
    code2 = _settings(live_client, open_course["token"], other, enabled=True)["code"]
    r = _join(live_client, code2, email="ada@school.edu", password="not-the-password")
    assert r.status_code == 401
    assert r.json()["detail"] == cj.NO_MATCH
    assert _roster(live_client, open_course["token"], other) == []
    login = live_client.post("/auth/login", json={"email": "ada@school.edu", "password": PW})
    assert login.status_code == 200 and login.json()["student_id"] == first["student_id"]


def test_every_mismatch_gets_the_same_answer(live_client, open_course):
    """Whatever the reason a join cannot use an email, the answer is the
    same, so the form cannot tell anyone which addresses have accounts."""
    _join(live_client, open_course["code"], email="taken@school.edu")
    other_teacher = _signup(live_client, email="t2@school.edu")
    other_course = _course(live_client, other_teacher["token"], name="Elsewhere", code="E1")
    live_client.post(
        f"/bluebook/courses/{other_course}/students",
        json={"students": [{"email": "invited-elsewhere@school.edu"}]},
        headers=_auth(other_teacher["token"]),
    )
    answers = set()
    for email in ("taken@school.edu", "invited-elsewhere@school.edu", "t2@school.edu"):
        r = _join(live_client, open_course["code"], email=email, password="wrong-password")
        answers.add((r.status_code, r.json()["detail"]))
    assert answers == {(401, cj.NO_MATCH)}


def test_a_teacher_account_with_its_right_password_is_told_why(live_client, open_course):
    r = _join(live_client, open_course["code"], email="teach@school.edu", password=PW)
    assert r.status_code == 409 and "teacher account" in r.json()["detail"]


def test_an_account_in_another_workspace_with_its_right_password_is_told_why(
    live_client, open_course
):
    other_teacher = _signup(live_client, email="t2@school.edu")
    other_course = _course(live_client, other_teacher["token"], name="Elsewhere", code="E1")
    code2 = _settings(live_client, other_teacher["token"], other_course, enabled=True)["code"]
    assert _join(live_client, code2, email="ada@school.edu").status_code == 200
    r = _join(live_client, open_course["code"], email="ada@school.edu")
    assert r.status_code == 409 and "another teacher's workspace" in r.json()["detail"]
    assert _roster(live_client, open_course["token"], open_course["course"]) == []


def test_unknown_switched_off_replaced_and_malformed_codes_answer_alike(live_client, open_course):
    t, c, old = open_course["token"], open_course["course"], open_course["code"]
    off_course = _course(live_client, t, name="Off", code="OFF")
    off_code = _settings(live_client, t, off_course, enabled=True)["code"]
    _settings(live_client, t, off_course, enabled=False)
    live_client.post(f"/bluebook/courses/{c}/join/reset", headers=_auth(t))
    for code in ("ZZZZZZ", off_code, old, "nope"):
        g = live_client.get(f"/auth/join/{code}")
        p = _join(live_client, code)
        assert (g.status_code, g.json()["detail"]) == (404, cj.LINK_NOT_WORKING), code
        assert (p.status_code, p.json()["detail"]) == (404, cj.LINK_NOT_WORKING), code


def test_a_code_whose_course_or_workspace_is_gone_does_not_work(live_client, open_course):
    repo = get_repository()
    repo.put_course_join(
        {
            "course_id": "no-such-course",
            "tenant_id": open_course["tenant"],
            "code": "GHST22",
            "enabled": True,
            "allowed_domain": "",
            "require_approval": False,
        }
    )
    assert live_client.get("/auth/join/GHST22").status_code == 404
    # A join row naming a different workspace from its course.
    other = _signup(live_client, email="t2@school.edu")
    other_course = _course(live_client, other["token"], name="Elsewhere", code="E1")
    repo.put_course_join(
        {
            "course_id": other_course,
            "tenant_id": open_course["tenant"],
            "code": "MSMT22",
            "enabled": True,
            "allowed_domain": "",
            "require_approval": False,
        }
    )
    assert live_client.get("/auth/join/MSMT22").status_code == 404


def test_a_workspace_without_collections_does_not_take_joins(live_client, open_course):
    get_repository().set_tenant_products(open_course["tenant"], ["original"])
    principal_mod.invalidate_tenant_cache()
    assert live_client.get(f"/auth/join/{open_course['code']}").status_code == 404


@pytest.mark.parametrize(
    "fields, detail",
    [
        ({"email": "no-at-sign"}, "Enter a valid email address."),
        ({"email": "x" * 250 + "@a.edu"}, "Enter a valid email address."),
        ({"password": "short"}, "password must be at least 8 characters"),
        ({"terms": False}, cj.TERMS_REQUIRED),
    ],
)
def test_a_join_needs_a_real_email_a_long_enough_password_and_the_terms(
    live_client, open_course, fields, detail
):
    r = _join(live_client, open_course["code"], **fields)
    assert r.status_code == 422 and r.json()["detail"] == detail
    assert _roster(live_client, open_course["token"], open_course["course"]) == []


def test_the_domain_limit(live_client, open_course):
    _settings(live_client, open_course["token"], open_course["course"], allowed_domain="school.edu")
    info = live_client.get(f"/auth/join/{open_course['code']}").json()
    assert info["allowed_domain"] == "school.edu"
    r = _join(live_client, open_course["code"], email="ada@gmail.com")
    assert r.status_code == 422
    assert r.json()["detail"] == "This course only accepts email addresses ending in @school.edu."
    # A look-alike subdomain is not the domain.
    assert _join(live_client, open_course["code"], email="ada@evil-school.edu").status_code == 422
    assert _join(live_client, open_course["code"], email="ada@school.edu").status_code == 200


def test_joining_is_audited_with_the_terms_version(live_client, open_course):
    out = _join(live_client, open_course["code"]).json()
    rows = get_repository().list_audit(student_id=out["student_id"])["items"]
    joined = [r for r in rows if r["action"] == "bluebook_join"]
    assert len(joined) == 1
    details = joined[0]["details"]
    assert details["status"] == "enrolled" and details["account"] == "created"
    assert details["terms_version"]


def test_joining_a_workspace_with_original_creates_the_profile_record(live_client, open_course):
    get_repository().set_tenant_products(open_course["tenant"], ["original", "bluebook"])
    principal_mod.invalidate_tenant_cache()
    out = _join(live_client, open_course["code"]).json()
    assert get_repository().get(out["student_id"]) is not None


def test_join_responses_say_nothing_about_scores_or_the_engine(live_client, open_course):
    texts = [
        live_client.get(f"/auth/join/{open_course['code']}").text,
        _join(live_client, open_course["code"], password="short").text,
        _join(live_client, "ZZZZZZ").text,
        cj.NO_MATCH,
        cj.LINK_NOT_WORKING,
        cj.TERMS_REQUIRED,
    ]
    for text in texts:
        low = text.lower()
        for word in ("score", "consistency", "stylometr", "deviation", "original"):
            assert word not in low, (word, text)


# ── Approval ──────────────────────────────────────────────────────────────────


@pytest.fixture
def approval_course(live_client, open_course):
    _settings(live_client, open_course["token"], open_course["course"], require_approval=True)
    return open_course


def test_with_approval_on_a_joiner_waits_as_pending(live_client, approval_course):
    t, c = approval_course["token"], approval_course["course"]
    assert (
        live_client.get(f"/auth/join/{approval_course['code']}").json()["require_approval"] is True
    )
    r = _join(live_client, approval_course["code"])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["join"]["status"] == "pending"
    [row] = _roster(live_client, t, c)
    assert (row["state"], row["email"], row["name"]) == ("pending", "ada@school.edu", "Ada")
    assert row["requested_at"]
    me = live_client.get("/bluebook/me", headers=_auth(out["token"])).json()
    assert me["courses"] == [] and [x["course_id"] for x in me["pending_courses"]] == [c]
    # Not on the roster yet, so not counted on the course.
    assert get_repository().list_enrollments_for_course(c) == []


def test_a_pending_student_sees_no_collections_at_all(live_client, approval_course):
    t, c = approval_course["token"], approval_course["course"]
    on_course = _exam(live_client, t, course_id=c)
    everyone = _exam(live_client, t, title="Workspace-wide")
    out = _join(live_client, approval_course["code"]).json()
    h = _auth(out["token"])
    assert live_client.get("/bluebook/me/exams", headers=h).json()["exams"] == []
    for exam in (on_course, everyone):
        assert live_client.get(f"/bluebook/me/exams/{exam['id']}", headers=h).status_code == 404
        assert (
            live_client.post(f"/bluebook/me/exams/{exam['id']}/start", headers=h).status_code == 404
        )
    # Once approved, both appear.
    live_client.post(
        f"/bluebook/courses/{c}/join-requests/{out['student_id']}/approve", headers=_auth(t)
    )
    ids = {e["exam_id"] for e in live_client.get("/bluebook/me/exams", headers=h).json()["exams"]}
    assert ids == {on_course["id"], everyone["id"]}
    assert live_client.get(f"/bluebook/me/exams/{everyone['id']}", headers=h).status_code == 200


def test_a_pending_student_cannot_start_or_seal_through_the_older_routes(
    live_client, approval_course
):
    """The session and seal routes apply the dashboard's visibility rules
    (routers/bluebook.py _student_exam_state), so a student waiting for
    approval cannot reach a workspace-wide collection through them either."""
    t, c = approval_course["token"], approval_course["course"]
    everyone = _exam(live_client, t, title="Workspace-wide")
    out = _join(live_client, approval_course["code"]).json()
    h = _auth(out["token"])
    sid = out["student_id"]
    start = live_client.post(
        f"/bluebook/exams/{everyone['id']}/session", headers=h, json={"student_id": sid}
    )
    assert start.status_code == 404
    seal = live_client.post(
        "/bluebook/submissions",
        headers=h,
        json={"exam_id": everyone["id"], "student_id": sid, "word_count": 3},
    )
    assert seal.status_code == 404
    assert get_repository().list_bluebook_submissions_for_student(sid) == []
    # Once approved, the same sitting opens.
    live_client.post(f"/bluebook/courses/{c}/join-requests/{sid}/approve", headers=_auth(t))
    again = live_client.post(
        f"/bluebook/exams/{everyone['id']}/session", headers=h, json={"student_id": sid}
    )
    assert again.status_code == 200, again.text


def test_approving_puts_the_student_on_the_roster(live_client, approval_course):
    t, c = approval_course["token"], approval_course["course"]
    out = _join(live_client, approval_course["code"]).json()
    r = live_client.post(
        f"/bluebook/courses/{c}/join-requests/{out['student_id']}/approve", headers=_auth(t)
    )
    assert r.status_code == 200 and r.json() == {"approved": [out["student_id"]]}
    [row] = _roster(live_client, t, c)
    assert row["state"] == "active"
    me = live_client.get("/bluebook/me", headers=_auth(out["token"])).json()
    assert [x["course_id"] for x in me["courses"]] == [c] and me["pending_courses"] == []
    again = live_client.post(
        f"/bluebook/courses/{c}/join-requests/{out['student_id']}/approve", headers=_auth(t)
    )
    assert again.status_code == 404


def test_approve_all(live_client, approval_course):
    t, c = approval_course["token"], approval_course["course"]
    ids = [
        _join(live_client, approval_course["code"], email=f"s{i}@school.edu").json()["student_id"]
        for i in range(3)
    ]
    r = live_client.post(f"/bluebook/courses/{c}/join-requests/approve-all", headers=_auth(t))
    assert r.status_code == 200 and sorted(r.json()["approved"]) == sorted(ids)
    assert {row["state"] for row in _roster(live_client, t, c)} == {"active"}
    assert live_client.post(
        f"/bluebook/courses/{c}/join-requests/approve-all", headers=_auth(t)
    ).json() == {"approved": []}


def test_declining_deletes_an_account_made_only_to_ask(live_client, approval_course):
    t, c = approval_course["token"], approval_course["course"]
    out = _join(live_client, approval_course["code"]).json()
    r = live_client.delete(
        f"/bluebook/courses/{c}/join-requests/{out['student_id']}", headers=_auth(t)
    )
    assert r.status_code == 200
    assert r.json() == {"declined": out["student_id"], "account_deleted": True}
    assert _roster(live_client, t, c) == []
    assert get_repository().get_user(out["student_id"]) is None
    assert (
        live_client.post(
            "/auth/login", json={"email": "ada@school.edu", "password": PW}
        ).status_code
        == 401
    )
    receipt = get_repository().list_audit(student_id=out["student_id"])["items"]
    assert [e["action"] for e in receipt] == ["bluebook_join_decline"]
    again = live_client.delete(
        f"/bluebook/courses/{c}/join-requests/{out['student_id']}", headers=_auth(t)
    )
    assert again.status_code == 404


def test_declining_keeps_an_account_that_is_on_another_course(live_client, approval_course):
    t, c = approval_course["token"], approval_course["course"]
    other = _course(live_client, t, name="Logic", code="LOG1")
    code2 = _settings(live_client, t, other, enabled=True)["code"]
    first = _join(live_client, code2).json()  # on Logic, no approval needed
    _join(live_client, approval_course["code"])  # waits on Ethics
    r = live_client.delete(
        f"/bluebook/courses/{c}/join-requests/{first['student_id']}", headers=_auth(t)
    )
    assert r.json()["account_deleted"] is False
    assert get_repository().get_user(first["student_id"]) is not None
    assert [x["state"] for x in _roster(live_client, t, other)] == ["active"]


@pytest.mark.parametrize("attachment", ["other_request", "submission", "profile"])
def test_declining_keeps_an_account_with_anything_else_attached(
    live_client, approval_course, attachment
):
    t, c = approval_course["token"], approval_course["course"]
    out = _join(live_client, approval_course["code"]).json()
    sid, repo = out["student_id"], get_repository()
    if attachment == "other_request":
        repo.put_join_request("another-course", sid, approval_course["tenant"])
    elif attachment == "submission":
        repo.put_bluebook_submission(
            {
                "id": "sub-x",
                "tenant_id": approval_course["tenant"],
                "exam_id": "e",
                "student_id": sid,
            }
        )
    else:
        from tests.test_repository_contract import _make_state

        repo.put(_make_state(sid))
    r = live_client.delete(f"/bluebook/courses/{c}/join-requests/{sid}", headers=_auth(t))
    assert r.json()["account_deleted"] is False
    assert repo.get_user(sid) is not None


def test_a_profile_with_no_reference_writing_does_not_keep_the_account(
    live_client, approval_course
):
    t, c = approval_course["token"], approval_course["course"]
    out = _join(live_client, approval_course["code"]).json()
    get_repository().get_or_create(out["student_id"])
    r = live_client.delete(
        f"/bluebook/courses/{c}/join-requests/{out['student_id']}", headers=_auth(t)
    )
    assert r.json()["account_deleted"] is True


def test_a_student_already_on_the_course_is_never_made_pending(live_client, approval_course):
    t, c = approval_course["token"], approval_course["course"]
    live_client.post(
        f"/bluebook/courses/{c}/students",
        json={"students": [{"email": "ada@school.edu"}]},
        headers=_auth(t),
    )
    out = _join(live_client, approval_course["code"]).json()
    assert out["join"]["status"] == "enrolled"
    assert [x["state"] for x in _roster(live_client, t, c)] == ["active"]


def test_asking_twice_keeps_one_request(live_client, approval_course):
    _join(live_client, approval_course["code"])
    r = _join(live_client, approval_course["code"], password=PW)
    assert r.json()["join"]["status"] == "pending"
    assert len(get_repository().list_join_requests_for_course(approval_course["course"])) == 1


def test_adding_a_waiting_student_by_email_answers_their_request(live_client, approval_course):
    t, c = approval_course["token"], approval_course["course"]
    out = _join(live_client, approval_course["code"]).json()
    r = live_client.post(
        f"/bluebook/courses/{c}/students",
        json={"students": [{"email": "ada@school.edu"}]},
        headers=_auth(t),
    )
    assert r.json()["students"][0]["state"] == "active"
    assert get_repository().list_join_requests_for_course(c) == []
    assert [x["state"] for x in _roster(live_client, t, c)] == ["active"]
    me = live_client.get("/bluebook/me", headers=_auth(out["token"])).json()
    assert [x["course_id"] for x in me["courses"]] == [c] and me["pending_courses"] == []


def test_a_leftover_request_for_a_course_the_student_is_on_is_not_shown(
    live_client, approval_course
):
    t, c = approval_course["token"], approval_course["course"]
    out = _join(live_client, approval_course["code"]).json()
    get_repository().put_enrollment(c, out["student_id"], approval_course["tenant"])
    me = live_client.get("/bluebook/me", headers=_auth(out["token"])).json()
    assert me["pending_courses"] == []
    assert [x["state"] for x in _roster(live_client, t, c)] == ["active"]


def test_rows_for_a_course_that_is_gone_are_not_listed_to_the_student(live_client, approval_course):
    out = _join(live_client, approval_course["code"]).json()
    repo = get_repository()
    repo.put_enrollment("gone-course", out["student_id"], approval_course["tenant"])
    repo.put_join_request("gone-too", out["student_id"], approval_course["tenant"])
    me = live_client.get("/bluebook/me", headers=_auth(out["token"])).json()
    assert me["courses"] == []
    assert [x["course_id"] for x in me["pending_courses"]] == [approval_course["course"]]


def test_a_waiting_request_with_no_account_is_not_listed(live_client, approval_course):
    get_repository().put_join_request(
        approval_course["course"], "ghost:id", approval_course["tenant"]
    )
    assert _roster(live_client, approval_course["token"], approval_course["course"]) == []


def test_approving_a_request_whose_account_is_gone_approves_nobody(live_client, approval_course):
    t, c = approval_course["token"], approval_course["course"]
    get_repository().put_join_request(c, "ghost:id", approval_course["tenant"])
    r = live_client.post(f"/bluebook/courses/{c}/join-requests/ghost:id/approve", headers=_auth(t))
    assert r.status_code == 200 and r.json() == {"approved": []}
    assert get_repository().list_join_requests_for_course(c) == []


def test_a_pending_student_cannot_share_past_papers(live_client, approval_course):
    get_repository().set_tenant_products(approval_course["tenant"], ["original", "bluebook"])
    principal_mod.invalidate_tenant_cache()
    out = _join(live_client, approval_course["code"]).json()
    r = live_client.post(
        "/bluebook/me/papers",
        data={"text": "An essay I wrote last term.", "title": "Old essay"},
        headers=_auth(out["token"]),
    )
    assert r.status_code == 403 and "approved" in r.json()["detail"]


# ── Caps ──────────────────────────────────────────────────────────────────────


def test_the_waiting_list_has_a_cap(live_client, approval_course, monkeypatch):
    monkeypatch.setattr(cj, "MAX_PENDING_PER_COURSE", 1)
    assert _join(live_client, approval_course["code"], email="a@school.edu").status_code == 200
    r = _join(live_client, approval_course["code"], email="b@school.edu")
    assert r.status_code == 403 and "waiting" in r.json()["detail"]
    assert get_repository().get_user_by_email("b@school.edu") is None
    # Someone already waiting can ask again.
    assert _join(live_client, approval_course["code"], email="a@school.edu").status_code == 200


def test_the_free_workspace_student_cap_applies_to_joins_and_approvals(
    live_client, open_course, monkeypatch
):
    from original import bluebook_rules as rules

    monkeypatch.setattr(rules, "MAX_ENROLLED_STUDENTS", 1)
    t, c = open_course["token"], open_course["course"]
    assert _join(live_client, open_course["code"], email="a@school.edu").status_code == 200
    r = _join(live_client, open_course["code"], email="b@school.edu")
    assert r.status_code == 403 and "can't take more students" in r.json()["detail"]
    assert get_repository().get_user_by_email("b@school.edu") is None
    # An approval past the cap is refused too, singly and all at once.
    _settings(live_client, t, c, require_approval=True)
    waiting = _join(live_client, open_course["code"], email="c@school.edu").json()
    one = live_client.post(
        f"/bluebook/courses/{c}/join-requests/{waiting['student_id']}/approve", headers=_auth(t)
    )
    every = live_client.post(f"/bluebook/courses/{c}/join-requests/approve-all", headers=_auth(t))
    assert one.status_code == every.status_code == 403
    assert "Free workspaces can hold 1 students." == one.json()["detail"]


def test_workspaces_that_are_not_self_serve_have_no_student_cap(
    live_client, open_course, monkeypatch
):
    from original import bluebook_rules as rules

    monkeypatch.setattr(rules, "MAX_ENROLLED_STUDENTS", 0)
    repo = get_repository()
    tenant = repo.get_tenant(open_course["tenant"])
    repo.put_tenant(
        open_course["tenant"], tenant["name"], environment="production", meta={"plan": "pilot"}
    )
    assert _join(live_client, open_course["code"]).status_code == 200


# ── Rate limits ───────────────────────────────────────────────────────────────


def test_wrong_codes_are_rate_limited(live_client, open_course):
    for _ in range(_shared._LOGIN_MAX_ATTEMPTS):
        assert live_client.get("/auth/join/ZZZZZZ").status_code == 404
    assert live_client.get(f"/auth/join/{open_course['code']}").status_code == 429
    assert _join(live_client, open_course["code"]).status_code == 429


def test_wrong_passwords_are_rate_limited_per_email(live_client, open_course):
    _join(live_client, open_course["code"])
    for _ in range(_shared._LOGIN_MAX_ATTEMPTS):
        assert _join(live_client, open_course["code"], password="wrong-password").status_code == 401
    # The right password is refused too now, for a while.
    assert _join(live_client, open_course["code"]).status_code == 429


def test_every_join_attempt_counts_against_a_per_client_budget(
    live_client, open_course, monkeypatch
):
    monkeypatch.setattr(cj, "JOIN_ATTEMPTS_PER_WINDOW", 3)
    for i in range(3):
        assert _join(live_client, open_course["code"], email=f"s{i}@school.edu").status_code == 200
    r = _join(live_client, open_course["code"], email="s9@school.edu")
    assert r.status_code == 429


# ── Deletion ──────────────────────────────────────────────────────────────────


def test_deleting_a_course_removes_its_join_link_and_waiting_list(live_client, approval_course):
    t, c, code = approval_course["token"], approval_course["course"], approval_course["code"]
    out = _join(live_client, code).json()
    assert live_client.delete(f"/bluebook/courses/{c}", headers=_auth(t)).status_code in (200, 204)
    repo = get_repository()
    assert repo.get_course_join(c) is None and repo.get_course_join_by_code(code) is None
    assert repo.list_join_requests_for_student(out["student_id"]) == []
    assert live_client.get(f"/auth/join/{code}").status_code == 404


def test_erasing_a_waiting_student_removes_their_request(live_client, approval_course):
    t, c = approval_course["token"], approval_course["course"]
    out = _join(live_client, approval_course["code"]).json()
    r = live_client.delete(f"/bluebook/students/{out['student_id']}", headers=_auth(t))
    assert r.status_code == 200, r.text
    assert get_repository().list_join_requests_for_course(c) == []
    assert get_repository().get_user(out["student_id"]) is None
