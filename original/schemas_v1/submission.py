"""
schemas_v1/submission.py — Submission and scoring schemas.

Pydantic v2 schemas for submission and scoring endpoints.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Text cleaning helpers ────────────────────────────────────────────────────
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_SPACE_RE = re.compile(r"\s{3,}")

def _clean_submission_text(text: str) -> str:
    """Strip HTML/markdown artefacts and normalise whitespace."""
    text = _HTML_TAG_RE.sub(" ", text)          # strip HTML tags
    text = _MULTI_SPACE_RE.sub(" ", text)        # collapse excessive whitespace
    return text.strip()


class _TextValidationMixin:
    """Shared text validators for submission-related schemas."""

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        v = _clean_submission_text(v)
        if not v:
            raise ValueError("Text must not be empty after cleaning")
        word_count = len(v.split())
        if word_count < 50:
            raise ValueError(
                f"Text too short for reliable analysis ({word_count} words). "
                f"Minimum 50 words required."
            )
        if word_count > 20000:
            raise ValueError(
                f"Text too long ({word_count} words). Maximum 20,000 words."
            )
        # UTF-8 enforcement: reject if text contains null bytes
        if "\x00" in v:
            raise ValueError("Text contains null bytes")
        return v


class ScoreRequest(_TextValidationMixin, BaseModel):
    """Request to score a submission against a student's writing profile."""

    text: str = Field(
        ...,
        min_length=50,
        description="The submission text to score (50–20,000 words).",
        json_schema_extra={"example": "In this essay I will argue that Paul's conception of justification..."},
    )
    submission_id: Optional[str] = Field(None, description="Optional client-side submission ID for correlation.")
    assignment: Optional[str] = Field(None, description="Assignment name (e.g. 'Midterm Essay').")
    course_id: Optional[str] = Field(None, description="Course ID if applicable.")


class ParagraphArcOut(BaseModel):
    """Per-paragraph tension arc metrics."""

    model_config = ConfigDict(from_attributes=True)

    index: int
    peak_count: int
    resolved_peaks: int
    resolution_ratio: float
    mean_tension: float
    max_tension: float


class TensionArcOut(BaseModel):
    """
    Catastrophe/eucatastrophe stylometric fingerprint.

    κ = σ(ρ)·(1−μ(ρ)) — catastrophe index.
    High κ → human writing with genuine unresolved tension.
    Low κ + flat max(T) → AI-typical eucatastrophic prose.
    """

    model_config = ConfigDict(from_attributes=True)

    catastrophe_index: float = Field(..., description="κ = σ(ρ)·(1−μ(ρ)). Core signal.")
    resolution_ratio_mean: float = Field(..., description="μ(ρ) — mean tension-peak resolution ratio.")
    resolution_ratio_std: float = Field(..., description="σ(ρ) — std deviation of resolution ratios.")
    mean_tension: float = Field(..., description="μ(T) — mean sentence tension amplitude.")
    max_tension: float = Field(..., description="max T(i) — AI rarely exceeds 0.18 in academic prose.")
    authenticity_signal: Optional[float] = Field(
        None, description="Deviation from student's own κ baseline (None if no baseline yet)."
    )
    arc_flag: str = Field(
        ..., description="'authentic' | 'ai_typical' | 'review' | 'insufficient_length'."
    )
    arc_flag_reason: str = Field(..., description="Human-readable explanation for the arc flag.")
    tension_series: List[float] = Field(
        ..., description="Per-sentence T(i) values for chart rendering."
    )
    paragraph_arcs: List[ParagraphArcOut] = Field(
        default_factory=list,
        description="Per-paragraph arc summaries.",
    )


class ScoreResponse(BaseModel):
    """Authorship scoring result with quantum deviation analysis."""

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    submission_id: str = Field(..., description="Unique submission identifier.")
    student_id: str = Field(..., description="Student whose baseline was compared against.")
    status: str = Field(..., description="Scoring status: pending, scoring, scored, or failed.")
    deviation_score: float = Field(
        ...,
        ge=0.0, le=1.0,
        description="Deviation from baseline (0 = identical to baseline, 1 = maximum deviation). "
                    "This is the primary authorship signal.",
    )
    authorship_probability: float = Field(
        ...,
        ge=0.0, le=1.0,
        description="Born-rule probability that the submission was written by this student.",
    )
    recommended_action: str = Field(
        ...,
        description="System recommendation: no_action (0–0.40), monitor (0.40–0.55), "
                    "schedule_conversation (0.55–0.75), escalate (0.75+).",
    )
    rationale: str = Field(..., description="Human-readable explanation for the recommendation.")
    baseline_confidence: Dict = Field(
        ...,
        description="Confidence metrics: purity (density matrix purity), sample_count, authenticated_count.",
    )
    interference: Dict = Field(
        ...,
        description="Top constructive and destructive feature contributions to the deviation score.",
    )
    feature_vector: Dict = Field(..., description="All 89 normalised feature values for this submission (Tiers 1–15).")
    baseline_vector: Dict = Field(..., description="Baseline diagonal values for comparison.")
    model_version: str = Field(..., description="Scoring model version used.")
    scored_at: datetime = Field(..., description="Timestamp when scoring completed.")
    catastrophic_drift: bool = Field(
        False,
        description="True when the submission is >3 SDs from the baseline mean across all features. "
                    "Triggers immediate escalation regardless of the deviation score.",
    )
    catastrophic_drift_rms_z: float = Field(
        0.0,
        description="RMS z-score across all features (>3.0 triggers catastrophic drift alert).",
    )
    tension_arc: Optional[TensionArcOut] = Field(
        None, description="Tension arc analysis result (None if text too short or NLP unavailable)."
    )


class BaselineAddRequest(_TextValidationMixin, BaseModel):
    """Request to add a verified writing sample to a student's baseline profile."""

    text: str = Field(
        ...,
        min_length=50,
        description="The baseline text (50–20,000 words). Must be authenticated writing by this student.",
        json_schema_extra={"example": "The doctrine of justification by faith alone has been central to Reformed theology..."},
    )
    assignment: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Assignment name this sample came from.",
        json_schema_extra={"example": "Systematic Theology I — Essay 2"},
    )
    provenance: str = Field(
        "verified",
        description=(
            "Authentication level: 'proctored' (in-class exam), 'verified' (instructor-confirmed), "
            "'canvas' (imported via Canvas LTI), or 'unverified' (student-submitted)."
        ),
    )
    submitted_at: Optional[datetime] = Field(
        None,
        description="Original submission timestamp (defaults to now if omitted).",
    )

    @field_validator("provenance")
    @classmethod
    def validate_provenance(cls, v: str) -> str:
        if v not in _VALID_PROVENANCES:
            raise ValueError(
                f"Invalid provenance '{v}'. Must be one of: {', '.join(sorted(_VALID_PROVENANCES))}"
            )
        return v


class BaselineAddResponse(BaseModel):
    """Response after adding a baseline sample."""

    model_config = ConfigDict(protected_namespaces=())

    sample_id: str
    student_id: str
    feature_count: int
    word_count: int
    provenance: str
    model_version: str
    new_sample_count: int


_VALID_ACTIONS = {"escalate", "monitor", "clear", "schedule_conversation"}
_VALID_PROVENANCES = {"proctored", "verified", "canvas", "unverified"}


class DecisionRequest(BaseModel):
    """Request body for recording an instructor decision."""

    action: str = Field(
        ...,
        description=f"One of: {', '.join(sorted(_VALID_ACTIONS))}",
    )
    notes: Optional[str] = Field(None, max_length=2000)

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in _VALID_ACTIONS:
            raise ValueError(
                f"Invalid action '{v}'. Must be one of: {', '.join(sorted(_VALID_ACTIONS))}"
            )
        return v


class SubmissionListResponse(BaseModel):
    """Paginated list of submissions."""

    items: List[ScoreResponse]
    total: int
    page: int
    limit: int


class SubmissionDetail(BaseModel):
    """Detailed information about a submission."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    student_id: str
    course_id: str
    assignment: str
    word_count: int
    char_count: int
    submitted_at: datetime
    status: str
    created_at: datetime
