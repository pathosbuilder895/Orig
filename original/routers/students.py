"""Student roster and per-student read surfaces.

Roster listing, student state, baseline readiness, single-sample prose, FERPA
deletion + data inventory, formation pathways, and single-file text
extraction. Moved verbatim from original/api.py.

Baseline ingestion lives in students_baseline.py and scoring in
students_scoring.py — same route group, split only for file size.
"""

from __future__ import annotations

import io
import os

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from .. import principal as principal_mod
from ..repository import get_repository
from ..schemas import (
    BaselineWordStats,
    ReadinessResponse,
    SampleSummary,
    StudentStateResponse,
)
from ._shared import _repo, _require_guard

router = APIRouter()


# ── Student list ──────────────────────────────────────────────────────────────


@router.get("/students")
def list_students(request: Request, tenant_id: str = ""):
    """
    List student IDs.

    Scoping (ADR-003): an authenticated, non-super principal only ever sees its
    own tenant's students — the `tenant_id` query param cannot widen that. The
    anonymous demo principal and super/operator roles keep the original
    behaviour (optional `tenant_id` filter, else all).
    """
    principal = getattr(request.state, "principal", None)
    roster_tenant = None
    if principal and not principal.is_demo and principal.role not in principal_mod.SUPER_ROLES:
        roster_tenant = principal.tenant_id
        ids = _repo().list_ids_for_tenant(roster_tenant)
    elif tenant_id:
        roster_tenant = tenant_id
        ids = _repo().list_ids_for_tenant(tenant_id)
    else:
        ids = _repo().list_ids()
    # `students` stays a list of ids (back-compat). `roster` adds the
    # display-ready rows (real names, baseline counts, status) the dashboards
    # render — only when scoped to a single tenant.
    roster = _repo().roster_for_tenant(roster_tenant) if roster_tenant else None
    return {"students": ids, "roster": roster}


# ── Student state ─────────────────────────────────────────────────────────────


@router.get("/students/{student_id}", response_model=StudentStateResponse)
def get_student(student_id: str):
    state = _repo().get(student_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Student '{student_id}' not found")

    traj = state.trajectory
    baseline_dict = {
        code: float(state.baseline_mean[i])
        for i, code in enumerate(
            __import__("original.constants", fromlist=["ALL_FEATURE_CODES"]).ALL_FEATURE_CODES
        )
    }

    samples_out = [
        SampleSummary(
            index=i,
            assignment=s.assignment,
            provenance=s.provenance,
            submitted_at=s.submitted_at,
            auth_weight=s.auth_weight,
        )
        for i, s in enumerate(state.samples)
    ]

    return StudentStateResponse(
        student_id=student_id,
        sample_count=state.sample_count,
        authenticated_count=state.authenticated_count,
        purity=state.purity,
        von_neumann_entropy=state.von_neumann_entropy,
        effective_sample_count=state.effective_sample_count,
        trajectory_direction=traj.direction,
        trajectory_confidence=traj.confidence,
        baseline_vector=baseline_dict,
        samples=samples_out,
    )


# ── Baseline-readiness check (pilot onboarding surface) ──────────────────────
# Answers "is this student's baseline good enough to score against yet?" in
# one call, with plain-language recommendations. Verdict thresholds: 5
# authenticated samples is where scoring confidence saturates
# (quantum/scoring.py), 2 is the developing floor, and 0 authenticated
# cannot score at all (the score endpoint 422s).


@router.get("/students/{student_id}/readiness", response_model=ReadinessResponse)
def get_student_readiness(student_id: str):
    state = _repo().get(student_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Student '{student_id}' not found")

    from collections import Counter
    from statistics import median as _median

    provenance_mix = dict(Counter(s.provenance for s in state.samples))
    word_counts = [len((s.text or "").split()) for s in state.samples]
    word_stats = None
    if word_counts:
        word_stats = BaselineWordStats(
            min=min(word_counts),
            median=int(_median(word_counts)),
            mean=round(sum(word_counts) / len(word_counts), 1),
            max=max(word_counts),
            n_below_300=sum(1 for w in word_counts if w < 300),
        )

    auth = state.authenticated_count
    eff = state.effective_sample_count
    if auth >= 5 and eff >= 3:
        verdict = "ready"
    elif auth >= 2:
        verdict = "developing"
    else:
        verdict = "insufficient"

    recs: list[str] = []
    if auth == 0:
        recs.append(
            "Collect a first proctored writing sample (via Bluebook) — "
            "scoring cannot run until at least one authenticated sample exists."
        )
    if auth < 5:
        recs.append(
            f"Collect {5 - auth} more authenticated sample(s) — "
            "the target for reliable comparison is 5-8."
        )
    if word_stats and word_stats.n_below_300 > 0:
        recs.append(
            f"{word_stats.n_below_300} baseline sample(s) are under 300 "
            "words — prefer 300+ word samples for stable style measurement."
        )
    assignments = {s.assignment for s in state.samples if s.assignment}
    if state.sample_count >= 3 and len(assignments) <= 1:
        recs.append(
            "All samples come from one assignment — collect baselines "
            "across different assignments to capture the student's range."
        )
    if not recs:
        recs.append("Baseline is in good shape — no action needed.")

    return ReadinessResponse(
        student_id=student_id,
        sample_count=state.sample_count,
        authenticated_count=auth,
        effective_sample_count=eff,
        purity=state.purity,
        provenance_mix=provenance_mix,
        word_stats=word_stats,
        verdict=verdict,
        recommendations=recs,
    )


# ── Read a single baseline sample's prose text ───────────────────────────────
# The StudentStateResponse exposes only SampleSummary metadata (index,
# assignment, provenance, submitted_at, auth_weight) — not the text itself,
# so the demo UI can stay slim. When the professor wants to read a specific
# sample's writing (to remind themselves of the student's voice, or to
# verify a sample is legitimate before authenticating it), they fetch
# the prose lazily via this endpoint.


@router.get("/students/{student_id}/samples/{index}/text")
def get_sample_text(student_id: str, index: int):
    """
    Return the raw prose of a single baseline sample.

    Returns 404 if the student doesn't exist or the index is out of range.
    Response shape mirrors the SampleSummary metadata so the caller can
    render headers + body in a single round-trip without re-fetching the
    student state.
    """
    state = _repo().get(student_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Student '{student_id}' not found")
    if index < 0 or index >= len(state.samples):
        raise HTTPException(
            status_code=404,
            detail=f"Sample index {index} out of range (student has {len(state.samples)} samples)",
        )
    s = state.samples[index]
    return {
        "student_id": student_id,
        "index": index,
        "assignment": s.assignment,
        "provenance": s.provenance,
        "submitted_at": s.submitted_at,
        "auth_weight": s.auth_weight,
        "word_count": len((s.text or "").split()),
        "char_count": len(s.text or ""),
        "text": s.text or "",
    }


# ── FERPA: student data deletion ──────────────────────────────────────────────


@router.delete("/students/{student_id}", status_code=200)
def delete_student(student_id: str, request: Request):
    """
    Permanently delete all stored data for a student (FERPA right-to-erasure).

    Removes the student profile, all baseline samples, all fidelity scores,
    all adaptive-context manifests, and all instructor corrections associated
    with this student_id.  The deletion is immediate and irreversible — there
    is no soft-delete or recovery path.

    Returns 200 with a confirmation payload on success, 404 if not found.
    Returns 404 also when the SQLite commit fails (no data was removed).

    Intended audience: institution data-compliance officers and LMS admins.
    When GUARD_DESTRUCTIVE=1 (pilot/production mode), requires an
    X-Guard-Token header matching MAINTENANCE_TOKEN. Demo mode is open.
    """
    _require_guard(request)
    remote = getattr(request.client, "host", "unknown") if request.client else "unknown"
    deleted = _repo().delete_student(student_id)
    if not deleted:
        _repo().log_audit(
            action="student_delete", student_id=student_id, actor=remote, result="not_found"
        )
        raise HTTPException(
            status_code=404,
            detail=f"Student '{student_id}' not found — nothing to delete.",
        )
    _repo().log_audit(action="student_delete", student_id=student_id, actor=remote, result="ok")
    return {
        "deleted": True,
        "student_id": student_id,
        "message": (
            f"All data for student '{student_id}' has been permanently removed "
            "(baseline profile, fidelity scores, AI-likelihood scores, "
            "manifests, corrections, stored display name, and audit history). "
            "A single audit entry recording this deletion is retained. "
            "Copies age out of rotating on-disk backups within ~24 hours."
        ),
    }


# ── FERPA: data inventory + audit log ────────────────────────────────────────


@router.get("/students/{student_id}/data-inventory")
def student_data_inventory(student_id: str):
    """
    FERPA data-access response: structured inventory of all data held for a student.

    Returns a categorized breakdown of:
    - Baseline writing samples (count, provenance types, date range)
    - Fidelity / calibration scores
    - Scored submission manifests (by recommendation action)
    - Instructor corrections
    - Audit log entries

    Intended for: student data-access requests, FERPA compliance officers,
    deletion confirmations ("prove everything was purged").
    """
    inv = _repo().student_data_inventory(student_id)
    if inv is None:
        raise HTTPException(status_code=404, detail=f"Student '{student_id}' not found")
    return inv


# ── Formation pathways (ADR-002 — routed through the Repository seam) ─────────
# These handlers depend only on the Repository interface, never on store
# directly. Swapping in a Postgres-backed Repository requires no change here.


@router.get("/students/{student_id}/formation")
def get_formation(student_id: str):
    """Return the student's active (or most recent) formation pathway, or null."""
    repo = get_repository(os.environ.get("ENVIRONMENT", "demo"))
    return {"pathway": repo.get_formation_pathway(student_id)}


@router.post("/students/{student_id}/formation", status_code=201)
def open_formation(student_id: str, body: dict | None = None):
    """
    Open a three-session formation pathway. Idempotent — returns the existing
    open pathway if one is already in progress.

    Optional body: { submission_id, reason }
    """
    body = body or {}
    repo = get_repository(os.environ.get("ENVIRONMENT", "demo"))
    pathway = repo.open_formation_pathway(
        student_id,
        submission_id=body.get("submission_id"),
        reason=body.get("reason"),
    )
    if pathway is None:
        raise HTTPException(status_code=500, detail="Could not open formation pathway")
    return {"pathway": pathway}


@router.post("/students/{student_id}/formation/advance")
def advance_formation(student_id: str):
    """
    Advance the open pathway by one session. On the final session the pathway
    completes and the triggering submission's review flag is cleared.
    Returns 404 if there is no open pathway.
    """
    repo = get_repository(os.environ.get("ENVIRONMENT", "demo"))
    pathway = repo.advance_formation_pathway(student_id)
    if pathway is None:
        raise HTTPException(
            status_code=404,
            detail=f"No open formation pathway for student '{student_id}'.",
        )
    return {"pathway": pathway}


# ── File upload (text extraction) ────────────────────────────────────────────


@router.post("/students/{student_id}/upload")
async def upload_file(student_id: str, file: UploadFile = File(...)):
    """Extract plain text from an uploaded .txt, .docx, or .pdf file."""
    filename = file.filename or "unknown"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    raw = await file.read()

    if ext == "txt":
        text = raw.decode("utf-8", errors="replace")
    elif ext == "docx":
        try:
            from docx import Document

            doc = Document(io.BytesIO(raw))
            text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError as exc:
            raise HTTPException(status_code=500, detail="python-docx not installed") from exc
    elif ext == "pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(raw))
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError as exc:
            raise HTTPException(status_code=500, detail="pypdf not installed") from exc
    else:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '.{ext}'. Use .txt, .docx, or .pdf.",
        )

    word_count = len(text.split())
    return {"text": text, "filename": filename, "word_count": word_count}
