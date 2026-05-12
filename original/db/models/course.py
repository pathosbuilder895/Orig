"""
db/models/course.py — Course model.

Represents a course within an institution.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from original.db.base import Base, UUIDMixin, TimestampMixin


class Course(Base, UUIDMixin, TimestampMixin):
    """A course within an institution."""

    __tablename__ = "courses"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    institution_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    instructor_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    semester: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # Relationships
    institution: Mapped["Institution"] = relationship("Institution", back_populates="courses")
    instructor: Mapped["User"] = relationship("User")
    students: Mapped[list["StudentEnrollment"]] = relationship(
        "StudentEnrollment",
        back_populates="course",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Course {self.code} {self.semester}>"
