"""
schemas_v1/student.py — Student-related schemas.

Pydantic v2 schemas for student endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class StudentCreate(BaseModel):
    """Request to create a new student."""

    external_id: str = Field(..., min_length=1)
    full_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    course_id: Optional[str] = None


class StudentResponse(BaseModel):
    """Response with student information."""

    id: str
    external_id: str
    full_name: str
    email: str
    institution_id: str
    baseline_sample_count: int = 0
    last_submission_at: Optional[datetime] = None
    baseline_confidence: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class StudentStateResponse(BaseModel):
    """Full quantum state summary for a student."""

    student_id: str
    sample_count: int
    authenticated_count: int
    purity: float
    trajectory_direction: str
    trajectory_confidence: float
    effective_sample_count: float
    last_updated: datetime
