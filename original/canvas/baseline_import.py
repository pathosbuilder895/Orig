"""
canvas/baseline_import.py — Import baseline samples from Canvas Submissions API.

Provides API endpoints that let an instructor:
  1. List a student's past Canvas submissions for a course
  2. Select which ones to import as baseline samples
  3. Import selected submissions as verified baseline samples

Handles both submission types:
  - online_text_entry: body text is used directly
  - online_upload: attachments are downloaded and text extracted via pypdf / python-docx

Canvas Submissions API reference:
  https://canvas.instructure.com/doc/api/submissions.html
"""

from __future__ import annotations

import hashlib
import io
from datetime import datetime
from typing import Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from original.api.deps import get_current_instructor, get_db, require_same_institution
from original.constants import ALL_FEATURE_CODES, AUTH_WEIGHTS
from original.core.config import get_settings
from original.core.logging import get_logger
from original.db.models import BaselineSample, Provenance, Student
from original.features.pipeline import extract_features

log = get_logger(__name__)
router = APIRouter(prefix="/canvas/baseline", tags=["Canvas Baseline Import"])


# ── Text extraction helpers ───────────────────────────────────────────────────

async def _extract_text_from_attachment(
    url: str,
    filename: str,
    access_token: str,
    client: httpx.AsyncClient,
) -> Optional[str]:
    """Download a Canvas file attachment and extract plain text."""
    try:
        resp = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
        resp.raise_for_status()
        raw = resp.content
    except Exception as exc:
        log.warning("Failed to download Canvas attachment", extra={"url": url, "error": str(exc)})
        return None

    name_lower = filename.lower()
    try:
        if name_lower.endswith(".txt"):
            return raw.decode("utf-8", errors="replace")
        elif name_lower.endswith(".pdf"):
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        elif name_lower.endswith(".docx"):
            from docx import Document
            doc = Document(io.BytesIO(raw))
            return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as exc:
        log.warning("Text extraction failed", extra={"filename": filename, "error": str(exc)})
    return None


async def _get_submission_text(
    sub: dict,
    canvas_url: str,
    access_token: str,
    client: httpx.AsyncClient,
) -> Optional[str]:
    """Extract usable text from a Canvas submission object."""
    sub_type = sub.get("submission_type", "")

    # Inline text
    if sub_type == "online_text_entry":
        body = sub.get("body") or ""
        return body if body.strip() else None

    # File upload — try each attachment in order
    if sub_type == "online_upload":
        attachments = sub.get("attachments", [])
        for att in attachments:
            url  = att.get("url") or att.get("preview_url") or ""
            name = att.get("display_name") or att.get("filename") or ""
            if not url:
                continue
            # Canvas attachment URLs are pre-signed; pass the token anyway
            text = await _extract_text_from_attachment(url, name, access_token, client)
            if text and len(text.split()) >= 50:
                return text

    return None


# ── Schemas ───────────────────────────────────────────────────────────────────

class CanvasSubmissionPreview(BaseModel):
    """Preview of a Canvas submission available for baseline import."""
    canvas_submission_id: str
    assignment_name: str
    submitted_at: Optional[str] = None
    word_count: int
    preview: str = Field(..., description="First 200 characters of the submission text.")
    already_imported: bool = False


class ListCanvasSubmissionsRequest(BaseModel):
    """Request to list a student's Canvas submissions."""
    canvas_course_id: str
    canvas_user_id: str
    canvas_url: Optional[str] = None
    access_token: Optional[str] = None


class ListCanvasSubmissionsResponse(BaseModel):
    """List of Canvas submissions available for import."""
    submissions: List[CanvasSubmissionPreview]
    total: int


class ImportBaselineRequest(BaseModel):
    """Request to import selected Canvas submissions as baseline samples."""
    canvas_course_id: str
    canvas_user_id: str
    canvas_url: Optional[str] = None
    access_token: Optional[str] = None
    submission_ids: List[str] = Field(
        ..., description="Canvas submission IDs to import as baseline.",
    )


class ImportBaselineResponse(BaseModel):
    """Result of baseline import."""
    imported: int
    skipped: int
    errors: List[str]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/{student_id}/list-canvas-submissions",
    response_model=ListCanvasSubmissionsResponse,
)
async def list_canvas_submissions(
    body: ListCanvasSubmissionsRequest,
    student: Student = Depends(require_same_institution),
    user=Depends(get_current_instructor),
    db: Session = Depends(get_db),
):
    """
    List a student's past Canvas submissions available for baseline import.

    Fetches from the Canvas Submissions API and shows which ones haven't
    already been imported.
    """
    settings = get_settings()
    canvas_url = (body.canvas_url or settings.CANVAS_BASE_URL).rstrip("/")
    access_token = body.access_token or settings.CANVAS_API_TOKEN

    if not access_token or not canvas_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Canvas URL and access token are required.",
        )

    # Fetch all submissions (paginated) from Canvas
    list_url = (
        f"{canvas_url}/api/v1/courses/{body.canvas_course_id}"
        f"/students/submissions"
    )
    params = {
        "student_ids[]": body.canvas_user_id,
        "include[]": ["assignment", "attachments"],
        "submission_types[]": ["online_text_entry", "online_upload"],
        "per_page": 50,
    }

    canvas_subs: List[dict] = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            next_url: Optional[str] = list_url
            while next_url:
                resp = await client.get(
                    next_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params if next_url == list_url else None,
                )
                resp.raise_for_status()
                canvas_subs.extend(resp.json())
                # Follow Canvas Link header pagination
                link_header = resp.headers.get("Link", "")
                next_url = None
                for part in link_header.split(","):
                    if 'rel="next"' in part:
                        next_url = part.split(";")[0].strip().strip("<>")
                        break
    except Exception as exc:
        log.error("Failed to fetch Canvas submissions", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch submissions from Canvas: {exc}",
        )

    # Check which ones are already imported (by text hash)
    existing_hashes = set(
        h for (h,) in db.query(BaselineSample.text_hash)
        .filter(BaselineSample.student_id == student.id)
        .all()
    )

    previews = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for sub in canvas_subs:
            body_text = await _get_submission_text(sub, canvas_url, access_token, client)
            if not body_text or len(body_text.split()) < 50:
                continue

            text_hash = hashlib.sha256(body_text.encode()).hexdigest()
            word_count = len(body_text.split())
            assignment = sub.get("assignment", {})
            assignment_name = (
                assignment.get("name", "Unknown Assignment") if assignment else "Unknown"
            )
            previews.append(CanvasSubmissionPreview(
                canvas_submission_id=str(sub.get("id", "")),
                assignment_name=assignment_name,
                submitted_at=sub.get("submitted_at"),
                word_count=word_count,
                preview=body_text[:200].strip() + ("..." if len(body_text) > 200 else ""),
                already_imported=text_hash in existing_hashes,
            ))

    return ListCanvasSubmissionsResponse(
        submissions=previews,
        total=len(previews),
    )


@router.post(
    "/{student_id}/import-baseline",
    response_model=ImportBaselineResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_baseline_from_canvas(
    body: ImportBaselineRequest,
    student: Student = Depends(require_same_institution),
    user=Depends(get_current_instructor),
    db: Session = Depends(get_db),
):
    """
    Import selected Canvas submissions as baseline samples for this student.

    Fetches the full text for each selected submission, extracts features,
    and creates baseline samples with 'verified' provenance.
    """
    settings = get_settings()
    canvas_url = (body.canvas_url or settings.CANVAS_BASE_URL).rstrip("/")
    access_token = body.access_token or settings.CANVAS_API_TOKEN

    if not access_token or not canvas_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Canvas URL and access token are required.",
        )

    imported = 0
    skipped = 0
    errors = []

    # Fetch the selected submissions in one paginated call using submission_ids[] filter
    list_url = (
        f"{canvas_url}/api/v1/courses/{body.canvas_course_id}"
        f"/students/submissions"
    )
    fetch_params = {
        "student_ids[]": body.canvas_user_id,
        "submission_ids[]": body.submission_ids,
        "include[]": ["assignment", "attachments"],
        "per_page": 50,
    }
    fetched_subs: List[dict] = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            next_url: Optional[str] = list_url
            while next_url:
                resp = await client.get(
                    next_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=fetch_params if next_url == list_url else None,
                )
                resp.raise_for_status()
                fetched_subs.extend(resp.json())
                link_header = resp.headers.get("Link", "")
                next_url = None
                for part in link_header.split(","):
                    if 'rel="next"' in part:
                        next_url = part.split(";")[0].strip().strip("<>")
                        break
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch submissions from Canvas: {exc}",
        )

    # Build a lookup by submission ID string for quick access
    sub_map = {str(s.get("id", "")): s for s in fetched_subs}

    async with httpx.AsyncClient(timeout=30.0) as client:
        for sub_id in body.submission_ids:
            sub_data = sub_map.get(str(sub_id))
            if not sub_data:
                errors.append(f"Submission {sub_id}: not found in Canvas response.")
                skipped += 1
                continue
            try:
                body_text = await _get_submission_text(sub_data, canvas_url, access_token, client)
                if not body_text or len(body_text.split()) < 50:
                    skipped += 1
                    continue

                # Check for duplicate
                text_hash = hashlib.sha256(body_text.encode()).hexdigest()
                existing = db.query(BaselineSample).filter(
                    BaselineSample.text_hash == text_hash
                ).first()
                if existing:
                    skipped += 1
                    continue

                # Extract features
                feature_dict = extract_features(body_text)

                # Build assignment name
                assignment_obj = sub_data.get("assignment") or {}
                assignment_name = assignment_obj.get("name") or f"Canvas Import: {sub_id}"

                # Create baseline sample
                provenance = Provenance.VERIFIED
                sample = BaselineSample(
                    student_id=student.id,
                    assignment=assignment_name,
                    text_hash=text_hash,
                    raw_text=body_text,
                    feature_vector=feature_dict,
                    provenance=provenance,
                    auth_weight=AUTH_WEIGHTS.get(provenance, 0.7),
                    word_count=len(body_text.split()),
                    submitted_at=datetime.fromisoformat(
                        (sub_data.get("submitted_at") or datetime.utcnow().isoformat())
                        .replace("Z", "+00:00")
                    ),
                    added_by_id=user.id,
                    model_version=settings.MODEL_VERSION,
                )
                db.add(sample)
                db.commit()
                imported += 1

            except Exception as exc:
                errors.append(f"Submission {sub_id}: {str(exc)[:100]}")
                log.error(
                    "Canvas baseline import failed for submission",
                    extra={"submission_id": sub_id, "error": str(exc)},
                )

    log.info(
        "Canvas baseline import complete",
        extra={
            "student_id": student.id,
            "imported": imported,
            "skipped": skipped,
            "errors": len(errors),
        },
    )

    return ImportBaselineResponse(
        imported=imported,
        skipped=skipped,
        errors=errors,
    )
