#!/usr/bin/env python3
"""
migrate_sqlite_to_pg.py — WS-6 P4 data migration (SQLite -> Postgres).

Copies every row of the live SQLite store (``original/store.py``,
``ORIGINAL_DB``) into the live Postgres schema (``original/db/models/live.py``,
``DATABASE_URL``), then emits a per-table row-count + content-checksum parity
report so the migration can be *proven* faithful, not just assumed. The set of
tables migrated is exactly ``MIGRATORS`` below, one per table in
``original.db.models.live.LiveBase.metadata`` -- see ``tests/test_migration.py``,
which derives its completeness check from that same metadata so a table added
to the live schema without a migrator here fails loudly instead of silently
losing data on cutover.

Why table-level, not Repository-to-Repository
---------------------------------------------
The audit sketch says "read via SqliteRepository, write via
PostgresRepository", but the Repository write methods are the wrong tool for
a faithful migration: ``put_tenant``, ``log_audit``, ``put_fidelity_score``,
etc. all stamp ``created_at = now()``, and the calibration/formation write
paths are lifecycle-based (start -> complete) rather than direct inserts.
Going through them would silently rewrite every timestamp and drop
is_authentic=False fidelity rows (there's no Repository read for those). So
this reads raw SQLite rows and inserts SQLAlchemy model instances directly,
preserving primary keys and original timestamps exactly.

The schema is a *transform*, not a copy (see db/models/live.py): the scoped
``"{tenant}:{local}"`` student id splits into a composite ``(tenant_id,
student_id)`` key; TEXT timestamps become ``timestamptz``; JSON-string
columns become JSONB. The parity checksum is therefore computed over a
**backend-agnostic canonical form** (scoped id reconstructed, timestamps
normalized to a single ISO-8601 UTC representation, JSON parsed and
sort-keyed) so an identical checksum from both backends is real proof the
transform round-tripped, not an artifact of matching storage formats.

FERPA
-----
This moves real student data. Run it on the Render host or over an encrypted
tunnel to the managed Postgres instance -- never pull a production student
database onto a laptop. ``--dry-run`` reads and checksums both sides without
writing, for a pre-cutover parity check.

Usage
-----
    ORIGINAL_DB=/data/profiles.db \
    DATABASE_URL=postgresql://user:pass@host:5432/db \
    python -m scripts.migrate_sqlite_to_pg [--dry-run] [--report PATH]

Exit code is 0 iff every table reports row-count AND checksum parity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from original.db.models.live import (
    AiLikelihoodScore,
    AuditLogEntry,
    BaselineRequest,
    BluebookCourse,
    BluebookExam,
    BluebookSubmission,
    CalibrationRun,
    Correction,
    FidelityScore,
    FormationPathway,
    ParkBeat,
    ParkSession,
    StaffUser,
    StudentName,
    StudentProfile,
    SubmissionManifest,
    Tenant,
    TunedThresholds,
)
from original.db.postgres_session import session_scope
from original.db.tenancy_shim import split_scoped_id


# ── Canonical-form helpers (backend-agnostic) ────────────────────────────────
def _parse_ts(value) -> datetime | None:
    """SQLite TEXT timestamp (ISO with 'Z' or '+00:00'), empty string, or a
    datetime from Postgres -> an aware UTC datetime, or None. store.py always
    writes UTC-aware strings; a naive value is assumed UTC defensively."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _canon_ts(value) -> str | None:
    """Timestamp -> single canonical ISO-8601 UTC string (or None). Makes a
    'Z'-suffixed SQLite string and a Postgres timestamptz compare equal."""
    dt = _parse_ts(value)
    return dt.isoformat() if dt is not None else None


def _parse_json(text) -> object:
    """JSON string (SQLite) or already-parsed dict/list (Postgres JSONB) ->
    the parsed object."""
    if text is None or text == "":
        return None
    if isinstance(text, dict | list):
        return text
    return json.loads(text)


def _scoped(student_id: str | None) -> str | None:
    """Round-trip-stable scoped id for the canonical form: for a colon'd id
    it's unchanged; for a legacy flat id it's unchanged too. None passes
    through. (This is the identity join_scoped_id(*split_scoped_id(x)); kept
    explicit so the canonical form's meaning is obvious.)"""
    return student_id


# ── Per-table migrators ──────────────────────────────────────────────────────
# Each migrator reads raw SQLite rows into canonical dicts (backend-agnostic),
# turns a canonical dict into a live-schema model instance, and reads the
# Postgres side back into the *same* canonical dict shape. The checksum runs
# over the canonical dicts, so it proves the transform round-tripped.
class _Migrator:
    name: str
    model: type
    pk: str  # canonical-dict key rows are sorted by for a deterministic checksum

    def read_sqlite(self, conn: sqlite3.Connection) -> list[dict]:
        raise NotImplementedError

    def to_model(self, row: dict):
        raise NotImplementedError

    def read_pg(self, session) -> list[dict]:
        raise NotImplementedError


def _split_local(student_id: str | None) -> tuple[str, str] | tuple[None, None]:
    """Scoped student id -> (tenant_id, local_id) for a composite-key insert;
    (None, None) for a NULL student id (corrections / bluebook_submissions)."""
    if student_id is None:
        return None, None
    return split_scoped_id(student_id)


class _TenantMigrator(_Migrator):
    name = "tenants"
    model = Tenant
    pk = "tenant_id"

    def read_sqlite(self, conn):
        rows = conn.execute(
            "SELECT tenant_id, name, environment, created_at, meta_json FROM tenants"
        ).fetchall()
        return [
            {
                "tenant_id": r[0],
                "name": r[1],
                "environment": r[2],
                "created_at": _canon_ts(r[3]),
                "meta": _parse_json(r[4]) or {},
            }
            for r in rows
        ]

    def to_model(self, row):
        return Tenant(
            tenant_id=row["tenant_id"],
            name=row["name"],
            environment=row["environment"],
            created_at=_parse_ts(row["created_at"]),
            meta_json=row["meta"],
        )

    def read_pg(self, session):
        return [
            {
                "tenant_id": t.tenant_id,
                "name": t.name,
                "environment": t.environment,
                "created_at": _canon_ts(t.created_at),
                "meta": t.meta_json or {},
            }
            for t in session.query(Tenant).all()
        ]


class _UserMigrator(_Migrator):
    name = "users"
    model = StaffUser
    pk = "user_id"

    def read_sqlite(self, conn):
        rows = conn.execute(
            "SELECT user_id, email, password_hash, role, tenant_id, name, created_at FROM users"
        ).fetchall()
        return [
            {
                "user_id": r[0],
                "email": r[1],
                "password_hash": r[2],
                "role": r[3],
                "tenant_id": r[4],
                "name": r[5],
                "created_at": _canon_ts(r[6]),
            }
            for r in rows
        ]

    def to_model(self, row):
        return StaffUser(
            user_id=row["user_id"],
            email=row["email"],
            password_hash=row["password_hash"],
            role=row["role"],
            tenant_id=row["tenant_id"],
            name=row["name"],
            created_at=_parse_ts(row["created_at"]),
        )

    def read_pg(self, session):
        return [
            {
                "user_id": u.user_id,
                "email": u.email,
                "password_hash": u.password_hash,
                "role": u.role,
                "tenant_id": u.tenant_id,
                "name": u.name,
                "created_at": _canon_ts(u.created_at),
            }
            for u in session.query(StaffUser).all()
        ]


class _StudentProfileMigrator(_Migrator):
    name = "student_profiles"
    model = StudentProfile
    pk = "student_id"

    def read_sqlite(self, conn):
        rows = conn.execute("SELECT student_id, data FROM student_profiles").fetchall()
        return [{"student_id": _scoped(r[0]), "data": _parse_json(r[1])} for r in rows]

    def to_model(self, row):
        tenant_id, local_id = _split_local(row["student_id"])
        return StudentProfile(
            tenant_id=tenant_id, student_id=local_id, data=row["data"], rho_bytes=None
        )

    def read_pg(self, session):
        from original.db.tenancy_shim import join_scoped_id

        return [
            {"student_id": join_scoped_id(p.tenant_id, p.student_id), "data": p.data}
            for p in session.query(StudentProfile).all()
        ]


class _StudentNameMigrator(_Migrator):
    name = "student_names"
    model = StudentName
    pk = "student_id"

    def read_sqlite(self, conn):
        rows = conn.execute(
            "SELECT student_id, display_name, updated_at FROM student_names"
        ).fetchall()
        return [
            {
                "student_id": _scoped(r[0]),
                "display_name": r[1],
                "updated_at": _canon_ts(r[2]),  # '' -> None
            }
            for r in rows
        ]

    def to_model(self, row):
        tenant_id, local_id = _split_local(row["student_id"])
        return StudentName(
            tenant_id=tenant_id,
            student_id=local_id,
            display_name=row["display_name"],
            updated_at=_parse_ts(row["updated_at"]),
        )

    def read_pg(self, session):
        from original.db.tenancy_shim import join_scoped_id

        return [
            {
                "student_id": join_scoped_id(n.tenant_id, n.student_id),
                "display_name": n.display_name,
                "updated_at": _canon_ts(n.updated_at),
            }
            for n in session.query(StudentName).all()
        ]


class _ManifestMigrator(_Migrator):
    name = "submission_manifests"
    model = SubmissionManifest
    pk = "submission_id"

    def read_sqlite(self, conn):
        rows = conn.execute(
            "SELECT submission_id, student_id, created_at, manifest_json, "
            "divergence_score, action FROM submission_manifests"
        ).fetchall()
        return [
            {
                "submission_id": r[0],
                "student_id": _scoped(r[1]),
                "created_at": _canon_ts(r[2]),
                "manifest": _parse_json(r[3]),
                "divergence_score": r[4],
                "action": r[5],
            }
            for r in rows
        ]

    def to_model(self, row):
        tenant_id, local_id = _split_local(row["student_id"])
        return SubmissionManifest(
            submission_id=row["submission_id"],
            tenant_id=tenant_id,
            student_id=local_id,
            created_at=_parse_ts(row["created_at"]),
            manifest_json=row["manifest"],
            divergence_score=row["divergence_score"],
            action=row["action"],
        )

    def read_pg(self, session):
        from original.db.tenancy_shim import join_scoped_id

        return [
            {
                "submission_id": m.submission_id,
                "student_id": join_scoped_id(m.tenant_id, m.student_id),
                "created_at": _canon_ts(m.created_at),
                "manifest": m.manifest_json,
                "divergence_score": m.divergence_score,
                "action": m.action,
            }
            for m in session.query(SubmissionManifest).all()
        ]


class _CorrectionMigrator(_Migrator):
    name = "corrections"
    model = Correction
    pk = "id"

    def read_sqlite(self, conn):
        rows = conn.execute(
            "SELECT id, submission_id, student_id, original_verdict, original_action, "
            "original_divergence_score, corrected_verdict, corrected_action, is_correct, "
            "reviewer, notes, created_at FROM corrections"
        ).fetchall()
        return [
            {
                "id": r[0],
                "submission_id": r[1],
                "student_id": _scoped(r[2]),
                "original_verdict": r[3],
                "original_action": r[4],
                "original_divergence_score": r[5],
                "corrected_verdict": r[6],
                "corrected_action": r[7],
                "is_correct": bool(r[8]),
                "reviewer": r[9],
                "notes": r[10],
                "created_at": _canon_ts(r[11]),
            }
            for r in rows
        ]

    def to_model(self, row):
        tenant_id, local_id = _split_local(row["student_id"])
        return Correction(
            id=row["id"],
            submission_id=row["submission_id"],
            tenant_id=tenant_id,
            student_id=local_id,
            original_verdict=row["original_verdict"],
            original_action=row["original_action"],
            original_divergence_score=row["original_divergence_score"],
            corrected_verdict=row["corrected_verdict"],
            corrected_action=row["corrected_action"],
            is_correct=row["is_correct"],
            reviewer=row["reviewer"],
            notes=row["notes"],
            created_at=_parse_ts(row["created_at"]),
        )

    def read_pg(self, session):
        from original.db.tenancy_shim import join_scoped_id

        out = []
        for c in session.query(Correction).all():
            scoped = join_scoped_id(c.tenant_id, c.student_id) if c.student_id else None
            out.append(
                {
                    "id": c.id,
                    "submission_id": c.submission_id,
                    "student_id": scoped,
                    "original_verdict": c.original_verdict,
                    "original_action": c.original_action,
                    "original_divergence_score": c.original_divergence_score,
                    "corrected_verdict": c.corrected_verdict,
                    "corrected_action": c.corrected_action,
                    "is_correct": bool(c.is_correct),
                    "reviewer": c.reviewer,
                    "notes": c.notes,
                    "created_at": _canon_ts(c.created_at),
                }
            )
        return out


class _CalibrationRunMigrator(_Migrator):
    name = "calibration_runs"
    model = CalibrationRun
    pk = "id"

    def read_sqlite(self, conn):
        rows = conn.execute(
            "SELECT id, run_label, dataset_label, started_at, completed_at, status, auc, "
            "n_essays_scored, n_authors, config_json, report_json, error FROM calibration_runs"
        ).fetchall()
        return [
            {
                "id": r[0],
                "run_label": r[1],
                "dataset_label": r[2],
                "started_at": _canon_ts(r[3]),
                "completed_at": _canon_ts(r[4]),
                "status": r[5],
                "auc": r[6],
                "n_essays_scored": r[7],
                "n_authors": r[8],
                "config": _parse_json(r[9]),
                "report": _parse_json(r[10]),
                "error": r[11],
            }
            for r in rows
        ]

    def to_model(self, row):
        return CalibrationRun(
            id=row["id"],
            run_label=row["run_label"],
            dataset_label=row["dataset_label"],
            started_at=_parse_ts(row["started_at"]),
            completed_at=_parse_ts(row["completed_at"]),
            status=row["status"],
            auc=row["auc"],
            n_essays_scored=row["n_essays_scored"],
            n_authors=row["n_authors"],
            config_json=row["config"],
            report_json=row["report"],
            error=row["error"],
        )

    def read_pg(self, session):
        return [
            {
                "id": c.id,
                "run_label": c.run_label,
                "dataset_label": c.dataset_label,
                "started_at": _canon_ts(c.started_at),
                "completed_at": _canon_ts(c.completed_at),
                "status": c.status,
                "auc": c.auc,
                "n_essays_scored": c.n_essays_scored,
                "n_authors": c.n_authors,
                "config": c.config_json,
                "report": c.report_json,
                "error": c.error,
            }
            for c in session.query(CalibrationRun).all()
        ]


class _TunedThresholdsMigrator(_Migrator):
    name = "tuned_thresholds_v2"
    model = TunedThresholds
    pk = "id"

    def read_sqlite(self, conn):
        rows = conn.execute(
            "SELECT id, created_at, source, source_run_id, no_action, monitor, escalate, "
            "verdict_authentic_below, verdict_anomalous_at_or_above, notes, provenance_json "
            "FROM tuned_thresholds_v2"
        ).fetchall()
        return [
            {
                "id": r[0],
                "created_at": _canon_ts(r[1]),
                "source": r[2],
                "source_run_id": r[3],
                "no_action": r[4],
                "monitor": r[5],
                "escalate": r[6],
                "verdict_authentic_below": r[7],
                "verdict_anomalous_at_or_above": r[8],
                "notes": r[9],
                "provenance": _parse_json(r[10]),
            }
            for r in rows
        ]

    def to_model(self, row):
        return TunedThresholds(
            id=row["id"],
            created_at=_parse_ts(row["created_at"]),
            source=row["source"],
            source_run_id=row["source_run_id"],
            no_action=row["no_action"],
            monitor=row["monitor"],
            escalate=row["escalate"],
            verdict_authentic_below=row["verdict_authentic_below"],
            verdict_anomalous_at_or_above=row["verdict_anomalous_at_or_above"],
            notes=row["notes"],
            provenance_json=row["provenance"],
        )

    def read_pg(self, session):
        return [
            {
                "id": t.id,
                "created_at": _canon_ts(t.created_at),
                "source": t.source,
                "source_run_id": t.source_run_id,
                "no_action": t.no_action,
                "monitor": t.monitor,
                "escalate": t.escalate,
                "verdict_authentic_below": t.verdict_authentic_below,
                "verdict_anomalous_at_or_above": t.verdict_anomalous_at_or_above,
                "notes": t.notes,
                "provenance": t.provenance_json,
            }
            for t in session.query(TunedThresholds).all()
        ]


class _FidelityMigrator(_Migrator):
    name = "fidelity_scores"
    model = FidelityScore
    pk = "submission_id"

    def read_sqlite(self, conn):
        rows = conn.execute(
            "SELECT submission_id, student_id, fidelity, is_authentic, created_at "
            "FROM fidelity_scores"
        ).fetchall()
        return [
            {
                "submission_id": r[0],
                "student_id": _scoped(r[1]),
                "fidelity": r[2],
                "is_authentic": bool(r[3]),
                "created_at": _canon_ts(r[4]),
            }
            for r in rows
        ]

    def to_model(self, row):
        tenant_id, local_id = _split_local(row["student_id"])
        return FidelityScore(
            submission_id=row["submission_id"],
            tenant_id=tenant_id,
            student_id=local_id,
            fidelity=row["fidelity"],
            is_authentic=row["is_authentic"],
            created_at=_parse_ts(row["created_at"]),
        )

    def read_pg(self, session):
        from original.db.tenancy_shim import join_scoped_id

        return [
            {
                "submission_id": f.submission_id,
                "student_id": join_scoped_id(f.tenant_id, f.student_id),
                "fidelity": f.fidelity,
                "is_authentic": bool(f.is_authentic),
                "created_at": _canon_ts(f.created_at),
            }
            for f in session.query(FidelityScore).all()
        ]


class _AiLikelihoodMigrator(_Migrator):
    name = "ai_likelihood_scores"
    model = AiLikelihoodScore
    pk = "submission_id"

    def read_sqlite(self, conn):
        rows = conn.execute(
            "SELECT submission_id, student_id, probability, band, model_version, created_at "
            "FROM ai_likelihood_scores"
        ).fetchall()
        return [
            {
                "submission_id": r[0],
                "student_id": _scoped(r[1]),
                "probability": r[2],
                "band": r[3],
                "model_version": r[4],
                "created_at": _canon_ts(r[5]),
            }
            for r in rows
        ]

    def to_model(self, row):
        tenant_id, local_id = _split_local(row["student_id"])
        return AiLikelihoodScore(
            submission_id=row["submission_id"],
            tenant_id=tenant_id,
            student_id=local_id,
            probability=row["probability"],
            band=row["band"],
            model_version=row["model_version"],
            created_at=_parse_ts(row["created_at"]),
        )

    def read_pg(self, session):
        from original.db.tenancy_shim import join_scoped_id

        return [
            {
                "submission_id": a.submission_id,
                "student_id": join_scoped_id(a.tenant_id, a.student_id),
                "probability": a.probability,
                "band": a.band,
                "model_version": a.model_version,
                "created_at": _canon_ts(a.created_at),
            }
            for a in session.query(AiLikelihoodScore).all()
        ]


class _BluebookExamMigrator(_Migrator):
    name = "bluebook_exams"
    model = BluebookExam
    pk = "exam_id"

    def read_sqlite(self, conn):
        rows = conn.execute(
            "SELECT exam_id, tenant_id, title, course, duration, min_words, max_words, "
            "prompt, conditions_json, status, created_at FROM bluebook_exams"
        ).fetchall()
        return [
            {
                "exam_id": r[0],
                "tenant_id": r[1],
                "title": r[2],
                "course": r[3],
                "duration": r[4],
                "min_words": r[5],
                "max_words": r[6],
                "prompt": r[7],
                "conditions": _parse_json(r[8]) or {},
                "status": r[9],
                "created_at": _canon_ts(r[10]),
            }
            for r in rows
        ]

    def to_model(self, row):
        return BluebookExam(
            exam_id=row["exam_id"],
            tenant_id=row["tenant_id"],
            title=row["title"],
            course=row["course"],
            duration=row["duration"],
            min_words=row["min_words"],
            max_words=row["max_words"],
            prompt=row["prompt"],
            conditions_json=row["conditions"],
            status=row["status"],
            created_at=_parse_ts(row["created_at"]),
        )

    def read_pg(self, session):
        return [
            {
                "exam_id": e.exam_id,
                "tenant_id": e.tenant_id,
                "title": e.title,
                "course": e.course,
                "duration": e.duration,
                "min_words": e.min_words,
                "max_words": e.max_words,
                "prompt": e.prompt,
                "conditions": e.conditions_json or {},
                "status": e.status,
                "created_at": _canon_ts(e.created_at),
            }
            for e in session.query(BluebookExam).all()
        ]


class _BluebookSubmissionMigrator(_Migrator):
    name = "bluebook_submissions"
    model = BluebookSubmission
    pk = "submission_id"

    def read_sqlite(self, conn):
        rows = conn.execute(
            "SELECT submission_id, exam_id, tenant_id, student_id, candidate, exam_title, "
            "course, word_count, time_min, stylometric, ai_score, status, created_at "
            "FROM bluebook_submissions"
        ).fetchall()
        return [
            {
                "submission_id": r[0],
                "exam_id": r[1],
                "tenant_id": r[2],
                "student_id": _scoped(r[3]),
                "candidate": r[4],
                "exam_title": r[5],
                "course": r[6],
                "word_count": r[7],
                "time_min": r[8],
                "stylometric": r[9],
                "ai_score": r[10],
                "status": r[11],
                "created_at": _canon_ts(r[12]),
            }
            for r in rows
        ]

    def to_model(self, row):
        # bluebook_submissions carries its own tenant_id column in BOTH schemas
        # (it isn't derived from student_id). student_id is stored LOCAL in the
        # live schema; split off any tenant prefix but keep the row's own
        # tenant_id as the authority.
        _, local_id = _split_local(row["student_id"])
        return BluebookSubmission(
            submission_id=row["submission_id"],
            exam_id=row["exam_id"],
            tenant_id=row["tenant_id"],
            student_id=local_id,
            candidate=row["candidate"],
            exam_title=row["exam_title"],
            course=row["course"],
            word_count=row["word_count"],
            time_min=row["time_min"],
            stylometric=row["stylometric"],
            ai_score=row["ai_score"],
            status=row["status"],
            created_at=_parse_ts(row["created_at"]),
        )

    def read_pg(self, session):
        out = []
        for s in session.query(BluebookSubmission).all():
            scoped = f"{s.tenant_id}:{s.student_id}" if s.student_id else None
            out.append(
                {
                    "submission_id": s.submission_id,
                    "exam_id": s.exam_id,
                    "tenant_id": s.tenant_id,
                    "student_id": scoped,
                    "candidate": s.candidate,
                    "exam_title": s.exam_title,
                    "course": s.course,
                    "word_count": s.word_count,
                    "time_min": s.time_min,
                    "stylometric": s.stylometric,
                    "ai_score": s.ai_score,
                    "status": s.status,
                    "created_at": _canon_ts(s.created_at),
                }
            )
        return out


class _BluebookCourseMigrator(_Migrator):
    name = "bluebook_courses"
    model = BluebookCourse
    pk = "course_id"

    def read_sqlite(self, conn):
        rows = conn.execute(
            "SELECT course_id, tenant_id, code, name, term, status, created_at "
            "FROM bluebook_courses"
        ).fetchall()
        return [
            {
                "course_id": r[0],
                "tenant_id": r[1],
                "code": r[2],
                "name": r[3],
                "term": r[4],
                "status": r[5],
                "created_at": _canon_ts(r[6]),
            }
            for r in rows
        ]

    def to_model(self, row):
        return BluebookCourse(
            course_id=row["course_id"],
            tenant_id=row["tenant_id"],
            code=row["code"],
            name=row["name"],
            term=row["term"],
            status=row["status"],
            created_at=_parse_ts(row["created_at"]),
        )

    def read_pg(self, session):
        return [
            {
                "course_id": c.course_id,
                "tenant_id": c.tenant_id,
                "code": c.code,
                "name": c.name,
                "term": c.term,
                "status": c.status,
                "created_at": _canon_ts(c.created_at),
            }
            for c in session.query(BluebookCourse).all()
        ]


class _AuditMigrator(_Migrator):
    name = "audit_log"
    model = AuditLogEntry
    pk = "id"

    def read_sqlite(self, conn):
        rows = conn.execute(
            "SELECT id, created_at, action, student_id, tenant_id, actor, result, details_json "
            "FROM audit_log"
        ).fetchall()
        return [
            {
                # canonical form keeps the FULL scoped student_id (as SQLite
                # stored it) + tenant_id, so both backends reconstruct the same
                # pair -- see to_model / read_pg for the split/rejoin.
                "id": r[0],
                "created_at": _canon_ts(r[1]),
                "action": r[2],
                "student_id": r[3],
                "tenant_id": r[4],
                "actor": r[5],
                "result": r[6],
                "details": _parse_json(r[7]) or {},
            }
            for r in rows
        ]

    def to_model(self, row):
        # audit_log is the one table that stored the FULL scoped id in
        # student_id AND a derived tenant_id column. The live schema stores the
        # LOCAL id. Strip the tenant prefix when present; otherwise keep the id
        # as-is (system-action rows have student_id NULL, or a legacy flat id).
        full = row["student_id"]
        tenant = row["tenant_id"]
        if full and tenant and full.startswith(f"{tenant}:"):
            local = full[len(tenant) + 1 :]
        elif full and tenant and ":" not in full:
            # colon-less id with an explicit non-derived tenant would not
            # round-trip through join_scoped_id -- flag rather than corrupt.
            raise ValueError(
                f"audit_log id={row['id']}: student_id {full!r} has no "
                f"'{tenant}:' prefix; cannot faithfully split -- migrate manually"
            )
        else:
            local = full
        return AuditLogEntry(
            id=row["id"],
            created_at=_parse_ts(row["created_at"]),
            action=row["action"],
            student_id=local,
            tenant_id=tenant,
            actor=row["actor"],
            result=row["result"],
            details_json=row["details"],
        )

    def read_pg(self, session):
        out = []
        for a in session.query(AuditLogEntry).all():
            full = (
                f"{a.tenant_id}:{a.student_id}" if (a.tenant_id and a.student_id) else a.student_id
            )
            out.append(
                {
                    "id": a.id,
                    "created_at": _canon_ts(a.created_at),
                    "action": a.action,
                    "student_id": full,
                    "tenant_id": a.tenant_id,
                    "actor": a.actor,
                    "result": a.result,
                    "details": a.details_json or {},
                }
            )
        return out


class _FormationMigrator(_Migrator):
    name = "formation_pathways"
    model = FormationPathway
    pk = "id"

    def read_sqlite(self, conn):
        rows = conn.execute(
            "SELECT id, student_id, submission_id, status, current_step, reason, "
            "created_at, updated_at FROM formation_pathways"
        ).fetchall()
        return [
            {
                "id": r[0],
                "student_id": _scoped(r[1]),
                "submission_id": r[2],
                "status": r[3],
                "current_step": r[4],
                "reason": r[5],
                "created_at": _canon_ts(r[6]),
                "updated_at": _canon_ts(r[7]),
            }
            for r in rows
        ]

    def to_model(self, row):
        tenant_id, local_id = _split_local(row["student_id"])
        return FormationPathway(
            id=row["id"],
            tenant_id=tenant_id,
            student_id=local_id,
            submission_id=row["submission_id"],
            status=row["status"],
            current_step=row["current_step"],
            reason=row["reason"],
            created_at=_parse_ts(row["created_at"]),
            updated_at=_parse_ts(row["updated_at"]),
        )

    def read_pg(self, session):
        from original.db.tenancy_shim import join_scoped_id

        return [
            {
                "id": f.id,
                "student_id": join_scoped_id(f.tenant_id, f.student_id),
                "submission_id": f.submission_id,
                "status": f.status,
                "current_step": f.current_step,
                "reason": f.reason,
                "created_at": _canon_ts(f.created_at),
                "updated_at": _canon_ts(f.updated_at),
            }
            for f in session.query(FormationPathway).all()
        ]


class _BaselineRequestMigrator(_Migrator):
    name = "baseline_requests"
    model = BaselineRequest
    pk = "external_request_id"

    def read_sqlite(self, conn):
        rows = conn.execute(
            "SELECT external_request_id, student_id, status, requested_at, data_json "
            "FROM baseline_requests"
        ).fetchall()
        return [
            {
                "external_request_id": r[0],
                "student_id": _scoped(r[1]),
                "status": r[2],
                # requested_at is a REAL Unix epoch in BOTH schemas -- not a
                # timestamp column; keep the float verbatim.
                "requested_at": r[3],
                "data": _parse_json(r[4]),
            }
            for r in rows
        ]

    def to_model(self, row):
        tenant_id, local_id = _split_local(row["student_id"])
        return BaselineRequest(
            external_request_id=row["external_request_id"],
            tenant_id=tenant_id,
            student_id=local_id,
            status=row["status"],
            requested_at=row["requested_at"],
            data_json=row["data"],
        )

    def read_pg(self, session):
        from original.db.tenancy_shim import join_scoped_id

        return [
            {
                "external_request_id": b.external_request_id,
                "student_id": join_scoped_id(b.tenant_id, b.student_id),
                "status": b.status,
                "requested_at": b.requested_at,
                "data": b.data_json,
            }
            for b in session.query(BaselineRequest).all()
        ]


class _ParkSessionMigrator(_Migrator):
    name = "park_sessions"
    model = ParkSession
    pk = "exam_session_id"

    def read_sqlite(self, conn):
        rows = conn.execute(
            "SELECT exam_session_id, tenant_id, park_token, created_at FROM park_sessions"
        ).fetchall()
        return [
            {
                "exam_session_id": r[0],
                "tenant_id": r[1],
                "park_token": r[2],
                "created_at": _canon_ts(r[3]),
            }
            for r in rows
        ]

    def to_model(self, row):
        return ParkSession(
            exam_session_id=row["exam_session_id"],
            tenant_id=row["tenant_id"],
            park_token=row["park_token"],
            created_at=_parse_ts(row["created_at"]),
        )

    def read_pg(self, session):
        return [
            {
                "exam_session_id": s.exam_session_id,
                "tenant_id": s.tenant_id,
                "park_token": s.park_token,
                "created_at": _canon_ts(s.created_at),
            }
            for s in session.query(ParkSession).all()
        ]


class _ParkBeatMigrator(_Migrator):
    name = "park_beats"
    model = ParkBeat
    # park_beats has no single-column primary key -- it's keyed
    # (park_token, student_hint) (see ParkBeat's docstring in db/models/live.py).
    # "beat_key" is a canonical-form-only sort key (never a real column on
    # either backend), built identically from both sides so the checksum's
    # sort order is deterministic.
    pk = "beat_key"

    def read_sqlite(self, conn):
        rows = conn.execute(
            "SELECT park_token, student_hint, state, first_seen_at, last_seen_at, "
            "transitions_json FROM park_beats"
        ).fetchall()
        return [
            {
                "beat_key": f"{r[0]}:{r[1]}",
                "park_token": r[0],
                "student_hint": r[1],
                "state": r[2],
                "first_seen_at": _canon_ts(r[3]),
                "last_seen_at": _canon_ts(r[4]),
                "transitions": _parse_json(r[5]) or [],
            }
            for r in rows
        ]

    def to_model(self, row):
        return ParkBeat(
            park_token=row["park_token"],
            student_hint=row["student_hint"],
            state=row["state"],
            first_seen_at=_parse_ts(row["first_seen_at"]),
            last_seen_at=_parse_ts(row["last_seen_at"]),
            transitions_json=row["transitions"],
        )

    def read_pg(self, session):
        return [
            {
                "beat_key": f"{b.park_token}:{b.student_hint}",
                "park_token": b.park_token,
                "student_hint": b.student_hint,
                "state": b.state,
                "first_seen_at": _canon_ts(b.first_seen_at),
                "last_seen_at": _canon_ts(b.last_seen_at),
                "transitions": b.transitions_json or [],
            }
            for b in session.query(ParkBeat).all()
        ]


# Insertion order respects the tenants FK: tenants first, then everything that
# references it. (audit_log has no tenant FK, but ordering it late is
# harmless; park_beats has no tenant FK either -- it isn't scoped to a
# student or tenant at all, see ParkBeat's docstring -- but it must still
# flush after park_sessions since a phone-park session logically precedes its
# beats even without a DB-level FK enforcing it.)
MIGRATORS: list[_Migrator] = [
    _TenantMigrator(),
    _UserMigrator(),
    _StudentProfileMigrator(),
    _StudentNameMigrator(),
    _ManifestMigrator(),
    _CorrectionMigrator(),
    _CalibrationRunMigrator(),
    _TunedThresholdsMigrator(),
    _FidelityMigrator(),
    _AiLikelihoodMigrator(),
    _BluebookExamMigrator(),
    _BluebookSubmissionMigrator(),
    _BluebookCourseMigrator(),
    _AuditMigrator(),
    _FormationMigrator(),
    _BaselineRequestMigrator(),
    _ParkSessionMigrator(),
    _ParkBeatMigrator(),
]


# ── Checksum ──────────────────────────────────────────────────────────────────
def _checksum(rows: list[dict], pk: str) -> str:
    """sha256 over the canonical rows, sorted by primary key so ordering never
    affects the digest. ``default=str`` covers any residual non-JSON scalar."""
    ordered = sorted(rows, key=lambda r: (r[pk] is None, r[pk]))
    blob = json.dumps(ordered, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ── Driver ────────────────────────────────────────────────────────────────────
def _referenced_tenants(sqlite_rows: dict) -> set[str]:
    """Every tenant_id a student-scoped row will reference in Postgres. SQLite
    ran with FK enforcement OFF, so its data can name tenants never registered
    in the tenants table (the demo sandbox, the tenancy-shim legacy-flat
    sentinel, a tenant derived from a scoped id but never explicitly created).
    Postgres enforces the FK, so those must exist before their children insert
    -- this is exactly what PostgresRepository._ensure_tenant_exists does at
    write time. Audit_log is excluded: it deliberately carries no tenant FK."""
    referenced: set[str] = set()
    for m in MIGRATORS:
        if m.name in ("tenants", "audit_log"):
            continue
        for inst in (m.to_model(r) for r in sqlite_rows[m.name]):
            tid = getattr(inst, "tenant_id", None)
            if tid:
                referenced.add(tid)
    return referenced


def migrate(sqlite_path: str, *, dry_run: bool = False) -> dict:
    """Run the migration (or, with dry_run, only read+checksum both sides).

    Returns a report dict: overall parity, a per-table row-count and checksum
    from each backend, plus any placeholder tenants backfilled for FK integrity
    (SQLite's FK-off data can reference unregistered tenants). Never prints --
    the CLI wrapper renders it."""
    conn = sqlite3.connect(sqlite_path)
    try:
        sqlite_rows = {m.name: m.read_sqlite(conn) for m in MIGRATORS}
    finally:
        conn.close()

    registered = {r["tenant_id"] for r in sqlite_rows["tenants"]}
    backfilled = sorted(_referenced_tenants(sqlite_rows) - registered)

    if not dry_run:
        with session_scope() as session:
            # Flush after each table, in MIGRATORS order (tenants first), so a
            # parent tenants row is committed to the DB before any child row's
            # FK is checked. A bare ForeignKey column without an ORM
            # relationship() does NOT drive SQLAlchemy's flush insert-ordering,
            # so a single add-everything-then-commit would flush in add order
            # and violate the tenants FK; the explicit per-table flush orders it.
            for m in MIGRATORS:
                if m.name == "tenants":
                    for row in sqlite_rows["tenants"]:
                        session.add(m.to_model(row))
                    for tid in backfilled:
                        # Placeholder row, matching _ensure_tenant_exists.
                        session.add(
                            Tenant(
                                tenant_id=tid,
                                name=tid,
                                environment="demo",
                                created_at=datetime.now(UTC),
                                meta_json={},
                            )
                        )
                else:
                    for row in sqlite_rows[m.name]:
                        session.add(m.to_model(row))
                session.flush()

    with session_scope() as session:
        pg_rows = {m.name: m.read_pg(session) for m in MIGRATORS}

    tables = []
    all_ok = True
    for m in MIGRATORS:
        s_rows, p_rows = sqlite_rows[m.name], pg_rows[m.name]
        if m.name == "tenants":
            # Parity = every SQLite tenant faithfully present in PG. Backfilled
            # placeholders legitimately make pg_rows exceed sqlite_rows, so
            # compare against the PG tenants that originated in SQLite only.
            p_from_sqlite = [r for r in p_rows if r["tenant_id"] in registered]
            s_sum, p_sum = _checksum(s_rows, m.pk), _checksum(p_from_sqlite, m.pk)
            ok = len(s_rows) == len(p_from_sqlite) and s_sum == p_sum
            entry = {
                "table": m.name,
                "sqlite_rows": len(s_rows),
                "pg_rows": len(p_rows),
                "backfilled_tenants": backfilled,
                "sqlite_checksum": s_sum,
                "pg_checksum": p_sum,
                "parity": ok,
            }
        else:
            s_sum, p_sum = _checksum(s_rows, m.pk), _checksum(p_rows, m.pk)
            ok = len(s_rows) == len(p_rows) and s_sum == p_sum
            entry = {
                "table": m.name,
                "sqlite_rows": len(s_rows),
                "pg_rows": len(p_rows),
                "sqlite_checksum": s_sum,
                "pg_checksum": p_sum,
                "parity": ok,
            }
        all_ok = all_ok and ok
        tables.append(entry)

    return {
        "dry_run": dry_run,
        "parity": all_ok,
        "backfilled_tenants": backfilled,
        "tables": tables,
    }


def _render(report: dict) -> str:
    lines = [
        f"{'table':<24} {'sqlite':>8} {'pg':>8}  parity",
        "-" * 52,
    ]
    for t in report["tables"]:
        mark = "OK" if t["parity"] else "MISMATCH"
        lines.append(f"{t['table']:<24} {t['sqlite_rows']:>8} {t['pg_rows']:>8}  {mark}")
    lines.append("-" * 52)
    if report.get("backfilled_tenants"):
        lines.append(
            "backfilled placeholder tenants (referenced but unregistered in "
            f"SQLite): {', '.join(report['backfilled_tenants'])}"
        )
    lines.append(
        f"overall parity: {'OK' if report['parity'] else 'FAILED'}"
        + (" (dry-run)" if report["dry_run"] else "")
    )
    return "\n".join(lines)


def main(argv=None) -> int:
    import os

    parser = argparse.ArgumentParser(description="Migrate the SQLite store into Postgres.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="read + checksum both backends without writing (pre-cutover parity check)",
    )
    parser.add_argument(
        "--report", type=Path, help="also write the full JSON report (with checksums) here"
    )
    args = parser.parse_args(argv)

    sqlite_path = os.environ.get("ORIGINAL_DB")
    if not sqlite_path:
        sqlite_path = str(Path(__file__).resolve().parent.parent / "profiles.db")
    if not Path(sqlite_path).exists():
        print(f"error: SQLite database not found at {sqlite_path}", file=sys.stderr)
        return 2
    if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
        print("error: DATABASE_URL must point at a postgresql:// instance", file=sys.stderr)
        return 2

    report = migrate(sqlite_path, dry_run=args.dry_run)
    print(_render(report))
    if args.report:
        args.report.write_text(json.dumps(report, indent=2, default=str))
        print(f"\nfull report written to {args.report}")
    return 0 if report["parity"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
