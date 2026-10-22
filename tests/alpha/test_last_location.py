"""Cross-device "resume where you left off" (2026-10): one saved location per
signed-in account, kept on the server, readable only by its owner, checked
against current access when it is read back, never resuming into an exam
sitting, never holding a link token, and deleted with the student's data."""

from __future__ import annotations

import pytest

from original.repository import get_repository
from tests.alpha.test_past_papers import _fresh, _ok, _workspace  # noqa: F401  (autouse fixture)

URL = "/bluebook/me/location"


def _exam(client, T, title="Resume exam"):
    return _ok(client.post("/bluebook/exams", json={
        "title": title, "status": "ACTIVE", "duration": 25,
        "questions": ["Say something."], "conditions": {"aiDetect": False},
    }, headers=T), 201)


def _put(client, H, **loc):
    return client.put(URL, json=loc, headers=H)


def _get(client, H):
    return _ok(client.get(URL, headers=H))["location"]


@pytest.mark.slow
def test_teacher_location_round_trips_and_is_owner_only(live_client):
    T, [(sid, S), _] = _workspace(live_client, "loc1@example.test")
    T2, _ = _workspace(live_client, "loc1b@example.test", n_students=1)
    assert _get(live_client, T) is None
    _ok(_put(live_client, T, screen="students", entity_kind="student", entity_id=sid,
             tab="work", scroll_fraction=0.62, scroll_anchor=f"row-{sid}"))
    loc = _get(live_client, T)
    assert loc["screen"] == "students" and loc["entity_kind"] == "student" and loc["entity_id"] == sid
    assert loc["tab"] == "work" and loc["scroll_fraction"] == pytest.approx(0.62)
    assert loc["scroll_anchor"] == f"row-{sid}" and loc["updated_at"]
    # Upsert: one row per account, the newest wins.
    _ok(_put(live_client, T, screen="courses", scroll_fraction=0.1))
    assert _get(live_client, T)["screen"] == "courses"
    # Nobody else reads it: another teacher and the student each see only their own.
    assert _get(live_client, T2) is None
    assert _get(live_client, S) is None
    # Not signed in: refused.
    assert live_client.get(URL).status_code in (401, 403)
    assert live_client.put(URL, json={"screen": "students"}).status_code in (401, 403)


@pytest.mark.slow
def test_invalid_locations_are_refused(live_client):
    T, [(sid, S), _] = _workspace(live_client, "loc2@example.test")
    bad = [
        dict(screen="login"), dict(screen="invite"), dict(screen="landing"), dict(screen="nope"),
        dict(screen="students", scroll_fraction=1.5), dict(screen="students", scroll_fraction=-0.1),
        dict(screen="students", tab="has space"), dict(screen="students", entity_kind="exam", entity_id="x"),
        dict(screen="manage-exam"),  # needs its exam
        dict(screen="students", entity_kind="student", entity_id="a" * 200),
        # A link token never fits an id or anchor.
        dict(screen="students", scroll_anchor="?invite=abc.def.ghi"),
        dict(screen="students", entity_kind="student", entity_id="eyJhbGciOi.eyJzdWIi.sig"),
        # A student screen is not a teacher's, and the other way round.
        dict(screen="student-home"),
    ]
    for loc in bad:
        assert _put(live_client, T, **loc).status_code == 422, loc
    assert _put(live_client, S, screen="students").status_code == 422
    assert _put(live_client, S, screen="proctor", entity_kind="exam", entity_id="x").status_code == 422


@pytest.mark.slow
def test_deleted_or_forbidden_entities_fall_back(live_client):
    T, [(sid, S), _] = _workspace(live_client, "loc3@example.test")
    T2, _ = _workspace(live_client, "loc3b@example.test", n_students=1)
    exam = _exam(live_client, T)
    _ok(_put(live_client, T, screen="proctor", entity_kind="exam", entity_id=exam["id"], tab="phones"))
    assert _get(live_client, T)["entity_id"] == exam["id"]
    _ok(live_client.delete(f"/bluebook/exams/{exam['id']}", headers=T))
    assert _get(live_client, T) is None  # deleted exam: back to Overview
    # Another workspace's exam or student: saved for the account, but never handed back.
    other = _exam(live_client, T2, "Other")
    _ok(_put(live_client, T, screen="manage-exam", entity_kind="exam", entity_id=other["id"]))
    assert _get(live_client, T) is None
    _ok(_put(live_client, T, screen="students", entity_kind="student", entity_id="someone:else"))
    assert _get(live_client, T) is None
    # A course that still exists comes back with what the roster screen needs.
    course = _ok(live_client.get("/bluebook/courses", headers=T))["courses"][0]
    _ok(_put(live_client, T, screen="roster", entity_kind="course", entity_id=course["id"]))
    loc = _get(live_client, T)
    assert loc["entity_id"] == course["id"] and loc["entity"]["name"] == course["name"]


@pytest.mark.slow
def test_student_never_resumes_into_a_sitting(live_client):
    T, [(sid, S), (sid2, S2)] = _workspace(live_client, "loc4@example.test")
    exam = _exam(live_client, T)
    # Saved while writing: stored and returned as the exam's start screen.
    _ok(_put(live_client, S, screen="exam", entity_kind="exam", entity_id=exam["id"], scroll_fraction=0.9))
    loc = _get(live_client, S)
    assert loc["screen"] == "briefing" and loc["entity_id"] == exam["id"]
    assert loc["scroll_fraction"] == 0  # the briefing opens at its top
    # Sealed: nothing to resume into; the student lands on their home.
    _ok(live_client.post(f"/bluebook/me/exams/{exam['id']}/start", headers=S))
    _ok(live_client.post("/bluebook/submissions", json={
        "exam_id": exam["id"], "student_id": sid, "word_count": 2, "text": "two words", "answers": ["two words"],
    }, headers=S), 201)
    assert _get(live_client, S) is None
    # Another student's submission is never resumed.
    subs = get_repository().list_bluebook_submissions_for_student(sid)
    _ok(_put(live_client, S2, screen="student-submission", entity_kind="submission", entity_id=subs[0]["id"]))
    assert _get(live_client, S2) is None
    _ok(_put(live_client, S, screen="student-submission", entity_kind="submission", entity_id=subs[0]["id"]))
    assert _get(live_client, S)["entity_id"] == subs[0]["id"]


@pytest.mark.slow
def test_withdrawal_deletion_removes_the_location(live_client):
    T, [(sid, S), _] = _workspace(live_client, "loc5@example.test")
    _ok(_put(live_client, S, screen="student-account"))
    assert get_repository().get_last_location(sid) is not None
    assert get_repository().delete_student(sid) is True
    assert get_repository().get_last_location(sid) is None
