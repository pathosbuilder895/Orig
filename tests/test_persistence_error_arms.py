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
     there is no way to construct that fixture except raw SQL. Raw SQL
     here never writes/corrupts anything a test then asserts was already
     there -- it only constructs fixture state (or, for
     TestInitSchemaMigrationArms, reads back a pre-migration column list
     that has no protocol-level surface at all; see that class's own
     docstring for why those particular reads are raw SQL by necessity).

Part 1/Task 5 (persistence branch-coverage sweep) added a second wave below
the original four items, same idioms: the remaining single-session-call
PostgresRepository/store.py exception guards (a big parametrized table per
backend, monkeypatching ``session_scope``/``_get_conn`` respectively),
guards that re-raise instead of swallowing, two-stage "boom after the Nth
call" guards for methods that make more than one session/connection call
(``advance_formation_pathway``, store's ``delete_student``), inner
per-row JSON-corruption fallbacks that are SQLite/Text-column-specific
(``list_manifests``/``manifest_stats``/``load_baseline_requests``/
``park_beat``/``park_tiles`` in store.py; ``get_fused_scores`` in
PostgresRepository -- ``channels_json`` is a plain Text column there,
deliberately, so corruption is representable the same way), and the
legacy-short-vector dimension-padding arm shared by both backends'
deserializers. A cross-backend divergence surfaced while writing the
GENRE_UNKNOWN contract test (test_repository_contract.py) -- see
``postgres_repository.PostgresRepository.get_genre_stats``'s updated
docstring and its own commit for the fix.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from original import postgres_repository, store
from original.constants import FEATURE_DIM
from original.quantum.state import StudentState

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
    of the moment this test actually runs).

    Also ensures the live schema exists via ``LiveBase.metadata.create_all``
    (checkfirst=True by default, so this is a cheap no-op when the schema is
    already present). Without this, a test file that ran earlier in the same
    session and dropped the schema in its own teardown (test_cutover.py,
    test_migration.py both do) leaves Postgres reachable but tableless, and
    the tests below would fail with UndefinedTable instead of exercising the
    guard behaviour they're testing -- reachability alone isn't the same
    contract as "safe to run in any sandbox."."""
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url.startswith("postgresql"):
        return False
    from original.db import postgres_session
    from original.db.models.live import LiveBase

    try:
        postgres_session.reset_engine()
        engine = postgres_session.get_engine()
        with engine.connect():
            pass
        LiveBase.metadata.create_all(bind=engine)
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


# ── Step 4: Remaining PostgresRepository exception guards (single
# session_scope call) ──────────────────────────────────────────────────────
#
# Same idiom as Step 1 -- monkeypatch session_scope to raise, assert the
# documented degraded return value -- for every guard Step 1 (Task 4) didn't
# reach. One parametrized table rather than ~40 near-identical functions.

_PG_SINGLE_CALL_GUARDS = [
    ("list_ids", (), {}, []),
    ("all_states", (), {}, []),
    ("count", (), {}, 0),
    ("list_ids_for_tenant", ("sem",), {}, []),
    ("get_display_name", ("sem:pg-guard-1",), {}, ""),
    ("get_manifest", ("sub-pg-guard",), {}, None),
    ("submission_student_id", ("sub-pg-guard",), {}, None),
    ("put_fidelity_score", ("sub-pg-guard", "sem:pg-guard-1", 0.5, True), {}, None),
    ("get_authentic_fidelities", ("sem:pg-guard-1",), {}, []),
    ("update_fidelity_authenticity", ("sub-pg-guard", True), {}, None),
    ("put_ai_likelihood_score", ("sub-pg-guard", "sem:pg-guard-1", 0.5, "low"), {}, None),
    ("put_fused_score", ("sub-pg-guard", "sem:pg-guard-1", 0.1, 0.5, "low", {}), {}, None),
    ("list_corrections", (), {}, {"total": 0, "limit": 100, "offset": 0, "items": []}),
    ("start_calibration_run", ("dataset-pg-guard",), {}, None),
    (
        "complete_calibration_run",
        (1,),
        {"auc": 0.5, "n_essays_scored": 1, "n_authors": 1, "report": {}},
        False,
    ),
    ("fail_calibration_run", (1, "boom"), {}, False),
    ("get_calibration_run", (1,), {}, None),
    (
        "put_tuned_thresholds",
        (),
        {"no_action": 0.1, "monitor": 0.2, "escalate": 0.3, "source": "manual"},
        None,
    ),
    ("get_active_tuned_thresholds", (), {}, None),
    ("list_tuned_thresholds", (), {}, {"total": 0, "limit": 50, "offset": 0, "items": []}),
    ("get_tenant", ("sem",), {}, None),
    ("list_tenants", (), {}, []),
    ("put_tenant", ("sem", "Seminary"), {}, None),
    (
        "tenant_stats",
        ("sem",),
        {},
        {
            "tenant_id": "sem",
            "student_count": 0,
            "sample_count": 0,
            "submission_count": 0,
            "last_active_at": None,
            "action_counts": {},
        },
    ),
    ("put_user", ("u-pg-guard", "pg-guard@example.com", "hash", "admin", "sem"), {}, None),
    ("get_user_by_email", ("pg-guard@example.com",), {}, None),
    ("get_bluebook_exam", ("exam-pg-guard",), {}, None),
    ("list_bluebook_exams", ("sem",), {}, []),
    ("list_bluebook_submissions", ("sem",), {}, []),
    ("get_bluebook_submission_by_uuid", ("uuid-pg-guard",), {}, None),
    ("get_bluebook_session", ("exam-pg-guard", "key-pg-guard"), {}, None),
    ("list_bluebook_courses", ("sem",), {}, []),
    ("log_audit", ("action-pg-guard",), {}, None),
    ("list_audit", (), {}, {"total": 0, "limit": 100, "offset": 0, "items": []}),
    ("get_formation_pathway", ("sem:pg-guard-1",), {}, None),
    ("open_formation_pathway", ("sem:pg-guard-1",), {}, None),
    (
        "put_baseline_request",
        ("req-pg-guard", "sem:pg-guard-1", "pending", 100.0, "{}"),
        {},
        None,
    ),
    ("load_baseline_requests", (), {}, []),
    # get_genre_stats/get_cohort_stats have no guard of their own -- the
    # exception is caught one level down, inside the private _pool_groups()
    # helper they both share, which returns [] on failure (deliberately
    # uncached; see its own comment) so genre_stats_from_groups([], ...)
    # falls back to None the same way an underpopulated pool would.
    ("get_genre_stats", ("lab_report", "sem", None), {}, None),
    ("get_cohort_stats", ("sem", None), {}, None),
]


@pytest.mark.postgres
@pytest.mark.parametrize("method_name, args, kwargs, expected", _PG_SINGLE_CALL_GUARDS)
def test_pg_repository_guard_swallows_session_failure(
    monkeypatch, method_name, args, kwargs, expected
):
    monkeypatch.setattr(postgres_repository, "session_scope", _boom)
    repo = postgres_repository.PostgresRepository()
    result = getattr(repo, method_name)(*args, **kwargs)
    assert result == expected


# ── Step 5: PostgresRepository guards that re-raise instead of swallowing ──
#
# A handful of writers log-and-``raise`` rather than returning a degraded
# value -- matching store.py's sqlite3.Error writers (Step 8 below), which
# also surface write failures instead of silently dropping them.
#
# get()/get_or_create() belong here too (final-review fix): a session
# failure is a real infrastructure error, not "this student doesn't exist
# yet" -- the not-found case is already represented without an exception
# (session.get() returns None for a missing row; see the `row is not None`
# branch in get_or_create()), so there is no legitimate "not found"
# exception to swallow here. Before the fix, get() returned None and
# get_or_create() fabricated an empty StudentState on ANY exception
# (connection drop, pool exhaustion, ...), indistinguishable from a
# genuinely new/missing student -- masking real outages as normal states.
_PG_RERAISING_GUARDS = [
    ("get", ("sem:pg-guard-1",), {}),
    ("get_or_create", ("sem:pg-goc-guard",), {}),
    ("put", (StudentState(student_id="sem:pg-put-guard"),), {}),
    ("put_bluebook_exam", ({"id": "exam-pg-raise", "tenant_id": "sem", "title": "T"},), {}),
    ("put_bluebook_submission", ({"id": "sub-pg-raise", "tenant_id": "sem"},), {}),
    (
        "get_or_create_bluebook_session",
        ("exam-pg-raise", "key-pg-raise", "sem", 1800),
        {},
    ),
    ("put_bluebook_course", ({"id": "course-pg-raise", "tenant_id": "sem", "name": "N"},), {}),
]


@pytest.mark.postgres
@pytest.mark.parametrize("method_name, args, kwargs", _PG_RERAISING_GUARDS)
def test_pg_repository_guard_reraises_on_session_failure(monkeypatch, method_name, args, kwargs):
    monkeypatch.setattr(postgres_repository, "session_scope", _boom)
    repo = postgres_repository.PostgresRepository()
    with pytest.raises(RuntimeError, match="simulated connection failure"):
        getattr(repo, method_name)(*args, **kwargs)


# ── Step 6: PostgresRepository two-stage guards ────────────────────────────
#
# advance_formation_pathway calls get_formation_pathway (1 session_scope
# call) BEFORE its own try/except (a 2nd call) to decide whether there's
# even an open pathway to advance. A single global session_scope boom makes
# that FIRST call fail too, so get_formation_pathway's own guard returns
# None, and advance_formation_pathway short-circuits on its "no open
# pathway" branch -- never reaching its own except block at all. Real
# Postgres sets up a genuinely open pathway first (session_scope call #1,
# unpatched); only the SECOND call (this method's own UPDATE) is made to
# fail, isolating the branch under test.


@pytest.mark.postgres
def test_advance_formation_pathway_returns_none_on_second_session_failure(monkeypatch):
    # Unlike every test in Step 4/5 above (which fully replace session_scope
    # with _boom and never dial out), the first call here is real -- so this
    # one actually needs a reachable Postgres to self-skip against, matching
    # the file's documented "safe to run in any sandbox" contract.
    if not _postgres_session_available():
        pytest.skip(
            "no reachable Postgres -- set DATABASE_URL to a postgresql:// "
            "instance to run this two-stage guard test"
        )
    repo = postgres_repository.PostgresRepository()
    student_id = "sem:pg-advance-guard"
    opened = repo.open_formation_pathway(student_id)
    assert opened["status"] == "open"

    real_session_scope = postgres_repository.session_scope
    calls = {"n": 0}

    def _boom_after_first_call():
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("simulated connection failure")
        return real_session_scope()

    monkeypatch.setattr(postgres_repository, "session_scope", _boom_after_first_call)
    assert repo.advance_formation_pathway(student_id) is None


# ── Step 7: PostgresRepository partial branches ────────────────────────────


@pytest.mark.postgres
def test_parse_iso_or_now_falsy_input_returns_now():
    """_parse_iso_or_now(None) skips the parse attempt entirely -- a pure
    function, no session/DB involved."""
    before = datetime.now(UTC)
    result = postgres_repository.PostgresRepository._parse_iso_or_now(None)
    after = datetime.now(UTC)
    assert before <= result <= after


@pytest.mark.postgres
def test_parse_iso_or_now_malformed_string_falls_back_to_now():
    """A string that fails datetime.fromisoformat() hits the except
    ValueError: pass arm, then falls through to the same "now" default."""
    before = datetime.now(UTC)
    result = postgres_repository.PostgresRepository._parse_iso_or_now("not-a-valid-iso-date")
    after = datetime.now(UTC)
    assert before <= result <= after


@pytest.mark.postgres
def test_doc_to_state_pads_legacy_short_vector():
    """Mirrors test_store_deserialize_pads_legacy_short_vector (Step 10)
    for the Postgres side. PostgresRepository has no public write path that
    produces a short vector -- every real caller constructs a StudentState
    from the current FEATURE_DIM-wide feature pipeline -- so the fixture
    doc is written directly through session_scope/the ORM: the sanctioned
    exception for constructing states unreachable through the protocol.
    The assertion reads back through repo.get(), the public API."""
    if not _postgres_session_available():
        pytest.skip(
            "no reachable Postgres -- set DATABASE_URL to a postgresql:// "
            "instance to run this legacy-dimension-padding test"
        )
    from original.db.models.live import StudentProfile
    from original.db.postgres_session import session_scope

    tenant_id, local_id = "sem", "pg-legacy-dim-student"
    student_id = f"{tenant_id}:{local_id}"
    short_vector = [0.25] * 74  # pre-Tier-13-15 width, shorter than FEATURE_DIM
    doc = {
        "student_id": student_id,
        "samples": [
            {
                "text": "legacy short-vector sample",
                "vector": short_vector,
                "provenance": "instructor_verified",
                "auth_weight": 1.0,
                "assignment": "",
                "submitted_at": "",
                "genre": None,
                "topic_centroid": None,
                "context_manifest": None,
                "keystroke_data": None,
            }
        ],
        "baseline_kappa": None,
        "kappa_log": [],
        "consecutive_drift_count": 0,
    }
    with session_scope() as session:
        postgres_repository.PostgresRepository._ensure_tenant_exists(session, tenant_id)
        # merge(), not add(): this file's tests share one real Postgres
        # instance with no per-test table wipe (unlike
        # test_repository_contract.py's `repo` fixture), so a plain INSERT
        # would violate the primary key on a second local run against the
        # same persistent container. merge() upserts by primary key.
        session.merge(StudentProfile(tenant_id=tenant_id, student_id=local_id, data=doc))

    repo = postgres_repository.PostgresRepository()
    state = repo.get(student_id)
    assert state is not None
    vector = state.samples[0].vector
    assert vector.shape == (FEATURE_DIM,)
    assert list(vector[:74]) == short_vector
    assert all(v == pytest.approx(0.5) for v in vector[74:])


@pytest.mark.postgres
def test_get_fused_scores_degrades_channels_on_corrupted_json_row():
    """Mirrors test_store_get_fused_scores_degrades_channels_on_corrupted_json
    (Step 1b) for PostgresRepository's own inner per-row fallback.
    channels_json is a plain Text column on FusedScore (see its model
    comment) precisely so this failure mode is representable the same way
    on both backends -- constructed with a raw UPDATE through the same
    session factory the repository itself uses (sanctioned: constructs a
    state unreachable through the protocol). The assertion reads back
    through repo.get_fused_scores(), the public API."""
    if not _postgres_session_available():
        pytest.skip(
            "no reachable Postgres -- set DATABASE_URL to a postgresql:// "
            "instance to run this inner-JSON-corruption-fallback test"
        )
    from sqlalchemy import text

    from original.db.postgres_session import session_scope

    repo = postgres_repository.PostgresRepository()
    repo.put_fused_score(
        submission_id="sub-pg-corrupt-1",
        student_id="sem:pg-corrupt-stu",
        fused_log_odds=0.1,
        probability=0.52,
        band="low",
        channels={"peer_centered_z": 0.4},
        model_version="v1",
    )
    with session_scope() as session:
        session.execute(
            text("UPDATE fused_scores SET channels_json = :v WHERE submission_id = :sid"),
            {"v": "{not valid json", "sid": "sub-pg-corrupt-1"},
        )

    rows = repo.get_fused_scores(student_id="sem:pg-corrupt-stu")
    assert len(rows) == 1
    assert rows[0]["submission_id"] == "sub-pg-corrupt-1"
    assert rows[0]["band"] == "low"
    assert rows[0]["channels"] == {}


@pytest.mark.postgres
def test_delete_tenant_students_records_failed_id_when_delete_student_fails(monkeypatch):
    """delete_tenant_students only calls delete_student() on ids it just
    fetched via list_ids_for_tenant(), which by construction exist -- so
    delete_student() genuinely returning False is unreachable through the
    protocol alone. Monkeypatching delete_student itself is the same
    sanctioned "narrow seam" idiom as monkeypatching session_scope, one
    level up: it's the only way to observe the failed-ids bookkeeping
    (the else branch of delete_tenant_students' own if/else) at all."""
    if not _postgres_session_available():
        pytest.skip(
            "no reachable Postgres -- set DATABASE_URL to a postgresql:// "
            "instance to run this bulk-delete partial-failure test"
        )
    # A dedicated tenant -- this file's tests share one real Postgres
    # instance with no per-test table wipe (unlike test_repository_contract.py's
    # `repo` fixture), so a shared id like "sem" would pick up other tests'
    # students and make deleted_count depend on run order.
    tenant_id = "pg-bulk-delete-guard-tenant"
    repo = postgres_repository.PostgresRepository()
    repo.put(StudentState(student_id=f"{tenant_id}:pg-bulk-ok"))
    repo.put(StudentState(student_id=f"{tenant_id}:pg-bulk-fail"))

    real_delete_student = repo.delete_student

    def _fake_delete_student(student_id):
        if student_id == f"{tenant_id}:pg-bulk-fail":
            return False
        return real_delete_student(student_id)

    monkeypatch.setattr(repo, "delete_student", _fake_delete_student)
    result = repo.delete_tenant_students(tenant_id)
    assert result["deleted_count"] == 1
    assert result["failed_ids"] == [f"{tenant_id}:pg-bulk-fail"]


# ── Step 8: Remaining store.py exception guards (single _get_conn call) ────
#
# Mirrors Step 4 for store.py's module-level functions, monkeypatching
# store._get_conn (the narrowest seam store.py's own connections go
# through -- see module docstring item 1's rationale, same idiom one level
# down).


def _store_boom():
    raise RuntimeError("simulated connection failure")


def _store_boom_sqlite_error():
    raise sqlite3.OperationalError("simulated connection failure")


_STORE_SINGLE_CALL_GUARDS = [
    (
        "put_manifest",
        ("sub-store-guard", "sem:store-guard-1", {"created_at": "2026-01-01T00:00:00Z"}),
        {},
        None,
    ),
    ("submission_student_id", ("sub-store-guard",), {}, None),
    ("get_manifest", ("sub-store-guard",), {}, None),
    ("list_manifests", (), {}, {"total": 0, "limit": 100, "offset": 0, "items": []}),
    (
        "manifest_stats",
        (),
        {},
        {
            "total": 0,
            "by_action": {},
            "by_flag": {},
            "by_length_regime": {},
            "mean_divergence": None,
            "since": None,
            "until": None,
        },
    ),
    ("put_fidelity_score", ("sub-store-guard", "sem:store-guard-1", 0.5, True), {}, None),
    ("get_authentic_fidelities", ("sem:store-guard-1",), {}, []),
    ("put_ai_likelihood_score", ("sub-store-guard", "sem:store-guard-1", 0.5, "low"), {}, None),
    ("get_ai_likelihood_scores", (), {}, []),
    ("put_fused_score", ("sub-store-guard", "sem:store-guard-1", 0.1, 0.5, "low", {}), {}, None),
    ("get_fused_scores", (), {}, []),
    ("update_fidelity_authenticity", ("sub-store-guard", True), {}, None),
    # A single global boom exercises BOTH of put_correction's guards in one
    # call: no student_id/original_* kwargs forces the audit_log fallback
    # lookup (its own try/except Exception: pass), which then also fails,
    # leaving student_id None before the main INSERT try/except is reached.
    ("put_correction", ("sub-store-corr-guard", True), {}, None),
    ("list_corrections", (), {}, {"total": 0, "limit": 100, "offset": 0, "items": []}),
    ("start_calibration_run", ("dataset-store-guard",), {}, None),
    (
        "complete_calibration_run",
        (1,),
        {"auc": 0.5, "n_essays_scored": 1, "n_authors": 1, "report": {}},
        False,
    ),
    ("fail_calibration_run", (1, "boom"), {}, False),
    ("list_calibration_runs", (), {}, {"total": 0, "limit": 50, "offset": 0, "items": []}),
    ("get_calibration_run", (1,), {}, None),
    (
        "put_tuned_thresholds",
        (),
        {"no_action": 0.1, "monitor": 0.2, "escalate": 0.3, "source": "manual"},
        None,
    ),
    ("get_active_tuned_thresholds", (), {}, None),
    ("list_tuned_thresholds", (), {}, {"total": 0, "limit": 50, "offset": 0, "items": []}),
    ("put_tenant", ("sem", "Seminary"), {}, None),
    ("get_tenant", ("sem",), {}, None),
    ("put_user", ("u-store-guard", "store-guard@example.com", "hash", "admin", "sem"), {}, None),
    ("get_user_by_email", ("store-guard@example.com",), {}, None),
    ("get_bluebook_exam", ("exam-store-guard",), {}, None),
    ("list_bluebook_exams", ("sem",), {}, []),
    ("list_bluebook_submissions", ("sem",), {}, []),
    ("get_bluebook_submission_by_uuid", ("uuid-store-guard",), {}, None),
    ("get_bluebook_session", ("exam-store-guard", "key-store-guard"), {}, None),
    ("list_bluebook_courses", ("sem",), {}, []),
    ("list_tenants", (), {}, []),
    ("log_audit", ("action-store-guard",), {}, None),
    ("list_audit", (), {}, {"total": 0, "limit": 100, "offset": 0, "items": []}),
    ("set_display_name", ("sem:store-guard-1", "Name"), {}, None),
    ("get_display_name", ("sem:store-guard-1",), {}, ""),
    ("_display_names_for", (["sem:store-guard-1"],), {}, {}),
    ("_latest_actions_for", (["sem:store-guard-1"],), {}, {}),
    ("get_formation_pathway", ("sem:store-guard-1",), {}, None),
    ("open_formation_pathway", ("sem:store-guard-1",), {}, None),
    (
        "put_baseline_request",
        ("req-store-guard", "sem:store-guard-1", "pending", 100.0, "{}"),
        {},
        None,
    ),
    ("load_baseline_requests", (), {}, []),
]


@pytest.mark.parametrize("func_name, args, kwargs, expected", _STORE_SINGLE_CALL_GUARDS)
def test_store_guard_swallows_connection_failure(monkeypatch, func_name, args, kwargs, expected):
    monkeypatch.setattr(store, "_get_conn", _store_boom)
    fn = getattr(store, func_name)
    result = fn(*args, **kwargs)
    assert result == expected


# ── Step 9: store.py guards that re-raise instead of swallowing ────────────
#
# These four writers catch sqlite3.Error specifically (not bare Exception)
# and re-raise -- matching PostgresRepository's equivalent writers (Step 5),
# which log-and-raise on generic Exception. _store_boom_sqlite_error raises
# sqlite3.OperationalError so it's actually caught by that narrower except
# clause, not just propagated past it uncaught.

_STORE_SQLITE_ERROR_GUARDS = [
    ("put_bluebook_exam", ({"id": "exam-store-raise", "tenant_id": "sem", "title": "T"},), {}),
    ("put_bluebook_submission", ({"id": "sub-store-raise", "tenant_id": "sem"},), {}),
    (
        "get_or_create_bluebook_session",
        ("exam-store-raise", "key-store-raise", "sem", 1800),
        {},
    ),
    ("put_bluebook_course", ({"id": "course-store-raise", "tenant_id": "sem", "name": "N"},), {}),
]


@pytest.mark.parametrize("func_name, args, kwargs", _STORE_SQLITE_ERROR_GUARDS)
def test_store_guard_reraises_sqlite_error_on_connection_failure(
    monkeypatch, func_name, args, kwargs
):
    monkeypatch.setattr(store, "_get_conn", _store_boom_sqlite_error)
    fn = getattr(store, func_name)
    with pytest.raises(sqlite3.OperationalError, match="simulated connection failure"):
        fn(*args, **kwargs)


# ── Step 10: store.py two-stage guards ──────────────────────────────────────
#
# Same "boom after the Nth real call" idiom as Step 6, for the three
# store.py functions whose own except block sits behind an EARLIER,
# unguarded call using the same _get_conn seam (get()/list_ids() have no
# try/except of their own at all -- the WS-1 A1 "fail loudly on a corrupt
# DB" guarantee documented near _persist()'s definition -- so a single
# global boom raises there first and never reaches the guard under test).


def test_store_tenant_stats_returns_zeroed_stats_on_second_connection_failure(
    store_reset, monkeypatch
):
    """tenant_stats() calls list_ids_for_tenant() -> list_ids() (unguarded)
    before its own try/except. Call #1 (list_ids()) succeeds for real
    (returning [] against the isolated, empty store_reset DB); call #2
    (tenant_stats' own submission_manifests query) is made to fail."""
    real_get_conn = store_reset._get_conn
    calls = {"n": 0}

    def _boom_after_first_call():
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("simulated connection failure")
        return real_get_conn()

    monkeypatch.setattr(store_reset, "_get_conn", _boom_after_first_call)
    result = store_reset.tenant_stats("sem-tenant-stats-guard")
    assert result == {
        "tenant_id": "sem-tenant-stats-guard",
        "student_count": 0,
        "sample_count": 0,
        "submission_count": 0,
        "last_active_at": None,
        "action_counts": {},
    }


def test_store_delete_student_returns_false_on_second_connection_failure(store_reset, monkeypatch):
    """delete_student() calls get() (unguarded) as an existence pre-check
    before its own try/except. Call #1 (get()) must succeed and find the
    real profile put() persisted; call #2 (delete_student's own DELETEs) is
    made to fail."""
    student_id = "sem:store-delete-guard"
    store_reset.put(StudentState(student_id=student_id))

    real_get_conn = store_reset._get_conn
    calls = {"n": 0}

    def _boom_after_first_call():
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("simulated connection failure")
        return real_get_conn()

    monkeypatch.setattr(store_reset, "_get_conn", _boom_after_first_call)
    assert store_reset.delete_student(student_id) is False


def test_store_delete_student_clears_fusion_peer_cache_when_module_is_imported(
    store_reset, monkeypatch
):
    """store.py:[1702,1704] — `_fusion_peers = sys.modules.get(
    "original.fusion.peers"); if _fusion_peers is not None: ...clear_student(...)`.

    original.fusion.peers is optional and guarded via sys.modules precisely
    because the fusion package may never have been imported when the fused-
    score flags are off — delete_student() must not import it itself. Since
    other tests in a full suite run may or may not have already imported the
    real module (an ambient, order-dependent side effect), pin the state
    directly with monkeypatch.setitem(sys.modules, ...) rather than relying
    on import order: a fake module with a `clear_student` spy proves both
    that the True arm is taken (sys.modules lookup finds it) AND that the
    real function gets called with the deleted student's id -- something the
    module-import-only version of this test (test_repository_contract.py's
    TestDeleteStudentFullFootprint) doesn't itself assert."""
    import sys
    import types

    student_id = "sem:fusion-peer-clear"
    store_reset.put(StudentState(student_id=student_id))

    calls: list[str] = []
    fake_peers = types.ModuleType("original.fusion.peers")
    fake_peers.clear_student = lambda sid: calls.append(sid)
    monkeypatch.setitem(sys.modules, "original.fusion.peers", fake_peers)

    assert store_reset.delete_student(student_id) is True
    assert calls == [student_id]


def test_store_delete_student_skips_fusion_peer_cache_when_module_absent(
    store_reset, monkeypatch
):
    """store.py:[1702,1704] -- False arm. The sibling test above
    (test_store_delete_student_clears_fusion_peer_cache_when_module_is_imported)
    forces `original.fusion.peers` to be present in sys.modules, which only
    ever exercises the True arm (`1703->1704`) of the guard. The False arm
    (`1703->1705`, straight to `return True` with no clear_student() call)
    needs the module to be genuinely absent from sys.modules, which is not
    guaranteed by ambient state -- some other test in the process, or the
    fusion-enabled flags, may have already imported original.fusion.peers as
    a side effect. Pin the absence directly with monkeypatch.delitem(...,
    raising=False) so this proves the guard skips the cache-clear step
    regardless of what ran before it, rather than merely running default
    (potentially already-True-arm) sys.modules state."""
    import sys

    monkeypatch.delitem(sys.modules, "original.fusion.peers", raising=False)

    student_id = "sem:fusion-peer-absent"
    store_reset.put(StudentState(student_id=student_id))

    assert store_reset.delete_student(student_id) is True


def test_store_advance_formation_pathway_returns_none_on_second_connection_failure(
    store_reset, monkeypatch
):
    """Mirrors test_advance_formation_pathway_returns_none_on_second_session_failure
    (Step 6) for store.py: get_formation_pathway (call #1, real) must find
    a genuinely open pathway before advance_formation_pathway's own UPDATE
    (call #2) is made to fail."""
    student_id = "sem:store-advance-guard"
    opened = store_reset.open_formation_pathway(student_id)
    assert opened["status"] == "open"

    real_get_conn = store_reset._get_conn
    calls = {"n": 0}

    def _boom_after_first_call():
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("simulated connection failure")
        return real_get_conn()

    monkeypatch.setattr(store_reset, "_get_conn", _boom_after_first_call)
    assert store_reset.advance_formation_pathway(student_id) is None


def test_store_student_data_inventory_degrades_on_second_connection_failure(
    store_reset, monkeypatch
):
    """student_data_inventory() calls get() (unguarded) as an existence
    pre-check before its own try/except, same shape as delete_student()
    above. Call #1 (get()) must succeed and find the real profile put()
    persisted; call #2 (student_data_inventory's own COUNT queries) is made
    to fail, degrading every count to 0 rather than raising."""
    student_id = "sem:store-inventory-guard"
    store_reset.put(StudentState(student_id=student_id))

    real_get_conn = store_reset._get_conn
    calls = {"n": 0}

    def _boom_after_first_call():
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("simulated connection failure")
        return real_get_conn()

    monkeypatch.setattr(store_reset, "_get_conn", _boom_after_first_call)
    result = store_reset.student_data_inventory(student_id)
    assert result is not None
    cats = result["data_categories"]
    assert cats["fidelity_scores"]["count"] == 0
    assert cats["submission_manifests"]["total"] == 0
    assert cats["instructor_corrections"]["count"] == 0
    assert cats["audit_log_entries"]["count"] == 0
    assert cats["ai_likelihood_scores"]["count"] == 0
    assert cats["fused_scores"]["count"] == 0
    assert cats["display_name"]["on_file"] is False


def test_store_delete_tenant_students_records_failed_id_when_delete_student_fails(
    store_reset, monkeypatch
):
    """Mirrors test_delete_tenant_students_records_failed_id_when_delete_student_fails
    (Step 7) for store.py's module-level delete_student -- same "the False
    branch is unreachable through the protocol alone" reasoning."""
    store_reset.put(StudentState(student_id="sem:store-bulk-ok"))
    store_reset.put(StudentState(student_id="sem:store-bulk-fail"))

    real_delete_student = store_reset.delete_student

    def _fake_delete_student(student_id):
        if student_id == "sem:store-bulk-fail":
            return False
        return real_delete_student(student_id)

    monkeypatch.setattr(store_reset, "delete_student", _fake_delete_student)
    result = store_reset.delete_tenant_students("sem")
    assert result["deleted_count"] == 1
    assert result["failed_ids"] == ["sem:store-bulk-fail"]


# ── Step 11: store.py inner per-row JSON-corruption fallbacks ──────────────
#
# Same raw-SQL-constructs-the-fixture idiom as Step 1b, for every other
# store.py function with its own per-row try/except around a TEXT-column
# JSON blob (manifest_json, data_json, transitions_json) -- get_fused_scores'
# twin was already covered by Task 4; these are the ones Task 4 didn't
# reach.


def test_store_list_manifests_degrades_on_corrupted_manifest_json(store_reset):
    store_reset.put_manifest(
        "sub-store-corrupt-1",
        "sem:store-corrupt-stu",
        {"created_at": "2026-01-01T00:00:00Z"},
        action="monitor",
    )
    conn = sqlite3.connect(str(store_reset._DB_PATH))
    try:
        conn.execute(
            "UPDATE submission_manifests SET manifest_json = ? WHERE submission_id = ?",
            ("{not valid json", "sub-store-corrupt-1"),
        )
        conn.commit()
    finally:
        conn.close()

    result = store_reset.list_manifests(student_id="sem:store-corrupt-stu")
    assert result["total"] == 1
    item = result["items"][0]
    assert item["submission_id"] == "sub-store-corrupt-1"
    assert item["flags"] == []
    assert item["anchor_tiers"] == []
    assert item["length_regime"] == "unknown"


def test_store_manifest_stats_degrades_on_corrupted_manifest_json(store_reset):
    store_reset.put_manifest(
        "sub-store-corrupt-2",
        "sem:store-corrupt-stu2",
        {"created_at": "2026-01-01T00:00:00Z"},
        action="no_action",
    )
    conn = sqlite3.connect(str(store_reset._DB_PATH))
    try:
        conn.execute(
            "UPDATE submission_manifests SET manifest_json = ? WHERE submission_id = ?",
            ("{not valid json", "sub-store-corrupt-2"),
        )
        conn.commit()
    finally:
        conn.close()

    result = store_reset.manifest_stats()
    assert result["total"] == 1
    assert result["by_action"] == {"no_action": 1}
    assert result["by_length_regime"] == {"unknown": 1}
    assert result["by_flag"] == {}


def test_store_get_calibration_run_degrades_report_on_corrupted_json(store_reset):
    run_id = store_reset.start_calibration_run("dataset-store-corrupt")
    store_reset.complete_calibration_run(
        run_id, auc=0.5, n_essays_scored=1, n_authors=1, report={"roc": [0.1]}
    )
    conn = sqlite3.connect(str(store_reset._DB_PATH))
    try:
        conn.execute(
            "UPDATE calibration_runs SET report_json = ? WHERE id = ?",
            ("{not valid json", run_id),
        )
        conn.commit()
    finally:
        conn.close()

    run = store_reset.get_calibration_run(run_id, include_report=True)
    assert run is not None
    assert run["status"] == "completed"
    assert run["report"] == {}


def test_store_load_baseline_requests_skips_corrupted_row(store_reset):
    store_reset.put_baseline_request(
        "req-store-good", "sem:store-stu1", "pending", 100.0, json.dumps({"marker": "good"})
    )
    conn = sqlite3.connect(str(store_reset._DB_PATH))
    try:
        conn.execute(
            "INSERT INTO baseline_requests "
            "(external_request_id, student_id, status, requested_at, data_json) "
            "VALUES (?, ?, ?, ?, ?)",
            ("req-store-corrupt", "sem:store-stu2", "pending", 200.0, "{not valid json"),
        )
        conn.commit()
    finally:
        conn.close()

    result = store_reset.load_baseline_requests()
    assert len(result) == 1
    assert result[0]["marker"] == "good"


def test_store_park_beat_and_park_tiles_recover_from_corrupted_transitions_json(store_reset):
    """park_beat and park_tiles each parse transitions_json independently
    (there's no shared helper), so each gets its own corruption exercised
    separately: first a state-change park_beat() call that reads back
    corrupted history and discards it rather than crashing (3426-3427),
    then a fresh corruption with no intervening park_beat call so nothing
    "heals" the column before park_tiles reads it directly (3459-3460)."""
    now = datetime.now(UTC)
    exam_session_id, tenant_id, token = "park-corrupt-exam", "sem", "park-corrupt-token"
    hint = "park-corrupt-hint"

    store_reset.park_open(exam_session_id, tenant_id, token, now)
    store_reset.park_beat(token, hint, "active", now)

    conn = sqlite3.connect(str(store_reset._DB_PATH))
    try:
        conn.execute(
            "UPDATE park_beats SET transitions_json = ? WHERE park_token = ? AND student_hint = ?",
            ("{not valid json", token, hint),
        )
        conn.commit()
    finally:
        conn.close()

    store_reset.park_beat(token, hint, "dropped", now)
    tiles = store_reset.park_tiles(exam_session_id)
    assert len(tiles) == 1
    assert tiles[0]["state"] == "dropped"
    assert tiles[0]["transitions"] == [{"state": "dropped", "at": store.park_iso_utc(now)}]

    conn = sqlite3.connect(str(store_reset._DB_PATH))
    try:
        conn.execute(
            "UPDATE park_beats SET transitions_json = ? WHERE park_token = ? AND student_hint = ?",
            ("{not valid json", token, hint),
        )
        conn.commit()
    finally:
        conn.close()

    tiles_after_corruption = store_reset.park_tiles(exam_session_id)
    assert len(tiles_after_corruption) == 1
    assert tiles_after_corruption[0]["transitions"] == []


# ── Step 12: legacy-dimension padding, store.py side ────────────────────────


def test_store_deserialize_pads_legacy_short_vector(store_reset):
    """Mirrors test_doc_to_state_pads_legacy_short_vector (Step 7) for
    store.py's own _deserialize. store.py's public write API always
    produces FEATURE_DIM-wide vectors, so the only way to construct a
    stored document with a legacy short vector is a raw INSERT of a hand-
    built JSON blob -- sanctioned to construct this otherwise-unreachable
    fixture state. The assertion reads back through store.get(), the
    public API."""
    student_id = "sem:store-legacy-dim-student"
    short_vector = [0.25] * 62  # pre-Tier-8-12 width, shorter than FEATURE_DIM
    doc = {
        "student_id": student_id,
        "samples": [
            {
                "text": "legacy short-vector sample",
                "vector": short_vector,
                "provenance": "instructor_verified",
                "auth_weight": 1.0,
                "assignment": "",
                "submitted_at": "",
                "word_count": None,
                "genre": None,
                "topic_centroid": None,
                "context_manifest": None,
                "keystroke_data": None,
            }
        ],
        "baseline_kappa": None,
        "kappa_log": [],
        "consecutive_drift_count": 0,
    }
    # Trigger schema creation first -- a bare sqlite3.connect() against a
    # brand-new store_reset DB file predates _init_schema() ever running on
    # it, so student_profiles doesn't exist yet.
    store_reset.list_ids()
    conn = sqlite3.connect(str(store_reset._DB_PATH))
    try:
        conn.execute(
            "INSERT OR REPLACE INTO student_profiles (student_id, data) VALUES (?, ?)",
            (student_id, json.dumps(doc)),
        )
        conn.commit()
    finally:
        conn.close()

    state = store_reset.get(student_id)
    assert state is not None
    vector = state.samples[0].vector
    assert vector.shape == (FEATURE_DIM,)
    assert list(vector[:62]) == short_vector
    assert all(v == pytest.approx(0.5) for v in vector[62:])


# ── Step 13: original/db/session.py (dormant v1 stack) ─────────────────────
#
# Never reached by anything in the live stack (see the module's own
# docstring); Step 2 already covers its get_engine() branches. get_db()/
# init_db()/drop_db() were still at 0% within this scoped run.


def test_db_session_get_db_yields_and_closes_session():
    from original.db import session as db_session

    gen = db_session.get_db()
    session = next(gen)
    assert session is not None
    # Drive past the yield so the `finally: session.close()` line runs too.
    with pytest.raises(StopIteration):
        next(gen)


def test_db_session_init_db_and_drop_db_against_a_throwaway_engine(monkeypatch):
    """init_db()/drop_db() bind to the module-level _engine global (built
    once at import time from whatever DATABASE_URL the dormant v1 Settings
    resolved to then), not a fresh get_engine() call -- monkeypatch that
    global to a throwaway in-memory engine so this never touches the real
    configured database."""
    from sqlalchemy import create_engine, inspect

    from original.db import session as db_session
    from original.db.base import Base

    throwaway_engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(db_session, "_engine", throwaway_engine)

    db_session.init_db()
    assert set(Base.metadata.tables) <= set(inspect(throwaway_engine).get_table_names())

    db_session.drop_db()
    assert inspect(throwaway_engine).get_table_names() == []


def test_postgres_session_init_db_and_drop_db_against_a_throwaway_engine(monkeypatch):
    """The LIVE schema's init_db()/drop_db() (original/db/postgres_session.py)
    -- distinct from the dormant v1 pair just above -- call get_engine()
    fresh each time rather than binding a cached global, so monkeypatching
    get_engine() itself is the narrow seam here. Every other test that
    needs the live schema (test_repository_contract.py's `repo` fixture)
    calls LiveBase.metadata.create_all()/table.delete() directly against
    the real shared Postgres instance instead of through these two
    wrappers, which is why they were still uncovered -- and exactly why
    this test must NOT run them for real: drop_db() would wipe every table
    other tests in this session depend on."""
    from sqlalchemy import create_engine, inspect

    from original.db import postgres_session
    from original.db.models.live import LiveBase

    throwaway_engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(postgres_session, "get_engine", lambda: throwaway_engine)

    postgres_session.init_db()
    assert set(LiveBase.metadata.tables) <= set(inspect(throwaway_engine).get_table_names())

    postgres_session.drop_db()
    assert inspect(throwaway_engine).get_table_names() == []


# ── Step 14: repository.py's SqliteRepository.db_path() ────────────────────
#
# PostgresRepository.db_path() raising NotImplementedError is already
# covered by tests/test_baseline_requests.py::
# test_postgres_repo_db_path_has_no_equivalent (outside this task's scoped
# file list, confirmed by direct measurement -- see the task report). Only
# the SqliteRepository forwarding line had no coverage anywhere in scope.


def test_sqlite_repository_db_path_matches_store_db_path(store_reset):
    import original.repository as repository

    repository.reset_repository()
    repo = repository.get_repository()
    assert isinstance(repo, repository.SqliteRepository)
    assert repo.db_path() == store_reset._DB_PATH
