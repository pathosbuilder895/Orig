"""
original/middleware/rbac.py — Role-Based Access Control (RBAC) middleware.

Enforces access control rules:
- Students can only view their own data (submissions, baselines, scores)
- Teachers can only view students in their courses
- Admins can view their institution's data
- Compliance officers have read-only access to audit logs

Implementation:
- Implemented as FastAPI dependency injection
- Used in route handlers via Depends()
- Raises HTTPException(403) on unauthorized access
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from original.auth.jwt import TokenData, decode_token
from original.core.exceptions import AuthError
from original.db.models import User, UserRole, Student, Submission, Course, StudentEnrollment
from original.db.session import get_db


# ── Permission Checks ────────────────────────────────────────────────────────────


def get_current_user(token: Optional[str] = None, db: Session = Depends(get_db)) -> User:
    """
    Extract and validate the current user from JWT token.

    Args:
        token: JWT token from Authorization header (passed by FastAPI)
        db: Database session

    Returns:
        User object

    Raises:
        HTTPException(401): If token is invalid or user not found
    """
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No token provided")

    try:
        # Decode token (may raise AuthError)
        token_data = decode_token(token)
    except AuthError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=e.detail,
        )

    # Fetch user from database
    user = db.query(User).filter(User.id == token_data.sub).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


def require_role(required_role: UserRole) -> callable:
    """
    Factory function to create role-checking dependencies.

    Args:
        required_role: The role required to access the route

    Returns:
        A dependency function that checks the role

    Example:
        @app.get("/admin/users")
        async def list_all_users(user: User = Depends(require_role(UserRole.ADMIN))):
            return {"users": ...}
    """

    async def check_role(user: User = Depends(get_current_user)) -> User:
        if user.role != required_role and user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This endpoint requires {required_role.value} role",
            )
        return user

    return check_role


# ── Data Access Checks ───────────────────────────────────────────────────────────


def check_student_access(student_id: str, user: User, db: Session) -> bool:
    """
    Check if the user can access a student's data.

    Rules:
    - Students can view their own data
    - Teachers can view students in their courses
    - Admins can view any student in their institution
    - Compliance officers cannot view student data directly

    Args:
        student_id: Student UUID
        user: Current user
        db: Database session

    Returns:
        True if access allowed, False otherwise
    """
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        return False

    if user.role == UserRole.STUDENT:
        # Students can only view their own data
        return user.id == student_id

    if user.role == UserRole.TEACHER:
        # Teachers can view students in their courses
        is_enrolled = (
            db.query(StudentEnrollment)
            .join(Course)
            .filter(
                StudentEnrollment.student_id == student_id,
                Course.instructor_id == user.id,
            )
            .first()
            is not None
        )
        return is_enrolled

    if user.role == UserRole.ADMIN:
        # Admins can view students in their institution
        return student.institution_id == user.institution_id

    if user.role == UserRole.COMPLIANCE_OFFICER:
        # Compliance officers have read-only audit access (not direct data access)
        return False

    return False


def check_submission_access(submission_id: str, user: User, db: Session) -> bool:
    """
    Check if the user can access a submission.

    Rules:
    - Students can view their own submissions
    - Teachers can view submissions from their course students
    - Admins can view any submission in their institution

    Args:
        submission_id: Submission UUID
        user: Current user
        db: Database session

    Returns:
        True if access allowed, False otherwise
    """
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        return False

    # Check student access first (covers student + teacher + admin cases)
    return check_student_access(submission.student_id, user, db)


def check_course_access(course_id: str, user: User, db: Session) -> bool:
    """
    Check if the user can access a course.

    Rules:
    - Teachers can access their own courses
    - Students can access courses they're enrolled in
    - Admins can access any course in their institution

    Args:
        course_id: Course UUID
        user: Current user
        db: Database session

    Returns:
        True if access allowed, False otherwise
    """
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        return False

    if user.role == UserRole.TEACHER:
        return course.instructor_id == user.id

    if user.role == UserRole.STUDENT:
        is_enrolled = (
            db.query(StudentEnrollment)
            .filter(
                StudentEnrollment.course_id == course_id,
                StudentEnrollment.student_id == user.id,
            )
            .first()
            is not None
        )
        return is_enrolled

    if user.role == UserRole.ADMIN:
        return course.institution_id == user.institution_id

    return False


def check_institution_access(institution_id: str, user: User) -> bool:
    """
    Check if the user can access an institution's data.

    Rules:
    - Admins can only access their own institution
    - Compliance officers can access any institution (read-only)
    - Others cannot access institution data directly

    Args:
        institution_id: Institution UUID
        user: Current user

    Returns:
        True if access allowed, False otherwise
    """
    if user.role == UserRole.ADMIN:
        return user.institution_id == institution_id

    if user.role == UserRole.COMPLIANCE_OFFICER:
        # Compliance officers have read-only access for audits
        return True

    return False


# ── Dependency Factories ─────────────────────────────────────────────────────────


def ensure_student_access(
    student_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> User:
    """
    Dependency that ensures user can access a student.

    Args:
        student_id: Student UUID (passed in route)
        user: Current user
        db: Database session

    Returns:
        User if access allowed

    Raises:
        HTTPException(403): If access denied

    Example:
        @app.get("/students/{student_id}")
        async def get_student(user = Depends(ensure_student_access("student_id"))):
            return {"student": ...}
    """
    if not check_student_access(student_id, user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this student's data",
        )
    return user


def ensure_submission_access(
    submission_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> User:
    """
    Dependency that ensures user can access a submission.

    Args:
        submission_id: Submission UUID (passed in route)
        user: Current user
        db: Database session

    Returns:
        User if access allowed

    Raises:
        HTTPException(403): If access denied

    Example:
        @app.get("/submissions/{submission_id}")
        async def get_submission(user = Depends(ensure_submission_access("submission_id"))):
            return {"submission": ...}
    """
    if not check_submission_access(submission_id, user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this submission",
        )
    return user


def ensure_course_access(
    course_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> User:
    """
    Dependency that ensures user can access a course.

    Args:
        course_id: Course UUID (passed in route)
        user: Current user
        db: Database session

    Returns:
        User if access allowed

    Raises:
        HTTPException(403): If access denied

    Example:
        @app.get("/courses/{course_id}")
        async def get_course(user = Depends(ensure_course_access("course_id"))):
            return {"course": ...}
    """
    if not check_course_access(course_id, user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this course",
        )
    return user


def ensure_institution_access(
    institution_id: str, user: User = Depends(get_current_user)
) -> User:
    """
    Dependency that ensures user can access an institution.

    Args:
        institution_id: Institution UUID (passed in route)
        user: Current user

    Returns:
        User if access allowed

    Raises:
        HTTPException(403): If access denied

    Example:
        @app.get("/institutions/{institution_id}")
        async def get_institution(user = Depends(ensure_institution_access("institution_id"))):
            return {"institution": ...}
    """
    if not check_institution_access(institution_id, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this institution",
        )
    return user


# ── RBAC Summary ─────────────────────────────────────────────────────────────────

"""
RBAC Access Matrix
==================

Data Type           | Student | Teacher | Admin | Compliance
--------------------|---------|---------|-------|----------
Own data            | ✓       | ✓       | ✓     | ✗
Course data         | Enroll  | Own     | Inst  | ✗
Student data        | Own     | Course  | Inst  | ✗
Submission data     | Own     | Course  | Inst  | ✗
Baseline data       | Own     | Course  | Inst  | ✗
Scoring results     | Own     | Course  | Inst  | ✗
Instructor decisions| Own     | Own     | Inst  | ✗
Audit logs          | No      | No      | Inst  | ✓ (RO)
User management     | No      | No      | Inst  | No
Admin settings      | No      | No      | Inst  | No

Legend:
  ✓    = Full access
  ✗    = No access
  RO   = Read-only
  Own  = Own record only
  Enroll = Enrolled courses only
  Course = Courses taught / students in course
  Inst = Institution data only
"""

__all__ = [
    "get_current_user",
    "require_role",
    "check_student_access",
    "check_submission_access",
    "check_course_access",
    "check_institution_access",
    "ensure_student_access",
    "ensure_submission_access",
    "ensure_course_access",
    "ensure_institution_access",
]
