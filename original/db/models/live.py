"""
db/models/live.py — SQLAlchemy 2.x models for the LIVE pilot schema (WS-6 P2).

Faithful port of the 16-table SQLite schema created inline by
``original/store.py:_get_conn()`` — see ADR-006 and docs/AUDIT_2026-07-06.md
§10 Phase P2. These models are **not yet wired into a live path**: the live
backend still reads/writes through ``original/store.py``. They exist so the
fresh alembic baseline (alembic/versions) and the P3 ``PostgresRepository``
have one canonical schema definition.

Why a separate declarative base
-------------------------------
The dormant v1 models (``original/db/models/{user,student,...}.py``) already
claim table names such as ``users`` on ``original.db.base.Base`` with a
materially different shape (UUID PKs, JWT auth columns, ``institutions``
instead of ``tenants``). None of them genuinely matches the live schema, so
the live models get their own ``LiveBase``/``MetaData`` — v1 imports keep
working untouched until WS-6 P6 deletes the v1 surface.

Model ↔ table map (all NEW models; no v1 model was a genuine match)
-------------------------------------------------------------------
======================  =========================
Model                   Table
======================  =========================
Tenant                  tenants
StaffUser               users
StudentProfile          student_profiles
StudentName             student_names
SubmissionManifest      submission_manifests
FidelityScore           fidelity_scores
AiLikelihoodScore       ai_likelihood_scores
FusedScore              fused_scores
Correction              corrections
CalibrationRun          calibration_runs
TunedThresholds         tuned_thresholds_v2
BluebookCourse          bluebook_courses
BluebookExam            bluebook_exams
BluebookSubmission      bluebook_submissions
BluebookSession         bluebook_sessions
FormationPathway        formation_pathways
BaselineRequest         baseline_requests
AuditLogEntry           audit_log
ParkSession             park_sessions
ParkBeat                park_beats
======================  =========================

``ParkSession``/``ParkBeat``/``BluebookSession`` are the only models here that
were NOT ported from the SQLite store's original 16-table DDL — the first two
arrived with the QR phone-park proctoring surface (T8), the third with the
Bluebook exam-day robustness work. All three were authored against both
backends at once, so there is no legacy shape to stay faithful to.

Design decisions (audit §10 P2, applied uniformly)
--------------------------------------------------
**Tenancy as a constraint, not a convention.** The SQLite store scopes
students with a ``"{tenant_id}:{local_id}"`` string-prefix key convention
(``store.py`` ~1976: ``list_ids_for_tenant`` prefix-scans the flat id space).
Every student-scoped table here instead carries a real ``tenant_id`` column
(FK → ``tenants.tenant_id``) next to the **local** ``student_id``, with a
composite key replacing the prefixed string::

    legacy scoped id "seminary-dallas:marcus"  ⇄  (tenant_id="seminary-dallas",
                                                   student_id="marcus")

Unscoped legacy ids (no ``:`` prefix) are assigned the deployment's default/
sentinel tenant by the P4 migration script. The repository-boundary
compatibility shim that keeps the API's existing scoped-id scheme working is
**Phase P3** work, not part of this module.

**Timestamps.** The store writes ISO-8601 strings into TEXT columns; here
they become ``DateTime(timezone=True)`` (``timestamptz`` on Postgres).
Repositories keep returning the exact ISO string shapes the API expects —
the string⇄datetime conversion happens at the repository boundary (P3), so
no API response changes. One deliberate exception: ``BaselineRequest.
requested_at`` was ``REAL`` (Unix epoch seconds) in SQLite and stays a Float.

**JSON documents.** JSON-string TEXT columns (``*_json``, ``student_profiles.
data``) become ``JSON().with_variant(postgresql.JSONB, "postgresql")`` —
portable JSON on SQLite, JSONB on Postgres.

**numpy blobs.** The live store has **no** byte-level numpy columns today:
feature vectors and topic centroids ride inside the ``student_profiles.data``
JSON document as float lists (``store.py:_serialize`` / ``quantum/state.py``
recomputes ρ from samples). Per the audit's BYTEA decision,
``StudentProfile.rho_bytes`` (LargeBinary → BYTEA) is reserved for the raw
C-order float64 ``ndarray.tobytes()`` serialization of the density matrix;
it is NULL until a later phase elects to persist ρ.

**Booleans.** SQLite stored 0/1 INTEGERs (``fidelity_scores.is_authentic``,
``corrections.is_correct``); modeled as ``Boolean`` — the P3 repository keeps
the store's existing truthy int contract at the boundary.

**Indexes.** Every ``CREATE INDEX`` in the store DDL is ported explicitly.
Indexes whose column set gained ``tenant_id`` get new names; unchanged ones
keep their legacy ``idx_*`` names so the P4 migration is diffable against
the SQLite schema.

**No invented FKs.** SQLite ran with FK enforcement off; relationships the
store kept "logical" (e.g. ``bluebook_submissions.exam_id``, corrections →
manifests) stay FK-free to preserve delete semantics. The only FK introduced
is the tenancy one — the point of the upgrade. ``audit_log.tenant_id``
deliberately has **no** FK: audit appends are best-effort and must never be
rejected (``store.py:log_audit`` never raises).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Text,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names so alembic autogenerate stays stable across
# dialects (SQLite ↔ Postgres). Explicitly named Index()es are unaffected.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Portable JSON document column: plain JSON on SQLite, JSONB on Postgres.
JSONDoc = JSON().with_variant(postgresql.JSONB(), "postgresql")


class LiveBase(DeclarativeBase):
    """Declarative base for the live pilot schema (separate from v1 ``Base``)."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# ── Tenancy & staff ───────────────────────────────────────────────────────────


class Tenant(LiveBase):
    """Institution registry row (``tenants``).

    Phase 0 tenant registry: per-institution metadata attaching environment
    context (demo / pilot / production) to a student cohort. ``meta_json`` is
    a free-form document so new metadata fields need no schema change.
    """

    __tablename__ = "tenants"
    __table_args__ = (Index("idx_tenants_environment", "environment"),)

    tenant_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    environment: Mapped[str] = mapped_column(Text, nullable=False, server_default="demo")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        JSONDoc, nullable=False, server_default=text("'{}'")
    )


class StaffUser(LiveBase):
    """Staff login row (``users``) — professor / admin / operator (ADR-003).

    Students are NOT stored here (they authenticate via student_auth
    sessions). ``password_hash`` is the stdlib PBKDF2-HMAC-SHA256 string.
    ``email`` stays globally unique (it is the login key across tenants).
    ``tenant_id`` was already a real column in SQLite; it gains the FK here.
    Operators use a sentinel tenant + ``'operator'`` role — the P4 migration
    must seed that sentinel tenant row before user rows reference it.
    """

    __tablename__ = "users"
    __table_args__ = (Index("idx_users_tenant", "tenant_id"),)

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default="professor")
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.tenant_id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ── Student aggregate ─────────────────────────────────────────────────────────


class StudentProfile(LiveBase):
    """Serialized ``StudentState`` document (``student_profiles``).

    SQLite kept ``student_id TEXT PRIMARY KEY`` holding the scoped
    ``"{tenant}:{local}"`` id and a ``data`` TEXT column with the JSON
    document produced by ``store.py:_serialize`` (samples with feature
    vectors / topic centroids as float lists, kappa log, drift counter).
    Here the scoped id splits into the composite primary key
    ``(tenant_id, student_id)`` — the composite-unique constraint that
    replaces the prefix convention.

    ``rho_bytes`` is the reserved BYTEA home for the density matrix ρ as raw
    C-order float64 ``ndarray.tobytes()`` (shape ``(FEATURE_DIM,
    FEATURE_DIM)``); today ρ is always recomputed from the samples inside
    ``data`` (``quantum/state.py:density_matrix``) and the column stays NULL.
    """

    __tablename__ = "student_profiles"

    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.tenant_id"), primary_key=True)
    student_id: Mapped[str] = mapped_column(Text, primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONDoc, nullable=False)
    rho_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


class StudentName(LiveBase):
    """Human-readable display name (``student_names``).

    Kept out of the profile document so a name can be recorded (login / LTI
    launch / import) before any baseline exists. SQLite declared
    ``updated_at TEXT NOT NULL DEFAULT ''`` — the empty-string "never set"
    sentinel becomes NULL under ``DateTime``.
    """

    __tablename__ = "student_names"

    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.tenant_id"), primary_key=True)
    student_id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── Scoring artifacts ─────────────────────────────────────────────────────────


class SubmissionManifest(LiveBase):
    """Phase 5 adaptive-scoring audit row (``submission_manifests``).

    One row per adaptive scoring run with a context manifest; used to tune
    ``_derive_directives`` thresholds against production data.
    """

    __tablename__ = "submission_manifests"
    __table_args__ = (
        Index(
            "idx_manifest_tenant_student_created",
            "tenant_id",
            "student_id",
            "created_at",
        ),
    )

    submission_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.tenant_id"), nullable=False)
    student_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSONDoc, nullable=False)
    divergence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    action: Mapped[str | None] = mapped_column(Text, nullable=True)


class FidelityScore(LiveBase):
    """Quantum fidelity score for conformal calibration (``fidelity_scores``).

    Written by ``put_fidelity_score`` after each scoring call; read by
    ``get_authentic_fidelities`` to build the conformal calibration set.
    ``is_authentic`` was INTEGER 0/1 in SQLite.
    """

    __tablename__ = "fidelity_scores"
    __table_args__ = (
        Index("idx_fidelity_tenant_student", "tenant_id", "student_id", "is_authentic"),
    )

    submission_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.tenant_id"), nullable=False)
    student_id: Mapped[str] = mapped_column(Text, nullable=False)
    fidelity: Mapped[float] = mapped_column(Float, nullable=False)
    is_authentic: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AiLikelihoodScore(LiveBase):
    """AI-likelihood detector output (``ai_likelihood_scores``).

    One row per scored submission when AI_LIKELIHOOD_SHADOW=1 or
    AI_LIKELIHOOD_ENABLED=1. Deliberately separate from ``fidelity_scores``
    (different write lifecycle — see the store DDL comment).
    """

    __tablename__ = "ai_likelihood_scores"
    __table_args__ = (
        Index(
            "idx_ai_likelihood_tenant_student",
            "tenant_id",
            "student_id",
            "created_at",
        ),
    )

    submission_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.tenant_id"), nullable=False)
    student_id: Mapped[str] = mapped_column(Text, nullable=False)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    band: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FusedScore(LiveBase):
    """Report-only fused stylometric score (``fused_scores``).

    One row per scored submission when FUSED_SCORE_SHADOW=1 or
    FUSED_SCORE_ENABLED=1. ``channels_json`` carries the peer-centered
    per-channel values so weights can be refit without re-extraction.
    """

    __tablename__ = "fused_scores"
    __table_args__ = (
        Index(
            "idx_fused_scores_tenant_student",
            "tenant_id",
            "student_id",
            "created_at",
        ),
    )

    submission_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.tenant_id"), nullable=False)
    student_id: Mapped[str] = mapped_column(Text, nullable=False)
    fused_log_odds: Mapped[float] = mapped_column(Float, nullable=False)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    band: Mapped[str] = mapped_column(Text, nullable=False)
    channels_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    model_version: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Recoverability for the baseline-volume confound (C1, 2026-08 fix pass):
    # the compression channel's distance drifts as Profile.text (the
    # concatenation of every authenticated baseline) grows, and that growth
    # is not yet capped or normalized. Persisting the exact baseline sample
    # count and reference-pool size alongside every row is what lets a later
    # analysis regress the confound out of the shadow data instead of
    # discovering years later that it can't be reconstructed.
    baseline_samples: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_profiles: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ── Feedback & calibration ────────────────────────────────────────────────────


class Correction(LiveBase):
    """Instructor verdict feedback (``corrections``, PR 7).

    Foreign-keys *logically* to ``submission_manifests`` — SQLite kept the
    relationship index-only and rows may reference submissions scored before
    manifest logging existed, so no FK is added. ``student_id`` (and hence
    ``tenant_id``) is nullable: corrections are submission-centric.
    ``is_correct`` was INTEGER 0/1 in SQLite.
    """

    __tablename__ = "corrections"
    __table_args__ = (
        Index("idx_corrections_submission", "submission_id"),
        Index("idx_corrections_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[str] = mapped_column(Text, nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("tenants.tenant_id"), nullable=True
    )
    student_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_divergence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    corrected_verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewer: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CalibrationRun(LiveBase):
    """Calibration-lab run record (``calibration_runs``, PR 8a).

    ``report_json`` carries the full CalibrationReport (ROC points,
    threshold metrics, per-author stats). Lab-global: not tenant-scoped.
    """

    __tablename__ = "calibration_runs"
    __table_args__ = (Index("idx_calibration_started", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    dataset_label: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    auc: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_essays_scored: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_authors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    config_json: Mapped[dict[str, Any] | None] = mapped_column(JSONDoc, nullable=True)
    report_json: Mapped[dict[str, Any] | None] = mapped_column(JSONDoc, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class TunedThresholds(LiveBase):
    """Versioned threshold set (``tuned_thresholds_v2``, PR 8b).

    Append-only: every "Apply Suggestions" click writes a new row and the
    latest row by ``created_at`` is the active set (subtle versioning
    semantics — port with its tests first, per the WS-6 risk table). Note
    the real table name is ``tuned_thresholds_v2``; audit §10 cites
    ``tuned_thresholds_v`` — the ``_v2`` name is canonical.
    """

    __tablename__ = "tuned_thresholds_v2"
    __table_args__ = (Index("idx_tuned_thresholds_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    no_action: Mapped[float] = mapped_column(Float, nullable=False)
    monitor: Mapped[float] = mapped_column(Float, nullable=False)
    escalate: Mapped[float] = mapped_column(Float, nullable=False)
    verdict_authentic_below: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict_anomalous_at_or_above: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance_json: Mapped[dict[str, Any] | None] = mapped_column(JSONDoc, nullable=True)


# ── Bluebook (secure-exam layer) ──────────────────────────────────────────────


class BluebookCourse(LiveBase):
    """Instructor-created course record (``bluebook_courses``)."""

    __tablename__ = "bluebook_courses"
    __table_args__ = (Index("idx_bluebook_courses_tenant", "tenant_id", "created_at"),)

    course_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.tenant_id"), nullable=False)
    code: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    term: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BluebookExam(LiveBase):
    """Bluebook examination definition (``bluebook_exams``).

    Tenant-scoped instructor artifact: title, course, timing, prompt, and
    lockdown conditions. Submissions flow to ``student_profiles`` as
    proctored baselines.
    """

    __tablename__ = "bluebook_exams"
    __table_args__ = (Index("idx_bluebook_exams_tenant", "tenant_id", "created_at"),)

    exam_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.tenant_id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    course: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_words: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_words: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    conditions_json: Mapped[dict[str, Any]] = mapped_column(
        JSONDoc, nullable=False, server_default=text("'{}'")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BluebookSubmission(LiveBase):
    """One sat examination (``bluebook_submissions``).

    Carries the Original-derived integrity reading for the Results view; the
    prose lives in ``student_profiles`` as the proctored baseline sample.
    ``exam_id`` stays FK-free (kept logical in SQLite; external Bbook flows
    may reference exams not stored locally). ``student_id`` is the local id
    with ``tenant_id`` alongside, like every student-scoped table.
    """

    __tablename__ = "bluebook_submissions"
    __table_args__ = (Index("idx_bluebook_subs_tenant", "tenant_id", "created_at"),)

    submission_id: Mapped[str] = mapped_column(Text, primary_key=True)
    exam_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.tenant_id"), nullable=False)
    student_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    candidate: Mapped[str | None] = mapped_column(Text, nullable=True)
    exam_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    course: Mapped[str | None] = mapped_column(Text, nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stylometric: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="SUBMITTED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Idempotent sealing (Bluebook exam-day robustness): client seal id --
    # replays with the same uuid return the prior row instead of writing a
    # second one.
    submission_uuid: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    late: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class BluebookSession(LiveBase):
    """One (exam, student) sitting (``bluebook_sessions``): pins the immutable
    server deadline (exam-day robustness). The first insert wins; reopening
    the exam returns the same row, so the clock can never be restarted or
    paused by closing the tab.
    """

    __tablename__ = "bluebook_sessions"

    exam_id: Mapped[str] = mapped_column(Text, primary_key=True)
    student_key: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.tenant_id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ── Formation, requests, audit ────────────────────────────────────────────────


class FormationPathway(LiveBase):
    """Formation pathway (``formation_pathways``, ADR-002 convergence slice).

    Opened when a submission diverges; advances through three sessions
    (baseline → formation → verification). "One open pathway per student"
    is enforced by store logic, not a DB constraint — kept that way.
    """

    __tablename__ = "formation_pathways"
    __table_args__ = (Index("idx_formation_tenant_student", "tenant_id", "student_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.tenant_id"), nullable=False)
    student_id: Mapped[str] = mapped_column(Text, nullable=False)
    submission_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BaselineRequest(LiveBase):
    """Durable proctored baseline request (``baseline_requests``).

    The full BaselineRequest object is stored in ``data_json``; status /
    student / requested_at are promoted to columns for querying without
    deserializing every row. ``requested_at`` was ``REAL`` in SQLite — Unix
    epoch seconds, **not** an ISO string — and stays a Float.
    """

    __tablename__ = "baseline_requests"
    __table_args__ = (Index("idx_baseline_requests_status", "status", "requested_at"),)

    external_request_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.tenant_id"), nullable=False)
    student_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[float] = mapped_column(Float, nullable=False)
    data_json: Mapped[dict[str, Any]] = mapped_column(JSONDoc, nullable=False)


class AuditLogEntry(LiveBase):
    """Append-only audit row (``audit_log``, Phase 3 — FERPA reporting).

    Best-effort: ``store.py:log_audit`` never raises, so this table gets
    **no** tenant FK — an audit append must not be rejected because a tenant
    row is missing. ``student_id`` stores the local id going forward (the
    legacy scoped id is split by the P4 migration); ``tenant_id`` was
    already a real (derived) column in SQLite.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("idx_audit_student", "student_id", "created_at"),
        Index("idx_audit_action", "action", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    student_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    tenant_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str] = mapped_column(Text, nullable=False, server_default="ok")
    details_json: Mapped[dict[str, Any]] = mapped_column(
        JSONDoc, nullable=False, server_default=text("'{}'")
    )


# ── QR phone-park (proctoring deterrence) ─────────────────────────────────────
#
# PRIVACY CONTRACT (docs/STUDENT_DISCLOSURE.md) — these two tables are the
# whole persistent footprint of the phone-park feature, and they are
# deliberately anaemic. They store NO IP address, NO user-agent, NO location,
# NO device fingerprint, and NO roster identifier: not a student_id, not an
# email, not a tenant-scoped id. The only student-supplied datum is
# ``ParkBeat.student_hint``, free text the student types on their own phone
# (initials, a nickname) purely so a proctor can tell one tile from another.
# That is why neither table carries the (tenant_id, student_id) composite the
# rest of this schema uses — there is no student row to key against, and the
# tenancy shim is bypassed entirely. Rows are purged after 24h.
#
# The feature is deterrence and signal, never proof: a beacon that stops
# beating is a prompt for a human to look, not evidence of anything.


class ParkSession(LiveBase):
    """One QR phone-park session per exam sitting (``park_sessions``).

    A professor opens a session at exam start; the returned ``park_token`` is
    baked into a QR code that students scan. The token is the capability —
    holding it is what lets an (anonymous, unauthenticated) phone beat against
    the session, so it is a ``secrets.token_urlsafe`` value, not a guessable id.

    ``tenant_id`` records the opening staff principal's institution and is the
    only thing that scopes reads: a professor may only see sessions their own
    tenant opened. It is emphatically NOT a per-student identifier.

    TTL (6h from ``created_at``) is applied at the repository boundary rather
    than stored, so the retention policy lives in exactly one place.
    """

    __tablename__ = "park_sessions"
    __table_args__ = (Index("idx_park_sessions_created", "created_at"),)

    exam_session_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.tenant_id"), nullable=False)
    park_token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ParkBeat(LiveBase):
    """One parked phone's heartbeat row (``park_beats``).

    Keyed ``(park_token, student_hint)`` — a natural composite key, since a
    phone identifies itself by nothing more than the token it scanned and the
    hint its owner typed. There is no id column and no FK to
    ``park_sessions``: a rotated or purged token's orphans are removed
    explicitly by ``park_open``/``park_delete``/``park_purge`` (the same
    "no invented FKs" posture the rest of this module takes), and adding one
    would make SQLite and Postgres disagree, since the store runs with FK
    enforcement off.

    ``transitions_json`` is an append-only list of ``{"state", "at"}`` objects
    recording only *changes* of state — a 10s heartbeat that keeps reporting
    the same state appends nothing, so the list stays bounded by how often the
    phone actually left and returned to the parked page.
    """

    __tablename__ = "park_beats"

    park_token: Mapped[str] = mapped_column(Text, primary_key=True)
    student_hint: Mapped[str] = mapped_column(Text, primary_key=True)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    transitions_json: Mapped[list[Any]] = mapped_column(
        JSONDoc, nullable=False, server_default=text("'[]'")
    )


#: All 20 live models in store-DDL order, for tests and the P3 repository.
LIVE_MODELS = [
    StudentProfile,
    StudentName,
    SubmissionManifest,
    Correction,
    CalibrationRun,
    TunedThresholds,
    FidelityScore,
    AiLikelihoodScore,
    FusedScore,
    Tenant,
    StaffUser,
    BluebookExam,
    BluebookSubmission,
    BluebookSession,
    BluebookCourse,
    AuditLogEntry,
    FormationPathway,
    BaselineRequest,
    ParkSession,
    ParkBeat,
]
