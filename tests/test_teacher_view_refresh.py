"""Alpha bug 2026-10-20 (pilot 859436e): after a student signed in in the
teacher's browser, the teacher saw no examinations or submissions.

The server side was never the problem; these pin that, so the fix stays in
the client: a student redeeming an invite does not revoke the teacher's
token, the teacher's lists still carry the sealed work (with the student_id
the Students page's "View work" filters on), and a student token is refused
on the teacher routes (which is what a clobbered browser was sending).
"""

from __future__ import annotations

from tests.test_bluebook_self_serve import (  # noqa: F401  (fixtures re-used)
    _auth,
    _course,
    _exam,
    _isolate,
    _signup,
    _student,
)


def test_teacher_still_sees_work_after_student_signs_in(live_client):
    t = _signup(live_client)
    course = _course(live_client, t["token"])
    e = _exam(live_client, t["token"], course_id=course)
    s = _student(live_client, t["token"], course, "ana@x.edu")
    r = live_client.post(
        "/bluebook/submissions",
        json={"exam_id": e["id"], "student_id": s["student_id"], "text": "sealed words here"},
        headers=_auth(s["token"]),
    )
    assert r.status_code == 201, r.text

    teacher = _auth(t["token"])
    exams = live_client.get("/bluebook/exams", headers=teacher)
    assert exams.status_code == 200 and [x["id"] for x in exams.json()["exams"]] == [e["id"]]
    subs = live_client.get("/bluebook/submissions", headers=teacher).json()["submissions"]
    assert [x["student_id"] for x in subs] == [s["student_id"]]
    sub = live_client.get(f"/bluebook/submissions/{subs[0]['id']}", headers=teacher)
    assert sub.status_code == 200 and "sealed words here" in sub.text
    rows = live_client.get("/bluebook/students", headers=teacher).json()["students"]
    assert [(r["student_id"], r["submissions"]) for r in rows] == [(s["student_id"], 1)]

    student = _auth(s["token"])
    for path in ("/bluebook/students", "/bluebook/submissions"):
        assert live_client.get(path, headers=student).status_code == 403, path
