"""
db/models/student.py — Student and StudentEnrollment models.

Represents students and their enrollment in courses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, String, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from original.db.base import Base, UUIDMixin, TimestampMixin


class Student(Base, UUIDMixin, TimestampMixin):
    """A student (learner) in the system."""

    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("external_id", "institution_id", name="uq_student_ext_id_inst"),
    )

    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    institution_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    baseline_kappa: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, default=None,
        comment="Running mean catastrophe index κ across all authenticated baselines",
    )

    # Relationships
    institution: Mapped["Institution"] = relationship("Institution", back_populates="students")
    enrollments: Mapped[list["StudentEnrollment"]] = relationship(
        "StudentEnrollment",
        back_populates="student",
        cascade="all, delete-orphan",
    )
    baseline_samples: Mapped[list["BaselineSample"]] = relationship(
        "BaselineSample",
        back_populates="student",
        cascade="all, delete-orphan",
    )
    submissions: Mapped[list["Submission"]] = relationship(
        "Submission",
        back_populates="student",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Student {self.full_name} ({self.external_id})>"


class StudentEnrollment(Base, UUIDMixin, TimestampMixin):
    """Enrollment of a student in a course."""

    __tablename__ = "student_enrollments"
    __table_args__ = (
        UniqueConstraint("student_id", "course_id", name="uq_enrollment"),
    )

    student_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=datetime.utcnow,
    )

    # Relationships
    student: Mapped["Student"] = relationship("Student", back_populates="enrollments")
    course: Mapped["Course"] = relationship("Course", back_populates="students")

    def __repr__(self) -> str:
        return f"<StudentEnrollment {self.student_id[:8]}... → {self.course_id[:8]}...>"
