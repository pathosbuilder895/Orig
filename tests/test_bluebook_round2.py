"""Bluebook round 2 (2026-10): getting a class in, marks and feedback, one
answer per question, the workspace student list, and the live proctor view.

Plan: ~/.claude/plans/ok-what-stops-me-keen-zebra.md (Phase B, items 1, 3-5).
Email is always exercised with SendGrid mocked: nothing here opens a socket.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import urllib.error
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from original import bluebook_rules as rules
from original import mailer
from original.repository import get_repository
from tests.test_bluebook_self_serve import (  # noqa: F401  (fixtures re-used)
    PW,
    _add_students,
    _auth,
    _course,
    _exam,
    _isolate,
    _signup,
    _student,
)


def _token(path: str) -> str:
    q = parse_qs(urlparse(path).query)
    return (q.get("invite") or q.get("reset"))[0]


@pytest.fixture
def mail(monkeypatch):
    """Mail configured, with every send captured instead of delivered."""
    sent = []
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.test-not-real")
    monkeypatch.setenv("MAIL_FROM", "Bluebook <no-reply@test.example>")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://bluebook.test.example")

    def fake_send(to, subject, text):
        sent.append({"to": to, "subject": subject, "text": text})
        return True

    monkeypatch.setattr(mailer, "send", fake_send)
    return sent


@pytest.fixture(autouse=True)
def _no_mail_env(monkeypatch):
    for k in ("SENDGRID_API_KEY", "MAIL_FROM", "PUBLIC_BASE_URL"):
        monkeypatch.delenv(k, raising=False)


# ── mailer ────────────────────────────────────────────────────────────────────


class _Resp:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_mailer_is_a_no_op_without_config(monkeypatch):
    called = []
    monkeypatch.setattr(mailer.urllib.request, "urlopen", lambda *a, **k: called.append(1))
    assert mailer.configured() is False
    assert mailer.send("a@x.edu", "s", "t") is False
    monkeypatch.setenv("SENDGRID_API_KEY", "k")
    assert mailer.configured() is False  # MAIL_FROM still missing
    assert called == []


def test_mailer_posts_to_sendgrid_without_click_tracking(monkeypatch):
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.k")
    monkeypatch.setenv("MAIL_FROM", '"Bluebook" <no-reply@x.edu>')
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["auth"] = req.headers["Authorization"]
        seen["body"] = json.loads(req.data)
        return _Resp(202)

    monkeypatch.setattr(mailer.urllib.request, "urlopen", fake_urlopen)
    assert (
        mailer.send_invite("stu@x.edu", "https://b/?invite=t", course="Ethics", teacher="Ms T")
        is True
    )
    assert seen["url"] == mailer.SENDGRID_URL
    assert seen["auth"] == "Bearer SG.k"
    body = seen["body"]
    assert body["from"] == {"email": "no-reply@x.edu", "name": "Bluebook"}
    assert body["tracking_settings"]["click_tracking"]["enable"] is False
    assert "Ms T has added you to Bluebook for Ethics" in body["content"][0]["value"]
    assert "https://b/?invite=t" in body["content"][0]["value"]


@pytest.mark.parametrize("raise_exc", [True, False])
def test_mailer_failures_return_false_and_never_raise(monkeypatch, raise_exc):
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.k")
    monkeypatch.setenv("MAIL_FROM", "no-reply@x.edu")

    def fake_urlopen(req, timeout):
        if raise_exc:
            raise urllib.error.HTTPError(req.full_url, 401, "no", {}, None)
        raise TimeoutError()

    monkeypatch.setattr(mailer.urllib.request, "urlopen", fake_urlopen)
    assert mailer.send_reset("a@x.edu", "https://b/?reset=t") is False


def test_mailer_unexpected_status_is_false(monkeypatch):
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.k")
    monkeypatch.setenv("MAIL_FROM", "no-reply@x.edu")
    monkeypatch.setattr(mailer.urllib.request, "urlopen", lambda req, timeout: _Resp(500))
    assert mailer.send("a@x.edu", "s", "t") is False
    assert mailer.send("", "s", "t") is False


def test_absolute_url_prefers_public_base(monkeypatch):
    assert mailer.absolute_url("/p", "http://req/") == "http://req/p"
    assert mailer.absolute_url("/p") == "/p"
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://site.example/")
    assert mailer.absolute_url("/p", "http://req/") == "https://site.example/p"


def test_startup_line_mentions_account_email(monkeypatch, caplog):
    from original.routers._shared import log_email_sender_status

    monkeypatch.setenv("SENDGRID_API_KEY", "SG.k")
    monkeypatch.setenv("MAIL_FROM", "no-reply@x.edu")
    with caplog.at_level(logging.WARNING, logger="original.routers._shared"):
        log_email_sender_status()
    msg = caplog.records[-1].getMessage()
    assert "account email" in msg and "once MAIL_FROM" not in msg


# ── Getting a class in ────────────────────────────────────────────────────────


def test_auth_me_reports_whether_mail_is_configured(live_client, monkeypatch):
    t = _signup(live_client)
    assert live_client.get("/auth/me", headers=_auth(t["token"])).json()["mail"] is False
    monkeypatch.setenv("SENDGRID_API_KEY", "k")
    monkeypatch.setenv("MAIL_FROM", "no-reply@x.edu")
    assert live_client.get("/auth/me", headers=_auth(t["token"])).json()["mail"] is True


def test_roster_add_emails_invites_when_asked(live_client, mail):
    t = _signup(live_client, name="Ms Teach")
    course = _course(live_client, t["token"], "Ethics")
    r = live_client.post(
        f"/bluebook/courses/{course}/students",
        json={"students": [{"email": "a@x.edu"}, {"email": "b@x.edu"}], "send_email": True},
        headers=_auth(t["token"]),
    )
    rows = r.json()["students"]
    assert [row["emailed"] for row in rows] == [True, True]
    assert {m["to"] for m in mail} == {"a@x.edu", "b@x.edu"}
    assert "https://bluebook.test.example/bluebook/?invite=" in mail[0]["text"]
    assert "Ms Teach has added you to Bluebook for Ethics" in mail[0]["text"]
    # the emailed link is the same one-time link the teacher sees
    link = mail[0]["text"].split("expires in 14 days):\n")[1].split("\n")[0]
    assert _token(link) in {_token(row["invite_path"]) for row in rows}


def test_roster_add_without_email_flag_sends_nothing(live_client, mail):
    t = _signup(live_client)
    rows = _add_students(live_client, t["token"], _course(live_client, t["token"]), "a@x.edu")
    assert rows[0]["emailed"] is False and mail == []


def test_reissue_can_email(live_client, mail):
    t = _signup(live_client)
    course = _course(live_client, t["token"])
    sid = _add_students(live_client, t["token"], course, "a@x.edu")[0]["student_id"]
    r = live_client.post(
        f"/bluebook/courses/{course}/students/{sid}/invite",
        json={"send_email": True},
        headers=_auth(t["token"]),
    )
    assert r.json()["emailed"] is True and len(mail) == 1


def test_reissue_pending_replaces_only_waiting_students(live_client, mail):
    t = _signup(live_client)
    course = _course(live_client, t["token"])
    _student(live_client, t["token"], course, "active@x.edu")
    old = _add_students(live_client, t["token"], course, "w1@x.edu", "w2@x.edu")
    r = live_client.post(
        f"/bluebook/courses/{course}/invites/reissue-pending",
        json={"send_email": True},
        headers=_auth(t["token"]),
    )
    fresh = r.json()["students"]
    assert sorted(x["email"] for x in fresh) == ["w1@x.edu", "w2@x.edu"]
    assert all(x["emailed"] for x in fresh) and len(mail) == 2
    # old links are dead, new ones work
    dead = live_client.post(
        "/auth/invite/redeem", json={"token": _token(old[0]["invite_path"]), "password": PW}
    )
    assert dead.status_code == 400
    ok = live_client.post(
        "/auth/invite/redeem", json={"token": _token(fresh[0]["invite_path"]), "password": PW}
    )
    assert ok.status_code == 200
    # no body at all is fine (defaults to no email)
    again = live_client.post(
        f"/bluebook/courses/{course}/invites/reissue-pending", headers=_auth(t["token"])
    )
    assert [x["emailed"] for x in again.json()["students"]] == [False]


def test_reissue_pending_is_tenant_scoped(live_client):
    a = _signup(live_client, "a@t.edu")
    b = _signup(live_client, "b@t.edu")
    course = _course(live_client, a["token"])
    r = live_client.post(
        f"/bluebook/courses/{course}/invites/reissue-pending", headers=_auth(b["token"])
    )
    assert r.status_code == 404


# ── Password reset ────────────────────────────────────────────────────────────


def test_reset_request_is_uniform_and_emails_only_real_accounts(live_client, mail):
    t = _signup(live_client, "teach@x.edu")
    for email in ("nobody@x.edu", "teach@x.edu", "not-an-email"):
        r = live_client.post("/auth/password-reset/request", json={"email": email})
        assert r.status_code == 200 and r.json() == {"ok": True, "mail": True}
    assert [m["to"] for m in mail] == ["teach@x.edu"]
    link = mail[0]["text"].split("expires in 14 days):\n")[1].split("\n")[0]
    assert "?reset=" in link
    r = live_client.post(
        "/auth/invite/redeem", json={"token": _token(link), "password": "brand-new-pw1"}
    )
    assert r.status_code == 200 and r.json()["tenant_id"] == t["tenant_id"]
    login = live_client.post(
        "/auth/login", json={"email": "teach@x.edu", "password": "brand-new-pw1"}
    )
    assert login.status_code == 200


def test_reset_request_without_mail_sends_nothing(live_client):
    _signup(live_client, "teach@x.edu")
    r = live_client.post("/auth/password-reset/request", json={"email": "teach@x.edu"})
    assert r.json() == {"ok": True, "mail": False}
    assert (
        get_repository().latest_invite_for_user(
            get_repository().get_user_by_email("teach@x.edu")["user_id"]
        )
        is None
    )


def test_reset_request_is_throttled(live_client):
    codes = [
        live_client.post("/auth/password-reset/request", json={"email": "x@x.edu"}).status_code
        for _ in range(11)
    ]
    assert codes[:10] == [200] * 10 and codes[10] == 429


def test_reset_for_a_student_records_the_student(live_client, mail):
    t = _signup(live_client)
    s = _student(live_client, t["token"], _course(live_client, t["token"]), "stu@x.edu")
    live_client.post("/auth/password-reset/request", json={"email": "stu@x.edu"})
    audit = get_repository().list_audit(action="password_reset_request")
    assert audit["items"][0]["student_id"] in (s["student_id"], s["student_id"].split(":", 1)[1])


# ── Terms at signup ───────────────────────────────────────────────────────────


def test_signup_requires_accepting_terms(live_client):
    r = live_client.post("/auth/signup", json={"email": "t@x.edu", "password": PW})
    assert r.status_code == 422
    assert get_repository().get_user_by_email("t@x.edu") is None


def test_signup_records_the_terms_version(live_client):
    from original.routers.auth import TERMS_VERSION

    _signup(live_client, "t@x.edu")
    item = get_repository().list_audit(action="signup")["items"][0]
    details = item.get("details") or json.loads(item.get("details_json") or "{}")
    assert details["terms_version"] == TERMS_VERSION


# ── One answer per question ───────────────────────────────────────────────────


def test_questions_round_trip_and_derive_the_prompt(live_client):
    t = _signup(live_client)
    e = _exam(live_client, t["token"], questions=["  First? ", "", "Second?"])
    got = live_client.get(f"/bluebook/exams/{e['id']}", headers=_auth(t["token"])).json()
    assert got["questions"] == ["First?", "Second?"]
    assert got["prompt"] == "1. First?\n\n2. Second?"
    r = live_client.patch(
        f"/bluebook/exams/{e['id']}", json={"questions": ["Only one"]}, headers=_auth(t["token"])
    ).json()
    assert (r["questions"], r["prompt"]) == (["Only one"], "Only one")
    r = live_client.patch(
        f"/bluebook/exams/{e['id']}", json={"prompt": "Legacy prompt"}, headers=_auth(t["token"])
    ).json()
    assert (r["questions"], r["prompt"]) == ([], "Legacy prompt")


@pytest.mark.parametrize("questions", [["x"] * 21, [1, 2], "not a list", ["x" * 8001]])
def test_bad_questions_are_422(live_client, questions):
    t = _signup(live_client)
    r = live_client.post(
        "/bluebook/exams", json={"title": "T", "questions": questions}, headers=_auth(t["token"])
    )
    assert r.status_code == 422


def test_answers_are_stored_shown_and_exported(live_client):
    t = _signup(live_client)
    course = _course(live_client, t["token"])
    s = _student(live_client, t["token"], course)
    e = _exam(live_client, t["token"], course_id=course, questions=["Q one?", "Q two?"])
    detail = live_client.get(f"/bluebook/me/exams/{e['id']}", headers=_auth(s["token"])).json()
    assert detail["questions"] == ["Q one?", "Q two?"]
    r = live_client.post(
        "/bluebook/submissions",
        json={"exam_id": e["id"], "student_id": s["student_id"], "answers": ["A one", "A two"]},
        headers=_auth(s["token"]),
    )
    sid = r.json()["id"]
    teacher_view = live_client.get(f"/bluebook/submissions/{sid}", headers=_auth(t["token"])).json()
    assert teacher_view["answers"] == ["A one", "A two"]
    assert teacher_view["questions"] == ["Q one?", "Q two?"]
    assert teacher_view["text"] == "Question 1.\nA one\n\nQuestion 2.\nA two"
    mine = live_client.get(f"/bluebook/me/submissions/{sid}", headers=_auth(s["token"])).json()
    assert mine["answers"] == ["A one", "A two"]
    csv_text = live_client.get(f"/bluebook/exams/{e['id']}/export", headers=_auth(t["token"])).text
    row = next(csv.DictReader(io.StringIO(csv_text)))
    assert (row["answer_1"], row["answer_2"]) == ("A one", "A two")


def test_upcoming_exam_withholds_questions(live_client):
    t = _signup(live_client)
    course = _course(live_client, t["token"])
    s = _student(live_client, t["token"], course)
    soon = rules.now_utc() + timedelta(days=1)
    e = _exam(
        live_client, t["token"], course_id=course, questions=["Secret?"], opens_at=soon.isoformat()
    )
    detail = live_client.get(f"/bluebook/me/exams/{e['id']}", headers=_auth(s["token"])).json()
    assert detail["questions"] == [] and detail["prompt"] is None
    listed = live_client.get("/bluebook/me/exams", headers=_auth(s["token"])).json()["exams"]
    assert listed[0]["questions_count"] == 1


@pytest.mark.parametrize("answers", [["x"] * 21, [1], "nope"])
def test_bad_answers_are_422(live_client, answers):
    t = _signup(live_client)
    r = live_client.post(
        "/bluebook/submissions", json={"answers": answers}, headers=_auth(t["token"])
    )
    assert r.status_code == 422


def test_oversized_answers_are_413(live_client, monkeypatch):
    monkeypatch.setattr(rules, "MAX_TEXT_CHARS", 10)
    t = _signup(live_client)
    r = live_client.post(
        "/bluebook/submissions",
        json={"answers": ["123456", "123456"], "text": "short"},
        headers=_auth(t["token"]),
    )
    assert r.status_code == 413
    r = live_client.post(
        "/bluebook/submissions", json={"answers": ["12345678901"]}, headers=_auth(t["token"])
    )
    assert r.status_code == 413


# ── Marks and feedback ────────────────────────────────────────────────────────


def _sat(live_client):
    t = _signup(live_client)
    course = _course(live_client, t["token"])
    s = _student(live_client, t["token"], course)
    e = _exam(live_client, t["token"], course_id=course)
    sub = live_client.post(
        "/bluebook/submissions",
        json={"exam_id": e["id"], "student_id": s["student_id"], "text": "My answer"},
        headers=_auth(s["token"]),
    ).json()["id"]
    return t, s, e, sub


def test_feedback_is_hidden_until_released(live_client):
    t, s, e, sub = _sat(live_client)
    r = live_client.patch(
        f"/bluebook/submissions/{sub}/feedback",
        json={"mark": " 18/20 ", "feedback": "Clear argument."},
        headers=_auth(t["token"]),
    )
    assert r.status_code == 200
    assert (r.json()["mark"], r.json()["feedback"]) == ("18/20", "Clear argument.")
    assert r.json()["graded_at"]

    def student_sees():
        one = live_client.get(f"/bluebook/me/submissions/{sub}", headers=_auth(s["token"])).json()
        lst = live_client.get("/bluebook/me/submissions", headers=_auth(s["token"])).json()[
            "submissions"
        ][0]
        exams = live_client.get("/bluebook/me/exams", headers=_auth(s["token"])).json()["exams"]
        return one, lst, exams[0]

    one, lst, ex = student_sees()
    assert one["results_released"] is False and "mark" not in one and "feedback" not in one
    assert "mark" not in lst and ex["results_released"] is False
    assert "graded_by" not in one

    rel = live_client.post(f"/bluebook/exams/{e['id']}/release", headers=_auth(t["token"]))
    assert rel.status_code == 200 and rel.json()["results_released_at"]
    one, lst, ex = student_sees()
    assert (one["mark"], one["feedback"], one["results_released"]) == (
        "18/20",
        "Clear argument.",
        True,
    )
    assert lst["mark"] == "18/20" and ex["results_released"] is True
    assert "graded_by" not in one

    live_client.post(f"/bluebook/exams/{e['id']}/unrelease", headers=_auth(t["token"]))
    one, _, _ = student_sees()
    assert "mark" not in one

    # teacher list carries marks; CSV too
    listed = live_client.get("/bluebook/submissions", headers=_auth(t["token"])).json()[
        "submissions"
    ]
    assert listed[0]["mark"] == "18/20"
    row = next(
        csv.DictReader(
            io.StringIO(
                live_client.get(f"/bluebook/exams/{e['id']}/export", headers=_auth(t["token"])).text
            )
        )
    )
    assert (row["mark"], row["feedback"]) == ("18/20", "Clear argument.")


def test_feedback_can_be_cleared_and_is_validated(live_client):
    t, _, _, sub = _sat(live_client)
    h = _auth(t["token"])
    live_client.patch(f"/bluebook/submissions/{sub}/feedback", json={"mark": "A"}, headers=h)
    cleared = live_client.patch(
        f"/bluebook/submissions/{sub}/feedback", json={"mark": "", "feedback": ""}, headers=h
    ).json()
    assert (cleared["mark"], cleared["feedback"]) == (None, None)
    assert (
        live_client.patch(
            f"/bluebook/submissions/{sub}/feedback", json={"mark": "x" * 21}, headers=h
        ).status_code
        == 422
    )
    assert (
        live_client.patch(
            f"/bluebook/submissions/{sub}/feedback", json={"feedback": "x" * 5001}, headers=h
        ).status_code
        == 422
    )


def test_feedback_and_release_are_staff_and_tenant_only(live_client):
    t, s, e, sub = _sat(live_client)
    other = _signup(live_client, "other@x.edu")
    assert (
        live_client.patch(
            f"/bluebook/submissions/{sub}/feedback",
            json={"mark": "A"},
            headers=_auth(other["token"]),
        ).status_code
        == 404
    )
    assert (
        live_client.post(
            f"/bluebook/exams/{e['id']}/release", headers=_auth(other["token"])
        ).status_code
        == 404
    )
    assert (
        live_client.patch(
            f"/bluebook/submissions/{sub}/feedback", json={"mark": "A"}, headers=_auth(s["token"])
        ).status_code
        == 403
    )
    assert (
        live_client.post(
            f"/bluebook/exams/{e['id']}/release", headers=_auth(s["token"])
        ).status_code
        == 403
    )
    assert (
        live_client.patch(
            "/bluebook/submissions/nope/feedback", json={}, headers=_auth(t["token"])
        ).status_code
        == 404
    )


def test_student_view_rule():
    rec = {
        "id": "1",
        "tenant_id": "t",
        "stylometric": 1,
        "aiScore": 2,
        "mark": "A",
        "feedback": "f",
        "graded_at": "x",
        "graded_by": "p",
    }
    hidden = rules.student_view(rec)
    assert set(hidden) == {"id", "results_released"}
    shown = rules.student_view(rec, released=True)
    assert shown["mark"] == "A" and "graded_by" not in shown and "aiScore" not in shown


# ── Students list ─────────────────────────────────────────────────────────────


def test_students_list_spans_courses(live_client):
    t = _signup(live_client)
    c1 = _course(live_client, t["token"], "Ethics")
    c2 = _course(live_client, t["token"], "Logic")
    s = _student(live_client, t["token"], c1, "ana@x.edu")
    _add_students(live_client, t["token"], c2, "ana@x.edu", "ben@x.edu")
    e = _exam(live_client, t["token"], course_id=c1)
    live_client.post(
        "/bluebook/submissions",
        json={"exam_id": e["id"], "student_id": s["student_id"], "text": "x"},
        headers=_auth(s["token"]),
    )
    rows = {
        r["email"]: r
        for r in live_client.get("/bluebook/students", headers=_auth(t["token"])).json()["students"]
    }
    assert set(rows) == {"ana@x.edu", "ben@x.edu"}
    assert sorted(c["name"] for c in rows["ana@x.edu"]["courses"]) == ["Ethics", "Logic"]
    assert (rows["ana@x.edu"]["state"], rows["ana@x.edu"]["submissions"]) == ("active", 1)
    assert rows["ana@x.edu"]["last_submitted_at"]
    assert (rows["ben@x.edu"]["state"], rows["ben@x.edu"]["submissions"]) == ("invited", 0)
    other = _signup(live_client, "o@x.edu")
    assert (
        live_client.get("/bluebook/students", headers=_auth(other["token"])).json()["students"]
        == []
    )
    assert live_client.get("/bluebook/students", headers=_auth(s["token"])).status_code == 403


# ── Live proctor view ─────────────────────────────────────────────────────────


def test_live_view_tracks_each_student(live_client, monkeypatch):
    t = _signup(live_client)
    course = _course(live_client, t["token"])
    writer = _student(live_client, t["token"], course, "w@x.edu")
    done = _student(live_client, t["token"], course, "d@x.edu")
    lapsed = _student(live_client, t["token"], course, "l@x.edu")
    _add_students(live_client, t["token"], course, "n@x.edu")
    e = _exam(live_client, t["token"], course_id=course, duration=30)
    for who in (writer, done, lapsed):
        live_client.post(f"/bluebook/me/exams/{e['id']}/start", headers=_auth(who["token"]))
    live_client.post(
        "/bluebook/submissions",
        json={
            "exam_id": e["id"],
            "student_id": done["student_id"],
            "text": "x",
            "warnings": [{"type": "tab_hidden"}],
        },
        headers=_auth(done["token"]),
    )
    # the lapsed student's deadline is in the past
    from original import store

    with store._get_conn() as conn:
        conn.execute(
            "UPDATE bluebook_sessions SET deadline_at = ? WHERE student_key = ?",
            ((rules.now_utc() - timedelta(minutes=1)).isoformat(), lapsed["student_id"]),
        )
        conn.commit()
    live = live_client.get(f"/bluebook/exams/{e['id']}/live", headers=_auth(t["token"])).json()
    by = {r["email"]: r for r in live["students"]}
    assert by["w@x.edu"]["status"] == "writing" and 28 <= by["w@x.edu"]["minutes_left"] <= 30
    assert by["d@x.edu"]["status"] == "submitted" and by["d@x.edu"]["warnings"] == 1
    assert by["l@x.edu"]["status"] == "time_up" and by["l@x.edu"]["minutes_left"] == 0
    assert by["n@x.edu"]["status"] == "not_started"
    assert live["counts"] == {
        "enrolled": 4,
        "writing": 1,
        "submitted": 1,
        "late": 0,
        "not_started": 1,
        "time_up": 1,
    }
    assert [r["status"] for r in live["students"]][:2] == ["writing", "time_up"]


def test_live_view_for_a_workspace_wide_exam_and_scoping(live_client):
    t = _signup(live_client)
    c1 = _course(live_client, t["token"], "A")
    c2 = _course(live_client, t["token"], "B")
    _add_students(live_client, t["token"], c1, "a@x.edu")
    _add_students(live_client, t["token"], c2, "b@x.edu")
    e = _exam(live_client, t["token"])  # no course: everyone in the workspace
    live = live_client.get(f"/bluebook/exams/{e['id']}/live", headers=_auth(t["token"])).json()
    assert live["counts"]["enrolled"] == 2
    other = _signup(live_client, "o@x.edu")
    assert (
        live_client.get(
            f"/bluebook/exams/{e['id']}/live", headers=_auth(other["token"])
        ).status_code
        == 404
    )


def test_submission_takes_title_and_course_from_its_exam(live_client):
    t = _signup(live_client)
    e = _exam(live_client, t["token"], title="Named exam", course="ETH 101")
    sid = live_client.post(
        "/bluebook/submissions", json={"exam_id": e["id"], "text": "x"}, headers=_auth(t["token"])
    ).json()["id"]
    got = live_client.get(f"/bluebook/submissions/{sid}", headers=_auth(t["token"])).json()
    assert (got["exam"], got["course"]) == ("Named exam", "ETH 101")
    # another workspace's exam id is refused outright (it used to be accepted
    # with the title left blank), so neither its title nor a row leaks
    other = _signup(live_client, "o@x.edu")
    refused = live_client.post(
        "/bluebook/submissions", json={"exam_id": e["id"], "text": "x"}, headers=_auth(other["token"])
    )
    assert refused.status_code == 404
    assert refused.json() == {"detail": "exam not found"}
    assert len(get_repository().list_bluebook_submissions_for_exam(e["id"])) == 1
