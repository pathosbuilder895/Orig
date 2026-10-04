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
from fastapi.responses import Response

from .. import bluebook_rules as rules
from .. import principal as principal_mod
from .. import student_auth
from ..schemas import (
    BluebookCreateCourseRequest,
    BluebookCreateExamRequest,
    BluebookRecordSubmissionRequest,
    BluebookSessionResponse,
    BluebookStartSessionRequest,
    BluebookUpdateCourseRequest,
    BluebookUpdateExamRequest,
    SubmissionFeedbackRequest,
)
from ._shared import (
    _MAGIC_SESSION_TTL,
    _bluebook_tenant,
    _int_or,
    _launch_products,
    _render_launch_localstorage,
    _repo,
    _require_staff,
    _require_student_session,
)

router = APIRouter()


# ── Shared helpers (self-serve, 2026-09) ──────────────────────────────────────


def _list_scope(request: Request) -> str | None:
    """Tenant filter for staff list routes: own tenant, the demo tenant for
    the anonymous sandbox, or None (all tenants) for operators."""
    p = getattr(request.state, "principal", None)
    if p and not p.is_demo and p.role not in principal_mod.SUPER_ROLES:
        return p.tenant_id
    if p and p.is_demo:
        return principal_mod.DEMO_TENANT
    return None


def _can_touch(request: Request, owner: str | None) -> bool:
    p = getattr(request.state, "principal", None)
    if p is None:
        return False
    if p.is_demo:
        return owner in (None, principal_mod.DEMO_TENANT)
    return p.role in principal_mod.SUPER_ROLES or owner == p.tenant_id


def _owned_exam(exam_id: str, request: Request) -> dict:
    """The exam, if the staff caller may manage it; 404 otherwise (a
    cross-tenant id is indistinguishable from a missing one)."""
    rec = _repo().get_bluebook_exam(exam_id)
    if rec is None or not _can_touch(request, rec.get("tenant_id")):
        raise HTTPException(status_code=404, detail="exam not found")
    return rec


def _owned_course(course_id: str, request: Request) -> dict:
    rec = _repo().get_bluebook_course(course_id)
    if rec is None or not _can_touch(request, rec.get("tenant_id")):
        raise HTTPException(status_code=404, detail="course not found")
    return rec


def _self_serve(tenant: str) -> bool:
    return rules.is_self_serve(_repo().get_tenant(tenant))


def _window(opens_raw, closes_raw) -> tuple[str | None, str | None]:
    """Validate and normalise an exam window to UTC ISO strings."""
    try:
        opens = rules.parse_instant(opens_raw)
        closes = rules.parse_instant(closes_raw)
    except ValueError:
        raise HTTPException(
            status_code=422, detail="opens_at/closes_at must be ISO-8601 timestamps"
        ) from None
    if opens is not None and closes is not None and closes <= opens:
        raise HTTPException(status_code=422, detail="closes_at must be after opens_at")
    return (
        opens.isoformat() if opens is not None else None,
        closes.isoformat() if closes is not None else None,
    )


def _questions(raw) -> list[str]:
    try:
        return rules.clean_questions(raw)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None


def _shape(rec: dict) -> dict:
    return rules.shape_for_products(rec, principal_mod.tenant_products(rec.get("tenant_id")))


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
    exam_id = str(body.get("eid") or "")
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
        "original_products": _launch_products(tenant),
    }
    # A link bound to a stored exam on a course enrols the student on that
    # course, so the student routes (/bluebook/me/exams/...) let them load it.
    # The token is signed by the operator for exactly this student and exam.
    if exam_id:
        stored = _repo().get_bluebook_exam(exam_id)
        if stored and stored.get("tenant_id") == tenant and stored.get("course_id"):
            _repo().put_enrollment(stored["course_id"], sid, tenant)
    _repo().log_audit(
        action="bluebook_magic_launch",
        student_id=sid,
        tenant_id=tenant,
        result="ok",
        details={"exam": exam, "exam_id": exam_id},
    )
    redirect = "/bluebook/"
    # exam_id lets the SPA load the teacher's actual exam (prompt, timing,
    # conditions) instead of the built-in sample; the title alone could not.
    params = {k: v for k, v in {"exam": exam, "exam_id": exam_id, "candidate": name}.items() if v}
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
    if body.course_id:
        course = _repo().get_bluebook_course(body.course_id)
        if course is None or course.get("tenant_id") != tenant:
            raise HTTPException(status_code=422, detail="course_id is not one of your courses")
    opens_at, closes_at = _window(body.opens_at, body.closes_at)
    questions = _questions(body.questions)
    if _self_serve(tenant) and len(_repo().list_bluebook_exams(tenant)) >= rules.MAX_EXAMS:
        raise HTTPException(
            status_code=403,
            detail=f"Free workspaces can hold {rules.MAX_EXAMS} exams. Delete one to add another.",
        )
    rec = {
        "id": uuid.uuid4().hex[:16],
        "tenant_id": tenant,
        "course_id": body.course_id or None,
        "opens_at": opens_at,
        "closes_at": closes_at,
        "title": title[:200],
        "course": body.course[:80],
        "duration": _int_or(body.duration, 90),
        "minWords": _int_or(body.minWords, 0),
        "maxWords": _int_or(body.maxWords, 0),
        "prompt": (rules.joined_prompt(questions) if questions else body.prompt)[:8000],
        "questions": questions,
        "conditions": body.conditions if isinstance(body.conditions, dict) else {},
        "status": (body.status or "DRAFT").upper()[:20],
    }
    _repo().put_bluebook_exam(rec)
    _repo().log_audit(action="bluebook_exam_create", tenant_id=tenant, details={"title": title})
    rec["submissions"] = 0
    return rec


@router.get("/bluebook/exams")
def bluebook_list_exams(request: Request):
    # Staff only: exam prompts must not reach students before they sit.
    # Students read their exams through /bluebook/me/exams.
    _require_staff(request)
    scope = _list_scope(request)  # None for operators: all tenants
    exams = _repo().list_bluebook_exams(scope)
    counts = _repo().bluebook_submission_counts_by_exam(scope)
    for e in exams:
        e["submissions"] = counts.get(e["id"], 0)
    return {"exams": exams}


@router.get("/bluebook/exams/{exam_id}")
def bluebook_get_exam(exam_id: str, request: Request):
    # Staff only: exam prompts must not reach students before they sit.
    # Students read their exams through /bluebook/me/exams.
    _require_staff(request)
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
    restarts or pauses the clock (exam-day robustness spec §1).

    Callers: either the signed-in student starting/resuming their own
    sitting (session student id must match ``body.student_id``, when
    given), or staff. Previously this route had no auth check at all: an
    anonymous caller could pin the server-side deadline for an arbitrary
    student_id on any exam under the demo tenant (T-65) — same class of
    hole as ``bluebook_record_submission`` below, same fix shape.
    """
    try:
        _require_staff(request)
    except HTTPException:
        session = _require_student_session(request)
        if body.student_id and session.get("sid") != body.student_id:
            raise HTTPException(
                status_code=403,
                detail="Session does not match the requested student_id.",
            ) from None
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
    """Record one sat examination (the integrity reading for the Results view).

    Callers: either the signed-in student sealing their own sitting (session
    student id must match ``body.student_id``), or staff. Previously this
    route had no auth check at all — any caller could write a submission
    naming an arbitrary student_id/candidate, including a classmate's.
    """
    try:
        _require_staff(request)
    except HTTPException:
        session = _require_student_session(request)
        if body.student_id and session.get("sid") != body.student_id:
            raise HTTPException(
                status_code=403,
                detail="Session does not match the submission's student_id.",
            ) from None
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

    try:
        warnings = rules.clean_warnings(body.warnings)
        answers = rules.clean_answers(body.answers)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    text = body.text if body.text is not None else (rules.joined_answers(answers) or None)
    if text is not None and len(text) > rules.MAX_TEXT_CHARS:
        raise HTTPException(status_code=413, detail="Submission text is too long.")
    if sum(len(a) for a in answers) > rules.MAX_TEXT_CHARS:
        raise HTTPException(status_code=413, detail="Submission text is too long.")
    if (
        _self_serve(tenant)
        and _repo().count_bluebook_submissions_since(
            tenant, rules.month_start(rules.now_utc()).isoformat()
        )
        >= rules.MAX_SUBMISSIONS_PER_MONTH
    ):
        raise HTTPException(
            status_code=403,
            detail="This workspace has reached its monthly submission limit.",
        )
    # A tenant without Original never stores Original's readings, whatever a
    # client sends: self-serve workspaces stay out of stylometric profiling.
    has_original = "original" in principal_mod.tenant_products(tenant)
    # A client that omits the exam's title or course (a launch link with only
    # an id, an older client) still gets a readable row: take them from the
    # stored exam when it belongs to this workspace.
    stored_exam = _repo().get_bluebook_exam(str(body.exam_id)) if body.exam_id else None
    if stored_exam and stored_exam.get("tenant_id") != tenant:
        stored_exam = None

    rec = {
        "id": uuid.uuid4().hex[:16],
        "exam_id": (str(body.exam_id) if body.exam_id else None),
        "tenant_id": tenant,
        "text": text,
        "answers": answers,
        "warnings": warnings,
        "student_id": body.student_id[:128],
        "candidate": body.candidate[:120],
        "exam_title": (body.exam_title or (stored_exam or {}).get("title") or "")[:200],
        "course": (body.course or (stored_exam or {}).get("course") or "")[:80],
        "word_count": _int_or(body.word_count, 0),
        "time_min": _int_or(body.time_min, 0),
        "stylometric": _clamp_pct(body.stylometric) if has_original else None,
        "ai_score": _clamp_pct(body.ai_score) if has_original else None,
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
        details={
            "exam_id": rec["exam_id"],
            "late": rec["late"],
            "warnings": len(warnings),
        },
    )
    return {"id": rec["id"], "status": rec["status"], "late": rec["late"]}


@router.get("/bluebook/submissions")
def bluebook_list_submissions(request: Request):
    # Staff only: a signed-in student previously got the whole institution's
    # submissions and integrity scores from this list.
    _require_staff(request)
    subs = _repo().list_bluebook_submissions(_list_scope(request))
    return {"submissions": [_shape(s) for s in subs]}


@router.get("/bluebook/submissions/{submission_id}")
def bluebook_get_submission(submission_id: str, request: Request):
    """One submission with its sealed text and warnings (staff, own tenant)."""
    _require_staff(request)
    rec = _repo().get_bluebook_submission(submission_id)
    if rec is None or not _can_touch(request, rec.get("tenant_id")):
        raise HTTPException(status_code=404, detail="submission not found")
    exam = _repo().get_bluebook_exam(rec["exam_id"]) if rec.get("exam_id") else None
    rec["questions"] = (exam or {}).get("questions") or []
    return _shape(rec)


@router.patch("/bluebook/submissions/{submission_id}/feedback")
def bluebook_submission_feedback(
    submission_id: str, body: SubmissionFeedbackRequest, request: Request
):
    """Record a teacher's mark and comment. Students see them only after
    the exam's results are released (POST /bluebook/exams/{id}/release)."""
    staff = _require_staff(request)
    rec = _repo().get_bluebook_submission(submission_id)
    if rec is None or not _can_touch(request, rec.get("tenant_id")):
        raise HTTPException(status_code=404, detail="submission not found")
    mark = (body.mark or "").strip()
    feedback = (body.feedback or "").strip()
    if len(mark) > rules.MAX_MARK_CHARS:
        raise HTTPException(
            status_code=422, detail=f"mark must be at most {rules.MAX_MARK_CHARS} characters"
        )
    if len(feedback) > rules.MAX_FEEDBACK_CHARS:
        raise HTTPException(status_code=422, detail="feedback is too long")
    _repo().set_bluebook_submission_feedback(
        submission_id, mark or None, feedback or None, staff.user_id
    )
    _repo().log_audit(
        action="bluebook_feedback",
        tenant_id=rec.get("tenant_id"),
        student_id=rec.get("student_id") or None,
        actor=staff.user_id,
        details={"submission_id": submission_id, "marked": bool(mark), "commented": bool(feedback)},
    )
    return _shape(_repo().get_bluebook_submission(submission_id))


def _set_release(exam_id: str, request: Request, released: bool) -> dict:
    staff = _require_staff(request)
    rec = _owned_exam(exam_id, request)
    rec["results_released_at"] = rules.now_utc().isoformat() if released else None
    _repo().put_bluebook_exam(rec)
    _repo().log_audit(
        action="bluebook_results_release" if released else "bluebook_results_unrelease",
        tenant_id=rec.get("tenant_id"),
        actor=staff.user_id,
        details={"exam_id": exam_id},
    )
    return _repo().get_bluebook_exam(exam_id)


@router.post("/bluebook/exams/{exam_id}/release")
def bluebook_release_results(exam_id: str, request: Request):
    """Show students their marks and feedback for this exam."""
    return _set_release(exam_id, request, True)


@router.post("/bluebook/exams/{exam_id}/unrelease")
def bluebook_unrelease_results(exam_id: str, request: Request):
    """Hide marks and feedback from students again."""
    return _set_release(exam_id, request, False)


@router.get("/bluebook/exams/{exam_id}/export")
def bluebook_export_exam(exam_id: str, request: Request):
    """CSV of every submission for one exam, text included (staff)."""
    _require_staff(request)
    exam = _owned_exam(exam_id, request)
    subs = _repo().list_bluebook_submissions_for_exam(exam_id)
    ids = [s["student_id"] for s in subs if s.get("student_id")]
    people = {u["user_id"]: u for u in _repo().list_users_by_ids(ids)}
    body = rules.submissions_csv(subs, people)
    _repo().log_audit(
        action="bluebook_export",
        tenant_id=exam.get("tenant_id"),
        details={"exam_id": exam_id, "rows": len(subs)},
    )
    safe = "".join(c if c.isalnum() else "-" for c in (exam.get("title") or "exam"))[:60]
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe or "exam"}.csv"'},
    )


@router.patch("/bluebook/exams/{exam_id}")
def bluebook_update_exam(exam_id: str, body: BluebookUpdateExamRequest, request: Request):
    """Partial update. Only fields present in the body change; null clears
    course_id / opens_at / closes_at."""
    _require_staff(request)
    rec = _owned_exam(exam_id, request)
    sent = body.model_fields_set
    if "title" in sent:
        title = (body.title or "").strip()
        if not title:
            raise HTTPException(status_code=422, detail="title is required")
        rec["title"] = title[:200]
    if "course" in sent:
        rec["course"] = (body.course or "")[:80]
    if "duration" in sent:
        rec["duration"] = _int_or(body.duration, 90)
    if "minWords" in sent:
        rec["minWords"] = _int_or(body.minWords, 0)
    if "maxWords" in sent:
        rec["maxWords"] = _int_or(body.maxWords, 0)
    if "prompt" in sent:
        rec["prompt"] = (body.prompt or "")[:8000]
        rec["questions"] = []
    if "questions" in sent:
        rec["questions"] = _questions(body.questions)
        rec["prompt"] = rules.joined_prompt(rec["questions"])[:8000]
    if "conditions" in sent:
        rec["conditions"] = body.conditions if isinstance(body.conditions, dict) else {}
    if "status" in sent:
        rec["status"] = (body.status or "DRAFT").upper()[:20]
    if "course_id" in sent:
        if body.course_id:
            course = _repo().get_bluebook_course(body.course_id)
            if course is None or course.get("tenant_id") != rec.get("tenant_id"):
                raise HTTPException(status_code=422, detail="course_id is not one of your courses")
        rec["course_id"] = body.course_id or None
    if "opens_at" in sent or "closes_at" in sent:
        rec["opens_at"], rec["closes_at"] = _window(
            body.opens_at if "opens_at" in sent else rec.get("opens_at"),
            body.closes_at if "closes_at" in sent else rec.get("closes_at"),
        )
    _repo().put_bluebook_exam(rec)
    _repo().log_audit(
        action="bluebook_exam_update",
        tenant_id=rec.get("tenant_id"),
        details={"exam_id": exam_id, "fields": sorted(sent)},
    )
    return _repo().get_bluebook_exam(exam_id)


@router.delete("/bluebook/exams/{exam_id}")
def bluebook_delete_exam(exam_id: str, request: Request):
    """Delete an exam nobody has sat yet. With submissions it is a 409:
    close or archive it instead, so no student's work is orphaned."""
    _require_staff(request)
    rec = _owned_exam(exam_id, request)
    if _repo().list_bluebook_submissions_for_exam(exam_id):
        raise HTTPException(
            status_code=409,
            detail="This exam has submissions. Set its status to CLOSED instead.",
        )
    _repo().delete_bluebook_exam(exam_id)
    _repo().log_audit(
        action="bluebook_exam_delete", tenant_id=rec.get("tenant_id"), details={"exam_id": exam_id}
    )
    return {"deleted": exam_id}


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
    _require_staff(request)
    scope = _list_scope(request)
    courses = _repo().list_bluebook_courses(scope)
    students = _repo().enrollment_counts_by_course(scope)
    exams: dict[str, int] = {}
    for e in _repo().list_bluebook_exams(scope):
        if e.get("course_id"):
            exams[e["course_id"]] = exams.get(e["course_id"], 0) + 1
    for c in courses:
        c["students"] = students.get(c["id"], 0)
        c["exams"] = exams.get(c["id"], 0)
    return {"courses": courses}


@router.patch("/bluebook/courses/{course_id}")
def bluebook_update_course(course_id: str, body: BluebookUpdateCourseRequest, request: Request):
    _require_staff(request)
    rec = _owned_course(course_id, request)
    sent = body.model_fields_set
    if "name" in sent:
        name = (body.name or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="course name is required")
        rec["name"] = name[:160]
    if "code" in sent:
        rec["code"] = (body.code or "")[:40]
    if "term" in sent:
        rec["term"] = (body.term or "")[:60]
    if "status" in sent:
        rec["status"] = (body.status or "ACTIVE").upper()[:20]
    _repo().put_bluebook_course(rec)
    _repo().log_audit(
        action="bluebook_course_update",
        tenant_id=rec.get("tenant_id"),
        details={"course_id": course_id, "fields": sorted(sent)},
    )
    return _repo().get_bluebook_course(course_id)


@router.delete("/bluebook/courses/{course_id}")
def bluebook_delete_course(course_id: str, request: Request):
    """Delete a course and its roster. Refused (409) while any exam still
    belongs to it; students' accounts and past submissions are kept."""
    _require_staff(request)
    rec = _owned_course(course_id, request)
    if any(
        e.get("course_id") == course_id for e in _repo().list_bluebook_exams(rec.get("tenant_id"))
    ):
        raise HTTPException(
            status_code=409,
            detail="Exams still belong to this course. Move or delete them first.",
        )
    _repo().delete_bluebook_course(course_id)
    _repo().log_audit(
        action="bluebook_course_delete",
        tenant_id=rec.get("tenant_id"),
        details={"course_id": course_id},
    )
    return {"deleted": course_id}
