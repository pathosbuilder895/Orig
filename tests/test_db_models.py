"""
tests/test_db_models.py — WS-6 P2 live-schema SQLAlchemy model validation.

Covers the acceptance points from docs/implementation/WS-6-postgres-convergence.md
Phase P2 that are checkable without a live Postgres:

- ``LiveBase.metadata.create_all`` builds all 16 live tables on SQLite.
- Per-model round-trip of a representative row (including JSON documents,
  raw bytes, datetimes, floats, booleans).
- Tenancy-as-constraint: composite (tenant_id, student_id) uniqueness and
  the tenant FK actually enforce at the database level.
- The v1 model imports are untouched (never break v1 imports).

These models are not wired into any live path yet (P3 does that); the tests
exercise the schema itself.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest
from sqlalchemy import create_engine, event, insert, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from original.constants import FEATURE_DIM
from original.db.models.live import (
    LIVE_MODELS,
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
    LiveBase,
    StaffUser,
    StudentName,
    StudentProfile,
    SubmissionManifest,
    Tenant,
    TunedThresholds,
)

EXPECTED_TABLES = {
    "student_profiles",
    "student_names",
    "submission_manifests",
    "corrections",
    "calibration_runs",
    "tuned_thresholds_v2",
    "fidelity_scores",
    "ai_likelihood_scores",
    "tenants",
    "users",
    "bluebook_exams",
    "bluebook_submissions",
    "bluebook_courses",
    "audit_log",
    "formation_pathways",
    "baseline_requests",
}

TENANT_ID = "seminary-dallas"
NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)


def _wall(dt: datetime) -> datetime:
    """Naive wall-clock time — SQLite's DATETIME drops the UTC offset on
    storage (Postgres timestamptz keeps it; the P3 repository returns ISO
    strings either way)."""
    return dt.replace(tzinfo=None)


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://")

    # SQLite enforces FKs only with the pragma on (mirrors what Postgres
    # gives us for free — the point of the tenancy upgrade).
    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    LiveBase.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        s.add(Tenant(tenant_id=TENANT_ID, name="Seminary of Dallas", created_at=NOW))
        s.commit()
        yield s


# ── Schema shape ──────────────────────────────────────────────────────────────


def test_create_all_builds_all_16_tables(engine):
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
    assert len(LIVE_MODELS) == 16


def test_v1_imports_still_work():
    # WS-6 P2 must not break the dormant v1 stack before P6 deletes it.
    from original.db.base import Base as V1Base
    from original.db.models import Institution, User
    from original.db.models import LiveBase as ReExported

    assert User.__tablename__ == "users"  # v1 users on v1 Base…
    assert "users" in V1Base.metadata.tables
    assert "users" in ReExported.metadata.tables  # …live users on LiveBase
    assert V1Base.metadata is not ReExported.metadata
    assert Institution.__tablename__ == "institutions"


# ── Representative-row round-trips ────────────────────────────────────────────

# The serialized StudentState document shape written by store.py:_serialize.
PROFILE_DOC = {
    "student_id": "marcus",
    "samples": [
        {
            "text": "In the beginning was the Word...",
            "vector": [0.5] * FEATURE_DIM,
            "provenance": "proctored",
            "auth_weight": 1.0,
            "assignment": "Essay 1",
            "submitted_at": "2026-07-01T09:00:00+00:00",
            "genre": "theological_reflection",
            "topic_centroid": None,
            "context_manifest": None,
        }
    ],
    "baseline_kappa": 0.42,
    "kappa_log": [0.42],
    "consecutive_drift_count": 0,
}

RHO = np.eye(FEATURE_DIM, dtype=np.float64) / FEATURE_DIM

REPRESENTATIVE_ROWS = {
    Tenant: dict(
        tenant_id="grace-college",
        name="Grace College",
        environment="pilot",
        created_at=NOW,
        meta_json={"contact": "provost@grace.edu", "seats": 120},
    ),
    StaffUser: dict(
        user_id="u-001",
        email="prof@seminary.edu",
        password_hash="pbkdf2:sha256$260000$abc$def",
        role="professor",
        tenant_id=TENANT_ID,
        name="Dr. Whitfield",
        created_at=NOW,
    ),
    StudentProfile: dict(
        tenant_id=TENANT_ID,
        student_id="marcus",
        data=PROFILE_DOC,
        rho_bytes=RHO.tobytes(),
    ),
    StudentName: dict(
        tenant_id=TENANT_ID,
        student_id="marcus",
        display_name="Marcus Whitfield",
        updated_at=NOW,
    ),
    SubmissionManifest: dict(
        submission_id="sub-001",
        tenant_id=TENANT_ID,
        student_id="marcus",
        created_at=NOW,
        manifest_json={"genre": "exegesis", "directives": ["relax_lexical"]},
        divergence_score=0.31,
        action="no_action",
    ),
    FidelityScore: dict(
        submission_id="sub-001",
        tenant_id=TENANT_ID,
        student_id="marcus",
        fidelity=0.937,
        is_authentic=True,
        created_at=NOW,
    ),
    AiLikelihoodScore: dict(
        submission_id="sub-001",
        tenant_id=TENANT_ID,
        student_id="marcus",
        probability=0.12,
        band="low",
        model_version="v0.3.1",
        created_at=NOW,
    ),
    Correction: dict(
        submission_id="sub-001",
        tenant_id=TENANT_ID,
        student_id="marcus",
        original_verdict="anomalous",
        original_action="monitor",
        original_divergence_score=0.61,
        corrected_verdict="authentic",
        corrected_action="no_action",
        is_correct=False,
        reviewer="prof@seminary.edu",
        notes="Student wrote under exam stress.",
        created_at=NOW,
    ),
    CalibrationRun: dict(
        run_label="july-tuning",
        dataset_label="pilot-corpus-v2",
        started_at=NOW,
        completed_at=NOW,
        status="completed",
        auc=0.91,
        n_essays_scored=250,
        n_authors=48,
        config_json={"folds": 5},
        report_json={"roc": [[0.0, 0.0], [1.0, 1.0]]},
        error=None,
    ),
    TunedThresholds: dict(
        created_at=NOW,
        source="calibration",
        source_run_id=1,
        no_action=0.35,
        monitor=0.55,
        escalate=0.75,
        verdict_authentic_below=0.4,
        verdict_anomalous_at_or_above=0.7,
        notes="Applied from run july-tuning",
        provenance_json={"run_id": 1, "operator": "prof@seminary.edu"},
    ),
    BluebookCourse: dict(
        course_id="c-001",
        tenant_id=TENANT_ID,
        code="TH501",
        name="Systematic Theology I",
        term="Fall 2026",
        status="ACTIVE",
        created_at=NOW,
    ),
    BluebookExam: dict(
        exam_id="e-001",
        tenant_id=TENANT_ID,
        title="Midterm: Christology",
        course="TH501",
        duration=90,
        min_words=400,
        max_words=1200,
        prompt="Discuss the hypostatic union.",
        conditions_json={"lockdown": True, "spellcheck": False},
        status="PUBLISHED",
        created_at=NOW,
    ),
    BluebookSubmission: dict(
        submission_id="bb-001",
        exam_id="e-001",
        tenant_id=TENANT_ID,
        student_id="marcus",
        candidate="Marcus Whitfield",
        exam_title="Midterm: Christology",
        course="TH501",
        word_count=845,
        time_min=74,
        stylometric=92,
        ai_score=8,
        status="SUBMITTED",
        created_at=NOW,
    ),
    FormationPathway: dict(
        tenant_id=TENANT_ID,
        student_id="marcus",
        submission_id="sub-001",
        status="open",
        current_step=1,
        reason="divergent submission",
        created_at=NOW,
        updated_at=NOW,
    ),
    BaselineRequest: dict(
        external_request_id="req-001",
        tenant_id=TENANT_ID,
        student_id="marcus",
        status="pending",
        requested_at=1783891200.5,  # Unix epoch seconds (REAL in SQLite) — not ISO
        data_json={"external_request_id": "req-001", "prompt": "Introduce yourself."},
    ),
    AuditLogEntry: dict(
        created_at=NOW,
        action="baseline_add",
        student_id="marcus",
        tenant_id=TENANT_ID,
        actor="prof@seminary.edu",
        result="ok",
        details_json={"submission_id": "sub-001", "provenance": "proctored"},
    ),
}


@pytest.mark.parametrize("model", LIVE_MODELS, ids=lambda m: m.__tablename__)
def test_round_trip_representative_row(session, model):
    kwargs = REPRESENTATIVE_ROWS[model]
    session.add(model(**kwargs))
    session.commit()
    session.expunge_all()  # force a real re-read from the database

    # Select the inserted row by its PK columns where the test supplied them
    # (the session fixture pre-seeds one Tenant row).
    stmt = select(model)
    for col in inspect(model).primary_key:
        if col.name in kwargs:
            stmt = stmt.where(col == kwargs[col.name])
    row = session.execute(stmt).scalar_one()
    for field, expected in kwargs.items():
        got = getattr(row, field)
        if isinstance(expected, datetime):
            assert _wall(got if got.tzinfo is None else got) == _wall(expected), field
        else:
            assert got == expected, field


def test_profile_bytes_and_json_round_trip_exactly(session):
    """The highest-stakes round-trip: numpy bytes and the profile document."""
    session.add(StudentProfile(**REPRESENTATIVE_ROWS[StudentProfile]))
    session.commit()
    session.expunge_all()

    row = session.execute(select(StudentProfile)).scalar_one()
    # Byte-exact ρ round-trip (LargeBinary → BYTEA on Postgres).
    assert row.rho_bytes == RHO.tobytes()
    rho_back = np.frombuffer(row.rho_bytes, dtype=np.float64).reshape(FEATURE_DIM, FEATURE_DIM)
    np.testing.assert_array_equal(rho_back, RHO)
    # JSON document round-trips structurally intact, vector length preserved.
    assert row.data == PROFILE_DOC
    assert len(row.data["samples"][0]["vector"]) == FEATURE_DIM


# ── Tenancy as a constraint ───────────────────────────────────────────────────


def test_composite_uniqueness_rejects_duplicate_student_in_tenant(session):
    session.add(StudentProfile(tenant_id=TENANT_ID, student_id="marcus", data={"v": 1}))
    session.commit()
    with pytest.raises(IntegrityError):
        # Core insert so the duplicate hits the DB constraint, not the
        # session identity map.
        session.execute(
            insert(StudentProfile).values(tenant_id=TENANT_ID, student_id="marcus", data={"v": 2})
        )
    session.rollback()


def test_same_local_id_allowed_across_tenants(session):
    """The whole point of (tenant_id, student_id): 'marcus' at two schools
    are different students, without any string-prefix convention."""
    session.add(Tenant(tenant_id="other-college", name="Other College", created_at=NOW))
    # No relationship()s are mapped (faithful port), so flush the tenant
    # before the profiles that FK it.
    session.flush()
    session.add(StudentProfile(tenant_id=TENANT_ID, student_id="marcus", data={"v": 1}))
    session.add(StudentProfile(tenant_id="other-college", student_id="marcus", data={"v": 2}))
    session.commit()

    rows = session.execute(select(StudentProfile)).scalars().all()
    assert {(r.tenant_id, r.student_id) for r in rows} == {
        (TENANT_ID, "marcus"),
        ("other-college", "marcus"),
    }


def test_tenant_fk_rejects_unknown_tenant(session):
    with pytest.raises(IntegrityError):
        session.execute(
            insert(StudentProfile).values(tenant_id="no-such-tenant", student_id="ghost", data={})
        )
    session.rollback()


def test_audit_log_has_no_tenant_fk(session):
    """Audit appends are best-effort (store.log_audit never raises) — an
    unknown tenant must NOT be rejected here."""
    session.add(
        AuditLogEntry(
            created_at=NOW,
            action="tenant_register",
            tenant_id="not-registered-yet",
            details_json={},
        )
    )
    session.commit()
    assert session.execute(select(AuditLogEntry)).scalar_one().result == "ok"


def test_server_defaults_match_store_ddl(session):
    """Defaults ported from store.py DDL apply at the database level."""
    session.execute(insert(Tenant).values(tenant_id="t-min", name="Minimal", created_at=NOW))
    session.execute(
        insert(BluebookExam).values(
            exam_id="e-min", tenant_id="t-min", title="Minimal", created_at=NOW
        )
    )
    session.commit()
    session.expunge_all()

    tenant = session.get(Tenant, "t-min")
    assert tenant.environment == "demo"
    assert tenant.meta_json == {}
    exam = session.get(BluebookExam, "e-min")
    assert exam.status == "DRAFT"
    assert exam.conditions_json == {}
