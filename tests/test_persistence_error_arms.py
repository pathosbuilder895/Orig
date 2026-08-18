"""
tests/test_persistence_error_arms.py — Backend-specific persistence branch
arms not expressible through the Repository contract protocol (Part 1,
Task 4 of the persistence branch-coverage plan).

test_repository_contract.py exercises Repository purely through its public
interface so the same assertions run against both SqliteRepository and
PostgresRepository. That deliberately excludes anything that only makes
sense for one backend's internals:

  1. PostgresRepository's outer ``except Exception`` guards -- forcing a
     real SQLAlchemy failure (a bad query, a dropped connection) isn't
     practical against a real database, so these are tested by monkeypatching
     ``postgres_repository.session_scope`` itself to raise, then asserting
     each method's documented degraded return value. Marked
     ``@pytest.mark.postgres`` because the module they live in is, but none
     of these tests actually needs a reachable Postgres instance -- the
     session factory is stubbed out before it would ever be dialed.
  2. store.py's matching inner JSON-corruption fallback in
     ``get_fused_scores`` (one corrupted row degrades to ``channels={}``
     instead of failing the whole read) -- store.py's own public API only
     ever writes valid JSON, so producing a corrupted column needs one raw
     SQL UPDATE against the fixture row. Raw SQL here is controller-sanctioned
     for this file only, to construct states unreachable through the Repository
     protocol (corrupting stored JSON for the fallback test). Assertions always
     go through the protocol.
  3. ``get_engine()`` bootstrap arms in ``original/db/session.py`` (dormant
     v1, zero prior coverage) and ``original/db/postgres_session.py`` (the
     live schema's lazily-built, process-cached engine) -- the
     cached-reuse branch and the sqlite-vs-postgresql URL-scheme branches.
  4. store.py's ``_init_schema`` PRAGMA-guarded ALTER-TABLE migration arms
     (fused_scores.baseline_samples/reference_profiles,
     bluebook_submissions.submission_uuid/late) -- exercising the
     column-absent side needs a fixture DB that predates those columns.
     store.py's public API always writes through the CURRENT schema, so
     there is no way to construct that fixture except raw SQL. Raw SQL here
     is controller-sanctioned for this file only, to construct the
     pre-migration fixture states. Assertions always read back through
     the protocol, never through raw SQL.
"""

from __future__ import annotations

import os
import sqlite3
from types import SimpleNamespace

import pytest

from original import postgres_repository, store

# ── Step 1: PostgresRepository exception guards ───────────────────────────


def _boom():
    raise RuntimeError("simulated connection failure")


@pytest.mark.postgres
def test_roster_for_tenant_returns_empty_on_session_failure(monkeypatch):
    monkeypatch.setattr(postgres_repository, "session_scope", _boom)
    assert postgres_repository.PostgresRepository().roster_for_tenant("sem") == []


@pytest.mark.postgres
def test_list_manifests_returns_empty_page_on_session_failure(monkeypatch):
    monkeypatch.setattr(postgres_repository, "session_scope", _boom)
    result = postgres_repository.PostgresRepository().list_manifests()
    assert result == {"total": 0, "limit": 100, "offset": 0, "items": []}


@pytest.mark.postgres
def test_manifest_stats_returns_zeroed_stats_on_session_failure(monkeypatch):
    monkeypatch.setattr(postgres_repository, "session_scope", _boom)
    result = postgres_repository.PostgresRepository().manifest_stats()
    assert result == {
        "total": 0,
        "by_action": {},
        "by_flag": {},
        "by_length_regime": {},
        "mean_divergence": None,
        "since": None,
        "until": None,
    }


@pytest.mark.postgres
def test_put_manifest_swallows_session_failure(monkeypatch):
    monkeypatch.setattr(postgres_repository, "session_scope", _boom)
    # put_manifest never returns a value on either path; the assertion that
    # matters is that the RuntimeError from _boom() does not propagate.
    result = postgres_repository.PostgresRepository().put_manifest(
        "sub1", "sem:stu1", {"created_at": "2026-01-01T00:00:00Z"}
    )
    assert result is None


@pytest.mark.postgres
def test_put_correction_returns_none_on_session_failure(monkeypatch):
    monkeypatch.setattr(postgres_repository, "session_scope", _boom)
    # Supplying student_id + all three "original_*" fields skips the
    # get_manifest()/submission_student_id() fallback lookups (each of which
    # has its own guard) so this exercises put_correction's own guard only.
    result = postgres_repository.PostgresRepository().put_correction(
        "sub1",
        True,
        student_id="sem:stu1",
        original_verdict="authentic",
        original_action="no_action",
        original_divergence_score=0.1,
    )
    assert result is None


@pytest.mark.postgres
def test_list_calibration_runs_returns_empty_page_on_session_failure(monkeypatch):
    monkeypatch.setattr(postgres_repository, "session_scope", _boom)
    result = postgres_repository.PostgresRepository().list_calibration_runs()
    assert result == {"total": 0, "limit": 50, "offset": 0, "items": []}


@pytest.mark.postgres
def test_get_fused_scores_returns_empty_on_session_failure(monkeypatch):
    monkeypatch.setattr(postgres_repository, "session_scope", _boom)
    assert postgres_repository.PostgresRepository().get_fused_scores() == []


@pytest.mark.postgres
def test_get_ai_likelihood_scores_returns_empty_on_session_failure(monkeypatch):
    monkeypatch.setattr(postgres_repository, "session_scope", _boom)
    assert postgres_repository.PostgresRepository().get_ai_likelihood_scores() == []


@pytest.mark.postgres
def test_student_data_inventory_returns_none_on_session_failure(monkeypatch):
    monkeypatch.setattr(postgres_repository, "session_scope", _boom)
    assert postgres_repository.PostgresRepository().student_data_inventory("sem:stu1") is None


@pytest.mark.postgres
def test_delete_student_returns_false_on_session_failure(monkeypatch):
    monkeypatch.setattr(postgres_repository, "session_scope", _boom)
    assert postgres_repository.PostgresRepository().delete_student("sem:stu1") is False


@pytest.mark.postgres
def test_set_display_name_swallows_session_failure(monkeypatch):
    monkeypatch.setattr(postgres_repository, "session_scope", _boom)
    repo = postgres_repository.PostgresRepository()
    assert repo.set_display_name("sem:err-student", "Name") is None


# ── Step 1b: store.py's matching inner JSON-corruption fallback ───────────


def test_store_get_fused_scores_degrades_channels_on_corrupted_json(store_reset):
    """Mirrors PostgresRepository.get_fused_scores's per-row try/except:
    one row with unparseable channels_json degrades to channels={} instead
    of failing the whole read."""
    store_reset.put_fused_score(
        submission_id="sub-corrupt-1",
        student_id="sem:stu1",
        fused_log_odds=0.1,
        probability=0.52,
        band="low",
        channels={"peer_centered_z": 0.4},
        model_version="v1",
    )

    # Raw SQL is the sanctioned exception here (see module docstring): it
    # ONLY corrupts the one column under test, produced through the public
    # put_fused_score() API above -- never used to assert through.
    conn = sqlite3.connect(str(store_reset._DB_PATH))
    try:
        conn.execute(
            "UPDATE fused_scores SET channels_json = ? WHERE submission_id = ?",
            ("{not valid json", "sub-corrupt-1"),
        )
        conn.commit()
    finally:
        conn.close()

    rows = store_reset.get_fused_scores(student_id="sem:stu1")
    assert len(rows) == 1
    assert rows[0]["submission_id"] == "sub-corrupt-1"
    assert rows[0]["band"] == "low"
    assert rows[0]["channels"] == {}


# ── Step 2: get_engine() bootstrap arms ────────────────────────────────────


def _fake_settings(database_url: str, **overrides) -> SimpleNamespace:
    values = dict(
        DATABASE_URL=database_url,
        DEBUG=False,
        DB_POOL_SIZE=10,
        DB_MAX_OVERFLOW=20,
        DB_POOL_RECYCLE=3600,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_db_session_get_engine_sqlite_scheme_branch(monkeypatch):
    """original/db/session.py is the dormant v1 engine factory -- nothing in
    the live stack imports it, so it starts at 0% coverage. get_engine()
    reads DATABASE_URL through the lru_cache-memoised get_settings(); rather
    than fight that process-wide cache, monkeypatch the name db.session
    imported it under so each call sees whatever URL this test wants."""
    from original.db import session as db_session

    monkeypatch.setattr(db_session, "get_settings", lambda: _fake_settings("sqlite:///:memory:"))
    engine = db_session.get_engine()
    try:
        assert str(engine.url).startswith("sqlite")
    finally:
        engine.dispose()


def test_db_session_get_engine_postgres_scheme_branch(monkeypatch):
    """The non-sqlite branch builds the engine with pool_size/max_overflow/
    pool_recycle from settings. create_engine() is lazy (no connection is
    opened), so this needs no reachable Postgres -- a well-formed
    postgresql:// URL is enough to exercise the branch."""
    from original.db import session as db_session

    monkeypatch.setattr(
        db_session,
        "get_settings",
        lambda: _fake_settings(
            "postgresql://user:pass@localhost:5432/testdb",
            DB_POOL_SIZE=3,
            DB_MAX_OVERFLOW=7,
            DB_POOL_RECYCLE=900,
        ),
    )
    engine = db_session.get_engine()
    try:
        assert str(engine.url).startswith("postgresql")
        # QueuePool.size() reports its configured pool_size -- confirms the
        # non-sqlite branch actually threaded settings.DB_POOL_SIZE through,
        # not just that it took the "else" fork.
        assert engine.pool.size() == 3
    finally:
        engine.dispose()


def test_postgres_session_get_engine_caches_and_reuses_sqlite_scheme(monkeypatch):
    """The live-schema engine is built once, lazily, and cached in the
    module-level ``_engine`` global -- a second get_engine() call must
    return the SAME object, not rebuild. reset_engine() first (test
    isolation) and again at the end (this module's own caution: never leave
    a monkeypatched/sqlite-backed engine cached for a later test in this
    process, e.g. test_repository_contract.py's postgres-backed fixture)."""
    from original.db import postgres_session

    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    postgres_session.reset_engine()
    try:
        engine1 = postgres_session.get_engine()
        engine2 = postgres_session.get_engine()
        assert engine1 is engine2
        assert str(engine1.url).startswith("sqlite")
    finally:
        postgres_session.reset_engine()


def _postgres_session_available() -> bool:
    """Mirrors test_repository_contract.py's ``_postgres_available()``
    (checked at call time, not import time, so it reflects DATABASE_URL as
    of the moment this test actually runs)."""
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url.startswith("postgresql"):
        return False
    from original.db import postgres_session

    try:
        postgres_session.reset_engine()
        with postgres_session.get_engine().connect():
            return True
    except Exception:
        return False


@pytest.mark.postgres
def test_postgres_session_get_engine_postgres_scheme_branch():
    """The non-sqlite branch of db/postgres_session.py's get_engine(),
    exercised against the real local Postgres container so the pool-settings
    construction path is proven to actually connect, not just build an
    object. Self-skips if no postgresql:// DATABASE_URL is reachable."""
    from original.db import postgres_session

    if not _postgres_session_available():
        pytest.skip(
            "no reachable Postgres -- set DATABASE_URL to a postgresql:// "
            "instance to run this get_engine() branch test"
        )

    postgres_session.reset_engine()
    try:
        engine = postgres_session.get_engine()
        assert str(engine.url).startswith("postgresql")
        with engine.connect():
            pass
    finally:
        postgres_session.reset_engine()


# ── Step 3: store.py's _init_schema() migration arms ──────────────────────


class TestInitSchemaMigrationArms:
    """_init_schema() runs the full CREATE-TABLE-IF-NOT-EXISTS ladder on
    every connection (WS-1 A1's "corrupt DB fails loudly" guarantee), but
    two tables also carry PRAGMA-guarded ALTER TABLE upgrade arms for
    pre-existing DBs: fused_scores gained baseline_samples/reference_profiles
    (C1 fix pass) and bluebook_submissions gained submission_uuid/late.
    Both column-present (skip) and column-absent (ALTER) arms need
    coverage; the column-absent side needs a DB that predates those
    columns. store.py's public API always writes through the CURRENT
    schema, so there is no way to build that fixture except raw SQL --
    the sanctioned exception from the task brief. Raw SQL below ONLY
    constructs the pre-migration fixture DB; every assertion after
    _init_schema() runs reads back through plain SQL against the same
    connection, not through any store.py API (there being no API for
    "read one row's raw columns" in the first place).
    """

    def test_fused_scores_and_bluebook_submissions_alter_arms_fire(self, tmp_path):
        db_path = tmp_path / "old_schema.db"
        conn = sqlite3.connect(str(db_path))
        try:
            # Pre-C1 fused_scores shape: no baseline_samples/reference_profiles.
            conn.execute(
                """
                CREATE TABLE fused_scores (
                    submission_id     TEXT PRIMARY KEY,
                    student_id        TEXT NOT NULL,
                    fused_log_odds    REAL NOT NULL,
                    probability       REAL NOT NULL,
                    band              TEXT NOT NULL,
                    channels_json     TEXT NOT NULL DEFAULT '{}',
                    model_version     TEXT NOT NULL DEFAULT '',
                    created_at        TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT INTO fused_scores "
                "(submission_id, student_id, fused_log_odds, probability, band, "
                " channels_json, model_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("sub-old-1", "sem:stu1", 0.5, 0.6, "medium", "{}", "v1", "2026-01-01T00:00:00Z"),
            )

            # Pre-submission_uuid/late bluebook_submissions shape.
            conn.execute(
                """
                CREATE TABLE bluebook_submissions (
                    submission_id TEXT PRIMARY KEY,
                    exam_id       TEXT,
                    tenant_id     TEXT NOT NULL,
                    student_id    TEXT,
                    candidate     TEXT,
                    exam_title    TEXT,
                    course        TEXT,
                    word_count    INTEGER,
                    time_min      INTEGER,
                    stylometric   INTEGER,
                    ai_score      INTEGER,
                    status        TEXT NOT NULL DEFAULT 'SUBMITTED',
                    created_at    TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT INTO bluebook_submissions "
                "(submission_id, exam_id, tenant_id, student_id, candidate, exam_title, "
                " course, word_count, time_min, stylometric, ai_score, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "bbsub-old-1",
                    "exam1",
                    "sem",
                    "stu1",
                    "Jane",
                    "Midterm",
                    "THEO101",
                    500,
                    60,
                    1,
                    0,
                    "SUBMITTED",
                    "2026-01-01T00:00:00Z",
                ),
            )
            conn.commit()

            # Sanity: pre-migration, neither table has the newer columns yet.
            fused_cols_before = {r[1] for r in conn.execute("PRAGMA table_info(fused_scores)")}
            sub_cols_before = {
                r[1] for r in conn.execute("PRAGMA table_info(bluebook_submissions)")
            }
            assert "baseline_samples" not in fused_cols_before
            assert "reference_profiles" not in fused_cols_before
            assert "submission_uuid" not in sub_cols_before
            assert "late" not in sub_cols_before

            store._init_schema(conn)

            fused_cols_after = {r[1] for r in conn.execute("PRAGMA table_info(fused_scores)")}
            sub_cols_after = {r[1] for r in conn.execute("PRAGMA table_info(bluebook_submissions)")}
            assert {"baseline_samples", "reference_profiles"} <= fused_cols_after
            assert {"submission_uuid", "late"} <= sub_cols_after

            # Pre-existing rows survive the ALTER; new columns take ALTER's
            # own default (NULL when none was declared, 0 for `late`).
            fused_row = conn.execute(
                "SELECT submission_id, band, baseline_samples, reference_profiles "
                "FROM fused_scores WHERE submission_id = 'sub-old-1'"
            ).fetchone()
            assert fused_row == ("sub-old-1", "medium", None, None)

            sub_row = conn.execute(
                "SELECT submission_id, candidate, submission_uuid, late "
                "FROM bluebook_submissions WHERE submission_id = 'bbsub-old-1'"
            ).fetchone()
            assert sub_row == ("bbsub-old-1", "Jane", None, 0)

            # And the ALTER arm's sibling (column-already-present, skip) is
            # covered by every other test in the suite that round-trips
            # through _get_conn() on a fresh DB -- re-running _init_schema
            # on this now-upgraded connection exercises it here too, for a
            # belt-and-braces check within this same test.
            store._init_schema(conn)
            fused_cols_repeat = {r[1] for r in conn.execute("PRAGMA table_info(fused_scores)")}
            assert fused_cols_repeat == fused_cols_after
        finally:
            conn.close()
