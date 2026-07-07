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

from typing import Protocol, runtime_checkable

from . import store
from .quantum.state import StudentState


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

    # ── Student state ────────────────────────────────────────────────────
    def get(self, student_id):
        self._todo("get")

    def get_or_create(self, student_id):
        self._todo("get_or_create")

    def put(self, state):
        self._todo("put")

    def list_ids(self):
        self._todo("list_ids")

    def all_states(self):
        self._todo("all_states")

    def count(self):
        self._todo("count")

    def clear(self):
        self._todo("clear")

    def delete_student(self, student_id):
        self._todo("delete_student")

    def list_ids_for_tenant(self, tenant_id):
        self._todo("list_ids_for_tenant")

    def set_display_name(self, student_id, name):
        self._todo("set_display_name")

    def get_display_name(self, student_id):
        self._todo("get_display_name")

    def roster_for_tenant(self, tenant_id):
        self._todo("roster_for_tenant")

    def delete_tenant_students(self, tenant_id):
        self._todo("delete_tenant_students")

    def student_data_inventory(self, student_id):
        self._todo("student_data_inventory")

    # ── Manifests ─────────────────────────────────────────────────────────
    def put_manifest(self, submission_id, student_id, manifest, divergence_score=None, action=None):
        self._todo("put_manifest")

    def get_manifest(self, submission_id):
        self._todo("get_manifest")

    def list_manifests(
        self, student_id=None, action=None, flag=None, since=None, until=None, limit=100, offset=0
    ):
        self._todo("list_manifests")

    def manifest_stats(self, since=None, until=None):
        self._todo("manifest_stats")

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
    def get_tenant(self, tenant_id):
        self._todo("get_tenant")

    def list_tenants(self, environment=None):
        self._todo("list_tenants")

    def put_tenant(self, tenant_id, name, environment="demo", meta=None):
        self._todo("put_tenant")

    def tenant_stats(self, tenant_id):
        self._todo("tenant_stats")

    # ── Users ─────────────────────────────────────────────────────────────
    def put_user(self, user_id, email, password_hash, role, tenant_id, name=""):
        self._todo("put_user")

    def get_user_by_email(self, email):
        self._todo("get_user_by_email")

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
    def log_audit(
        self, action, student_id=None, tenant_id=None, actor=None, result="ok", details=None
    ):
        self._todo("log_audit")

    def list_audit(self, student_id=None, action=None, limit=100, offset=0):
        self._todo("list_audit")

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
