"""Bluebook magic-link launch + exam/session/submission/course CRUD.

Moved verbatim from original/api.py; the exam-session endpoint and the
idempotent-seal/late-tagging behaviour on ``bluebook_record_submission`` were
added here directly (exam-day robustness).
"""

from __future__ import annotations

import sqlite3
import urllib.parse
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request

from .. import principal as principal_mod
from .. import student_auth
from ..schemas import (
    BluebookCreateCourseRequest,
    BluebookCreateExamRequest,
    BluebookRecordSubmissionRequest,
    BluebookSessionResponse,
    BluebookStartSessionRequest,
)
from ._shared import (
    _MAGIC_SESSION_TTL,
    _bluebook_tenant,
    _int_or,
    _render_launch_localstorage,
    _repo,
    _require_staff,
)

router = APIRouter()


# ── Bluebook magic-link launch (no-Canvas fallback) ───────────────────────────
# The offline roster_links.py builds one signed launch token per student. This
# endpoint redeems it: it authenticates the bound student (a short session) AND
# issues a proctor attestation, both server-side, so a magic-link proctored
# sitting lands a `proctored` sample on a real pilot — the same end state as an
# LTI/Canvas exam launch. Mirrors /lti/launch: the credentials are minted here
# and handed to the browser via localStorage, never left in the distributed URL.
# The link carries only a signed, purpose-built launch token (no session token).


@router.get("/bluebook/launch")
def bluebook_magic_launch(request: Request, t: str = ""):
    body = student_auth.verify_launch_token(t)
    if not body:
        raise HTTPException(
            status_code=400,
            detail="This launch link is invalid or has expired. Ask your instructor for a new one.",
        )
    sid = str(body.get("sid") or "")
    tenant = str(body.get("tid") or "")
    exam = str(body.get("exam") or "")
    name = str(body.get("name") or "")
    if not sid:
        raise HTTPException(status_code=400, detail="Launch link is missing its student binding.")

    # Record the LMS-style display name only if the operator opted to include it
    # (roster_links --include-name); links are name-free by default (FERPA).
    if name:
        try:
            _repo().set_display_name(sid, name)
        except Exception:
            pass

    ls = {
        # Authenticates the bound student to the isolation middleware so the
        # proctored write to their own id is permitted on a pilot tenant.
        "original_session_token": student_auth.mint_session(
            sid, name, ttl_seconds=_MAGIC_SESSION_TTL
        ),
        "bluebook_student_id": sid,
        "original_tenant": tenant,
        # Authorizes the `proctored` provenance (see _authorize_provenance) —
        # without it the sitting would be downgraded to 'unverified'.
        "bluebook_proctor_token": student_auth.mint_proctor_attestation(sid, exam),
    }
    _repo().log_audit(
        action="bluebook_magic_launch",
        student_id=sid,
        tenant_id=tenant,
        result="ok",
        details={"exam": exam},
    )
    redirect = "/bluebook/"
    params = {k: v for k, v in {"exam": exam, "candidate": name}.items() if v}
    if params:
        redirect = redirect + "?" + urllib.parse.urlencode(params)
    return _render_launch_localstorage(ls, redirect)


# ── Bluebook examinations (secure-exam layer, tenant-scoped) ──────────────────
# Instructor-created exams persist here. Submissions themselves flow to
# /students/{id}/baseline as proctored samples. Scoping mirrors list_students:
# an authenticated non-super principal sees only its tenant; demo sees "demo".


@router.post("/bluebook/exams", status_code=201)
def bluebook_create_exam(body: BluebookCreateExamRequest, request: Request):
    _require_staff(request)
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="title is required")
    tenant = _bluebook_tenant(request)
    rec = {
        "id": uuid.uuid4().hex[:16],
        "tenant_id": tenant,
        "title": title[:200],
        "course": body.course[:80],
        "duration": _int_or(body.duration, 90),
        "minWords": _int_or(body.minWords, 0),
        "maxWords": _int_or(body.maxWords, 0),
        "prompt": body.prompt[:8000],
        "conditions": body.conditions if isinstance(body.conditions, dict) else {},
        "status": (body.status or "DRAFT").upper()[:20],
    }
    _repo().put_bluebook_exam(rec)
    _repo().log_audit(action="bluebook_exam_create", tenant_id=tenant, details={"title": title})
    rec["submissions"] = 0
    return rec


@router.get("/bluebook/exams")
def bluebook_list_exams(request: Request):
    p = getattr(request.state, "principal", None)
    if p and not p.is_demo and p.role not in principal_mod.SUPER_ROLES:
        exams = _repo().list_bluebook_exams(p.tenant_id)
    elif p and p.is_demo:
        exams = _repo().list_bluebook_exams(principal_mod.DEMO_TENANT)
    else:  # super / operator → all tenants
        exams = _repo().list_bluebook_exams(None)
    return {"exams": exams}


@router.get("/bluebook/exams/{exam_id}")
def bluebook_get_exam(exam_id: str, request: Request):
    rec = _repo().get_bluebook_exam(exam_id)
    if not rec:
        raise HTTPException(status_code=404, detail="exam not found")
    p = getattr(request.state, "principal", None)
    owner = rec.get("tenant_id")
    if p and not p.is_demo and p.role not in principal_mod.SUPER_ROLES and owner != p.tenant_id:
        raise HTTPException(status_code=403, detail="cross-tenant access denied")
    if p and p.is_demo and owner not in (None, principal_mod.DEMO_TENANT):
        raise HTTPException(status_code=403, detail="cross-tenant access denied")
    return rec


def _student_key(body) -> str:
    """The (exam, student) session key: the resolved student id when we have
    one, else a ``cand:``-prefixed candidate label for demo sittings that
    never bound a real student. Truncated to the store's column width."""
    return (body.student_id or (body.candidate and f"cand:{body.candidate}") or "")[:128]


@router.post("/bluebook/exams/{exam_id}/session", response_model=BluebookSessionResponse)
def bluebook_start_session(exam_id: str, body: BluebookStartSessionRequest, request: Request):
    """Begin (or resume) a sitting: the first call pins the server deadline;
    every later call returns the same one, so reopening the tab never
    restarts or pauses the clock (exam-day robustness spec §1)."""
    tenant = _bluebook_tenant(request)
    exam = _repo().get_bluebook_exam(exam_id)
    if exam is None or exam.get("tenant_id") not in (tenant, None):
        raise HTTPException(status_code=404, detail="exam not found")
    duration_seconds = max(60, _int_or(exam.get("duration"), 90) * 60)
    student_key = _student_key(body)
    if not student_key.strip():
        raise HTTPException(status_code=422, detail="student_id or candidate is required")
    s = _repo().get_or_create_bluebook_session(exam_id, student_key, tenant, duration_seconds)
    return BluebookSessionResponse(
        exam_id=exam_id,
        started_at=s["started_at"],
        deadline_at=s["deadline_at"],
        server_now=datetime.now(UTC).isoformat(),
        duration_seconds=duration_seconds,
    )


@router.post("/bluebook/submissions", status_code=201)
def bluebook_record_submission(body: BluebookRecordSubmissionRequest, request: Request):
    """Record one sat examination (the integrity reading for the Results view)."""
    tenant = _bluebook_tenant(request)

    # Idempotent sealing (robustness spec §2): a retried seal with the same
    # client submission_uuid returns the prior row instead of writing again.
    if body.submission_uuid:
        prior = _repo().get_bluebook_submission_by_uuid(body.submission_uuid[:64])
        if prior is not None:
            return {
                "id": prior["id"],
                "status": prior["status"],
                "late": prior.get("late", 0),
                "duplicate": True,
            }

    def _clamp_pct(v):
        n = _int_or(v, None)
        return None if n is None else max(0, min(100, n))

    rec = {
        "id": uuid.uuid4().hex[:16],
        "exam_id": (str(body.exam_id) if body.exam_id else None),
        "tenant_id": tenant,
        "student_id": body.student_id[:128],
        "candidate": body.candidate[:120],
        "exam_title": body.exam_title[:200],
        "course": body.course[:80],
        "word_count": _int_or(body.word_count, 0),
        "time_min": _int_or(body.time_min, 0),
        "stylometric": _clamp_pct(body.stylometric),
        "ai_score": _clamp_pct(body.ai_score),
        "status": (body.status or "SUBMITTED").upper()[:20],
    }
    rec["submission_uuid"] = body.submission_uuid[:64] if body.submission_uuid else None
    # Late tagging: only when this sitting has a server-pinned deadline. No
    # session row (degrade-open client start) -> no late judgment possible.
    rec["late"] = 0
    if rec["exam_id"]:
        student_key = _student_key(body)
        sess = _repo().get_bluebook_session(rec["exam_id"], student_key) if student_key else None
        if sess:
            deadline = datetime.fromisoformat(sess["deadline_at"])
            if datetime.now(UTC) > deadline + timedelta(seconds=300):
                rec["late"] = 1
    try:
        _repo().put_bluebook_submission(rec)
    except Exception as e:
        # A racing replay: two requests carrying the same client submission_uuid
        # can both pass the `prior is None` check above, then race to insert —
        # the loser hits the unique index/constraint on submission_uuid. SQLite
        # raises sqlite3.IntegrityError directly; Postgres (via SQLAlchemy) raises
        # sqlalchemy.exc.IntegrityError. sqlalchemy is imported lazily here
        # (not at module top) so a SQLite-only deployment never pays for
        # importing it just to check an exception type it will never see —
        # get_repository() applies the same lazy-import discipline for the
        # same reason.
        is_uuid_conflict = isinstance(e, sqlite3.IntegrityError)
        if not is_uuid_conflict:
            try:
                from sqlalchemy.exc import IntegrityError as _SAIntegrityError
            except ImportError:
                _SAIntegrityError = ()
            is_uuid_conflict = isinstance(e, _SAIntegrityError)
        if is_uuid_conflict and rec["submission_uuid"]:
            prior = _repo().get_bluebook_submission_by_uuid(rec["submission_uuid"])
            if prior is not None:
                return {
                    "id": prior["id"],
                    "status": prior["status"],
                    "late": prior.get("late", 0),
                    "duplicate": True,
                }
        raise
    _repo().log_audit(
        action="bluebook_submission",
        tenant_id=tenant,
        student_id=rec["student_id"],
        details={"exam_id": rec["exam_id"], "late": rec["late"]},
    )
    return {"id": rec["id"], "status": rec["status"], "late": rec["late"]}


@router.get("/bluebook/submissions")
def bluebook_list_submissions(request: Request):
    p = getattr(request.state, "principal", None)
    if p and not p.is_demo and p.role not in principal_mod.SUPER_ROLES:
        subs = _repo().list_bluebook_submissions(p.tenant_id)
    elif p and p.is_demo:
        subs = _repo().list_bluebook_submissions(principal_mod.DEMO_TENANT)
    else:
        subs = _repo().list_bluebook_submissions(None)
    return {"submissions": subs}


@router.post("/bluebook/courses", status_code=201)
def bluebook_create_course(body: BluebookCreateCourseRequest, request: Request):
    _require_staff(request)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="course name is required")
    tenant = _bluebook_tenant(request)
    rec = {
        "id": uuid.uuid4().hex[:16],
        "tenant_id": tenant,
        "code": body.code[:40],
        "name": name[:160],
        "term": body.term[:60],
        "status": (body.status or "ACTIVE").upper()[:20],
    }
    _repo().put_bluebook_course(rec)
    _repo().log_audit(
        action="bluebook_course_create", tenant_id=tenant, details={"code": rec["code"]}
    )
    return {**rec, "active": rec["status"] == "ACTIVE", "students": 0, "exams": 0}


@router.get("/bluebook/courses")
def bluebook_list_courses(request: Request):
    p = getattr(request.state, "principal", None)
    if p and not p.is_demo and p.role not in principal_mod.SUPER_ROLES:
        courses = _repo().list_bluebook_courses(p.tenant_id)
    elif p and p.is_demo:
        courses = _repo().list_bluebook_courses(principal_mod.DEMO_TENANT)
    else:
        courses = _repo().list_bluebook_courses(None)
    return {"courses": courses}
