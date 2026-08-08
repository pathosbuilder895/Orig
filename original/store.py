"""
store.py — Student state store with SQLite persistence.

Keeps a hot in-memory cache for sub-millisecond reads while
durably writing each mutation to a local SQLite database so
baseline profiles survive server restarts.

In production this would be backed by Postgres + pgvector.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from .constants import FEATURE_DIM
from .principal import tenant_of
from .quantum.state import BaselineSample, StudentState

log = logging.getLogger(__name__)


def _escape_like(s: str) -> str:
    r"""
    Escape SQL LIKE wildcards so a literal string can be used as a LIKE
    pattern. Escapes the backslash first (the escape char), then '%' and '_'.
    Pair with ``LIKE ? ESCAPE '\'`` in the query.
    """
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ── Database path ─────────────────────────────────────────────────────────────

_DB_PATH = Path(os.environ.get("ORIGINAL_DB", Path(__file__).parent.parent / "profiles.db"))

# ── Bayesian genre-pool cache ─────────────────────────────────────────────────
# Building a genre pool is O(N×S) — it iterates every student and every sample.
# Cache the pool keyed on (tenant, genre); bust on every put() so newly-added
# baseline samples are reflected in the next call. Dict clear is thread-safe in
# CPython (GIL-protected). This is the ONE process-local cache that survives
# WS-6 P6 (the _STORE profile cache is gone): it's a derived aggregate,
# invalidated on every write in THIS worker, and a cross-worker staleness
# window on a slow-moving population statistic is acceptable where stale
# student profiles were not.
#
# The key MUST stay a (tenant, genre) pair, not a bare genre: a genre-only key
# would hand one tenant's cached aggregate to the next tenant that asks for the
# same genre, reintroducing exactly the cross-tenant leak the filter removes.
#
# A genre of None is the genre-AGNOSTIC pool backing get_cohort_stats — its own
# distinct key, never conflated with a real genre label (no genre is named
# None), so the two share one cache, one scan idiom, and one busting site.
#
# What's cached is the pool grouped BY STUDENT, not a finished mean/std, so
# that get_genre_stats's leave-one-out exclusion is a filter over the cached
# groups rather than a fresh scan per student. Caching finished stats under a
# (tenant, genre, excluded) key would be correct but would make every distinct
# student a guaranteed cache miss — turning the one cache that amortises the
# full-store scan into a per-student scan.
_GENRE_STATS_CACHE: dict[tuple[str | None, str | None], list[tuple[str, list[np.ndarray]]]] = {}


# ── SQLite helpers ────────────────────────────────────────────────────────────

# ``ORIGINAL_DB=":memory:"`` (used by validation/benchmark/reproducibility.py's
# lock_environment(), and every validation script built on it, to guarantee no
# cross-*process* store contamination between separate runs) needs a
# different connect string than a real file. Plain ``sqlite3.connect(":memory:")``
# creates a brand-new, anonymous, UNSHARED database on every call — not a
# handle onto one shared database the way a file path is. Since every call
# site uses ``with _get_conn() as conn: ...``, and the context-manager
# protocol on a sqlite3.Connection only manages the transaction
# (commit/rollback) and does NOT close the connection, a fresh-connection-
# per-call policy (correct, and unchanged below, for the file-backed path)
# would make each anonymous in-memory database eligible for GC — and gone —
# right after the call that created it. A write from one call would then be
# invisible to a read from the next.
#
# The fix is SQLite's own named shared-cache URI (``file:<name>?mode=memory&
# cache=shared``, requires ``uri=True``): every ``sqlite3.connect()`` call
# using the same name attaches to the SAME in-memory database, while still
# returning a distinct ``Connection`` object each time — exactly like the
# file-backed path's fresh-connection-per-call shape, just with a different
# connect string. Verified directly (not just documented behavior taken on
# faith): two such connections are `is`-distinct objects, and a completely
# fresh connection opened on another thread — with sqlite3's DEFAULT
# check_same_thread=True, no override needed — immediately sees rows written
# by a different connection. ``mode=memory`` is required on the named form:
# without it, ``file:<name>?cache=shared`` is a relative *file* path, which
# would silently write to disk instead of memory (verified directly).
#
# One wrinkle: a shared-cache in-memory database is destroyed the instant its
# LAST connection closes (same rule that makes plain ":memory:" unshared in
# the first place — SQLite doesn't special-case "shared" out of that). Since
# every caller's connection is short-lived (opened, used, GC'd), the shared
# database would still be destroyed between calls without something holding
# it open. ``_MEMORY_KEEPALIVE_CONN`` is that something: opened once, lazily,
# on first use, held for the life of the process, and never used for queries
# — its only job is to keep at least one handle on the shared-cache database
# open at all times so the real per-call connections below always find it
# already populated with the schema instead of starting fresh empty each time.
#
# ``_MEMORY_GENERATION`` is what makes reset_memory_conn() (below) a *reliable*
# reset rather than a "close the keepalive and hope every other connection
# has already been garbage-collected by the time the next connect() runs"
# best-effort: the shared-cache database's identity is keyed by this name, so
# bumping it hands out a brand-new, guaranteed-empty database on the next
# _get_conn() call regardless of whether some earlier connection is still
# technically alive somewhere. Verified directly: two named shared-cache
# databases with different names are fully independent even while both have
# open connections.
#
# This design needs no lock and no check_same_thread=False on the connection
# it RETURNS to callers: every _get_conn() call — including for ":memory:" now
# — returns a brand-new Connection object used by exactly one caller, identical
# in shape to the file-backed path. (The module-internal keepalive connection
# below IS opened with check_same_thread=False, for the different reason
# explained at its creation site — it is never queried, only held open and
# later closed, possibly from another thread.) There
# is no shared mutable Connection object for two threads to contend over, so
# the earlier design's transaction-flattening hazard (a `with conn:` block on
# one caller's connection committing/rolling back a DIFFERENT caller's
# in-flight transaction, because both callers shared the same connection
# object) is gone: each caller has its own connection now, same as the
# file-backed path always did.
#
# That is NOT the same as saying ":memory:" now supports genuinely concurrent
# store access, though — it does not, and this is a real, currently-latent
# limitation, not a solved problem. Measured directly: two threads (a writer
# holding a write transaction open, and a second connection trying to write
# the same table while the first is mid-transaction) reproduce a "database
# table is locked" OperationalError in ~70 microseconds even with
# busy_timeout=5000 set on both connections — vs. the file-backed WAL path,
# which genuinely waits (~1.8s, until the holder's transaction ends) under
# the identical scenario. SQLite's shared-cache mode enforces its own
# inter-connection *table*-level locking, and that locking bypasses the
# regular busy handler entirely — busy_timeout is measurably inert here, not
# just untested. original/lab/runner.py's background
# ThreadPoolExecutor(max_workers=1) writer thread + a request thread polling
# for status is exactly this shape; it doesn't reach ":memory:" today (no
# validation script drives /lab/), so this is Important, not Critical, but it
# would need solving before ":memory:" could be used anywhere with that kind
# of concurrent access. Candidate directions if that's ever needed —
# evaluate, don't assume: ``PRAGMA read_uncommitted=1`` (relaxes shared-cache
# read isolation, does not by itself fix writer-vs-writer table locking), or
# SQLite's ``vfs=memdb`` (present and connectable on this build, SQLite
# 3.53.1, via ``file:<name>?vfs=memdb&cache=shared`` — whether its locking
# behavior actually differs from plain ``cache=shared`` under concurrent
# writes has not been checked and should not be assumed).
_MEMORY_DB_BASENAME = "original_store_memdb"
_MEMORY_GENERATION = 0
_MEMORY_KEEPALIVE_CONN: sqlite3.Connection | None = None


def _memory_uri() -> str:
    return f"file:{_MEMORY_DB_BASENAME}_{_MEMORY_GENERATION}?mode=memory&cache=shared"


def _init_schema(conn: sqlite3.Connection) -> None:
    """Apply pragmas and the full CREATE-TABLE-IF-NOT-EXISTS ladder to a
    freshly-opened connection. Split out of ``_get_conn()`` so both branches
    (file-backed and ":memory:") share one implementation — both now run this
    on every call, exactly as the original file-backed path always did (cheap
    — all-IF-NOT-EXISTS — and how the WS-1 A1 "corrupt DB fails loudly"
    guarantee is preserved)."""
    # Concurrency hardening for pilot use: WAL allows readers during a write;
    # busy_timeout avoids spurious "database is locked" under parallel requests.
    # On ":memory:" WAL is not a supported mode; SQLite silently falls back to
    # "memory" journal mode instead of erroring (verified directly), so this
    # is harmless there too.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS student_profiles (
            student_id TEXT PRIMARY KEY,
            data       TEXT NOT NULL
        )
    """)
    # Human-readable student display names, kept out of the profile blob so a
    # name can be recorded (at login / LTI launch / import) before any baseline
    # exists. The roster reads from here so a professor sees real names, not the
    # opaque tenant-scoped ids.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS student_names (
            student_id   TEXT PRIMARY KEY,
            display_name TEXT NOT NULL DEFAULT '',
            updated_at   TEXT NOT NULL DEFAULT ''
        )
    """)
    # Phase 5 audit log — every adaptive scoring run with a manifest
    # appends a row here. Lets us inspect which directives fired against
    # which submissions and how that correlated with action/score, so we
    # can tune `_derive_directives` thresholds with real production data.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS submission_manifests (
            submission_id    TEXT PRIMARY KEY,
            student_id       TEXT NOT NULL,
            created_at       TEXT NOT NULL,
            manifest_json    TEXT NOT NULL,
            divergence_score REAL,
            action           TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_manifest_student_created
            ON submission_manifests(student_id, created_at)
    """)
    # PR 7: corrections feedback log — instructors flag whether a verdict
    # was right or wrong and (optionally) supply the corrected label. Used
    # by the retraining job (PR 8) to tune verdict thresholds. Foreign-keys
    # logically to submission_manifests, but SQLite FK enforcement is off
    # by default — we keep the relationship in the indexed lookup.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS corrections (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id            TEXT NOT NULL,
            student_id               TEXT,
            original_verdict         TEXT,
            original_action          TEXT,
            original_divergence_score REAL,
            corrected_verdict        TEXT,
            corrected_action         TEXT,
            is_correct               INTEGER NOT NULL,
            reviewer                 TEXT,
            notes                    TEXT,
            created_at               TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_corrections_submission
            ON corrections(submission_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_corrections_created
            ON corrections(created_at)
    """)
    # PR 8a: calibration runs — every "Run Calibration" click from the lab
    # dashboard appends a row here. report_json carries the full
    # CalibrationReport (ROC points, threshold metrics, per-author stats)
    # so historical comparisons don't need to re-execute calibrations.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS calibration_runs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            run_label        TEXT,
            dataset_label    TEXT NOT NULL,
            started_at       TEXT NOT NULL,
            completed_at     TEXT,
            status           TEXT NOT NULL,
            auc              REAL,
            n_essays_scored  INTEGER,
            n_authors        INTEGER,
            config_json      TEXT,
            report_json      TEXT,
            error            TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_calibration_started
            ON calibration_runs(started_at)
    """)
    # PR 8b: tuned thresholds — every "Apply Suggestions" click writes a
    # new row. The latest row by `created_at` is the active threshold set;
    # in-process scoring reads it on demand. Source can be a calibration
    # run, the corrections feedback loop, or manual override.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tuned_thresholds_v2 (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at         TEXT NOT NULL,
            source             TEXT NOT NULL,
            source_run_id      INTEGER,
            no_action          REAL NOT NULL,
            monitor            REAL NOT NULL,
            escalate           REAL NOT NULL,
            verdict_authentic_below      REAL,
            verdict_anomalous_at_or_above REAL,
            notes              TEXT,
            provenance_json    TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_tuned_thresholds_created
            ON tuned_thresholds_v2(created_at)
    """)
    # Production Phase 6: quantum fidelity scores for conformal calibration.
    # Populated by put_fidelity_score() after each scoring call.  Read by
    # get_authentic_fidelities() at scoring time to build the conformal
    # calibration set.  Grows automatically as instructors confirm verdicts
    # via the corrections feedback loop.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fidelity_scores (
            submission_id    TEXT PRIMARY KEY,
            student_id       TEXT NOT NULL,
            fidelity         REAL NOT NULL,
            is_authentic     INTEGER NOT NULL,
            created_at       TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_fidelity_student
            ON fidelity_scores(student_id, is_authentic)
    """)
    # AI-likelihood shadow scores (second scoring mode). One row per scored
    # submission whenever AI_LIKELIHOOD_SHADOW=1 or AI_LIKELIHOOD_ENABLED=1.
    # In shadow mode this table is the ONLY footprint of the detector —
    # nothing is surfaced to professors — so scripts/shadow_report.py can
    # measure real-world false-positive rates (joined against the
    # instructor-corrected is_authentic labels in fidelity_scores) before
    # any enablement decision. Deliberately a separate table from
    # fidelity_scores: that table is conditionally written (fidelity > 0)
    # and feeds conformal calibration; coupling an unrelated signal to that
    # lifecycle would silently drop rows and pollute the contract.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_likelihood_scores (
            submission_id    TEXT PRIMARY KEY,
            student_id       TEXT NOT NULL,
            probability      REAL NOT NULL,
            band             TEXT NOT NULL,
            model_version    TEXT NOT NULL DEFAULT '',
            created_at       TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_ai_likelihood_student
            ON ai_likelihood_scores(student_id, created_at)
    """)
    # Phase 0 — Tenant registry. Lightweight per-institution metadata that
    # lets us attach environment context (demo / pilot / production) to a
    # student cohort without a Postgres migration. Stored as a JSON blob so
    # new metadata fields can be added without schema changes.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            tenant_id    TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            environment  TEXT NOT NULL DEFAULT 'demo',
            created_at   TEXT NOT NULL,
            meta_json    TEXT NOT NULL DEFAULT '{}'
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_tenants_environment
            ON tenants(environment)
    """)
    # Staff users (professor / admin / operator) for email+password login
    # (ADR-003, Phase 1.x). Students authenticate via student_auth sessions and
    # are NOT stored here. password_hash is a PBKDF2-HMAC-SHA256 string (stdlib,
    # so the demo deployment needs no extra crypto deps). tenant_id ties the
    # user to one institution; operators use a sentinel tenant + 'operator' role.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id       TEXT PRIMARY KEY,
            email         TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role          TEXT NOT NULL DEFAULT 'professor',
            tenant_id     TEXT NOT NULL,
            name          TEXT NOT NULL DEFAULT '',
            created_at    TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_users_tenant
            ON users(tenant_id)
    """)
    # Bluebook examinations (secure-exam layer). Tenant-scoped instructor
    # artifacts: title, course, timing, prompt, and the lockdown conditions.
    # Submissions themselves flow to student_profiles as proctored baselines.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bluebook_exams (
            exam_id         TEXT PRIMARY KEY,
            tenant_id       TEXT NOT NULL,
            title           TEXT NOT NULL,
            course          TEXT,
            duration        INTEGER,
            min_words       INTEGER,
            max_words       INTEGER,
            prompt          TEXT,
            conditions_json TEXT NOT NULL DEFAULT '{}',
            status          TEXT NOT NULL DEFAULT 'DRAFT',
            created_at      TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bluebook_exams_tenant
            ON bluebook_exams(tenant_id, created_at)
    """)
    # Bluebook submissions — one row per sat examination, linked to its exam.
    # Carries the Original-derived integrity reading for the Results view; the
    # prose itself lives in student_profiles (as the proctored baseline sample).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bluebook_submissions (
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
            created_at    TEXT NOT NULL,
            submission_uuid TEXT,
            late          INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bluebook_subs_tenant
            ON bluebook_submissions(tenant_id, created_at)
    """)
    # In-place upgrade for pre-existing DBs (no migration ladder yet —
    # PRAGMA-guarded ALTERs, kept in sync with the fresh CREATE above).
    _sub_cols = {r[1] for r in conn.execute("PRAGMA table_info(bluebook_submissions)")}
    if "submission_uuid" not in _sub_cols:
        conn.execute("ALTER TABLE bluebook_submissions ADD COLUMN submission_uuid TEXT")
    if "late" not in _sub_cols:
        conn.execute("ALTER TABLE bluebook_submissions ADD COLUMN late INTEGER DEFAULT 0")
    # Partial unique index (ADD COLUMN can't carry UNIQUE): seal replays with
    # the same client submission_uuid must not create a second row.
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_bluebook_subs_uuid
            ON bluebook_submissions(submission_uuid)
            WHERE submission_uuid IS NOT NULL
    """)
    # Bluebook sessions — one row per (exam, student) sitting, pinning the
    # immutable server deadline (exam-day robustness spec §1). The first
    # insert wins; reopening the exam can never restart or pause the clock.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bluebook_sessions (
            exam_id     TEXT NOT NULL,
            student_key TEXT NOT NULL,
            tenant_id   TEXT NOT NULL,
            started_at  TEXT NOT NULL,
            deadline_at TEXT NOT NULL,
            PRIMARY KEY (exam_id, student_key)
        )
    """)
    # Bluebook courses — instructor-created, tenant-scoped course records.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bluebook_courses (
            course_id   TEXT PRIMARY KEY,
            tenant_id   TEXT NOT NULL,
            code        TEXT,
            name        TEXT NOT NULL,
            term        TEXT,
            status      TEXT NOT NULL DEFAULT 'ACTIVE',
            created_at  TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bluebook_courses_tenant
            ON bluebook_courses(tenant_id, created_at)
    """)
    # Phase 3 — Audit log. Every significant action (baseline add, score,
    # deletion, correction, threshold apply) appends a row. Used for FERPA
    # compliance reporting, operator oversight, and debugging. The
    # `details_json` blob carries action-specific context (submission_id,
    # provenance, action result) without a schema migration per new field.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at    TEXT NOT NULL,
            action        TEXT NOT NULL,
            student_id    TEXT,
            tenant_id     TEXT,
            actor         TEXT,
            result        TEXT NOT NULL DEFAULT 'ok',
            details_json  TEXT NOT NULL DEFAULT '{}'
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_student
            ON audit_log(student_id, created_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_action
            ON audit_log(action, created_at)
    """)
    # Formation pathways (ADR-002 convergence slice). A pathway is opened when a
    # submission diverges (review opportunity). It advances through three
    # sessions (baseline → formation → verification); completion clears the
    # review flag on the triggering submission. One open pathway per student.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS formation_pathways (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id     TEXT NOT NULL,
            submission_id  TEXT,
            status         TEXT NOT NULL DEFAULT 'open',
            current_step   INTEGER NOT NULL DEFAULT 0,
            reason         TEXT,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_formation_student
            ON formation_pathways(student_id, status)
    """)
    # Proctored baseline requests (durable). Previously in-memory only — a
    # restart dropped every pending request. The full BaselineRequest is
    # stored as a JSON blob; status / student_id / requested_at are promoted
    # to columns for querying without deserialising every row.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS baseline_requests (
            external_request_id TEXT PRIMARY KEY,
            student_id          TEXT NOT NULL,
            status              TEXT NOT NULL,
            requested_at        REAL NOT NULL,
            data_json           TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_baseline_requests_status
            ON baseline_requests(status, requested_at)
    """)
    # QR phone-park (proctoring deterrence). PRIVACY CONTRACT — see
    # docs/STUDENT_DISCLOSURE.md and the park_* functions at the bottom of this
    # module: these two tables hold NO IP, NO user-agent, NO location, NO device
    # fingerprint and NO roster identifier. `student_hint` is free text the
    # student types on their own phone so a proctor can tell tiles apart; it is
    # never one of our student ids and never an email. Rows purge after 24h.
    #
    # Note the absence of the "{tenant}:{local}" scoped student id this schema
    # uses everywhere else: park rows key on an opaque token, so there is
    # deliberately nothing here to join back to a student.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS park_sessions (
            exam_session_id TEXT PRIMARY KEY,
            tenant_id       TEXT NOT NULL,
            park_token      TEXT NOT NULL UNIQUE,
            created_at      TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_park_sessions_created
            ON park_sessions(created_at)
    """)
    # Composite PK (park_token, student_hint) doubles as the park_token index —
    # SQLite uses the leftmost prefix, so no separate index is needed.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS park_beats (
            park_token       TEXT NOT NULL,
            student_hint     TEXT NOT NULL,
            state            TEXT NOT NULL,
            first_seen_at    TEXT NOT NULL,
            last_seen_at     TEXT NOT NULL,
            transitions_json TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY (park_token, student_hint)
        )
    """)
    conn.commit()


def _get_conn() -> sqlite3.Connection:
    if str(_DB_PATH) == ":memory:":
        global _MEMORY_KEEPALIVE_CONN
        if _MEMORY_KEEPALIVE_CONN is None:
            # First touch in this process (or first touch since the last
            # reset_memory_conn()): open the keepalive so the shared-cache
            # database isn't destroyed the moment the very first real
            # (per-call) connection below closes. A harmless, unlocked
            # lazy-init — see the module-level comment above for why a
            # benign duplicate-open race here can't cause data loss (mirrors
            # original/repository.py's unlocked ``_REPO`` singleton).
            #
            # check_same_thread=False here ONLY: this connection never runs a
            # query (its entire lifecycle is "open" then, later, "close" in
            # reset_memory_conn()), so there is no concurrent-query hazard for
            # the default guard to protect against — unlike the per-call
            # connection on the next line, which genuinely is single-owner,
            # single-thread, and keeps the default. Without this, a harness
            # that runs more than one logical "run" in one process (e.g.
            # validation/audits/pooled_calibration_payoff.py, comparing pooled
            # vs. self calibration across two separate TestClient/app
            # instances) hits sqlite3.ProgrammingError the moment
            # reset_memory_conn() is called from a different thread than
            # whichever thread happened to lazily create this connection —
            # FastAPI's TestClient can serve a request on a worker thread
            # distinct from the caller's own. Reproduced and fixed directly;
            # see test_reset_memory_conn_is_safe_from_a_different_thread.
            _MEMORY_KEEPALIVE_CONN = sqlite3.connect(
                _memory_uri(), uri=True, timeout=10.0, check_same_thread=False
            )
        conn = sqlite3.connect(_memory_uri(), uri=True, timeout=10.0)
        _init_schema(conn)
        return conn

    # File-backed path (production default): unchanged fresh-connection-per-
    # call behaviour, exactly as before this fix.
    conn = sqlite3.connect(str(_DB_PATH), timeout=10.0)
    _init_schema(conn)
    return conn


def reset_memory_conn() -> None:
    """Test/script hook: force the next ``:memory:`` ``_get_conn()`` call to
    attach to a genuinely fresh, empty database.

    Mirrors ``original/repository.py``'s ``reset_repository()`` shape ("drop
    the cached singleton, let it rebuild lazily on next use") but lives here
    because the connection state it resets lives here, not in repository.py
    — ``SqliteRepository`` is a stateless pass-through to this module's
    functions and owns no connection of its own to reset.

    Closes the current keepalive connection AND bumps ``_MEMORY_GENERATION``
    so the next database name is one this process has never used before.
    The generation bump (not just closing the keepalive) is what makes this
    a *reliable* reset rather than a "close it and hope every other
    connection from the previous run has already been garbage-collected by
    the time the next connect() runs" best-effort — the old generation's
    database, if anything is still attached to it, is simply abandoned
    rather than raced with.

    Safe to call regardless of the current ``_DB_PATH``: on the file-backed
    path this state is simply unused (that branch of ``_get_conn()`` never
    touches ``_MEMORY_KEEPALIVE_CONN``/``_MEMORY_GENERATION``), so resetting
    it has no observable effect there — it only matters the next time
    ``_DB_PATH`` is ``":memory:"``.

    Deliberately NOT called from ``clear()``: ``clear()``'s contract
    (documented on that function) is an intentional, permanent no-op that
    matches ``PostgresRepository.clear()`` — wiring a real reset in here for
    only the ``:memory:`` case would silently break that parity for anyone
    relying on ``clear()`` doing nothing. This is a separate, explicit,
    opt-in hook.
    """
    global _MEMORY_KEEPALIVE_CONN, _MEMORY_GENERATION
    if _MEMORY_KEEPALIVE_CONN is not None:
        _MEMORY_KEEPALIVE_CONN.close()
        _MEMORY_KEEPALIVE_CONN = None
    _MEMORY_GENERATION += 1


def _serialize(state: StudentState) -> str:
    """Convert StudentState to a JSON string for SQLite storage."""
    samples = [
        {
            "text": s.text,
            "vector": s.vector.tolist(),
            "provenance": s.provenance,
            "auth_weight": s.auth_weight,
            "assignment": s.assignment,
            "submitted_at": s.submitted_at,
            "word_count": s.word_count,
            # Phase 4 context metadata — null-safe for legacy samples that
            # haven't been backfilled yet (caller persists after lazy
            # ensure_sample_context_metadata()).
            "genre": s.genre,
            "topic_centroid": (s.topic_centroid.tolist() if s.topic_centroid is not None else None),
            "context_manifest": s.context_manifest,
            # Tier 17 readiness (additive) — raw Bbook stylemetry blob, or
            # None for legacy/non-keystroke samples. Never used for scoring;
            # only scripts/tier17_report.py reads it back out.
            "keystroke_data": s.keystroke_data,
        }
        for s in state.samples
    ]
    return json.dumps(
        {
            "student_id": state.student_id,
            "samples": samples,
            "baseline_kappa": state.baseline_kappa,
            "kappa_log": state.kappa_log,
            # Phase 8 — drift counter survives restarts so a student who got
            # one outlier today + one outlier next week still triggers
            # rebaseline. Defaults to 0 on legacy rows that predate the field.
            "consecutive_drift_count": state._consecutive_drift_count,
        }
    )


def _deserialize(data: str) -> StudentState:
    """Reconstruct a StudentState from a JSON string."""
    d = json.loads(data)
    state = StudentState(
        student_id=d["student_id"],
        baseline_kappa=d.get("baseline_kappa"),
        kappa_log=d.get("kappa_log", []),
    )
    # Phase 8 — restore drift counter; default 0 for legacy rows.
    state._consecutive_drift_count = int(d.get("consecutive_drift_count", 0))
    for s in d.get("samples", []):
        v = np.array(s["vector"], dtype=np.float64)
        if v.shape[0] != FEATURE_DIM:
            # Stored vector has wrong dimension — e.g. 62 (pre-Tier 8–12 expansion),
            # 74 (pre-Tier 13–15 prosodic expansion), or 90 (pre-Tier 16 citation
            # fingerprint).  Pad with 0.5 (neutral mid-range) for missing
            # dimensions so the density matrix construction doesn't crash.
            # Run `python -m original.cli rebuild-baselines` to re-extract accurately.
            log.warning(
                "Baseline vector for student %s has dimension %d; expected %d. "
                "Padding missing dimensions with 0.5. "
                "Run 'rebuild-baselines' to restore full accuracy.",
                d["student_id"],
                v.shape[0],
                FEATURE_DIM,
            )
            padded = np.full(FEATURE_DIM, 0.5, dtype=np.float64)
            n = min(v.shape[0], FEATURE_DIM)
            padded[:n] = v[:n]
            v = padded
        # Phase 4 context metadata — None for legacy rows; numpy roundtrip
        # for the centroid.
        topic_centroid_raw = s.get("topic_centroid")
        topic_centroid = (
            np.array(topic_centroid_raw, dtype=np.float64)
            if topic_centroid_raw is not None
            else None
        )
        state.samples.append(
            BaselineSample(
                text=s["text"],
                vector=v,
                provenance=s["provenance"],
                auth_weight=s["auth_weight"],
                assignment=s.get("assignment", ""),
                submitted_at=s.get("submitted_at", ""),
                word_count=s.get("word_count"),
                genre=s.get("genre"),
                topic_centroid=topic_centroid,
                context_manifest=s.get("context_manifest"),
                # Tier 17 readiness (additive) — .get() defaults to None for
                # every sample serialized before this field existed.
                keystroke_data=s.get("keystroke_data"),
            )
        )
    return state


# WS-6 P6: the process-global ``_STORE`` cache is gone — every read goes to
# SQLite (read-through), which is what makes ``--workers N`` safe: no worker
# holds private state that another worker's write can silently invalidate.
# The WS-1 A1 guarantee ("an existing-but-corrupt DB must fail loudly, never
# present as empty") is preserved without a hydration step: ``_get_conn()``
# runs the CREATE TABLE ladder on every connect, and on a corrupt/non-DB file
# that itself raises ``sqlite3.DatabaseError`` at the first call site rather
# than any function quietly returning empty results.


def _persist(state: StudentState) -> None:
    """Write one student's state to SQLite (upsert)."""
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO student_profiles (student_id, data) VALUES (?, ?)",
                (state.student_id, _serialize(state)),
            )
    except sqlite3.Error as e:
        log.error("persist failed for student %s: %s", state.student_id, e)
        raise


# ── Public API ────────────────────────────────────────────────────────────────


def get(student_id: str) -> StudentState | None:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT data FROM student_profiles WHERE student_id = ?", (student_id,)
        ).fetchone()
    return _deserialize(row[0]) if row else None


def get_or_create(student_id: str) -> StudentState:
    """Return the stored state, creating (and persisting) an empty one if absent.

    The empty state is persisted immediately — with no in-memory cache, a
    follow-up ``get()`` can only see it via SQLite. Matches
    ``PostgresRepository.get_or_create``'s documented semantics exactly.
    """
    existing = get(student_id)
    if existing is not None:
        return existing
    state = StudentState(student_id=student_id)
    _persist(state)
    return state


def put(state: StudentState) -> None:
    """Persist a full student state (whole-document upsert)."""
    _persist(state)
    # Bust the Bayesian genre-stats cache (keyed on (tenant, genre)) — a new
    # sample may shift the cross-student genre distribution that
    # get_genre_stats() aggregates for whichever tenant this student belongs to.
    _GENRE_STATS_CACHE.clear()


def list_ids() -> list[str]:
    with _get_conn() as conn:
        rows = conn.execute("SELECT student_id FROM student_profiles").fetchall()
    return [r[0] for r in rows]


def all_states() -> list[StudentState]:
    """Every stored StudentState (the impostor-pool builder's input)."""
    with _get_conn() as conn:
        rows = conn.execute("SELECT data FROM student_profiles").fetchall()
    return [_deserialize(r[0]) for r in rows]


def count() -> int:
    with _get_conn() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM student_profiles").fetchone()[0])


def clear() -> None:
    """No-op (WS-6 P6): persisted data always survives ``clear()``.

    Historically cleared the in-memory cache without touching SQLite; with the
    cache gone there is nothing volatile to clear, which converges on
    ``PostgresRepository.clear()``'s documented contract. Deliberately does NOT
    delete rows — ``seed_demo_store()``'s reseed is an idempotent upsert, and a
    ``clear()`` that wiped SQLite would recreate the B16 data-loss footgun.
    """


# ── Phase 5: manifest audit log ──────────────────────────────────────────────


def put_manifest(
    submission_id: str,
    student_id: str,
    manifest: object,  # ContextManifest or its to_dict()
    divergence_score: float | None = None,
    action: str | None = None,
) -> None:
    """
    Append (or replace) a row in the `submission_manifests` audit table.

    Errors are swallowed — the audit log is best-effort and must never
    break the scoring path. The manifest is stored as a JSON string so
    we can `select manifest_json` later without code changes.
    """
    try:
        if hasattr(manifest, "to_json"):
            manifest_json = manifest.to_json()
            created_at = getattr(manifest, "created_at", "") or ""
        elif isinstance(manifest, dict):
            manifest_json = json.dumps(manifest, sort_keys=True)
            created_at = manifest.get("created_at", "") or ""
        else:
            log.warning("put_manifest: unsupported manifest type %r", type(manifest))
            return

        with _get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO submission_manifests
                    (submission_id, student_id, created_at, manifest_json,
                     divergence_score, action)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (submission_id, student_id, created_at, manifest_json, divergence_score, action),
            )
    except Exception as e:
        log.warning("put_manifest failed for %s: %s", submission_id, e)


def submission_student_id(submission_id: str) -> str | None:
    """Resolve the student a submission belongs to (manifest, then score audit).

    Mirrors ``put_correction``'s student back-fill precedence so a caller can
    tenant-scope a correction *before* writing it. Returns None when the
    submission is unknown — no manifest row (manifests are gated behind
    CONTEXT_MANIFEST_ENABLED) and no ``action='score'`` audit row yet.
    """
    m = get_manifest(submission_id)
    if m is not None and m.get("student_id"):
        return str(m["student_id"])
    try:
        with _get_conn() as conn:
            # The pattern matches against the JSON-encoded details_json, so
            # an id containing chars JSON escapes (\ or ") won't match its
            # own row and resolves to None — fail-safe, and ids are locally
            # generated so this doesn't occur in practice.
            row = conn.execute(
                "SELECT student_id FROM audit_log WHERE action = 'score' "
                r"AND details_json LIKE ? ESCAPE '\' ORDER BY created_at DESC LIMIT 1",
                (f'%"submission_id": "{_escape_like(submission_id)}"%',),
            ).fetchone()
            if row is not None and row[0]:
                return str(row[0])
    except Exception:
        pass
    return None


def get_manifest(submission_id: str) -> dict | None:
    """Return the manifest_json + sidecar fields for a submission, or None."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT student_id, created_at, manifest_json, divergence_score, action "
                "FROM submission_manifests WHERE submission_id = ?",
                (submission_id,),
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    return {
        "submission_id": submission_id,
        "student_id": row[0],
        "created_at": row[1],
        "manifest": json.loads(row[2]),
        "divergence_score": row[3],
        "action": row[4],
    }


# ── PR 7: manifest list / stats queries ──────────────────────────────────────


def list_manifests(
    student_id: str | None = None,
    action: str | None = None,
    flag: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """
    Paginated query over the submission_manifests audit table.

    All filters are optional. ``flag`` searches inside the JSON-serialised
    manifest's ``flags`` array — uses LIKE rather than json_extract so we
    don't depend on the SQLite JSON1 extension (not always compiled in on
    macOS Python builds).

    Returns
    -------
    {
        "total":   int,         # rows matching the filter (NOT the page)
        "limit":   int,
        "offset":  int,
        "items":   [
            {
                "submission_id":    str,
                "student_id":       str,
                "created_at":       str,
                "divergence_score": float | None,
                "action":           str | None,
                "flags":            List[str],
                "anchor_tiers":     List[int],
                "length_regime":    str,
            },
            ...
        ],
    }
    """
    where_clauses: list[str] = []
    params: list = []

    if student_id is not None:
        where_clauses.append("student_id = ?")
        params.append(student_id)
    if action is not None:
        where_clauses.append("action = ?")
        params.append(action)
    if since is not None:
        where_clauses.append("created_at >= ?")
        params.append(since)
    if until is not None:
        where_clauses.append("created_at <= ?")
        params.append(until)
    if flag is not None:
        # LIKE against the JSON column. Conservative: matches "flag" anywhere
        # in the JSON string. Good enough for the dashboard's filter UX —
        # collisions are unlikely (flags are short canonical strings).
        where_clauses.append("manifest_json LIKE ?")
        params.append(f'%"{flag}"%')

    where = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    try:
        with _get_conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM submission_manifests{where}",
                params,
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT submission_id, student_id, created_at, manifest_json,
                       divergence_score, action
                FROM submission_manifests
                {where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()
    except Exception as e:
        log.warning("list_manifests failed: %s", e)
        return {"total": 0, "limit": limit, "offset": offset, "items": []}

    items: list[dict] = []
    for row in rows:
        try:
            manifest = json.loads(row[3])
        except Exception:
            manifest = {}
        items.append(
            {
                "submission_id": row[0],
                "student_id": row[1],
                "created_at": row[2],
                "divergence_score": row[4],
                "action": row[5],
                # Stripped-down summary so the list endpoint is cheap to render.
                "flags": list(manifest.get("flags") or []),
                "anchor_tiers": list(manifest.get("anchor_tiers") or []),
                "length_regime": manifest.get("length_regime") or "unknown",
            }
        )

    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "items": items,
    }


def manifest_stats(
    since: str | None = None,
    until: str | None = None,
) -> dict:
    """
    Roll-up counts over the manifest audit table for the dashboard
    summary cards. Uses one pass through the result set rather than N
    separate aggregation queries — manifests are small JSON blobs and
    we expect O(thousands) of rows in normal use.
    """
    where_clauses: list[str] = []
    params: list = []
    if since is not None:
        where_clauses.append("created_at >= ?")
        params.append(since)
    if until is not None:
        where_clauses.append("created_at <= ?")
        params.append(until)
    where = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    by_action: dict[str, int] = {}
    by_flag: dict[str, int] = {}
    by_length_regime: dict[str, int] = {}
    divergence_sum = 0.0
    divergence_n = 0
    total = 0

    try:
        with _get_conn() as conn:
            for row in conn.execute(
                f"SELECT action, manifest_json, divergence_score "
                f"FROM submission_manifests{where}",
                params,
            ):
                total += 1
                action = row[0] or "unknown"
                by_action[action] = by_action.get(action, 0) + 1
                try:
                    m = json.loads(row[1])
                except Exception:
                    m = {}
                for f in m.get("flags") or []:
                    by_flag[f] = by_flag.get(f, 0) + 1
                regime = m.get("length_regime") or "unknown"
                by_length_regime[regime] = by_length_regime.get(regime, 0) + 1
                if row[2] is not None:
                    divergence_sum += float(row[2])
                    divergence_n += 1
    except Exception as e:
        log.warning("manifest_stats failed: %s", e)

    return {
        "total": total,
        "by_action": by_action,
        "by_flag": by_flag,
        "by_length_regime": by_length_regime,
        "mean_divergence": round(divergence_sum / divergence_n, 4) if divergence_n else None,
        "since": since,
        "until": until,
    }


# ── Production Phase 6: quantum fidelity store ───────────────────────────────


def put_fidelity_score(
    submission_id: str,
    student_id: str,
    fidelity: float,
    is_authentic: bool,
) -> None:
    """
    Store a quantum fidelity score for conformal calibration.

    Called by the API layer after scoring when AMPLITUDE_SCORING_ENABLED=1.
    The calibration set grows as instructors confirm verdicts — higher-quality
    data over time → tighter conformal p-values.

    Parameters
    ----------
    submission_id : unique submission identifier
    student_id    : student identifier
    fidelity      : quantum_fidelity score ∈ [0, 1]
    is_authentic  : True if the submission was confirmed authentic
    """
    import datetime

    created_at = datetime.datetime.utcnow().isoformat()
    try:
        with _get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO fidelity_scores
                    (submission_id, student_id, fidelity, is_authentic, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (submission_id, student_id, float(fidelity), 1 if is_authentic else 0, created_at),
            )
            conn.commit()
    except Exception:
        log.exception("put_fidelity_score failed for %s", submission_id)


def get_authentic_fidelities(
    student_id: str,
    limit: int = 200,
) -> list[float]:
    """
    Return the most recent ``limit`` confirmed-authentic fidelity scores
    for a student, for use as the conformal calibration set.

    Sources (merged):
    1. ``fidelity_scores`` table — populated by ``put_fidelity_score()`` when
       a submission is logged as authentic after scoring.
    2. Implicit: the corrections table is NOT queried here for simplicity;
       the API layer should call ``put_fidelity_score(..., is_authentic=True)``
       when an instructor correction confirms authenticity.

    Returns an empty list when the calibration set is empty — callers treat
    this as "no conformal data" and fall back to deviation_score only.
    """
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                """
                SELECT fidelity FROM fidelity_scores
                WHERE student_id = ? AND is_authentic = 1
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (student_id, limit),
            ).fetchall()
            return [float(row[0]) for row in rows]
    except Exception:
        log.exception("get_authentic_fidelities failed for %s", student_id)
        return []


def put_ai_likelihood_score(
    submission_id: str,
    student_id: str,
    probability: float,
    band: str,
    model_version: str = "",
) -> None:
    """
    Persist one AI-likelihood prediction (shadow or enabled mode).

    Mirrors put_fidelity_score: INSERT OR REPLACE (re-scoring the same
    submission_id keeps one row), never raises — persistence failures must
    never break the scoring endpoint.
    """
    import datetime

    created_at = datetime.datetime.utcnow().isoformat()
    try:
        with _get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO ai_likelihood_scores
                    (submission_id, student_id, probability, band,
                     model_version, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    submission_id,
                    student_id,
                    float(probability),
                    str(band),
                    str(model_version),
                    created_at,
                ),
            )
            conn.commit()
    except Exception:
        log.exception("put_ai_likelihood_score failed for %s", submission_id)


def get_ai_likelihood_scores(
    student_id: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """
    Fetch persisted AI-likelihood rows, newest first, optionally filtered by
    student. Used by tests and ops tooling (scripts/shadow_report.py reads
    the DB directly for its joins; this helper is the in-process surface).
    """
    try:
        with _get_conn() as conn:
            if student_id is not None:
                rows = conn.execute(
                    """
                    SELECT submission_id, student_id, probability, band,
                           model_version, created_at
                    FROM ai_likelihood_scores
                    WHERE student_id = ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (student_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT submission_id, student_id, probability, band,
                           model_version, created_at
                    FROM ai_likelihood_scores
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [
                {
                    "submission_id": r[0],
                    "student_id": r[1],
                    "probability": float(r[2]),
                    "band": r[3],
                    "model_version": r[4],
                    "created_at": r[5],
                }
                for r in rows
            ]
    except Exception:
        log.exception("get_ai_likelihood_scores failed")
        return []


# ── Hierarchical Bayesian prior: cross-student genre statistics ───────────────


# Cold-start floors for the genre prior. Both are checked against the pool
# that remains AFTER the scored student's own samples are removed.
#
# MIN_GENRE_VECTORS bounds how many vectors the prior rests on.
# MIN_GENRE_STUDENTS bounds how many *people* — mirroring null_pool.py's
# MIN_IMPOSTOR_STUDENTS. The vector floor alone was enough while the pool
# spanned every tenant, because genre matching bounded concentration on its
# own. Tenant-scoping shrank each pool enough that it no longer does: without
# a distinct-student floor, one prolific student's samples could stand in for
# a whole tenant's "population" prior.
MIN_GENRE_VECTORS = 5
MIN_GENRE_STUDENTS = 3


def get_genre_stats(genre: str, tenant: str | None, exclude_student_id: str | None) -> dict | None:
    """
    Compute cross-student mean, std, and sample count for a writing genre,
    scoped to a single tenant and excluding one student.

    Aggregates feature vectors from confirmed-authentic baseline samples
    (auth_weight > 0) with matching ``sample.genre``, across students in
    ``tenant`` only, skipping ``exclude_student_id`` entirely.  Returns
    ``None`` when what remains clears neither floor — the caller treats this
    as "no prior available" and falls back to the student-only baseline.

    This is the population-level reference distribution used by the
    Hierarchical Bayesian cold-start prior in ``scoring.score()``.

    Tenant scoping mirrors ``original/quantum/null_pool.py``'s
    ``build_impostor_stats``, which resolves ``tenant_of(claimed_student_id)``
    and pools only same-tenant peers: cross-tenant vectors are never pooled,
    the same isolation rule as every other cross-student read here.  Before
    WS-7 this function pooled across every tenant in the store — a
    FERPA-relevant leak of one institution's aggregate writing statistics
    into another institution's scoring.

    Self-exclusion mirrors ``build_impostor_stats`` too, which always drops
    ``claimed_student_id`` from its pool.  A prior containing the scored
    student is partly a blend toward that student's own writing, which damps
    the correction the prior exists to make; tenant-scoping sharpened this,
    since in a small same-tenant pool one student can be a large fraction of
    "their own" prior.

    The exclusion is per ``student_id``, not per person: two accounts for the
    same human (a re-enrolment, or an LTI id that differs from the roster id)
    would still contribute to each other's priors.  Nothing here can detect
    that; don't read the guarantee as stronger than it is.

    The DB read goes through ``all_states()``; the pool is memoised in
    ``_GENRE_STATS_CACHE`` keyed on ``(tenant, genre)`` and busted on every
    ``put()`` / ``delete_student()``.  What is cached is the pool grouped by
    student, not a finished mean/std, so one scan serves every student in the
    cohort and the leave-one-out step is a filter over the cached groups —
    see ``genre_stats_from_groups``.

    Parameters
    ----------
    genre : genre label (e.g. "argumentative_essay", "lab_report")
    tenant : the tenant slug to scope to — ``principal.tenant_of`` of the
        student being scored — or None for the legacy-flat (unscoped) pool,
        which is its own distinct cohort, never mixed with a real tenant's.
    exclude_student_id : the full scoped id of the student being scored,
        dropped from the pool; None pools every student in ``tenant``.

    Returns
    -------
    dict with keys "mean" (np.ndarray), "std" (np.ndarray), "n_samples" (int)
    or None if, after the exclusion, fewer than MIN_GENRE_STUDENTS contributing
    students or fewer than MIN_GENRE_VECTORS matching authentic samples remain
    in that tenant.
    """
    from .constants import GENRE_UNKNOWN

    # GENRE_UNKNOWN is the v2 resolver's abstention, not a genre. Pooling
    # every unclassified sample together would rebuild the "correspondence"
    # dumping ground under a new name — one bucket holding sermons, fiction
    # and lab reports alike — and estimate a "same-genre" prior from an
    # arbitrary mixture. Returning None here means the caller falls back to
    # the student-only baseline, which is the honest answer.
    #
    # Returned explicitly rather than by passing genre=None to _pool_groups:
    # None there means *no genre filter*, i.e. the genre-AGNOSTIC cohort pool
    # behind get_cohort_stats. That would hand back a cross-genre prior under
    # the name of a same-genre one — the exact confusion this guard prevents.
    if genre == GENRE_UNKNOWN:
        return None

    return genre_stats_from_groups(_pool_groups(tenant, genre), exclude_student_id)


def _pool_groups(tenant: str | None, genre: str | None) -> list[tuple[str, list[np.ndarray]]]:
    """The authenticated-sample pool for one ``(tenant, genre)``, grouped by
    student and memoised in ``_GENRE_STATS_CACHE``.

    ``genre=None`` means *no genre filter* — the genre-agnostic cohort pool
    behind ``get_cohort_stats``. One scan, one cache, one busting site for
    both priors, so they cannot drift on tenant scoping the way two
    hand-written scans would.
    """
    # O(1) fast path for the scan — the per-student groups are shared by every
    # student in this (tenant, genre); only the leave-one-out arithmetic in
    # genre_stats_from_groups is per-caller. Cache is busted by put() whenever
    # a baseline is stored.
    key = (tenant, genre)
    groups = _GENRE_STATS_CACHE.get(key)
    if groups is None:
        groups = []
        # Full read-through scan (WS-6 P6): all_states() snapshots the table,
        # so concurrent writers can't perturb the iteration the way the old
        # shared _STORE dict could.
        for student_state in all_states():
            if tenant_of(student_state.student_id) != tenant:
                continue
            student_vectors = [
                sample.vector
                for sample in student_state.samples
                if sample.auth_weight > 0
                and (genre is None or getattr(sample, "genre", None) == genre)
            ]
            if student_vectors:
                groups.append((student_state.student_id, student_vectors))
        _GENRE_STATS_CACHE[key] = groups
    return groups


def genre_stats_from_groups(
    groups: list[tuple[str, list[np.ndarray]]], exclude_student_id: str | None
) -> dict | None:
    """Leave-one-out mean/std over a genre pool grouped by student.

    Split out and shared with ``postgres_repository`` so the two backends
    cannot drift on floor semantics, on which student the exclusion removes,
    or on the order the two are applied (exclusion first, then both floors
    against what remains).

    ``groups`` is ``[(student_id, [vector, ...]), ...]`` and contains only
    students who contributed at least one authenticated same-genre sample —
    so ``len(groups)`` is already the distinct-contributing-student count.
    """
    vectors: list[np.ndarray] = []
    contributing_students = 0
    for student_id, student_vectors in groups:
        if student_id == exclude_student_id:
            continue
        contributing_students += 1
        vectors.extend(student_vectors)

    if contributing_students < MIN_GENRE_STUDENTS or len(vectors) < MIN_GENRE_VECTORS:
        return None

    mat = np.stack(vectors, axis=0)  # shape (N, FEATURE_DIM)
    return {
        "mean": mat.mean(axis=0),  # shape (FEATURE_DIM,)
        # Use the same 0.005 floor as StudentState.baseline_std to keep the
        # prior std compatible with the per-student sigma floor.
        "std": np.maximum(mat.std(axis=0), 0.005),
        "n_samples": len(vectors),
        # How many distinct people the pool represents, post-exclusion.
        # scoring.score() damps the prior's blend weight by this: a mean
        # estimated from 3 peers should not carry the authority of one
        # estimated from 300.
        "n_students": contributing_students,
    }


def get_cohort_stats(tenant: str | None, exclude_student_id: str | None) -> dict | None:
    """
    ``get_genre_stats``'s genre-agnostic sibling: cross-student mean, std and
    counts over EVERY confirmed-authentic baseline sample (auth_weight > 0)
    in ``tenant``, regardless of genre, excluding ``exclude_student_id``.

    Used as the cold-start fallback behind ``COHORT_PRIOR_FALLBACK`` when no
    same-genre prior exists yet for the student being scored.  Deliberately
    the *same* code path as the genre prior with the genre filter dropped
    (``_pool_groups(tenant, None)`` + ``genre_stats_from_groups``), so it
    inherits, rather than re-states, every invariant the genre prior already
    carries:

    * **tenant scoping** — never pools across institutions
      (``build_impostor_stats``'s rule; FERPA-relevant);
    * **leave-one-out** — the scored student is dropped from their own
      prior.  This matters *more* here than for the genre prior, not less:
      a tenant-wide pool in a small tenant is where a student most easily
      dominates "their own" population statistic;
    * **both cold-start floors** — ``MIN_GENRE_STUDENTS`` (3 distinct
      contributing people) and ``MIN_GENRE_VECTORS`` (5 vectors), checked
      after the exclusion.  Dropping the genre filter removes genre
      matching's natural cap on pool concentration, which is exactly why
      the distinct-student floor added for the genre prior is load-bearing
      here;
    * **``n_students``** in the returned dict, which ``scoring.score()``
      uses to damp the prior's blend weight by cohort size.  Without it a
      genre-*mismatched* fallback prior would silently be trusted more than
      a genre-matched one of the same size.

    Parameters
    ----------
    tenant : the tenant slug to scope to — ``principal.tenant_of`` of the
        student being scored — or None for the legacy-flat (unscoped) pool,
        which is its own distinct cohort, never mixed with a real tenant's.
    exclude_student_id : the full scoped id of the student being scored,
        dropped from the pool; None pools every student in ``tenant``.

    Returns
    -------
    Same dict shape as ``get_genre_stats`` — "mean", "std", "n_samples",
    "n_students" — or None when neither floor is cleared post-exclusion.
    """
    return genre_stats_from_groups(_pool_groups(tenant, None), exclude_student_id)


def update_fidelity_authenticity(submission_id: str, is_authentic: bool) -> None:
    """
    Update the ``is_authentic`` flag on an existing fidelity_scores row.

    Called by the corrections endpoint when an instructor's verdict
    overrides the automated authenticity label written at scoring time.
    This is what actually closes the conformal calibration feedback loop:
    real instructor signals → correct is_authentic labels → conformal set
    quality improves over time → tighter p-values.

    Silently no-ops when no fidelity row exists for this submission
    (i.e. AMPLITUDE_SCORING_ENABLED was off when it was scored).
    """
    try:
        with _get_conn() as conn:
            conn.execute(
                "UPDATE fidelity_scores SET is_authentic = ? WHERE submission_id = ?",
                (1 if is_authentic else 0, submission_id),
            )
            conn.commit()
    except Exception:
        log.exception("update_fidelity_authenticity failed for submission %s", submission_id)


def delete_student(student_id: str) -> bool:
    """
    Permanently delete all data for a student (FERPA right-to-erasure).

    Removes the student from:
    - student_profiles      (SQLite — baseline profile)
    - fidelity_scores       (SQLite — conformal calibration data)
    - ai_likelihood_scores  (SQLite — shadow-mode detector rows)
    - submission_manifests  (SQLite — adaptive-context audit log)
    - corrections           (SQLite — instructor feedback, by submission_id
                             to catch rows where student_id was never written)
    - student_names         (SQLite — display name from LTI / roster import)
    - audit_log             (SQLite — the student's action history; the
                             deletion itself is re-logged by the API caller
                             as the single retained deletion receipt)

    Returns True if the student existed and was deleted, False if not found or
    if the SQLite commit failed.
    """
    if get(student_id) is None:
        return False

    try:
        with _get_conn() as conn:
            # Collect submission_ids before deleting manifests so we can
            # purge orphaned corrections rows where student_id was not set
            # (put_correction() auto-fills student_id from the manifest, but
            # the manifest may not have existed at correction time → NULL gap).
            rows = conn.execute(
                "SELECT submission_id FROM submission_manifests WHERE student_id = ?",
                (student_id,),
            ).fetchall()
            sub_ids = [r[0] for r in rows]

            conn.execute("DELETE FROM student_profiles WHERE student_id = ?", (student_id,))
            conn.execute("DELETE FROM fidelity_scores WHERE student_id = ?", (student_id,))
            conn.execute("DELETE FROM ai_likelihood_scores WHERE student_id = ?", (student_id,))
            conn.execute("DELETE FROM submission_manifests WHERE student_id = ?", (student_id,))
            # Delete corrections by student_id AND by submission_id to cover
            # any rows where student_id was left NULL (FERPA completeness).
            conn.execute("DELETE FROM corrections WHERE student_id = ?", (student_id,))
            if sub_ids:
                placeholders = ",".join("?" * len(sub_ids))
                conn.execute(
                    f"DELETE FROM corrections WHERE submission_id IN ({placeholders})",
                    sub_ids,
                )
            # Display name (PII from LTI launches / roster import) and the
            # student's audit-log history both identify the student — purge
            # them too. The caller records ONE fresh audit row for the
            # deletion itself (the deletion receipt), which is disclosed in
            # docs/dpa_template.md §5.3.
            conn.execute("DELETE FROM student_names WHERE student_id = ?", (student_id,))
            conn.execute("DELETE FROM audit_log WHERE student_id = ?", (student_id,))
            conn.commit()
    except Exception:
        log.exception("delete_student failed for %s — no data was removed", student_id)
        return False

    _GENRE_STATS_CACHE.clear()  # this student's tenant's (tenant, genre) entries may include them
    return True


# ── PR 7: corrections feedback log ───────────────────────────────────────────


def put_correction(
    submission_id: str,
    is_correct: bool,
    *,
    student_id: str | None = None,
    original_verdict: str | None = None,
    original_action: str | None = None,
    original_divergence_score: float | None = None,
    corrected_verdict: str | None = None,
    corrected_action: str | None = None,
    reviewer: str | None = None,
    notes: str | None = None,
    created_at: str | None = None,
) -> int | None:
    """
    Append a correction row. ``is_correct`` is the simplest signal — even
    without a corrected_verdict, "this was wrong" is useful labelled data
    for retraining (PR 8).

    Returns the inserted row id, or None on failure.

    Auto-fills ``original_*`` fields from the manifest audit log when the
    caller doesn't supply them — saves the dashboard from a separate
    lookup round-trip.
    """
    from datetime import datetime

    if created_at is None:
        created_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Auto-fill from manifest if available and not provided.
    if (
        original_verdict is None
        or original_action is None
        or original_divergence_score is None
        or student_id is None
    ):
        existing = get_manifest(submission_id)
        if existing is not None:
            student_id = student_id or existing.get("student_id")
            original_action = original_action or existing.get("action")
            if original_divergence_score is None:
                original_divergence_score = existing.get("divergence_score")
            # Verdict is not in the audit table (it's in the report), so
            # we leave it None unless explicitly provided. The retraining
            # job can re-derive verdict from divergence_score + the same
            # threshold table that was active at scoring time.

    if student_id is None:
        # Manifests are gated behind CONTEXT_MANIFEST_ENABLED and often
        # empty even when the flag is on; the audit_log's unconditional
        # "score" row for this submission always carries student_id — fall
        # back to it so a correction can still be found per-student without
        # that flag (see /admin/audit's own action=score entries).
        try:
            with _get_conn() as conn:
                row = conn.execute(
                    "SELECT student_id FROM audit_log WHERE action = 'score' "
                    r"AND details_json LIKE ? ESCAPE '\' ORDER BY created_at DESC LIMIT 1",
                    (f'%"submission_id": "{_escape_like(submission_id)}"%',),
                ).fetchone()
                if row is not None:
                    student_id = row[0]
        except Exception:
            pass

    try:
        with _get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO corrections (
                    submission_id, student_id,
                    original_verdict, original_action, original_divergence_score,
                    corrected_verdict, corrected_action,
                    is_correct, reviewer, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    submission_id,
                    student_id,
                    original_verdict,
                    original_action,
                    original_divergence_score,
                    corrected_verdict,
                    corrected_action,
                    1 if is_correct else 0,
                    reviewer,
                    notes,
                    created_at,
                ),
            )
            return int(cur.lastrowid)
    except Exception as e:
        log.warning("put_correction failed for %s: %s", submission_id, e)
        return None


def list_corrections(
    submission_id: str | None = None,
    student_id: str | None = None,
    is_correct: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List corrections with optional filters."""
    where_clauses: list[str] = []
    params: list = []
    if submission_id is not None:
        where_clauses.append("submission_id = ?")
        params.append(submission_id)
    if student_id is not None:
        where_clauses.append("student_id = ?")
        params.append(student_id)
    if is_correct is not None:
        where_clauses.append("is_correct = ?")
        params.append(1 if is_correct else 0)
    where = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    try:
        with _get_conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM corrections{where}",
                params,
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT id, submission_id, student_id,
                       original_verdict, original_action, original_divergence_score,
                       corrected_verdict, corrected_action,
                       is_correct, reviewer, notes, created_at
                FROM corrections
                {where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()
    except Exception as e:
        log.warning("list_corrections failed: %s", e)
        return {"total": 0, "limit": limit, "offset": offset, "items": []}

    items: list[dict] = []
    for r in rows:
        items.append(
            {
                "id": r[0],
                "submission_id": r[1],
                "student_id": r[2],
                "original_verdict": r[3],
                "original_action": r[4],
                "original_divergence_score": r[5],
                "corrected_verdict": r[6],
                "corrected_action": r[7],
                "is_correct": bool(r[8]),
                "reviewer": r[9],
                "notes": r[10],
                "created_at": r[11],
            }
        )

    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "items": items,
    }


# ── PR 8a: calibration runs ──────────────────────────────────────────────────


def start_calibration_run(
    dataset_label: str,
    run_label: str | None = None,
    config: dict | None = None,
) -> int | None:
    """
    Insert a `running` row and return its row id. The lab UI polls
    ``get_calibration_run`` until status flips to `completed` or `failed`.
    """
    from datetime import datetime

    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with _get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO calibration_runs (
                    run_label, dataset_label, started_at, status, config_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (run_label, dataset_label, started_at, "running", json.dumps(config or {})),
            )
            return int(cur.lastrowid)
    except Exception as e:
        log.warning("start_calibration_run failed: %s", e)
        return None


def complete_calibration_run(
    run_id: int,
    *,
    auc: float,
    n_essays_scored: int,
    n_authors: int,
    report: dict,
) -> bool:
    """Mark a run completed and store the full report."""
    from datetime import datetime

    completed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with _get_conn() as conn:
            conn.execute(
                """
                UPDATE calibration_runs
                SET status='completed', completed_at=?, auc=?,
                    n_essays_scored=?, n_authors=?, report_json=?
                WHERE id=?
                """,
                (
                    completed_at,
                    float(auc),
                    int(n_essays_scored),
                    int(n_authors),
                    json.dumps(report),
                    run_id,
                ),
            )
            return True
    except Exception as e:
        log.warning("complete_calibration_run %d failed: %s", run_id, e)
        return False


def fail_calibration_run(run_id: int, error: str) -> bool:
    """Mark a run failed and capture the exception message."""
    from datetime import datetime

    completed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with _get_conn() as conn:
            conn.execute(
                """
                UPDATE calibration_runs
                SET status='failed', completed_at=?, error=?
                WHERE id=?
                """,
                (completed_at, str(error)[:2000], run_id),
            )
            return True
    except Exception as e:
        log.warning("fail_calibration_run %d failed: %s", run_id, e)
        return False


def list_calibration_runs(
    status: str | None = None,
    dataset_label: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List calibration runs (newest first), with optional filters."""
    where_clauses: list[str] = []
    params: list = []
    if status is not None:
        where_clauses.append("status = ?")
        params.append(status)
    if dataset_label is not None:
        where_clauses.append("dataset_label = ?")
        params.append(dataset_label)
    where = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    try:
        with _get_conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM calibration_runs{where}",
                params,
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT id, run_label, dataset_label, started_at, completed_at,
                       status, auc, n_essays_scored, n_authors, error
                FROM calibration_runs
                {where}
                ORDER BY started_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()
    except Exception as e:
        log.warning("list_calibration_runs failed: %s", e)
        return {"total": 0, "limit": limit, "offset": offset, "items": []}

    items: list[dict] = []
    for r in rows:
        items.append(
            {
                "id": r[0],
                "run_label": r[1],
                "dataset_label": r[2],
                "started_at": r[3],
                "completed_at": r[4],
                "status": r[5],
                "auc": r[6],
                "n_essays_scored": r[7],
                "n_authors": r[8],
                "error": r[9],
            }
        )
    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "items": items,
    }


def get_calibration_run(run_id: int, include_report: bool = True) -> dict | None:
    """Fetch one run; ``include_report=False`` skips the heavy JSON column."""
    cols = (
        "id, run_label, dataset_label, started_at, completed_at, status, "
        "auc, n_essays_scored, n_authors, config_json, error"
    )
    if include_report:
        cols += ", report_json"
    try:
        with _get_conn() as conn:
            row = conn.execute(
                f"SELECT {cols} FROM calibration_runs WHERE id=?",
                (run_id,),
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    out = {
        "id": row[0],
        "run_label": row[1],
        "dataset_label": row[2],
        "started_at": row[3],
        "completed_at": row[4],
        "status": row[5],
        "auc": row[6],
        "n_essays_scored": row[7],
        "n_authors": row[8],
        "config": json.loads(row[9] or "{}"),
        "error": row[10],
    }
    if include_report:
        try:
            out["report"] = json.loads(row[11] or "{}")
        except Exception:
            out["report"] = {}
    return out


# ── PR 8b: tuned thresholds (versioned) ──────────────────────────────────────


def put_tuned_thresholds(
    *,
    no_action: float,
    monitor: float,
    escalate: float,
    source: str,
    source_run_id: int | None = None,
    verdict_authentic_below: float | None = None,
    verdict_anomalous_at_or_above: float | None = None,
    notes: str | None = None,
    provenance: dict | None = None,
) -> int | None:
    """
    Append a new active-thresholds row. The latest row (by ``created_at``)
    is the active set; older rows are preserved for audit. ``source`` is
    one of {"manual", "calibration_run", "correction_retrain"}.
    """
    from datetime import datetime

    created_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with _get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO tuned_thresholds_v2 (
                    created_at, source, source_run_id,
                    no_action, monitor, escalate,
                    verdict_authentic_below, verdict_anomalous_at_or_above,
                    notes, provenance_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    source,
                    source_run_id,
                    float(no_action),
                    float(monitor),
                    float(escalate),
                    verdict_authentic_below,
                    verdict_anomalous_at_or_above,
                    notes,
                    json.dumps(provenance or {}),
                ),
            )
            return int(cur.lastrowid)
    except Exception as e:
        log.warning("put_tuned_thresholds failed: %s", e)
        return None


def get_active_tuned_thresholds() -> dict | None:
    """Most-recent row in ``tuned_thresholds_v2`` (the in-effect active set)."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                """
                SELECT id, created_at, source, source_run_id,
                       no_action, monitor, escalate,
                       verdict_authentic_below, verdict_anomalous_at_or_above,
                       notes, provenance_json
                FROM tuned_thresholds_v2
                ORDER BY created_at DESC
                LIMIT 1
                """,
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    return {
        "id": row[0],
        "created_at": row[1],
        "source": row[2],
        "source_run_id": row[3],
        "no_action": row[4],
        "monitor": row[5],
        "escalate": row[6],
        "verdict_authentic_below": row[7],
        "verdict_anomalous_at_or_above": row[8],
        "notes": row[9],
        "provenance": json.loads(row[10] or "{}"),
    }


def list_tuned_thresholds(limit: int = 50, offset: int = 0) -> dict:
    """Audit list of historical threshold sets."""
    try:
        with _get_conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM tuned_thresholds_v2",
            ).fetchone()[0]
            rows = conn.execute(
                """
                SELECT id, created_at, source, source_run_id,
                       no_action, monitor, escalate,
                       verdict_authentic_below, verdict_anomalous_at_or_above,
                       notes
                FROM tuned_thresholds_v2
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
    except Exception:
        return {"total": 0, "limit": limit, "offset": offset, "items": []}
    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": r[0],
                "created_at": r[1],
                "source": r[2],
                "source_run_id": r[3],
                "no_action": r[4],
                "monitor": r[5],
                "escalate": r[6],
                "verdict_authentic_below": r[7],
                "verdict_anomalous_at_or_above": r[8],
                "notes": r[9],
            }
            for r in rows
        ],
    }


# ── Tenant registry (Phase 0) ─────────────────────────────────────────────────
# Lightweight per-institution metadata. Backed by the same SQLite DB as
# student profiles. Environment can be 'demo', 'pilot', or 'production'.
# meta_json carries arbitrary key/value pairs (contact email, Canvas URL, etc.)
# without schema migrations as needs evolve.


def put_tenant(
    tenant_id: str,
    name: str,
    environment: str = "demo",
    meta: dict | None = None,
) -> None:
    """
    Upsert a tenant record.

    Args:
        tenant_id:   Stable identifier (e.g. slug like 'seminary-of-dallas').
        name:        Human-readable institution name.
        environment: One of 'demo', 'pilot', 'production'. Defaults to 'demo'.
        meta:        Optional dict of arbitrary metadata (contact, LMS URL, etc.).
    """
    created_at = datetime.now(UTC).isoformat()
    meta_json = json.dumps(meta or {})
    try:
        with _get_conn() as conn:
            conn.execute(
                """INSERT INTO tenants (tenant_id, name, environment, created_at, meta_json)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(tenant_id) DO UPDATE SET
                     name        = excluded.name,
                     environment = excluded.environment,
                     meta_json   = excluded.meta_json""",
                (tenant_id, name, environment, created_at, meta_json),
            )
            conn.commit()
    except Exception:
        log.exception("put_tenant failed for %s", tenant_id)


def get_tenant(tenant_id: str) -> dict | None:
    """Return tenant dict or None if not found."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT tenant_id, name, environment, created_at, meta_json "
                "FROM tenants WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "tenant_id": row[0],
            "name": row[1],
            "environment": row[2],
            "created_at": row[3],
            "meta": json.loads(row[4] or "{}"),
        }
    except Exception:
        log.exception("get_tenant failed for %s", tenant_id)
        return None


def put_user(
    user_id: str,
    email: str,
    password_hash: str,
    role: str,
    tenant_id: str,
    name: str = "",
) -> None:
    """Upsert a staff user (professor / admin / operator). Email is unique."""
    created_at = datetime.now(UTC).isoformat()
    try:
        with _get_conn() as conn:
            conn.execute(
                """INSERT INTO users
                   (user_id, email, password_hash, role, tenant_id, name, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     email         = excluded.email,
                     password_hash = excluded.password_hash,
                     role          = excluded.role,
                     tenant_id     = excluded.tenant_id,
                     name          = excluded.name""",
                (user_id, email.strip().lower(), password_hash, role, tenant_id, name, created_at),
            )
            conn.commit()
    except Exception:
        log.exception("put_user failed for %s", email)


def get_user_by_email(email: str) -> dict | None:
    """Return the user dict (including password_hash) or None."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT user_id, email, password_hash, role, tenant_id, name, created_at "
                "FROM users WHERE email = ?",
                (email.strip().lower(),),
            ).fetchone()
        if not row:
            return None
        return {
            "user_id": row[0],
            "email": row[1],
            "password_hash": row[2],
            "role": row[3],
            "tenant_id": row[4],
            "name": row[5],
            "created_at": row[6],
        }
    except Exception:
        log.exception("get_user_by_email failed for %s", email)
        return None


def _bluebook_exam_to_dict(row) -> dict:
    return {
        "id": row[0],
        "tenant_id": row[1],
        "title": row[2],
        "course": row[3],
        "duration": row[4],
        "minWords": row[5],
        "maxWords": row[6],
        "prompt": row[7],
        "conditions": json.loads(row[8] or "{}"),
        "status": row[9],
        "submissions": 0,
        "created_at": row[10],
    }


def put_bluebook_exam(rec: dict) -> None:
    """Upsert a Bluebook exam. `rec` carries id, tenant_id, title, course,
    duration, minWords, maxWords, prompt, conditions (dict), status."""
    created_at = datetime.now(UTC).isoformat()
    try:
        with _get_conn() as conn:
            conn.execute(
                """INSERT INTO bluebook_exams
                     (exam_id, tenant_id, title, course, duration, min_words,
                      max_words, prompt, conditions_json, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(exam_id) DO UPDATE SET
                     title=excluded.title, course=excluded.course,
                     duration=excluded.duration, min_words=excluded.min_words,
                     max_words=excluded.max_words, prompt=excluded.prompt,
                     conditions_json=excluded.conditions_json, status=excluded.status""",
                (
                    rec["id"],
                    rec["tenant_id"],
                    rec["title"],
                    rec.get("course", ""),
                    rec.get("duration"),
                    rec.get("minWords"),
                    rec.get("maxWords"),
                    rec.get("prompt", ""),
                    json.dumps(rec.get("conditions") or {}),
                    rec.get("status", "DRAFT"),
                    created_at,
                ),
            )
            conn.commit()
    except sqlite3.Error as e:
        log.error("put_bluebook_exam failed for %s: %s", rec.get("id"), e)
        raise


def get_bluebook_exam(exam_id: str) -> dict | None:
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT exam_id, tenant_id, title, course, duration, min_words, "
                "max_words, prompt, conditions_json, status, created_at "
                "FROM bluebook_exams WHERE exam_id = ?",
                (exam_id,),
            ).fetchone()
        return _bluebook_exam_to_dict(row) if row else None
    except Exception:
        log.exception("get_bluebook_exam failed for %s", exam_id)
        return None


def list_bluebook_exams(tenant_id: str | None) -> list[dict]:
    """List exams for a tenant, or all when tenant_id is None (operator view)."""
    try:
        with _get_conn() as conn:
            if tenant_id is None:
                rows = conn.execute(
                    "SELECT exam_id, tenant_id, title, course, duration, min_words, "
                    "max_words, prompt, conditions_json, status, created_at "
                    "FROM bluebook_exams ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT exam_id, tenant_id, title, course, duration, min_words, "
                    "max_words, prompt, conditions_json, status, created_at "
                    "FROM bluebook_exams WHERE tenant_id = ? ORDER BY created_at DESC",
                    (tenant_id,),
                ).fetchall()
        return [_bluebook_exam_to_dict(r) for r in rows]
    except Exception:
        log.exception("list_bluebook_exams failed for %s", tenant_id)
        return []


def _bluebook_sub_to_dict(row) -> dict:
    sid = row[3] or ""
    return {
        "id": row[0],
        "exam_id": row[1],
        "tenant_id": row[2],
        "student_id": sid,
        "student": row[4] or "Candidate",
        "candidateId": (sid.split(":")[-1][:6] if ":" in sid else (sid[:6] or "—")),
        "candidate": row[4],
        "exam": row[5] or "",
        "course": row[6] or "",
        "words": row[7] or 0,
        "timeMin": row[8] or 0,
        "stylometric": row[9],
        "aiScore": row[10],
        "status": row[11],
        "created_at": row[12],
        "submission_uuid": row[13],
        "late": row[14] or 0,
    }


def put_bluebook_submission(rec: dict) -> None:
    created_at = datetime.now(UTC).isoformat()
    try:
        with _get_conn() as conn:
            conn.execute(
                """INSERT INTO bluebook_submissions
                     (submission_id, exam_id, tenant_id, student_id, candidate,
                      exam_title, course, word_count, time_min, stylometric,
                      ai_score, status, created_at, submission_uuid, late)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    rec["id"],
                    rec.get("exam_id"),
                    rec["tenant_id"],
                    rec.get("student_id"),
                    rec.get("candidate"),
                    rec.get("exam_title"),
                    rec.get("course"),
                    rec.get("word_count"),
                    rec.get("time_min"),
                    rec.get("stylometric"),
                    rec.get("ai_score"),
                    rec.get("status", "SUBMITTED"),
                    created_at,
                    rec.get("submission_uuid"),
                    rec.get("late", 0),
                ),
            )
            conn.commit()
    except sqlite3.Error as e:
        log.error("put_bluebook_submission failed for %s: %s", rec.get("id"), e)
        raise


def list_bluebook_submissions(tenant_id: str | None) -> list[dict]:
    cols = (
        "submission_id, exam_id, tenant_id, student_id, candidate, exam_title, "
        "course, word_count, time_min, stylometric, ai_score, status, created_at, "
        "submission_uuid, late"
    )
    try:
        with _get_conn() as conn:
            if tenant_id is None:
                rows = conn.execute(
                    f"SELECT {cols} FROM bluebook_submissions ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {cols} FROM bluebook_submissions WHERE tenant_id = ? "
                    "ORDER BY created_at DESC",
                    (tenant_id,),
                ).fetchall()
        return [_bluebook_sub_to_dict(r) for r in rows]
    except Exception:
        log.exception("list_bluebook_submissions failed for %s", tenant_id)
        return []


def get_bluebook_submission_by_uuid(submission_uuid: str) -> dict | None:
    """Replay lookup for idempotent sealing: a retried seal with the same
    client submission_uuid gets the prior row back instead of a second write."""
    cols = (
        "submission_id, exam_id, tenant_id, student_id, candidate, exam_title, "
        "course, word_count, time_min, stylometric, ai_score, status, created_at, "
        "submission_uuid, late"
    )
    try:
        with _get_conn() as conn:
            row = conn.execute(
                f"SELECT {cols} FROM bluebook_submissions WHERE submission_uuid = ?",
                (submission_uuid,),
            ).fetchone()
        return _bluebook_sub_to_dict(row) if row else None
    except Exception:
        log.exception("get_bluebook_submission_by_uuid failed for %s", submission_uuid)
        return None


def get_or_create_bluebook_session(
    exam_id: str, student_key: str, tenant_id: str, duration_seconds: int
) -> dict:
    """Idempotent per-(exam, student) session: the first call pins started_at/
    deadline_at; every later call returns the same row unchanged, so reopening
    the exam can never restart or pause the clock (robustness spec §1)."""
    now = datetime.now(UTC)
    started_at = now.isoformat()
    deadline_at = (now + timedelta(seconds=int(duration_seconds))).isoformat()
    try:
        with _get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO bluebook_sessions
                     (exam_id, student_key, tenant_id, started_at, deadline_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(exam_id, student_key) DO NOTHING""",
                (exam_id, student_key, tenant_id, started_at, deadline_at),
            )
            created = cur.rowcount == 1
            conn.commit()
            row = conn.execute(
                "SELECT exam_id, student_key, tenant_id, started_at, deadline_at "
                "FROM bluebook_sessions WHERE exam_id = ? AND student_key = ?",
                (exam_id, student_key),
            ).fetchone()
        return {
            "exam_id": row[0],
            "student_key": row[1],
            "tenant_id": row[2],
            "started_at": row[3],
            "deadline_at": row[4],
            "created": created,
        }
    except sqlite3.Error as e:
        log.error("get_or_create_bluebook_session failed for %s/%s: %s", exam_id, student_key, e)
        raise


def get_bluebook_session(exam_id: str, student_key: str) -> dict | None:
    """Read-only session lookup (late-tagging at seal time). None when the
    sitting was never registered (degrade-open client start)."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT exam_id, student_key, tenant_id, started_at, deadline_at "
                "FROM bluebook_sessions WHERE exam_id = ? AND student_key = ?",
                (exam_id, student_key),
            ).fetchone()
        if row is None:
            return None
        return {
            "exam_id": row[0],
            "student_key": row[1],
            "tenant_id": row[2],
            "started_at": row[3],
            "deadline_at": row[4],
        }
    except Exception:
        log.exception("get_bluebook_session failed for %s/%s", exam_id, student_key)
        return None


def _bluebook_course_to_dict(row) -> dict:
    return {
        "id": row[0],
        "tenant_id": row[1],
        "code": row[2],
        "name": row[3],
        "term": row[4],
        "status": row[5],
        "active": (row[5] or "").upper() == "ACTIVE",
        "students": 0,
        "exams": 0,
        "created_at": row[6],
    }


def put_bluebook_course(rec: dict) -> None:
    created_at = datetime.now(UTC).isoformat()
    try:
        with _get_conn() as conn:
            conn.execute(
                """INSERT INTO bluebook_courses
                     (course_id, tenant_id, code, name, term, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(course_id) DO UPDATE SET
                     code=excluded.code, name=excluded.name,
                     term=excluded.term, status=excluded.status""",
                (
                    rec["id"],
                    rec["tenant_id"],
                    rec.get("code", ""),
                    rec["name"],
                    rec.get("term", ""),
                    rec.get("status", "ACTIVE"),
                    created_at,
                ),
            )
            conn.commit()
    except sqlite3.Error as e:
        log.error("put_bluebook_course failed for %s: %s", rec.get("id"), e)
        raise


def list_bluebook_courses(tenant_id: str | None) -> list[dict]:
    cols = "course_id, tenant_id, code, name, term, status, created_at"
    try:
        with _get_conn() as conn:
            if tenant_id is None:
                rows = conn.execute(
                    f"SELECT {cols} FROM bluebook_courses ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {cols} FROM bluebook_courses WHERE tenant_id = ? "
                    "ORDER BY created_at DESC",
                    (tenant_id,),
                ).fetchall()
        return [_bluebook_course_to_dict(r) for r in rows]
    except Exception:
        log.exception("list_bluebook_courses failed for %s", tenant_id)
        return []


def list_tenants(environment: str | None = None) -> list[dict]:
    """
    List all tenants, optionally filtered by environment.

    Args:
        environment: If given, return only tenants matching this environment
                     ('demo', 'pilot', 'production').
    """
    try:
        with _get_conn() as conn:
            if environment:
                rows = conn.execute(
                    "SELECT tenant_id, name, environment, created_at, meta_json "
                    "FROM tenants WHERE environment = ? ORDER BY created_at",
                    (environment,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT tenant_id, name, environment, created_at, meta_json "
                    "FROM tenants ORDER BY created_at"
                ).fetchall()
        return [
            {
                "tenant_id": r[0],
                "name": r[1],
                "environment": r[2],
                "created_at": r[3],
                "meta": json.loads(r[4] or "{}"),
            }
            for r in rows
        ]
    except Exception:
        log.exception("list_tenants failed")
        return []


# ── Audit log (Phase 3) ───────────────────────────────────────────────────────
# Best-effort append-only log of significant system actions. Never raises —
# audit failure must not break the hot path (scoring, baseline ingest, etc.).


def log_audit(
    action: str,
    student_id: str | None = None,
    tenant_id: str | None = None,
    actor: str | None = None,
    result: str = "ok",
    details: dict | None = None,
) -> None:
    """
    Append one row to the audit log.

    Args:
        action:     Short verb describing what happened.
                    Conventional values:
                    'baseline_add', 'score', 'student_delete', 'correction',
                    'threshold_apply', 'tenant_register', 'bulk_delete'.
        student_id: Affected student (None for system-wide actions).
        tenant_id:  Institution the action belongs to (derived from
                    student_id prefix when omitted).
        actor:      IP address, user email, or service name — whoever
                    triggered the action.
        result:     'ok' | 'error' | 'not_found'.
        details:    Arbitrary key/value dict (submission_id, provenance, etc.).
    """
    try:
        # Auto-derive tenant_id from student_id prefix (e.g. 'seminary:marcus' → 'seminary')
        if tenant_id is None and student_id and ":" in student_id:
            tenant_id = student_id.split(":", 1)[0]

        with _get_conn() as conn:
            conn.execute(
                """INSERT INTO audit_log
                   (created_at, action, student_id, tenant_id, actor, result, details_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(UTC).isoformat(),
                    action,
                    student_id,
                    tenant_id,
                    actor,
                    result,
                    json.dumps(details or {}),
                ),
            )
            conn.commit()
    except Exception:
        log.exception("log_audit silently failed for action=%s student=%s", action, student_id)


def list_audit(
    student_id: str | None = None,
    action: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """
    Query audit log entries. All filters are optional AND-combined.

    Args:
        student_id: Filter to this student's actions.
        action:     Filter to this action type.
        limit:      Max rows (cap 1000).
        offset:     Pagination offset.
    """
    limit = min(limit, 1000)
    try:
        with _get_conn() as conn:
            clauses, params = [], []
            if student_id:
                clauses.append("student_id = ?")
                params.append(student_id)
            if action:
                clauses.append("action = ?")
                params.append(action)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            total = conn.execute(f"SELECT COUNT(*) FROM audit_log {where}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT id, created_at, action, student_id, tenant_id, actor, result, "
                f"details_json FROM audit_log {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
        return {
            "total": int(total),
            "limit": limit,
            "offset": offset,
            "items": [
                {
                    "id": r[0],
                    "created_at": r[1],
                    "action": r[2],
                    "student_id": r[3],
                    "tenant_id": r[4],
                    "actor": r[5],
                    "result": r[6],
                    "details": json.loads(r[7] or "{}"),
                }
                for r in rows
            ],
        }
    except Exception:
        log.exception("list_audit failed")
        return {"total": 0, "limit": limit, "offset": offset, "items": []}


# ── Phase 2: Tenant-scoped student operations ─────────────────────────────────
# Student IDs for tenant-scoped deployments use the convention
# "{tenant_id}:{local_id}" (e.g. "seminary-dallas:marcus_whitfield").
# These helpers filter the existing flat store by prefix, enabling
# per-institution dashboards and bulk operations without a schema change.


def list_ids_for_tenant(tenant_id: str) -> list[str]:
    """
    Return all student IDs that belong to a given tenant (prefix match).

    Works with both the naming convention `{tenant_id}:{local_id}` and
    unscoped IDs (for backward compatibility, unscoped students are omitted).
    Python ``startswith`` on the id list, not SQL LIKE — exact by construction,
    no wildcard-escaping concern (see tenant_stats for the LIKE-escaped case).
    """
    prefix = f"{tenant_id}:"
    return [sid for sid in list_ids() if sid.startswith(prefix)]


# ── Student display names + roster ────────────────────────────────────────────


def set_display_name(student_id: str, name: str) -> None:
    """Record a human-readable display name for a student (best-effort, upsert).

    A blank name never overwrites an existing one, so a later anonymous touch
    can't wipe a real name captured at login.
    """
    name = (name or "").strip()
    if not name:
        return
    now = datetime.now(UTC).isoformat()
    try:
        with _get_conn() as conn:
            conn.execute(
                """INSERT INTO student_names (student_id, display_name, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(student_id) DO UPDATE SET
                     display_name = excluded.display_name,
                     updated_at   = excluded.updated_at""",
                (student_id, name, now),
            )
            conn.commit()
    except Exception:
        log.exception("set_display_name failed for %s", student_id)


def get_display_name(student_id: str) -> str:
    """Return the stored display name for a student, or '' if none."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT display_name FROM student_names WHERE student_id = ?",
                (student_id,),
            ).fetchone()
        return row[0] if row and row[0] else ""
    except Exception:
        return ""


def _display_names_for(student_ids: list[str]) -> dict[str, str]:
    """Bulk-fetch display names for a set of student ids."""
    if not student_ids:
        return {}
    try:
        with _get_conn() as conn:
            qmarks = ",".join("?" for _ in student_ids)
            rows = conn.execute(
                f"SELECT student_id, display_name FROM student_names "
                f"WHERE student_id IN ({qmarks})",
                student_ids,
            ).fetchall()
        return {r[0]: r[1] for r in rows if r[1]}
    except Exception:
        return {}


def _latest_actions_for(student_ids: list[str]) -> dict[str, str]:
    """Most-recent scoring action per student (for roster status)."""
    if not student_ids:
        return {}
    try:
        with _get_conn() as conn:
            qmarks = ",".join("?" for _ in student_ids)
            rows = conn.execute(
                f"""SELECT student_id, action FROM submission_manifests
                    WHERE student_id IN ({qmarks})
                    ORDER BY created_at ASC""",
                student_ids,
            ).fetchall()
        # ASC so the last write per student wins → most recent action.
        latest: dict[str, str] = {}
        for sid, action in rows:
            if action:
                latest[sid] = action
        return latest
    except Exception:
        return {}


def _status_for(sample_count: int, action: str | None) -> str:
    """Roster status label from baseline count + latest action."""
    if sample_count <= 0:
        return "no_baseline"
    if action in ("escalate", "schedule_conversation"):
        return "needs_review"
    if action == "monitor":
        return "monitor"
    return "clear"


def roster_for_tenant(tenant_id: str) -> list[dict]:
    """A display-ready roster for one tenant: name, baseline counts, status.

    This is what the professor/admin dashboards render — real names instead of
    the opaque tenant-scoped ids, so the logged-in product is actually usable.
    """
    ids = list_ids_for_tenant(tenant_id)
    names = _display_names_for(ids)
    actions = _latest_actions_for(ids)
    roster: list[dict] = []
    for sid in sorted(ids):
        state = get(sid)
        sample_count = state.sample_count if state else 0
        authenticated_count = state.authenticated_count if state else 0
        local = sid.split(":", 1)[1] if ":" in sid else sid
        roster.append(
            {
                "id": sid,
                "name": names.get(sid) or f"Student {local[:6]}",
                "has_name": bool(names.get(sid)),
                "sample_count": sample_count,
                "authenticated_count": authenticated_count,
                "status": _status_for(sample_count, actions.get(sid)),
            }
        )
    return roster


def tenant_stats(tenant_id: str) -> dict:
    """
    Aggregate statistics for a single tenant from the live store + SQLite.

    Returns:
        student_count:     Number of students in this tenant.
        sample_count:      Total baseline samples across all students.
        submission_count:  Scored submissions recorded in submission_manifests.
        last_active_at:    ISO timestamp of the most recent manifest row.
        action_counts:     Dict mapping recommendation action → count.
    """
    student_ids = list_ids_for_tenant(tenant_id)
    student_count = len(student_ids)
    _states = (get(sid) for sid in student_ids)
    sample_count = sum(s.sample_count for s in _states if s is not None)

    # Escape SQL LIKE wildcards so a tenant_id containing '_' or '%' cannot
    # accidentally match other tenants' rows (e.g. 'sem_a' must not match
    # 'semXa:...'). The deletion path uses Python startswith() and is already
    # exact; this keeps the stats counts consistent with it.
    like_prefix = _escape_like(f"{tenant_id}:") + "%"
    try:
        with _get_conn() as conn:
            row = conn.execute(
                r"""SELECT COUNT(*), MAX(created_at)
                   FROM submission_manifests
                   WHERE student_id LIKE ? ESCAPE '\'""",
                (like_prefix,),
            ).fetchone()
            submission_count = int(row[0]) if row else 0
            last_active_at = row[1] if row else None

            action_rows = conn.execute(
                r"""SELECT action, COUNT(*) FROM submission_manifests
                   WHERE student_id LIKE ? ESCAPE '\' AND action IS NOT NULL
                   GROUP BY action""",
                (like_prefix,),
            ).fetchall()
            action_counts = {r[0]: r[1] for r in action_rows}
    except Exception:
        log.exception("tenant_stats DB query failed for %s", tenant_id)
        submission_count, last_active_at, action_counts = 0, None, {}

    return {
        "tenant_id": tenant_id,
        "student_count": student_count,
        "sample_count": sample_count,
        "submission_count": submission_count,
        "last_active_at": last_active_at,
        "action_counts": action_counts,
    }


def delete_tenant_students(tenant_id: str) -> dict:
    """
    FERPA-safe bulk deletion of all students belonging to a tenant.

    Calls delete_student() for each matching student so that every
    associated record (fidelity scores, manifests, corrections) is
    purged via the same code path as a single-student deletion.

    Returns:
        deleted_count:  Number of students successfully erased.
        failed_ids:     Student IDs where deletion raised an exception.
    """
    ids_to_delete = list_ids_for_tenant(tenant_id)
    deleted, failed = 0, []
    for sid in ids_to_delete:
        if delete_student(sid):
            deleted += 1
        else:
            failed.append(sid)
    log_audit(
        action="bulk_delete",
        tenant_id=tenant_id,
        result="ok" if not failed else "partial",
        details={"deleted_count": deleted, "failed_count": len(failed)},
    )
    return {"deleted_count": deleted, "failed_ids": failed}


# ── Phase 3: FERPA data inventory ─────────────────────────────────────────────


def student_data_inventory(student_id: str) -> dict | None:
    """
    Return a structured inventory of all data held for a student.

    Used for FERPA data-access requests ("what do you hold on me?") and
    deletion-confirmation audits ("prove everything was purged").

    Returns None if the student is not in the store.
    """
    state = get(student_id)
    if state is None:
        return None

    try:
        with _get_conn() as conn:
            fidelity_count = conn.execute(
                "SELECT COUNT(*) FROM fidelity_scores WHERE student_id = ?",
                (student_id,),
            ).fetchone()[0]

            manifest_rows = conn.execute(
                "SELECT COUNT(*), MIN(created_at), MAX(created_at), action "
                "FROM submission_manifests WHERE student_id = ? GROUP BY action",
                (student_id,),
            ).fetchall()

            correction_count = conn.execute(
                "SELECT COUNT(*) FROM corrections WHERE student_id = ?",
                (student_id,),
            ).fetchone()[0]

            audit_count = conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE student_id = ?",
                (student_id,),
            ).fetchone()[0]

            ai_likelihood_count = conn.execute(
                "SELECT COUNT(*) FROM ai_likelihood_scores WHERE student_id = ?",
                (student_id,),
            ).fetchone()[0]

            name_row = conn.execute(
                "SELECT display_name FROM student_names WHERE student_id = ?",
                (student_id,),
            ).fetchone()
    except Exception:
        log.exception("student_data_inventory DB query failed for %s", student_id)
        fidelity_count = manifest_rows = correction_count = audit_count = 0
        ai_likelihood_count = 0
        name_row = None

    manifests_by_action: dict = {}
    if manifest_rows:
        for r in manifest_rows:
            count, earliest, latest, action = r[0], r[1], r[2], r[3] or "unknown"
            manifests_by_action[action] = {"count": count, "earliest": earliest, "latest": latest}

    samples = state.samples
    return {
        "student_id": student_id,
        "data_categories": {
            "baseline_samples": {
                "count": len(samples),
                "provenances": list({s.provenance for s in samples}),
                "earliest": min((s.submitted_at for s in samples if s.submitted_at), default=None),
                "latest": max((s.submitted_at for s in samples if s.submitted_at), default=None),
            },
            "fidelity_scores": {
                "count": int(fidelity_count),
            },
            "submission_manifests": {
                "total": sum(v["count"] for v in manifests_by_action.values()),
                "by_action": manifests_by_action,
            },
            "instructor_corrections": {
                "count": int(correction_count),
            },
            "audit_log_entries": {
                "count": int(audit_count),
            },
            "ai_likelihood_scores": {
                "count": int(ai_likelihood_count),
            },
            "display_name": {
                "on_file": bool(name_row and name_row[0]),
            },
        },
        "effective_sample_weight": state.effective_sample_count,
        "generated_at": datetime.now(UTC).isoformat(),
    }


# ── Formation pathways (ADR-002) ──────────────────────────────────────────────
# A three-session developmental pathway opened when a submission diverges.
# Steps: 0 = not started, 1 = baseline done, 2 = formation done,
#        3 = verification done → status 'completed', review flag cleared.

FORMATION_STEPS = 3


def _formation_row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "student_id": row[1],
        "submission_id": row[2],
        "status": row[3],
        "current_step": row[4],
        "reason": row[5],
        "created_at": row[6],
        "updated_at": row[7],
        "total_steps": FORMATION_STEPS,
    }


def get_formation_pathway(student_id: str) -> dict | None:
    """Return the student's open pathway, or the most recent if none open."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                """SELECT id, student_id, submission_id, status, current_step,
                          reason, created_at, updated_at
                   FROM formation_pathways
                   WHERE student_id = ?
                   ORDER BY (status='open') DESC, updated_at DESC
                   LIMIT 1""",
                (student_id,),
            ).fetchone()
        return _formation_row_to_dict(row) if row else None
    except Exception:
        log.exception("get_formation_pathway failed for %s", student_id)
        return None


def open_formation_pathway(
    student_id: str,
    submission_id: str | None = None,
    reason: str | None = None,
) -> dict | None:
    """
    Open a formation pathway for a student. Idempotent: if an open pathway
    already exists, it is returned unchanged (a student has at most one).
    """
    existing = get_formation_pathway(student_id)
    if existing and existing["status"] == "open":
        return existing
    now = datetime.now(UTC).isoformat()
    try:
        with _get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO formation_pathways
                   (student_id, submission_id, status, current_step, reason, created_at, updated_at)
                   VALUES (?, ?, 'open', 0, ?, ?, ?)""",
                (student_id, submission_id, reason, now, now),
            )
            conn.commit()
            new_id = cur.lastrowid
    except Exception:
        log.exception("open_formation_pathway failed for %s", student_id)
        return None
    log_audit(
        action="formation_open",
        student_id=student_id,
        details={"submission_id": submission_id, "pathway_id": new_id},
    )
    return get_formation_pathway(student_id)


def advance_formation_pathway(student_id: str) -> dict | None:
    """
    Advance the student's open pathway by one session. On reaching the final
    step the pathway is marked 'completed' and the triggering submission's
    review flag is cleared (manifest action → no_action; fidelity authentic).
    Returns the updated pathway, or None if there is no open pathway.
    """
    p = get_formation_pathway(student_id)
    if not p or p["status"] != "open":
        return None
    new_step = min(p["current_step"] + 1, FORMATION_STEPS)
    completed = new_step >= FORMATION_STEPS
    now = datetime.now(UTC).isoformat()
    try:
        with _get_conn() as conn:
            conn.execute(
                """UPDATE formation_pathways
                   SET current_step = ?, status = ?, updated_at = ?
                   WHERE id = ?""",
                (new_step, "completed" if completed else "open", now, p["id"]),
            )
            # Clearing the review flag on completion: neutralise the triggering
            # submission so the student's record no longer shows divergence.
            if completed and p["submission_id"]:
                conn.execute(
                    "UPDATE submission_manifests SET action = 'no_action' WHERE submission_id = ?",
                    (p["submission_id"],),
                )
            conn.commit()
    except Exception:
        log.exception("advance_formation_pathway failed for %s", student_id)
        return None

    if completed and p["submission_id"]:
        # Conformal feedback loop: a completed formation says the work was
        # authentic after all.
        update_fidelity_authenticity(p["submission_id"], True)

    log_audit(
        action="formation_complete" if completed else "formation_advance",
        student_id=student_id,
        details={"pathway_id": p["id"], "step": new_step, "submission_id": p["submission_id"]},
    )
    return get_formation_pathway(student_id)


# ── Proctored baseline requests (durable persistence) ─────────────────────────
# Write-through storage for the baseline_requests registry, so pending
# proctored requests survive a process restart.


def put_baseline_request(
    external_request_id: str,
    student_id: str,
    status: str,
    requested_at: float,
    data_json: str,
) -> None:
    """Upsert a baseline request row (best-effort; never raises)."""
    try:
        with _get_conn() as conn:
            conn.execute(
                """INSERT INTO baseline_requests
                   (external_request_id, student_id, status, requested_at, data_json)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(external_request_id) DO UPDATE SET
                     student_id   = excluded.student_id,
                     status       = excluded.status,
                     requested_at = excluded.requested_at,
                     data_json    = excluded.data_json""",
                (external_request_id, student_id, status, requested_at, data_json),
            )
            conn.commit()
    except Exception:
        log.exception("put_baseline_request failed for %s", external_request_id)


def load_baseline_requests() -> list[dict]:
    """Return every persisted baseline request as a raw dict (data_json parsed)."""
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT data_json FROM baseline_requests ORDER BY requested_at"
            ).fetchall()
        out: list[dict] = []
        for r in rows:
            try:
                out.append(json.loads(r[0]))
            except Exception:
                continue
        return out
    except Exception:
        log.exception("load_baseline_requests failed")
        return []


# ── QR phone-park (proctoring deterrence) ─────────────────────────────────────
#
# PRIVACY CONTRACT — mirrors docs/STUDENT_DISCLOSURE.md. Everything below
# stores exactly five things: an opaque `park_token`, the `exam_session_id` a
# professor chose, the `student_hint` a student typed on their own phone, UTC
# timestamps, and state transitions. It stores NO IP address, NO user-agent, NO
# location, NO device fingerprint, and NO roster identifier — no student_id, no
# email, no scoped "{tenant}:{local}" key. Nothing here can be joined back to a
# student profile, and that is the design, not an oversight. Rows purge after
# 24h (`park_purge`).
#
# If you are about to add a column that logs a request, a header, or anything
# derived from one: stop. That is the line this feature does not cross.
#
# What the data means: a parked phone beats every ~10s. A beat that stops
# arriving is a signal for a human proctor to look up — deterrence, never
# proof. A second phone or airplane mode defeats it entirely.

#: Upper bound on a single row's transition list. The beat endpoint is
#: anonymous (the token is the capability), so a phone flipping state in a loop
#: must not be able to grow one row without limit. Oldest entries are dropped.
PARK_MAX_TRANSITIONS = 200


def park_utc(dt: datetime) -> datetime:
    """Normalise a park timestamp to timezone-aware UTC.

    A naive datetime is *assumed* to be UTC rather than rejected — callers in
    this codebase build them with ``datetime.now(UTC)``, and silently shifting
    a naive value by the server's local offset would corrupt the 30s
    dropped-detection window in a way no test would notice.
    """
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def park_iso_utc(dt: datetime) -> str:
    """The canonical phone-park timestamp string: UTC, microsecond precision.

    Both repository backends return park timestamps through this helper so
    their dict shapes are byte-identical, and so SQLite's lexicographic TEXT
    comparison (used by ``park_purge``) sorts chronologically — fixed-width
    output is what makes that equivalence hold.
    """
    return park_utc(dt).isoformat(timespec="microseconds")


def _park_session_row_to_dict(row) -> dict:
    return {
        "exam_session_id": row[0],
        "tenant_id": row[1],
        "park_token": row[2],
        "created_at": row[3],
    }


def park_open(exam_session_id: str, tenant_id: str, park_token: str, created_at: datetime) -> None:
    """Open (or re-open) a phone-park session for an exam sitting.

    Upsert on ``exam_session_id``. When a re-open rotates the token — which
    only happens once the previous one has expired, since the router hands back
    a live token unchanged — the superseded token's beats are deleted in the
    same transaction rather than left as orphans no session can reach.
    """
    ts = park_iso_utc(created_at)
    with _get_conn() as conn:
        prev = conn.execute(
            "SELECT park_token FROM park_sessions WHERE exam_session_id = ?",
            (exam_session_id,),
        ).fetchone()
        if prev and prev[0] != park_token:
            conn.execute("DELETE FROM park_beats WHERE park_token = ?", (prev[0],))
        conn.execute(
            """INSERT INTO park_sessions (exam_session_id, tenant_id, park_token, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(exam_session_id) DO UPDATE SET
                 tenant_id  = excluded.tenant_id,
                 park_token = excluded.park_token,
                 created_at = excluded.created_at""",
            (exam_session_id, tenant_id, park_token, ts),
        )
        conn.commit()


def park_get_session(park_token: str) -> dict | None:
    """Look a park session up by its token (the phone's only credential)."""
    with _get_conn() as conn:
        row = conn.execute(
            """SELECT exam_session_id, tenant_id, park_token, created_at
                 FROM park_sessions WHERE park_token = ?""",
            (park_token,),
        ).fetchone()
    return _park_session_row_to_dict(row) if row else None


def park_get_session_by_exam(exam_session_id: str) -> dict | None:
    """Look a park session up by exam id (the professor's handle on it)."""
    with _get_conn() as conn:
        row = conn.execute(
            """SELECT exam_session_id, tenant_id, park_token, created_at
                 FROM park_sessions WHERE exam_session_id = ?""",
            (exam_session_id,),
        ).fetchone()
    return _park_session_row_to_dict(row) if row else None


def park_beat(park_token: str, student_hint: str, state: str, at: datetime) -> None:
    """Record one heartbeat from a parked phone.

    Upserts the ``(park_token, student_hint)`` row's ``last_seen_at``. A
    transition is appended **only** when ``state`` differs from the last
    recorded state, so a 10s heartbeat holding steady adds nothing — the log
    grows with real events (phone left the page, came back), not with time.
    """
    ts = park_iso_utc(at)
    with _get_conn() as conn:
        row = conn.execute(
            """SELECT state, transitions_json
                 FROM park_beats
                WHERE park_token = ? AND student_hint = ?""",
            (park_token, student_hint),
        ).fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO park_beats
                     (park_token, student_hint, state,
                      first_seen_at, last_seen_at, transitions_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    park_token,
                    student_hint,
                    state,
                    ts,
                    ts,
                    json.dumps([{"state": state, "at": ts}]),
                ),
            )
        else:
            prev_state, transitions_json = row
            if prev_state == state:
                conn.execute(
                    """UPDATE park_beats
                          SET last_seen_at = ?
                        WHERE park_token = ? AND student_hint = ?""",
                    (ts, park_token, student_hint),
                )
            else:
                try:
                    transitions = json.loads(transitions_json)
                except Exception:
                    transitions = []
                transitions.append({"state": state, "at": ts})
                transitions = transitions[-PARK_MAX_TRANSITIONS:]
                conn.execute(
                    """UPDATE park_beats
                          SET state = ?, last_seen_at = ?, transitions_json = ?
                        WHERE park_token = ? AND student_hint = ?""",
                    (state, ts, json.dumps(transitions), park_token, student_hint),
                )
        conn.commit()


def park_tiles(exam_session_id: str) -> list[dict]:
    """Every parked phone on a session, oldest arrival first.

    Returns raw stored state — the "dropped" reading of a phone that stopped
    beating is derived at the API boundary from ``last_seen_at``, so the store
    never has to know what the staleness threshold is.
    """
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT b.student_hint, b.state, b.first_seen_at, b.last_seen_at, b.transitions_json
                 FROM park_beats b
                 JOIN park_sessions s ON s.park_token = b.park_token
                WHERE s.exam_session_id = ?
                ORDER BY b.first_seen_at, b.student_hint""",
            (exam_session_id,),
        ).fetchall()
    out: list[dict] = []
    for hint, state, first_seen, last_seen, transitions_json in rows:
        try:
            transitions = json.loads(transitions_json)
        except Exception:
            transitions = []
        out.append(
            {
                "student_hint": hint,
                "state": state,
                "first_seen_at": first_seen,
                "last_seen_at": last_seen,
                "transitions": transitions,
            }
        )
    return out


def park_delete(exam_session_id: str) -> int:
    """Delete a park session and every beat on it. Returns rows removed."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT park_token FROM park_sessions WHERE exam_session_id = ?",
            (exam_session_id,),
        ).fetchone()
        if row is None:
            return 0
        beats = conn.execute("DELETE FROM park_beats WHERE park_token = ?", (row[0],)).rowcount
        sessions = conn.execute(
            "DELETE FROM park_sessions WHERE exam_session_id = ?", (exam_session_id,)
        ).rowcount
        conn.commit()
    return int(beats) + int(sessions)


def park_purge(before: datetime) -> int:
    """Delete every park session created before ``before``, and its beats.

    The 24h retention sweep. Called opportunistically on session open so the
    deployment needs no scheduler; safe to call at any time. Returns rows
    removed.
    """
    cutoff = park_iso_utc(before)
    with _get_conn() as conn:
        tokens = [
            r[0]
            for r in conn.execute(
                "SELECT park_token FROM park_sessions WHERE created_at < ?", (cutoff,)
            ).fetchall()
        ]
        if not tokens:
            return 0
        beats = 0
        for token in tokens:
            beats += conn.execute("DELETE FROM park_beats WHERE park_token = ?", (token,)).rowcount
        sessions = conn.execute(
            "DELETE FROM park_sessions WHERE created_at < ?", (cutoff,)
        ).rowcount
        conn.commit()
    return int(beats) + int(sessions)
