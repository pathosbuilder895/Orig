"""A failed database write must not copy student writing into the app logs.

SQLAlchemy formats every DBAPI exception with its bound parameters
(``[parameters: (...)]``), and ``PostgresRepository`` logs the exceptions it
re-raises. With the default engine settings, one failed write of a Bluebook
submission put the opening and closing ~150 characters of the essay, and of
its answers, into the pilot's logs (2026-10-09 disk-write audit). Every
live-schema engine is now built with ``hide_parameters=True``.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import StatementError

from original.db import postgres_session
from original.db.models.live import BluebookSubmission, Tenant
from original.postgres_repository import PostgresRepository

SENTINEL = "SENTINEL-ESSAY"
ESSAY = f"{SENTINEL} my grandmother taught me to bake bread on Sundays. " * 12


def _submission() -> dict:
    return {
        "id": uuid.uuid4().hex[:16],
        "exam_id": None,
        "tenant_id": "audit-" + uuid.uuid4().hex[:8],
        "text": ESSAY,
        "answers": [ESSAY],
        "warnings": [],
        "student_id": "",
        "candidate": "",
        "exam_title": "Audit",
        "course": "",
        "word_count": 1,
        "time_min": 1,
        "stylometric": None,
        "ai_score": None,
        "status": "SUBMITTED",
        "late": 0,
        "submission_uuid": None,
    }


def _fail_a_submission_write(rec: dict, caplog) -> StatementError:
    """Write one submission twice: the second write fails on its primary key
    and the repository logs the failure."""
    repo = PostgresRepository()
    repo.put_bluebook_submission(rec)
    caplog.set_level(logging.ERROR, logger="original.postgres_repository")
    with pytest.raises(StatementError) as excinfo:
        repo.put_bluebook_submission(dict(rec))
    return excinfo.value


def _assert_no_student_text(exc: StatementError, caplog) -> None:
    assert "parameters hidden" in str(exc)
    assert SENTINEL not in str(exc)
    logged = [r for r in caplog.records if r.name == "original.postgres_repository"]
    assert logged, "the repository should log the failed write"
    assert SENTINEL not in caplog.text


@pytest.fixture
def sqlite_live_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'live.db'}")
    postgres_session.reset_engine()
    postgres_session.init_db()
    yield
    postgres_session.reset_engine()


def test_failed_submission_write_logs_no_student_text(sqlite_live_schema, caplog):
    exc = _fail_a_submission_write(_submission(), caplog)
    _assert_no_student_text(exc, caplog)


def test_postgres_engine_hides_parameters(monkeypatch):
    """The production branch, checked without a server: create_engine does
    not connect until first use."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@127.0.0.1:1/none")
    postgres_session.reset_engine()
    try:
        assert postgres_session.get_engine().hide_parameters is True
    finally:
        postgres_session.reset_engine()


@pytest.mark.postgres
def test_failed_submission_write_logs_no_student_text_on_postgres(postgres_schema, caplog):
    rec = _submission()
    try:
        exc = _fail_a_submission_write(rec, caplog)
    finally:
        # The first write landed (with the placeholder tenant row the
        # repository seeds); leave the shared schema as it was.
        with postgres_schema.begin() as conn:
            sub = BluebookSubmission
            conn.execute(delete(sub).where(sub.submission_id == rec["id"]))
            conn.execute(delete(Tenant).where(Tenant.tenant_id == rec["tenant_id"]))
    _assert_no_student_text(exc, caplog)
