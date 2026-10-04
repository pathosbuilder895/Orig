"""Baseline ingestion for a student.

Single-sample add, batch file upload, and the Bbook proctored-baseline request
surfaces. Moved verbatim from original/api.py; part of the /students* route
group split out of students.py for file size.
"""

from __future__ import annotations

import io
import logging

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from .. import baseline_requests, bbook_client, consumed_attestations, student_auth
from .. import principal as principal_mod
from ..constants import AUTH_WEIGHTS
from ..features.pipeline import feature_vector
from ..quantum.state import BaselineSample
from ..schemas import AddSampleRequest, DriftPendingResponse, DriftResultOut
from ..tension_arc import analyze_tension_arc, update_student_baseline_kappa
from ._shared import _authorize_provenance, _persist_or_503, _repo, _require_guard, _require_staff

router = APIRouter()


# ── Add baseline sample ───────────────────────────────────────────────────────


def _strip_raw_keystroke_arrays(keystroke_data: dict | None) -> dict | None:
    """ADR-010 (keystroke capture is macro-only): drop the raw per-key
    ``keystrokes`` and per-pause ``pauses`` arrays from an incoming
    ``keystroke_data`` blob before it is ever persisted.

    Every other key in the blob (``revisions``, ``deletionRate``,
    ``wordCount``, ``sessionDurationSec``, ``avgWpm``, etc. — see
    ``original/features/tier17.py``) is a macro/precomputed summary field,
    not raw per-key timing, and is kept. ``None`` passes through unchanged
    so a request without any keystroke telemetry stays that way. Returns a
    new dict — the caller's original ``keystroke_data`` (e.g. the request
    object, or whatever still needs the raw arrays for transient Tier 17
    feature extraction before this point) is never mutated.
    """
    if keystroke_data is None:
        return None
    stripped = dict(keystroke_data)
    stripped.pop("keystrokes", None)
    stripped.pop("pauses", None)
    return stripped


def _hashes_from_samples(samples) -> set[str]:
    """SHA-256 hashes of a sample iterable's text for dedup, covering both
    batch-uploaded samples (which carry .text_hash) and paste-added ones
    (hashed from .text here). Pure — takes samples directly so a caller that
    already holds a fetched StudentState can dedup without a second repo
    round-trip."""
    import hashlib as _hashlib

    hashes: set[str] = set()
    for s in samples:
        h = getattr(s, "text_hash", None)
        if not h and getattr(s, "text", None):
            h = _hashlib.sha256(s.text.encode()).hexdigest()
        if h:
            hashes.add(h)
    return hashes


def _existing_text_hashes(student_id: str) -> set[str]:
    """SHA-256 hashes of every baseline sample's text for dedup. Fetches the
    student's state itself; missing student → empty set, never created.
    Callers that already have a fetched/created state in hand should call
    ``_hashes_from_samples(state.samples)`` directly instead, to avoid a
    redundant repo round-trip."""
    state = _repo().get(student_id)
    if state is None:
        return set()
    return _hashes_from_samples(state.samples)


def _consume_proctor_attestation_if_needed(
    request: Request | None, student_id: str, sample: BaselineSample, provenance: str
) -> tuple[str, bool]:
    """Single-use enforcement for proctor attestations (T-69).

    If ``sample`` was admitted at 'proctored' trust and the caller
    presented an ``X-Proctor-Attestation`` header, consume the token's jti;
    a second write presenting the same token (replay within its 6h window)
    is retroactively downgraded rather than admitted at full weight again.
    Mutates ``sample`` in place on downgrade — safe because every baseline
    aggregate (``baseline_mean``/``baseline_std``/``loo_distances``) filters
    on ``auth_weight`` at READ time (quantum/state.py), never at admit time.

    No-op (returns ``provenance`` unchanged, no downgrade) when there is no
    attestation header or the sample wasn't admitted at proctored trust in
    the first place — the common case for every non-proctored write.

    Returns ``(effective_provenance, downgraded_here)``.
    """
    if provenance != "proctored" or request is None:
        return provenance, False
    attestation = request.headers.get("X-Proctor-Attestation", "")
    if not attestation:
        return provenance, False
    jti = student_auth.attestation_jti(attestation)
    exam = student_auth.attestation_exam(attestation)
    tenant_id = principal_mod.tenant_of(student_id)
    if consumed_attestations.mark_used(jti, tenant_id, exam, student_id):
        return provenance, False
    sample.provenance = "unverified"
    sample.auth_weight = AUTH_WEIGHTS["unverified"]
    return "unverified", True


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
    # identical text as a second sample. Built from `state.samples` (already
    # fetched/created above) rather than _existing_text_hashes(student_id),
    # which would redundantly re-fetch the same state from the repo.
    if req.submission_uuid:
        import hashlib

        text_hash = hashlib.sha256(req.text.encode()).hexdigest()
        if text_hash in _hashes_from_samples(state.samples):
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
        # ADR-010: never persist the raw per-key/per-pause arrays — only the
        # macro/summary fields (if any) inside the blob survive. `vec` above
        # was already extracted from the unstripped req.keystroke_data, so
        # Tier 17's (currently-disabled) feature extraction is unaffected.
        keystroke_data=_strip_raw_keystroke_arrays(req.keystroke_data),
        composition_summary=req.composition_summary,
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

    # Proctor attestations are single-use (T-69). Consumed only here, after
    # a successful admit — not before the drift gate above — so a
    # drift-held (202/409) attempt never burns the attestation; a
    # legitimate retry of the same sitting can still redeem it.
    provenance, downgraded_by_replay = _consume_proctor_attestation_if_needed(
        request, student_id, sample, provenance
    )
    if downgraded_by_replay:
        auth_weight = AUTH_WEIGHTS["unverified"]
        provenance_downgraded = True

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
def request_proctored_baseline(student_id: str, req: RequestBaselineRequest, request: Request):
    """
    Provision a magic-link proctored baseline exam in Bbook for this student.

    Staff only: provisioning an exam is an instructor action, not something a
    student may trigger for themselves (T-68) — the guard runs before the
    Bbook-config check so an unauthorized caller is refused even when the
    integration is unconfigured. ``request`` has no ``= None`` default on
    purpose: FastAPI always injects it over HTTP, and ``_require_staff`` has
    no in-process ``None`` arm, so a default would only turn a scripted call
    into an AttributeError.

    Guard choice, recorded: this uses ``_require_staff`` (mirroring
    ``/baseline-requests/pending``), which admits the anonymous demo
    principal OFF a real deploy. The route emails a live magic-link bearer
    credential to a caller-supplied address, which is closer to
    ``_require_non_demo_staff``'s rationale; it is acceptable today only
    because Bbook (``BBOOK_API_URL``) is configured solely on the pilot
    service, where the demo principal is refused. Revisit if Bbook is ever
    enabled on the demo deploy.

    Returns the pending request record with the magic-link URL (only when
    SMTP delivery failed or is unconfigured — otherwise the student receives
    it by email). Idempotency is per-call: each invocation creates a new
    pending request with a fresh UUID.

    Requires BBOOK_API_URL and BBOOK_EXTERNAL_SECRET in the environment.
    Returns 503 if Bbook integration is not configured, 502 on Bbook errors.
    """
    _require_staff(request)

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
def list_pending_baseline_requests(request: Request):
    """List currently-pending proctored baseline requests for the caller's tenant.

    Previously unauthenticated and unscoped: any caller, staff or not, could
    read every institution's pending requests, including student emails and
    live (unredeemed) magic-link bearer credentials. Staff now see only
    their own tenant's pending requests; SUPER_ROLES keep the cross-tenant
    "all schools" view, matching ``list_all_baseline_requests`` below and
    ``principal_mod.assert_tenant_access``'s convention.
    """
    principal = _require_staff(request)
    visible = []
    for r in baseline_requests.list_pending():
        try:
            principal_mod.assert_student_access(principal, r.student_id)
        except principal_mod.TenantAccessError:
            continue
        visible.append(r)
    return {"requests": [r.to_dict() for r in visible]}


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
def upload_baseline_batch(
    student_id: str,
    files: list[UploadFile] = File(...),
    provenance: str = Form("verified"),
    assignment: str = Form(""),
    request: Request = None,
):
    """
    Upload one or more files (PDF, DOCX, TXT) as baseline samples in a single
    request. Used by the Import Papers drawer in the professor demo.

    High-trust provenance is gated the same way ``add_baseline`` gates it:
    a non-staff caller without a valid proctor attestation is downgraded to
    ``unverified`` (never rejected), so the batch route can no longer be used
    to self-assert ``verified`` for uploaded files (T-67). The anonymous demo
    principal keeps its requested provenance OFF a real deploy, exactly as
    ``add_baseline`` does — the sandbox path is byte-identical.

    The response always carries ``provenance`` / ``requested_provenance`` /
    ``provenance_downgraded`` (``add_baseline`` emits the latter two only on
    a downgrade); always-present is the deliberate convention here because a
    batch has one effective provenance for every file it admitted.
    """
    if provenance not in AUTH_WEIGHTS:
        raise HTTPException(
            status_code=422, detail=f"provenance must be one of: {list(AUTH_WEIGHTS)}"
        )

    # Gate high-trust provenance behind staff/attestation (see
    # _authorize_provenance) — the batch route previously skipped this.
    requested_provenance = provenance
    provenance, provenance_downgraded = _authorize_provenance(request, student_id, provenance)

    state = _repo().get_or_create(student_id)
    imported = 0
    skipped_duplicates = 0
    errors: list[str] = []
    # Phase 8: per-file drift outcomes — surfaced on the batch response so
    # an instructor can see which files were held without aborting the batch.
    drift_holds: list[dict] = []

    # Dedup: seed from every hash already on record for this student, using
    # the same hash-building logic add_baseline's seal-replay guard and the
    # Canvas-import route use (falls back to hashing .text when a sample's
    # .text_hash didn't survive a persistence round-trip — BaselineSample
    # .text_hash is a plain attribute, not a stored field, so it never does).
    # Built from `state.samples` (already fetched by get_or_create above)
    # rather than via _existing_text_hashes(student_id), which would re-fetch
    # the same state from the repo a second time for no reason — there's no
    # await between the two calls, so nothing could have changed in between.
    # Grown as files are admitted below so duplicates *within* this same
    # batch are still caught without a second per-file repository read.
    seen_hashes = _hashes_from_samples(state.samples)

    for upload in files:
        filename = upload.filename or "unknown"
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        raw = upload.file.read()

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
        if text_hash in seen_hashes:
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
        # Recorded locally (not on the sample — see the comment above
        # seen_hashes) so a duplicate later in *this* batch is still caught.
        seen_hashes.add(text_hash)

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

        # T-69: consumed per file, exactly as add_baseline does, not once
        # per batch — a proctor attestation authorizes ONE document, so a
        # batch trying to admit several under the same attestation must
        # only honor the first. Once `provenance` is downgraded, every
        # remaining file's own call short-circuits at
        # _consume_proctor_attestation_if_needed's first check
        # (provenance != "proctored") without touching the ledger again.
        provenance, downgraded_by_replay = _consume_proctor_attestation_if_needed(
            request, student_id, sample, provenance
        )
        if downgraded_by_replay:
            provenance_downgraded = True

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

    # Audit log — mirrors add_baseline's shape so a provenance downgrade on
    # this route leaves the same forensic trace (attack 7 in the threat
    # model: the batch route is a detection surface, not just an ingest).
    _repo().log_audit(
        action="baseline_batch_upload",
        student_id=student_id,
        details={
            "provenance": provenance,
            "auth_weight": AUTH_WEIGHTS[provenance],
            "imported": imported,
            "skipped_duplicates": skipped_duplicates,
            "drift_holds": len(drift_holds),
            "sample_count_after": state.sample_count,
            **(
                {"requested_provenance": requested_provenance, "provenance_downgraded": True}
                if provenance_downgraded
                else {}
            ),
        },
    )

    return {
        "imported": imported,
        "skipped_duplicates": skipped_duplicates,
        "errors": errors,
        "drift_holds": drift_holds,
        "provenance": provenance,
        "requested_provenance": requested_provenance,
        "provenance_downgraded": provenance_downgraded,
    }
