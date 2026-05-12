"""
tasks/scoring.py — Background scoring tasks.

Provides async task handlers for scoring submissions when ENABLE_BACKGROUND_SCORING=True.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
from sqlalchemy.orm import Session

from original.constants import ALL_FEATURE_CODES
from original.core.logging import get_logger
from original.db.models import BaselineSample, Submission, SubmissionStatus, ScoringResult
from original.db.session import SessionLocal
from original.features.pipeline import extract_features, compute_full_features
from original.quantum.scoring import score
from original.quantum.state import BaselineSample as QBaselineSample, StudentState
from original.tension_arc import analyze_tension_arc

log = get_logger(__name__)


def reconstruct_student_state(student_id: str, db: Session) -> StudentState:
    """
    Reconstruct a student's quantum state from baseline samples in the database.

    Args:
        student_id: Student ID
        db: Database session

    Returns:
        StudentState object with all active baseline samples
    """
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
    for sample in baseline_samples:
        # Convert stored JSON feature vector to numpy array
        feature_list = [
            sample.feature_vector.get(code, 0.0) for code in ALL_FEATURE_CODES
        ]
        vector = np.array(feature_list, dtype=np.float64)

        q_sample = QBaselineSample(
            text=sample.raw_text or "",
            vector=vector,
            provenance=sample.provenance,
            auth_weight=sample.auth_weight,
            assignment=sample.assignment,
            submitted_at=sample.submitted_at.isoformat(),
        )
        q_samples.append(q_sample)

        if sample.raw_text:
            raw_texts.append(sample.raw_text)

    state = StudentState(student_id=student_id, samples=q_samples)
    return state, raw_texts


def get_or_create_student_state(student_id: str, db: Session = None) -> StudentState:
    """
    Get or create a cached student state.

    For now, this just reconstructs from the database.
    In production, integrate with Redis for caching.

    Args:
        student_id: Student ID
        db: Database session (creates one if not provided)

    Returns:
        StudentState object
    """
    if db is None:
        db = SessionLocal()
        should_close = True
    else:
        should_close = False

    try:
        state, raw_texts = reconstruct_student_state(student_id, db)
        return state, raw_texts
    finally:
        if should_close:
            db.close()


def score_submission_task(
    submission_id: str, text: str, db: Session = None
) -> None:
    """
    Background task to score a submission.

    Args:
        submission_id: Submission ID
        text: Submission text
        db: Database session (creates one if not provided)
    """
    if db is None:
        db = SessionLocal()
        should_close = True
    else:
        should_close = False

    try:
        # Load submission
        submission = db.query(Submission).filter(
            Submission.id == submission_id
        ).first()

        if not submission:
            log.warning("Submission not found", extra={"submission_id": submission_id})
            return

        # Update status
        submission.status = SubmissionStatus.SCORING
        db.commit()

        # Reconstruct student state and collect baseline texts
        state, baseline_texts = reconstruct_student_state(submission.student_id, db)

        # Extract features with real comparison features (KL-divergence)
        features = compute_full_features(text, baseline_texts)
        submission_vector = np.array(
            [features[code] for code in ALL_FEATURE_CODES],
            dtype=np.float64,
        )

        # Score — pass (state, vector, feature_dict, submission_id)
        layer7_output = score(state, submission_vector, features, str(submission.id))

        # ── Tension Arc (orthogonal signal, non-fatal) ────────────────────────
        try:
            # Fetch student to get baseline_kappa (may be None if no proctored baselines yet)
            from original.db.models import Student as _Student
            _student = db.query(_Student).filter(
                _Student.id == submission.student_id
            ).first()
            _baseline_kappa = _student.baseline_kappa if _student else None
            tension_result = analyze_tension_arc(
                text=text,
                baseline_kappa=_baseline_kappa,
            )
            layer7_output.tension_arc = tension_result
        except Exception as _exc:
            log.warning(
                "tension_arc_failed_in_background_task",
                extra={"error": str(_exc), "submission_id": submission_id},
            )

        # Create result
        scoring_result = ScoringResult(
            submission_id=submission.id,
            model_version="1.0.0",
            deviation_score=layer7_output.authorship.deviation_score,
            authorship_probability=layer7_output.authorship.authorship_probability,
            recommended_action=layer7_output.recommendation.action,
            baseline_confidence={
                "purity": layer7_output.baseline_confidence.purity,
                "sample_count": layer7_output.baseline_confidence.sample_count,
            },
            full_result={},
            feature_vector=features,
            scored_at=datetime.utcnow(),
        )

        submission.status = SubmissionStatus.SCORED
        db.add(scoring_result)
        db.commit()

        log.info(
            "Submission scored",
            extra={
                "submission_id": submission_id,
                "deviation": layer7_output.authorship.deviation_score,
            },
        )

    except Exception as e:
        log.error(
            "Scoring task failed",
            extra={"submission_id": submission_id, "error": str(e)},
            exc_info=True,
        )
        submission.status = SubmissionStatus.FAILED
        db.commit()

    finally:
        if should_close:
            db.close()
