"""Student roster and per-student read surfaces.

Roster listing, student state, baseline readiness, single-sample prose, FERPA
deletion + data inventory, formation pathways, and single-file text
extraction. Moved verbatim from original/api.py.

Baseline ingestion lives in students_baseline.py and scoring in
students_scoring.py — same route group, split only for file size.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from .. import principal as principal_mod
from .. import student_auth
from ..approved_papers import approved_submission_ids, count_approved, gate_sources, sample_sources
from ..features.matter import without_page_breaks
from ..repository import get_repository
from ..schemas import (
    BaselineWordStats,
    ReadinessResponse,
    SampleSummary,
    StudentStateResponse,
    WriterCreateRequest,
)
from ..upload_utils import ExtractorUnavailableError, extract_text_from_bytes
from ._shared import (
    _bluebook_tenant,
    _repo,
    _require_guard,
    _require_staff,
    drift_gate_advisory,
    min_baseline_samples,
)

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


@router.post("/students", status_code=201)
def create_writer(body: WriterCreateRequest, request: Request):
    """Add a writer by name: no course, email, invite or account.

    For a writer who sends papers by email. The id is minted in the caller's
    own tenant by the rule every student id follows
    (``student_auth.derive_student_id``: ``"{tenant}:{16 hex}"``), keyed on
    a random value instead of an email, so nothing in a request can choose or
    widen the tenant. The writer is then what a roster add makes for a tenant
    with Original (an empty profile plus a stored name), so every Original
    page treats them as a student, and ``DELETE /students/{id}`` erases them.
    Names are not deduplicated: two people can share one.

    The open fictional demo (no sign-in, never a real deploy) may add a
    writer anonymously, into the demo tenant, as it may use its other write
    routes; on a real deploy only a signed-in staff account can.

    ``set_display_name`` logs and swallows a write failure, so the name is
    read back: a writer whose name did not save is erased again and the
    caller gets a 503, never a 201 for a nameless writer.
    """
    staff = _require_staff(request)
    tenant = _bluebook_tenant(request)
    if "original" not in principal_mod.tenant_products(tenant):
        raise HTTPException(
            status_code=403, detail="This workspace's plan does not include Original."
        )
    # An empty tenant would slugify to "default"; a tenant that is not its
    # own slug would mint an id outside the caller's tenant. Refuse both.
    if not tenant or student_auth.slugify(tenant) != tenant:
        raise HTTPException(
            status_code=400, detail="Your account has no workspace to add a writer to."
        )
    repo = _repo()
    actor = staff.user_id if not staff.is_demo else "demo"
    sid = student_auth.derive_student_id(tenant, secrets.token_hex(16))
    while repo.get(sid) is not None:
        sid = student_auth.derive_student_id(tenant, secrets.token_hex(16))
    repo.get_or_create(sid)
    repo.set_display_name(sid, body.name)
    if repo.get_display_name(sid) != body.name:
        repo.delete_student(sid)
        repo.log_audit(
            action="writer_create", student_id=sid, tenant_id=tenant, actor=actor, result="failed"
        )
        raise HTTPException(
            status_code=503,
            detail="The writer could not be saved just now. Nothing was added. Try again.",
        )
    # The name lives in student_names only, never in the audit row.
    repo.log_audit(
        action="writer_create", student_id=sid, tenant_id=tenant, actor=actor, result="ok"
    )
    return {"student_id": sid, "name": body.name}


# ── Student state ─────────────────────────────────────────────────────────────

# How each sample got into the baseline, and so whether it is an approved
# past paper (rule B), is defined once in original/approved_papers.py. The
# old private names stay importable for callers that used them.
_approved_submission_ids = approved_submission_ids
_sample_sources = sample_sources


@router.get("/students/{student_id}", response_model=StudentStateResponse)
def get_student(student_id: str, request: Request):
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

    # The route's access rule lets a student read their own record; the
    # derived source is staff wording, so a student gets "unknown" throughout
    # and no lookup runs on their behalf.
    principal = getattr(request.state, "principal", None)
    if principal is not None and principal.role == "student":
        sources = ["unknown"] * len(state.samples)
    else:
        sources = _sample_sources(student_id, state.samples)
    samples_out = [
        SampleSummary(
            index=i,
            assignment=s.assignment,
            provenance=s.provenance,
            submitted_at=s.submitted_at,
            auth_weight=s.auth_weight,
            source=sources[i],
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
# one call, with plain-language recommendations. Verdict thresholds: ready at
# MIN_BASELINE_SAMPLES approved papers (3 by default, rule B in
# original/approved_papers.py), the minimum the score endpoint accepts;
# building with something on file but fewer approved papers; needs more with
# nothing on file (the score endpoint 422s below the floor). 5 is still where
# scoring confidence saturates (quantum/scoring.py), and the recommendations
# still suggest 5 to 8.


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
    # Approved papers (rule B, original/approved_papers.py): a trusted
    # provenance, or a shared paper / take-home sitting a teacher approved.
    # A student's own self-upload is on file and counted in
    # authenticated_count, but it does not bring the student to the floor.
    approved = count_approved(state.samples, gate_sources(student_id, state.samples))
    floor = min_baseline_samples()
    # Ready at the floor the score route enforces (3 approved papers by
    # default, MIN_BASELINE_SAMPLES): the 2026-11 alpha builds every baseline
    # from exactly three. It used to need 5 (and an effective count of 3), so
    # every alpha reading said "inconclusive". Building: some papers on file,
    # not yet enough approved ones to compare. Needs more: none.
    if approved >= floor:
        verdict = "ready"
    elif auth >= 1:
        verdict = "developing"
    else:
        verdict = "insufficient"

    recs: list[str] = []
    if auth > 0 and approved < floor:
        recs.append(
            f"Original will not compare new writing until this student has at least "
            f"{floor} approved baseline papers; this student has {approved}."
        )
    if auth == 0:
        recs.append(
            "Collect a first proctored writing sample (via Collections) — "
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
        approved_count=approved,
        effective_sample_count=eff,
        purity=state.purity,
        provenance_mix=provenance_mix,
        word_stats=word_stats,
        verdict=verdict,
        recommendations=recs,
        drift_gate="advisory" if drift_gate_advisory() else "hold",
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
        "char_count": len(without_page_breaks(s.text or "")),  # page markers do not count
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
    # Who acted, never where from: the audit log holds no network addresses
    # (the privacy policy says so). The staff account on a real deploy; the
    # anonymous demo principal off one.
    p = getattr(request.state, "principal", None)
    actor = (p.user_id if p is not None and not p.is_demo else None) or "demo"
    deleted = _repo().delete_student(student_id)
    if not deleted:
        _repo().log_audit(
            action="student_delete", student_id=student_id, actor=actor, result="not_found"
        )
        raise HTTPException(
            status_code=404,
            detail=f"Student '{student_id}' not found — nothing to delete.",
        )
    _repo().log_audit(action="student_delete", student_id=student_id, actor=actor, result="ok")
    # The CHARACTERISTIC_WEIGHTS=shadow pool cache (original/quantum/
    # impostor_cache.py) is keyed by tenant and can outlive an erased
    # student by up to TTL_SECONDS otherwise — every peer's shadow preview
    # would keep including the deleted student until the cache expired on
    # its own.
    from ..quantum import impostor_cache

    impostor_cache.invalidate(student_id)
    return {
        "deleted": True,
        "student_id": student_id,
        "message": (
            f"All data for student '{student_id}' has been permanently removed "
            "(baseline profile, fidelity scores, AI-likelihood scores, "
            "manifests, corrections, stored display name, and audit history). "
            "A single audit entry recording this deletion is retained. "
            "Copies remain in encrypted backups until those backups expire."
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
    repo = get_repository()
    return {"pathway": repo.get_formation_pathway(student_id)}


@router.post("/students/{student_id}/formation", status_code=201)
def open_formation(student_id: str, body: dict | None = None):
    """
    Open a three-session formation pathway. Idempotent — returns the existing
    open pathway if one is already in progress.

    Optional body: { submission_id, reason }
    """
    body = body or {}
    repo = get_repository()
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
    repo = get_repository()
    pathway = repo.advance_formation_pathway(student_id)
    if pathway is None:
        raise HTTPException(
            status_code=404,
            detail=f"No open formation pathway for student '{student_id}'.",
        )
    return {"pathway": pathway}


# ── File upload (text extraction) ────────────────────────────────────────────


@router.post("/students/{student_id}/upload")
def upload_file(student_id: str, file: UploadFile = File(...)):
    """Extract plain text from an uploaded .txt, .docx, or .pdf file.

    Plain ``def``, not ``async def`` (T-09): the .docx (python-docx) and
    .pdf (pypdf) branches do real CPU-bound parsing inline — python-docx
    builds a full DOM, pypdf's extract_text() walks the content stream page
    by page — and doing that inside an async handler blocks the whole
    event loop for the duration, which stalls every other in-flight
    request, including a live exam's heartbeat polling. FastAPI dispatches
    a plain ``def`` route to its threadpool automatically, so this one
    change fixes all three branches (.txt included) with no other code
    change — same fix already applied to the sibling upload routes,
    ``import_turnitin_csv`` and ``upload_baseline_batch``. ``file.file`` is
    UploadFile's underlying sync SpooledTemporaryFile, same as those two.

    The text goes into a box the teacher sees and edits. A PDF's comes back
    without its page markers and tag (``matter.without_page_breaks``):
    exactly the text this route returned before markers were kept, so the
    tag does not show in the box or count as a word there. A PDF analysed
    from the box is therefore measured like a paste, with no page-based
    rules; the stored-paper upload routes keep the markers. A .docx keeps
    its page markers (one alone on its line, which the box's word count
    skips): the parts list reads a title page from the break after it.
    """
    filename = file.filename or "unknown"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    raw = file.file.read()

    if ext not in ("txt", "docx", "pdf"):
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '.{ext}'. Use .txt, .docx, or .pdf.",
        )
    try:
        text = extract_text_from_bytes(raw, f"upload.{ext}")
    except ExtractorUnavailableError as exc:
        raise HTTPException(status_code=500, detail=f"{exc.package} not installed") from exc
    except ValueError as exc:  # corrupt file: the caller's input
        raise HTTPException(status_code=422, detail="This file could not be read.") from exc

    if ext == "pdf":
        text = without_page_breaks(text)
    word_count = len(text.split())
    return {"text": text, "filename": filename, "word_count": word_count}
