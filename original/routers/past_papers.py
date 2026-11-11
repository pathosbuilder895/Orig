"""Past papers a student shares from their Collections account (2026-10 alpha).

A student who has old papers of their own can share them here instead of
emailing them to the teacher. Nothing a student shares is scored, read for
features, or added to their writing baseline on upload: it waits as
``pending`` until a teacher approves or declines it. Approval goes through
the existing baseline-write handler (validation, replay guard, drift gate and
audit unchanged), at the self-upload provenance ``unverified`` -- a shared
paper is not supervised writing, so it never carries supervised trust. Only
approved papers enter the baseline, so only they count toward the
minimum-baseline gate (``min_baseline_samples``).

The student side returns titles and review status only -- never a score,
feature, drift reading or baseline count (#288/#290). A paper the drift gate
kept out after approval is ``held`` for the teacher and shows the student
"pending", since the reason is a score-derived reading.

``baseline_source`` records whether the paper is a whole paper
(``independent``) or a section of a longer one (``split``, with
``parent_title``), so calibration can keep split-derived baselines apart
(scripts/alpha/batch_score_alpha.py reads it from the staff list).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import ValidationError

from .. import principal as principal_mod
from ..schemas import AddSampleRequest
from ..upload_utils import extract_text_from_bytes
from ._shared import _bluebook_tenant, _repo, _require_staff
from .bluebook import _can_touch
from .bluebook_accounts import _require_student
from .students_baseline import add_baseline

router = APIRouter()

RECEIVED = "Received — your teacher will review it."
NOT_AVAILABLE = "Sharing past papers isn't available in this workspace."
MAX_TEXT_CHARS = 200_000  # AddSampleRequest.text's own cap
MIN_WORDS = 20
MAX_TITLE = 200
MAX_PER_DAY = 20
SOURCES = ("independent", "split")
# What the student is shown for each stored status. "held" (the drift gate
# kept an approved paper out) is a score-derived outcome: the student sees
# it as still waiting for the teacher.
_STUDENT_STATUS = {
    "pending": "pending",
    "held": "pending",
    "approved": "approved",
    "declined": "declined",
}


def _has_original(tenant_id: str | None) -> bool:
    return "original" in principal_mod.tenant_products(tenant_id)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _student_view(rec: dict) -> dict:
    return {
        "paper_id": rec["paper_id"],
        "title": rec["title"],
        "status": _STUDENT_STATUS.get(rec["status"], "pending"),
        "shared_at": rec.get("created_at"),
        "is_section": rec.get("baseline_source") == "split",
        "section_of": rec.get("parent_title") or None,
    }


def _own_papers(p) -> list[dict]:
    return [_student_view(r) for r in _repo().list_past_papers(p.tenant_id, p.user_id)]


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


# ── Student ───────────────────────────────────────────────────────────────────


@router.get("/bluebook/me/papers")
def my_past_papers(request: Request):
    """The signed-in student's own shared papers: title and review status only."""
    p = _require_student(request)
    return {"enabled": _has_original(p.tenant_id), "papers": _own_papers(p)}


@router.post("/bluebook/me/papers", status_code=201)
def share_past_paper(
    request: Request,
    file: UploadFile | None = File(None),
    text: str = Form(""),
    title: str = Form(""),
    is_section: str = Form(""),
    parent_title: str = Form(""),
):
    """Share one past paper (a PDF, DOCX or TXT file, or pasted text) for the
    teacher to review. Stored as pending; never scored."""
    p = _require_student(request)
    if not _has_original(p.tenant_id):
        raise HTTPException(status_code=403, detail=NOT_AVAILABLE)

    pasted = (text or "").strip()
    filename = None
    if file is not None and file.filename:
        if pasted:
            raise HTTPException(
                status_code=422, detail="Choose a file or paste the text, not both."
            )
        filename = file.filename[:200]
        raw = file.file.read()
        try:
            body = extract_text_from_bytes(raw, filename)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="We could not read that file. Use a PDF, DOCX or TXT file, or paste the text.",
            ) from None
        body = body.strip()
    else:
        body = pasted
    if not body:
        raise HTTPException(status_code=422, detail="Add a file or paste the text of your paper.")
    if len(body) > MAX_TEXT_CHARS:
        raise HTTPException(status_code=413, detail="This paper is too long to share here.")
    words = len(body.split())
    if words < MIN_WORDS:
        raise HTTPException(
            status_code=422, detail=f"This paper is too short. Share at least {MIN_WORDS} words."
        )

    section = _truthy(is_section)
    parent = (parent_title or "").strip()[:MAX_TITLE]
    if section and not parent:
        raise HTTPException(
            status_code=422, detail="Name the longer paper this section comes from."
        )
    label = (title or "").strip()[:MAX_TITLE]
    if not label:
        label = (filename.rsplit(".", 1)[0] if filename else "") or "Untitled paper"

    since = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    if _repo().count_past_papers_since(p.user_id, since) >= MAX_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail="You have shared a lot of papers today. Please try again tomorrow.",
        )
    digest = _sha(body)
    if any(_sha(r["text"]) == digest for r in _repo().list_past_papers(p.tenant_id, p.user_id)):
        raise HTTPException(status_code=409, detail="You have already shared this paper.")

    rec = {
        "paper_id": uuid.uuid4().hex[:16],
        "tenant_id": p.tenant_id,
        "student_id": p.user_id,
        "title": label,
        "text": body,
        "word_count": words,
        "filename": filename,
        "baseline_source": "split" if section else "independent",
        "parent_title": parent if section else None,
        "status": "pending",
    }
    _repo().put_past_paper(rec)
    _repo().log_audit(
        action="past_paper_shared",
        student_id=p.user_id,
        tenant_id=p.tenant_id,
        actor=p.user_id,
        details={"paper_id": rec["paper_id"], "baseline_source": rec["baseline_source"]},
    )
    return {"message": RECEIVED, "papers": _own_papers(p)}


# ── Teacher ───────────────────────────────────────────────────────────────────


def _staff_view(rec: dict, names: dict[str, dict]) -> dict:
    who = names.get(rec["student_id"]) or {}
    return {
        "paper_id": rec["paper_id"],
        "student_id": rec["student_id"],
        "student": who.get("name") or who.get("email") or "",
        "title": rec["title"],
        "word_count": rec["word_count"],
        "filename": rec.get("filename"),
        "baseline_source": rec.get("baseline_source") or "independent",
        "parent_title": rec.get("parent_title"),
        "status": rec["status"],
        "shared_at": rec.get("created_at"),
        "reviewed_at": rec.get("reviewed_at"),
        "text_sha256": _sha(rec["text"]),
    }


def _names(rows: list[dict]) -> dict[str, dict]:
    ids = sorted({r["student_id"] for r in rows})
    return {u["user_id"]: u for u in _repo().list_users_by_ids(ids)} if ids else {}


def _owned_paper(paper_id: str, request: Request) -> dict:
    _require_staff(request)
    rec = _repo().get_past_paper(paper_id)
    if rec is None or not _can_touch(request, rec.get("tenant_id")):
        raise HTTPException(status_code=404, detail="paper not found")
    # The student must belong to the paper's own workspace (a scoped id),
    # and be one the caller may act on.
    if principal_mod.tenant_of(rec["student_id"]) != rec["tenant_id"]:
        raise HTTPException(status_code=404, detail="paper not found")
    try:
        principal_mod.assert_student_access(request.state.principal, rec["student_id"])
    except principal_mod.TenantAccessError:
        raise HTTPException(status_code=404, detail="paper not found") from None
    if not _has_original(rec["tenant_id"]):
        raise HTTPException(status_code=403, detail=NOT_AVAILABLE)
    return rec


def _actor(request: Request) -> str:
    return getattr(request.state.principal, "user_id", "") or ""


@router.get("/bluebook/past-papers")
def list_shared_papers(request: Request, status: str = "", student_id: str = ""):
    """Every paper students in this workspace have shared, newest first."""
    _require_staff(request)
    tenant = _bluebook_tenant(request)
    rows = _repo().list_past_papers(tenant, student_id or None)
    if status:
        rows = [r for r in rows if r["status"] == status]
    names = _names(rows)
    return {"papers": [_staff_view(r, names) for r in rows]}


@router.get("/bluebook/past-papers/{paper_id}")
def read_shared_paper(paper_id: str, request: Request):
    """One shared paper with its text, for the teacher to read before deciding."""
    rec = _owned_paper(paper_id, request)
    return {**_staff_view(rec, _names([rec])), "text": rec["text"]}


@router.post("/bluebook/past-papers/{paper_id}/approve")
def approve_shared_paper(paper_id: str, request: Request):
    """Add the paper to the student's baseline (as a self-upload)."""
    rec = _owned_paper(paper_id, request)
    if rec["status"] == "approved":
        return {"paper_id": paper_id, "status": "approved"}
    if rec["status"] == "declined":
        raise HTTPException(status_code=409, detail="This paper was declined.")
    created = str(rec.get("created_at") or "")[:10]
    try:
        req = AddSampleRequest(
            text=rec["text"],
            provenance="unverified",
            assignment=rec["title"],
            submitted_at=created,
            submission_uuid=f"past_paper_{rec['paper_id']}",
        )
    except ValidationError:
        raise HTTPException(status_code=422, detail="This paper is too long to add.") from None
    status = "approved"
    try:
        add_baseline(rec["student_id"], req, request)
    except HTTPException as exc:
        if exc.status_code not in (202, 409):  # drift gate: hold for review
            raise
        status = "held"
    _repo().set_past_paper_status(paper_id, status, _actor(request))
    _repo().log_audit(
        action="past_paper_approve",
        student_id=rec["student_id"],
        tenant_id=rec["tenant_id"],
        actor=_actor(request),
        result=status,
        details={"paper_id": paper_id, "baseline_source": rec.get("baseline_source")},
    )
    return {"paper_id": paper_id, "status": status}


@router.post("/bluebook/past-papers/{paper_id}/decline")
def decline_shared_paper(paper_id: str, request: Request):
    """Leave the paper out of the baseline."""
    rec = _owned_paper(paper_id, request)
    if rec["status"] == "approved":
        raise HTTPException(
            status_code=409,
            detail="This paper is already in the baseline. Remove it from the student's reference papers instead.",
        )
    _repo().set_past_paper_status(paper_id, "declined", _actor(request))
    _repo().log_audit(
        action="past_paper_decline",
        student_id=rec["student_id"],
        tenant_id=rec["tenant_id"],
        actor=_actor(request),
        details={"paper_id": paper_id},
    )
    return {"paper_id": paper_id, "status": "declined"}
