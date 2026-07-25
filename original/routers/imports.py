"""Roster/submission import surfaces: Turnitin CSV and the (unimplemented)
Canvas baseline import. Moved verbatim from original/api.py."""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, File, HTTPException, UploadFile

from ._shared import _repo

router = APIRouter()


# ── Turnitin CSV import ───────────────────────────────────────────────────────


@router.post("/import/courses/{course_id}/turnitin-csv")
async def import_turnitin_csv(course_id: str, file: UploadFile = File(...)):
    """
    Parse a Turnitin admin CSV export and create student/submission stubs.

    Expected columns (Turnitin default export):
      Last Name, First Name, Student ID, Assignment Title, Date Submitted,
      Similarity, File Name
    """
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig", errors="replace")  # handle BOM
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not decode CSV: {exc}") from exc

    reader = csv.DictReader(io.StringIO(text))
    # Normalise header keys: lowercase, strip whitespace
    rows = []
    for row in reader:
        rows.append({k.strip().lower(): v.strip() for k, v in row.items()})

    if not rows:
        raise HTTPException(status_code=422, detail="CSV is empty or has no data rows.")

    total_rows = len(rows)
    matched_students = 0
    created_students = 0
    flagged_submissions = 0
    unmatched_rows = 0
    errors: list[str] = []

    # Possible column names across Turnitin export versions
    def _col(row: dict, *candidates: str) -> str:
        for c in candidates:
            if c in row and row[c]:
                return row[c]
        return ""

    for i, row in enumerate(rows, 1):
        last = _col(row, "last name", "lastname", "surname")
        first = _col(row, "first name", "firstname")
        sid = _col(row, "student id", "studentid", "id", "user id")
        name = f"{first} {last}".strip() or sid or f"Student_{i}"

        if not (last or first or sid):
            unmatched_rows += 1
            errors.append(f"Row {i}: could not identify student (no name or ID)")
            continue

        student_id = sid or name.lower().replace(" ", "_")

        state = _repo().get(student_id)
        if state is None:
            state = _repo().get_or_create(student_id)
            created_students += 1
        else:
            matched_students += 1

        flagged_submissions += 1  # stub — no text yet, needs file upload

    return {
        "total_rows": total_rows,
        "matched_students": matched_students,
        "created_students": created_students,
        "flagged_submissions": flagged_submissions,
        "unmatched_rows": unmatched_rows,
        "errors": errors,
    }


# ── Canvas baseline import (not available in the pilot server) ────────────────
# These used to return demo placeholder JSON with a 200 status, which reads
# as success to any client that doesn't inspect the body. 501 is honest about
# there being no real Canvas integration on this server (WS-7 step 5). The
# professor.html call sites check r.ok and surface the detail string.


@router.post("/canvas/baseline/{student_id}/list-canvas-submissions")
def list_canvas_submissions(student_id: str, req: dict = None):
    """
    List a student's past Canvas submissions available for baseline import.
    Not implemented on this server — use 'Drop files' or 'Paste text' instead.
    """
    raise HTTPException(501, "Canvas import not available in the pilot server")


@router.post("/canvas/baseline/{student_id}/import-baseline")
def import_canvas_baseline(student_id: str, req: dict = None):
    """Not implemented on this server — see list_canvas_submissions."""
    raise HTTPException(501, "Canvas import not available in the pilot server")
