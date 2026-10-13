"""Staff-only study labels, rescore controls and privacy-limited exports."""

from __future__ import annotations

import csv
import io
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .. import principal as principal_mod
from ..schemas import StudyLabelsRequest
from ..study_export import export_csv
from ..study_scoring import rescore_exam, style_scoring_enabled
from ._shared import _repo, _require_staff
from .bluebook import _can_touch, _owned_exam

router = APIRouter()
_MAX_LABEL_CSV_BYTES = 1_000_000
_MAX_LABEL_CSV_ROWS = 2_000
_LABEL_CSV_HEADER = ("submission_id", "study_label", "imitated_student_id")


def _owned_original_exam(exam_id: str, request: Request) -> dict:
    _require_staff(request)
    exam = _owned_exam(exam_id, request)
    if "original" not in principal_mod.tenant_products(exam.get("tenant_id")):
        raise HTTPException(
            status_code=403, detail="This workspace's plan does not include Original."
        )
    return exam


def _owned_original_submission(submission_id: str, request: Request) -> dict:
    _require_staff(request)
    row = _repo().get_bluebook_submission(submission_id)
    if row is None or not _can_touch(request, row.get("tenant_id")):
        raise HTTPException(status_code=404, detail="submission not found")
    if "original" not in principal_mod.tenant_products(row.get("tenant_id")):
        raise HTTPException(
            status_code=403, detail="This workspace's plan does not include Original."
        )
    return row


def _clean_label(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _clean_imitated_student_id(value: str | None, tenant_id: str | None) -> str | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    if len(cleaned) > 128:
        raise HTTPException(status_code=422, detail="imitated_student_id is too long")
    owner = principal_mod.tenant_of(cleaned)
    if owner is not None and owner != tenant_id:
        raise HTTPException(
            status_code=422, detail="imitated_student_id must belong to this workspace"
        )
    return cleaned


def _apply_labels(row: dict, label: str | None, imitated_id: str | None, actor: str) -> bool:
    repo = _repo()
    result = repo.set_bluebook_study_fields(row["id"], label, imitated_id)
    if result is None:
        raise HTTPException(status_code=404, detail="submission not found")
    if result["changed"]:
        fields = [
            name
            for name, before, after in (
                ("study_label", result["previous"]["study_label"], label),
                (
                    "imitated_student_id",
                    result["previous"]["imitated_student_id"],
                    imitated_id,
                ),
            )
            if before != after
        ]
        repo.log_audit(
            action="bluebook_study_labels",
            student_id=row.get("student_id") or None,
            tenant_id=row.get("tenant_id"),
            actor=actor,
            details={"submission_id": row["id"], "fields": fields},
        )
    return result["changed"]


@router.patch("/bluebook/submissions/{submission_id}/study-label")
def set_submission_study_label(submission_id: str, body: StudyLabelsRequest, request: Request):
    """Set or clear ground-truth study metadata for one sealed submission."""
    staff = _require_staff(request)
    row = _owned_original_submission(submission_id, request)
    if not body.model_fields_set:
        raise HTTPException(status_code=422, detail="At least one study field is required")
    current = _repo().get_bluebook_study_submission(submission_id) or {}
    label = (
        _clean_label(body.study_label)
        if "study_label" in body.model_fields_set
        else current.get("study_label")
    )
    imitated_id = (
        _clean_imitated_student_id(body.imitated_student_id, row.get("tenant_id"))
        if "imitated_student_id" in body.model_fields_set
        else current.get("imitated_student_id")
    )
    changed = _apply_labels(row, label, imitated_id, staff.user_id)
    return {"submission_id": submission_id, "changed": changed}


@router.post("/bluebook/study-labels.csv")
async def batch_set_study_labels(request: Request):
    """Apply CSV rows with exact columns submission_id,study_label,imitated_student_id."""
    staff = _require_staff(request)
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in {"text/csv", "application/csv"}:
        raise HTTPException(status_code=415, detail="Content-Type must be text/csv")
    raw = await request.body()
    if len(raw) > _MAX_LABEL_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV is too large")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
        if tuple(reader.fieldnames or ()) != _LABEL_CSV_HEADER:
            raise HTTPException(
                status_code=422,
                detail="CSV header must be submission_id,study_label,imitated_student_id",
            )
        parsed = list(reader)
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="CSV must be UTF-8") from None
    if len(parsed) > _MAX_LABEL_CSV_ROWS:
        raise HTTPException(status_code=413, detail="CSV may contain at most 2000 rows")
    if not parsed:
        raise HTTPException(status_code=422, detail="CSV must contain at least one row")

    updates = []
    seen = set()
    for line, item in enumerate(parsed, start=2):
        if None in item or any(value is None for value in item.values()):
            raise HTTPException(status_code=422, detail=f"malformed CSV row {line}")
        submission_id = (item.get("submission_id") or "").strip()
        if not submission_id or submission_id in seen:
            raise HTTPException(
                status_code=422, detail=f"invalid or duplicate submission_id at row {line}"
            )
        seen.add(submission_id)
        row = _owned_original_submission(submission_id, request)
        label = _clean_label(item.get("study_label"))
        if label is not None and len(label) > 120:
            raise HTTPException(status_code=422, detail=f"study_label is too long at row {line}")
        imitated_id = _clean_imitated_student_id(
            item.get("imitated_student_id"), row.get("tenant_id")
        )
        updates.append((row, label, imitated_id))

    changed = 0
    for row, label, imitated_id in updates:
        changed += _apply_labels(row, label, imitated_id, staff.user_id)
    return {"rows": len(updates), "changed": changed, "unchanged": len(updates) - changed}


@router.get("/bluebook/exams/{exam_id}/study-export.csv")
def export_study_exam(exam_id: str, request: Request):
    exam = _owned_original_exam(exam_id, request)
    salt = os.environ.get("STUDY_EXPORT_SALT", "")
    try:
        content = export_csv(
            _repo().list_bluebook_study_submissions([exam_id], exam.get("tenant_id")), salt
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="study-{exam_id}.csv"'},
    )


@router.post("/bluebook/exams/{exam_id}/rescore")
def rescore_study_exam(exam_id: str, request: Request):
    exam = _owned_original_exam(exam_id, request)
    if not style_scoring_enabled(exam, exam.get("tenant_id")):
        raise HTTPException(
            status_code=409, detail="Original style scoring is not enabled for this exam"
        )
    try:
        result = rescore_exam(exam_id, repo=_repo())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    staff = request.state.principal
    _repo().log_audit(
        action="bluebook_study_rescore",
        tenant_id=exam.get("tenant_id"),
        actor=staff.user_id,
        details=result,
    )
    return result
