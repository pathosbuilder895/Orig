"""
postgres_repository.py — PostgresRepository (WS-6 P3, ADR-002 action item 4).

Split out of repository.py deliberately, not for size. requirements-demo.txt
and requirements-pilot.txt explicitly exclude sqlalchemy/psycopg2/alembic
("demo uses SQLite via store.py, no ORM") to keep the demo/pilot dependency
set light. PostgresRepository imports sqlalchemy at module level; if it
lived in repository.py, that import would run whenever anything imports
``original.repository`` -- which api.py does unconditionally, in every
environment, including plain SQLite demo/pilot runs. Keeping it in its own
module lets repository.py's ``PostgresRepository`` re-export
(``__getattr__``, PEP 562) defer the sqlalchemy import until something
actually asks for the class -- which today is only tests and
tools that explicitly opt into a Postgres backend, never api.py's own
import graph. get_repository() never constructs a PostgresRepository (see
its own docstring) — this module's sqlalchemy import is therefore reachable
today only via an explicit ``from original.repository import
PostgresRepository`` or ``original.postgres_repository`` import, not via the
demo/pilot server's normal startup path.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .constants import FEATURE_DIM
from .core.logging import get_logger
from .db.models.live import (
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
from .db.postgres_session import session_scope
from .db.tenancy_shim import _LEGACY_FLAT_TENANT, join_scoped_id, split_scoped_id
from .quantum.state import BaselineSample, StudentState

# The phone-park timestamp format, transition cap, and genre-prior cold-start
# floors are defined once, in the SQLite store, and imported here so the two
# backends cannot drift apart on any of them. genre_stats_from_groups carries
# both genre-prior floors and the leave-one-out exclusion, so neither backend
# can apply them differently. store.py carries no sqlalchemy
# import, so this costs nothing.
from .store import (
    PARK_MAX_TRANSITIONS,
    genre_stats_from_groups,
    park_iso_utc,
    park_utc,
)

log = get_logger(__name__)


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

    def __init__(self):
        # Mirrors store.py's module-level _GENRE_STATS_CACHE, but scoped to
        # this instance rather than the process: get_repository() caches a
        # single PostgresRepository singleton in production (so this behaves
        # identically to a process-global cache there), while each test in
        # test_repository_contract.py gets its own fresh instance/cache —
        # avoiding cross-test leakage a module-level dict would risk.
        # A genre of None is the genre-agnostic cohort pool (get_cohort_stats)
        # — its own key in the same cache, mirroring store._GENRE_STATS_CACHE.
        self._genre_stats_cache: dict[tuple[str | None, str | None], list[tuple[str, list]]] = {}

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
            # Bust the genre-stats cache — a new sample may shift the
            # cross-student genre distribution get_genre_stats() aggregates.
            self._genre_stats_cache.clear()
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
            # this student's tenant's (tenant, genre) entries may include them
            self._genre_stats_cache.clear()
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
        try:
            with session_scope() as session:
                tenant_id, local_id = split_scoped_id(student_id)
                self._ensure_tenant_exists(session, tenant_id)
                stmt = (
                    pg_insert(FidelityScore)
                    .values(
                        submission_id=submission_id,
                        tenant_id=tenant_id,
                        student_id=local_id,
                        fidelity=float(fidelity),
                        is_authentic=bool(is_authentic),
                        created_at=datetime.now(UTC),
                    )
                    .on_conflict_do_update(
                        index_elements=["submission_id"],
                        set_={
                            "tenant_id": tenant_id,
                            "student_id": local_id,
                            "fidelity": float(fidelity),
                            "is_authentic": bool(is_authentic),
                            "created_at": datetime.now(UTC),
                        },
                    )
                )
                session.execute(stmt)
        except Exception:
            log.exception("put_fidelity_score failed for %s", submission_id)

    def get_authentic_fidelities(self, student_id, limit=200):
        try:
            with session_scope() as session:
                tenant_id, local_id = split_scoped_id(student_id)
                rows = session.execute(
                    select(FidelityScore.fidelity)
                    .where(
                        FidelityScore.tenant_id == tenant_id,
                        FidelityScore.student_id == local_id,
                        FidelityScore.is_authentic.is_(True),
                    )
                    .order_by(FidelityScore.created_at.desc())
                    .limit(limit)
                ).all()
                return [float(f) for (f,) in rows]
        except Exception:
            log.exception("get_authentic_fidelities failed for %s", student_id)
            return []

    def update_fidelity_authenticity(self, submission_id, is_authentic):
        try:
            with session_scope() as session:
                session.execute(
                    FidelityScore.__table__.update()
                    .where(FidelityScore.submission_id == submission_id)
                    .values(is_authentic=bool(is_authentic))
                )
        except Exception:
            log.exception("update_fidelity_authenticity failed for submission %s", submission_id)

    def put_ai_likelihood_score(
        self, submission_id, student_id, probability, band, model_version=""
    ):
        try:
            with session_scope() as session:
                tenant_id, local_id = split_scoped_id(student_id)
                self._ensure_tenant_exists(session, tenant_id)
                stmt = (
                    pg_insert(AiLikelihoodScore)
                    .values(
                        submission_id=submission_id,
                        tenant_id=tenant_id,
                        student_id=local_id,
                        probability=float(probability),
                        band=str(band),
                        model_version=str(model_version),
                        created_at=datetime.now(UTC),
                    )
                    .on_conflict_do_update(
                        index_elements=["submission_id"],
                        set_={
                            "tenant_id": tenant_id,
                            "student_id": local_id,
                            "probability": float(probability),
                            "band": str(band),
                            "model_version": str(model_version),
                            "created_at": datetime.now(UTC),
                        },
                    )
                )
                session.execute(stmt)
        except Exception:
            log.exception("put_ai_likelihood_score failed for %s", submission_id)

    def get_ai_likelihood_scores(self, student_id=None, limit=500):
        try:
            with session_scope() as session:
                stmt = select(AiLikelihoodScore)
                if student_id is not None:
                    tenant_id, local_id = split_scoped_id(student_id)
                    stmt = stmt.where(
                        AiLikelihoodScore.tenant_id == tenant_id,
                        AiLikelihoodScore.student_id == local_id,
                    )
                rows = (
                    session.execute(stmt.order_by(AiLikelihoodScore.created_at.desc()).limit(limit))
                    .scalars()
                    .all()
                )
                return [
                    {
                        "submission_id": row.submission_id,
                        "student_id": join_scoped_id(row.tenant_id, row.student_id),
                        "probability": float(row.probability),
                        "band": row.band,
                        "model_version": row.model_version,
                        "created_at": row.created_at.isoformat(),
                    }
                    for row in rows
                ]
        except Exception:
            log.exception("get_ai_likelihood_scores failed")
            return []

    def get_genre_stats(self, genre, tenant, exclude_student_id):
        """Tenant-scoped, self-excluding genre prior — see
        store.get_genre_stats's docstring for the full contract.
        """
        return genre_stats_from_groups(self._pool_groups(tenant, genre), exclude_student_id)

    def get_cohort_stats(self, tenant, exclude_student_id):
        """Tenant-scoped, self-excluding genre-AGNOSTIC cohort prior — see
        store.get_cohort_stats's docstring for the full contract.

        Same pool scan as get_genre_stats with the genre filter dropped, and
        the same shared genre_stats_from_groups for the floors, the
        leave-one-out exclusion and n_students, so neither the two priors nor
        the two backends can drift apart on any of them.
        """
        return genre_stats_from_groups(self._pool_groups(tenant, None), exclude_student_id)

    def _pool_groups(self, tenant, genre):
        """The authenticated-sample pool for one ``(tenant, genre)``, grouped
        by student and memoised in ``self._genre_stats_cache``.  ``genre=None``
        drops the genre filter (the cohort pool).

        Filters with an indexed equality match on StudentProfile.tenant_id —
        the same "database constraint instead of a naming convention" the FK
        column exists for — rather than pulling every tenant's profile JSON
        and discarding non-matching rows in Python. A None `tenant` (the
        legacy-flat pool) maps to db.tenancy_shim._LEGACY_FLAT_TENANT exactly
        like split_scoped_id does, since that's the sentinel legacy-flat ids
        actually carry on this column (comparing the column to Python `None`
        would translate to SQL `IS NULL`, which no row would ever satisfy).
        """
        key = (tenant, genre)
        groups = self._genre_stats_cache.get(key)
        if groups is not None:
            return groups

        tenant_id_column_value = tenant if tenant is not None else _LEGACY_FLAT_TENANT
        try:
            with session_scope() as session:
                rows = (
                    session.execute(
                        select(StudentProfile.data).where(
                            StudentProfile.tenant_id == tenant_id_column_value
                        )
                    )
                    .scalars()
                    .all()
                )
        except Exception:
            log.exception("genre/cohort pool query failed for genre %s tenant %s", genre, tenant)
            # Deliberately NOT cached: a transient DB error must not pin an
            # empty pool until the next write. Returning [] here makes the
            # caller's floors fail closed (no prior), same as a cold pool.
            return []

        groups = []
        for data in rows:
            # The doc's own student_id is the full scoped id (_state_to_doc
            # writes state.student_id verbatim, and _doc_to_state feeds it
            # straight back into StudentState.student_id), so it matches
            # the value the caller passes as exclude_student_id.
            student_vectors = [
                np.array(sample["vector"], dtype=np.float64)
                for sample in data.get("samples", [])
                if (sample.get("auth_weight") or 0) > 0
                and (genre is None or sample.get("genre") == genre)
            ]
            if student_vectors:
                groups.append((data.get("student_id"), student_vectors))
        self._genre_stats_cache[key] = groups
        return groups

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
        try:
            created_at_dt = self._parse_iso_or_now(created_at) if created_at else datetime.now(UTC)
            if (
                original_verdict is None
                or original_action is None
                or original_divergence_score is None
                or student_id is None
            ):
                existing = self.get_manifest(submission_id)
                if existing is not None:
                    student_id = student_id or existing.get("student_id")
                    original_action = original_action or existing.get("action")
                    if original_divergence_score is None:
                        original_divergence_score = existing.get("divergence_score")
            if student_id is None:
                # submission_student_id already covers the same manifest ->
                # audit_log fallback chain store.py's put_correction inlines.
                student_id = self.submission_student_id(submission_id)

            tenant_id, local_id = (None, None)
            if student_id is not None:
                tenant_id, local_id = split_scoped_id(student_id)

            with session_scope() as session:
                if tenant_id is not None:
                    self._ensure_tenant_exists(session, tenant_id)
                row = Correction(
                    submission_id=submission_id,
                    tenant_id=tenant_id,
                    student_id=local_id,
                    original_verdict=original_verdict,
                    original_action=original_action,
                    original_divergence_score=original_divergence_score,
                    corrected_verdict=corrected_verdict,
                    corrected_action=corrected_action,
                    is_correct=bool(is_correct),
                    reviewer=reviewer,
                    notes=notes,
                    created_at=created_at_dt,
                )
                session.add(row)
                session.flush()
                return row.id
        except Exception as e:
            log.warning("put_correction failed for %s: %s", submission_id, e)
            return None

    def list_corrections(
        self, submission_id=None, student_id=None, is_correct=None, limit=100, offset=0
    ):
        try:
            with session_scope() as session:
                stmt = select(Correction)
                if submission_id is not None:
                    stmt = stmt.where(Correction.submission_id == submission_id)
                if student_id is not None:
                    tenant_id, local_id = split_scoped_id(student_id)
                    stmt = stmt.where(
                        Correction.tenant_id == tenant_id, Correction.student_id == local_id
                    )
                if is_correct is not None:
                    stmt = stmt.where(Correction.is_correct == bool(is_correct))
                total = session.execute(
                    select(func.count()).select_from(stmt.subquery())
                ).scalar_one()
                rows = (
                    session.execute(
                        stmt.order_by(Correction.created_at.desc()).limit(limit).offset(offset)
                    )
                    .scalars()
                    .all()
                )

                items = []
                for row in rows:
                    items.append(
                        {
                            "id": row.id,
                            "submission_id": row.submission_id,
                            "student_id": (
                                join_scoped_id(row.tenant_id, row.student_id)
                                if row.tenant_id
                                else row.student_id
                            ),
                            "original_verdict": row.original_verdict,
                            "original_action": row.original_action,
                            "original_divergence_score": row.original_divergence_score,
                            "corrected_verdict": row.corrected_verdict,
                            "corrected_action": row.corrected_action,
                            "is_correct": bool(row.is_correct),
                            "reviewer": row.reviewer,
                            "notes": row.notes,
                            "created_at": row.created_at.isoformat(),
                        }
                    )
                return {"total": int(total), "limit": limit, "offset": offset, "items": items}
        except Exception as e:
            log.warning("list_corrections failed: %s", e)
            return {"total": 0, "limit": limit, "offset": offset, "items": []}

    # ── Calibration runs ─────────────────────────────────────────────────
    def start_calibration_run(self, dataset_label, run_label=None, config=None):
        try:
            with session_scope() as session:
                row = CalibrationRun(
                    run_label=run_label,
                    dataset_label=dataset_label,
                    started_at=datetime.now(UTC),
                    status="running",
                    config_json=config or {},
                )
                session.add(row)
                session.flush()
                return row.id
        except Exception as e:
            log.warning("start_calibration_run failed: %s", e)
            return None

    def complete_calibration_run(self, run_id, *, auc, n_essays_scored, n_authors, report):
        try:
            with session_scope() as session:
                # An UPDATE with no matching row still succeeds in SQL terms
                # (0 rows affected, no exception) -- matches
                # SqliteRepository's documented "returns True for an unknown
                # run_id" quirk (test_complete_unknown_run_returns_true_store_quirk).
                session.execute(
                    CalibrationRun.__table__.update()
                    .where(CalibrationRun.id == run_id)
                    .values(
                        status="completed",
                        completed_at=datetime.now(UTC),
                        auc=float(auc),
                        n_essays_scored=int(n_essays_scored),
                        n_authors=int(n_authors),
                        report_json=report,
                    )
                )
                return True
        except Exception as e:
            log.warning("complete_calibration_run %d failed: %s", run_id, e)
            return False

    def fail_calibration_run(self, run_id, error):
        try:
            with session_scope() as session:
                session.execute(
                    CalibrationRun.__table__.update()
                    .where(CalibrationRun.id == run_id)
                    .values(
                        status="failed", completed_at=datetime.now(UTC), error=str(error)[:2000]
                    )
                )
                return True
        except Exception as e:
            log.warning("fail_calibration_run %d failed: %s", run_id, e)
            return False

    def list_calibration_runs(self, status=None, dataset_label=None, limit=50, offset=0):
        try:
            with session_scope() as session:
                stmt = select(CalibrationRun)
                if status is not None:
                    stmt = stmt.where(CalibrationRun.status == status)
                if dataset_label is not None:
                    stmt = stmt.where(CalibrationRun.dataset_label == dataset_label)
                total = session.execute(
                    select(func.count()).select_from(stmt.subquery())
                ).scalar_one()
                rows = (
                    session.execute(
                        stmt.order_by(CalibrationRun.started_at.desc()).limit(limit).offset(offset)
                    )
                    .scalars()
                    .all()
                )
                items = [
                    {
                        "id": row.id,
                        "run_label": row.run_label,
                        "dataset_label": row.dataset_label,
                        "started_at": row.started_at.isoformat(),
                        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                        "status": row.status,
                        "auc": row.auc,
                        "n_essays_scored": row.n_essays_scored,
                        "n_authors": row.n_authors,
                        "error": row.error,
                    }
                    for row in rows
                ]
                return {"total": int(total), "limit": limit, "offset": offset, "items": items}
        except Exception as e:
            log.warning("list_calibration_runs failed: %s", e)
            return {"total": 0, "limit": limit, "offset": offset, "items": []}

    def get_calibration_run(self, run_id, include_report=True):
        try:
            with session_scope() as session:
                row = session.get(CalibrationRun, run_id)
                if row is None:
                    return None
                out = {
                    "id": row.id,
                    "run_label": row.run_label,
                    "dataset_label": row.dataset_label,
                    "started_at": row.started_at.isoformat(),
                    "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                    "status": row.status,
                    "auc": row.auc,
                    "n_essays_scored": row.n_essays_scored,
                    "n_authors": row.n_authors,
                    "config": row.config_json or {},
                    "error": row.error,
                }
                if include_report:
                    out["report"] = row.report_json or {}
                return out
        except Exception:
            return None

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
        try:
            with session_scope() as session:
                row = TunedThresholds(
                    created_at=datetime.now(UTC),
                    source=source,
                    source_run_id=source_run_id,
                    no_action=float(no_action),
                    monitor=float(monitor),
                    escalate=float(escalate),
                    verdict_authentic_below=verdict_authentic_below,
                    verdict_anomalous_at_or_above=verdict_anomalous_at_or_above,
                    notes=notes,
                    provenance_json=provenance or {},
                )
                session.add(row)
                session.flush()
                return row.id
        except Exception as e:
            log.warning("put_tuned_thresholds failed: %s", e)
            return None

    def get_active_tuned_thresholds(self):
        try:
            with session_scope() as session:
                row = (
                    session.execute(
                        select(TunedThresholds).order_by(TunedThresholds.created_at.desc()).limit(1)
                    )
                    .scalars()
                    .first()
                )
                if row is None:
                    return None
                return {
                    "id": row.id,
                    "created_at": row.created_at.isoformat(),
                    "source": row.source,
                    "source_run_id": row.source_run_id,
                    "no_action": row.no_action,
                    "monitor": row.monitor,
                    "escalate": row.escalate,
                    "verdict_authentic_below": row.verdict_authentic_below,
                    "verdict_anomalous_at_or_above": row.verdict_anomalous_at_or_above,
                    "notes": row.notes,
                    "provenance": row.provenance_json or {},
                }
        except Exception:
            return None

    def list_tuned_thresholds(self, limit=50, offset=0):
        try:
            with session_scope() as session:
                total = session.execute(
                    select(func.count()).select_from(TunedThresholds)
                ).scalar_one()
                rows = (
                    session.execute(
                        select(TunedThresholds)
                        .order_by(TunedThresholds.created_at.desc())
                        .limit(limit)
                        .offset(offset)
                    )
                    .scalars()
                    .all()
                )
                items = [
                    {
                        "id": row.id,
                        "created_at": row.created_at.isoformat(),
                        "source": row.source,
                        "source_run_id": row.source_run_id,
                        "no_action": row.no_action,
                        "monitor": row.monitor,
                        "escalate": row.escalate,
                        "verdict_authentic_below": row.verdict_authentic_below,
                        "verdict_anomalous_at_or_above": row.verdict_anomalous_at_or_above,
                        "notes": row.notes,
                    }
                    for row in rows
                ]
                return {"total": int(total), "limit": limit, "offset": offset, "items": items}
        except Exception:
            return {"total": 0, "limit": limit, "offset": offset, "items": []}

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
    @staticmethod
    def _bluebook_exam_to_dict(row: BluebookExam) -> dict:
        return {
            "id": row.exam_id,
            "tenant_id": row.tenant_id,
            "title": row.title,
            "course": row.course,
            "duration": row.duration,
            "minWords": row.min_words,
            "maxWords": row.max_words,
            "prompt": row.prompt,
            "conditions": row.conditions_json or {},
            "status": row.status,
            "submissions": 0,
            "created_at": row.created_at.isoformat(),
        }

    def put_bluebook_exam(self, rec):
        try:
            with session_scope() as session:
                self._ensure_tenant_exists(session, rec["tenant_id"])
                values = {
                    "title": rec["title"],
                    "course": rec.get("course", ""),
                    "duration": rec.get("duration"),
                    "min_words": rec.get("minWords"),
                    "max_words": rec.get("maxWords"),
                    "prompt": rec.get("prompt", ""),
                    "conditions_json": rec.get("conditions") or {},
                    "status": rec.get("status", "DRAFT"),
                }
                stmt = (
                    pg_insert(BluebookExam)
                    .values(
                        exam_id=rec["id"],
                        tenant_id=rec["tenant_id"],
                        created_at=datetime.now(UTC),
                        **values,
                    )
                    .on_conflict_do_update(index_elements=["exam_id"], set_=values)
                )
                session.execute(stmt)
        except Exception as e:
            log.error("put_bluebook_exam failed for %s: %s", rec.get("id"), e)
            raise

    def get_bluebook_exam(self, exam_id):
        try:
            with session_scope() as session:
                row = session.get(BluebookExam, exam_id)
                return self._bluebook_exam_to_dict(row) if row else None
        except Exception:
            log.exception("get_bluebook_exam failed for %s", exam_id)
            return None

    def list_bluebook_exams(self, tenant_id):
        try:
            with session_scope() as session:
                stmt = select(BluebookExam)
                if tenant_id is not None:
                    stmt = stmt.where(BluebookExam.tenant_id == tenant_id)
                rows = (
                    session.execute(stmt.order_by(BluebookExam.created_at.desc())).scalars().all()
                )
                return [self._bluebook_exam_to_dict(r) for r in rows]
        except Exception:
            log.exception("list_bluebook_exams failed for %s", tenant_id)
            return []

    @staticmethod
    def _bluebook_sub_to_dict(row: BluebookSubmission) -> dict:
        scoped_sid = join_scoped_id(row.tenant_id, row.student_id) if row.student_id else ""
        candidate_id = row.student_id[:6] if row.student_id else "—"
        return {
            "id": row.submission_id,
            "exam_id": row.exam_id,
            "tenant_id": row.tenant_id,
            "student_id": scoped_sid,
            "student": row.candidate or "Candidate",
            "candidateId": candidate_id,
            "candidate": row.candidate,
            "exam": row.exam_title or "",
            "course": row.course or "",
            "words": row.word_count or 0,
            "timeMin": row.time_min or 0,
            "stylometric": row.stylometric,
            "aiScore": row.ai_score,
            "status": row.status,
            "created_at": row.created_at.isoformat(),
        }

    def put_bluebook_submission(self, rec):
        try:
            with session_scope() as session:
                self._ensure_tenant_exists(session, rec["tenant_id"])
                raw_student_id = rec.get("student_id")
                local_student_id = split_scoped_id(raw_student_id)[1] if raw_student_id else None
                session.add(
                    BluebookSubmission(
                        submission_id=rec["id"],
                        exam_id=rec.get("exam_id"),
                        tenant_id=rec["tenant_id"],
                        student_id=local_student_id,
                        candidate=rec.get("candidate"),
                        exam_title=rec.get("exam_title"),
                        course=rec.get("course"),
                        word_count=rec.get("word_count"),
                        time_min=rec.get("time_min"),
                        stylometric=rec.get("stylometric"),
                        ai_score=rec.get("ai_score"),
                        status=rec.get("status", "SUBMITTED"),
                        created_at=datetime.now(UTC),
                    )
                )
        except Exception as e:
            log.error("put_bluebook_submission failed for %s: %s", rec.get("id"), e)
            raise

    def list_bluebook_submissions(self, tenant_id):
        try:
            with session_scope() as session:
                stmt = select(BluebookSubmission)
                if tenant_id is not None:
                    stmt = stmt.where(BluebookSubmission.tenant_id == tenant_id)
                rows = (
                    session.execute(stmt.order_by(BluebookSubmission.created_at.desc()))
                    .scalars()
                    .all()
                )
                return [self._bluebook_sub_to_dict(r) for r in rows]
        except Exception:
            log.exception("list_bluebook_submissions failed for %s", tenant_id)
            return []

    @staticmethod
    def _bluebook_course_to_dict(row: BluebookCourse) -> dict:
        return {
            "id": row.course_id,
            "tenant_id": row.tenant_id,
            "code": row.code,
            "name": row.name,
            "term": row.term,
            "status": row.status,
            "active": (row.status or "").upper() == "ACTIVE",
            "students": 0,
            "exams": 0,
            "created_at": row.created_at.isoformat(),
        }

    def put_bluebook_course(self, rec):
        try:
            with session_scope() as session:
                self._ensure_tenant_exists(session, rec["tenant_id"])
                values = {
                    "code": rec.get("code", ""),
                    "name": rec["name"],
                    "term": rec.get("term", ""),
                    "status": rec.get("status", "ACTIVE"),
                }
                stmt = (
                    pg_insert(BluebookCourse)
                    .values(
                        course_id=rec["id"],
                        tenant_id=rec["tenant_id"],
                        created_at=datetime.now(UTC),
                        **values,
                    )
                    .on_conflict_do_update(index_elements=["course_id"], set_=values)
                )
                session.execute(stmt)
        except Exception as e:
            log.error("put_bluebook_course failed for %s: %s", rec.get("id"), e)
            raise

    def list_bluebook_courses(self, tenant_id):
        try:
            with session_scope() as session:
                stmt = select(BluebookCourse)
                if tenant_id is not None:
                    stmt = stmt.where(BluebookCourse.tenant_id == tenant_id)
                rows = (
                    session.execute(stmt.order_by(BluebookCourse.created_at.desc())).scalars().all()
                )
                return [self._bluebook_course_to_dict(r) for r in rows]
        except Exception:
            log.exception("list_bluebook_courses failed for %s", tenant_id)
            return []

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
    _FORMATION_STEPS = 3

    @staticmethod
    def _formation_row_to_dict(row: FormationPathway, scoped_student_id: str) -> dict:
        return {
            "id": row.id,
            "student_id": scoped_student_id,
            "submission_id": row.submission_id,
            "status": row.status,
            "current_step": row.current_step,
            "reason": row.reason,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
            "total_steps": PostgresRepository._FORMATION_STEPS,
        }

    def get_formation_pathway(self, student_id):
        try:
            with session_scope() as session:
                tenant_id, local_id = split_scoped_id(student_id)
                row = (
                    session.execute(
                        select(FormationPathway)
                        .where(
                            FormationPathway.tenant_id == tenant_id,
                            FormationPathway.student_id == local_id,
                        )
                        .order_by(
                            (FormationPathway.status == "open").desc(),
                            FormationPathway.updated_at.desc(),
                        )
                        .limit(1)
                    )
                    .scalars()
                    .first()
                )
                return self._formation_row_to_dict(row, student_id) if row else None
        except Exception:
            log.exception("get_formation_pathway failed for %s", student_id)
            return None

    def open_formation_pathway(self, student_id, submission_id=None, reason=None):
        existing = self.get_formation_pathway(student_id)
        if existing and existing["status"] == "open":
            return existing
        try:
            with session_scope() as session:
                tenant_id, local_id = split_scoped_id(student_id)
                self._ensure_tenant_exists(session, tenant_id)
                now = datetime.now(UTC)
                row = FormationPathway(
                    tenant_id=tenant_id,
                    student_id=local_id,
                    submission_id=submission_id,
                    status="open",
                    current_step=0,
                    reason=reason,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                session.flush()
                new_id = row.id
        except Exception:
            log.exception("open_formation_pathway failed for %s", student_id)
            return None
        self.log_audit(
            action="formation_open",
            student_id=student_id,
            details={"submission_id": submission_id, "pathway_id": new_id},
        )
        return self.get_formation_pathway(student_id)

    def advance_formation_pathway(self, student_id):
        p = self.get_formation_pathway(student_id)
        if not p or p["status"] != "open":
            return None
        new_step = min(p["current_step"] + 1, self._FORMATION_STEPS)
        completed = new_step >= self._FORMATION_STEPS
        try:
            with session_scope() as session:
                session.execute(
                    FormationPathway.__table__.update()
                    .where(FormationPathway.id == p["id"])
                    .values(
                        current_step=new_step,
                        status="completed" if completed else "open",
                        updated_at=datetime.now(UTC),
                    )
                )
                if completed and p["submission_id"]:
                    session.execute(
                        SubmissionManifest.__table__.update()
                        .where(SubmissionManifest.submission_id == p["submission_id"])
                        .values(action="no_action")
                    )
        except Exception:
            log.exception("advance_formation_pathway failed for %s", student_id)
            return None

        if completed and p["submission_id"]:
            self.update_fidelity_authenticity(p["submission_id"], True)

        self.log_audit(
            action="formation_complete" if completed else "formation_advance",
            student_id=student_id,
            details={
                "pathway_id": p["id"],
                "step": new_step,
                "submission_id": p["submission_id"],
            },
        )
        return self.get_formation_pathway(student_id)

    # ── Baseline requests ─────────────────────────────────────────────────
    def put_baseline_request(
        self, external_request_id, student_id, status, requested_at, data_json
    ):
        try:
            doc = json.loads(data_json) if isinstance(data_json, str) else data_json
            with session_scope() as session:
                tenant_id, local_id = split_scoped_id(student_id)
                self._ensure_tenant_exists(session, tenant_id)
                values = {
                    "tenant_id": tenant_id,
                    "student_id": local_id,
                    "status": status,
                    "requested_at": float(requested_at),
                    "data_json": doc,
                }
                stmt = (
                    pg_insert(BaselineRequest)
                    .values(external_request_id=external_request_id, **values)
                    .on_conflict_do_update(index_elements=["external_request_id"], set_=values)
                )
                session.execute(stmt)
        except Exception:
            log.exception("put_baseline_request failed for %s", external_request_id)

    def load_baseline_requests(self):
        try:
            with session_scope() as session:
                rows = session.execute(
                    select(BaselineRequest.data_json).order_by(BaselineRequest.requested_at)
                ).all()
                return [doc for (doc,) in rows if doc is not None]
        except Exception:
            log.exception("load_baseline_requests failed")
            return []

    # ── QR phone-park (proctoring deterrence) ─────────────────────────────
    #
    # PRIVACY CONTRACT (docs/STUDENT_DISCLOSURE.md, mirrored on the Repository
    # Protocol and in store.py): these methods persist an opaque park_token, an
    # exam_session_id, a student-typed student_hint, UTC timestamps, and state
    # transitions. NO IP address, NO user-agent, NO location, NO device
    # fingerprint, NO roster identifier. Note that — uniquely on this class —
    # nothing here calls split_scoped_id/join_scoped_id: park rows key on a
    # token, not on a student, so the tenancy shim has nothing to translate.
    # `tenant_id` scopes a professor's *reads*; it identifies an institution,
    # never a person. Rows purge after 24h.
    #
    # Timestamps: `datetime` in; ISO-8601 UTC strings out via
    # `store.park_iso_utc` — the same helper SqliteRepository uses, so both
    # backends return byte-identical dicts (that equality is what makes the
    # dual-backend contract suite meaningful).

    @staticmethod
    def _park_session_to_dict(row: ParkSession) -> dict:
        return {
            "exam_session_id": row.exam_session_id,
            "tenant_id": row.tenant_id,
            "park_token": row.park_token,
            "created_at": park_iso_utc(row.created_at),
        }

    def park_open(self, exam_session_id, tenant_id, park_token, created_at):
        with session_scope() as session:
            self._ensure_tenant_exists(session, tenant_id)
            prev = session.execute(
                select(ParkSession.park_token).where(ParkSession.exam_session_id == exam_session_id)
            ).scalar_one_or_none()
            if prev is not None and prev != park_token:
                # Token rotated (only possible once the old one expired) — the
                # superseded token's beats are unreachable, so they go now
                # rather than waiting for the 24h purge.
                session.execute(ParkBeat.__table__.delete().where(ParkBeat.park_token == prev))
            values = {
                "tenant_id": tenant_id,
                "park_token": park_token,
                "created_at": park_utc(created_at),
            }
            session.execute(
                pg_insert(ParkSession)
                .values(exam_session_id=exam_session_id, **values)
                .on_conflict_do_update(index_elements=["exam_session_id"], set_=values)
            )

    def park_get_session(self, park_token):
        with session_scope() as session:
            row = session.execute(
                select(ParkSession).where(ParkSession.park_token == park_token)
            ).scalar_one_or_none()
            return self._park_session_to_dict(row) if row else None

    def park_get_session_by_exam(self, exam_session_id):
        with session_scope() as session:
            row = session.execute(
                select(ParkSession).where(ParkSession.exam_session_id == exam_session_id)
            ).scalar_one_or_none()
            return self._park_session_to_dict(row) if row else None

    def park_beat(self, park_token, student_hint, state, at):
        at = park_utc(at)
        ts = park_iso_utc(at)
        with session_scope() as session:
            row = session.execute(
                select(ParkBeat).where(
                    ParkBeat.park_token == park_token,
                    ParkBeat.student_hint == student_hint,
                )
            ).scalar_one_or_none()
            if row is None:
                session.execute(
                    pg_insert(ParkBeat).values(
                        park_token=park_token,
                        student_hint=student_hint,
                        state=state,
                        first_seen_at=at,
                        last_seen_at=at,
                        transitions_json=[{"state": state, "at": ts}],
                    )
                )
            elif row.state == state:
                # Steady heartbeat: bump liveness only. Appending here is what
                # would turn a 10s beat into an unbounded log.
                row.last_seen_at = at
            else:
                transitions = list(row.transitions_json or [])
                transitions.append({"state": state, "at": ts})
                row.state = state
                row.last_seen_at = at
                row.transitions_json = transitions[-PARK_MAX_TRANSITIONS:]

    def park_tiles(self, exam_session_id):
        with session_scope() as session:
            rows = session.execute(
                select(ParkBeat)
                .join(ParkSession, ParkSession.park_token == ParkBeat.park_token)
                .where(ParkSession.exam_session_id == exam_session_id)
                .order_by(ParkBeat.first_seen_at, ParkBeat.student_hint)
            ).scalars()
            return [
                {
                    "student_hint": r.student_hint,
                    "state": r.state,
                    "first_seen_at": park_iso_utc(r.first_seen_at),
                    "last_seen_at": park_iso_utc(r.last_seen_at),
                    "transitions": list(r.transitions_json or []),
                }
                for r in rows
            ]

    def park_delete(self, exam_session_id):
        with session_scope() as session:
            token = session.execute(
                select(ParkSession.park_token).where(ParkSession.exam_session_id == exam_session_id)
            ).scalar_one_or_none()
            if token is None:
                return 0
            beats = session.execute(
                ParkBeat.__table__.delete().where(ParkBeat.park_token == token)
            ).rowcount
            sessions = session.execute(
                ParkSession.__table__.delete().where(ParkSession.exam_session_id == exam_session_id)
            ).rowcount
            return int(beats) + int(sessions)

    def park_purge(self, before):
        before = park_utc(before)
        with session_scope() as session:
            tokens = list(
                session.execute(
                    select(ParkSession.park_token).where(ParkSession.created_at < before)
                ).scalars()
            )
            if not tokens:
                return 0
            beats = session.execute(
                ParkBeat.__table__.delete().where(ParkBeat.park_token.in_(tokens))
            ).rowcount
            sessions = session.execute(
                ParkSession.__table__.delete().where(ParkSession.created_at < before)
            ).rowcount
            return int(beats) + int(sessions)

    # ── DB path ───────────────────────────────────────────────────────────
    def db_path(self):
        self._todo("db_path")
