"""Course join links (2026-10): students join a course with a link or a short code.

A teacher turns joining on for a course and shares its link
(``/bluebook/?join=<code>``) or just the code. A student who opens it gives a
name, email and password and lands in the course, or, when the teacher
requires approval, waits as Pending until the teacher approves them.

Teacher routes (staff, own course) read and change the settings, reset the
code (which kills the old link: the link is the code), and approve or
decline waiting students. The public routes under ``/auth/join/`` need no
sign-in, like invite redemption.

What the public routes never say is whether an email already has an
account. A new email and a teacher's not-yet-activated roster row both
succeed the same way (the row is reused, so no duplicate is made); an
existing account joins only with its own password, and a wrong one gets the
same message whatever the reason. Unknown, switched-off and replaced codes
all get one message. Every attempt is rate limited per client, and failures
also per email, on the shared sign-in throttle.
"""

from __future__ import annotations

import re
import secrets

from fastapi import APIRouter, HTTPException, Request

from .. import bluebook_rules as rules
from .. import principal as principal_mod
from .. import student_auth
from .. import users as users_mod
from ..schemas import JoinCourseRequest, JoinSettingsRequest
from ._shared import (
    _LOGIN_MAX_ATTEMPTS,
    _record_login_failure,
    _repo,
    _require_staff,
    _throttle_login,
)
from .auth import TERMS_VERSION, _check_new_password, _session_payload
from .bluebook import _owned_course

router = APIRouter()

# No O/0, I/1 or L, so a code read aloud or copied from a board is never
# ambiguous. 31 symbols, 6 long: about 887 million codes.
JOIN_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
JOIN_CODE_LENGTH = 6
# The Collections app reads ?join= and shows its join screen.
JOIN_PATH = "/bluebook/?join="
# A leaked link cannot fill a course's approval queue without bound.
MAX_PENDING_PER_COURSE = 200
# Every join attempt, success or not, counts against this per-client budget;
# failures also count against the ordinary sign-in budget, per client and
# per email. Higher than the failure budget so a class joining together from
# one school network is not stopped by its own successes.
JOIN_ATTEMPTS_PER_WINDOW = _LOGIN_MAX_ATTEMPTS * 6
_CODE_ATTEMPTS = 8

LINK_NOT_WORKING = (
    "This join link or code isn't working. Check the code, or ask your teacher for a new link."
)
NO_MATCH = (
    "We couldn't add you with that email and password. If you already use "
    "Collections, enter the password you already have, or reset it from the sign-in page."
)
TERMS_REQUIRED = "Please tick the box to say you have read the student notice and accept the terms."
_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


def new_code() -> str:
    return "".join(secrets.choice(JOIN_CODE_ALPHABET) for _ in range(JOIN_CODE_LENGTH))


def normalize_code(raw: str) -> str | None:
    """The code as stored, or None when it cannot be a join code. Case,
    spaces and hyphens are forgiven ("k7q-w3x" reads as "K7QW3X")."""
    code = re.sub(r"[\s-]", "", raw or "").upper()
    if len(code) != JOIN_CODE_LENGTH or any(c not in JOIN_CODE_ALPHABET for c in code):
        return None
    return code


def normalize_domain(raw: str | None) -> str:
    """``"@School.edu "`` -> ``"school.edu"``; empty means any domain.
    Raises 422 for anything that is not a domain name."""
    domain = (raw or "").strip().lower().lstrip("@")
    if not domain:
        return ""
    if len(domain) > 253 or not _DOMAIN_RE.match(domain):
        raise HTTPException(status_code=422, detail="Enter a domain like school.edu.")
    return domain


def email_allowed(email: str, domain: str) -> bool:
    return not domain or email.rsplit("@", 1)[-1] == domain


def _settings_view(rec: dict | None) -> dict:
    code = rec["code"] if rec else None
    return {
        "enabled": bool(rec and rec["enabled"]),
        "code": code,
        "join_path": JOIN_PATH + code if code else None,
        "allowed_domain": (rec or {}).get("allowed_domain") or "",
        "require_approval": bool(rec and rec["require_approval"]),
    }


def _save(course: dict, rec: dict, fresh_code: bool) -> dict:
    """Store ``rec`` for ``course``, drawing a new code when ``fresh_code``
    (or when the course has none yet). A drawn code that another course
    already holds is drawn again."""
    out = {**rec, "course_id": course["id"], "tenant_id": course["tenant_id"]}
    for _ in range(_CODE_ATTEMPTS):
        if fresh_code or not out.get("code"):
            out["code"] = new_code()
        if _repo().put_course_join(out):
            return out
        fresh_code = True
    raise HTTPException(status_code=503, detail="Could not make a new code. Please try again.")


# ── Teacher: settings ─────────────────────────────────────────────────────────


@router.get("/bluebook/courses/{course_id}/join")
def join_settings(course_id: str, request: Request):
    _require_staff(request)
    _owned_course(course_id, request)
    return _settings_view(_repo().get_course_join(course_id))


@router.put("/bluebook/courses/{course_id}/join")
def update_join_settings(course_id: str, body: JoinSettingsRequest, request: Request):
    """Turn joining on or off, set the domain limit and the approval
    setting. The first save gives the course its code."""
    staff = _require_staff(request)
    course = _owned_course(course_id, request)
    rec = _repo().get_course_join(course_id) or {
        "code": None,
        "enabled": False,
        "allowed_domain": "",
        "require_approval": False,
    }
    if body.enabled is not None:
        rec["enabled"] = body.enabled
    if body.allowed_domain is not None:
        rec["allowed_domain"] = normalize_domain(body.allowed_domain)
    if body.require_approval is not None:
        rec["require_approval"] = body.require_approval
    saved = _save(course, rec, fresh_code=False)
    _repo().log_audit(
        action="bluebook_join_settings",
        tenant_id=course["tenant_id"],
        actor=staff.user_id,
        details={
            "course_id": course_id,
            "enabled": saved["enabled"],
            "domain_limit": bool(saved["allowed_domain"]),
            "require_approval": saved["require_approval"],
        },
    )
    return _settings_view(saved)


@router.post("/bluebook/courses/{course_id}/join/reset")
def reset_join_code(course_id: str, request: Request):
    """Replace the code. The old code and every copy of the old link stop
    working at once; students already on the course are unaffected."""
    staff = _require_staff(request)
    course = _owned_course(course_id, request)
    rec = _repo().get_course_join(course_id) or {
        "enabled": False,
        "allowed_domain": "",
        "require_approval": False,
    }
    saved = _save(course, rec, fresh_code=True)
    _repo().log_audit(
        action="bluebook_join_reset",
        tenant_id=course["tenant_id"],
        actor=staff.user_id,
        details={"course_id": course_id},
    )
    return _settings_view(saved)


# ── Teacher: waiting students ─────────────────────────────────────────────────


def _over_student_cap(tenant: str, student_ids: list[str]) -> bool:
    """Whether enrolling these students would take a free workspace past its
    student cap. Students already on any of its rosters do not count again."""
    if not rules.is_self_serve(_repo().get_tenant(tenant)):
        return False
    new = sum(1 for sid in student_ids if not _repo().list_enrollments_for_student(sid))
    return _repo().count_enrolled_students(tenant) + new > rules.MAX_ENROLLED_STUDENTS


def _cap_refusal() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail=f"Free workspaces can hold {rules.MAX_ENROLLED_STUDENTS} students.",
    )


def _enrol(course_id: str, user: dict, tenant: str) -> None:
    """Put a student on a course, exactly as the roster's "Add students"
    does: a workspace that holds Original also gets their profile record."""
    sid = user["user_id"]
    if "original" in principal_mod.tenant_products(tenant):
        _repo().get_or_create(sid)
        _repo().set_display_name(sid, user.get("name") or user["email"].split("@")[0])
    _repo().put_enrollment(course_id, sid, tenant)


def _approve(course: dict, student_ids: list[str]) -> list[str]:
    users = {u["user_id"]: u for u in _repo().list_users_by_ids(student_ids)}
    approved = []
    for sid in student_ids:
        user = users.get(sid)
        if user is not None:
            _enrol(course["id"], user, course["tenant_id"])
            approved.append(sid)
        _repo().delete_join_request(course["id"], sid)
    return approved


@router.post("/bluebook/courses/{course_id}/join-requests/{student_id}/approve")
def approve_join_request(course_id: str, student_id: str, request: Request):
    staff = _require_staff(request)
    course = _owned_course(course_id, request)
    waiting = {r["student_id"] for r in _repo().list_join_requests_for_course(course_id)}
    if student_id not in waiting:
        raise HTTPException(status_code=404, detail="Nobody by that id is waiting to join.")
    if _over_student_cap(course["tenant_id"], [student_id]):
        raise _cap_refusal()
    approved = _approve(course, [student_id])
    _repo().log_audit(
        action="bluebook_join_approve",
        tenant_id=course["tenant_id"],
        student_id=student_id,
        actor=staff.user_id,
        details={"course_id": course_id},
    )
    return {"approved": approved}


@router.post("/bluebook/courses/{course_id}/join-requests/approve-all")
def approve_all_join_requests(course_id: str, request: Request):
    staff = _require_staff(request)
    course = _owned_course(course_id, request)
    waiting = [r["student_id"] for r in _repo().list_join_requests_for_course(course_id)]
    if _over_student_cap(course["tenant_id"], waiting):
        raise _cap_refusal()
    approved = _approve(course, waiting)
    _repo().log_audit(
        action="bluebook_join_approve_all",
        tenant_id=course["tenant_id"],
        actor=staff.user_id,
        details={"course_id": course_id, "approved": len(approved)},
    )
    return {"approved": approved}


def _nothing_else_attached(student_id: str) -> bool:
    """True when a student account holds nothing but its login: on no
    roster, waiting for no other course, no sealed work, no reference
    writing. Declining such a joiner deletes the account, so a declined
    stranger's name and email do not linger where no teacher can see them."""
    if _repo().list_enrollments_for_student(student_id):
        return False
    if _repo().list_join_requests_for_student(student_id):
        return False
    if _repo().list_bluebook_submissions_for_student(student_id):
        return False
    profile = _repo().get(student_id)
    return profile is None or profile.sample_count == 0


@router.delete("/bluebook/courses/{course_id}/join-requests/{student_id}")
def decline_join_request(course_id: str, student_id: str, request: Request):
    """Decline a waiting student. An account made only to ask (nothing else
    attached) is deleted with the request; any other account is kept."""
    staff = _require_staff(request)
    course = _owned_course(course_id, request)
    if not _repo().delete_join_request(course_id, student_id):
        raise HTTPException(status_code=404, detail="Nobody by that id is waiting to join.")
    deleted = _nothing_else_attached(student_id) and _repo().delete_student(student_id)
    # Logged after any deletion, so this row is the retained receipt.
    _repo().log_audit(
        action="bluebook_join_decline",
        tenant_id=course["tenant_id"],
        student_id=student_id,
        actor=staff.user_id,
        details={"course_id": course_id, "account_deleted": bool(deleted)},
    )
    return {"declined": student_id, "account_deleted": bool(deleted)}


# ── Public: join by link or code ──────────────────────────────────────────────


def _live_join(raw_code: str) -> tuple[dict, dict] | None:
    """(join settings, course) for a code that works right now, else None:
    malformed, unknown, replaced, switched off, or its course or workspace
    no longer offers Collections. The caller answers every None alike."""
    code = normalize_code(raw_code)
    rec = _repo().get_course_join_by_code(code) if code else None
    if rec is None or not rec["enabled"]:
        return None
    course = _repo().get_bluebook_course(rec["course_id"])
    if course is None or course.get("tenant_id") != rec["tenant_id"]:
        return None
    if "bluebook" not in principal_mod.tenant_products(rec["tenant_id"]):
        return None
    return rec, course


def _dead_link(request: Request, email: str = "") -> HTTPException:
    _record_login_failure(request, email, scope="join")
    return HTTPException(status_code=404, detail=LINK_NOT_WORKING)


@router.get("/auth/join/{code}")
def join_lookup(code: str, request: Request):
    """What the join screen shows before the student types anything: the
    course, and the rules the teacher set. Unknown codes count as failures."""
    _throttle_login(request, "", scope="join")
    found = _live_join(code)
    if found is None:
        raise _dead_link(request)
    rec, course = found
    return {
        "code": rec["code"],
        "course_name": course["name"],
        "course_code": course.get("code") or "",
        "term": course.get("term") or "",
        "allowed_domain": rec["allowed_domain"],
        "require_approval": rec["require_approval"],
    }


@router.post("/auth/join/{code}")
def join_course(code: str, body: JoinCourseRequest, request: Request):
    """Join a course: create the account (or reuse the teacher's roster row
    for this email, or an existing account with its own password), then
    enrol, or wait for approval when the course asks for it, and sign in."""
    email = body.email.strip().lower()
    _throttle_login(request, "", scope="join-all", limit=JOIN_ATTEMPTS_PER_WINDOW)
    _record_login_failure(request, "", scope="join-all")
    _throttle_login(request, email, scope="join")
    found = _live_join(code)
    if found is None:
        raise _dead_link(request, email)
    rec, course = found
    tenant = rec["tenant_id"]
    if "@" not in email or len(email) > 254:
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    if not email_allowed(email, rec["allowed_domain"]):
        raise HTTPException(
            status_code=422,
            detail=f"This course only accepts email addresses ending in @{rec['allowed_domain']}.",
        )
    _check_new_password(body.password)
    if not body.accept_terms:
        raise HTTPException(status_code=422, detail=TERMS_REQUIRED)

    # Who is joining. Nothing is written until every check has passed.
    existing = _repo().get_user_by_email(email)
    reuse_row = bool(
        existing
        and existing["role"] == "student"
        and existing["tenant_id"] == tenant
        and not users_mod.is_activated(existing)
    )
    if existing is not None and not reuse_row:
        # An account with a password: only its own password joins it. A
        # wrong one (or a row that has none, in another workspace) gets the
        # same answer as any other mismatch.
        if not users_mod.verify_password(body.password, existing["password_hash"]):
            _record_login_failure(request, email, scope="join")
            raise HTTPException(status_code=401, detail=NO_MATCH)
        # The caller has proved they own this account, so it is safe to
        # say why it cannot join.
        if existing["role"] != "student":
            raise HTTPException(
                status_code=409,
                detail="This is a teacher account. Students join with their own account.",
            )
        if existing["tenant_id"] != tenant:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Your Collections account belongs to another teacher's workspace, so it "
                    "can't join this course. Ask your teacher to add you with another email."
                ),
            )
    sid = existing["user_id"] if existing else student_auth.derive_student_id(tenant, email)
    on_course = any(
        e["student_id"] == sid for e in _repo().list_enrollments_for_course(rec["course_id"])
    )
    pending = rec["require_approval"] and not on_course
    if pending:
        waiting = _repo().list_join_requests_for_course(rec["course_id"])
        if sid not in {r["student_id"] for r in waiting} and len(waiting) >= MAX_PENDING_PER_COURSE:
            raise HTTPException(
                status_code=403,
                detail="Too many students are waiting to join this course. Ask your teacher.",
            )
    elif not on_course and _over_student_cap(tenant, [sid]):
        raise HTTPException(
            status_code=403,
            detail="This course can't take more students right now. Ask your teacher.",
        )

    if existing is None:
        user, _ = users_mod.create_student_account(tenant, email, body.name.strip()[:120])
        users_mod.set_password(sid, body.password)
        account = "created"
    elif reuse_row:
        # The teacher already listed this email: the same row, no duplicate.
        # Their earlier invite link is left working, so the student it was
        # meant for can still use it to set their own password.
        user = existing
        users_mod.set_password(sid, body.password)
        account = "roster_row"
    else:
        user = existing
        account = "existing"

    if pending:
        _repo().put_join_request(rec["course_id"], sid, tenant)
    elif not on_course:
        _enrol(rec["course_id"], user, tenant)
    status = "pending" if pending else "enrolled"
    _repo().log_audit(
        action="bluebook_join",
        student_id=sid,
        tenant_id=tenant,
        actor=user["email"],
        result="ok",
        details={
            "course_id": rec["course_id"],
            "status": status,
            "account": account,
            "terms_version": TERMS_VERSION,
        },
    )
    return {
        **_session_payload(user),
        "join": {"course_id": rec["course_id"], "course_name": course["name"], "status": status},
    }
