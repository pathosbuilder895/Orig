"""
db/models/__init__.py — ORM model exports.

Re-export all models for convenient importing.

Two model families live here (see live.py's module docstring):
- v1 (dormant) models on ``original.db.base.Base`` — retired at WS-6 P6.
- LIVE pilot-schema models on ``live.LiveBase`` — the WS-6 P2 port of the
  16-table store.py schema, target of the fresh alembic baseline.
"""

from original.db.models.baseline import BaselineSample, Provenance
from original.db.models.canvas import (
    CanvasSubmission,
    CanvasSubmissionStatus,
    LTINonce,
    LTIRegistration,
)
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
    LiveBase,
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
    "LTIRegistration",
    "LTINonce",
    "CanvasSubmission",
    "CanvasSubmissionStatus",
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
    "Correction",
    "CalibrationRun",
    "TunedThresholds",
    "BluebookCourse",
    "BluebookExam",
    "BluebookSubmission",
    "FormationPathway",
    "BaselineRequest",
    "AuditLogEntry",
]
