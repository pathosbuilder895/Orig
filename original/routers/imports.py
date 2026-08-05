"""Roster/submission import surfaces: Turnitin CSV and the (unimplemented)
Canvas baseline import. Moved verbatim from original/api.py."""

from __future__ import annotations

import csv
import hashlib
import io
import logging

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from ..constants import AUTH_WEIGHTS
from ..features.pipeline import feature_vector
from ..quantum.state import BaselineSample
from ._shared import _authorize_provenance, _persist_or_503, _repo, _require_staff
from .students_baseline import _existing_text_hashes

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


# ── Canvas baseline import ───────────────────────────────────────────────────


def _canvas_required_ids(body: dict) -> tuple[str, str]:
    course_id = str(body.get("canvas_course_id") or "").strip()
    user_id = str(body.get("canvas_user_id") or "").strip()
    if not course_id or not user_id:
        raise HTTPException(
            status_code=422,
            detail="canvas_course_id and canvas_user_id are required",
        )
    return course_id, user_id


@router.post("/canvas/baseline/{student_id}/list-canvas-submissions")
async def list_canvas_submissions(
    student_id: str, req: dict | None = None, request: Request = None
):
    """List usable Canvas submissions and mark already-imported texts."""
    from ..canvas import live_import as canvas_live

    _require_staff(request)
    body = req or {}
    canvas_url, access_token = canvas_live.resolve_canvas_config(
        body.get("canvas_url"), body.get("access_token")
    )
    course_id, user_id = _canvas_required_ids(body)
    existing_hashes = _existing_text_hashes(student_id)
    previews = []
    async with canvas_live.make_client() as client:
        submissions = await canvas_live.fetch_submissions(
            client, canvas_url, access_token, course_id, user_id
        )
        for submission in submissions:
            text = await canvas_live.get_submission_text(submission, access_token, client)
            if not text or len(text.split()) < canvas_live.MIN_WORDS:
                continue
            digest = hashlib.sha256(text.encode()).hexdigest()
            previews.append(
                {
                    "canvas_submission_id": str(submission.get("id", "")),
                    "assignment_name": canvas_live.assignment_name_of(submission),
                    "submitted_at": submission.get("submitted_at"),
                    "word_count": len(text.split()),
                    "preview": text[:200].strip() + ("..." if len(text) > 200 else ""),
                    "already_imported": digest in existing_hashes,
                }
            )
    return {"submissions": previews, "total": len(previews)}


@router.post("/canvas/baseline/{student_id}/import-baseline")
async def import_canvas_baseline(student_id: str, req: dict | None = None, request: Request = None):
    """Import selected Canvas submissions with deduplication and drift holds."""
    from ..canvas import live_import as canvas_live

    _require_staff(request)
    body = req or {}
    canvas_url, access_token = canvas_live.resolve_canvas_config(
        body.get("canvas_url"), body.get("access_token")
    )
    course_id, user_id = _canvas_required_ids(body)
    submission_ids = [str(value) for value in body.get("submission_ids", []) if str(value)]
    if not submission_ids:
        raise HTTPException(status_code=422, detail="submission_ids is required")
    provenance, downgraded = _authorize_provenance(request, student_id, "canvas")
    state = _repo().get_or_create(student_id)
    existing_hashes = _existing_text_hashes(student_id)
    imported = skipped = 0
    errors = []
    drift_holds = []
    async with canvas_live.make_client() as client:
        fetched = await canvas_live.fetch_submissions(
            client,
            canvas_url,
            access_token,
            course_id,
            user_id,
            submission_ids=submission_ids,
        )
        by_id = {str(row.get("id", "")): row for row in fetched}
        for submission_id in submission_ids:
            submission = by_id.get(submission_id)
            if submission is None:
                errors.append(f"Submission {submission_id}: not found in Canvas response.")
                skipped += 1
                continue
            try:
                text = await canvas_live.get_submission_text(submission, access_token, client)
                if not text or len(text.split()) < canvas_live.MIN_WORDS:
                    skipped += 1
                    continue
                digest = hashlib.sha256(text.encode()).hexdigest()
                if digest in existing_hashes:
                    skipped += 1
                    continue
                sample = BaselineSample(
                    text=text,
                    vector=feature_vector(text),
                    provenance=provenance,
                    auth_weight=AUTH_WEIGHTS[provenance],
                    assignment=canvas_live.assignment_name_of(
                        submission, fallback=f"Canvas Import: {submission_id}"
                    ),
                    submitted_at=submission.get("submitted_at") or "",
                    word_count=len(text.split()),
                )
                sample.text_hash = digest  # type: ignore[attr-defined]
                if AUTH_WEIGHTS[provenance] > 0:
                    try:
                        drift = state.check_drift(sample)
                        if drift.recommendation != "accept":
                            drift_holds.append(
                                {"canvas_submission_id": submission_id, "drift": drift.to_dict()}
                            )
                            continue
                    except Exception as exc:
                        logging.getLogger(__name__).warning(
                            "drift check failed for canvas submission %s: %s",
                            submission_id,
                            exc,
                        )
                state.add_sample(sample)
                existing_hashes.add(digest)
                imported += 1
            except Exception as exc:
                errors.append(f"Submission {submission_id}: {str(exc)[:100]}")
    if imported or drift_holds:
        _persist_or_503(state)
    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "drift_holds": drift_holds,
        "provenance": provenance,
        "provenance_downgraded": downgraded,
    }


@router.post("/canvas/baseline/{student_id}/fetch-submission-text")
async def fetch_canvas_submission_text(
    student_id: str, req: dict | None = None, request: Request = None
):
    """Fetch one Canvas submission for analysis without storing it."""
    from ..canvas import live_import as canvas_live

    _require_staff(request)
    body = req or {}
    canvas_url, access_token = canvas_live.resolve_canvas_config(
        body.get("canvas_url"), body.get("access_token")
    )
    course_id, user_id = _canvas_required_ids(body)
    submission_id = str(body.get("canvas_submission_id") or "").strip()
    if not submission_id:
        raise HTTPException(status_code=422, detail="canvas_submission_id is required")
    async with canvas_live.make_client() as client:
        fetched = await canvas_live.fetch_submissions(
            client,
            canvas_url,
            access_token,
            course_id,
            user_id,
            submission_ids=[submission_id],
        )
        submission = next((row for row in fetched if str(row.get("id", "")) == submission_id), None)
        if submission is None:
            raise HTTPException(
                status_code=404,
                detail=f"Submission {submission_id} not found in Canvas.",
            )
        text = await canvas_live.get_submission_text(submission, access_token, client)
    if not text or len(text.split()) < canvas_live.MIN_WORDS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Submission {submission_id} has no usable text "
                f"(minimum {canvas_live.MIN_WORDS} words required)."
            ),
        )
    return {
        "text": text,
        "word_count": len(text.split()),
        "assignment_name": canvas_live.assignment_name_of(submission),
        "submitted_at": submission.get("submitted_at"),
    }
