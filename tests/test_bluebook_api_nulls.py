"""Regression: Bluebook create endpoints must accept explicit JSON nulls.

The pre-typed dict contract accepted ``maxWords: null`` (the e2e fixtures and
older clients send it for "no limit") and the handlers coerce via
``_int_or(..., default)``. When WS-7 introduced typed request models, strict
``int`` annotations 422'd those nulls before the handler ran — caught by the
tenancy-isolation e2e spec on PR #30. These tests pin the tolerant contract
at the API layer so it can't regress silently again.
"""


def test_create_exam_accepts_null_numeric_fields(live_client, store_reset):
    resp = live_client.post(
        "/bluebook/exams",
        json={
            "title": "Null-tolerance regression exam",
            "course": "REG-101",
            "duration": None,
            "minWords": None,
            "maxWords": None,
            "prompt": "",
            "status": "ACTIVE",
        },
    )
    assert resp.status_code in (200, 201), resp.text
    rec = resp.json()
    # _int_or coerces nulls to the documented defaults
    assert rec["duration"] == 90
    assert rec["minWords"] == 0
    assert rec["maxWords"] == 0


def test_record_submission_accepts_null_numeric_fields(live_client, store_reset):
    resp = live_client.post(
        "/bluebook/submissions",
        json={
            "student_id": "reg-student",
            "candidate": "Regression Candidate",
            "exam_title": "Null-tolerance regression exam",
            "word_count": None,
            "time_min": None,
        },
    )
    assert resp.status_code in (200, 201), resp.text
    # The create response is deliberately minimal ({id, status}); verify the
    # coerced values through the list endpoint instead.
    sub_id = resp.json()["id"]
    listed = live_client.get("/bluebook/submissions").json()["submissions"]
    rec = next(s for s in listed if s["id"] == sub_id)
    # the list serializer exposes frontend-facing key names
    assert rec["words"] == 0
    assert rec["timeMin"] == 0
