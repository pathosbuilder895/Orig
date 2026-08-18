"""
API-level tests for the Bluebook exam-session endpoint, idempotent seal
replay, late tagging, and the baseline seal-replay guard (exam-day
robustness spec §1-§2).

Endpoints covered (handlers live in original/routers/ after the WS-7.3 split):
  POST /bluebook/exams/{exam_id}/session   begin/resume a sitting, pin deadline
        -> original/routers/bluebook.py:bluebook_start_session
  POST /bluebook/submissions               idempotent seal + late tagging
        -> original/routers/bluebook.py:bluebook_record_submission
  POST /students/{id}/baseline             seal-replay dedup guard
        -> original/routers/students_baseline.py:add_baseline

Mirrors the fixture style of tests/test_bluebook_api_nulls.py (the sibling
WS-7 regression file for this same endpoint family): the session-scoped
``live_app``/``live_client`` fixtures + per-test ``store_reset`` from
tests/conftest.py, not a locally-defined ``app``/``client`` pair.

Note: this file does not attempt to restore the full CRUD/tenant-scoping/
professor-only-gate/SECRET_KEY-lifespan coverage that an older, now-orphaned
copy of this file (pre-transplant branch, commit e429668) had — that
coverage is not present anywhere in the current live-stack test suite
(only tests/test_bluebook_api_nulls.py touches these endpoints today) and
restoring it is out of scope for this task; see task-7-report.md.
"""

import pytest

from original import principal as pr


def _auth(token: str):
    return {"Authorization": f"Bearer {token}"}


def _exam_body(**overrides):
    body = {
        "title": "Midterm Essay",
        "course": "THEO 501",
        "duration": 90,
        "minWords": 200,
        "maxWords": 2000,
        "prompt": "Discuss the doctrine of justification by faith.",
        "status": "PUBLISHED",
    }
    body.update(overrides)
    return body


def _submission_body(exam_id=None, **overrides):
    body = {
        "exam_id": exam_id,
        "student_id": "tenanta:carol",
        "candidate": "Carol Smith",
        "exam_title": "Midterm Essay",
        "course": "THEO 501",
        "word_count": 850,
        "time_min": 62,
        "stylometric": 92,
        "ai_score": 4,
        "status": "SUBMITTED",
    }
    body.update(overrides)
    return body


# ── Exam sessions: server-pinned deadline (robustness spec §1) ────────────────


def test_session_pins_deadline(live_client, store_reset):
    prof = pr.mint_principal_token("prof_a", "professor", "tenanta")
    exam = live_client.post(
        "/bluebook/exams", json=_exam_body(duration=30), headers=_auth(prof)
    ).json()
    r1 = live_client.post(
        f"/bluebook/exams/{exam['id']}/session",
        json={"student_id": "tenanta:carol", "candidate": ""},
        headers=_auth(prof),
    )
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["duration_seconds"] == 30 * 60
    assert b1["deadline_at"] > b1["started_at"]
    r2 = live_client.post(
        f"/bluebook/exams/{exam['id']}/session",
        json={"student_id": "tenanta:carol", "candidate": ""},
        headers=_auth(prof),
    )
    assert r2.json()["deadline_at"] == b1["deadline_at"]
    assert r2.json()["started_at"] == b1["started_at"]


def test_session_unknown_exam_404(live_client, store_reset):
    r = live_client.post(
        "/bluebook/exams/no-such-exam/session",
        json={"student_id": "demo:x", "candidate": ""},
    )
    assert r.status_code == 404, r.text


def test_session_requires_some_identity(live_client, store_reset):
    exam = live_client.post("/bluebook/exams", json=_exam_body()).json()
    r = live_client.post(
        f"/bluebook/exams/{exam['id']}/session",
        json={"student_id": "", "candidate": ""},
    )
    assert r.status_code == 422, r.text


# ── Seal idempotency + late tagging (robustness spec §2) ──────────────────────


def test_seal_replay_returns_prior_result(live_client, store_reset):
    r1 = live_client.post(
        "/bluebook/submissions", json=_submission_body(submission_uuid="uu-x")
    ).json()
    r2 = live_client.post(
        "/bluebook/submissions", json=_submission_body(submission_uuid="uu-x")
    ).json()
    assert r2["id"] == r1["id"]
    assert r2.get("duplicate") is True
    subs = live_client.get("/bluebook/submissions").json()["submissions"]
    assert sum(1 for s in subs if s.get("submission_uuid") == "uu-x") == 1


def test_no_session_means_not_late(live_client, store_reset):
    exam = live_client.post("/bluebook/exams", json=_exam_body(duration=30)).json()
    r = live_client.post(
        "/bluebook/submissions",
        json=_submission_body(exam_id=exam["id"], submission_uuid="uu-y"),
    ).json()
    assert r["late"] == 0


def test_late_after_deadline_grace(live_client, store_reset, monkeypatch):
    from datetime import datetime as _real_dt
    from datetime import timedelta

    # The handler lives in original/routers/bluebook.py (WS-7.3 router split)
    # and binds its own `datetime`, so the stand-in must be installed on that
    # module — patching original.api would no longer reach the seal path.
    import original.routers.bluebook as bb_mod

    exam = live_client.post("/bluebook/exams", json=_exam_body(duration=30)).json()
    live_client.post(
        f"/bluebook/exams/{exam['id']}/session",
        json={"student_id": "demo:late", "candidate": ""},
    )

    class _Later:
        """datetime stand-in: now() is 40 minutes in the future (past the
        30-minute exam + 5-minute grace); everything else passes through."""

        @staticmethod
        def now(tz=None):
            return _real_dt.now(tz) + timedelta(minutes=40)

        fromisoformat = _real_dt.fromisoformat

    monkeypatch.setattr(bb_mod, "datetime", _Later)
    r = live_client.post(
        "/bluebook/submissions",
        json=_submission_body(exam_id=exam["id"], student_id="demo:late", submission_uuid="uu-z"),
    ).json()
    assert r["late"] == 1


def test_racing_replay_returns_prior_result_not_500(live_client, store_reset, monkeypatch):
    """Simulate the race the try/except in bluebook_record_submission guards:
    two inserts for the same submission_uuid both reach put_bluebook_submission
    (bypassing the up-front prior-lookup, as a true concurrent race would) —
    the second must hit the unique-index conflict and degrade to the replay
    response, not a 500 (exercises the sqlite3.IntegrityError branch; the
    equivalent sqlalchemy.exc.IntegrityError branch is exercised by the
    Postgres-backed store/repository tests from earlier tasks, not here)."""
    import original.api as api_mod

    body = _submission_body(submission_uuid="uu-race")
    r1 = live_client.post("/bluebook/submissions", json=body)
    assert r1.status_code == 201, r1.text

    # Force the up-front idempotency check to miss once (as a true race
    # would), so the handler falls through to the try/except IntegrityError
    # path and relies on the unique index to catch the duplicate write.
    repo = api_mod._repo()
    real_lookup = repo.get_bluebook_submission_by_uuid
    calls = {"n": 0}

    def _miss_once(uuid_):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return real_lookup(uuid_)

    monkeypatch.setattr(repo, "get_bluebook_submission_by_uuid", _miss_once)

    r2 = live_client.post("/bluebook/submissions", json=body)

    assert r2.status_code == 201, r2.text
    assert r2.json().get("duplicate") is True
    assert r2.json()["id"] == r1.json()["id"]


def test_submission_before_deadline_is_not_late(live_client, store_reset):
    """Sibling of test_late_after_deadline_grace: a sitting with a real
    server-pinned session, sealed well before the deadline (+ grace) elapses,
    must leave late=0 — covers the deadline check's "still on time" arm,
    which the existing late/no-session tests don't reach (no-session skips
    the deadline check entirely; the late test only exercises the "past
    deadline" arm)."""
    exam = live_client.post("/bluebook/exams", json=_exam_body(duration=30)).json()
    live_client.post(
        f"/bluebook/exams/{exam['id']}/session",
        json={"student_id": "demo:ontime", "candidate": ""},
    )
    r = live_client.post(
        "/bluebook/submissions",
        json=_submission_body(
            exam_id=exam["id"], student_id="demo:ontime", submission_uuid="uu-ontime"
        ),
    ).json()
    assert r["late"] == 0


def test_submission_non_conflict_repo_error_propagates(live_client, store_reset, monkeypatch):
    """When put_bluebook_submission raises something other than a
    unique-index conflict (neither sqlite3.IntegrityError nor
    sqlalchemy.exc.IntegrityError), the handler must not misclassify it as a
    replay — it re-raises the original error instead of swallowing it.
    Exercises: the `not is_uuid_conflict` arm that walks into the lazy
    sqlalchemy import (is_uuid_conflict starts False for a non-sqlite3
    exception), and the final `is_uuid_conflict and submission_uuid` check's
    False arm (still False after the sqlalchemy check) that falls through to
    the bare `raise` instead of returning a duplicate response."""
    import original.api as api_mod

    repo = api_mod._repo()

    def _boom(rec):
        raise RuntimeError("simulated non-conflict repo failure")

    monkeypatch.setattr(repo, "put_bluebook_submission", _boom)

    with pytest.raises(RuntimeError, match="simulated non-conflict repo failure"):
        live_client.post("/bluebook/submissions", json=_submission_body())


def test_submission_conflict_but_prior_lookup_miss_propagates(
    live_client, store_reset, monkeypatch
):
    """A genuine unique-index conflict (sqlite3.IntegrityError) whose
    follow-up prior-row lookup then comes back empty (a second, rarer race)
    must not be swallowed either — there is no prior row to hand back, so the
    handler falls through to the bare `raise` rather than returning a
    fabricated duplicate response. Exercises the `if prior is not None`
    False arm."""
    import sqlite3

    import original.api as api_mod

    repo = api_mod._repo()

    def _conflict(rec):
        raise sqlite3.IntegrityError("simulated unique-index conflict")

    monkeypatch.setattr(repo, "put_bluebook_submission", _conflict)
    monkeypatch.setattr(repo, "get_bluebook_submission_by_uuid", lambda uuid_: None)

    with pytest.raises(sqlite3.IntegrityError, match="simulated unique-index conflict"):
        live_client.post(
            "/bluebook/submissions",
            json=_submission_body(submission_uuid="uu-lost-race"),
        )


# ── Baseline replay guard (robustness spec §2, seal step 2) ───────────────────


def test_baseline_seal_replay_adds_exactly_one_sample(live_client, store_reset):
    body = {
        "text": "A reflective essay of sufficient length for feature extraction. " * 30,
        "provenance": "unverified",
        "submission_uuid": "uu-seal-guard-1",
    }
    r1 = live_client.post("/students/demo:replay/baseline", json=body)
    assert r1.status_code == 200, r1.text
    idx1 = r1.json()["sample_index"]
    r2 = live_client.post("/students/demo:replay/baseline", json=body)
    assert r2.status_code == 200, r2.text
    assert r2.json().get("skipped") is True
    assert r2.json()["sample_index"] == idx1  # profile did NOT grow


def test_baseline_without_uuid_keeps_todays_behavior(live_client, store_reset):
    body = {
        "text": "A different reflective essay, long enough for extraction. " * 30,
        "provenance": "unverified",
    }
    r1 = live_client.post("/students/demo:replay2/baseline", json=body)
    r2 = live_client.post("/students/demo:replay2/baseline", json=body)
    assert r2.status_code == 200, r2.text
    assert r2.json().get("skipped") is None
    assert r2.json()["sample_index"] == r1.json()["sample_index"] + 1
