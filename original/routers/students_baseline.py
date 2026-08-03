"""Baseline ingestion for a student.

Single-sample add, batch file upload, and the Bbook proctored-baseline request
surfaces. Moved verbatim from original/api.py; part of the /students* route
group split out of students.py for file size.
"""

from __future__ import annotations

import io
import logging

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from .. import baseline_requests, bbook_client
from ..constants import AUTH_WEIGHTS
from ..features.pipeline import feature_vector
from ..quantum.state import BaselineSample
from ..schemas import AddSampleRequest, DriftPendingResponse, DriftResultOut
from ..tension_arc import analyze_tension_arc, update_student_baseline_kappa
from ._shared import _authorize_provenance, _persist_or_503, _repo, _require_guard

router = APIRouter()


# ── Add baseline sample ───────────────────────────────────────────────────────


def _existing_text_hashes(student_id: str) -> set[str]:
    """SHA-256 hashes of every baseline sample's text for dedup, covering both
    batch-uploaded samples (which carry .text_hash) and paste-added ones
    (hashed from .text here). Missing student → empty set, never created."""
    import hashlib as _hashlib

    state = _repo().get(student_id)
    if state is None:
        return set()
    hashes: set[str] = set()
    for s in state.samples:
        h = getattr(s, "text_hash", None)
        if not h and getattr(s, "text", None):
            h = _hashlib.sha256(s.text.encode()).hexdigest()
        if h:
            hashes.add(h)
    return hashes


@router.post("/students/{student_id}/baseline")
def add_baseline(student_id: str, req: AddSampleRequest, request: Request = None):
    if req.provenance not in AUTH_WEIGHTS:
        raise HTTPException(
            status_code=422, detail=f"provenance must be one of: {list(AUTH_WEIGHTS)}"
        )

    # Gate high-trust provenance behind staff/attestation (see _authorize_provenance).
    provenance, provenance_downgraded = _authorize_provenance(request, student_id, req.provenance)
    auth_weight = AUTH_WEIGHTS[provenance]

    state = _repo().get_or_create(student_id)

    # Seal-replay guard (robustness spec §2, seal step 2): a retried baseline
    # upload carrying the same submission_uuid must not double-count an
    # identical text as a second sample.
    if req.submission_uuid:
        import hashlib

        text_hash = hashlib.sha256(req.text.encode()).hexdigest()
        if text_hash in _existing_text_hashes(student_id):
            return {
                "skipped": True,
                "reason": "duplicate_text",
                "student_id": student_id,
                "sample_index": state.sample_count - 1,
                "provenance": req.provenance,
                "authenticated_count": state.authenticated_count,
                "purity": state.purity,
            }

    vec = feature_vector(req.text, keystroke_data=req.keystroke_data)

    # Genre label — classify the text at ingestion time so the Hierarchical
    # Bayesian prior (BAYESIAN_PRIOR_ENABLED=1) has cross-student genre data.
    # Uses the same rule-based resolver as the context manifest pipeline.
    # Runs even when the manifest flag is off — genre metadata is cheap and
    # the prior needs it independent of the manifest subsystem.
    _sample_genre: str | None = None
    try:
        from ..context.resolvers import resolve_genre

        _genre_result = resolve_genre(req.text)
        _sample_genre = (_genre_result or {}).get("primary")
    except Exception:
        pass  # genre labeling is best-effort; don't fail baseline ingestion

    sample = BaselineSample(
        text=req.text,
        vector=vec,
        provenance=provenance,
        auth_weight=auth_weight,
        assignment=req.assignment,
        submitted_at=req.submitted_at,
        genre=_sample_genre,
        keystroke_data=req.keystroke_data,
    )

    # ── Phase 8: drift gate before adding to baseline ─────────────────────────
    # Only authenticated samples (auth_weight > 0) participate in the
    # baseline_mean — unverified samples can't drift the baseline either way,
    # so we skip the check for them. The check is best-effort: a failure is
    # logged and the sample is admitted as before (Phase 1 behaviour).
    drift_result = None
    if auth_weight > 0:
        try:
            drift_result = state.check_drift(sample)
        except Exception as e:
            logging.getLogger(__name__).warning(
                "drift check failed for %s: %s — admitting sample without gate",
                student_id,
                e,
            )
            drift_result = None

    # check_drift mutates _consecutive_drift_count regardless of recommendation;
    # persist the counter even on flag/rebaseline so the workflow is sticky.
    if drift_result is not None and drift_result.recommendation != "accept":
        # Sample is held for review — DO NOT admit to state.samples.
        _persist_or_503(state)  # persist counter mutation
        body = DriftPendingResponse(
            status="pending_review"
            if drift_result.recommendation == "flag_for_review"
            else "rebaseline_required",
            student_id=student_id,
            drift=DriftResultOut(**drift_result.to_dict()),
        )
        # 202 = Accepted but not applied (review pending);
        # 409 = Conflict (existing baseline is stale, rebaseline needed).
        status_code = 202 if drift_result.recommendation == "flag_for_review" else 409
        raise HTTPException(status_code=status_code, detail=body.model_dump())

    state.add_sample(sample)

    # Update tension arc κ baseline for authenticated samples
    if provenance in ("proctored", "verified"):
        arc = analyze_tension_arc(req.text)
        if arc.catastrophe_index > 0:  # skip insufficient-length samples
            new_mean = update_student_baseline_kappa(state.kappa_log, arc.catastrophe_index)
            state.baseline_kappa = new_mean

    _persist_or_503(state)  # persist to SQLite

    # Audit log — record the baseline addition
    _repo().log_audit(
        action="baseline_add",
        student_id=student_id,
        details={
            "provenance": provenance,
            "auth_weight": auth_weight,
            "sample_count_after": state.sample_count,
            "genre": _sample_genre,
            **(
                {"requested_provenance": req.provenance, "provenance_downgraded": True}
                if provenance_downgraded
                else {}
            ),
        },
    )

    # Auto-complete any outstanding magic-link baseline requests for this
    # student (Phase 2). Only fires for authenticated provenance — an
    # unverified self-upload doesn't satisfy a "proctored baseline" request.
    completed_requests: list = []
    if auth_weight > 0:
        try:
            completed_requests = baseline_requests.mark_completed_for_student(student_id)
        except Exception as e:
            logging.getLogger(__name__).warning(
                "baseline-request auto-complete failed for %s: %s",
                student_id,
                e,
            )

    response = {
        "student_id": student_id,
        "sample_index": state.sample_count - 1,
        "provenance": provenance,
        "auth_weight": auth_weight,
        "authenticated_count": state.authenticated_count,
        "purity": state.purity,
    }
    # Signal to the caller when a requested high-trust provenance was downgraded
    # for lack of staff/attestation, so a UI can explain it rather than silently
    # showing a weaker sample than asked for.
    if provenance_downgraded:
        response["provenance_downgraded"] = True
        response["requested_provenance"] = req.provenance
    # Include the drift result on accept too — useful for UIs that want to
    # show the trend even when no action was triggered.
    if drift_result is not None:
        response["drift"] = drift_result.to_dict()
    if completed_requests:
        response["completed_baseline_requests"] = [
            r.external_request_id for r in completed_requests
        ]
    return response


# ── Bbook integration: request a proctored baseline sitting ──────────────────
# Phase 2 (Original-first flow). The professor on professor.html clicks
# "Request proctored baseline" for a student. Original calls Bbook to
# provision a one-off magic-link exam and records the pending request here
# so the professor can see status. When Bbook later POSTs the resulting
# baseline back to /students/{id}/baseline (Phase 1 sync flow), the
# corresponding pending request is auto-marked completed.

from pydantic import BaseModel as _PydanticBaseModel  # local import to avoid disturbing top imports


class RequestBaselineRequest(_PydanticBaseModel):
    """Inbound shape for POST /students/{id}/request-baseline."""

    student_email: str
    student_name: str
    exam_title: str = "Proctored Baseline Sitting"
    institution_name: str | None = None
    requested_by: str | None = None  # free-form audit field
    duration_mins: int = 45
    min_word_count: int | None = None
    max_word_count: int | None = None
    prompt_text: str | None = None


@router.post("/students/{student_id}/request-baseline")
def request_proctored_baseline(student_id: str, req: RequestBaselineRequest):
    """
    Provision a magic-link proctored baseline exam in Bbook for this student.

    Returns the pending request record with the magic-link URL (only when
    SMTP delivery failed or is unconfigured — otherwise the student receives
    it by email). Idempotency is per-call: each invocation creates a new
    pending request with a fresh UUID.

    Requires BBOOK_API_URL and BBOOK_EXTERNAL_SECRET in the environment.
    Returns 503 if Bbook integration is not configured, 502 on Bbook errors.
    """
    if not bbook_client.is_enabled():
        raise HTTPException(
            status_code=503,
            detail="Bbook integration is not configured (set BBOOK_API_URL).",
        )

    external_id = baseline_requests.make_external_id()

    # Pre-record the pending request so the UI sees it immediately, even
    # before the Bbook round-trip completes. We'll update with the magic
    # link and Bbook exam id once the response arrives.
    import time as _time

    pending = baseline_requests.BaselineRequest(
        external_request_id=external_id,
        student_id=student_id,
        student_email=req.student_email,
        student_name=req.student_name,
        exam_title=req.exam_title,
        bbook_exam_id=None,
        magic_link=None,
        requested_at=_time.time(),
        expires_at=None,
        requested_by=req.requested_by,
    )
    baseline_requests.record(pending)

    try:
        result = bbook_client.request_baseline(
            student_email=req.student_email,
            student_name=req.student_name,
            exam_title=req.exam_title,
            institution_name=req.institution_name,
            requested_by=req.requested_by,
            duration_mins=req.duration_mins,
            min_word_count=req.min_word_count,
            max_word_count=req.max_word_count,
            prompt_text=req.prompt_text,
            external_request_id=external_id,
        )
    except Exception as e:
        baseline_requests.mark_failed(external_id, str(e))
        logging.getLogger(__name__).exception("Bbook baseline-request call failed")
        raise HTTPException(status_code=502, detail=f"Bbook call failed: {e}") from e

    # Update the pending record with the Bbook exam id + magic link + expiry.
    pending.bbook_exam_id = result.examId
    pending.magic_link = result.magicLink
    pending.email_delivered = result.emailDelivered
    if result.expiresAt:
        # Parse "2026-05-18T..." to epoch seconds for the registry
        from datetime import datetime

        try:
            pending.expires_at = datetime.fromisoformat(
                result.expiresAt.replace("Z", "+00:00")
            ).timestamp()
        except Exception:
            pending.expires_at = None
    baseline_requests.record(pending)

    return pending.to_dict()


@router.get("/baseline-requests/pending")
def list_pending_baseline_requests():
    """List all currently-pending proctored baseline requests."""
    return {"requests": [r.to_dict() for r in baseline_requests.list_pending()]}


@router.get("/baseline-requests")
def list_all_baseline_requests(request: Request):
    """
    List every proctored baseline request, regardless of status.
    When GUARD_DESTRUCTIVE=1, requires X-Guard-Token header (admin only).
    """
    _require_guard(request)
    return {"requests": [r.to_dict() for r in baseline_requests.list_all()]}


# ── Batch file upload → baseline ──────────────────────────────────────────────


@router.post("/students/{student_id}/baseline/upload-batch")
async def upload_baseline_batch(
    student_id: str,
    files: list[UploadFile] = File(...),
    provenance: str = Form("verified"),
    assignment: str = Form(""),
):
    """
    Upload one or more files (PDF, DOCX, TXT) as baseline samples in a single
    request.  Mirrors the v1 batch upload but requires no auth — used by the
    Import Papers drawer in the professor demo.
    """
    if provenance not in AUTH_WEIGHTS:
        raise HTTPException(
            status_code=422, detail=f"provenance must be one of: {list(AUTH_WEIGHTS)}"
        )

    state = _repo().get_or_create(student_id)
    imported = 0
    skipped_duplicates = 0
    errors: list[str] = []
    # Phase 8: per-file drift outcomes — surfaced on the batch response so
    # an instructor can see which files were held without aborting the batch.
    drift_holds: list[dict] = []

    for upload in files:
        filename = upload.filename or "unknown"
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        raw = await upload.read()

        # ── Text extraction ───────────────────────────────────────────────────
        try:
            if ext == "txt":
                text = raw.decode("utf-8", errors="replace")
            elif ext == "docx":
                from docx import Document as _Doc

                doc = _Doc(io.BytesIO(raw))
                text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
            elif ext == "pdf":
                from pypdf import PdfReader as _PdfReader

                reader = _PdfReader(io.BytesIO(raw))
                text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
            else:
                errors.append(f"{filename}: unsupported type '.{ext}' — use .txt, .docx, or .pdf")
                continue
        except Exception as exc:
            errors.append(f"{filename}: extraction error — {exc}")
            continue

        if not text.strip():
            errors.append(f"{filename}: no text extracted (empty or image-only file?)")
            continue

        # ── Deduplication ─────────────────────────────────────────────────────
        import hashlib as _hashlib

        text_hash = _hashlib.sha256(text.encode()).hexdigest()
        if any(getattr(s, "text_hash", None) == text_hash for s in state.samples):
            skipped_duplicates += 1
            continue

        # ── Feature extraction & store ────────────────────────────────────────
        try:
            vec = feature_vector(text)
        except Exception as exc:
            errors.append(f"{filename}: feature extraction failed — {exc}")
            continue

        label = assignment.strip() or filename.rsplit(".", 1)[0]
        sample = BaselineSample(
            text=text,
            vector=vec,
            provenance=provenance,
            auth_weight=AUTH_WEIGHTS[provenance],
            assignment=label,
            submitted_at="",
        )
        # Attach hash for future dedup checks
        sample.text_hash = text_hash  # type: ignore[attr-defined]

        # ── Phase 8: per-file drift gate (best-effort) ────────────────────────
        # Batch ingestion does NOT 202/409 on drift — that would block the
        # whole upload. Instead we hold individual outliers, record them in
        # `drift_holds`, and continue the loop. Instructor sees the per-file
        # outcome in the response.
        if AUTH_WEIGHTS[provenance] > 0:
            try:
                dr = state.check_drift(sample)
                if dr.recommendation != "accept":
                    drift_holds.append(
                        {
                            "filename": filename,
                            "drift": dr.to_dict(),
                        }
                    )
                    continue  # skip add_sample; counter already mutated
            except Exception as exc:
                # Drift check failure ≠ ingestion failure; admit as before.
                logging.getLogger(__name__).warning(
                    "drift check failed in batch for %s: %s",
                    filename,
                    exc,
                )

        state.add_sample(sample)

        if provenance in ("proctored", "verified"):
            arc = analyze_tension_arc(text)
            if arc.catastrophe_index > 0:
                new_mean = update_student_baseline_kappa(state.kappa_log, arc.catastrophe_index)
                state.baseline_kappa = new_mean

        imported += 1

    # Always persist when there was any state mutation (admitted samples
    # OR drift counter increments from holds).
    if imported > 0 or drift_holds:
        _persist_or_503(state)

    return {
        "imported": imported,
        "skipped_duplicates": skipped_duplicates,
        "errors": errors,
        "drift_holds": drift_holds,
    }
