"""A student submits a stored exam once: two tabs cannot both land.

Within one tab a retried seal reuses its submission_uuid and the server
returns the first row (test_bluebook_api.py::test_seal_replay_returns_prior_result).
Two tabs open on the same exam each mint their own uuid, so both used to be
recorded. The dashboard start route already refused a second sitting ("You
have already submitted this exam."); the seal now holds the same rule, and so
does the launch-link session route, so a tab opened after the seal says so
before the student writes anything.

The rule is deliberately narrow: only a signed-in student, only an exam the
workspace has stored. Staff recording a submission (a teacher previewing
their own exam) and unstored sample ids behave as before.
"""

from __future__ import annotations

import threading
import time

from original import student_auth

SID = "demo:dana"


def _student():
    return {"Authorization": f"Bearer {student_auth.mint_session(SID, 'Dana')}"}


def _exam(live_client) -> str:
    r = live_client.post(
        "/bluebook/exams",
        json={"title": "Once only", "course": "HIST 1", "duration": 60, "prompt": "Discuss.", "status": "PUBLISHED"},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _seal(live_client, exam_id, uuid, headers=None, student_id=SID):
    return live_client.post(
        "/bluebook/submissions",
        headers=headers if headers is not None else _student(),
        json={
            "exam_id": exam_id, "student_id": student_id, "candidate": "Dana",
            "word_count": 12, "time_min": 5, "status": "SUBMITTED",
            "text": "Twelve words of an answer to the question that was set.",
            "submission_uuid": uuid,
        },
    )


def _rows(exam_id):
    from original.repository import get_repository

    return [s for s in get_repository().list_bluebook_submissions_for_student(SID) if s.get("exam_id") == exam_id]


def test_a_second_tab_cannot_submit_the_same_exam_again(live_client, store_reset):
    exam_id = _exam(live_client)
    assert _seal(live_client, exam_id, "tab-a").status_code == 201
    r = _seal(live_client, exam_id, "tab-b")
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "You have already submitted this collection."
    assert len(_rows(exam_id)) == 1


def test_a_retry_of_the_same_seal_still_returns_the_first_row(live_client, store_reset):
    exam_id = _exam(live_client)
    first = _seal(live_client, exam_id, "tab-a")
    again = _seal(live_client, exam_id, "tab-a")
    assert again.status_code == 201
    assert again.json()["id"] == first.json()["id"] and again.json()["duplicate"] is True
    assert len(_rows(exam_id)) == 1


def test_staff_and_unstored_exams_are_unchanged(live_client, store_reset):
    exam_id = _exam(live_client)
    # The anonymous demo principal is staff in the demo sandbox.
    assert _seal(live_client, exam_id, "staff-1", headers={}).status_code == 201
    assert _seal(live_client, exam_id, "staff-2", headers={}).status_code == 201
    # A sample or launch-link id the workspace never stored.
    assert _seal(live_client, "sample-exam", "s-1").status_code == 201
    assert _seal(live_client, "sample-exam", "s-2").status_code == 201


def test_a_tab_opened_after_the_seal_is_told_before_writing(live_client, store_reset):
    exam_id = _exam(live_client)
    start = live_client.post(f"/bluebook/exams/{exam_id}/session", headers=_student(), json={"student_id": SID})
    assert start.status_code == 200, start.text
    assert _seal(live_client, exam_id, "tab-a").status_code == 201
    again = live_client.post(f"/bluebook/exams/{exam_id}/session", headers=_student(), json={"student_id": SID})
    assert again.status_code == 409
    assert again.json()["detail"] == "You have already submitted this collection."


def test_two_seals_at_the_same_moment_record_one_submission(live_client, store_reset, monkeypatch):
    """Both requests pass the "already submitted?" check before either has
    written, unless the check and the write happen together."""
    from original.repository import SqliteRepository

    exam_id = _exam(live_client)
    real_put = SqliteRepository.put_bluebook_submission

    def slow_put(self, rec):
        time.sleep(0.3)  # widen the window between the check and the write
        return real_put(self, rec)

    monkeypatch.setattr(SqliteRepository, "put_bluebook_submission", slow_put)
    statuses = []
    threads = [
        threading.Thread(target=lambda u=u: statuses.append(_seal(live_client, exam_id, u).status_code))
        for u in ("tab-a", "tab-b")
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(statuses) == [201, 409]
    assert len(_rows(exam_id)) == 1
