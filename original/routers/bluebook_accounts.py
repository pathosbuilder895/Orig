"""Bluebook self-serve people: course rosters, invites, and the student dashboard.

Teacher routes (staff, own tenant) manage who is on a course and hand out
one-time set-password links. Student routes (``/bluebook/me/*``) derive the
student from the session and never take a student id from the path, so the
isolation middleware's rule — a student touches only their own record —
holds without any new case.

See docs/superpowers/specs/2026-09-17-bluebook-standalone-backend-design.md,
Sections 3-4 and the 2026-09-28 amendment.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from .. import bluebook_rules as rules
from .. import invites as invites_mod
from .. import mailer, student_auth
from .. import principal as principal_mod
from .. import users as users_mod
from ..schemas import RosterAddRequest, SendEmailRequest
from . import phone_park
from ._shared import _bluebook_tenant, _exam_submissions, _repo, _require_staff
from .bluebook import _owned_course, _owned_exam, only_waiting

router = APIRouter()


def _staff_name(staff) -> str:
    user = _repo().get_user(staff.user_id)
    return (user or {}).get("name") or ""


def _deliver_invite(
    request: Request, email: str, inv: dict, course: dict, teacher: str, send: bool
) -> bool:
    """Email one invite when asked to and mail is configured. Never raises:
    the link is always returned to the teacher as well."""
    if not send or not mailer.configured():
        return False
    link = mailer.absolute_url(inv["invite_path"], str(request.base_url))
    return mailer.send_invite(email, link, course.get("name") or "", teacher)


# ── Teacher: course rosters ───────────────────────────────────────────────────


def _roster_row(user: dict | None, student_id: str, invite: dict | None) -> dict:
    if user is None:
        # Enrolled through a signed launch link: no account exists.
        return {
            "student_id": student_id,
            "email": None,
            "name": None,
            "state": "link",
            "invite_expires_at": None,
        }
    active = users_mod.is_activated(user)
    pending = (
        invite if invite and not invite.get("redeemed_at") and not invite.get("voided_at") else None
    )
    return {
        "student_id": student_id,
        "email": user["email"],
        "name": user.get("name") or "",
        "state": "active" if active else "invited",
        "invite_expires_at": pending["expires_at"] if pending and not active else None,
    }


@router.post("/bluebook/courses/{course_id}/students")
def roster_add(course_id: str, body: RosterAddRequest, request: Request):
    """Add students by email. Creates each account if new, enrols it, and
    returns a one-time set-password link for every account not yet active.
    One bad row (invalid email, email owned by another account) is reported
    in its own result and does not stop the rest."""
    staff = _require_staff(request)
    course = _owned_course(course_id, request)
    tenant = course["tenant_id"]
    if not body.students or len(body.students) > rules.MAX_ROSTER_BATCH:
        raise HTTPException(
            status_code=422,
            detail=f"Add between 1 and {rules.MAX_ROSTER_BATCH} students at a time.",
        )

    # Dedupe inside the batch: a repeated email would otherwise issue a
    # second invite and silently void the first link we just returned.
    batch: dict[str, str] = {}
    for st in body.students:
        email = st.email.strip().lower()
        if email and email not in batch:
            batch[email] = st.name.strip()[:120]

    if rules.is_self_serve(_repo().get_tenant(tenant)):
        new = sum(
            1
            for email in batch
            if not _repo().list_enrollments_for_student(
                student_auth.derive_student_id(tenant, email)
            )
        )
        if _repo().count_enrolled_students(tenant) + new > rules.MAX_ENROLLED_STUDENTS:
            raise HTTPException(
                status_code=403,
                detail=f"Free workspaces can hold {rules.MAX_ENROLLED_STUDENTS} students.",
            )

    has_original = "original" in principal_mod.tenant_products(tenant)
    teacher = _staff_name(staff) if body.send_email else ""
    results = []
    for email, name in batch.items():
        if "@" not in email or len(email) > 254:
            results.append({"email": email, "error": "Not a valid email address."})
            continue
        try:
            user, created = users_mod.create_student_account(tenant, email, name)
        except ValueError as e:
            results.append({"email": email, "error": str(e)})
            continue
        sid = user["user_id"]
        if has_original:
            # Only a tenant that bought Original gets a profile record: that
            # is what lets its staff see the student in Original's roster.
            _repo().get_or_create(sid)
            _repo().set_display_name(sid, user.get("name") or email.split("@")[0])
        _repo().put_enrollment(course_id, sid, tenant)
        # Added by the teacher: a request to join by link is answered.
        _repo().delete_join_request(course_id, sid)
        row = {
            "student_id": sid,
            "email": user["email"],
            "name": user.get("name") or "",
            "account": "created" if created else "existing",
            "state": "active" if users_mod.is_activated(user) else "invited",
            "invite_path": None,
            "invite_expires_at": None,
            "emailed": False,
        }
        if row["state"] == "invited":
            inv = invites_mod.issue(tenant, sid, staff.user_id, course_id)
            row["invite_path"] = inv["invite_path"]
            row["invite_expires_at"] = inv["expires_at"]
            row["emailed"] = _deliver_invite(
                request, user["email"], inv, course, teacher, body.send_email
            )
        results.append(row)

    _repo().log_audit(
        action="bluebook_roster_add",
        tenant_id=tenant,
        actor=staff.user_id,
        details={
            "course_id": course_id,
            "added": sum(1 for r in results if "error" not in r),
            "emailed": sum(1 for r in results if r.get("emailed")),
        },
    )
    return {"students": results}


@router.get("/bluebook/courses/{course_id}/students")
def roster_list(course_id: str, request: Request):
    """The course roster, then anyone who joined by link and is waiting for
    the teacher's approval (state "pending", course_join.py)."""
    _require_staff(request)
    _owned_course(course_id, request)
    enrolled = _repo().list_enrollments_for_course(course_id)
    ids = [e["student_id"] for e in enrolled]
    waiting = [
        r for r in _repo().list_join_requests_for_course(course_id) if r["student_id"] not in ids
    ]
    users = {
        u["user_id"]: u for u in _repo().list_users_by_ids(ids + [r["student_id"] for r in waiting])
    }
    rows = []
    for sid in ids:
        user = users.get(sid)
        invite = _repo().latest_invite_for_user(sid) if user else None
        rows.append(_roster_row(user, sid, invite))
    for r in waiting:
        user = users.get(r["student_id"])
        if user is not None:
            rows.append(
                {
                    "student_id": r["student_id"],
                    "email": user["email"],
                    "name": user.get("name") or "",
                    "state": "pending",
                    "invite_expires_at": None,
                    "requested_at": r["created_at"],
                }
            )
    return {"students": rows}


@router.delete("/bluebook/courses/{course_id}/students/{student_id}")
def roster_remove(course_id: str, student_id: str, request: Request):
    """Take a student off a course. Their account and past work are kept."""
    staff = _require_staff(request)
    course = _owned_course(course_id, request)
    if not _repo().delete_enrollment(course_id, student_id):
        raise HTTPException(status_code=404, detail="student is not on this course")
    # An unused set-password link would re-enrol the student on redemption;
    # void it so removal also revokes the link (matters when links never
    # expire, INVITE_NO_EXPIRY=1). Accounts already set up are unaffected.
    _repo().void_invites_for_user(student_id)
    _repo().log_audit(
        action="bluebook_roster_remove",
        tenant_id=course["tenant_id"],
        student_id=student_id,
        actor=staff.user_id,
        details={"course_id": course_id},
    )
    return {"removed": student_id}


@router.post("/bluebook/courses/{course_id}/students/{student_id}/invite")
def roster_reissue_invite(
    course_id: str, student_id: str, request: Request, body: SendEmailRequest | None = None
):
    """Issue a fresh set-password link, voiding earlier ones. This is also
    the teacher-driven password reset. Emailed when asked and mail is set up;
    the link is always returned too."""
    staff = _require_staff(request)
    course = _owned_course(course_id, request)
    enrolled = {e["student_id"] for e in _repo().list_enrollments_for_course(course_id)}
    user = _repo().get_user(student_id) if student_id in enrolled else None
    if user is None or user.get("role") != "student":
        raise HTTPException(status_code=404, detail="student is not on this course")
    inv = invites_mod.issue(course["tenant_id"], student_id, staff.user_id, course_id)
    send = bool(body and body.send_email)
    emailed = _deliver_invite(
        request, user["email"], inv, course, _staff_name(staff) if send else "", send
    )
    _repo().log_audit(
        action="bluebook_invite_reissue",
        tenant_id=course["tenant_id"],
        student_id=student_id,
        actor=staff.user_id,
        details={"course_id": course_id},
    )
    return {
        "student_id": student_id,
        "invite_path": inv["invite_path"],
        "invite_expires_at": inv["expires_at"],
        "emailed": emailed,
    }


@router.post("/bluebook/courses/{course_id}/invites/reissue-pending")
def roster_reissue_pending(course_id: str, request: Request, body: SendEmailRequest | None = None):
    """Fresh links for every student on the course who has not set a
    password yet. Links are stored hashed, so an earlier link can never be
    shown again; this replaces them all in one go."""
    staff = _require_staff(request)
    course = _owned_course(course_id, request)
    send = bool(body and body.send_email)
    teacher = _staff_name(staff) if send else ""
    ids = [e["student_id"] for e in _repo().list_enrollments_for_course(course_id)]
    out = []
    for user in _repo().list_users_by_ids(ids):
        if user.get("role") != "student" or users_mod.is_activated(user):
            continue
        inv = invites_mod.issue(course["tenant_id"], user["user_id"], staff.user_id, course_id)
        out.append(
            {
                "student_id": user["user_id"],
                "email": user["email"],
                "name": user.get("name") or "",
                "state": "invited",
                "invite_path": inv["invite_path"],
                "invite_expires_at": inv["expires_at"],
                "emailed": _deliver_invite(request, user["email"], inv, course, teacher, send),
            }
        )
    _repo().log_audit(
        action="bluebook_invite_reissue_pending",
        tenant_id=course["tenant_id"],
        actor=staff.user_id,
        details={
            "course_id": course_id,
            "reissued": len(out),
            "emailed": sum(r["emailed"] for r in out),
        },
    )
    return {"students": out}


# ── Teacher: everyone in the workspace ────────────────────────────────────────


def _tenant_rosters(tenant: str | None) -> tuple[dict, dict[str, list[dict]]]:
    """(courses by id, student_id -> [course]) across a tenant's courses."""
    courses = {c["id"]: c for c in _repo().list_bluebook_courses(tenant)}
    by_student: dict[str, list[dict]] = {}
    for cid, c in courses.items():
        for e in _repo().list_enrollments_for_course(cid):
            by_student.setdefault(e["student_id"], []).append(
                {"course_id": cid, "name": c.get("name"), "code": c.get("code")}
            )
    return courses, by_student


@router.get("/bluebook/students")
def students_list(request: Request):
    """Every student on any of the workspace's course rosters, with their
    courses, account state, and how much they have submitted."""
    _require_staff(request)
    tenant = _bluebook_tenant(request)
    _, by_student = _tenant_rosters(tenant)
    users = {u["user_id"]: u for u in _repo().list_users_by_ids(list(by_student))}
    stats: dict[str, dict] = {}
    for sub in _repo().list_bluebook_submissions(tenant):
        sid = sub.get("student_id")
        if sid in by_student:
            st = stats.setdefault(sid, {"n": 0, "last": None})
            st["n"] += 1
            if st["last"] is None or (sub.get("created_at") or "") > st["last"]:
                st["last"] = sub.get("created_at")
    rows = []
    for sid, courses in by_student.items():
        user = users.get(sid)
        invite = _repo().latest_invite_for_user(sid) if user else None
        row = _roster_row(user, sid, invite)
        row["courses"] = courses
        row["submissions"] = stats.get(sid, {}).get("n", 0)
        row["last_submitted_at"] = stats.get(sid, {}).get("last")
        rows.append(row)
    rows.sort(key=lambda r: (r.get("name") or r.get("email") or "~").lower())
    return {"students": rows}


@router.get("/bluebook/exams/{exam_id}/live")
def exam_live(exam_id: str, request: Request):
    """Who is writing right now: roster vs started vs submitted, with time
    left. Built from sittings (server deadlines) and submissions; warnings
    arrive with the seal, so they are known only for submitted students."""
    _require_staff(request)
    exam = _owned_exam(exam_id, request)
    now = rules.now_utc()
    _, by_student = _tenant_rosters(exam.get("tenant_id"))
    course_id = exam.get("course_id")
    roster = [
        sid
        for sid, cs in by_student.items()
        if not course_id or any(c["course_id"] == course_id for c in cs)
    ]
    subs = {}
    for s in _exam_submissions(exam):
        if s.get("student_id"):
            subs[s["student_id"]] = s
    ids = list(dict.fromkeys(roster + list(subs)))
    users = {u["user_id"]: u for u in _repo().list_users_by_ids(ids)}
    rows = []
    counts = {
        "enrolled": len(roster),
        "writing": 0,
        "submitted": 0,
        "late": 0,
        "not_started": 0,
        "time_up": 0,
    }
    for sid in ids:
        user = users.get(sid) or {}
        session = _repo().get_bluebook_session(exam_id, sid)
        sub = subs.get(sid)
        minutes_left = None
        if sub:
            status = "submitted"
        elif session:
            deadline = rules.parse_instant(session["deadline_at"])
            remaining = (deadline - now).total_seconds() if deadline else 0
            status = "writing" if remaining > 0 else "time_up"
            minutes_left = max(0, int(-(-remaining // 60)))
        else:
            status = "not_started"
        counts[status] += 1
        if sub and sub.get("late"):
            counts["late"] += 1
        rows.append(
            {
                "student_id": sid,
                "name": user.get("name") or (sub or {}).get("candidate") or "",
                "email": user.get("email"),
                "status": status,
                "started_at": (session or {}).get("started_at"),
                "deadline_at": (session or {}).get("deadline_at"),
                "minutes_left": minutes_left,
                "submitted_at": (sub or {}).get("created_at"),
                "late": bool((sub or {}).get("late")),
                "warnings": len((sub or {}).get("warnings") or []),
            }
        )
    order = {"writing": 0, "time_up": 1, "not_started": 2, "submitted": 3}
    rows.sort(key=lambda r: (order[r["status"]], (r["name"] or r["email"] or "").lower()))
    return {
        "exam": {
            "id": exam["id"],
            "title": exam.get("title"),
            "state": rules.exam_state(exam, now),
        },
        "now": now.isoformat(),
        "counts": counts,
        "students": rows,
    }


# ── Teacher: erasure ──────────────────────────────────────────────────────────


@router.delete("/bluebook/students/{student_id}")
def student_erase(student_id: str, request: Request):
    """Permanently erase a student and all their Bluebook work (FERPA
    right-to-erasure): submissions and their text, sittings, course rosters,
    set-password links, and their login. There is no undo.

    Staff may erase only their own workspace's students; operators may cross
    workspaces. A cross-tenant id reads as a missing one (404). A student who
    also has an Original profile with writing samples is refused with 409:
    erasing them removes their writing baseline too, which stays behind
    Original's guarded ``DELETE /students/{id}``. A profile with no samples
    (its only approved exam was removed again) holds no baseline, so it does
    not block erasure and is deleted with the rest."""
    staff = _require_staff(request)
    try:
        principal_mod.assert_student_access(staff, student_id)
    except principal_mod.TenantAccessError:
        raise HTTPException(status_code=404, detail="student not found") from None
    profile = _repo().get(student_id)
    if profile is not None and profile.sample_count > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "This student has an Original profile. Erase them through "
                "Original's data deletion, which also removes their writing baseline."
            ),
        )
    tenant = principal_mod.tenant_of(student_id)
    erased = _repo().delete_student(student_id)
    # Logged after the purge, so this row is the one retained erasure receipt.
    _repo().log_audit(
        action="bluebook_student_erase",
        tenant_id=tenant,
        student_id=student_id,
        actor=staff.user_id,
        result="ok" if erased else "not_found",
    )
    if not erased:
        raise HTTPException(status_code=404, detail="student not found")
    return {"erased": student_id}


# ── Student dashboard ─────────────────────────────────────────────────────────


def _require_student(request: Request) -> principal_mod.Principal:
    p = getattr(request.state, "principal", None)
    if p is None or p.is_demo:
        raise HTTPException(status_code=401, detail="Sign in to see your exams.")
    if p.role != "student":
        raise HTTPException(status_code=403, detail="Student account required.")
    return p


def _visible_exam(p: principal_mod.Principal, exam_id: str, now: datetime) -> tuple[dict, str]:
    """The exam and its state, if this student may see it: same tenant, not
    a draft, and either course-less (open to the whole workspace, though not
    to a student still waiting for approval) or on a course the student is
    enrolled in. 404 otherwise."""
    exam = _repo().get_bluebook_exam(exam_id)
    if exam is None or exam.get("tenant_id") != p.tenant_id:
        raise HTTPException(status_code=404, detail="exam not found")
    state = rules.exam_state(exam, now)
    if state == rules.DRAFT:
        raise HTTPException(status_code=404, detail="exam not found")
    course_id = exam.get("course_id")
    enrolled = {e["course_id"] for e in _repo().list_enrollments_for_student(p.user_id)}
    if course_id and course_id not in enrolled:
        raise HTTPException(status_code=404, detail="exam not found")
    if not course_id and only_waiting(p.user_id, enrolled):
        raise HTTPException(status_code=404, detail="exam not found")
    return exam, state


def _exam_summary(exam: dict, state: str, session: dict | None, submitted: bool) -> dict:
    return {
        "exam_id": exam["id"],
        "title": exam.get("title"),
        "course": exam.get("course"),
        "course_id": exam.get("course_id"),
        "duration": exam.get("duration"),
        "timed": rules.is_timed(exam),
        "setting": rules.setting(exam),
        "min_words": exam.get("minWords"),
        "max_words": exam.get("maxWords"),
        "opens_at": exam.get("opens_at"),
        "closes_at": exam.get("closes_at"),
        "state": state,
        "questions_count": len(exam.get("questions") or []) or (1 if exam.get("prompt") else 0),
        "results_released": bool(exam.get("results_released_at")),
        "session": (
            {"started_at": session["started_at"], "deadline_at": session["deadline_at"]}
            if session
            else None
        ),
        "submitted": submitted,
    }


def _exam_detail(exam: dict, state: str, session: dict | None, submitted: bool) -> dict:
    out = _exam_summary(exam, state, session, submitted)
    # The prompt is withheld until the student may actually sit the exam.
    reveal = state == rules.OPEN or session is not None or submitted
    out["prompt"] = exam.get("prompt") if reveal else None
    out["questions"] = (exam.get("questions") or []) if reveal else []
    out["conditions"] = exam.get("conditions") or {}
    return out


@router.get("/bluebook/me")
def me(request: Request):
    p = _require_student(request)
    user = _repo().get_user(p.user_id)

    def _courses(rows: list[dict]) -> list[dict]:
        out = []
        for e in rows:
            c = _repo().get_bluebook_course(e["course_id"])
            if c and c.get("tenant_id") == p.tenant_id:
                out.append(
                    {
                        "course_id": c["id"],
                        "code": c.get("code"),
                        "name": c["name"],
                        "term": c.get("term"),
                    }
                )
        return out

    courses = _courses(_repo().list_enrollments_for_student(p.user_id))
    # Courses joined by link that still wait for the teacher's approval.
    on = {c["course_id"] for c in courses}
    pending = [
        c
        for c in _courses(_repo().list_join_requests_for_student(p.user_id))
        if c["course_id"] not in on
    ]
    return {
        "student_id": p.user_id,
        "name": (user or {}).get("name", ""),
        "email": (user or {}).get("email"),
        "tenant_id": p.tenant_id,
        "products": sorted(p.products),
        "has_account": user is not None,
        "courses": courses,
        "pending_courses": pending,
    }


@router.get("/bluebook/me/exams")
def my_exams(request: Request):
    p = _require_student(request)
    now = rules.now_utc()
    enrolled = {e["course_id"] for e in _repo().list_enrollments_for_student(p.user_id)}
    if only_waiting(p.user_id, enrolled):
        return {"exams": []}
    submitted = {
        s["exam_id"]
        for s in _repo().list_bluebook_submissions_for_student(p.user_id)
        if s.get("exam_id")
    }
    out = []
    for exam in _repo().list_bluebook_exams(p.tenant_id):
        course_id = exam.get("course_id")
        if course_id and course_id not in enrolled:
            continue
        state = rules.exam_state(exam, now)
        if state == rules.DRAFT:
            continue
        session = _repo().get_bluebook_session(exam["id"], p.user_id)
        out.append(_exam_summary(exam, state, session, exam["id"] in submitted))
    return {"exams": out}


@router.get("/bluebook/me/exams/{exam_id}")
def my_exam(exam_id: str, request: Request):
    p = _require_student(request)
    exam, state = _visible_exam(p, exam_id, rules.now_utc())
    session = _repo().get_bluebook_session(exam_id, p.user_id)
    submitted = any(
        s.get("exam_id") == exam_id
        for s in _repo().list_bluebook_submissions_for_student(p.user_id)
    )
    return _exam_detail(exam, state, session, submitted)


@router.post("/bluebook/me/exams/{exam_id}/start")
def my_exam_start(exam_id: str, request: Request):
    """Begin (or resume) a sitting from the dashboard. Pins the server
    deadline exactly as the launch-link path does, clipped so it never
    passes the exam's closes_at. A tenant that bought Original also gets a
    proctor attestation, which the seal's report-only comparison sends; the
    seal never adds to the student's baseline (a professor approves which
    sealed exams do). A Bluebook-only workspace gets none, because it never
    profiles."""
    p = _require_student(request)
    now = rules.now_utc()
    exam, state = _visible_exam(p, exam_id, now)
    if any(
        s.get("exam_id") == exam_id
        for s in _repo().list_bluebook_submissions_for_student(p.user_id)
    ):
        raise HTTPException(status_code=409, detail="You have already submitted this exam.")
    existing = _repo().get_bluebook_session(exam_id, p.user_id)
    if existing is None and state != rules.OPEN:
        detail = (
            "This exam has not opened yet." if state == rules.UPCOMING else "This exam is closed."
        )
        raise HTTPException(status_code=409, detail=detail)
    if existing is None:
        # Phone parking (only if the teacher switched it on): a new sitting
        # waits for the phone; one already under way is never held up.
        phone_park.require_cleared(exam, exam_id, p.user_id)
    seconds = rules.session_seconds(exam, now)
    if seconds is None:
        # Untimed and never closes: nothing to pin (see rules.session_seconds).
        s = {"started_at": now.isoformat(), "deadline_at": None, "created": existing is None}
    else:
        s = _repo().get_or_create_bluebook_session(exam_id, p.user_id, p.tenant_id, seconds)
    proctor_token = None
    if "original" in p.products:
        proctor_token = student_auth.mint_proctor_attestation(p.user_id, exam_id)
    _repo().log_audit(
        action="bluebook_dashboard_start",
        tenant_id=p.tenant_id,
        student_id=p.user_id,
        details={"exam_id": exam_id, "resumed": not s.get("created", True)},
    )
    return {
        "exam": _exam_detail(exam, rules.OPEN, s if s.get("deadline_at") else existing, False),
        "started_at": s["started_at"],
        "deadline_at": s["deadline_at"],
        "server_now": datetime.now(UTC).isoformat(),
        "duration_seconds": seconds,
        "proctor_token": proctor_token,
    }


@router.get("/bluebook/me/submissions")
def my_submissions(request: Request):
    p = _require_student(request)
    released = _released_exams(p.tenant_id)
    return {
        "submissions": [
            rules.student_view(s, released=s.get("exam_id") in released)
            for s in _repo().list_bluebook_submissions_for_student(p.user_id)
        ]
    }


def _released_exams(tenant: str) -> set:
    return {e["id"] for e in _repo().list_bluebook_exams(tenant) if e.get("results_released_at")}


@router.get("/bluebook/me/submissions/{submission_id}")
def my_submission(submission_id: str, request: Request):
    p = _require_student(request)
    rec = _repo().get_bluebook_submission(submission_id)
    if rec is None or rec.get("student_id") != p.user_id:
        raise HTTPException(status_code=404, detail="submission not found")
    exam = _repo().get_bluebook_exam(rec["exam_id"]) if rec.get("exam_id") else None
    return rules.student_view(rec, released=bool((exam or {}).get("results_released_at")))


# ── Resume where you left off, across devices (2026-10) ───────────────────────
# One saved location per signed-in account: the screen, the item it shows,
# the tab and the scroll position. The browser saves it (debounced, and when
# the page is hidden); sign-in on any device reads it back. It is read back
# only after checking, now, that the account may still open that item, so a
# deleted or no-longer-shared item falls back to the home screen. A student
# never resumes into a sitting: an exam location comes back as that exam's
# briefing, where the normal start rules apply. Only the account's own row is
# ever read (the key is the caller's id, never a path or body field), and the
# fields are short identifiers, so a link token or any text cannot be stored.

_SCREENS = {
    # screen -> the entity kind it shows ("" for none, None if it needs none)
    "staff": {
        "dashboard": "",
        "sessions": "",
        "courses": "",
        "students": "student",
        "results": "",
        "account": "",
        "proctor": "exam",
        "manage-exam": "exam",
        "roster": "course",
    },
    "student": {
        "student-home": "",
        "student-account": "",
        "student-submission": "submission",
        "briefing": "exam",
        # Saved while writing; always read back as the briefing.
        "exam": "exam",
    },
}
# Screens that cannot be shown without their item.
_NEEDS_ENTITY = {"proctor", "manage-exam", "roster", "student-submission", "briefing", "exam"}
_ID_RE = r"^[A-Za-z0-9_:@-][A-Za-z0-9_:@.-]{0,127}$"
_TAB_RE = r"^[a-z0-9_-]{1,32}$"


class LastLocationBody(BaseModel):
    screen: str = Field(max_length=32)
    entity_kind: str = Field(default="", max_length=16)
    entity_id: str = Field(default="", max_length=128)
    tab: str = Field(default="", max_length=32)
    scroll_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    scroll_anchor: str = Field(default="", max_length=128)


def _location_account(request: Request) -> tuple[principal_mod.Principal, str]:
    """(principal, "staff"|"student") for a real signed-in account. The
    anonymous demo principal is shared by every visitor, so it never has a
    saved location."""
    p = getattr(request.state, "principal", None)
    if p is None or p.is_demo or not p.user_id:
        raise HTTPException(status_code=401, detail="Sign in to save your place.")
    if p.role == "student":
        return p, "student"
    _require_staff(request)
    return p, "staff"


def _looks_like_token(value: str) -> bool:
    # A signed token (JWT-style a.b.c) or anything carrying a link query.
    return value.count(".") >= 2 or "?" in value or "=" in value


def _clean_location(body: LastLocationBody, kind: str) -> dict:
    screens = _SCREENS[kind]
    if body.screen not in screens:
        raise HTTPException(status_code=422, detail="That screen is not kept.")
    want = screens[body.screen]
    ek, eid = body.entity_kind, body.entity_id
    if (ek or eid) and (ek != want or not eid):
        raise HTTPException(status_code=422, detail="That item does not belong on this screen.")
    if body.screen in _NEEDS_ENTITY and not eid:
        raise HTTPException(status_code=422, detail="This screen needs its item.")
    for value in (eid, body.scroll_anchor):
        if value and (not re.match(_ID_RE, value) or _looks_like_token(value)):
            raise HTTPException(status_code=422, detail="Only short identifiers are kept.")
    if body.tab and not re.match(_TAB_RE, body.tab):
        raise HTTPException(status_code=422, detail="Only short identifiers are kept.")
    return {
        "screen": body.screen,
        "entity_kind": ek,
        "entity_id": eid,
        "tab": body.tab,
        "scroll_fraction": round(float(body.scroll_fraction), 4),
        "scroll_anchor": body.scroll_anchor,
    }


@router.put("/bluebook/me/location")
def put_last_location(request: Request, body: dict | None = Body(default=None)):
    """Save where the signed-in account is now (one row per account). The
    sign-in is checked before the body, so a caller who is not signed in
    learns nothing about the shape."""
    p, kind = _location_account(request)
    try:
        parsed = LastLocationBody.model_validate(body or {})
    except ValidationError:
        raise HTTPException(status_code=422, detail="That location is not valid.") from None
    loc = _clean_location(parsed, kind)
    saved = _repo().put_last_location(p.user_id, p.tenant_id, p.role, loc)
    return {"saved": True, "updated_at": saved.get("updated_at")}


def _resolve_location(request: Request, p, kind: str, loc: dict) -> dict | None:
    """The saved location as it may be opened now, or None (go home)."""
    screen, ek, eid = loc.get("screen"), loc.get("entity_kind") or "", loc.get("entity_id") or ""
    if screen not in _SCREENS[kind] or loc.get("tenant_id") != p.tenant_id:
        return None
    out = {
        "screen": screen,
        "entity_kind": ek,
        "entity_id": eid,
        "entity": None,
        "tab": loc.get("tab") or "",
        "scroll_fraction": float(loc.get("scroll_fraction") or 0.0),
        "scroll_anchor": loc.get("scroll_anchor") or "",
        "updated_at": loc.get("updated_at"),
    }
    try:
        if kind == "staff":
            if ek == "exam":
                exam = _owned_exam(eid, request)
                out["entity"] = {"id": exam["id"], "title": exam.get("title")}
            elif ek == "course":
                course = _owned_course(eid, request)
                out["entity"] = {
                    "id": course["id"],
                    "name": course.get("name"),
                    "code": course.get("code"),
                }
            elif ek == "student":
                _, by_student = _tenant_rosters(_bluebook_tenant(request))
                if eid not in by_student:
                    return None
                out["entity"] = {"id": eid}
        else:
            if ek == "submission":
                rec = _repo().get_bluebook_submission(eid)
                if rec is None or rec.get("student_id") != p.user_id:
                    return None
                out["entity"] = {"id": eid}
            elif ek == "exam":
                exam, state = _visible_exam(p, eid, rules.now_utc())
                submitted = any(
                    s.get("exam_id") == eid
                    for s in _repo().list_bluebook_submissions_for_student(p.user_id)
                )
                if submitted:
                    return None
                # Never straight into a sitting: the briefing is the exam's
                # start/resume screen, and it applies the start rules.
                out.update(screen="briefing", tab="", scroll_fraction=0.0, scroll_anchor="")
                out["entity"] = {"id": exam["id"], "title": exam.get("title"), "state": state}
    except HTTPException:
        return None
    return out


@router.get("/bluebook/me/location")
def get_last_location(request: Request):
    """Where the signed-in account last was, if it may still go there; null
    sends the app to its home screen. Only the caller's own row is read."""
    p, kind = _location_account(request)
    loc = _repo().get_last_location(p.user_id)
    if not loc:
        return {"location": None}
    if loc.get("role") != p.role and not (kind == "staff" and loc.get("role") != "student"):
        return {"location": None}
    return {"location": _resolve_location(request, p, kind, loc)}
