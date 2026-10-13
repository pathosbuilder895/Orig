"""Server-side Original style scores for sealed Collections submissions.

Study scores are report-only, remain separate from student-facing response
shapes, and are computed only when an exam explicitly enables ``aiDetect``
and its tenant has the Original product.
"""

from __future__ import annotations

import hashlib
import json
import logging

from fastapi import HTTPException

log = logging.getLogger(__name__)

STYLE_ENGINE_VERSION = "original-layer7-style-v1"


def style_scoring_enabled(exam: dict, tenant_id: str | None) -> bool:
    """Whether the stored exam and tenant both authorize style scoring."""
    from . import principal

    conditions = exam.get("conditions") or {}
    return (
        isinstance(conditions, dict)
        and conditions.get("aiDetect") is True
        and "original" in principal.tenant_products(tenant_id)
    )


def _threshold_version(repo) -> str:
    """Identify the static and currently applied action-threshold set."""
    from .constants import ACTION_THRESHOLDS

    payload = {
        "static": ACTION_THRESHOLDS,
        "tuned": repo.get_active_tuned_thresholds(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "thresholds-sha256:" + hashlib.sha256(encoded.encode()).hexdigest()[:16]


def score_study_submission(submission: dict, repo=None) -> dict:
    """Score a sealed row against its current approved reference baselines.

    Repeated calls replace the single submission score row, making both a seal
    replay and a staff rescore safe. The probe itself is never added to the
    student's baseline.
    """
    from .repository import get_repository
    from .routers.students_scoring import score_submission
    from .schemas import ScoreSubmissionRequest

    repo = repo or get_repository()
    if submission.get("status", "SUBMITTED").upper() != "SUBMITTED":
        return {"status": "skipped", "reason": "not_sealed"}
    writer_id = str(submission.get("student_id") or "").strip()
    study_label = str(submission.get("study_label") or "").strip().casefold()
    claimed_id = str(submission.get("imitated_student_id") or "").strip()
    student_id = claimed_id if study_label == "shadow" else writer_id
    text = str(submission.get("text") or "")
    if not student_id or not text.strip():
        return {"status": "skipped", "reason": "missing_student_or_text"}

    from . import principal

    student_tenant = principal.tenant_of(student_id)
    submission_tenant = submission.get("tenant_id")
    if student_tenant is not None and submission_tenant and student_tenant != submission_tenant:
        return {"status": "skipped", "reason": "baseline_student_tenant_mismatch"}
    state = repo.get(student_id)
    approved_samples = [
        sample
        for sample in getattr(state, "samples", [])
        if state is not None
        if getattr(sample, "provenance", None) in {"proctored", "verified"}
    ]
    baseline_count = len(approved_samples)
    baseline_words = sum(
        len((getattr(sample, "text", "") or "").split()) for sample in approved_samples
    )

    probe_id = str(submission.get("id") or submission.get("submission_id") or "")
    try:
        result = score_submission(
            student_id,
            ScoreSubmissionRequest(
                text=text,
                submission_id=probe_id,
                assignment=str(submission.get("exam") or submission.get("exam_title") or ""),
            ),
            request=None,
        )
    except HTTPException as exc:
        # A student without an approved baseline is a readiness finding, not
        # a failed seal. Do not persist client-supplied scores as fallback.
        return {"status": "skipped", "reason": f"scoring_unavailable_{exc.status_code}"}
    except Exception:
        log.exception("Original style score failed for sealed submission")
        return {"status": "skipped", "reason": "scoring_error"}

    score = float(result.authorship.deviation_score)
    features = {str(key): float(value) for key, value in result.feature_vector.items()}
    engine_version = STYLE_ENGINE_VERSION
    threshold_version = _threshold_version(repo)
    action = str(result.recommendation.action)
    if not repo.set_bluebook_style_score(
        probe_id,
        score,
        features,
        engine_version,
        threshold_version,
        float(result.authorship.authorship_probability),
        action,
        action,
        baseline_count,
        baseline_words,
    ):
        return {"status": "skipped", "reason": "submission_missing"}
    return {
        "status": "scored",
        "score": score,
        "authorship_probability": float(result.authorship.authorship_probability),
        "recommended_action": action,
        "verdict": action,
        "baseline_count": baseline_count,
        "baseline_words": baseline_words,
        "engine_version": engine_version,
        "threshold_version": threshold_version,
    }


def rescore_exam(exam_id: str, repo=None) -> dict:
    """Rescore every sealed submission in an authorized Original exam."""
    from . import principal
    from .repository import get_repository

    repo = repo or get_repository()
    exam = repo.get_bluebook_exam(exam_id)
    if exam is None:
        raise ValueError("exam not found")
    if not style_scoring_enabled(exam, exam.get("tenant_id")):
        raise ValueError("Original style scoring is not enabled for this exam")

    rows = repo.list_bluebook_study_submissions([exam_id], exam.get("tenant_id"))
    counts = {"scored": 0, "skipped": 0}
    for row in rows:
        student_id = row.get("student_id") or ""
        owner = principal.tenant_of(student_id)
        if owner is not None and owner != exam.get("tenant_id"):
            counts["skipped"] += 1
            continue
        result = score_study_submission(row, repo=repo)
        counts[result["status"] if result["status"] in counts else "skipped"] += 1
    counts["exam_id"] = exam_id
    counts["total"] = len(rows)
    return counts
