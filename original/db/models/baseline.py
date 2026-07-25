"""
db/models/baseline.py — BaselineSample model.

Stores authenticated writing samples for a student used to build
their quantum authorship profile.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from original.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from original.db.models.course import Course
    from original.db.models.student import Student
    from original.db.models.user import User


class Provenance(str, Enum):
    """Provenance level of a baseline sample."""

    PROCTORED = "proctored"
    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class BaselineSample(Base, UUIDMixin, TimestampMixin):
    """An authenticated baseline writing sample for a student."""

    __tablename__ = "baseline_samples"

    student_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("courses.id", ondelete="SET NULL"),
        nullable=True,
    )
    assignment: Mapped[str] = mapped_column(String(255), nullable=False)
    text_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    feature_vector: Mapped[dict] = mapped_column(JSON, nullable=False)
    provenance: Mapped[Provenance] = mapped_column(
        String(20),
        default=Provenance.VERIFIED,
        index=True,
    )
    auth_weight: Mapped[float] = mapped_column(Float, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    added_by_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # Relationships
    student: Mapped[Student] = relationship("Student", back_populates="baseline_samples")
    course: Mapped[Course] = relationship("Course")
    added_by: Mapped[User] = relationship("User")

    def __repr__(self) -> str:
        return f"<BaselineSample {self.student_id[:8]}... {self.assignment}>"
