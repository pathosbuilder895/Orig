"""
schemas_v1/auth.py — Authentication request/response schemas.

Pydantic v2 schemas for auth endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from original.db.models import UserRole


class LoginRequest(BaseModel):
    """Request to log in a user."""

    email: EmailStr
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    """Response containing authentication tokens."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class RefreshRequest(BaseModel):
    """Request to refresh an access token."""

    refresh_token: str


class UserCreate(BaseModel):
    """Request to create a new user."""

    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8)
    role: UserRole = UserRole.INSTRUCTOR
    institution_id: str


class UserResponse(BaseModel):
    """Response with user information."""

    id: str
    email: str
    full_name: str
    role: str
    institution_id: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
