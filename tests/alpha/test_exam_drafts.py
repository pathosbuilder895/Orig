"""Server copy of a student's unsealed exam draft (2026-10): saved by the
signed-in student, restored from any browser, never shown to staff, refused
and deleted once the exam is sealed, deleted with the student's data, and
never part of the sealed text or a baseline."""

from __future__ import annotations

import pytest

from original.repository import get_repository
from tests.alpha.test_past_papers import _fresh, _ok, _workspace  # noqa: F401  (autouse fixture)


def _exam(client, T, title="Draft exam"):
    return _ok(client.post("/bluebook/exams", json={
        "title": title, "status": "ACTIVE", "duration": 25,
        "questions": ["Say something."], "conditions": {"aiDetect": False},
    }, headers=T), 201)


def _put(client, exam_id, H, content, at=1000):
    return client.put(f"/bluebook/exams/{exam_id}/draft",
                      json={"content": content, "answers": [content], "client_saved_at": at}, headers=H)


@pytest.mark.slow
def test_draft_round_trips_for_the_student_only(live_client):
    T, [(sid, S), (_sid2, S2)] = _workspace(live_client, "dr1@example.test")
    exam = _exam(live_client, T)
    assert _ok(live_client.get(f"/bluebook/exams/{exam['id']}/draft", headers=S))["draft"] is None
    _ok(_put(live_client, exam["id"], S, "first words", at=111))
    _ok(_put(live_client, exam["id"], S, "first words and more", at=222))
    d = _ok(live_client.get(f"/bluebook/exams/{exam['id']}/draft", headers=S))["draft"]
    assert d["content"] == "first words and more" and d["answers"] == ["first words and more"]
    assert d["client_saved_at"] == 222 and d["updated_at"]
    # Another student sees only their own (none); staff are refused; no sign-in is refused.
    assert _ok(live_client.get(f"/bluebook/exams/{exam['id']}/draft", headers=S2))["draft"] is None
    assert live_client.get(f"/bluebook/exams/{exam['id']}/draft", headers=T).status_code == 403
    assert _put(live_client, exam["id"], T, "staff").status_code == 403
    assert live_client.get(f"/bluebook/exams/{exam['id']}/draft").status_code in (401, 403)
    assert live_client.get("/bluebook/exams/nope/draft", headers=S).status_code == 404


@pytest.mark.slow
def test_seal_deletes_the_draft_and_later_saves_are_refused(live_client):
    T, [(sid, S), _] = _workspace(live_client, "dr2@example.test")
    exam = _exam(live_client, T)
    _ok(_put(live_client, exam["id"], S, "unsealed draft text"))
    _ok(live_client.post(f"/bluebook/me/exams/{exam['id']}/start", headers=S))
    sealed = "the sealed answer, which is what counts"
    _ok(live_client.post("/bluebook/submissions", json={
        "exam_id": exam["id"], "student_id": sid, "word_count": 7, "text": sealed, "answers": [sealed],
    }, headers=S), 201)
    assert get_repository().get_exam_draft(exam["id"], sid) is None
    got = _ok(live_client.get(f"/bluebook/exams/{exam['id']}/draft", headers=S))
    assert got == {"draft": None, "submitted": True}
    r = _put(live_client, exam["id"], S, "after the seal")
    assert r.status_code == 409
    assert get_repository().get_exam_draft(exam["id"], sid) is None
    # The sealed text is the one that was sealed, not the draft.
    subs = get_repository().list_bluebook_submissions_for_student(sid)
    assert len(subs) == 1
    full = get_repository().get_bluebook_submission(subs[0]["id"])
    assert full["text"] == sealed


@pytest.mark.slow
def test_withdrawal_deletion_removes_drafts(live_client):
    T, [(sid, S), _] = _workspace(live_client, "dr3@example.test")
    exam = _exam(live_client, T)
    _ok(_put(live_client, exam["id"], S, "draft to be deleted"))
    assert get_repository().get_exam_draft(exam["id"], sid) is not None
    assert get_repository().delete_student(sid) is True
    assert get_repository().get_exam_draft(exam["id"], sid) is None


@pytest.mark.slow
def test_oversized_draft_is_refused(live_client):
    T, [(sid, S), _] = _workspace(live_client, "dr4@example.test")
    exam = _exam(live_client, T)
    from original import bluebook_rules as rules
    r = _put(live_client, exam["id"], S, "x" * (rules.MAX_TEXT_CHARS + 1))
    assert r.status_code in (413, 422)
