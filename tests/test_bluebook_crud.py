"""
Bluebook CRUD + route-inventory tests (WS-5 gap).

Covers the actual `/bluebook/*` surface — exams, courses, submissions (the
Results view) — plus the tenant-scoped student roster. This is also the
direct safety net the T6 router split relies on to prove no route is dropped
or renamed when handlers move from `original/api.py` into `original/routers/`.

Note on scope: the live surface only offers create+list (+get for exams);
there is no update or delete endpoint for any Bluebook noun today, so this
file tests create/list/get and the authorization/tenant-scoping rules around
them rather than a full CRUD matrix that doesn't exist yet.
"""

from __future__ import annotations

import pytest

from original import principal as pr

EXPECTED_ROUTES = [
    ("/bluebook/launch", "GET"),
    ("/bluebook/exams", "POST"),
    ("/bluebook/exams", "GET"),
    ("/bluebook/exams/{exam_id}", "GET"),
    ("/bluebook/submissions", "POST"),
    ("/bluebook/submissions", "GET"),
    ("/bluebook/courses", "POST"),
    ("/bluebook/courses", "GET"),
    ("/students", "GET"),
]

PW = "s3cret-passw0rd"


def _auth(token: str):
    return {"Authorization": f"Bearer {token}"}


def _provision_professor(live_client, tenant: str, email: str) -> str:
    """Register + log in a professor, exactly as tests/test_staff_auth.py does."""
    live_client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PW,
            "role": "professor",
            "tenant_id": tenant,
            "name": "Dr Test",
        },
    )
    r = live_client.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    """Registering + logging in several professors per test can otherwise
    trip the shared per-IP login-throttle window across this file's tests."""
    import original.api as _api

    _api._login_attempts.clear()
    yield


@pytest.fixture
def api_mod(live_app):
    import original.api

    return original.api


@pytest.fixture
def real_deploy(api_mod, monkeypatch):
    """Flip the loaded app into pilot behaviour without reloading it (same
    pattern as tests/test_pilot_lockdown.py)."""
    monkeypatch.setattr(api_mod, "_IS_REAL_DEPLOY", True)
    yield


def test_bluebook_route_inventory_is_complete(live_app):
    """Every /bluebook (+roster) route present — the router-split (T6) safety
    net. If this fails after a refactor, a route was dropped or renamed."""
    live = {(r.path, m) for r in live_app.routes for m in (r.methods or ())}
    for path, method in EXPECTED_ROUTES:
        assert (path, method) in live, f"missing {method} {path}"


# ── Exams ──────────────────────────────────────────────────────────────────


def test_create_exam_requires_staff_login_in_pilot(real_deploy, live_client):
    r = live_client.post(
        "/bluebook/exams",
        json={"title": "Midterm", "course": "THEO-101"},
    )
    assert r.status_code == 401, r.text


def test_create_exam_missing_title_422(live_client, store_reset):
    token = _provision_professor(live_client, "bbcrud", "prof.exam1@bbcrud.edu")
    r = live_client.post(
        "/bluebook/exams",
        json={"title": "   ", "course": "THEO-101"},
        headers=_auth(token),
    )
    assert r.status_code == 422


def test_create_exam_then_list_and_get_scoped_to_tenant(live_client, store_reset):
    token = _provision_professor(live_client, "bbcrud", "prof.exam2@bbcrud.edu")
    created = live_client.post(
        "/bluebook/exams",
        json={"title": "Final Exam", "course": "THEO-201", "prompt": "Discuss."},
        headers=_auth(token),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["title"] == "Final Exam"
    assert body["duration"] == 90  # default
    exam_id = body["id"]

    listed = live_client.get("/bluebook/exams", headers=_auth(token))
    assert listed.status_code == 200
    ids = [e["id"] for e in listed.json()["exams"]]
    assert exam_id in ids

    fetched = live_client.get(f"/bluebook/exams/{exam_id}", headers=_auth(token))
    assert fetched.status_code == 200
    assert fetched.json()["id"] == exam_id


def test_exam_get_missing_returns_404(live_client, store_reset):
    token = _provision_professor(live_client, "bbcrud", "prof.exam3@bbcrud.edu")
    r = live_client.get("/bluebook/exams/does-not-exist", headers=_auth(token))
    assert r.status_code == 404


def test_exam_get_cross_tenant_denied(live_client, store_reset):
    owner_token = _provision_professor(live_client, "bbcrud", "prof.exam4a@bbcrud.edu")
    other_token = _provision_professor(live_client, "bbcrud2", "prof.exam4b@bbcrud2.edu")
    created = live_client.post(
        "/bluebook/exams",
        json={"title": "Private Exam", "course": "THEO-301"},
        headers=_auth(owner_token),
    )
    exam_id = created.json()["id"]

    r = live_client.get(f"/bluebook/exams/{exam_id}", headers=_auth(other_token))
    assert r.status_code == 403

    # the anonymous demo principal (owner is a real, non-demo tenant) is
    # denied too — only same-tenant or demo-tenant exams are readable.
    r_anon = live_client.get(f"/bluebook/exams/{exam_id}")
    assert r_anon.status_code == 403


def test_exam_list_excludes_other_tenants(live_client, store_reset):
    token_a = _provision_professor(live_client, "bbcrud", "prof.exam5a@bbcrud.edu")
    token_b = _provision_professor(live_client, "bbcrud2", "prof.exam5b@bbcrud2.edu")
    live_client.post(
        "/bluebook/exams",
        json={"title": "Tenant A Exam", "course": "A-101"},
        headers=_auth(token_a),
    )
    listed_b = live_client.get("/bluebook/exams", headers=_auth(token_b))
    titles_b = [e["title"] for e in listed_b.json()["exams"]]
    assert "Tenant A Exam" not in titles_b


# ── Courses ────────────────────────────────────────────────────────────────


def test_create_course_requires_staff_login_in_pilot(real_deploy, live_client):
    r = live_client.post("/bluebook/courses", json={"name": "Systematic Theology I"})
    assert r.status_code == 401, r.text


def test_create_course_missing_name_422(live_client, store_reset):
    token = _provision_professor(live_client, "bbcrud", "prof.course1@bbcrud.edu")
    r = live_client.post(
        "/bluebook/courses",
        json={"name": "  ", "code": "ST-101"},
        headers=_auth(token),
    )
    assert r.status_code == 422


def test_create_course_then_list_scoped_to_tenant(live_client, store_reset):
    token = _provision_professor(live_client, "bbcrud", "prof.course2@bbcrud.edu")
    created = live_client.post(
        "/bluebook/courses",
        json={"name": "Systematic Theology I", "code": "ST-101", "term": "Fall 2026"},
        headers=_auth(token),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Systematic Theology I"
    assert body["active"] is True
    course_id = body["id"]

    listed = live_client.get("/bluebook/courses", headers=_auth(token))
    ids = [c["id"] for c in listed.json()["courses"]]
    assert course_id in ids


def test_course_list_excludes_other_tenants(live_client, store_reset):
    token_a = _provision_professor(live_client, "bbcrud", "prof.course3a@bbcrud.edu")
    token_b = _provision_professor(live_client, "bbcrud2", "prof.course3b@bbcrud2.edu")
    live_client.post(
        "/bluebook/courses",
        json={"name": "Tenant A Course", "code": "A-101"},
        headers=_auth(token_a),
    )
    listed_b = live_client.get("/bluebook/courses", headers=_auth(token_b))
    names_b = [c["name"] for c in listed_b.json()["courses"]]
    assert "Tenant A Course" not in names_b


# ── Submissions (the Results view) ────────────────────────────────────────
# Unlike exams/courses, recording a submission is NOT staff-gated by design
# (students, not professors, submit exams) — verify that stays true, then
# verify scoping for the professor-facing Results list.


def test_record_submission_does_not_require_staff(live_client, store_reset):
    r = live_client.post(
        "/bluebook/submissions",
        json={
            "student_id": "anon-student",
            "candidate": "Anon Candidate",
            "exam_title": "Open Submission Exam",
            "word_count": 450,
            "time_min": 40,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "SUBMITTED"


def test_record_submission_then_appears_in_scoped_list(live_client, store_reset):
    token = _provision_professor(live_client, "bbcrud", "prof.sub1@bbcrud.edu")
    created = live_client.post(
        "/bluebook/submissions",
        json={
            "student_id": "bbcrud:stu1",
            "candidate": "Stu One",
            "exam_title": "Midterm",
            "word_count": 600,
            "time_min": 55,
            "stylometric": 92,
        },
        headers=_auth(token),
    )
    assert created.status_code == 201, created.text
    sub_id = created.json()["id"]

    listed = live_client.get("/bluebook/submissions", headers=_auth(token))
    assert listed.status_code == 200
    rec = next(s for s in listed.json()["submissions"] if s["id"] == sub_id)
    # list serializer exposes frontend-facing key names (words/timeMin), not
    # the request body's word_count/time_min.
    assert rec["words"] == 600
    assert rec["timeMin"] == 55
    assert rec["stylometric"] == 92


def test_submission_list_excludes_other_tenants(live_client, store_reset):
    token_a = _provision_professor(live_client, "bbcrud", "prof.sub2a@bbcrud.edu")
    token_b = _provision_professor(live_client, "bbcrud2", "prof.sub2b@bbcrud2.edu")
    live_client.post(
        "/bluebook/submissions",
        json={
            "student_id": "bbcrud:stu2",
            "candidate": "Tenant A Candidate",
            "exam_title": "Tenant A Exam",
        },
        headers=_auth(token_a),
    )
    listed_b = live_client.get("/bluebook/submissions", headers=_auth(token_b))
    candidates_b = [s["candidate"] for s in listed_b.json()["submissions"]]
    assert "Tenant A Candidate" not in candidates_b


# ── Student roster ─────────────────────────────────────────────────────────
# Not a /bluebook/* path, but the fourth Bluebook noun named in the plan
# (students-roster) and part of the same T6 safety net.


LONG_TEXT = (
    "Grace and peace are the twin notes that open nearly every Pauline letter, "
    "and their repetition is not accidental but theological. The writer returns "
    "again and again to the same vocabulary, the same cadence, the same habit of "
    "qualifying a bold claim with a gentle clause. Across a semester these habits "
    "compound into a recognizable voice, and it is that voice, not any single "
    "sentence, that the system learns to know and to defend with care and patience."
)


def test_roster_scoped_by_tenant(live_client, store_reset):
    token_a = _provision_professor(live_client, "bbcrud", "prof.roster1a@bbcrud.edu")
    token_b = _provision_professor(live_client, "bbcrud2", "prof.roster1b@bbcrud2.edu")

    sid = "bbcrud:essay1"
    r = live_client.post(
        f"/students/{sid}/baseline",
        json={"text": LONG_TEXT, "assignment": "a1"},
        headers=_auth(token_a),
    )
    assert r.status_code == 200, r.text

    roster_a = live_client.get("/students", headers=_auth(token_a))
    assert sid in roster_a.json()["students"]

    roster_b = live_client.get("/students", headers=_auth(token_b))
    assert sid not in roster_b.json()["students"]
