"""
api/v1/students.py — Student management endpoints.

Handles student CRUD, state retrieval, and baseline sample management.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from original.api.deps import get_current_instructor, get_db, require_same_institution
from original.core.logging import get_logger
from original.db.models import BaselineSample, Student, StudentEnrollment, Submission
from original.schemas_v1.student import (
    StudentCreate,
    StudentResponse,
    StudentStateResponse,
)

log = get_logger(__name__)

router = APIRouter(prefix="/students", tags=["Students"])


@router.get("/", status_code=status.HTTP_200_OK)
def list_students(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    course_id: Optional[str] = None,
    status_filter: str = "active",
    user=Depends(get_current_instructor),
    db: Session = Depends(get_db),
):
    """
    List students in the instructor's institution.

    Args:
        skip: Number of records to skip
        limit: Maximum records to return
        course_id: Filter by course ID
        status_filter: "active", "all"
        user: Current user (instructor)
        db: Database session

    Returns:
        List of students with counts
    """
    query = db.query(Student).filter(
        Student.institution_id == user.institution_id
    )

    if status_filter == "active":
        query = query.filter(Student.is_active == True)

    if course_id:
        query = (
            query.join(StudentEnrollment)
            .filter(StudentEnrollment.course_id == course_id)
        )

    total = query.count()
    students = query.offset(skip).limit(limit).all()

    # Enrich with baseline counts
    results = []
    for student in students:
        baseline_count = (
            db.query(func.count(BaselineSample.id))
            .filter(
                BaselineSample.student_id == student.id,
                BaselineSample.is_active == True,
            )
            .scalar()
        )
        last_submission = (
            db.query(func.max(Submission.submitted_at))
            .filter(Submission.student_id == student.id)
            .scalar()
        )
        results.append(
            StudentResponse(
                id=student.id,
                external_id=student.external_id,
                full_name=student.full_name,
                email=student.email,
                institution_id=student.institution_id,
                baseline_sample_count=baseline_count or 0,
                last_submission_at=last_submission,
            )
        )

    return {"items": results, "total": total, "skip": skip, "limit": limit}


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_student(
    request: StudentCreate,
    user=Depends(get_current_instructor),
    db: Session = Depends(get_db),
) -> StudentResponse:
    """
    Create a new student.

    Args:
        request: Student creation request
        user: Current user (must be instructor or admin)
        db: Database session

    Returns:
        Created student
    """
    # Check if student already exists
    existing = db.query(Student).filter(
        Student.external_id == request.external_id,
        Student.institution_id == user.institution_id,
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Student already exists",
        )

    student = Student(
        external_id=request.external_id,
        full_name=request.full_name,
        email=request.email,
        institution_id=user.institution_id,
    )
    db.add(student)
    db.commit()
    db.refresh(student)

    # Enroll in course if provided
    if request.course_id:
        enrollment = StudentEnrollment(
            student_id=student.id,
            course_id=request.course_id,
        )
        db.add(enrollment)
        db.commit()

    return StudentResponse.model_validate(student)


@router.get("/{student_id}", status_code=status.HTTP_200_OK)
def get_student(
    student: Student = Depends(require_same_institution),
    db: Session = Depends(get_db),
) -> StudentResponse:
    """
    Get a student's information.

    Args:
        student: Student (via dependency)
        db: Database session

    Returns:
        StudentResponse
    """
    baseline_count = (
        db.query(func.count(BaselineSample.id))
        .filter(
            BaselineSample.student_id == student.id,
            BaselineSample.is_active == True,
        )
        .scalar()
    )
    last_submission = (
        db.query(func.max(Submission.submitted_at))
        .filter(Submission.student_id == student.id)
        .scalar()
    )

    return StudentResponse(
        id=student.id,
        external_id=student.external_id,
        full_name=student.full_name,
        email=student.email,
        institution_id=student.institution_id,
        baseline_sample_count=baseline_count or 0,
        last_submission_at=last_submission,
    )


@router.get("/{student_id}/state", status_code=status.HTTP_200_OK)
def get_student_state(
    student: Student = Depends(require_same_institution),
    db: Session = Depends(get_db),
) -> StudentStateResponse:
    """
    Get the quantum state for a student.

    Args:
        student: Student (via dependency)
        db: Database session

    Returns:
        StudentStateResponse with state metrics
    """
    from original.constants import AUTH_WEIGHTS
    from original.quantum.state import StudentState, BaselineSample as QBaselineSample

    # Load all active baseline samples
    baseline_samples = (
        db.query(BaselineSample)
        .filter(
            BaselineSample.student_id == student.id,
            BaselineSample.is_active == True,
        )
        .order_by(BaselineSample.created_at)
        .all()
    )

    # Convert to quantum baseline samples
    q_samples = []
    for sample in baseline_samples:
        import numpy as np

        vector = np.array(
            [sample.feature_vector.get(k, 0.0) for k in range(34)],
            dtype=np.float64,
        )
        q_sample = QBaselineSample(
            text="",
            vector=vector,
            provenance=sample.provenance,
            auth_weight=sample.auth_weight,
            assignment=sample.assignment,
            submitted_at=sample.submitted_at.isoformat(),
        )
        q_samples.append(q_sample)

    # Build quantum state
    state = StudentState(student_id=student.id, samples=q_samples)

    authenticated_count = sum(
        1 for s in baseline_samples if s.auth_weight > 0
    )

    return StudentStateResponse(
        student_id=student.id,
        sample_count=len(baseline_samples),
        authenticated_count=authenticated_count,
        purity=state.purity,
        trajectory_direction=state.trajectory.direction,
        trajectory_confidence=state.trajectory.confidence,
        effective_sample_count=state.effective_sample_count,
        last_updated=datetime.utcnow(),
    )


@router.get("/{student_id}/baseline", status_code=status.HTTP_200_OK)
def list_baseline_samples(
    student: Student = Depends(require_same_institution),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    List baseline samples for a student.

    Args:
        student: Student (via dependency)
        skip: Number of records to skip
        limit: Maximum records to return
        db: Database session

    Returns:
        List of baseline samples
    """
    query = db.query(BaselineSample).filter(
        BaselineSample.student_id == student.id,
        BaselineSample.is_active == True,
    )
    total = query.count()
    samples = query.order_by(BaselineSample.created_at.desc()).offset(skip).limit(limit).all()

    return {
        "items": [
            {
                "id": s.id,
                "assignment": s.assignment,
                "provenance": s.provenance,
                "word_count": s.word_count,
                "submitted_at": s.submitted_at,
                "created_at": s.created_at,
            }
            for s in samples
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


class RosterImportResult(BaseModel):
    """Result of a bulk CSV roster import."""
    created: int
    skipped_duplicates: int
    errors: List[str]
    student_ids: List[str]


@router.post("/roster/import", response_model=RosterImportResult, status_code=status.HTTP_201_CREATED)
async def import_roster_csv(
    file: UploadFile = File(...),
    course_id: Optional[str] = Query(None, description="Enroll imported students in this course."),
    user=Depends(get_current_instructor),
    db: Session = Depends(get_db),
):
    """
    Bulk-import students from a CSV file.

    Expected columns (case-insensitive, order flexible):
      external_id, full_name, email

    Returns counts of created/skipped students and a list of their IDs.
    Students whose external_id already exists in this institution are skipped
    (not updated) to avoid overwriting existing profiles.
    """
    content = await file.read()
    text = content.decode("utf-8-sig", errors="replace")  # handle Excel BOM

    try:
        reader = csv.DictReader(io.StringIO(text))
        # Normalise header names: strip whitespace, lowercase
        rows = []
        for row in reader:
            rows.append({k.strip().lower(): v.strip() for k, v in row.items()})
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not parse CSV: {exc}",
        )

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="CSV file is empty or has no data rows.",
        )

    # Accept several column name aliases
    _ID_KEYS   = {"external_id", "student_id", "id", "canvas_user_id"}
    _NAME_KEYS = {"full_name", "name", "student name", "student_name"}
    _EMAIL_KEYS = {"email", "email_address", "student_email"}

    def _pick(row: dict, keys: set) -> str:
        for k in keys:
            if k in row and row[k]:
                return row[k]
        return ""

    created = 0
    skipped = 0
    errors: List[str] = []
    student_ids: List[str] = []

    for i, row in enumerate(rows, start=2):  # row 1 is the header
        external_id = _pick(row, _ID_KEYS)
        full_name   = _pick(row, _NAME_KEYS)
        email       = _pick(row, _EMAIL_KEYS)

        if not external_id and not full_name:
            errors.append(f"Row {i}: missing both external_id and full_name — skipped.")
            continue

        # Auto-generate external_id from name if not supplied
        if not external_id and full_name:
            parts = full_name.lower().split()
            last  = parts[-1] if parts else "student"
            first = parts[0][0] if parts else "x"
            external_id = f"{last}_{first}"

        # Duplicate check
        existing = db.query(Student).filter(
            Student.external_id == external_id,
            Student.institution_id == user.institution_id,
        ).first()

        if existing:
            skipped += 1
            student_ids.append(existing.id)
            continue

        try:
            student = Student(
                external_id=external_id,
                full_name=full_name or external_id,
                email=email or None,
                institution_id=user.institution_id,
            )
            db.add(student)
            db.flush()  # get student.id without committing yet

            if course_id:
                db.add(StudentEnrollment(student_id=student.id, course_id=course_id))

            db.commit()
            db.refresh(student)
            created += 1
            student_ids.append(student.id)

        except Exception as exc:
            db.rollback()
            errors.append(f"Row {i} ({external_id}): {str(exc)[:120]}")

    log.info(
        "Roster CSV import complete",
        extra={
            "institution_id": user.institution_id,
            "created": created,
            "skipped": skipped,
            "errors": len(errors),
        },
    )
    return RosterImportResult(
        created=created,
        skipped_duplicates=skipped,
        errors=errors,
        student_ids=student_ids,
    )


@router.delete("/{student_id}/baseline/{sample_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_baseline_sample(
    student: Student = Depends(require_same_institution),
    sample_id: str = None,
    db: Session = Depends(get_db),
):
    """
    Soft-delete a baseline sample.

    Args:
        student: Student (via dependency)
        sample_id: Baseline sample ID
        db: Database session
    """
    sample = db.query(BaselineSample).filter(
        BaselineSample.id == sample_id,
        BaselineSample.student_id == student.id,
    ).first()

    if not sample:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sample not found",
        )

    sample.is_active = False
    db.commit()
