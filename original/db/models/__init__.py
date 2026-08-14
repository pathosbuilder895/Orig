"""
db/models/__init__.py — ORM model exports.

Re-export all models for convenient importing.

Two model families live here (see live.py's module docstring):
- v1 models on ``original.db.base.Base`` — WS-6 P6 deleted the dormant v1 API
  surface but this ORM layer stays: ``original.cli.delete_student`` (the
  documented manual FERPA-deletion CLI — see README.md/SETUP.md/
  docs/data_inventory.md) still queries it, and its models are coupled by FK
  + relationship() string references, so none of it can be split off without
  either retiring that CLI or decoupling the schema. ``original.cli.
  security_audit`` also depends on ``original.core.config`` via this stack.
  ``db/models/canvas.py`` (CanvasSubmission/LTINonce/LTIRegistration) had no
  such coupling and was deleted in the T3 db/core lint-scope cleanup.
- LIVE pilot-schema models on ``live.LiveBase`` — the WS-6 P2 port of the
  16-table store.py schema (plus the two T8 phone-park tables authored
  directly against it), target of the fresh alembic baseline.
"""

from original.db.models.baseline import BaselineSample, Provenance
from original.db.models.course import Course
from original.db.models.institution import Institution

# ── LIVE pilot schema (WS-6 P2) — separate LiveBase metadata ──────────────────
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
    FusedScore,
    LiveBase,
    ParkBeat,
    ParkSession,
    StaffUser,
    StudentName,
    StudentProfile,
    SubmissionManifest,
    Tenant,
    TunedThresholds,
)
from original.db.models.student import Student, StudentEnrollment
from original.db.models.submission import (
    ActionType,
    InstructorDecision,
    ScoringResult,
    Submission,
    SubmissionStatus,
)
from original.db.models.user import RefreshToken, User, UserRole

__all__ = [
    "Institution",
    "User",
    "UserRole",
    "RefreshToken",
    "Course",
    "Student",
    "StudentEnrollment",
    "BaselineSample",
    "Provenance",
    "Submission",
    "ScoringResult",
    "SubmissionStatus",
    "InstructorDecision",
    "ActionType",
    # LIVE pilot schema (WS-6 P2)
    "LiveBase",
    "LIVE_MODELS",
    "Tenant",
    "StaffUser",
    "StudentProfile",
    "StudentName",
    "SubmissionManifest",
    "FidelityScore",
    "AiLikelihoodScore",
    "FusedScore",
    "Correction",
    "CalibrationRun",
    "TunedThresholds",
    "BluebookCourse",
    "BluebookExam",
    "BluebookSubmission",
    "FormationPathway",
    "BaselineRequest",
    "AuditLogEntry",
    "ParkSession",
    "ParkBeat",
]
