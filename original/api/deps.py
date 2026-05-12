"""
api/deps.py — FastAPI dependency functions.

Provides database session, authentication, and authorization dependencies.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from original.auth.jwt import decode_token
from original.core.exceptions import AuthError, ForbiddenError
from original.core.logging import get_logger, set_request_context
from original.db.models import Student, User, UserRole
from original.db.session import get_db  # re-export — same object, so test overrides apply

log = get_logger(__name__)

# HTTP Bearer — missing header returns 401 (not FastAPI's default 403 for no credentials)
security = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """
    Verify JWT token and return the current user.

    Raises:
        AuthError: If token is invalid or user is inactive
    """
    if credentials is None:
        raise AuthError(detail="Not authenticated")

    token = credentials.credentials

    try:
        token_data = decode_token(token)
    except AuthError:
        raise

    # Load user from database
    user = db.query(User).filter(User.id == token_data.sub).first()
    if not user or not user.is_active:
        raise AuthError(detail="User not found or inactive")

    # Set request context for logging
    set_request_context(
        request_id="",  # Set by middleware
        user_id=user.id,
        institution=user.institution_id,
    )

    return user


def get_current_instructor(
    user: User = Depends(get_current_user),
) -> User:
    """
    Verify current user is an instructor or admin.

    Raises:
        ForbiddenError: If user is not an instructor or admin
    """
    if user.role not in (UserRole.INSTRUCTOR, UserRole.ADMIN):
        raise ForbiddenError(detail="Instructor or admin access required")
    return user


def get_current_admin(
    user: User = Depends(get_current_user),
) -> User:
    """
    Verify current user is an admin.

    Raises:
        ForbiddenError: If user is not an admin
    """
    if user.role != UserRole.ADMIN:
        raise ForbiddenError(detail="Admin access required")
    return user


def require_same_institution(
    student_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Student:
    """
    Verify that a student belongs to the current user's institution.

    Args:
        student_id: ID of the student
        user: Current user
        db: Database session

    Returns:
        Student object

    Raises:
        HTTPException: If student not found or in different institution
    """
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    if student.institution_id != user.institution_id:
        raise ForbiddenError(detail="Student not in your institution")

    return student
