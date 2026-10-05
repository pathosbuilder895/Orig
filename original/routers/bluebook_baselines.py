"""Professor-approved writing baselines (plan Phase 7).

A sealed Bluebook exam enters a student's Original baseline only when a
professor approves it, one at a time or for a whole examination, and an
approval can be removed. "In baseline" is derived from the baseline itself:
the SHA-256 of the exam's answer text among the student's sample hashes, so
there is no approval table to drift out of step with the profile.

Adding goes through the existing baseline-write handler, so validation, the
seal-replay guard, the drift gate and its audit entry apply unchanged; the
drift gate is never overridden. Design:
docs/superpowers/specs/2026-10-05-baseline-approval-design.md
"""

from __future__ import annotations

import hashlib
import logging
import sys

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from .. import principal as principal_mod
from ..schemas import AddSampleRequest
from ..tension_arc import analyze_tension_arc, update_student_baseline_kappa
from ._shared import _exam_submissions, _persist_or_503, _repo, _require_staff
from .bluebook import _can_touch, _owned_exam
from .students_baseline import _hashes_from_samples, add_baseline

log = logging.getLogger(__name__)
router = APIRouter()

NO_ORIGINAL = "This workspace's plan does not include Original."
NOTHING_WRITTEN = "Nothing written to add."
NOT_ADDED = "Could not be added."
TOO_LONG = "This exam is too long to add as a baseline sample."
HELD_DETAIL = (
    "Not added: this exam differs strongly from the student's existing samples. "
    "Approval does not override this check."
)


def _baseline_text(rec: dict) -> str:
    """The student's own words: answers joined by a blank line, without the
    "Question N." headings the stored text carries for multi-question exams."""
    raw = rec.get("answers") or []
    if raw:  # stored answers win, even when all blank: the text has headings
        return "\n\n".join(str(a).strip() for a in raw if str(a or "").strip())
    return (rec.get("text") or "").strip()


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _fingerprints(rec: dict) -> set[str]:
    """Every fingerprint this exam can have in a baseline: the approved form
    (answers, no headings) and, for samples the old seal-time write added,
    the stored text exactly as it was sent (with "Question N." headings)."""
    out = set()
    text = _baseline_text(rec)
    if text:
        out.add(_fingerprint(text))
    if rec.get("text"):
        out.add(_fingerprint(rec["text"]))
    return out


def _require_original(tenant_id: str | None) -> None:
    if "original" not in principal_mod.tenant_products(tenant_id):
        raise HTTPException(status_code=403, detail=NO_ORIGINAL)


def _actor(request: Request) -> str:
    p = getattr(request.state, "principal", None)
    return getattr(p, "user_id", "") or ""


def _owned_submission(submission_id: str, request: Request) -> dict:
    _require_staff(request)
    rec = _repo().get_bluebook_submission(submission_id)
    if rec is None or not _can_touch(request, rec.get("tenant_id")):
        raise HTTPException(status_code=404, detail="submission not found")
    _require_original(rec.get("tenant_id"))
    return rec


def _owned_original_exam(exam_id: str, request: Request) -> dict:
    _require_staff(request)
    exam = _owned_exam(exam_id, request)
    _require_original(exam.get("tenant_id"))
    return exam


def _student_in_workspace(rec: dict, request: Request) -> bool:
    """Whether the submission's student belongs to the submission's workspace
    and is one the caller may act on.

    The approval routes are not under ``/students/{id}``, so the tenant
    middleware never checks the student; a submission row can name any
    student id (staff may record one for a student they name), so every
    profile read or write here must pass this first. ``assert_student_access``
    carries the demo and flat-id rules (including the real-deploy lockdown);
    the second test pins a tenant-prefixed id to the row's own workspace.
    """
    student_id = rec.get("student_id")
    if not student_id:
        return False
    try:
        principal_mod.assert_student_access(request.state.principal, student_id)
    except principal_mod.TenantAccessError:
        return False
    owner = principal_mod.tenant_of(student_id)
    return owner is None or owner == rec.get("tenant_id")


def _require_student_in_workspace(rec: dict, request: Request) -> None:
    if not _student_in_workspace(rec, request):
        raise HTTPException(status_code=404, detail="submission not found")


def _submitted_at(rec: dict) -> str:
    created = rec.get("created_at")
    value = created.isoformat() if hasattr(created, "isoformat") else str(created or "")
    return value[:10]


def _row(rec: dict, status: str, detail: str = "") -> dict:
    return {
        "submission_id": rec["id"],
        "student": rec.get("student"),
        "status": status,
        "detail": detail,
    }


def _add(rec: dict, request: Request) -> dict:
    # Per row, not only per exam: an exam with no workspace (a legacy row)
    # lists submissions from every workspace, and a row from one without
    # Original must never reach a profile.
    _require_original(rec.get("tenant_id"))
    text = _baseline_text(rec)
    if not text or not rec.get("student_id"):
        return _row(rec, "nothing_written", NOTHING_WRITTEN)
    _require_student_in_workspace(rec, request)
    # "In baseline" is the same test the status route uses, so a sample the
    # old seal stored with "Question N." headings is not added a second time.
    state = _repo().get(rec["student_id"])
    if state is not None and _fingerprints(rec) & _hashes_from_samples(state.samples):
        return _row(rec, "already_in_baseline")
    try:
        req = AddSampleRequest(
            text=text,
            provenance="proctored",
            assignment=rec.get("exam") or "",
            submitted_at=_submitted_at(rec),
            submission_uuid=rec.get("submission_uuid") or rec["id"],
        )
    except ValidationError:
        # The seal caps the answers' total length; the blank lines joining
        # them can still carry the text past the baseline sample's own cap.
        raise HTTPException(status_code=422, detail=TOO_LONG) from None
    try:
        out = add_baseline(rec["student_id"], req, request)
    except HTTPException as exc:
        if exc.status_code in (202, 409):  # drift gate: flag for review / rebaseline
            return _row(rec, "held", HELD_DETAIL)
        raise
    return _row(rec, "already_in_baseline" if out.get("skipped") else "added")


def _matching_indices(state, fingerprints: set[str]) -> list[int]:
    """Indices of every sample carrying one of this exam's fingerprints
    (duplicates included), highest first so they can be popped in order."""
    return [
        i
        for i in range(len(state.samples) - 1, -1, -1)
        if _hashes_from_samples([state.samples[i]]) & fingerprints
    ]


def _rebuild_kappa(state) -> None:
    """Recompute the tension-arc κ baseline from the remaining samples with
    the admission rule (authenticated provenance, κ > 0)."""
    log: list[float] = []
    mean = None
    for sample in state.samples:
        if sample.provenance in ("proctored", "verified") and sample.text:
            kappa = analyze_tension_arc(sample.text).catastrophe_index
            if kappa > 0:
                mean = update_student_baseline_kappa(log, kappa)
    state.kappa_log = log
    state.baseline_kappa = mean


@router.post("/bluebook/submissions/{submission_id}/baseline")
def approve_submission_baseline(submission_id: str, request: Request):
    """Add one sealed exam to the student's writing baseline."""
    rec = _owned_submission(submission_id, request)
    result = _add(rec, request)
    if result["status"] == "nothing_written":
        raise HTTPException(status_code=422, detail=NOTHING_WRITTEN)
    _repo().log_audit(
        action="baseline_approve",
        student_id=rec["student_id"],
        tenant_id=rec.get("tenant_id"),
        actor=_actor(request),
        result=result["status"],
        details={"submission_id": rec["id"]},
    )
    return result


@router.delete("/bluebook/submissions/{submission_id}/baseline")
def remove_submission_baseline(submission_id: str, request: Request):
    """Take one exam back out of the student's baseline; the profile is
    recomputed from the remaining samples."""
    rec = _owned_submission(submission_id, request)
    if rec.get("student_id"):
        _require_student_in_workspace(rec, request)
    fingerprints = _fingerprints(rec)
    state = _repo().get(rec["student_id"]) if rec.get("student_id") and fingerprints else None
    indices = _matching_indices(state, fingerprints) if state is not None else []
    if not indices:
        return _row(rec, "not_in_baseline")
    for index in indices:
        state.remove_sample(index)
    _rebuild_kappa(state)
    _persist_or_503(state)
    # The fused score keeps a per-student profile of raw baseline text in
    # process (FUSED_SCORE_* flags); drop it, as delete_student does.
    fusion_peers = sys.modules.get("original.fusion.peers")
    if fusion_peers is not None:
        fusion_peers.clear_student(rec["student_id"])
    _repo().log_audit(
        action="baseline_remove",
        student_id=rec["student_id"],
        tenant_id=rec.get("tenant_id"),
        actor=_actor(request),
        result="removed",
        details={
            "submission_id": rec["id"],
            "samples_removed": len(indices),
            "sample_count_after": state.sample_count,
        },
    )
    return _row(rec, "removed")


@router.post("/bluebook/exams/{exam_id}/baseline")
def approve_exam_baselines(exam_id: str, request: Request):
    """Add every sealed submission of an examination to its student's baseline."""
    exam = _owned_original_exam(exam_id, request)
    ids: dict[str, list[str]] = {
        status: []
        for status in ("added", "already_in_baseline", "held", "nothing_written", "error")
    }
    results = []
    for rec in _exam_submissions(exam):
        try:
            row = _add(rec, request)
        except HTTPException as exc:
            row = _row(rec, "error", str(exc.detail))
        except Exception:
            # One bad row must not 500 the batch after earlier rows were saved.
            # The message carries ids only, never student text.
            log.exception("baseline approval failed for submission %s", rec["id"])
            row = _row(rec, "error", NOT_ADDED)
        ids[row["status"]].append(rec["id"])
        results.append(row)
    counts = {
        "added": len(ids["added"]),
        "already_in_baseline": len(ids["already_in_baseline"]),
        "held": len(ids["held"]),
        "nothing_written": len(ids["nothing_written"]),
        "errors": len(ids["error"]),
    }
    _repo().log_audit(
        action="baseline_approve_bulk",
        tenant_id=exam.get("tenant_id"),
        actor=_actor(request),
        details={
            "exam_id": exam_id,
            **counts,
            **{f"{status}_ids": sub_ids for status, sub_ids in ids.items()},
        },
    )
    return {**counts, "results": results}


@router.get("/bluebook/exams/{exam_id}/baseline")
def exam_baseline_status(exam_id: str, request: Request):
    """Whether each submission of an examination is in its student's baseline."""
    exam = _owned_original_exam(exam_id, request)
    hashes: dict[str, set[str]] = {}  # each student's baseline, read once
    out = []
    for rec in _exam_submissions(exam):
        text = _baseline_text(rec)
        sid = rec.get("student_id")
        in_baseline = False
        if sid and _student_in_workspace(rec, request):
            if sid not in hashes:
                state = _repo().get(sid)
                hashes[sid] = _hashes_from_samples(state.samples) if state is not None else set()
            in_baseline = bool(_fingerprints(rec) & hashes[sid])
        out.append(
            {
                "submission_id": rec["id"],
                "student": rec.get("student"),
                "in_baseline": in_baseline,
                "has_text": bool(text),
            }
        )
    return {"submissions": out}
