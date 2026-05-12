"""
api/v1/submissions.py — Submission and scoring endpoints.

Handles baseline sample submission and authorship scoring.
"""

import hashlib
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from original.api.deps import (
    get_current_instructor,
    get_db,
    require_same_institution,
)
from original.core.config import get_settings
from original.core.exceptions import InsufficientBaselineError
from original.core.limiter import limiter
from original.core.logging import get_logger
from original.db.models import (
    ActionType,
    BaselineSample,
    InstructorDecision,
    Provenance,
    Submission,
    SubmissionStatus,
    ScoringResult,
    Student,
)
from original.features.pipeline import extract_features, compute_full_features
from original.quantum.scoring import score
from original.quantum.state import BaselineSample as QBaselineSample, StudentState
from original.tension_arc import analyze_tension_arc, update_student_baseline_kappa
from original.schemas_v1.submission import (
    BaselineAddRequest,
    BaselineAddResponse,
    DecisionRequest,
    ScoreRequest,
    ScoreResponse,
    SubmissionListResponse,
)
from original.constants import AUTH_WEIGHTS, ALL_FEATURE_CODES

log = get_logger(__name__)

router = APIRouter(prefix="/submissions", tags=["Submissions"])


def _reconstruct_student_state(
    student_id: str, db: Session
) -> StudentState:
    """
    Reconstruct a student's quantum state from baseline samples in the DB.

    Args:
        student_id: Student ID
        db: Database session

    Returns:
        StudentState object
    """
    import numpy as np

    baseline_samples = (
        db.query(BaselineSample)
        .filter(
            BaselineSample.student_id == student_id,
            BaselineSample.is_active == True,
        )
        .order_by(BaselineSample.created_at)
        .all()
    )

    q_samples = []
    raw_texts = []
    skipped = 0
    for sample in baseline_samples:
        try:
            # Convert stored JSON feature vector back to numpy array
            feature_list = [sample.feature_vector.get(code, 0.0) for code in ALL_FEATURE_CODES]
            vector = np.array(feature_list, dtype=np.float64)

            # Guard: skip corrupt vectors (NaN, Inf, or wrong dimension)
            if vector.shape != (len(ALL_FEATURE_CODES),) or not np.isfinite(vector).all():
                log.warning(
                    "skipping_corrupt_baseline",
                    extra={"sample_id": sample.id, "student_id": student_id},
                )
                skipped += 1
                continue

            q_sample = QBaselineSample(
                text=sample.raw_text or "",
                vector=vector,
                provenance=sample.provenance,
                auth_weight=sample.auth_weight,
                assignment=sample.assignment,
                submitted_at=sample.submitted_at.isoformat(),
            )
            q_samples.append(q_sample)

            # Collect raw texts for comparison feature computation
            if sample.raw_text:
                raw_texts.append(sample.raw_text)
        except Exception as e:
            log.warning(
                "skipping_bad_baseline_sample",
                extra={"sample_id": sample.id, "error": str(e)},
            )
            skipped += 1

    if skipped:
        log.info(
            "baseline_reconstruction_summary",
            extra={"student_id": student_id, "used": len(q_samples), "skipped": skipped},
        )

    state = StudentState(student_id=student_id, samples=q_samples)
    return state, raw_texts


@router.post(
    "/{student_id}/baseline",
    response_model=BaselineAddResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add baseline sample",
    responses={
        409: {"description": "Duplicate text — this sample has already been submitted"},
        422: {"description": "Text too short/long or invalid provenance"},
    },
)
def add_baseline_sample(
    student: Student = Depends(require_same_institution),
    body: BaselineAddRequest = None,
    user=Depends(get_current_instructor),
    db: Session = Depends(get_db),
) -> BaselineAddResponse:
    """
    Add a baseline sample for a student.

    Args:
        student: Student (via dependency)
        request: Baseline sample request
        user: Current user (instructor)
        db: Database session

    Returns:
        BaselineAddResponse with sample details

    Raises:
        HTTPException: If text already exists (duplicate)
    """
    settings = get_settings()

    # Hash the text to detect duplicates
    text_hash = hashlib.sha256(body.text.encode()).hexdigest()

    # Check for duplicate
    existing = db.query(BaselineSample).filter(
        BaselineSample.text_hash == text_hash
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This text has already been submitted as a baseline",
        )

    # Extract features
    feature_dict = extract_features(body.text)

    # Calculate auth weight based on provenance
    provenance = Provenance(body.provenance)
    auth_weight = AUTH_WEIGHTS.get(provenance, 0.0)

    # Count words
    word_count = len(body.text.split())

    # Create baseline sample
    submitted_at = body.submitted_at or datetime.utcnow()
    sample = BaselineSample(
        student_id=student.id,
        course_id=None,  # Could be set if provided
        assignment=body.assignment or "unknown",
        text_hash=text_hash,
        raw_text=body.text,
        feature_vector=feature_dict,
        provenance=provenance,
        auth_weight=auth_weight,
        word_count=word_count,
        submitted_at=submitted_at,
        added_by_id=user.id,
        model_version=settings.MODEL_VERSION,
    )

    db.add(sample)
    db.commit()
    db.refresh(sample)

    # ── Update student's tension arc κ baseline for authenticated samples ──────
    # Only proctored/verified samples are trusted enough to build the κ baseline.
    if provenance.value in ("proctored", "verified"):
        try:
            arc = analyze_tension_arc(body.text)
            if arc.catastrophe_index > 0:   # skip insufficient-length samples
                kappa_log: list = []
                if student.baseline_kappa is not None:
                    # Reconstruct a single-element history from the running mean
                    # (exact history not stored; approximation sufficient for running mean)
                    kappa_log = [student.baseline_kappa]
                new_kappa = update_student_baseline_kappa(kappa_log, arc.catastrophe_index)
                student.baseline_kappa = new_kappa
                db.commit()
        except Exception as _exc:
            log.warning(
                "tension_arc_baseline_update_failed",
                extra={"student_id": student.id, "error": str(_exc)},
            )

    # Count new total baseline samples
    new_sample_count = (
        db.query(func.count(BaselineSample.id))
        .filter(
            BaselineSample.student_id == student.id,
            BaselineSample.is_active == True,
        )
        .scalar()
    )

    return BaselineAddResponse(
        sample_id=sample.id,
        student_id=student.id,
        feature_count=len(feature_dict),
        word_count=word_count,
        provenance=provenance.value,
        model_version=settings.MODEL_VERSION,
        new_sample_count=new_sample_count or 0,
    )


class BatchUploadResult(BaseModel):
    imported: int
    skipped_duplicates: int
    errors: List[str]


@router.post(
    "/{student_id}/baseline/upload-batch",
    response_model=BatchUploadResult,
    status_code=status.HTTP_200_OK,
)
def upload_baseline_batch(
    student: Student = Depends(require_same_institution),
    files: List[UploadFile] = File(...),
    provenance: str = Form("verified"),
    assignment: str = Form(""),
    user=Depends(get_current_instructor),
    db: Session = Depends(get_db),
) -> BatchUploadResult:
    """
    Upload multiple files (PDF, DOCX, TXT) as baseline samples in one request.

    Extracts text from each file, deduplicates by SHA-256 hash, runs feature
    extraction, and creates BaselineSample records.  Designed for bulk ingestion
    of past papers (e.g. migrating from Turnitin).

    Args:
        student:    Student (resolved via require_same_institution dependency)
        files:      One or more uploaded files (multipart form)
        provenance: "proctored" | "verified" (default "verified")
        assignment: Optional assignment label applied to all files in this batch
        user:       Current instructor
        db:         Database session

    Returns:
        BatchUploadResult with counts of imported, skipped, and error messages
    """
    from original.api.v1.upload_utils import extract_text_from_bytes, word_count as wc

    settings = get_settings()
    prov = Provenance(provenance)
    auth_weight = AUTH_WEIGHTS.get(prov, 0.0)

    imported = 0
    skipped_duplicates = 0
    errors: List[str] = []

    for upload in files:
        filename = upload.filename or "unknown"
        try:
            raw = upload.file.read()
            text = extract_text_from_bytes(raw, filename)
        except ValueError as exc:
            errors.append(f"{filename}: {exc}")
            continue
        except Exception as exc:
            errors.append(f"{filename}: read error — {exc}")
            continue

        if not text.strip():
            errors.append(f"{filename}: no text extracted (empty or image-only PDF?)")
            continue

        text_hash = hashlib.sha256(text.encode()).hexdigest()

        # Deduplicate against existing baseline samples for this student
        existing = db.query(BaselineSample).filter(
            BaselineSample.student_id == student.id,
            BaselineSample.text_hash == text_hash,
        ).first()
        if existing:
            skipped_duplicates += 1
            continue

        try:
            feature_dict = extract_features(text)
        except Exception as exc:
            errors.append(f"{filename}: feature extraction failed — {exc}")
            continue

        label = assignment.strip() or filename.rsplit(".", 1)[0]
        sample = BaselineSample(
            student_id=student.id,
            course_id=None,
            assignment=label,
            text_hash=text_hash,
            raw_text=text,
            feature_vector=feature_dict,
            provenance=prov,
            auth_weight=auth_weight,
            word_count=wc(text),
            submitted_at=datetime.utcnow(),
            added_by_id=user.id,
            model_version=settings.MODEL_VERSION,
        )
        db.add(sample)

        # Update tension arc κ baseline for authenticated samples
        if prov.value in ("proctored", "verified"):
            try:
                arc = analyze_tension_arc(text)
                if arc.catastrophe_index > 0:
                    kappa_log = [student.baseline_kappa] if student.baseline_kappa is not None else []
                    student.baseline_kappa = update_student_baseline_kappa(kappa_log, arc.catastrophe_index)
            except Exception:
                pass  # Non-fatal; logged at import level

        imported += 1

    if imported > 0:
        db.commit()

    log.info(
        "batch_baseline_upload",
        extra={
            "student_id": student.id,
            "imported": imported,
            "skipped": skipped_duplicates,
            "errors": len(errors),
        },
    )
    return BatchUploadResult(
        imported=imported,
        skipped_duplicates=skipped_duplicates,
        errors=errors,
    )


@router.post(
    "/{student_id}/score",
    response_model=ScoreResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Score submission",
    responses={
        422: {"description": "Insufficient baseline samples or text validation failure"},
        429: {"description": "Rate limit exceeded (10 requests/minute per IP)"},
    },
)
@limiter.limit("10/minute")
def score_submission(
    request: Request,
    student: Student = Depends(require_same_institution),
    body: ScoreRequest = None,
    background_tasks: BackgroundTasks = None,
    user=Depends(get_current_instructor),
    db: Session = Depends(get_db),
) -> ScoreResponse:
    """
    Score a submission against the student's baseline.

    Args:
        student: Student (via dependency)
        request: Scoring request with text
        background_tasks: For background job scheduling
        user: Current user (instructor)
        db: Database session

    Returns:
        ScoreResponse with scoring results

    Raises:
        InsufficientBaselineError: If student has < MIN_BASELINE_SAMPLES
    """
    settings = get_settings()

    # Hash text to check for duplicates
    text_hash = hashlib.sha256(body.text.encode()).hexdigest()

    # Current baseline count for this student — needed for cache validity check
    baseline_count = (
        db.query(func.count(BaselineSample.id))
        .filter(
            BaselineSample.student_id == student.id,
            BaselineSample.is_active == True,
        )
        .scalar()
    )

    # Check if already scored — cache is valid only when:
    #   1. The submission belongs to THIS student (prevent cross-student hash collisions)
    #   2. The baseline hasn't grown since scoring (stale cache = wrong scores)
    existing_submission = db.query(Submission).filter(
        Submission.student_id == student.id,
        Submission.text_hash == text_hash,
    ).first()

    if existing_submission and existing_submission.scoring_result:
        cached_baseline_count = (
            existing_submission.scoring_result.baseline_confidence or {}
        ).get("sample_count", 0)

        if cached_baseline_count == baseline_count:
            # Baseline unchanged — cached result is still valid
            result = existing_submission.scoring_result
            return ScoreResponse(
                submission_id=existing_submission.id,
                student_id=student.id,
                status=existing_submission.status,
                deviation_score=result.deviation_score,
                authorship_probability=result.authorship_probability,
                recommended_action=result.recommended_action,
                rationale="Cached result from previous scoring",
                baseline_confidence=result.baseline_confidence,
                interference=result.full_result.get("interference", {}),
                feature_vector=result.feature_vector,
                baseline_vector=result.full_result.get("baseline_vector", {}),
                model_version=result.model_version,
                scored_at=result.scored_at,
            )
        # Baseline has grown — fall through and re-score with updated baseline

    if baseline_count < settings.MIN_BASELINE_SAMPLES:
        raise InsufficientBaselineError(
            detail=f"Student needs {settings.MIN_BASELINE_SAMPLES} baseline samples. "
            f"Current: {baseline_count}"
        )

    # Count words
    word_count = len(body.text.split())
    char_count = len(body.text)

    # Create submission record
    submitted_at = datetime.utcnow()
    submission = Submission(
        student_id=student.id,
        course_id=body.course_id,
        assignment=body.assignment or "unknown",
        text_hash=text_hash,
        word_count=word_count,
        char_count=char_count,
        submitted_at=submitted_at,
        status=SubmissionStatus.PENDING,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    # Score synchronously (or via background task)
    try:
        import time as _time
        import numpy as np

        t0 = _time.perf_counter()

        # Reconstruct student state and collect baseline texts
        state, baseline_texts = _reconstruct_student_state(student.id, db)
        t_state = _time.perf_counter()

        # Extract features with real comparison features (KL-divergence)
        submission_features = compute_full_features(body.text, baseline_texts)
        submission_vector = np.array(
            [submission_features[code] for code in ALL_FEATURE_CODES],
            dtype=np.float64,
        )
        t_features = _time.perf_counter()

        # Run quantum scoring
        layer7_output = score(state, submission_vector, submission_features, submission.id)
        t_score = _time.perf_counter()

        # ── Tension Arc (orthogonal signal, non-fatal) ────────────────────────
        try:
            tension_result = analyze_tension_arc(
                text=body.text,
                baseline_kappa=student.baseline_kappa,   # None until 1+ authenticated baselines
            )
            layer7_output.tension_arc = tension_result
        except Exception as _exc:
            log.warning(
                "tension_arc_failed",
                extra={"error": str(_exc), "submission_id": str(submission.id)},
            )
            tension_result = None

        log.info(
            "scoring_timing",
            extra={
                "student_id": student.id,
                "submission_id": str(submission.id),
                "word_count": word_count,
                "baseline_count": len(baseline_texts),
                "state_build_ms": round((t_state - t0) * 1000, 2),
                "feature_extract_ms": round((t_features - t_state) * 1000, 2),
                "quantum_score_ms": round((t_score - t_features) * 1000, 2),
                "total_scoring_ms": round((t_score - t0) * 1000, 2),
            },
        )

        # Cap action if insufficient baseline for escalation
        recommended_action = layer7_output.recommendation.action
        if baseline_count < settings.MIN_BASELINE_FOR_ESCALATE:
            if recommended_action == "escalate":
                recommended_action = "schedule_conversation"

        # Create scoring result
        scoring_result = ScoringResult(
            submission_id=submission.id,
            model_version=settings.MODEL_VERSION,
            deviation_score=layer7_output.authorship.deviation_score,
            authorship_probability=layer7_output.authorship.authorship_probability,
            recommended_action=recommended_action,
            baseline_confidence={
                "purity": layer7_output.baseline_confidence.purity,
                "sample_count": layer7_output.baseline_confidence.sample_count,
                "authenticated_count": layer7_output.baseline_confidence.authenticated_count,
            },
            full_result={
                "interference": {
                    "constructive": [
                        {
                            "code": fc.code,
                            "contribution": fc.contribution,
                        }
                        for fc in layer7_output.interference.constructive_features[:5]
                    ],
                    "destructive": [
                        {
                            "code": fc.code,
                            "contribution": fc.contribution,
                        }
                        for fc in layer7_output.interference.destructive_features[:5]
                    ],
                },
                "baseline_vector": {
                    code: state.density_matrix[i, i]
                    for i, code in enumerate(ALL_FEATURE_CODES)
                },
            },
            feature_vector=submission_features,
            scored_at=datetime.utcnow(),
        )

        submission.status = SubmissionStatus.SCORED
        db.add(scoring_result)
        db.commit()

        return ScoreResponse(
            submission_id=submission.id,
            student_id=student.id,
            status=submission.status,
            deviation_score=scoring_result.deviation_score,
            authorship_probability=scoring_result.authorship_probability,
            recommended_action=recommended_action,
            rationale=layer7_output.recommendation.rationale,
            baseline_confidence=scoring_result.baseline_confidence,
            interference=scoring_result.full_result.get("interference", {}),
            feature_vector=submission_features,
            baseline_vector=scoring_result.full_result.get("baseline_vector", {}),
            model_version=settings.MODEL_VERSION,
            scored_at=scoring_result.scored_at,
            catastrophic_drift=layer7_output.catastrophic_drift,
            catastrophic_drift_rms_z=layer7_output.catastrophic_drift_rms_z,
            tension_arc=layer7_output.tension_arc,
        )

    except Exception as e:
        log.error("Scoring failed", extra={"submission_id": submission.id, "error": str(e)})
        submission.status = SubmissionStatus.FAILED
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Scoring failed",
        )


@router.get("/{student_id}/submissions", response_model=SubmissionListResponse)
def list_submissions(
    student: Student = Depends(require_same_institution),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> SubmissionListResponse:
    """
    List all submissions for a student.

    Args:
        student: Student (via dependency)
        skip: Number to skip
        limit: Maximum to return
        db: Database session

    Returns:
        SubmissionListResponse with paginated results
    """
    query = db.query(Submission).filter(Submission.student_id == student.id)
    total = query.count()
    submissions = (
        query.order_by(Submission.submitted_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    items = []
    for sub in submissions:
        if sub.scoring_result:
            items.append(
                ScoreResponse(
                    submission_id=sub.id,
                    student_id=student.id,
                    status=sub.status,
                    deviation_score=sub.scoring_result.deviation_score,
                    authorship_probability=sub.scoring_result.authorship_probability,
                    recommended_action=sub.scoring_result.recommended_action,
                    rationale="",
                    baseline_confidence=sub.scoring_result.baseline_confidence,
                    interference=sub.scoring_result.full_result.get("interference", {}),
                    feature_vector=sub.scoring_result.feature_vector,
                    baseline_vector=sub.scoring_result.full_result.get("baseline_vector", {}),
                    model_version=sub.scoring_result.model_version,
                    scored_at=sub.scoring_result.scored_at,
                )
            )

    return SubmissionListResponse(
        items=items,
        total=total,
        page=skip // limit,
        limit=limit,
    )


@router.get("/{student_id}/submissions/{submission_id}")
def get_submission(
    student: Student = Depends(require_same_institution),
    submission_id: str = None,
    db: Session = Depends(get_db),
):
    """Get a specific submission."""
    submission = db.query(Submission).filter(
        Submission.id == submission_id,
        Submission.student_id == student.id,
    ).first()

    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    if not submission.scoring_result:
        return {
            "submission_id": submission.id,
            "student_id": student.id,
            "status": submission.status,
            "created_at": submission.created_at,
        }

    result = submission.scoring_result
    return ScoreResponse(
        submission_id=submission.id,
        student_id=student.id,
        status=submission.status,
        deviation_score=result.deviation_score,
        authorship_probability=result.authorship_probability,
        recommended_action=result.recommended_action,
        rationale="",
        baseline_confidence=result.baseline_confidence,
        interference=result.full_result.get("interference", {}),
        feature_vector=result.feature_vector,
        baseline_vector=result.full_result.get("baseline_vector", {}),
        model_version=result.model_version,
        scored_at=result.scored_at,
    )


@router.post(
    "/{student_id}/submissions/{submission_id}/decision",
    status_code=status.HTTP_201_CREATED,
    summary="Record instructor decision",
    responses={
        404: {"description": "Submission not found"},
        422: {"description": "Invalid action value"},
    },
)
def record_instructor_decision(
    submission_id: str,
    body: DecisionRequest,
    student: Student = Depends(require_same_institution),
    user=Depends(get_current_instructor),
    db: Session = Depends(get_db),
):
    """
    Record an immutable instructor decision on a submission.

    Args:
        student: Student (via dependency)
        submission_id: Submission ID
        action: ActionType (escalate, monitor, clear, etc.)
        notes: Optional notes
        user: Current user (instructor)
        db: Database session

    Returns:
        Created decision
    """
    submission = db.query(Submission).filter(
        Submission.id == submission_id,
        Submission.student_id == student.id,
    ).first()

    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    # Create immutable decision record
    decision = InstructorDecision(
        submission_id=submission.id,
        user_id=user.id,
        action=ActionType(body.action),
        notes=body.notes,
    )

    db.add(decision)
    db.commit()
    db.refresh(decision)

    return {
        "id": decision.id,
        "submission_id": submission.id,
        "action": decision.action,
        "notes": decision.notes,
        "created_at": decision.created_at,
    }
