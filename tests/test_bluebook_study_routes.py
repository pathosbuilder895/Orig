from __future__ import annotations

import csv
import io
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from original import principal as principal_mod
from original.onboarding import set_original
from original.repository import get_repository

PW = "s3cret-passw0rd"
ANSWER = (
    "Careful arguments develop from premises, examples, objections and a measured conclusion. " * 8
)


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


def _workspace(client, email="prof@school.edu", *, original=True, ai_detect=True):
    response = client.post(
        "/auth/signup",
        json={"email": email, "password": PW, "name": "Prof", "accept_terms": True},
    )
    assert response.status_code == 201, response.text
    staff = response.json()
    if original:
        set_original(email, True)
    course = client.post(
        "/bluebook/courses",
        json={"name": "Ethics", "code": "ETH"},
        headers=_auth(staff["token"]),
    ).json()["id"]
    exam = client.post(
        "/bluebook/exams",
        json={
            "title": "Midterm",
            "status": "ACTIVE",
            "prompt": "Discuss.",
            "course_id": course,
            "conditions": {"aiDetect": ai_detect},
        },
        headers=_auth(staff["token"]),
    ).json()
    return staff, course, exam


def _student(client, staff, course, email="student@school.edu"):
    row = client.post(
        f"/bluebook/courses/{course}/students",
        json={"students": [{"email": email, "name": "Student"}]},
        headers=_auth(staff["token"]),
    ).json()["students"][0]
    token = parse_qs(urlparse(row["invite_path"]).query)["invite"][0]
    response = client.post("/auth/invite/redeem", json={"token": token, "password": PW})
    assert response.status_code == 200, response.text
    return response.json()


def _fake_score(score):
    return SimpleNamespace(
        authorship=SimpleNamespace(deviation_score=score),
        feature_vector={"feature_a": 0.25, "feature_b": 0.75},
    )


def _seal(client, student, exam_id, *, submission_uuid="seal-1"):
    response = client.post(
        "/bluebook/submissions",
        headers=_auth(student["token"]),
        json={
            "exam_id": exam_id,
            "student_id": student["student_id"],
            "text": ANSWER,
            "answers": [ANSWER],
            "word_count": len(ANSWER.split()),
            "submission_uuid": submission_uuid,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_staff_can_set_and_clear_labels_but_students_cannot_see_or_change_them(
    live_client,
):
    staff, course, exam = _workspace(live_client)
    student = _student(live_client, staff, course)
    submission_id = _seal(live_client, student, exam["id"])
    headers = _auth(staff["token"])

    changed = live_client.patch(
        f"/bluebook/submissions/{submission_id}/study-label",
        headers=headers,
        json={"study_label": "shadow", "imitated_student_id": student["student_id"]},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json() == {"submission_id": submission_id, "changed": True}
    stored = get_repository().get_bluebook_study_submission(submission_id)
    assert stored["study_label"] == "shadow"
    assert stored["imitated_student_id"] == student["student_id"]

    denied = live_client.patch(
        f"/bluebook/submissions/{submission_id}/study-label",
        headers=_auth(student["token"]),
        json={"study_label": "student-edit"},
    )
    assert denied.status_code == 403

    listed = live_client.get("/bluebook/me/submissions", headers=_auth(student["token"]))
    detail = live_client.get(
        f"/bluebook/me/submissions/{submission_id}", headers=_auth(student["token"])
    )
    for payload in (listed.json(), detail.json()):
        assert "study_label" not in str(payload)
        assert "imitated_student_id" not in str(payload)

    cleared = live_client.patch(
        f"/bluebook/submissions/{submission_id}/study-label",
        headers=headers,
        json={"study_label": "", "imitated_student_id": None},
    )
    assert cleared.status_code == 200
    stored = get_repository().get_bluebook_study_submission(submission_id)
    assert stored["study_label"] is None
    assert stored["imitated_student_id"] is None

    audits = get_repository().list_audit(action="bluebook_study_labels")
    assert audits["total"] == 2


def test_batch_csv_is_staff_only_validated_and_audited_per_changed_submission(live_client):
    staff, course, exam = _workspace(live_client)
    student = _student(live_client, staff, course)
    sub1 = _seal(live_client, student, exam["id"], submission_uuid="seal-1")
    sub2 = _seal(live_client, student, exam["id"], submission_uuid="seal-2")
    body = (
        "submission_id,study_label,imitated_student_id\n"
        f"{sub1},human,\n{sub2},shadow,{student['student_id']}\n"
    )
    response = live_client.post(
        "/bluebook/study-labels.csv",
        content=body,
        headers={**_auth(staff["token"]), "Content-Type": "text/csv"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"rows": 2, "changed": 2, "unchanged": 0}
    assert get_repository().get_bluebook_study_submission(sub1)["study_label"] == "human"
    assert get_repository().get_bluebook_study_submission(sub2)["study_label"] == "shadow"
    assert get_repository().list_audit(action="bluebook_study_labels")["total"] == 2

    invalid = live_client.post(
        "/bluebook/study-labels.csv",
        content=f"submission_id,label,imitated_student_id\n{sub1},human,\n",
        headers={**_auth(staff["token"]), "Content-Type": "text/csv"},
    )
    assert invalid.status_code == 422

    malformed = live_client.post(
        "/bluebook/study-labels.csv",
        content=f"submission_id,study_label,imitated_student_id\n{sub1},human\n",
        headers={**_auth(staff["token"]), "Content-Type": "text/csv"},
    )
    assert malformed.status_code == 422

    student_denied = live_client.post(
        "/bluebook/study-labels.csv",
        content=body,
        headers={**_auth(student["token"]), "Content-Type": "text/csv"},
    )
    assert student_denied.status_code == 403


def test_seal_scores_on_server_only_when_exam_and_tenant_allow_original(live_client, monkeypatch):
    from original.routers import students_scoring

    staff, course, exam = _workspace(live_client)
    student = _student(live_client, staff, course)
    calls = []
    monkeypatch.setattr(
        students_scoring,
        "score_submission",
        lambda sid, req, request=None: calls.append((sid, req.submission_id)) or _fake_score(0.23),
    )
    submission_id = _seal(live_client, student, exam["id"])
    stored = get_repository().get_bluebook_study_submission(submission_id)
    assert calls == [(student["student_id"], submission_id)]
    assert stored["style_score"] == 0.23
    assert stored["style_features"] == {"feature_a": 0.25, "feature_b": 0.75}
    assert stored["style_engine_version"] == "original-layer7-style-v1"
    assert stored["style_threshold_version"].startswith("thresholds-sha256:")


def test_seal_replay_retries_server_score_for_the_existing_submission(live_client, monkeypatch):
    from original.routers import students_scoring

    staff, course, exam = _workspace(live_client)
    student = _student(live_client, staff, course)
    calls = []

    def score(sid, req, request=None):
        calls.append(req.submission_id)
        return _fake_score(0.31)

    monkeypatch.setattr(students_scoring, "score_submission", score)
    first = _seal(live_client, student, exam["id"], submission_uuid="retry-score")
    second = _seal(live_client, student, exam["id"], submission_uuid="retry-score")
    assert second == first
    assert calls == [first, first]
    assert get_repository().get_bluebook_study_submission(first)["style_score"] == 0.31


@pytest.mark.parametrize(
    "original,ai_detect,expected_calls",
    [(False, True, 0), (True, False, 0)],
)
def test_seal_scoring_respects_exam_flag_and_tenant_product(
    live_client, monkeypatch, original, ai_detect, expected_calls
):
    from original.routers import students_scoring

    staff, course, exam = _workspace(
        live_client,
        email=f"prof-{original}-{ai_detect}@school.edu",
        original=original,
        ai_detect=ai_detect,
    )
    student = _student(
        live_client, staff, course, email=f"student-{original}-{ai_detect}@school.edu"
    )
    calls = []
    monkeypatch.setattr(
        students_scoring,
        "score_submission",
        lambda *args, **kwargs: calls.append(args) or _fake_score(0.23),
    )
    _seal(live_client, student, exam["id"])
    assert len(calls) == expected_calls


def test_staff_rescore_is_idempotent_and_scopes_to_exam(live_client, monkeypatch):
    from original.routers import students_scoring

    staff, course, exam = _workspace(live_client)
    student = _student(live_client, staff, course)
    calls = []
    monkeypatch.setattr(
        students_scoring,
        "score_submission",
        lambda sid, req, request=None: calls.append(req.submission_id) or _fake_score(0.41),
    )
    submission_id = _seal(live_client, student, exam["id"])
    calls.clear()
    first = live_client.post(f"/bluebook/exams/{exam['id']}/rescore", headers=_auth(staff["token"]))
    second = live_client.post(
        f"/bluebook/exams/{exam['id']}/rescore", headers=_auth(staff["token"])
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["scored"] == second.json()["scored"] == 1
    assert calls == [submission_id, submission_id]
    assert get_repository().get_bluebook_study_submission(submission_id)["style_score"] == 0.41


def test_study_export_endpoint_uses_salt_and_never_returns_raw_student_ids(
    live_client, monkeypatch
):
    staff, course, exam = _workspace(live_client)
    student = _student(live_client, staff, course)
    submission_id = _seal(live_client, student, exam["id"])
    live_client.patch(
        f"/bluebook/submissions/{submission_id}/study-label",
        headers=_auth(staff["token"]),
        json={"study_label": "human"},
    )
    monkeypatch.setenv("STUDY_EXPORT_SALT", "dummy-study-export-salt")
    response = live_client.get(
        f"/bluebook/exams/{exam['id']}/study-export.csv", headers=_auth(staff["token"])
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert student["student_id"] not in response.text
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows[0]["study_label"] == "human"
    assert rows[0]["submission_id"] == submission_id
    assert rows[0]["student_hash"].startswith("hmac-sha256:")


def test_study_routes_are_tenant_scoped_and_require_original_product(live_client):
    staff_a, course_a, exam_a = _workspace(live_client, email="a@school.edu")
    student = _student(live_client, staff_a, course_a)
    sub = _seal(live_client, student, exam_a["id"])
    staff_b, _, exam_b = _workspace(live_client, email="b@school.edu")

    denied = live_client.patch(
        f"/bluebook/submissions/{sub}/study-label",
        headers=_auth(staff_b["token"]),
        json={"study_label": "human"},
    )
    assert denied.status_code == 404
    no_original, _, no_original_exam = _workspace(
        live_client, email="bluebook-only@school.edu", original=False
    )
    denied_product = live_client.get(
        f"/bluebook/exams/{no_original_exam['id']}/study-export.csv",
        headers=_auth(no_original["token"]),
    )
    assert denied_product.status_code == 403
