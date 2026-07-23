"""
tests/test_migration.py — WS-6 P4 SQLite -> Postgres migration parity.

Seeds a temp SQLite store through the *real* store.py write paths (so the row
shapes are exactly what production writes -- including the edge cases a
Repository-level migration would drop: is_authentic=False fidelity rows,
NULL-student corrections, colon-less legacy ids, system-action audit rows),
runs scripts/migrate_sqlite_to_pg.migrate() against a live Postgres instance,
and asserts row-count + checksum parity for every table in the live schema.

The completeness check (``TestMigrationParity.
test_full_migration_reports_parity_for_every_live_table``) DERIVES the
expected table set from ``original.db.models.live.LiveBase.metadata.tables``
rather than a hardcoded count, specifically so a table added to the live
schema without a corresponding migrator in scripts/migrate_sqlite_to_pg.py
fails this test loudly instead of silently dropping that table's data on a
real cutover. See ``_EXCLUDED_FROM_MIGRATION`` for the (currently empty) list
of tables legitimately exempted from that check.

Postgres-gated exactly like tests/test_repository_contract.py: self-skips when
DATABASE_URL isn't a reachable postgresql:// instance. Marked @pytest.mark.postgres.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState

pytestmark = pytest.mark.postgres

# Tables present in original.db.models.live.LiveBase.metadata that the
# migration script legitimately does NOT migrate. Empty today -- every live
# table has a migrator in scripts/migrate_sqlite_to_pg.MIGRATORS. Add an entry
# here (with a comment justifying it) only for a table that's genuinely out of
# scope for the SQLite->Postgres cutover; do NOT add one just to make a
# missing migrator's test failure go away.
_EXCLUDED_FROM_MIGRATION: frozenset[str] = frozenset()


def _postgres_available() -> bool:
    if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
        return False
    from original.db import postgres_session

    try:
        postgres_session.reset_engine()
        with postgres_session.get_engine().connect():
            return True
    except Exception:
        return False


def _make_state(student_id: str, n: int = 2, genre: str | None = None) -> StudentState:
    state = StudentState(student_id=student_id)
    rng = np.random.default_rng(abs(hash(student_id)) % (2**31))
    for i in range(n):
        state.add_sample(
            BaselineSample(
                text=f"Sample {i} for migration testing.",
                vector=rng.random(FEATURE_DIM).astype(np.float64),
                provenance="proctored",
                auth_weight=1.0,
                assignment=f"A{i}",
                genre=genre,
            )
        )
    return state


def _seed_sqlite(store) -> None:
    """Populate every one of the live-schema tables via the real store write
    paths, deliberately hitting the shapes a naive migration would lose."""
    # tenants (real + demo environments)
    store.put_tenant("sem", "Seminary of Dallas", environment="pilot", meta={"contact": "a@b.edu"})
    store.put_tenant("acme", "Acme College", environment="demo")

    # users
    store.put_user("u1", "prof@sem.edu", "pbkdf2-hash-1", "professor", "sem", name="Prof One")
    store.put_user("u2", "op@acme.edu", "pbkdf2-hash-2", "operator", "acme")

    # student_profiles (scoped + a colon-less legacy flat id)
    store.put(_make_state("sem:alice", n=3, genre="sermon"))
    store.put(_make_state("sem:bob", n=1))
    store.put(_make_state("legacy_flat_student", n=2))  # no tenant prefix

    # student_names (one real, blank never overwrites so only set real ones)
    store.set_display_name("sem:alice", "Alice Anderson")
    store.set_display_name("legacy_flat_student", "Legacy Student")

    # submission_manifests (with flags + a null-action variant)
    store.put_manifest(
        "sub-1",
        "sem:alice",
        {"created_at": "2026-01-01T00:00:00Z", "flags": ["length_short"], "length_regime": "short"},
        divergence_score=0.42,
        action="monitor",
    )
    store.put_manifest(
        "sub-2",
        "sem:bob",
        {"created_at": "2026-01-02T12:30:00Z", "flags": []},
        divergence_score=None,
        action=None,
    )

    # corrections (one full, one auto-filled, one with NULL student_id)
    store.put_correction(
        "sub-1",
        True,
        student_id="sem:alice",
        original_verdict="authentic",
        original_action="monitor",
        original_divergence_score=0.42,
        reviewer="prof@sem.edu",
        notes="looks fine",
    )
    store.put_correction("sub-orphan", False)  # no student_id, no manifest -> NULL student

    # calibration_runs (one completed, one failed)
    r1 = store.start_calibration_run("dataset-A", run_label="run-1", config={"k": 3})
    store.complete_calibration_run(
        r1, auc=0.91, n_essays_scored=120, n_authors=40, report={"roc": [[0, 0], [1, 1]]}
    )
    r2 = store.start_calibration_run("dataset-B")
    store.fail_calibration_run(r2, "boom")

    # tuned_thresholds_v2 (two versions -> newest is active)
    store.put_tuned_thresholds(no_action=0.3, monitor=0.6, escalate=0.85, source="manual")
    store.put_tuned_thresholds(
        no_action=0.32,
        monitor=0.62,
        escalate=0.87,
        source="calibration_run",
        source_run_id=r1,
        verdict_authentic_below=0.4,
        notes="tuned",
        provenance={"by": "op"},
    )

    # fidelity_scores (BOTH authenticity values -- the is_authentic=False row is
    # the one a Repository-level migration would drop)
    store.put_fidelity_score("sub-1", "sem:alice", 0.88, is_authentic=True)
    store.put_fidelity_score("sub-2", "sem:bob", 0.31, is_authentic=False)

    # ai_likelihood_scores
    store.put_ai_likelihood_score("sub-1", "sem:alice", 0.12, "low", model_version="hgb-v1")

    # bluebook exams / submissions / courses
    store.put_bluebook_exam(
        {
            "id": "exam-1",
            "tenant_id": "sem",
            "title": "Final",
            "course": "THEO101",
            "minWords": 300,
            "conditions": {"blockWeb": True},
        }
    )
    store.put_bluebook_submission(
        {
            "id": "bbsub-1",
            "tenant_id": "sem",
            "exam_id": "exam-1",
            "student_id": "sem:alice",
            "candidate": "Alice",
            "word_count": 500,
            "submission_uuid": "seal-uuid-bbsub-1",
            "late": 1,
        }
    )
    store.put_bluebook_course(
        {"id": "course-1", "tenant_id": "sem", "name": "Theology 101", "code": "THEO101"}
    )

    # bluebook_sessions (composite PK exam_id+student_key -- two rows sharing
    # the same exam_id, distinguished only by student_key, so a naive
    # single-column checksum/parity key would collide them)
    store.get_or_create_bluebook_session("exam-1", "sem:alice", "sem", 3600)
    store.get_or_create_bluebook_session("exam-1", "sem:bob", "sem", 1800)

    # audit_log (student-scoped derives tenant; system action has student=None)
    store.log_audit("baseline_add", student_id="sem:alice", details={"n": 1})
    store.log_audit("tenant_register", tenant_id="sem", details={"name": "Seminary of Dallas"})
    store.log_audit("score", student_id="legacy_flat_student", details={"sub": "x"})

    # formation_pathways (open, then advance once)
    store.open_formation_pathway("sem:alice", submission_id="sub-1", reason="divergence")
    store.advance_formation_pathway("sem:alice")

    # baseline_requests
    store.put_baseline_request(
        "req-1", "sem:bob", "pending", 1_700_000_000.0, '{"exam": "Week 3", "status": "pending"}'
    )

    # park_sessions / park_beats (QR phone-park proctoring, T8). park_sessions
    # carries a tenant_id FK like the other tenant-scoped tables above; the two
    # beats on the one session exercise both the composite (park_token,
    # student_hint) key and a real state transition (active -> left_page),
    # which is the shape that grows transitions_json beyond its initial entry.
    park_created = datetime(2026, 1, 3, 9, 0, 0, tzinfo=UTC)
    store.park_open("exam-sess-1", "sem", "ptok-abc123", park_created)
    store.park_beat("ptok-abc123", "AB", "active", datetime(2026, 1, 3, 9, 0, 5, tzinfo=UTC))
    store.park_beat("ptok-abc123", "AB", "left_page", datetime(2026, 1, 3, 9, 0, 20, tzinfo=UTC))
    store.park_beat("ptok-abc123", "CD", "active", datetime(2026, 1, 3, 9, 0, 8, tzinfo=UTC))


@pytest.fixture
def seeded_sqlite(tmp_path, monkeypatch):
    """A temp SQLite store seeded across every live-schema table; yields its
    path."""
    from original import store

    db_file = tmp_path / "migrate_src.db"
    monkeypatch.setenv("ORIGINAL_DB", str(db_file))
    monkeypatch.setattr(store, "_DB_PATH", db_file)
    store._GENRE_STATS_CACHE.clear()
    store._GENRE_STATS_CACHE.clear()
    _seed_sqlite(store)
    yield str(db_file)
    store._GENRE_STATS_CACHE.clear()


@pytest.fixture
def fresh_pg():
    """A freshly-created, empty live-schema Postgres. Skips without Postgres."""
    if not _postgres_available():
        pytest.skip("no reachable Postgres — set DATABASE_URL to run the P4 migration test")
    from original.db import postgres_session
    from original.db.models.live import LiveBase

    engine = postgres_session.get_engine()
    LiveBase.metadata.drop_all(bind=engine)
    LiveBase.metadata.create_all(bind=engine)
    yield
    LiveBase.metadata.drop_all(bind=engine)


class TestMigrationParity:
    def test_migrators_cover_exactly_the_live_schema(self):
        """The completeness guarantee: MIGRATORS must cover exactly the table
        set SQLAlchemy knows about for the live schema (minus any explicitly
        justified exclusion), DERIVED from LiveBase.metadata rather than a
        hardcoded number. A table added to db/models/live.py without a
        corresponding _Migrator fails this immediately -- that's the point:
        it turns "we forgot a table" from a silent SQLite->Postgres data loss
        into a loud, specific test failure instead of a stale count nobody
        double-checks. (This is exactly how park_sessions/park_beats were
        missed the first time: the old check compared the migration script's
        own table set against itself -- self-referential, so a migrator that
        was never written could never be caught missing.)"""
        from original.db.models.live import LiveBase
        from scripts.migrate_sqlite_to_pg import MIGRATORS

        expected = set(LiveBase.metadata.tables.keys()) - _EXCLUDED_FROM_MIGRATION
        migrated = {m.name for m in MIGRATORS}
        assert migrated == expected, (
            f"MIGRATORS doesn't match the live schema -- "
            f"missing migrators: {expected - migrated or None}, "
            f"unexpected/stale migrators: {migrated - expected or None}"
        )

    def test_full_migration_reports_parity_for_every_live_table(self, seeded_sqlite, fresh_pg):
        from original.db.models.live import LiveBase
        from scripts.migrate_sqlite_to_pg import MIGRATORS, migrate

        report = migrate(seeded_sqlite, dry_run=False)

        expected_tables = set(LiveBase.metadata.tables.keys()) - _EXCLUDED_FROM_MIGRATION
        assert {t["table"] for t in report["tables"]} == expected_tables, (
            "the migration report must cover every live table -- derived from "
            "LiveBase.metadata, not a hardcoded count"
        )
        assert {t["table"] for t in report["tables"]} == {m.name for m in MIGRATORS}

        # Every table: checksum + parity flag. Row-count is exact everywhere
        # EXCEPT tenants, where backfilled FK-integrity placeholders make
        # pg_rows exceed sqlite_rows by exactly the backfill count.
        n_backfilled = len(report["backfilled_tenants"])
        assert (
            n_backfilled >= 1
        ), "the seed's legacy-flat student should backfill a placeholder tenant"
        for t in report["tables"]:
            assert t["sqlite_checksum"] == t["pg_checksum"], f"{t['table']}: checksum drifted"
            assert t["parity"], f"{t['table']}: not at parity"
            if t["table"] == "tenants":
                assert t["pg_rows"] == t["sqlite_rows"] + n_backfilled
            else:
                assert t["sqlite_rows"] == t["pg_rows"], f"{t['table']}: row count drifted"
        assert report["parity"], "overall parity must hold"

    def test_seed_actually_populated_the_edge_cases(self, seeded_sqlite, fresh_pg):
        """Guards the guard: prove the seed exercised the shapes a naive
        migration would drop, so parity above is a real result, not vacuous."""
        from scripts.migrate_sqlite_to_pg import migrate

        report = migrate(seeded_sqlite, dry_run=False)
        by_table = {t["table"]: t for t in report["tables"]}
        # is_authentic=False fidelity row + authentic one both present
        assert by_table["fidelity_scores"]["sqlite_rows"] == 2
        # NULL-student correction + full one
        assert by_table["corrections"]["sqlite_rows"] == 2
        # colon-less flat id student migrated alongside scoped ones
        assert by_table["student_profiles"]["sqlite_rows"] == 3
        # two sessions sharing exam_id, distinguished only by student_key --
        # proves the composite-PK checksum/parity keys on both columns
        assert by_table["bluebook_sessions"]["sqlite_rows"] == 2
        # audit rows: the 3 explicit log_audit calls PLUS the ones the
        # formation-pathway open/advance ops log internally -- includes a
        # system-action row (student=None) and a legacy-flat-id row.
        assert by_table["audit_log"]["sqlite_rows"] >= 3
        # the legacy-flat student forced a placeholder tenant backfill
        assert "__legacy_flat__" in report["backfilled_tenants"]
        # phone-park: one session, two composite-key beat rows (park_token,
        # student_hint) -- this is the gap this change closes, so assert it
        # explicitly rather than only via the blanket parity loop above.
        assert by_table["park_sessions"]["sqlite_rows"] == 1
        assert by_table["park_beats"]["sqlite_rows"] == 2
        assert by_table["park_sessions"]["parity"]
        assert by_table["park_beats"]["parity"]
        assert (
            by_table["park_sessions"]["sqlite_checksum"] == by_table["park_sessions"]["pg_checksum"]
        )
        assert by_table["park_beats"]["sqlite_checksum"] == by_table["park_beats"]["pg_checksum"]

    def test_bluebook_submission_uuid_and_late_survive_migration(self, seeded_sqlite, fresh_pg):
        """Regression guard: _BluebookSubmissionMigrator predates the
        submission_uuid/late columns and used to silently drop them on both
        the read_sqlite and read_pg sides, so the checksum parity check in
        test_full_migration_reports_parity_for_all_17_tables couldn't catch
        it (both sides omitted the same columns symmetrically). Assert the
        actual migrated values directly, not just checksum/row-count parity."""
        from original.db import postgres_session
        from original.db.models.live import BluebookSubmission
        from scripts.migrate_sqlite_to_pg import migrate

        migrate(seeded_sqlite, dry_run=False)

        with postgres_session.session_scope() as session:
            row = session.query(BluebookSubmission).filter_by(submission_id="bbsub-1").one()
            assert row.submission_uuid == "seal-uuid-bbsub-1"
            assert row.late == 1

    def test_dry_run_does_not_write(self, seeded_sqlite, fresh_pg):
        """--dry-run reads + checksums both sides but writes nothing, so the
        PG side stays empty and (empty != seeded) reports no parity."""
        from scripts.migrate_sqlite_to_pg import migrate

        report = migrate(seeded_sqlite, dry_run=True)
        assert report["dry_run"] is True
        # PG is still empty, SQLite is seeded -> mismatch on populated tables.
        by_table = {t["table"]: t for t in report["tables"]}
        assert by_table["student_profiles"]["pg_rows"] == 0
        assert by_table["student_profiles"]["sqlite_rows"] == 3
        assert report["parity"] is False

    def test_idempotency_guard_second_run_conflicts(self, seeded_sqlite, fresh_pg):
        """A second migration into an already-populated PG must fail loudly on
        the PK conflict, not silently double-insert -- the script is a one-shot
        cutover tool, and re-running it by accident should error, not corrupt."""
        from sqlalchemy.exc import IntegrityError

        from scripts.migrate_sqlite_to_pg import migrate

        migrate(seeded_sqlite, dry_run=False)
        with pytest.raises(IntegrityError):
            migrate(seeded_sqlite, dry_run=False)


class TestChecksumCompositePK:
    """Direct unit tests on the composite-key sort key
    ``_BluebookSessionMigrator.pk`` feeds to
    ``scripts.migrate_sqlite_to_pg._checksum()``. No Postgres required --
    pure function, deterministic.

    Why this exists: the parity tests above (TestMigrationParity) seed
    bluebook_sessions with two rows sharing exam_id but differing in
    student_key, and assert sqlite/pg checksums match. That's necessary but
    not sufficient -- a reviewer proved by mutation testing that reverting
    _BluebookSessionMigrator.pk down to the naive single column "exam_id"
    still passed the full suite 3/3 runs, because SQLite's and Postgres's
    row-read order happened to coincide for the small seeded dataset.
    Row-count and end-to-end checksum equality are pk-agnostic by
    construction and can never catch that class of bug on their own.

    bluebook_sessions has no single-column primary key, so the migrator
    follows the convention _ParkBeatMigrator established for its own
    (park_token, student_hint) key: both read_sqlite and read_pg emit a
    synthetic ``session_key`` ("{exam_id}:{student_key}") into the canonical
    dict, and pk names that column. _checksum() itself stays a plain
    single-column sort -- there is exactly one composite-key mechanism in
    this script, not two.

    test_bluebook_session_checksum_is_order_invariant_for_composite_pk below
    closes the gap: it reads _BluebookSessionMigrator.pk directly (never a
    hardcoded column name), so if that attribute ever regresses to a column
    that doesn't distinguish the two rows, this test fails immediately.
    """

    @staticmethod
    def _tied_session_rows() -> list[dict]:
        """Two bluebook_sessions rows in canonical form that tie on exam_id
        and differ only in student_key (and downstream fields) -- the exact
        shape that lets a naive single-column-exam_id checksum silently
        depend on input order. ``session_key`` is built exactly as
        _BluebookSessionMigrator.read_sqlite/read_pg build it."""
        return [
            {
                "session_key": "exam-1:sem:alice",
                "exam_id": "exam-1",
                "student_key": "sem:alice",
                "tenant_id": "sem",
                "started_at": "2026-01-01T00:00:00+00:00",
                "deadline_at": "2026-01-01T01:00:00+00:00",
            },
            {
                "session_key": "exam-1:sem:bob",
                "exam_id": "exam-1",
                "student_key": "sem:bob",
                "tenant_id": "sem",
                "started_at": "2026-01-01T00:30:00+00:00",
                "deadline_at": "2026-01-01T00:30:00+00:00",
            },
        ]

    def test_session_key_matches_what_the_migrator_actually_emits(self):
        """The fixture above hand-writes the canonical rows, so it is only
        meaningful if it agrees with the migrator's real read path. Drive
        _BluebookSessionMigrator.read_sqlite over a real SQLite store seeded
        with the same two sittings and assert the emitted session_key values
        match -- otherwise the order-invariance test below could pass against
        a shape production never produces."""
        import sqlite3 as _sqlite3

        from scripts.migrate_sqlite_to_pg import _BluebookSessionMigrator

        conn = _sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE bluebook_sessions (exam_id TEXT, student_key TEXT, "
            "tenant_id TEXT, started_at TEXT, deadline_at TEXT)"
        )
        for r in self._tied_session_rows():
            conn.execute(
                "INSERT INTO bluebook_sessions VALUES (?, ?, ?, ?, ?)",
                (
                    r["exam_id"],
                    r["student_key"],
                    r["tenant_id"],
                    r["started_at"],
                    r["deadline_at"],
                ),
            )
        emitted = _BluebookSessionMigrator().read_sqlite(conn)
        conn.close()

        pk = _BluebookSessionMigrator.pk
        assert {row[pk] for row in emitted} == {
            row[pk] for row in self._tied_session_rows()
        }, "the hand-written canonical fixture drifted from read_sqlite's real output"

    def test_bluebook_session_checksum_is_order_invariant_for_composite_pk(self):
        """Feeds the SAME two tied rows to _checksum() forward and reversed,
        keyed on the live _BluebookSessionMigrator.pk. A correct composite
        sort key must produce an identical digest either way.

        This is the regression-proof test: if _BluebookSessionMigrator.pk is
        ever reverted to a bare "exam_id", both rows tie on that single key,
        Python's sort is stable, so the two rows keep their (opposite) input
        orders in the sorted output -- forward and reversed then hash to
        DIFFERENT digests and this assertion fails.
        """
        from scripts.migrate_sqlite_to_pg import _BluebookSessionMigrator, _checksum

        rows = self._tied_session_rows()
        pk = _BluebookSessionMigrator.pk
        forward = _checksum(rows, pk)
        backward = _checksum(list(reversed(rows)), pk)
        assert forward == backward, (
            "_checksum() over bluebook_sessions rows must be order-invariant; "
            "a mismatch here means _BluebookSessionMigrator.pk no longer names "
            "a column that distinguishes every row (e.g. it regressed to a "
            "naive single column such as 'exam_id')"
        )

    def test_single_column_pk_would_not_be_order_invariant_on_the_same_rows(self):
        """Demonstrates the composite key is doing real discriminating work
        (not just cosmetic): applying the SAME tied rows to a naive
        single-column pk="exam_id" -- what _BluebookSessionMigrator.pk would
        be under the exact regression above -- is NOT order-invariant, so it
        would produce spurious parity failures (or, as the reviewer found,
        an incidental pass that means nothing) depending on backend read
        order. This test hardcodes "exam_id" rather than reading it off the
        live migrator, so it stays meaningful even if the class attribute is
        fixed correctly -- it documents *why* the fix was needed.
        """
        from scripts.migrate_sqlite_to_pg import _checksum

        rows = self._tied_session_rows()
        naive_forward = _checksum(rows, "exam_id")
        naive_backward = _checksum(list(reversed(rows)), "exam_id")
        assert naive_forward != naive_backward, (
            "expected a naive single-column pk to be order-DEPENDENT on rows "
            "that tie on that column -- if this now passes, the two tied rows "
            "stopped ticking a genuine test of composite-key necessity"
        )
