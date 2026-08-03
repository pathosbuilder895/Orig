"""
tests/test_store_bluebook.py — Bluebook persistence layer (T3, WS-5 §5.2).

Sealed-exam evidence — exams, submissions, courses — is written by
original/store.py:1734-1949 (put_bluebook_exam/submission/course +
list_bluebook_*). Before this file, no unit test executed that code path.

Covers:
- put_*/list_*/get_* round-trips for exam, submission, course.
- Upsert semantics: a second put() with the same id replaces, not duplicates.
- Tenant filtering returns only the caller's rows.
- Malformed conditions/JSON payloads are handled, not crashed.
- Injected sqlite3.Error on write surfaces (does not get silently
  swallowed) — the T3/A1 concern that broad `except` blocks hide
  corruption. Shared acceptance proof with WS-1.2's store hardening.
"""

from __future__ import annotations

import sqlite3

import pytest

from original import store


@pytest.fixture(autouse=True)
def _isolated_store(store_reset):
    """Use the shared conftest store_reset fixture (WS-5 §5.1) for every test."""
    yield store_reset


# ── Exams ──────────────────────────────────────────────────────────────────────

def _exam(id_="exam1", tenant_id="acme", **overrides):
    rec = {
        "id": id_,
        "tenant_id": tenant_id,
        "title": "Midterm",
        "course": "THEO 501",
        "duration": 90,
        "minWords": 200,
        "maxWords": 1000,
        "prompt": "Discuss.",
        "conditions": {"lockdown": True},
        "status": "DRAFT",
    }
    rec.update(overrides)
    return rec


def test_put_get_exam_roundtrip():
    store.put_bluebook_exam(_exam())
    got = store.get_bluebook_exam("exam1")
    assert got is not None
    assert got["title"] == "Midterm"
    assert got["tenant_id"] == "acme"
    assert got["conditions"] == {"lockdown": True}
    assert got["status"] == "DRAFT"


def test_get_unknown_exam_returns_none():
    assert store.get_bluebook_exam("nope") is None


def test_put_exam_upsert_replaces_not_duplicates():
    store.put_bluebook_exam(_exam(status="DRAFT"))
    store.put_bluebook_exam(_exam(title="Midterm (revised)", status="PUBLISHED"))
    all_rows = store.list_bluebook_exams(None)
    matching = [r for r in all_rows if r["id"] == "exam1"]
    assert len(matching) == 1
    assert matching[0]["title"] == "Midterm (revised)"
    assert matching[0]["status"] == "PUBLISHED"


def test_list_exams_tenant_filtering():
    store.put_bluebook_exam(_exam(id_="a1", tenant_id="acme"))
    store.put_bluebook_exam(_exam(id_="b1", tenant_id="beta"))
    acme_exams = store.list_bluebook_exams("acme")
    beta_exams = store.list_bluebook_exams("beta")
    assert {r["id"] for r in acme_exams} == {"a1"}
    assert {r["id"] for r in beta_exams} == {"b1"}
    # tenant_id=None (operator/demo view) sees everything.
    assert {r["id"] for r in store.list_bluebook_exams(None)} == {"a1", "b1"}


def test_put_exam_malformed_conditions_handled_not_crashed():
    # conditions must be a dict; a non-dict value is not the caller's contract
    # but must not crash the write — json.dumps({} or ...) falls back to {}.
    rec = _exam(conditions=None)
    store.put_bluebook_exam(rec)
    got = store.get_bluebook_exam("exam1")
    assert got["conditions"] == {}


# ── Submissions ────────────────────────────────────────────────────────────────

def _submission(id_="sub1", tenant_id="acme", exam_id="exam1", **overrides):
    rec = {
        "id": id_,
        "exam_id": exam_id,
        "tenant_id": tenant_id,
        "student_id": "acme:alice",
        "candidate": "Alice",
        "exam_title": "Midterm",
        "course": "THEO 501",
        "word_count": 500,
        "time_min": 45,
        "stylometric": 92,
        "ai_score": 4,
        "status": "SUBMITTED",
    }
    rec.update(overrides)
    return rec


def test_put_list_submission_roundtrip():
    store.put_bluebook_submission(_submission())
    subs = store.list_bluebook_submissions("acme")
    assert len(subs) == 1
    assert subs[0]["id"] == "sub1"
    assert subs[0]["exam_id"] == "exam1"
    assert subs[0]["student"] == "Alice"


def test_list_submissions_tenant_filtering():
    store.put_bluebook_submission(_submission(id_="s1", tenant_id="acme"))
    store.put_bluebook_submission(_submission(id_="s2", tenant_id="beta"))
    assert {r["id"] for r in store.list_bluebook_submissions("acme")} == {"s1"}
    assert {r["id"] for r in store.list_bluebook_submissions("beta")} == {"s2"}
    assert {r["id"] for r in store.list_bluebook_submissions(None)} == {"s1", "s2"}


# ── Courses ────────────────────────────────────────────────────────────────────

def _course(id_="course1", tenant_id="acme", **overrides):
    rec = {
        "id": id_,
        "tenant_id": tenant_id,
        "code": "THEO 501",
        "name": "Advanced Theology",
        "term": "Spring 2026",
        "status": "ACTIVE",
    }
    rec.update(overrides)
    return rec


def test_put_get_course_roundtrip():
    store.put_bluebook_course(_course())
    courses = store.list_bluebook_courses("acme")
    assert len(courses) == 1
    assert courses[0]["name"] == "Advanced Theology"
    assert courses[0]["active"] is True


def test_put_course_upsert_replaces_not_duplicates():
    store.put_bluebook_course(_course(status="ACTIVE"))
    store.put_bluebook_course(_course(name="Advanced Theology II", status="ARCHIVED"))
    courses = store.list_bluebook_courses("acme")
    assert len(courses) == 1
    assert courses[0]["name"] == "Advanced Theology II"
    assert courses[0]["active"] is False


def test_list_courses_tenant_filtering():
    store.put_bluebook_course(_course(id_="c1", tenant_id="acme"))
    store.put_bluebook_course(_course(id_="c2", tenant_id="beta"))
    assert {r["id"] for r in store.list_bluebook_courses("acme")} == {"c1"}
    assert {r["id"] for r in store.list_bluebook_courses(None)} == {"c1", "c2"}


# ── Injected-error test (T3/A1 shared acceptance proof) ───────────────────────

def test_put_bluebook_exam_surfaces_sqlite_error(monkeypatch):
    class _BoomConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **kw):
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "_get_conn", lambda: _BoomConn())
    with pytest.raises(sqlite3.Error):
        store.put_bluebook_exam(_exam())


def test_put_bluebook_submission_surfaces_sqlite_error(monkeypatch):
    class _BoomConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **kw):
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "_get_conn", lambda: _BoomConn())
    with pytest.raises(sqlite3.Error):
        store.put_bluebook_submission(_submission())


def test_put_bluebook_course_surfaces_sqlite_error(monkeypatch):
    class _BoomConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **kw):
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "_get_conn", lambda: _BoomConn())
    with pytest.raises(sqlite3.Error):
        store.put_bluebook_course(_course())


# ── Sessions (exam-day robustness spec §1) ─────────────────────────────────────

class TestBluebookSessions:
    def test_first_call_creates_session(self):
        from datetime import datetime

        s = store.get_or_create_bluebook_session("ex1", "sem:alice", "sem", 3600)
        assert s["created"] is True
        assert s["exam_id"] == "ex1" and s["tenant_id"] == "sem"
        started = datetime.fromisoformat(s["started_at"])
        deadline = datetime.fromisoformat(s["deadline_at"])
        assert (deadline - started).total_seconds() == 3600

    def test_second_call_returns_same_deadline(self):
        first = store.get_or_create_bluebook_session("ex1", "sem:alice", "sem", 3600)
        again = store.get_or_create_bluebook_session("ex1", "sem:alice", "sem", 3600)
        assert again["created"] is False
        assert again["deadline_at"] == first["deadline_at"]
        assert again["started_at"] == first["started_at"]

    def test_sessions_are_per_student_and_exam(self):
        a = store.get_or_create_bluebook_session("ex1", "sem:alice", "sem", 3600)
        b = store.get_or_create_bluebook_session("ex1", "sem:bob", "sem", 3600)
        c = store.get_or_create_bluebook_session("ex2", "sem:alice", "sem", 3600)
        assert a["created"] and b["created"] and c["created"]

    def test_read_only_lookup(self):
        assert store.get_bluebook_session("ex1", "sem:alice") is None
        created = store.get_or_create_bluebook_session("ex1", "sem:alice", "sem", 60)
        got = store.get_bluebook_session("ex1", "sem:alice")
        assert got is not None and got["deadline_at"] == created["deadline_at"]


# ── submission_uuid / late (exam-day robustness spec §2) ───────────────────────

class TestSubmissionUuid:
    def _rec(self, uuid_val):
        return {
            "id": "sub-" + uuid_val, "exam_id": "ex1", "tenant_id": "sem",
            "student_id": "sem:alice", "candidate": "Alice", "exam_title": "T",
            "course": "C", "word_count": 10, "time_min": 5, "stylometric": 90,
            "ai_score": None, "status": "SUBMITTED",
            "submission_uuid": uuid_val, "late": 0,
        }

    def test_uuid_roundtrip(self):
        store.put_bluebook_submission(self._rec("u-1"))
        got = store.get_bluebook_submission_by_uuid("u-1")
        assert got is not None and got["id"] == "sub-u-1"
        assert got["late"] == 0

    def test_unknown_uuid_returns_none(self):
        assert store.get_bluebook_submission_by_uuid("nope") is None

    def test_duplicate_uuid_insert_raises(self):
        store.put_bluebook_submission(self._rec("u-2"))
        dup = self._rec("u-2")
        dup["id"] = "other"
        with pytest.raises(sqlite3.Error):
            store.put_bluebook_submission(dup)
