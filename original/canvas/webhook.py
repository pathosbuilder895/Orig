"""
canvas/webhook.py — Canvas submission event receiver.

Handles two integration paths:

  1. Canvas Plagiarism Framework (legacy)
     Canvas calls this endpoint when a student submits to an assignment that
     has Original configured via the plagiarism platform.
     Endpoint: POST /canvas/submission

  2. Document Processor (emerging default)
     Canvas calls this endpoint via the Document Processor event stream.
     Endpoint: POST /canvas/document-processor

Both paths:
  a. Verify the request signature (HMAC-SHA256 on the payload)
  b. Fetch the submission text from Canvas via the Submissions API
  c. Trigger Original's scoring pipeline (background task)
  d. Return 200 immediately (Canvas expects fast acknowledgment)
  e. Post the report back to Canvas when scoring completes (see reporter.py)

Canvas Plagiarism Framework webhook reference:
  https://canvas.instructure.com/doc/api/file.plagiarism_platform.html
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Header, Request, status
from sqlalchemy.orm import Session

from original.core.config import get_settings
from original.core.logging import get_logger
from original.db.session import SessionLocal
from original.db.models.canvas import LTIRegistration, CanvasSubmission, CanvasSubmissionStatus
from original.canvas.reporter import post_reports_to_canvas, post_speedgrader_comment

log = get_logger(__name__)
router = APIRouter(prefix="/canvas", tags=["Canvas Webhooks"])


# ── Plagiarism Framework webhook ───────────────────────────────────────────────

@router.post(
    "/submission",
    summary="Canvas Plagiarism Framework submission event",
    status_code=status.HTTP_200_OK,
)
async def plagiarism_framework_submission(
    request: Request,
    background_tasks: BackgroundTasks,
    x_canvas_signature: Optional[str] = Header(None, alias="X-Canvas-Signature"),
):
    """
    Receive a Canvas Plagiarism Framework submission event.

    Canvas delivers a JSON body containing:
      - submission_id, assignment_id, course_id, user_id
      - submitted_at, submission_type, body / url / attachments
      - The access token needed to fetch full submission content

    We verify the HMAC signature, acknowledge immediately (200), then
    fetch the text and score asynchronously.
    """
    raw_body = await request.body()

    # Verify HMAC signature
    settings = get_settings()
    if not _verify_canvas_signature(raw_body, x_canvas_signature, settings.CANVAS_WEBHOOK_SECRET):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Canvas webhook signature",
        )

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    canvas_submission_id = str(payload.get("id", ""))
    canvas_assignment_id = str(payload.get("assignment_id", ""))
    canvas_course_id = str(payload.get("course_id", ""))
    canvas_user_id = str(payload.get("user_id", ""))
    submission_type = payload.get("submission_type", "")
    access_token = payload.get("user_data", {}).get("access_token") or payload.get("access_token")
    canvas_url = payload.get("canvas_url", settings.CANVAS_BASE_URL)

    log.info(
        "Canvas plagiarism submission received",
        extra={
            "canvas_submission_id": canvas_submission_id,
            "assignment_id": canvas_assignment_id,
        },
    )

    # Record the inbound event
    db = SessionLocal()
    try:
        record = _upsert_canvas_submission(
            db=db,
            canvas_submission_id=canvas_submission_id,
            canvas_assignment_id=canvas_assignment_id,
            canvas_course_id=canvas_course_id,
            canvas_user_id=canvas_user_id,
            submission_type=submission_type,
            canvas_url=canvas_url,
            access_token=access_token,
        )
        record_id = record.id
    finally:
        db.close()

    # Acknowledge immediately — Canvas will retry if we take too long
    background_tasks.add_task(
        _process_canvas_submission,
        record_id=record_id,
        payload=payload,
    )

    return {"status": "accepted", "canvas_submission_id": canvas_submission_id}


# ── Document Processor webhook ────────────────────────────────────────────────

@router.post(
    "/document-processor",
    summary="Canvas Document Processor submission event",
    status_code=status.HTTP_200_OK,
)
async def document_processor_submission(
    request: Request,
    background_tasks: BackgroundTasks,
    x_canvas_signature: Optional[str] = Header(None, alias="X-Canvas-Signature"),
):
    """
    Receive a Canvas Document Processor submission event.

    Document Processor uses a similar payload to the Plagiarism Framework
    but may include different fields.  We normalise and route to the same
    async processing pipeline.
    """
    raw_body = await request.body()

    settings = get_settings()
    if not _verify_canvas_signature(raw_body, x_canvas_signature, settings.CANVAS_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid Canvas webhook signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Document Processor may nest payload under 'data'
    data = payload.get("data", payload)
    canvas_submission_id = str(data.get("submission_id") or data.get("id", ""))
    canvas_assignment_id = str(data.get("assignment_id", ""))
    canvas_course_id = str(data.get("course_id", ""))
    canvas_user_id = str(data.get("user_id", ""))
    submission_type = data.get("submission_type", "online_text_entry")
    access_token = data.get("access_token") or settings.CANVAS_API_TOKEN
    canvas_url = data.get("canvas_url", settings.CANVAS_BASE_URL)

    log.info(
        "Canvas document processor event received",
        extra={"canvas_submission_id": canvas_submission_id},
    )

    db = SessionLocal()
    try:
        record = _upsert_canvas_submission(
            db=db,
            canvas_submission_id=canvas_submission_id,
            canvas_assignment_id=canvas_assignment_id,
            canvas_course_id=canvas_course_id,
            canvas_user_id=canvas_user_id,
            submission_type=submission_type,
            canvas_url=canvas_url,
            access_token=access_token,
        )
        record_id = record.id
    finally:
        db.close()

    background_tasks.add_task(
        _process_canvas_submission,
        record_id=record_id,
        payload=data,
    )
    return {"status": "accepted", "canvas_submission_id": canvas_submission_id}


# ── Submission status endpoint ────────────────────────────────────────────────

@router.get(
    "/submission/{canvas_submission_id}/status",
    summary="Check Canvas submission processing status",
)
def submission_status(canvas_submission_id: str):
    """Return the current processing status for a Canvas submission."""
    db = SessionLocal()
    try:
        record = db.query(CanvasSubmission).filter(
            CanvasSubmission.canvas_submission_id == canvas_submission_id
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail="Submission not found")
        return {
            "canvas_submission_id": record.canvas_submission_id,
            "status": record.status,
            "report_posted_at": record.report_posted_at,
            "error": record.error_message,
        }
    finally:
        db.close()


# ── Background processing ──────────────────────────────────────────────────────

async def _process_canvas_submission(record_id: str, payload: Dict[str, Any]) -> None:
    """
    Fetch submission text from Canvas, score it, and post report back.

    This runs as a FastAPI background task — errors are logged but do not
    bubble up to the HTTP response layer.
    """
    db = SessionLocal()
    try:
        record = db.query(CanvasSubmission).filter(
            CanvasSubmission.id == record_id
        ).first()
        if not record:
            log.error("Canvas submission record not found", extra={"record_id": record_id})
            return

        # Mark as processing
        record.status = CanvasSubmissionStatus.PROCESSING
        db.commit()

        # Fetch submission text from Canvas
        text = await _fetch_submission_text(record, payload)
        if not text or len(text.split()) < 20:
            record.status = CanvasSubmissionStatus.SKIPPED
            record.error_message = "Submission too short or empty"
            db.commit()
            log.info("Skipped short submission", extra={"record_id": record_id})
            return

        # Run Original scoring pipeline (with comparison features)
        from original.features.pipeline import compute_full_features
        from original.constants import ALL_FEATURE_CODES
        import numpy as np

        # Look up or create the student + baseline in Original's DB
        original_submission_id, deviation_score, authorship_prob, recommended_action, feature_dict = (
            await _run_original_scoring(
                db=db,
                record=record,
                text=text,
            )
        )

        # Post report back to Canvas (originality reports + SpeedGrader comment)
        await post_reports_to_canvas(
            record=record,
            deviation_score=deviation_score,
            authorship_probability=authorship_prob,
            recommended_action=recommended_action,
            feature_dict=feature_dict,
        )
        await post_speedgrader_comment(
            record=record,
            deviation_score=deviation_score,
            authorship_probability=authorship_prob,
            recommended_action=recommended_action,
        )

        record.status = CanvasSubmissionStatus.REPORTED
        record.original_submission_id = original_submission_id
        db.commit()
        log.info(
            "Canvas submission processed and reported",
            extra={"record_id": record_id, "deviation": deviation_score},
        )

    except Exception as exc:
        log.error(
            "Canvas submission processing failed",
            extra={"record_id": record_id, "error": str(exc)},
        )
        try:
            if record:
                record.status = CanvasSubmissionStatus.FAILED
                record.error_message = str(exc)[:500]
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


async def _fetch_submission_text(record: CanvasSubmission, payload: Dict) -> Optional[str]:
    """
    Fetch the submission text from Canvas.

    For online_text_entry submissions, the body may already be in the payload.
    For file uploads, we fetch from the Canvas Submissions API.
    """
    # Try payload body first (text entries)
    if payload.get("body"):
        return payload["body"]

    if not record.access_token or not record.canvas_url:
        return None

    # Fetch from Canvas Submissions API
    url = (
        f"{record.canvas_url}/api/v1/courses/{record.canvas_course_id}"
        f"/assignments/{record.canvas_assignment_id}"
        f"/submissions/{record.canvas_user_id}"
    )
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {record.access_token}"},
                params={"include[]": ["submission_comments", "submission_history"]},
            )
            resp.raise_for_status()
            data = resp.json()
            # Text entry
            if data.get("body"):
                return data["body"]
            # File upload: download first attachment
            attachments = data.get("attachments", [])
            if attachments:
                file_url = attachments[0].get("url")
                if file_url:
                    file_resp = await client.get(file_url)
                    file_resp.raise_for_status()
                    return file_resp.text
    except Exception as exc:
        log.error("Failed to fetch Canvas submission", extra={"url": url, "error": str(exc)})
    return None


async def _run_original_scoring(
    db: Session,
    record: CanvasSubmission,
    text: str,
) -> tuple:
    """
    Run Original scoring for the Canvas submission.

    Returns (submission_id, deviation_score, authorship_probability, action, feature_dict).
    """
    import hashlib
    from datetime import datetime
    import numpy as np
    from original.db.models import Student, Submission, SubmissionStatus, ScoringResult
    from original.db.models import BaselineSample
    from original.constants import ALL_FEATURE_CODES
    from original.features.pipeline import compute_full_features
    from original.quantum.state import StudentState
    from original.quantum.state import BaselineSample as QBaselineSample
    from original.quantum.scoring import score
    from original.core.config import get_settings

    settings = get_settings()
    empty_features = {}  # fallback for early returns

    # Find or create student by Canvas user ID
    student = db.query(Student).filter(
        Student.external_id == record.canvas_user_id,
    ).first()

    if not student:
        log.warning(
            "Canvas user not found in Original system",
            extra={"canvas_user_id": record.canvas_user_id},
        )
        return (None, 0.5, 0.5, "monitor", empty_features)

    # Get baseline samples
    samples = (
        db.query(BaselineSample)
        .filter(
            BaselineSample.student_id == student.id,
            BaselineSample.is_active == True,
        )
        .order_by(BaselineSample.created_at)
        .all()
    )

    if len(samples) < settings.MIN_BASELINE_SAMPLES:
        return (None, 0.5, 0.5, "monitor", empty_features)

    # Collect baseline texts for comparison features
    baseline_texts = [s.raw_text for s in samples if s.raw_text]

    # Extract features with real comparison features
    feature_dict = compute_full_features(text, baseline_texts)
    feature_vector = np.array(
        [feature_dict[c] for c in ALL_FEATURE_CODES], dtype=np.float64
    )

    # Create submission record
    text_hash = hashlib.sha256(record.canvas_submission_id.encode()).hexdigest()
    word_count = len(text.split())
    submission = Submission(
        student_id=student.id,
        assignment=f"Canvas:{record.canvas_assignment_id}",
        text_hash=text_hash,
        word_count=word_count,
        char_count=len(text),
        submitted_at=datetime.utcnow(),
        status=SubmissionStatus.SCORING,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    # Reconstruct student state and score
    q_samples = [
        QBaselineSample(
            text=s.raw_text or "",
            vector=np.array(
                [s.feature_vector.get(c, 0.0) for c in ALL_FEATURE_CODES], dtype=np.float64
            ),
            provenance=s.provenance,
            auth_weight=s.auth_weight,
            assignment=s.assignment,
            submitted_at=s.submitted_at.isoformat(),
        )
        for s in samples
    ]
    state = StudentState(student_id=student.id, samples=q_samples)
    result = score(state, feature_vector, feature_dict, submission.id)

    scoring_result = ScoringResult(
        submission_id=submission.id,
        model_version=settings.MODEL_VERSION,
        deviation_score=result.authorship.deviation_score,
        authorship_probability=result.authorship.authorship_probability,
        recommended_action=result.recommendation.action,
        baseline_confidence={
            "purity": result.baseline_confidence.purity,
            "sample_count": result.baseline_confidence.sample_count,
        },
        full_result={"interference": {}},
        feature_vector=feature_dict,
        scored_at=datetime.utcnow(),
    )
    submission.status = SubmissionStatus.SCORED
    db.add(scoring_result)
    db.commit()

    return (
        submission.id,
        result.authorship.deviation_score,
        result.authorship.authorship_probability,
        result.recommendation.action,
        feature_dict,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _verify_canvas_signature(
    body: bytes,
    signature_header: Optional[str],
    secret: str,
) -> bool:
    """Verify HMAC-SHA256 Canvas webhook signature."""
    if not secret:
        # No secret configured — behavior depends on environment
        settings = get_settings()
        if settings.ENVIRONMENT == "production":
            # Reject in production if secret is missing
            return False
        else:
            # Allow in development/testing with warning
            log.warning(
                "Canvas webhook signature verification skipped — CANVAS_WEBHOOK_SECRET not set. "
                "This is only acceptable in development."
            )
            return True
    if not signature_header:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _upsert_canvas_submission(
    db: Session,
    canvas_submission_id: str,
    canvas_assignment_id: str,
    canvas_course_id: str,
    canvas_user_id: str,
    submission_type: str,
    canvas_url: str,
    access_token: Optional[str],
) -> CanvasSubmission:
    record = db.query(CanvasSubmission).filter(
        CanvasSubmission.canvas_submission_id == canvas_submission_id
    ).first()
    if record:
        record.status = CanvasSubmissionStatus.PENDING
        record.error_message = None
    else:
        record = CanvasSubmission(
            canvas_submission_id=canvas_submission_id,
            canvas_assignment_id=canvas_assignment_id,
            canvas_course_id=canvas_course_id,
            canvas_user_id=canvas_user_id,
            submission_type=submission_type,
            canvas_url=canvas_url,
            access_token=access_token,
            status=CanvasSubmissionStatus.PENDING,
        )
        db.add(record)
    db.commit()
    db.refresh(record)
    return record
