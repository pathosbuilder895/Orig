"""
db/models/institution.py — Institution model.

Represents a seminary or theological institution using the Original system.

Data-policy defaults (FERPA mode):
  retain_raw_text_days  — how long submission raw text is kept (default: 365 days)
  retain_scores_days    — how long scoring results are kept (default: 1825 = 5 years)
  ferpa_mode            — if True, raw text is deleted after feature extraction;
                          only feature vectors and scores are retained.
                          This is the default and recommended setting for FERPA compliance.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import JSON, Boolean, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from original.db.base import Base, UUIDMixin, TimestampMixin

# Default data-policy applied to every new institution.
# Admins can override via PATCH /api/v1/admin/institutions/{id}/data-policy.
DEFAULT_DATA_POLICY: Dict[str, Any] = {
    "retain_raw_text_days": 365,   # 1 year
    "retain_scores_days": 1825,    # 5 years
    "ferpa_mode": True,            # delete raw text after feature extraction
}


def _default_settings() -> Dict[str, Any]:
    """Return a fresh copy of the default institution settings dict."""
    return {"data_policy": dict(DEFAULT_DATA_POLICY)}


class Institution(Base, UUIDMixin, TimestampMixin):
    """A seminary or theological institution."""

    __tablename__ = "institutions"

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    subdomain: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
    )
    settings: Mapped[Dict] = mapped_column(JSON, default=_default_settings)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    @property
    def data_policy(self) -> Dict[str, Any]:
        """Return the data policy, merging defaults for missing keys."""
        policy = (self.settings or {}).get("data_policy", {})
        return {**DEFAULT_DATA_POLICY, **policy}

    @property
    def ferpa_mode(self) -> bool:
        return self.data_policy.get("ferpa_mode", True)

    # Relationships
    users: Mapped[list["User"]] = relationship(
        "User",
        back_populates="institution",
        cascade="all, delete-orphan",
    )
    courses: Mapped[list["Course"]] = relationship(
        "Course",
        back_populates="institution",
        cascade="all, delete-orphan",
    )
    students: Mapped[list["Student"]] = relationship(
        "Student",
        back_populates="institution",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Institution {self.name} ({self.subdomain})>"
