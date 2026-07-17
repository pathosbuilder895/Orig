"""
repository.py — the persistence seam (ADR-002).

A single interface that every new feature routes through, so the demo
(SQLite) and v1 (Postgres) backends stop being parallel universes. The API
layer depends on ``Repository``, never on ``original.store`` directly.

Today only ``SqliteRepository`` exists (delegating to ``original.store``).
A ``PostgresRepository`` plugs in at ``get_repository()`` for the pilot /
production environments once the v1 SQLAlchemy models are extended to cover
these features. The ``environment`` argument is where that choice is made.

WS-6 P1 (docs/implementation/WS-6-postgres-convergence.md): this Protocol now
covers every public ``store.*`` function (formerly just the 9-method Formation
demonstrator slice) so ``api.py`` never reaches ``store`` directly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from . import store
from .constants import FEATURE_DIM
from .core.logging import get_logger
from .db.models.live import (
    AiLikelihoodScore,
    AuditLogEntry,
    Correction,
    FidelityScore,
    StaffUser,
    StudentName,
    StudentProfile,
    SubmissionManifest,
    Tenant,
)
from .db.postgres_session import session_scope
from .db.tenancy_shim import join_scoped_id, split_scoped_id
from .quantum.state import BaselineSample, StudentState

log = get_logger(__name__)


@runtime_checkable
class Repository(Protocol):
    """Storage operations the API depends on. Backend-agnostic."""

    # ── Student state ────────────────────────────────────────────────────
    def get(self, student_id: str) -> StudentState | None: ...
    def get_or_create(self, student_id: str) -> StudentState: ...
    def put(self, state: StudentState) -> None: ...
    def list_ids(self) -> list[str]: ...
    def all_states(self) -> list[StudentState]: ...
    def count(self) -> int: ...
    def clear(self) -> None: ...
    def delete_student(self, student_id: str) -> bool: ...
    def list_ids_for_tenant(self, tenant_id: str) -> list[str]: ...
    def set_display_name(self, student_id: str, name: str) -> None: ...
    def get_display_name(self, student_id: str) -> str: ...
    def roster_for_tenant(self, tenant_id: str) -> list[dict]: ...
    def delete_tenant_students(self, tenant_id: str) -> dict: ...
    def student_data_inventory(self, student_id: str) -> dict | None: ...

    # ── Manifests (Phase 3+ context audit trail) ────────────────────────────
    def put_manifest(
        self,
        submission_id: str,
        student_id: str,
        manifest: object,
        divergence_score: float | None = None,
        action: str | None = None,
    ) -> None: ...
    def get_manifest(self, submission_id: str) -> dict | None: ...
    def list_manifests(
        self,
        student_id: str | None = None,
        action: str | None = None,
        flag: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict: ...
    def manifest_stats(
        self,
        since: str | None = None,
        until: str | None = None,
    ) -> dict: ...
    def submission_student_id(self, submission_id: str) -> str | None: ...

    # ── Scores (fidelity + AI-likelihood + genre stats) ─────────────────────
    def put_fidelity_score(
        self,
        submission_id: str,
        student_id: str,
        fidelity: float,
        is_authentic: bool,
    ) -> None: ...
    def get_authentic_fidelities(self, student_id: str, limit: int = 200) -> list[float]: ...
    def update_fidelity_authenticity(self, submission_id: str, is_authentic: bool) -> None: ...
    def put_ai_likelihood_score(
        self,
        submission_id: str,
        student_id: str,
        probability: float,
        band: str,
        model_version: str = "",
    ) -> None: ...
    def get_ai_likelihood_scores(
        self,
        student_id: str | None = None,
        limit: int = 500,
    ) -> list[dict]: ...
    def get_genre_stats(self, genre: str) -> dict | None: ...

    # ── Corrections ──────────────────────────────────────────────────────
    def put_correction(
        self,
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
    ) -> int | None: ...
    def list_corrections(
        self,
        submission_id: str | None = None,
        student_id: str | None = None,
        is_correct: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict: ...

    # ── Calibration runs ─────────────────────────────────────────────────
    def start_calibration_run(
        self,
        dataset_label: str,
        run_label: str | None = None,
        config: dict | None = None,
    ) -> int | None: ...
    def complete_calibration_run(
        self,
        run_id: int,
        *,
        auc: float,
        n_essays_scored: int,
        n_authors: int,
        report: dict,
    ) -> bool: ...
    def fail_calibration_run(self, run_id: int, error: str) -> bool: ...
    def list_calibration_runs(
        self,
        status: str | None = None,
        dataset_label: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict: ...
    def get_calibration_run(self, run_id: int, include_report: bool = True) -> dict | None: ...

    # ── Tuned thresholds (tuned_thresholds_v2) ──────────────────────────────
    def put_tuned_thresholds(
        self,
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
    ) -> int | None: ...
    def get_active_tuned_thresholds(self) -> dict | None: ...
    def list_tuned_thresholds(self, limit: int = 50, offset: int = 0) -> dict: ...

    # ── Tenants ───────────────────────────────────────────────────────────
    def get_tenant(self, tenant_id: str) -> dict | None: ...
    def list_tenants(self, environment: str | None = None) -> list[dict]: ...
    def put_tenant(
        self,
        tenant_id: str,
        name: str,
        environment: str = "demo",
        meta: dict | None = None,
    ) -> None: ...
    def tenant_stats(self, tenant_id: str) -> dict: ...

    # ── Users ─────────────────────────────────────────────────────────────
    def put_user(
        self,
        user_id: str,
        email: str,
        password_hash: str,
        role: str,
        tenant_id: str,
        name: str = "",
    ) -> None: ...
    def get_user_by_email(self, email: str) -> dict | None: ...

    # ── Bluebook (exams, submissions, courses) ──────────────────────────────
    def put_bluebook_exam(self, rec: dict) -> None: ...
    def get_bluebook_exam(self, exam_id: str) -> dict | None: ...
    def list_bluebook_exams(self, tenant_id: str | None) -> list[dict]: ...
    def put_bluebook_submission(self, rec: dict) -> None: ...
    def list_bluebook_submissions(self, tenant_id: str | None) -> list[dict]: ...
    def put_bluebook_course(self, rec: dict) -> None: ...
    def list_bluebook_courses(self, tenant_id: str | None) -> list[dict]: ...

    # ── Audit log ─────────────────────────────────────────────────────────
    def log_audit(
        self,
        action: str,
        student_id: str | None = None,
        tenant_id: str | None = None,
        actor: str | None = None,
        result: str = "ok",
        details: dict | None = None,
    ) -> None: ...
    def list_audit(
        self,
        student_id: str | None = None,
        action: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict: ...

    # ── Formation pathways ────────────────────────────────────────────────
    def get_formation_pathway(self, student_id: str) -> dict | None: ...
    def open_formation_pathway(
        self,
        student_id: str,
        submission_id: str | None = None,
        reason: str | None = None,
    ) -> dict | None: ...
    def advance_formation_pathway(self, student_id: str) -> dict | None: ...

    # ── Baseline requests ─────────────────────────────────────────────────
    def put_baseline_request(
        self,
        external_request_id: str,
        student_id: str,
        status: str,
        requested_at: float,
        data_json: str,
    ) -> None: ...
    def load_baseline_requests(self) -> list[dict]: ...

    # ── DB path (replaces private store._DB_PATH reaches) ───────────────────
    def db_path(self) -> str: ...


class SqliteRepository:
    """Repository backed by the demo SQLite store (``original.store``)."""

    # ── Student state ────────────────────────────────────────────────────
    def get(self, student_id: str) -> StudentState | None:
        return store.get(student_id)

    def get_or_create(self, student_id: str) -> StudentState:
        return store.get_or_create(student_id)

    def put(self, state: StudentState) -> None:
        store.put(state)

    def list_ids(self) -> list[str]:
        return store.list_ids()

    def all_states(self) -> list[StudentState]:
        return store.all_states()

    def count(self) -> int:
        return store.count()

    def clear(self) -> None:
        store.clear()

    def delete_student(self, student_id: str) -> bool:
        return store.delete_student(student_id)

    def list_ids_for_tenant(self, tenant_id: str) -> list[str]:
        return store.list_ids_for_tenant(tenant_id)

    def set_display_name(self, student_id: str, name: str) -> None:
        store.set_display_name(student_id, name)

    def get_display_name(self, student_id: str) -> str:
        return store.get_display_name(student_id)

    def roster_for_tenant(self, tenant_id: str) -> list[dict]:
        return store.roster_for_tenant(tenant_id)

    def delete_tenant_students(self, tenant_id: str) -> dict:
        return store.delete_tenant_students(tenant_id)

    def student_data_inventory(self, student_id: str) -> dict | None:
        return store.student_data_inventory(student_id)

    # ── Manifests ─────────────────────────────────────────────────────────
    def put_manifest(
        self,
        submission_id: str,
        student_id: str,
        manifest: object,
        divergence_score: float | None = None,
        action: str | None = None,
    ) -> None:
        store.put_manifest(
            submission_id,
            student_id,
            manifest,
            divergence_score=divergence_score,
            action=action,
        )

    def get_manifest(self, submission_id: str) -> dict | None:
        return store.get_manifest(submission_id)

    def list_manifests(
        self,
        student_id: str | None = None,
        action: str | None = None,
        flag: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        return store.list_manifests(
            student_id=student_id,
            action=action,
            flag=flag,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )

    def manifest_stats(self, since: str | None = None, until: str | None = None) -> dict:
        return store.manifest_stats(since=since, until=until)

    def submission_student_id(self, submission_id: str) -> str | None:
        return store.submission_student_id(submission_id)

    # ── Scores ────────────────────────────────────────────────────────────
    def put_fidelity_score(
        self,
        submission_id: str,
        student_id: str,
        fidelity: float,
        is_authentic: bool,
    ) -> None:
        store.put_fidelity_score(submission_id, student_id, fidelity, is_authentic)

    def get_authentic_fidelities(self, student_id: str, limit: int = 200) -> list[float]:
        return store.get_authentic_fidelities(student_id, limit=limit)

    def update_fidelity_authenticity(self, submission_id: str, is_authentic: bool) -> None:
        store.update_fidelity_authenticity(submission_id, is_authentic)

    def put_ai_likelihood_score(
        self,
        submission_id: str,
        student_id: str,
        probability: float,
        band: str,
        model_version: str = "",
    ) -> None:
        store.put_ai_likelihood_score(
            submission_id,
            student_id,
            probability,
            band,
            model_version=model_version,
        )

    def get_ai_likelihood_scores(
        self,
        student_id: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        return store.get_ai_likelihood_scores(student_id=student_id, limit=limit)

    def get_genre_stats(self, genre: str) -> dict | None:
        return store.get_genre_stats(genre)

    # ── Corrections ──────────────────────────────────────────────────────
    def put_correction(
        self,
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
        return store.put_correction(
            submission_id,
            is_correct,
            student_id=student_id,
            original_verdict=original_verdict,
            original_action=original_action,
            original_divergence_score=original_divergence_score,
            corrected_verdict=corrected_verdict,
            corrected_action=corrected_action,
            reviewer=reviewer,
            notes=notes,
            created_at=created_at,
        )

    def list_corrections(
        self,
        submission_id: str | None = None,
        student_id: str | None = None,
        is_correct: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        return store.list_corrections(
            submission_id=submission_id,
            student_id=student_id,
            is_correct=is_correct,
            limit=limit,
            offset=offset,
        )

    # ── Calibration runs ─────────────────────────────────────────────────
    def start_calibration_run(
        self,
        dataset_label: str,
        run_label: str | None = None,
        config: dict | None = None,
    ) -> int | None:
        return store.start_calibration_run(dataset_label, run_label=run_label, config=config)

    def complete_calibration_run(
        self,
        run_id: int,
        *,
        auc: float,
        n_essays_scored: int,
        n_authors: int,
        report: dict,
    ) -> bool:
        return store.complete_calibration_run(
            run_id,
            auc=auc,
            n_essays_scored=n_essays_scored,
            n_authors=n_authors,
            report=report,
        )

    def fail_calibration_run(self, run_id: int, error: str) -> bool:
        return store.fail_calibration_run(run_id, error)

    def list_calibration_runs(
        self,
        status: str | None = None,
        dataset_label: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        return store.list_calibration_runs(
            status=status,
            dataset_label=dataset_label,
            limit=limit,
            offset=offset,
        )

    def get_calibration_run(self, run_id: int, include_report: bool = True) -> dict | None:
        return store.get_calibration_run(run_id, include_report=include_report)

    # ── Tuned thresholds ──────────────────────────────────────────────────
    def put_tuned_thresholds(
        self,
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
        return store.put_tuned_thresholds(
            no_action=no_action,
            monitor=monitor,
            escalate=escalate,
            source=source,
            source_run_id=source_run_id,
            verdict_authentic_below=verdict_authentic_below,
            verdict_anomalous_at_or_above=verdict_anomalous_at_or_above,
            notes=notes,
            provenance=provenance,
        )

    def get_active_tuned_thresholds(self) -> dict | None:
        return store.get_active_tuned_thresholds()

    def list_tuned_thresholds(self, limit: int = 50, offset: int = 0) -> dict:
        return store.list_tuned_thresholds(limit=limit, offset=offset)

    # ── Tenants ───────────────────────────────────────────────────────────
    def get_tenant(self, tenant_id: str) -> dict | None:
        return store.get_tenant(tenant_id)

    def list_tenants(self, environment: str | None = None) -> list[dict]:
        return store.list_tenants(environment=environment)

    def put_tenant(
        self,
        tenant_id: str,
        name: str,
        environment: str = "demo",
        meta: dict | None = None,
    ) -> None:
        store.put_tenant(tenant_id, name, environment=environment, meta=meta)

    def tenant_stats(self, tenant_id: str) -> dict:
        return store.tenant_stats(tenant_id)

    # ── Users ─────────────────────────────────────────────────────────────
    def put_user(
        self,
        user_id: str,
        email: str,
        password_hash: str,
        role: str,
        tenant_id: str,
        name: str = "",
    ) -> None:
        store.put_user(user_id, email, password_hash, role, tenant_id, name=name)

    def get_user_by_email(self, email: str) -> dict | None:
        return store.get_user_by_email(email)

    # ── Bluebook ──────────────────────────────────────────────────────────
    def put_bluebook_exam(self, rec: dict) -> None:
        store.put_bluebook_exam(rec)

    def get_bluebook_exam(self, exam_id: str) -> dict | None:
        return store.get_bluebook_exam(exam_id)

    def list_bluebook_exams(self, tenant_id: str | None) -> list[dict]:
        return store.list_bluebook_exams(tenant_id)

    def put_bluebook_submission(self, rec: dict) -> None:
        store.put_bluebook_submission(rec)

    def list_bluebook_submissions(self, tenant_id: str | None) -> list[dict]:
        return store.list_bluebook_submissions(tenant_id)

    def put_bluebook_course(self, rec: dict) -> None:
        store.put_bluebook_course(rec)

    def list_bluebook_courses(self, tenant_id: str | None) -> list[dict]:
        return store.list_bluebook_courses(tenant_id)

    # ── Audit log ─────────────────────────────────────────────────────────
    def log_audit(
        self,
        action: str,
        student_id: str | None = None,
        tenant_id: str | None = None,
        actor: str | None = None,
        result: str = "ok",
        details: dict | None = None,
    ) -> None:
        store.log_audit(
            action,
            student_id=student_id,
            tenant_id=tenant_id,
            actor=actor,
            result=result,
            details=details,
        )

    def list_audit(
        self,
        student_id: str | None = None,
        action: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        return store.list_audit(student_id=student_id, action=action, limit=limit, offset=offset)

    # ── Formation pathways ────────────────────────────────────────────────
    def get_formation_pathway(self, student_id: str) -> dict | None:
        return store.get_formation_pathway(student_id)

    def open_formation_pathway(
        self,
        student_id: str,
        submission_id: str | None = None,
        reason: str | None = None,
    ) -> dict | None:
        return store.open_formation_pathway(student_id, submission_id, reason)

    def advance_formation_pathway(self, student_id: str) -> dict | None:
        return store.advance_formation_pathway(student_id)

    # ── Baseline requests ─────────────────────────────────────────────────
    def put_baseline_request(
        self,
        external_request_id: str,
        student_id: str,
        status: str,
        requested_at: float,
        data_json: str,
    ) -> None:
        store.put_baseline_request(
            external_request_id,
            student_id,
            status,
            requested_at,
            data_json,
        )

    def load_baseline_requests(self) -> list[dict]:
        return store.load_baseline_requests()

    # ── DB path ───────────────────────────────────────────────────────────
    def db_path(self) -> str:
        return store._DB_PATH


class PostgresRepository:
    """
    Repository backed by the v1 Postgres/SQLAlchemy models — the pilot /
    production implementation (ADR-002 action item 4).

    Skeleton: the v1 models do not yet cover any of these aggregates. Each
    method raises until its model + query land, so the convergence work is
    explicit and discoverable rather than silently absent.

    When implemented, ``get_repository()`` selects this for
    ``environment in {"pilot", "production"}`` — the single switch point.
    """

    _NOT_READY = (
        "PostgresRepository.{op} is not implemented yet. Extend the v1 "
        "SQLAlchemy models to cover this, then wire it here (see ADR-002)."
    )

    def _todo(self, op: str):
        raise NotImplementedError(self._NOT_READY.format(op=op))

    @staticmethod
    def _ensure_tenant_exists(session, tenant_id: str, environment: str = "demo") -> None:
        """Idempotently insert a placeholder tenants row if absent.

        Several tables carry an FK to tenants (student_profiles,
        student_names, users, submission_manifests, ...). SQLite ran with FK
        enforcement off, so a write could reference a tenant_id that was
        never explicitly registered (the demo sandbox, the tenancy shim's
        legacy-flat sentinel, or simply out-of-order calls). Rather than
        rejecting those writes, seed a minimal row so the FK's referential
        promise holds without changing existing callers' behavior. A real
        ``put_tenant()`` call still overwrites name/environment/meta later.
        """
        stmt = (
            pg_insert(Tenant)
            .values(
                tenant_id=tenant_id,
                name=tenant_id,
                environment=environment,
                created_at=datetime.now(UTC),
                meta_json={},
            )
            .on_conflict_do_nothing(index_elements=["tenant_id"])
        )
        session.execute(stmt)

    # ── Student state ────────────────────────────────────────────────────
    @staticmethod
    def _state_to_doc(state: StudentState) -> dict:
        """Mirrors store.py's _serialize — a dict, not a JSON string,
        since StudentProfile.data is already a JSON/JSONB column."""
        return {
            "student_id": state.student_id,
            "samples": [
                {
                    "text": s.text,
                    "vector": s.vector.tolist(),
                    "provenance": s.provenance,
                    "auth_weight": s.auth_weight,
                    "assignment": s.assignment,
                    "submitted_at": s.submitted_at,
                    "genre": s.genre,
                    "topic_centroid": (
                        s.topic_centroid.tolist() if s.topic_centroid is not None else None
                    ),
                    "context_manifest": s.context_manifest,
                }
                for s in state.samples
            ],
            "baseline_kappa": state.baseline_kappa,
            "kappa_log": state.kappa_log,
            "consecutive_drift_count": state._consecutive_drift_count,
        }

    @staticmethod
    def _doc_to_state(doc: dict) -> StudentState:
        """Mirrors store.py's _deserialize, including the legacy-dimension
        padding fallback."""
        state = StudentState(
            student_id=doc["student_id"],
            baseline_kappa=doc.get("baseline_kappa"),
            kappa_log=doc.get("kappa_log", []),
        )
        state._consecutive_drift_count = int(doc.get("consecutive_drift_count", 0))
        for s in doc.get("samples", []):
            v = np.array(s["vector"], dtype=np.float64)
            if v.shape[0] != FEATURE_DIM:
                log.warning(
                    "Baseline vector for student %s has dimension %d; expected %d. "
                    "Padding missing dimensions with 0.5.",
                    doc["student_id"],
                    v.shape[0],
                    FEATURE_DIM,
                )
                padded = np.full(FEATURE_DIM, 0.5, dtype=np.float64)
                n = min(v.shape[0], FEATURE_DIM)
                padded[:n] = v[:n]
                v = padded
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
                    genre=s.get("genre"),
                    topic_centroid=topic_centroid,
                    context_manifest=s.get("context_manifest"),
                )
            )
        return state

    def get(self, student_id):
        try:
            with session_scope() as session:
                tenant_id, local_id = split_scoped_id(student_id)
                row = session.get(StudentProfile, (tenant_id, local_id))
                return self._doc_to_state(row.data) if row else None
        except Exception:
            log.exception("get failed for %s", student_id)
            return None

    def get_or_create(self, student_id):
        """SqliteRepository's get_or_create() inserts a fresh StudentState
        straight into the same in-memory dict get() reads from — a
        follow-up get() in the same process sees it immediately, with
        nothing persisted to SQLite until an explicit put(). Postgres has
        no shared cache across calls, so to honor that same "a follow-up
        get() sees the empty state" contract, an unknown id is persisted
        here immediately (an empty-samples row), not just returned."""
        try:
            with session_scope() as session:
                tenant_id, local_id = split_scoped_id(student_id)
                row = session.get(StudentProfile, (tenant_id, local_id))
                if row is not None:
                    return self._doc_to_state(row.data)
                self._ensure_tenant_exists(session, tenant_id)
                state = StudentState(student_id=student_id)
                stmt = (
                    pg_insert(StudentProfile)
                    .values(
                        tenant_id=tenant_id, student_id=local_id, data=self._state_to_doc(state)
                    )
                    .on_conflict_do_nothing(index_elements=["tenant_id", "student_id"])
                )
                session.execute(stmt)
                return state
        except Exception:
            log.exception("get_or_create failed for %s", student_id)
            return StudentState(student_id=student_id)

    def put(self, state):
        try:
            with session_scope() as session:
                tenant_id, local_id = split_scoped_id(state.student_id)
                self._ensure_tenant_exists(session, tenant_id)
                doc = self._state_to_doc(state)
                stmt = (
                    pg_insert(StudentProfile)
                    .values(tenant_id=tenant_id, student_id=local_id, data=doc)
                    .on_conflict_do_update(
                        index_elements=["tenant_id", "student_id"], set_={"data": doc}
                    )
                )
                session.execute(stmt)
        except Exception:
            log.exception("put failed for %s", state.student_id)
            raise  # mirror store.py's _persist: a write failure must surface, not vanish

    def list_ids(self):
        try:
            with session_scope() as session:
                rows = session.execute(
                    select(StudentProfile.tenant_id, StudentProfile.student_id)
                ).all()
                return [join_scoped_id(t, s) for t, s in rows]
        except Exception:
            log.exception("list_ids failed")
            return []

    def all_states(self):
        try:
            with session_scope() as session:
                rows = session.execute(select(StudentProfile)).scalars().all()
                return [self._doc_to_state(row.data) for row in rows]
        except Exception:
            log.exception("all_states failed")
            return []

    def count(self):
        try:
            with session_scope() as session:
                return session.execute(
                    select(func.count()).select_from(StudentProfile)
                ).scalar_one()
        except Exception:
            log.exception("count failed")
            return 0

    def clear(self):
        # store.clear() only empties SqliteRepository's in-memory cache and
        # never touches SQLite itself. Postgres has no such cache — every
        # call already reads the persisted rows directly — so there is
        # nothing to clear; a no-op preserves the identical observable
        # contract (persisted data survives clear() on both backends).
        pass

    def delete_student(self, student_id):
        # Every student-scoped table (per db/models/live.py's module
        # docstring) stores the LOCAL id in its own student_id column, with
        # tenant_id alongside as a separate FK column — NOT the full
        # "tenant:local" scoped string. Two different tenants can share the
        # same local id, so every match here filters on BOTH columns; a
        # local-id-only match would silently touch the wrong tenant's rows.
        try:
            with session_scope() as session:
                tenant_id, local_id = split_scoped_id(student_id)
                profile = session.get(StudentProfile, (tenant_id, local_id))
                if profile is None:
                    return False
                sub_ids = [
                    row[0]
                    for row in session.execute(
                        select(SubmissionManifest.submission_id).where(
                            SubmissionManifest.tenant_id == tenant_id,
                            SubmissionManifest.student_id == local_id,
                        )
                    ).all()
                ]
                session.delete(profile)
                session.execute(
                    FidelityScore.__table__.delete().where(
                        FidelityScore.tenant_id == tenant_id,
                        FidelityScore.student_id == local_id,
                    )
                )
                session.execute(
                    AiLikelihoodScore.__table__.delete().where(
                        AiLikelihoodScore.tenant_id == tenant_id,
                        AiLikelihoodScore.student_id == local_id,
                    )
                )
                session.execute(
                    SubmissionManifest.__table__.delete().where(
                        SubmissionManifest.tenant_id == tenant_id,
                        SubmissionManifest.student_id == local_id,
                    )
                )
                session.execute(
                    Correction.__table__.delete().where(
                        Correction.tenant_id == tenant_id,
                        Correction.student_id == local_id,
                    )
                )
                if sub_ids:
                    session.execute(
                        Correction.__table__.delete().where(Correction.submission_id.in_(sub_ids))
                    )
                name_row = session.get(StudentName, (tenant_id, local_id))
                if name_row is not None:
                    session.delete(name_row)
                return True
        except Exception:
            log.exception("delete_student failed for %s", student_id)
            return False

    def list_ids_for_tenant(self, tenant_id):
        # A real, indexed equality match on the FK column — not a
        # string-prefix scan. This is the point of the migration: tenant
        # isolation becomes a database constraint instead of a naming
        # convention (see db/models/live.py's StudentProfile docstring).
        try:
            with session_scope() as session:
                rows = session.execute(
                    select(StudentProfile.student_id).where(StudentProfile.tenant_id == tenant_id)
                ).all()
                return [join_scoped_id(tenant_id, s) for (s,) in rows]
        except Exception:
            log.exception("list_ids_for_tenant failed for %s", tenant_id)
            return []

    def set_display_name(self, student_id, name):
        name = (name or "").strip()
        if not name:
            return
        try:
            with session_scope() as session:
                tenant_id, local_id = split_scoped_id(student_id)
                self._ensure_tenant_exists(session, tenant_id)
                stmt = (
                    pg_insert(StudentName)
                    .values(
                        tenant_id=tenant_id,
                        student_id=local_id,
                        display_name=name,
                        updated_at=datetime.now(UTC),
                    )
                    .on_conflict_do_update(
                        index_elements=["tenant_id", "student_id"],
                        set_={"display_name": name, "updated_at": datetime.now(UTC)},
                    )
                )
                session.execute(stmt)
        except Exception:
            log.exception("set_display_name failed for %s", student_id)

    def get_display_name(self, student_id):
        try:
            with session_scope() as session:
                tenant_id, local_id = split_scoped_id(student_id)
                row = session.get(StudentName, (tenant_id, local_id))
                return row.display_name if row and row.display_name else ""
        except Exception:
            return ""

    @staticmethod
    def _status_for(sample_count: int, action: str | None) -> str:
        if sample_count <= 0:
            return "no_baseline"
        if action in ("escalate", "schedule_conversation"):
            return "needs_review"
        if action == "monitor":
            return "monitor"
        return "clear"

    def roster_for_tenant(self, tenant_id):
        try:
            with session_scope() as session:
                profile_rows = session.execute(
                    select(StudentProfile.student_id, StudentProfile.data).where(
                        StudentProfile.tenant_id == tenant_id
                    )
                ).all()
                name_rows = session.execute(
                    select(StudentName.student_id, StudentName.display_name).where(
                        StudentName.tenant_id == tenant_id
                    )
                ).all()
                names = {local: dn for local, dn in name_rows if dn}
                # ASC so the last write per student wins → most recent action.
                action_rows = session.execute(
                    select(SubmissionManifest.student_id, SubmissionManifest.action)
                    .where(SubmissionManifest.tenant_id == tenant_id)
                    .order_by(SubmissionManifest.created_at.asc())
                ).all()
                # Keyed by LOCAL id — SubmissionManifest.student_id is local
                # per db/models/live.py's module docstring, not the full
                # "tenant:local" string.
                latest_action: dict[str, str] = {}
                for local_sid, action in action_rows:
                    if action:
                        latest_action[local_sid] = action

                roster = []
                for local_id, data in sorted(profile_rows, key=lambda r: r[0]):
                    samples = data.get("samples", [])
                    sample_count = len(samples)
                    authenticated_count = sum(1 for s in samples if (s.get("auth_weight") or 0) > 0)
                    roster.append(
                        {
                            "id": join_scoped_id(tenant_id, local_id),
                            "name": names.get(local_id) or f"Student {local_id[:6]}",
                            "has_name": bool(names.get(local_id)),
                            "sample_count": sample_count,
                            "authenticated_count": authenticated_count,
                            "status": self._status_for(sample_count, latest_action.get(local_id)),
                        }
                    )
                return roster
        except Exception:
            log.exception("roster_for_tenant failed for %s", tenant_id)
            return []

    def delete_tenant_students(self, tenant_id):
        ids_to_delete = self.list_ids_for_tenant(tenant_id)
        deleted, failed = 0, []
        for sid in ids_to_delete:
            if self.delete_student(sid):
                deleted += 1
            else:
                failed.append(sid)
        self.log_audit(
            action="bulk_delete",
            tenant_id=tenant_id,
            result="ok" if not failed else "partial",
            details={"deleted_count": deleted, "failed_count": len(failed)},
        )
        return {"deleted_count": deleted, "failed_ids": failed}

    def student_data_inventory(self, student_id):
        try:
            with session_scope() as session:
                tenant_id, local_id = split_scoped_id(student_id)
                profile = session.get(StudentProfile, (tenant_id, local_id))
                if profile is None:
                    return None

                # Every student-scoped table stores the LOCAL id + a
                # separate tenant_id column (db/models/live.py's module
                # docstring) — filter on both, not the full scoped string.
                fidelity_count = session.execute(
                    select(func.count()).where(
                        FidelityScore.tenant_id == tenant_id, FidelityScore.student_id == local_id
                    )
                ).scalar_one()
                manifest_rows = session.execute(
                    select(
                        func.count(),
                        func.min(SubmissionManifest.created_at),
                        func.max(SubmissionManifest.created_at),
                        SubmissionManifest.action,
                    )
                    .where(
                        SubmissionManifest.tenant_id == tenant_id,
                        SubmissionManifest.student_id == local_id,
                    )
                    .group_by(SubmissionManifest.action)
                ).all()
                correction_count = session.execute(
                    select(func.count()).where(
                        Correction.tenant_id == tenant_id, Correction.student_id == local_id
                    )
                ).scalar_one()
                audit_count = session.execute(
                    select(func.count(AuditLogEntry.id)).where(
                        AuditLogEntry.tenant_id == tenant_id,
                        AuditLogEntry.student_id == local_id,
                    )
                ).scalar_one()
                ai_likelihood_count = session.execute(
                    select(func.count()).where(
                        AiLikelihoodScore.tenant_id == tenant_id,
                        AiLikelihoodScore.student_id == local_id,
                    )
                ).scalar_one()
                name_row = session.get(StudentName, (tenant_id, local_id))
                # Captured as plain values before the session closes below —
                # ORM attribute access on a detached instance raises.
                profile_data = profile.data
                has_display_name = bool(name_row and name_row.display_name)

            manifests_by_action: dict = {}
            for count, earliest, latest, action in manifest_rows:
                key = action or "unknown"
                manifests_by_action[key] = {
                    "count": count,
                    "earliest": earliest.isoformat() if earliest else None,
                    "latest": latest.isoformat() if latest else None,
                }

            samples = profile_data.get("samples", [])
            submitted_ats = [s.get("submitted_at") for s in samples if s.get("submitted_at")]
            state = self._doc_to_state(profile_data)
            return {
                "student_id": student_id,
                "data_categories": {
                    "baseline_samples": {
                        "count": len(samples),
                        "provenances": list({s.get("provenance") for s in samples}),
                        "earliest": min(submitted_ats, default=None),
                        "latest": max(submitted_ats, default=None),
                    },
                    "fidelity_scores": {"count": int(fidelity_count)},
                    "submission_manifests": {
                        "total": sum(v["count"] for v in manifests_by_action.values()),
                        "by_action": manifests_by_action,
                    },
                    "instructor_corrections": {"count": int(correction_count)},
                    "audit_log_entries": {"count": int(audit_count)},
                    "ai_likelihood_scores": {"count": int(ai_likelihood_count)},
                    "display_name": {"on_file": has_display_name},
                },
                "effective_sample_weight": state.effective_sample_count,
                "generated_at": datetime.now(UTC).isoformat(),
            }
        except Exception:
            log.exception("student_data_inventory failed for %s", student_id)
            return None

    # ── Manifests ─────────────────────────────────────────────────────────
    @staticmethod
    def _parse_iso_or_now(s: str | None):
        if s:
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                pass
        return datetime.now(UTC)

    def put_manifest(self, submission_id, student_id, manifest, divergence_score=None, action=None):
        try:
            if hasattr(manifest, "to_json"):
                manifest_doc = json.loads(manifest.to_json())
                created_at = getattr(manifest, "created_at", "") or ""
            elif isinstance(manifest, dict):
                manifest_doc = manifest
                created_at = manifest.get("created_at", "") or ""
            else:
                log.warning("put_manifest: unsupported manifest type %r", type(manifest))
                return
            with session_scope() as session:
                tenant_id, local_id = split_scoped_id(student_id)
                self._ensure_tenant_exists(session, tenant_id)
                stmt = (
                    pg_insert(SubmissionManifest)
                    .values(
                        submission_id=submission_id,
                        tenant_id=tenant_id,
                        student_id=local_id,
                        created_at=self._parse_iso_or_now(created_at),
                        manifest_json=manifest_doc,
                        divergence_score=divergence_score,
                        action=action,
                    )
                    .on_conflict_do_update(
                        index_elements=["submission_id"],
                        set_={
                            "tenant_id": tenant_id,
                            "student_id": local_id,
                            "created_at": self._parse_iso_or_now(created_at),
                            "manifest_json": manifest_doc,
                            "divergence_score": divergence_score,
                            "action": action,
                        },
                    )
                )
                session.execute(stmt)
        except Exception as e:
            log.warning("put_manifest failed for %s: %s", submission_id, e)

    def get_manifest(self, submission_id):
        try:
            with session_scope() as session:
                row = session.get(SubmissionManifest, submission_id)
                if row is None:
                    return None
                return {
                    "submission_id": submission_id,
                    "student_id": join_scoped_id(row.tenant_id, row.student_id),
                    "created_at": row.created_at.isoformat(),
                    "manifest": row.manifest_json,
                    "divergence_score": row.divergence_score,
                    "action": row.action,
                }
        except Exception:
            return None

    def list_manifests(
        self, student_id=None, action=None, flag=None, since=None, until=None, limit=100, offset=0
    ):
        try:
            with session_scope() as session:
                stmt = select(SubmissionManifest)
                if student_id is not None:
                    tenant_id, local_id = split_scoped_id(student_id)
                    stmt = stmt.where(
                        SubmissionManifest.tenant_id == tenant_id,
                        SubmissionManifest.student_id == local_id,
                    )
                if action is not None:
                    stmt = stmt.where(SubmissionManifest.action == action)
                if since is not None:
                    stmt = stmt.where(
                        SubmissionManifest.created_at >= self._parse_iso_or_now(since)
                    )
                if until is not None:
                    stmt = stmt.where(
                        SubmissionManifest.created_at <= self._parse_iso_or_now(until)
                    )
                if flag is not None:
                    # JSONB containment check on the flags array — no LIKE
                    # substring match needed (and so no wildcard-escaping
                    # concern at all, unlike the SQLite implementation).
                    stmt = stmt.where(
                        SubmissionManifest.manifest_json["flags"].as_string().contains(flag)
                    )
                total = session.execute(
                    select(func.count()).select_from(stmt.subquery())
                ).scalar_one()
                rows = (
                    session.execute(
                        stmt.order_by(SubmissionManifest.created_at.desc())
                        .limit(limit)
                        .offset(offset)
                    )
                    .scalars()
                    .all()
                )

                # Built inside the session: ORM attribute access after the
                # `with` block closes raises DetachedInstanceError.
                items = []
                for row in rows:
                    m = row.manifest_json or {}
                    items.append(
                        {
                            "submission_id": row.submission_id,
                            "student_id": join_scoped_id(row.tenant_id, row.student_id),
                            "created_at": row.created_at.isoformat(),
                            "divergence_score": row.divergence_score,
                            "action": row.action,
                            "flags": list(m.get("flags") or []),
                            "anchor_tiers": list(m.get("anchor_tiers") or []),
                            "length_regime": m.get("length_regime") or "unknown",
                        }
                    )
                return {"total": int(total), "limit": limit, "offset": offset, "items": items}
        except Exception as e:
            log.warning("list_manifests failed: %s", e)
            return {"total": 0, "limit": limit, "offset": offset, "items": []}

    def manifest_stats(self, since=None, until=None):
        by_action: dict[str, int] = {}
        by_flag: dict[str, int] = {}
        by_length_regime: dict[str, int] = {}
        divergence_sum, divergence_n, total = 0.0, 0, 0
        try:
            with session_scope() as session:
                stmt = select(
                    SubmissionManifest.action,
                    SubmissionManifest.manifest_json,
                    SubmissionManifest.divergence_score,
                )
                if since is not None:
                    stmt = stmt.where(
                        SubmissionManifest.created_at >= self._parse_iso_or_now(since)
                    )
                if until is not None:
                    stmt = stmt.where(
                        SubmissionManifest.created_at <= self._parse_iso_or_now(until)
                    )
                for action, manifest_json, divergence_score in session.execute(stmt):
                    total += 1
                    by_action[action or "unknown"] = by_action.get(action or "unknown", 0) + 1
                    m = manifest_json or {}
                    for f in m.get("flags") or []:
                        by_flag[f] = by_flag.get(f, 0) + 1
                    regime = m.get("length_regime") or "unknown"
                    by_length_regime[regime] = by_length_regime.get(regime, 0) + 1
                    if divergence_score is not None:
                        divergence_sum += float(divergence_score)
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

    def submission_student_id(self, submission_id):
        m = self.get_manifest(submission_id)
        if m is not None and m.get("student_id"):
            return str(m["student_id"])
        try:
            with session_scope() as session:
                # JSONB key lookup, not a LIKE substring match — immune to
                # the SQLite implementation's need to escape '_'/'%'
                # wildcards, since there's no pattern matching involved.
                row = session.execute(
                    select(AuditLogEntry.tenant_id, AuditLogEntry.student_id)
                    .where(
                        AuditLogEntry.action == "score",
                        AuditLogEntry.details_json["submission_id"].as_string() == submission_id,
                    )
                    .order_by(AuditLogEntry.created_at.desc())
                    .limit(1)
                ).first()
                if row is not None and row[1]:
                    return join_scoped_id(row[0], row[1]) if row[0] else row[1]
        except Exception:
            pass
        return None

    # ── Scores ────────────────────────────────────────────────────────────
    def put_fidelity_score(self, submission_id, student_id, fidelity, is_authentic):
        self._todo("put_fidelity_score")

    def get_authentic_fidelities(self, student_id, limit=200):
        self._todo("get_authentic_fidelities")

    def update_fidelity_authenticity(self, submission_id, is_authentic):
        self._todo("update_fidelity_authenticity")

    def put_ai_likelihood_score(
        self, submission_id, student_id, probability, band, model_version=""
    ):
        self._todo("put_ai_likelihood_score")

    def get_ai_likelihood_scores(self, student_id=None, limit=500):
        self._todo("get_ai_likelihood_scores")

    def get_genre_stats(self, genre):
        self._todo("get_genre_stats")

    # ── Corrections ──────────────────────────────────────────────────────
    def put_correction(
        self,
        submission_id,
        is_correct,
        *,
        student_id=None,
        original_verdict=None,
        original_action=None,
        original_divergence_score=None,
        corrected_verdict=None,
        corrected_action=None,
        reviewer=None,
        notes=None,
        created_at=None,
    ):
        self._todo("put_correction")

    def list_corrections(
        self, submission_id=None, student_id=None, is_correct=None, limit=100, offset=0
    ):
        self._todo("list_corrections")

    # ── Calibration runs ─────────────────────────────────────────────────
    def start_calibration_run(self, dataset_label, run_label=None, config=None):
        self._todo("start_calibration_run")

    def complete_calibration_run(self, run_id, *, auc, n_essays_scored, n_authors, report):
        self._todo("complete_calibration_run")

    def fail_calibration_run(self, run_id, error):
        self._todo("fail_calibration_run")

    def list_calibration_runs(self, status=None, dataset_label=None, limit=50, offset=0):
        self._todo("list_calibration_runs")

    def get_calibration_run(self, run_id, include_report=True):
        self._todo("get_calibration_run")

    # ── Tuned thresholds ──────────────────────────────────────────────────
    def put_tuned_thresholds(
        self,
        *,
        no_action,
        monitor,
        escalate,
        source,
        source_run_id=None,
        verdict_authentic_below=None,
        verdict_anomalous_at_or_above=None,
        notes=None,
        provenance=None,
    ):
        self._todo("put_tuned_thresholds")

    def get_active_tuned_thresholds(self):
        self._todo("get_active_tuned_thresholds")

    def list_tuned_thresholds(self, limit=50, offset=0):
        self._todo("list_tuned_thresholds")

    # ── Tenants ───────────────────────────────────────────────────────────
    @staticmethod
    def _tenant_to_dict(row: Tenant) -> dict:
        return {
            "tenant_id": row.tenant_id,
            "name": row.name,
            "environment": row.environment,
            "created_at": row.created_at.isoformat(),
            "meta": row.meta_json or {},
        }

    def get_tenant(self, tenant_id):
        try:
            with session_scope() as session:
                row = session.get(Tenant, tenant_id)
                return self._tenant_to_dict(row) if row else None
        except Exception:
            log.exception("get_tenant failed for %s", tenant_id)
            return None

    def list_tenants(self, environment=None):
        try:
            with session_scope() as session:
                stmt = select(Tenant)
                if environment:
                    stmt = stmt.where(Tenant.environment == environment)
                rows = session.execute(stmt).scalars().all()
                return [self._tenant_to_dict(r) for r in rows]
        except Exception:
            log.exception("list_tenants failed (environment=%s)", environment)
            return []

    def put_tenant(self, tenant_id, name, environment="demo", meta=None):
        try:
            with session_scope() as session:
                stmt = (
                    pg_insert(Tenant)
                    .values(
                        tenant_id=tenant_id,
                        name=name,
                        environment=environment,
                        created_at=datetime.now(UTC),
                        meta_json=meta or {},
                    )
                    .on_conflict_do_update(
                        index_elements=["tenant_id"],
                        # created_at is intentionally omitted — preserved
                        # from the first insert, matching SqliteRepository's
                        # ON CONFLICT clause.
                        set_={
                            "name": name,
                            "environment": environment,
                            "meta_json": meta or {},
                        },
                    )
                )
                session.execute(stmt)
        except Exception:
            log.exception("put_tenant failed for %s", tenant_id)

    def tenant_stats(self, tenant_id):
        try:
            with session_scope() as session:
                student_count, sample_count = 0, 0
                profile_rows = session.execute(
                    select(StudentProfile.data).where(StudentProfile.tenant_id == tenant_id)
                ).all()
                for (data,) in profile_rows:
                    student_count += 1
                    sample_count += len(data.get("samples", []))

                # A real equality match on the FK column — no LIKE-wildcard
                # escaping needed (unlike SqliteRepository's tenant_stats,
                # which prefix-scans a flat string column). This is the
                # point of the migration: tenant isolation is a database
                # constraint here, not a string convention.
                submission_count, last_active_at = session.execute(
                    select(func.count(), func.max(SubmissionManifest.created_at)).where(
                        SubmissionManifest.tenant_id == tenant_id
                    )
                ).one()
                action_rows = session.execute(
                    select(SubmissionManifest.action, func.count())
                    .where(
                        SubmissionManifest.tenant_id == tenant_id,
                        SubmissionManifest.action.is_not(None),
                    )
                    .group_by(SubmissionManifest.action)
                ).all()
                action_counts = {action: n for action, n in action_rows}
        except Exception:
            log.exception("tenant_stats DB query failed for %s", tenant_id)
            return {
                "tenant_id": tenant_id,
                "student_count": 0,
                "sample_count": 0,
                "submission_count": 0,
                "last_active_at": None,
                "action_counts": {},
            }

        return {
            "tenant_id": tenant_id,
            "student_count": student_count,
            "sample_count": sample_count,
            "submission_count": int(submission_count or 0),
            "last_active_at": last_active_at.isoformat() if last_active_at else None,
            "action_counts": action_counts,
        }

    # ── Users ─────────────────────────────────────────────────────────────
    @staticmethod
    def _user_to_dict(row: StaffUser) -> dict:
        return {
            "user_id": row.user_id,
            "email": row.email,
            "password_hash": row.password_hash,
            "role": row.role,
            "tenant_id": row.tenant_id,
            "name": row.name,
            "created_at": row.created_at.isoformat(),
        }

    def put_user(self, user_id, email, password_hash, role, tenant_id, name=""):
        try:
            with session_scope() as session:
                self._ensure_tenant_exists(session, tenant_id)
                normalized_email = email.strip().lower()
                stmt = (
                    pg_insert(StaffUser)
                    .values(
                        user_id=user_id,
                        email=normalized_email,
                        password_hash=password_hash,
                        role=role,
                        tenant_id=tenant_id,
                        name=name,
                        created_at=datetime.now(UTC),
                    )
                    .on_conflict_do_update(
                        index_elements=["user_id"],
                        set_={
                            "email": normalized_email,
                            "password_hash": password_hash,
                            "role": role,
                            "tenant_id": tenant_id,
                            "name": name,
                        },
                    )
                )
                session.execute(stmt)
        except Exception:
            log.exception("put_user failed for %s", email)

    def get_user_by_email(self, email):
        try:
            with session_scope() as session:
                normalized_email = email.strip().lower()
                stmt = select(StaffUser).where(StaffUser.email == normalized_email)
                row = session.execute(stmt).scalar_one_or_none()
                return self._user_to_dict(row) if row else None
        except Exception:
            log.exception("get_user_by_email failed for %s", email)
            return None

    # ── Bluebook ──────────────────────────────────────────────────────────
    def put_bluebook_exam(self, rec):
        self._todo("put_bluebook_exam")

    def get_bluebook_exam(self, exam_id):
        self._todo("get_bluebook_exam")

    def list_bluebook_exams(self, tenant_id):
        self._todo("list_bluebook_exams")

    def put_bluebook_submission(self, rec):
        self._todo("put_bluebook_submission")

    def list_bluebook_submissions(self, tenant_id):
        self._todo("list_bluebook_submissions")

    def put_bluebook_course(self, rec):
        self._todo("put_bluebook_course")

    def list_bluebook_courses(self, tenant_id):
        self._todo("list_bluebook_courses")

    # ── Audit ─────────────────────────────────────────────────────────────
    @staticmethod
    def _split_for_audit(
        student_id: str | None, tenant_id: str | None
    ) -> tuple[str | None, str | None]:
        """audit_log's student_id is nullable and its tenant_id is genuinely
        NULL for a colon-less student_id (unlike every other student-scoped
        table, which assigns the tenancy shim's legacy-flat sentinel) — this
        mirrors store.py's own "only derive when tenant_id is None AND
        student_id has a colon" rule exactly, not the general shim."""
        if student_id and ":" in student_id and tenant_id is None:
            tenant_id, student_id = student_id.split(":", 1)
        return tenant_id, student_id

    def log_audit(
        self, action, student_id=None, tenant_id=None, actor=None, result="ok", details=None
    ):
        try:
            tenant_id, local_student_id = self._split_for_audit(student_id, tenant_id)
            with session_scope() as session:
                session.add(
                    AuditLogEntry(
                        created_at=datetime.now(UTC),
                        action=action,
                        student_id=local_student_id,
                        tenant_id=tenant_id,
                        actor=actor,
                        result=result,
                        details_json=details or {},
                    )
                )
        except Exception:
            log.exception("log_audit silently failed for action=%s student=%s", action, student_id)

    def list_audit(self, student_id=None, action=None, limit=100, offset=0):
        limit = min(limit, 1000)
        try:
            with session_scope() as session:
                stmt = select(AuditLogEntry)
                if student_id:
                    tenant_id, local_id = self._split_for_audit(student_id, None)
                    if tenant_id is not None:
                        stmt = stmt.where(
                            AuditLogEntry.tenant_id == tenant_id,
                            AuditLogEntry.student_id == local_id,
                        )
                    else:
                        stmt = stmt.where(AuditLogEntry.student_id == local_id)
                if action:
                    stmt = stmt.where(AuditLogEntry.action == action)
                total = session.execute(
                    select(func.count()).select_from(stmt.subquery())
                ).scalar_one()
                rows = (
                    session.execute(
                        stmt.order_by(AuditLogEntry.created_at.desc()).limit(limit).offset(offset)
                    )
                    .scalars()
                    .all()
                )
                return {
                    "total": int(total),
                    "limit": limit,
                    "offset": offset,
                    "items": [
                        {
                            "id": row.id,
                            "created_at": row.created_at.isoformat(),
                            "action": row.action,
                            "student_id": (
                                join_scoped_id(row.tenant_id, row.student_id)
                                if row.tenant_id
                                else row.student_id
                            ),
                            "tenant_id": row.tenant_id,
                            "actor": row.actor,
                            "result": row.result,
                            "details": row.details_json or {},
                        }
                        for row in rows
                    ],
                }
        except Exception:
            log.exception("list_audit failed")
            return {"total": 0, "limit": limit, "offset": offset, "items": []}

    # ── Formation ─────────────────────────────────────────────────────────
    def get_formation_pathway(self, student_id):
        self._todo("get_formation_pathway")

    def open_formation_pathway(self, student_id, submission_id=None, reason=None):
        self._todo("open_formation_pathway")

    def advance_formation_pathway(self, student_id):
        self._todo("advance_formation_pathway")

    # ── Baseline requests ─────────────────────────────────────────────────
    def put_baseline_request(
        self, external_request_id, student_id, status, requested_at, data_json
    ):
        self._todo("put_baseline_request")

    def load_baseline_requests(self):
        self._todo("load_baseline_requests")

    # ── DB path ───────────────────────────────────────────────────────────
    def db_path(self):
        self._todo("db_path")


# ── Factory ───────────────────────────────────────────────────────────────────

_REPO: Repository | None = None


def get_repository(environment: str = "demo") -> Repository:
    """
    Return the repository for the given environment — the single switch point
    for the demo/v1 split (ADR-002).

    - demo                 → SqliteRepository (local, zero-dependency)
    - pilot | production   → PostgresRepository once its models land; until
                             then it also resolves to SQLite so nothing breaks,
                             and the NotImplementedError surfaces only when an
                             unported operation is actually called.

    Cached as a module singleton.
    """
    global _REPO
    if _REPO is None:
        # Postgres impl is a skeleton today; keep SQLite as the working default
        # for every environment. Flip this to PostgresRepository() per
        # environment as the v1 models are extended.
        _REPO = SqliteRepository()
    return _REPO


def reset_repository() -> None:
    """Test hook — drop the cached singleton so a fresh one is built."""
    global _REPO
    _REPO = None
