"""Professor-approved writing baselines (plan Phase 7,
docs/superpowers/specs/2026-10-05-baseline-approval-design.md)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException

from original import principal as principal_mod
from original.onboarding import set_original
from original.repository import get_repository

PW = "s3cret-passw0rd"
ANSWERS = [
    "Augustine argues that the restless heart finds rest only in God, and he builds the "
    "argument slowly, from memory and desire, through the long middle books of the work, "
    "until the reader sees that the search was the subject all along.",
    "I find the argument persuasive in its account of desire but less so in its account of "
    "memory, which seems to me to carry more of the weight than he admits, and which a modern "
    "reader would want to examine before accepting the conclusion he draws from it.",
]


@pytest.fixture(autouse=True)
def _isolate(store_reset, live_app):
    import original.api as api

    api._login_attempts.clear()
    principal_mod.invalidate_tenant_cache()
    yield
    api._login_attempts.clear()
    principal_mod.invalidate_tenant_cache()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _workspace(client, email="prof@school.edu", original=True):
    r = client.post(
        "/auth/signup",
        json={"email": email, "password": PW, "name": "Prof", "accept_terms": True},
    )
    assert r.status_code == 201, r.text
    prof = r.json()
    if original:
        set_original(email, True)
    course = client.post(
        "/bluebook/courses", json={"name": "Ethics", "code": "ETH"}, headers=_auth(prof["token"])
    ).json()["id"]
    exam = client.post(
        "/bluebook/exams",
        json={"title": "Midterm", "status": "ACTIVE", "prompt": "Discuss.", "course_id": course},
        headers=_auth(prof["token"]),
    ).json()
    return prof, course, exam


def _student(client, prof, course, email):
    row = client.post(
        f"/bluebook/courses/{course}/students",
        json={"students": [{"email": email, "name": email.split("@")[0]}]},
        headers=_auth(prof["token"]),
    ).json()["students"][0]
    token = parse_qs(urlparse(row["invite_path"]).query)["invite"][0]
    r = client.post("/auth/invite/redeem", json={"token": token, "password": PW})
    assert r.status_code == 200, r.text
    return r.json()


def _seal(client, student, exam_id, answers=ANSWERS):
    client.post(f"/bluebook/me/exams/{exam_id}/start", headers=_auth(student["token"]))
    body = {
        "exam_id": exam_id,
        "student_id": student["student_id"],
        "word_count": 120,
        "text": "\n\n".join(f"Question {i + 1}.\n{a}" for i, a in enumerate(answers)),
        "answers": answers,
        "submission_uuid": f"uuid-{student['student_id']}-{exam_id}",
    }
    r = client.post("/bluebook/submissions", json=body, headers=_auth(student["token"]))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _sample_count(student) -> int:
    state = get_repository().get(student["student_id"])
    return 0 if state is None else state.sample_count


def test_add_puts_the_answers_in_the_students_baseline(live_client):
    prof, course, exam = _workspace(live_client)
    stu = _student(live_client, prof, course, "one@school.edu")
    sub = _seal(live_client, stu, exam["id"])

    r = live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "added"
    state = get_repository().get(stu["student_id"])
    assert state.sample_count == 1
    assert state.samples[0].provenance == "proctored"
    assert state.samples[0].text == "\n\n".join(ANSWERS)  # no "Question N." headings
    assert state.samples[0].assignment == "Midterm"
    status = live_client.get(f"/bluebook/exams/{exam['id']}/baseline", headers=_auth(prof["token"]))
    rows = status.json()["submissions"]
    assert [(r["submission_id"], r["in_baseline"], r["has_text"]) for r in rows] == [(sub, True, True)]


def test_adding_twice_is_a_no_op(live_client):
    prof, course, exam = _workspace(live_client)
    stu = _student(live_client, prof, course, "one@school.edu")
    sub = _seal(live_client, stu, exam["id"])
    live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))

    r = live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))

    assert r.json()["status"] == "already_in_baseline"
    assert _sample_count(stu) == 1


def test_remove_then_add_again(live_client):
    prof, course, exam = _workspace(live_client)
    stu = _student(live_client, prof, course, "one@school.edu")
    sub = _seal(live_client, stu, exam["id"])
    live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))

    removed = live_client.delete(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))
    again = live_client.delete(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))
    readded = live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))

    assert removed.json()["status"] == "removed"
    assert again.json()["status"] == "not_in_baseline"
    assert readded.json()["status"] == "added"
    assert _sample_count(stu) == 1


def test_remove_finds_a_sample_the_old_seal_added_with_headings(live_client):
    from original.routers import students_baseline
    from original.schemas import AddSampleRequest

    prof, course, exam = _workspace(live_client)
    stu = _student(live_client, prof, course, "one@school.edu")
    sub = _seal(live_client, stu, exam["id"])
    stored = get_repository().get_bluebook_submission(sub)
    # What the pre-Phase-7 seal sent: the stored text, headings included.
    students_baseline.add_baseline(
        stu["student_id"], AddSampleRequest(text=stored["text"], provenance="unverified"), None
    )
    assert _sample_count(stu) == 1
    status = live_client.get(f"/bluebook/exams/{exam['id']}/baseline", headers=_auth(prof["token"]))
    assert status.json()["submissions"][0]["in_baseline"] is True

    r = live_client.delete(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))

    assert r.json()["status"] == "removed"
    assert _sample_count(stu) == 0


def test_a_sample_held_by_the_drift_gate_is_reported_not_added(live_client, monkeypatch):
    from original.routers import bluebook_baselines

    def held(student_id, req, request):
        raise HTTPException(status_code=202, detail={"status": "pending_review"})

    monkeypatch.setattr(bluebook_baselines, "add_baseline", held)
    prof, course, exam = _workspace(live_client)
    stu = _student(live_client, prof, course, "one@school.edu")
    sub = _seal(live_client, stu, exam["id"])

    r = live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))

    assert r.status_code == 200
    assert r.json()["status"] == "held"
    assert "held for review" in r.json()["detail"]
    assert _sample_count(stu) == 0


def test_bulk_adds_every_sealed_submission(live_client):
    prof, course, exam = _workspace(live_client)
    one = _student(live_client, prof, course, "one@school.edu")
    two = _student(live_client, prof, course, "two@school.edu")
    blank = _student(live_client, prof, course, "blank@school.edu")
    _seal(live_client, one, exam["id"])
    _seal(live_client, two, exam["id"], answers=[ANSWERS[1], ANSWERS[0]])
    _seal(live_client, blank, exam["id"], answers=[""])

    first = live_client.post(f"/bluebook/exams/{exam['id']}/baseline", headers=_auth(prof["token"]))
    second = live_client.post(f"/bluebook/exams/{exam['id']}/baseline", headers=_auth(prof["token"]))

    assert first.status_code == 200, first.text
    body = first.json()
    assert (body["added"], body["already_in_baseline"], body["held"]) == (2, 0, 0)
    assert (body["nothing_written"], body["errors"]) == (1, 0)
    assert len(body["results"]) == 3
    assert second.json()["already_in_baseline"] == 2


def test_empty_submission_is_refused(live_client):
    prof, course, exam = _workspace(live_client)
    stu = _student(live_client, prof, course, "one@school.edu")
    sub = _seal(live_client, stu, exam["id"], answers=[""])

    r = live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))

    assert r.status_code == 422
    assert r.json()["detail"] == "Nothing written to add."


def test_bluebook_only_workspace_is_refused(live_client):
    prof, course, exam = _workspace(live_client, original=False)
    stu = _student(live_client, prof, course, "one@school.edu")
    sub = _seal(live_client, stu, exam["id"])
    h = _auth(prof["token"])

    responses = [
        live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=h),
        live_client.delete(f"/bluebook/submissions/{sub}/baseline", headers=h),
        live_client.post(f"/bluebook/exams/{exam['id']}/baseline", headers=h),
        live_client.get(f"/bluebook/exams/{exam['id']}/baseline", headers=h),
    ]

    assert [r.status_code for r in responses] == [403, 403, 403, 403]
    assert all(r.json()["detail"] == "This workspace's plan does not include Original." for r in responses)


def test_another_workspace_gets_404(live_client):
    prof, course, exam = _workspace(live_client)
    stu = _student(live_client, prof, course, "one@school.edu")
    sub = _seal(live_client, stu, exam["id"])
    other, _c, _e = _workspace(live_client, email="other@school.edu")
    h = _auth(other["token"])

    assert live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=h).status_code == 404
    assert live_client.delete(f"/bluebook/submissions/{sub}/baseline", headers=h).status_code == 404
    assert live_client.post(f"/bluebook/exams/{exam['id']}/baseline", headers=h).status_code == 404
    assert live_client.get(f"/bluebook/exams/{exam['id']}/baseline", headers=h).status_code == 404


def test_a_student_cannot_approve(live_client):
    prof, course, exam = _workspace(live_client)
    stu = _student(live_client, prof, course, "one@school.edu")
    sub = _seal(live_client, stu, exam["id"])

    r = live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=_auth(stu["token"]))

    assert r.status_code == 403
    assert _sample_count(stu) == 0


def test_every_action_is_audited_without_student_text(live_client):
    prof, course, exam = _workspace(live_client)
    stu = _student(live_client, prof, course, "one@school.edu")
    sub = _seal(live_client, stu, exam["id"])
    h = _auth(prof["token"])
    live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=h)
    live_client.delete(f"/bluebook/submissions/{sub}/baseline", headers=h)
    live_client.post(f"/bluebook/exams/{exam['id']}/baseline", headers=h)

    repo = get_repository()
    for action in ("baseline_approve", "baseline_remove", "baseline_approve_bulk"):
        items = repo.list_audit(action=action)["items"]
        assert items, action
        assert "Augustine" not in repr(items)
