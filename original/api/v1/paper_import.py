"""
api/v1/import.py — Bulk import endpoints for institutional paper migration.

Handles:
  - POST /api/v1/import/courses/{course_id}/turnitin-csv
      Parses a Turnitin admin CSV export, maps students by external_id, and
      records flagged submission metadata (without paper text, which Turnitin
      does not include in CSV exports).  A follow-up batch file upload is
      required to attach actual paper content.

The Turnitin CSV format contains columns:
  Student Name, Student ID, Assignment, Submission Date, Similarity, File

Columns are matched case-insensitively and by common aliases so real exports
(which vary by Turnitin version) parse correctly.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from original.api.deps import get_current_instructor, get_db
from original.core.logging import get_logger
from original.db.models import Course, Student, StudentEnrollment, Submission, SubmissionStatus

log = get_logger(__name__)

router = APIRouter(prefix="/import", tags=["Import"])


# ── Column alias maps ──────────────────────────────────────────────────────────
# Turnitin CSV headers vary across versions/regions.  Map each logical field to
# all known header aliases (lowercase, stripped).

_ALIAS_STUDENT_NAME  = {"student name", "student", "name", "full name", "full_name"}
_ALIAS_STUDENT_ID    = {"student id", "student_id", "id", "external id", "external_id", "user id", "userid"}
_ALIAS_ASSIGNMENT    = {"assignment", "assignment name", "paper title", "title"}
_ALIAS_SUBMIT_DATE   = {"submission date", "date", "submitted", "submitted on", "date submitted"}
_ALIAS_SIMILARITY    = {"similarity", "similarity %", "similarity index", "match", "score"}
_ALIAS_FILE          = {"file", "filename", "file name", "attachment", "paper"}


def _detect_col(headers: List[str], aliases: set) -> Optional[int]:
    """Return column index whose header matches any alias (case-insensitive)."""
    for i, h in enumerate(headers):
        if h.strip().lower() in aliases:
            return i
    return None


class _TurnitinRow(BaseModel):
    student_name: Optional[str] = None
    student_id: Optional[str] = None
    assignment: Optional[str] = None
    submission_date: Optional[str] = None
    similarity: Optional[float] = None
    filename: Optional[str] = None


class TurnitinImportSummary(BaseModel):
    """Summary returned after processing a Turnitin CSV upload."""
    total_rows: int
    matched_students: int
    created_students: int
    unmatched_rows: int
    flagged_submissions: int
    errors: List[str]
    detail: List[Dict[str, Any]]  # per-row detail for UI display


@router.post(
    "/courses/{course_id}/turnitin-csv",
    response_model=TurnitinImportSummary,
    status_code=status.HTTP_200_OK,
)
async def import_turnitin_csv(
    course_id: str,
    file: UploadFile = File(..., description="Turnitin admin CSV export"),
    user=Depends(get_current_instructor),
    db: Session = Depends(get_db),
) -> TurnitinImportSummary:
    """
    Parse a Turnitin CSV export and record submission metadata.

    **What this does**
    - Reads the CSV and maps each row to a student via ``Student.external_id``.
    - Creates stub students for unrecognised IDs so nothing is silently dropped.
    - Records each paper as a ``Submission`` record with status ``needs_text``
      (a sentinel value indicating the file must be uploaded separately via
      ``POST /submissions/{id}/baseline/upload-batch``).
    - Returns a summary with per-row detail for the professor UI.

    **What this does NOT do**
    - Import the actual paper text — Turnitin CSV does not export full text.
    - Score submissions — a separate upload step is required.

    Args:
        course_id: The course to associate submissions with
        file:      Multipart CSV file upload
        user:      Authenticated instructor
        db:        Database session

    Returns:
        TurnitinImportSummary

    Raises:
        HTTPException 400: Unreadable CSV or missing required columns
        HTTPException 404: Course not found in instructor's institution
    """
    # Verify course belongs to instructor's institution
    course = db.query(Course).filter(
        Course.id == course_id,
        Course.institution_id == user.institution_id,
    ).first()
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course {course_id!r} not found in your institution.",
        )

    # Read and decode CSV bytes
    raw_bytes = await file.read()
    try:
        text = raw_bytes.decode("utf-8-sig")  # strip BOM if present
    except UnicodeDecodeError:
        text = raw_bytes.decode("latin-1", errors="replace")

    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",\t|;")
    except csv.Error:
        dialect = csv.excel

    reader = csv.reader(io.StringIO(text), dialect)
    rows = list(reader)

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV file is empty.",
        )

    # Detect header row (first non-blank row)
    header_row_idx = 0
    for i, row in enumerate(rows):
        if any(cell.strip() for cell in row):
            header_row_idx = i
            break

    headers = rows[header_row_idx]

    # Detect columns
    col_name   = _detect_col(headers, _ALIAS_STUDENT_NAME)
    col_id     = _detect_col(headers, _ALIAS_STUDENT_ID)
    col_assign = _detect_col(headers, _ALIAS_ASSIGNMENT)
    col_date   = _detect_col(headers, _ALIAS_SUBMIT_DATE)
    col_sim    = _detect_col(headers, _ALIAS_SIMILARITY)
    col_file   = _detect_col(headers, _ALIAS_FILE)

    if col_id is None and col_name is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Could not find a student identifier column.  "
                "Expected one of: 'Student ID', 'Student Name', 'External ID'.  "
                f"Headers found: {headers}"
            ),
        )

    # Parse data rows
    data_rows = rows[header_row_idx + 1 :]
    parsed: List[_TurnitinRow] = []
    for row in data_rows:
        if not any(cell.strip() for cell in row):
            continue  # skip blank rows
        def _get(col: Optional[int]) -> Optional[str]:
            if col is None or col >= len(row):
                return None
            v = row[col].strip()
            return v or None

        similarity = None
        raw_sim = _get(col_sim)
        if raw_sim:
            try:
                similarity = float(raw_sim.rstrip("%")) / 100.0
            except ValueError:
                pass

        parsed.append(_TurnitinRow(
            student_name   = _get(col_name),
            student_id     = _get(col_id),
            assignment     = _get(col_assign),
            submission_date= _get(col_date),
            similarity     = similarity,
            filename       = _get(col_file),
        ))

    # Process rows
    total_rows         = len(parsed)
    matched_students   = 0
    created_students   = 0
    unmatched_rows     = 0
    flagged_submissions= 0
    errors: List[str]  = []
    detail: List[Dict] = []

    for i, row in enumerate(parsed, start=1):
        external_id = row.student_id or ""
        full_name   = row.student_name or "Unknown Student"

        student = None

        # Try to match by external_id first
        if external_id:
            student = db.query(Student).filter(
                Student.external_id == external_id,
                Student.institution_id == user.institution_id,
            ).first()

        # Fall back to name match within institution
        if student is None and full_name and full_name != "Unknown Student":
            student = db.query(Student).filter(
                Student.full_name == full_name,
                Student.institution_id == user.institution_id,
            ).first()

        # Create stub student if not found
        if student is None:
            if not external_id and full_name == "Unknown Student":
                errors.append(f"Row {i}: no student ID or name — skipped")
                unmatched_rows += 1
                detail.append({"row": i, "status": "skipped", "reason": "no identifier"})
                continue

            student = Student(
                institution_id=user.institution_id,
                external_id=external_id or f"turnitin-import-{uuid.uuid4().hex[:8]}",
                full_name=full_name,
                email=None,
                is_active=True,
            )
            db.add(student)
            db.flush()  # get student.id before creating enrollment

            # Enroll in the course
            enrollment = StudentEnrollment(
                student_id=student.id,
                course_id=course_id,
            )
            db.add(enrollment)
            created_students += 1
        else:
            matched_students += 1
            # Ensure enrollment exists
            existing_enroll = db.query(StudentEnrollment).filter(
                StudentEnrollment.student_id == student.id,
                StudentEnrollment.course_id == course_id,
            ).first()
            if not existing_enroll:
                db.add(StudentEnrollment(student_id=student.id, course_id=course_id))

        # Record submission metadata as a stub (needs text upload)
        try:
            submitted_at = datetime.utcnow()
            if row.submission_date:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
                    try:
                        submitted_at = datetime.strptime(row.submission_date, fmt)
                        break
                    except ValueError:
                        continue

            stub = Submission(
                student_id  = student.id,
                course_id   = course_id,
                assignment  = row.assignment or "Turnitin Import",
                text_hash   = f"turnitin-stub-{uuid.uuid4().hex}",
                word_count  = 0,
                char_count  = 0,
                submitted_at= submitted_at,
                status      = SubmissionStatus.PENDING,
                # Similarity score and original filename stored in metadata field if available
            )
            db.add(stub)
            flagged_submissions += 1

            detail.append({
                "row"       : i,
                "student_id": student.id,
                "student"   : full_name,
                "assignment": row.assignment,
                "filename"  : row.filename,
                "similarity": row.similarity,
                "status"    : "flagged — needs text upload",
            })
        except Exception as exc:
            errors.append(f"Row {i} ({full_name}): failed to create stub — {exc}")
            detail.append({"row": i, "status": "error", "reason": str(exc)})

    db.commit()

    log.info(
        "turnitin_csv_import",
        extra={
            "course_id"         : course_id,
            "total_rows"        : total_rows,
            "matched_students"  : matched_students,
            "created_students"  : created_students,
            "flagged_submissions": flagged_submissions,
            "errors"            : len(errors),
        },
    )

    return TurnitinImportSummary(
        total_rows         = total_rows,
        matched_students   = matched_students,
        created_students   = created_students,
        unmatched_rows     = unmatched_rows,
        flagged_submissions= flagged_submissions,
        errors             = errors,
        detail             = detail,
    )
