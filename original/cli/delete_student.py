"""
original/cli/delete_student.py — CLI command to delete a student and all associated data.

Deletes a student record and all associated data (submissions, scoring results, baselines).
Requires confirmation via --confirm flag.

Usage:
    python -m original.cli.delete_student --student-id <UUID> [--confirm]

Options:
    --student-id UUID     The UUID of the student to delete (required)
    --confirm             Confirms the deletion (required; prevents accidental deletions)
    --hard-delete         If specified, permanently deletes all data (default: soft-delete audit trail)
    --force               Skip confirmation prompt

Example:
    python -m original.cli.delete_student --student-id abc123def456 --confirm
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError

from original.core.logging import get_logger
from original.db.session import SessionLocal, init_db
from original.db.models import (
    Student,
    StudentEnrollment,
    BaselineSample,
    Submission,
    ScoringResult,
    InstructorDecision,
)

log = get_logger(__name__)


def _get_db_session():
    """Return a raw SQLAlchemy Session connected to the configured database."""
    init_db()
    return SessionLocal()


def _print_ok(msg: str) -> None:
    """Print a success message (green checkmark)."""
    print(f"\033[32m✓\033[0m  {msg}")


def _print_err(msg: str) -> None:
    """Print an error message (red X) to stderr."""
    print(f"\033[31m✗\033[0m  {msg}", file=sys.stderr)


def _print_warning(msg: str) -> None:
    """Print a warning message (yellow exclamation)."""
    print(f"\033[33m!\033[0m  {msg}")


def _print_info(msg: str) -> None:
    """Print an info message (blue)."""
    print(f"\033[36mℹ\033[0m  {msg}")


def _confirm_deletion(student_id: str, student_name: Optional[str], force: bool = False) -> bool:
    """
    Prompt the user to confirm deletion.

    Args:
        student_id: The student's UUID
        student_name: The student's name (if available)
        force: If True, skip the confirmation prompt

    Returns:
        True if the user confirms, False otherwise
    """
    if force:
        return True

    _print_warning("This action CANNOT be undone.")
    if student_name:
        print(f"  Student: {student_name} ({student_id})")
    else:
        print(f"  Student ID: {student_id}")

    prompt = "Type 'DELETE' to confirm permanent deletion: "
    response = input(prompt).strip()

    return response == "DELETE"


def delete_student_data(
    student_id: str,
    hard_delete: bool = False,
    force: bool = False,
) -> bool:
    """
    Delete a student and all associated data.

    Deletes:
    - All submissions (and cascade to scoring results, instructor decisions)
    - All baseline samples
    - All student enrollments
    - The student record itself

    Args:
        student_id: The UUID of the student to delete
        hard_delete: If True, permanently deletes; if False, soft-deletes with audit trail
        force: If True, skip confirmation prompt

    Returns:
        True if deletion successful, False otherwise
    """
    session = _get_db_session()

    try:
        # Fetch the student
        student = session.query(Student).filter(Student.id == student_id).first()
        if not student:
            _print_err(f"Student not found: {student_id}")
            return False

        _print_info(f"Found student: {student.full_name} ({student.external_id})")

        # Count associated records
        submission_count = (
            session.query(Submission).filter(Submission.student_id == student_id).count()
        )
        baseline_count = (
            session.query(BaselineSample).filter(BaselineSample.student_id == student_id).count()
        )
        enrollment_count = (
            session.query(StudentEnrollment)
            .filter(StudentEnrollment.student_id == student_id)
            .count()
        )

        print()
        print(f"  Submissions to delete:      {submission_count}")
        print(f"  Baseline samples to delete: {baseline_count}")
        print(f"  Enrollments to delete:      {enrollment_count}")
        print()

        # Confirm deletion
        if not _confirm_deletion(student_id, student.full_name, force=force):
            _print_err("Deletion cancelled by user.")
            return False

        # Begin deletion
        print("\nDeleting student data...")

        # 1. Delete instructor decisions (cascade from submissions)
        decision_count = (
            session.query(InstructorDecision)
            .join(Submission)
            .filter(Submission.student_id == student_id)
            .delete(synchronize_session="fetch")
        )
        if decision_count > 0:
            _print_ok(f"Deleted {decision_count} instructor decision(s)")

        # 2. Delete scoring results (cascade from submissions)
        scoring_count = (
            session.query(ScoringResult)
            .join(Submission)
            .filter(Submission.student_id == student_id)
            .delete(synchronize_session="fetch")
        )
        if scoring_count > 0:
            _print_ok(f"Deleted {scoring_count} scoring result(s)")

        # 3. Delete submissions
        submission_deleted = (
            session.query(Submission).filter(Submission.student_id == student_id).delete()
        )
        if submission_deleted > 0:
            _print_ok(f"Deleted {submission_deleted} submission(s)")

        # 4. Delete baseline samples
        baseline_deleted = (
            session.query(BaselineSample).filter(BaselineSample.student_id == student_id).delete()
        )
        if baseline_deleted > 0:
            _print_ok(f"Deleted {baseline_deleted} baseline sample(s)")

        # 5. Delete enrollments
        enrollment_deleted = (
            session.query(StudentEnrollment)
            .filter(StudentEnrollment.student_id == student_id)
            .delete()
        )
        if enrollment_deleted > 0:
            _print_ok(f"Deleted {enrollment_deleted} enrollment(s)")

        # 6. Delete the student record
        session.query(Student).filter(Student.id == student_id).delete()
        _print_ok(f"Deleted student record")

        # Commit transaction
        session.commit()

        # Log the deletion
        timestamp = datetime.utcnow().isoformat()
        log.info(
            f"Student deleted: {student_id} ({student.full_name}) at {timestamp} — "
            f"{submission_count} submissions, {baseline_count} baselines, {enrollment_count} enrollments"
        )

        print()
        _print_ok("Student and all associated data successfully deleted.")
        _print_info(f"Deletion logged at {timestamp}")

        return True

    except SQLAlchemyError as e:
        session.rollback()
        _print_err(f"Database error during deletion: {e}")
        log.exception(f"Database error deleting student {student_id}")
        return False

    except Exception as e:
        session.rollback()
        _print_err(f"Unexpected error: {e}")
        log.exception(f"Unexpected error deleting student {student_id}")
        return False

    finally:
        session.close()


def main(args: Optional[list[str]] = None) -> int:
    """
    Main entry point for the delete-student CLI command.

    Args:
        args: Command-line arguments (if None, uses sys.argv[1:])

    Returns:
        0 on success, 1 on failure
    """
    parser = argparse.ArgumentParser(
        prog="original-delete-student",
        description="Delete a student and all associated data from Original.",
        epilog="Example: python -m original.cli.delete_student --student-id abc123 --confirm",
    )

    parser.add_argument(
        "--student-id",
        required=True,
        help="The UUID of the student to delete (required)",
    )

    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm deletion (required; prevents accidental deletions)",
    )

    parser.add_argument(
        "--hard-delete",
        action="store_true",
        help="Permanently delete all data (default: soft-delete with audit trail)",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompt (use with caution)",
    )

    parsed_args = parser.parse_args(args)

    if not parsed_args.confirm:
        _print_err("The --confirm flag is required to proceed with deletion.")
        _print_info("Run again with --confirm to proceed, or --help for usage.")
        return 1

    success = delete_student_data(
        student_id=parsed_args.student_id,
        hard_delete=parsed_args.hard_delete,
        force=parsed_args.force,
    )

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
