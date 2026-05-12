"""
db/models/submission.py — Submission and related models.

Stores student submissions and their scoring results.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, Optional

from sqlalchemy import Boolean, DateTime, JSON, ForeignKey, String, Float, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from original.db.base import Base, UUIDMixin, TimestampMixin


class SubmissionStatus(str, Enum):
    """Status of a submission in the scoring pipeline."""

    PENDING = "pending"
    SCORING = "scoring"
    SCORED = "scored"
    FAILED = "failed"


class Submission(Base, UUIDMixin, TimestampMixin):
    """A student submission for scoring."""

    __tablename__ = "submissions"
    __table_args__ = (
        Index("idx_student_course_assignment", "student_id", "course_id", "assignment"),
    )

    student_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("courses.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assignment: Mapped[str] = mapped_column(String(255), nullable=False)
    text_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[SubmissionStatus] = mapped_column(
        String(20),
        default=SubmissionStatus.PENDING,
        index=True,
    )

    # Relationships
    student: Mapped["Student"] = relationship("Student", back_populates="submissions")
    course: Mapped["Course"] = relationship("Course")
    scoring_result: Mapped["ScoringResult"] = relationship(
        "ScoringResult",
        back_populates="submission",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Submission {self.student_id[:8]}... {self.assignment} ({self.status})>"


class ScoringResult(Base, UUIDMixin, TimestampMixin):
    """The scoring result for a submission."""

    __tablename__ = "scoring_results"

    submission_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("submissions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    deviation_score: Mapped[float] = mapped_column(Float, nullable=False)
    authorship_probability: Mapped[float] = mapped_column(Float, nullable=False)
    recommended_action: Mapped[str] = mapped_column(String(50), nullable=False)
    baseline_confidence: Mapped[Dict] = mapped_column(JSON, nullable=False)
    full_result: Mapped[Dict] = mapped_column(JSON, nullable=False)
    feature_vector: Mapped[Dict] = mapped_column(JSON, nullable=False)
    scored_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Relationships
    submission: Mapped["Submission"] = relationship(
        "Submission",
        back_populates="scoring_result",
    )

    def __repr__(self) -> str:
        return f"<ScoringResult deviation={self.deviation_score:.2f}>"


class ActionType(str, Enum):
    """Instructor decision action."""

    ESCALATE = "escalate"
    SCHEDULE_CONVERSATION = "schedule_conversation"
    MONITOR = "monitor"
    CLEAR = "clear"
    OVERRIDE_CLEAR = "override_clear"


class InstructorDecision(Base, UUIDMixin, TimestampMixin):
    """An immutable instructor decision on a submission."""

    __tablename__ = "instructor_decisions"

    submission_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[ActionType] = mapped_column(String(50), nullable=False, index=True)
    notes: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    # Relationships
    submission: Mapped["Submission"] = relationship("Submission")
    user: Mapped["User"] = relationship("User")

    def __repr__(self) -> str:
        return f"<InstructorDecision {self.action}>"
