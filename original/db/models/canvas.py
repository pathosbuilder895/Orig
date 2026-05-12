"""
db/models/canvas.py — Canvas LTI integration models.

Tables:
  lti_registrations   — One row per Canvas instance registered with Original.
                        Stores the platform OIDC/JWKS URLs, client ID, and
                        deployment ID needed for LTI 1.3 launch validation.

  lti_nonces          — Short-lived nonces for LTI 1.3 OIDC replay prevention.
                        Expired rows are safe to purge periodically.

  canvas_submissions  — Tracks each Canvas submission event through the
                        scoring pipeline and report-posting workflow.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from original.db.base import Base, UUIDMixin, TimestampMixin


# ── LTI Registration ──────────────────────────────────────────────────────────

class LTIPlatformType(str, Enum):
    """LTI platform type — used to normalise claim differences between LMS vendors."""
    CANVAS      = "canvas"
    BLACKBOARD  = "blackboard"
    GENERIC     = "generic"


class LTIRegistration(Base, UUIDMixin, TimestampMixin):
    """
    One row per LTI 1.3 deployment registered with Original.

    Supports Canvas, Blackboard, and generic IMS LTI 1.3 platforms.
    Created by an admin via POST /admin/canvas/registrations.
    Required before any LTI launch from that platform will succeed.
    """

    __tablename__ = "lti_registrations"

    # The issuer URL the platform sends in the OIDC login request
    # Canvas:      https://seminary.instructure.com  (per-instance)
    # Blackboard:  https://blackboard.com            (global)
    platform_iss: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # LMS vendor — controls claim normalisation in _parse_claims()
    platform_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=LTIPlatformType.CANVAS,
        index=True,
    )

    # The client_id issued by the LMS when the developer key was created
    client_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # The deployment_id from the LMS Developer Key (can have multiple per client_id)
    deployment_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Platform OIDC authorization endpoint
    auth_endpoint: Mapped[str] = mapped_column(String(500), nullable=False)

    # Platform JWKS endpoint for public key retrieval
    jwks_url: Mapped[str] = mapped_column(String(500), nullable=False)

    # Platform access token for API calls (optional — system-level token)
    api_token: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Linked institution in Original's system
    institution_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("institutions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Human-readable label (e.g. "SBTS Canvas" or "SBTS Blackboard Ultra")
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="Canvas")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # Relationships
    institution: Mapped[Optional["Institution"]] = relationship("Institution")
    nonces: Mapped[list["LTINonce"]] = relationship(
        "LTINonce",
        back_populates="registration",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<LTIRegistration {self.platform_iss} client={self.client_id}>"


# ── LTI Nonces ────────────────────────────────────────────────────────────────

class LTINonce(Base, UUIDMixin):
    """
    Short-lived nonce record for LTI 1.3 OIDC replay prevention.

    One row is created per login initiation and deleted when consumed.
    Rows older than 10 minutes should be purged by a scheduled job.
    """

    __tablename__ = "lti_nonces"

    # SHA-256 hash of the nonce value (never store raw nonces)
    nonce: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    # The OAuth state parameter (used to correlate login and launch)
    state: Mapped[str] = mapped_column(String(64), nullable=False)

    registration_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("lti_registrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Unix timestamp when this nonce expires
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    # Relationships
    registration: Mapped["LTIRegistration"] = relationship(
        "LTIRegistration",
        back_populates="nonces",
    )

    def __repr__(self) -> str:
        return f"<LTINonce expires={self.expires_at}>"


# ── Canvas Submissions ────────────────────────────────────────────────────────

class CanvasSubmissionStatus(str, Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    REPORTED   = "reported"
    SKIPPED    = "skipped"
    FAILED     = "failed"


class CanvasSubmission(Base, UUIDMixin, TimestampMixin):
    """
    Tracks each Canvas submission event through the Original pipeline.

    Created when a Canvas webhook fires; updated as the submission moves
    through scoring and report posting.  Links the Canvas submission ID
    back to Original's Submission record once scoring completes.
    """

    __tablename__ = "canvas_submissions"

    # Canvas-side identifiers
    canvas_submission_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    canvas_assignment_id: Mapped[str] = mapped_column(String(255), nullable=False)
    canvas_course_id: Mapped[str] = mapped_column(String(255), nullable=False)
    canvas_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    submission_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="online_text_entry"
    )

    # Canvas API access (encrypted at rest in production via DB-level encryption)
    canvas_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    access_token: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Original-side cross-reference
    original_submission_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("submissions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Pipeline status
    status: Mapped[CanvasSubmissionStatus] = mapped_column(
        String(20),
        default=CanvasSubmissionStatus.PENDING,
        index=True,
    )
    report_posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:
        return f"<CanvasSubmission {self.canvas_submission_id} ({self.status})>"
