"""Staff / student / demo authentication, moved verbatim from original/api.py."""

from __future__ import annotations

import hmac
import secrets

from fastapi import APIRouter, HTTPException, Request

from .. import bluebook_rules as rules
from .. import invites as invites_mod
from .. import join_links as join_links_mod
from .. import mailer, student_auth
from .. import principal as principal_mod
from .. import users as users_mod
from ..bluebook_rules import SELF_SERVE_PLAN
from ..schemas import (
    AuthLoginRequest,
    AuthRegisterRequest,
    AuthSignupRequest,
    DemoLoginRequest,
    InviteRedeemRequest,
    JoinLinkInfoRequest,
    JoinLinkRequest,
    PasswordChangeRequest,
    PasswordResetRequest,
    StudentLoginRequest,
)
from ._shared import (
    _api,
    _audit_maintenance_access,
    _record_login_failure,
    _repo,
    _require_guard,
    _signup_open,
    _throttle_login,
)

router = APIRouter()

# The terms/privacy text a signup or an invited professor accepts
# (demo/legal/*.html). Bump with any material change; the audit log records
# the version each teacher accepted.
TERMS_VERSION = "2026-10-01-draft"
_TERMS_REQUIRED = "Please accept the terms of service and privacy policy."

_MIN_PASSWORD = 8
_MAX_PASSWORD = 1024  # PBKDF2 cost is linear in input length; bound it.


def _check_new_password(password: str) -> None:
    if len(password) < _MIN_PASSWORD:
        raise HTTPException(status_code=422, detail="password must be at least 8 characters")
    if len(password) > _MAX_PASSWORD:
        raise HTTPException(status_code=422, detail="password is too long")


def _session_payload(user: dict) -> dict:
    """What every successful sign-in returns. Students get the stateless
    student session the isolation middleware already confines to their own
    record; staff get a principal token. Both carry ``products`` so each
    dashboard can branch without another call.

    Both tokens carry the tag of the password as stored now (read back, since
    a caller may hold the row from before it set the password), so a later
    change or reset ends them (T-79)."""
    tid = user["tenant_id"]
    products = sorted(principal_mod.tenant_products(tid))
    current = _repo().get_user(user["user_id"]) or user
    pw = student_auth.password_tag(current.get("password_hash") or "")
    if user["role"] == "student":
        return {
            "token": student_auth.mint_session(
                user["user_id"], user.get("name", ""), account=True, pw=pw
            ),
            "role": "student",
            "tenant_id": tid,
            "student_id": user["user_id"],
            "name": user.get("name", ""),
            "email": user["email"],
            "products": products,
        }
    return {
        "token": principal_mod.mint_principal_token(user["user_id"], user["role"], tid, pw=pw),
        "role": user["role"],
        "tenant_id": tid,
        "name": user.get("name", ""),
        "email": user["email"],
        "products": products,
    }


# ── Staff auth: email + password → principal token (ADR-003, Phase 1.x) ───────
# Professors / admins / operators log in here. Students use student_auth.
# Every method (this, and LTI later) mints the same principal token, which the
# tenant-isolation middleware then enforces. Demo needs no login — anonymous
# requests resolve to the demo principal and keep working.


@router.post("/auth/login")
def auth_login(body: AuthLoginRequest, request: Request):
    email = body.email.strip()
    password = body.password
    _throttle_login(request, email)
    if not email or not password:
        raise HTTPException(status_code=422, detail="email and password are required")
    user = users_mod.authenticate(email, password)
    if not user:
        _record_login_failure(request, email)
        _repo().log_audit(action="login", actor=email, result="denied")
        raise HTTPException(status_code=401, detail="Invalid email or password")
    _repo().log_audit(action="login", tenant_id=user["tenant_id"], actor=user["email"], result="ok")
    return _session_payload(user)


@router.get("/auth/me")
def auth_me(request: Request):
    """Return the authenticated principal, or 401 for anonymous/demo callers."""
    p = getattr(request.state, "principal", None)
    if p is None or p.is_demo:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {
        "user_id": p.user_id,
        "role": p.role,
        "tenant_id": p.tenant_id,
        "auth_method": p.auth_method,
        "products": sorted(p.products),
        # Whether this site can send account email (invites, resets), so
        # the roster screen can offer "email each student".
        "mail": mailer.configured(),
    }


# ── Self-serve accounts (Bluebook public launch, 2026-09) ─────────────────────


@router.post("/auth/signup", status_code=201)
def auth_signup(body: AuthSignupRequest, request: Request):
    """Public teacher signup. Creates a private Bluebook-only workspace (its
    own tenant) and a professor account in it, then signs the teacher in.

    Every attempt counts against a per-IP signup budget, successes included,
    so one client cannot mint workspaces in bulk."""
    if not _signup_open():
        raise HTTPException(
            status_code=403,
            detail=(
                "Collections is invitation-only during the pilot, so new "
                "workspaces can't be created here. If you have been invited, "
                "use the link in your invitation email."
            ),
        )
    _throttle_login(request, "", scope="signup")
    _record_login_failure(request, "", scope="signup")
    email = body.email.strip().lower()
    name = body.name.strip()[:200]
    if not email or "@" not in email or len(email) > 254:
        raise HTTPException(status_code=422, detail="A valid email is required.")
    _check_new_password(body.password)
    if not body.accept_terms:
        raise HTTPException(status_code=422, detail=_TERMS_REQUIRED)
    if _repo().get_user_by_email(email):
        raise HTTPException(status_code=409, detail="An account with that email already exists.")
    tenant_id = f"t-{secrets.token_hex(6)}"
    label = f"{name or email.split('@')[0]}'s workspace"[:200]
    _repo().put_tenant(
        tenant_id,
        label,
        environment="production",
        meta={"plan": SELF_SERVE_PLAN, "created_via": "signup"},
    )
    _repo().set_tenant_products(tenant_id, ["bluebook"])
    principal_mod.invalidate_tenant_cache()
    user = users_mod.create_user(email, body.password, "professor", tenant_id, name)
    _repo().log_audit(
        action="signup",
        tenant_id=tenant_id,
        actor=email,
        result="ok",
        details={"terms_version": TERMS_VERSION},
    )
    return _session_payload(user)


@router.post("/auth/invite/redeem")
def auth_invite_redeem(body: InviteRedeemRequest, request: Request):
    """Redeem a one-time invite: set the password and sign in. A student
    invite also enrols them on the course it was issued for.

    An invited professor (any staff account that has never set a password)
    accepts the terms here, as a signup does: with self-serve signup closed
    this is the only place they can. The check runs before the invite is
    consumed, so a refusal leaves the link usable. Students, and staff
    resetting a password they already set, are unchanged."""
    _throttle_login(request, "", scope="invite")
    _check_new_password(body.password)
    token = body.token.strip()
    pending = invites_mod.find_redeemable(token)
    pending_user = _repo().get_user(pending["user_id"]) if pending else None
    first_activation = bool(pending_user and not users_mod.is_activated(pending_user))
    needs_terms = bool(first_activation and pending_user["role"] != "student")
    # A student ticks the student notice in the browser; record that the server
    # saw it, in the same audit row staff acceptance uses. Not yet required, so
    # an older client without the box still works (consent proper is #286).
    student_terms = bool(
        first_activation and pending_user["role"] == "student" and body.accept_terms
    )
    if needs_terms and not body.accept_terms:
        raise HTTPException(status_code=422, detail=_TERMS_REQUIRED)
    inv = invites_mod.redeem(token)
    user = _repo().get_user(inv["user_id"]) if inv else None
    if not inv or not user:
        _record_login_failure(request, "", scope="invite")
        raise HTTPException(
            status_code=400,
            detail="This invite link is invalid, expired, or already used.",
        )
    users_mod.set_password(user["user_id"], body.password)
    # One link is enough: a student invited to several courses holds one per
    # course (T-78), and the rest must not be able to set the password again.
    _repo().void_invites_for_user(user["user_id"])
    if inv.get("course_id") and user["role"] == "student":
        _repo().put_enrollment(inv["course_id"], user["user_id"], user["tenant_id"])
    _repo().log_audit(
        action="invite_redeem",
        student_id=user["user_id"] if user["role"] == "student" else None,
        tenant_id=user["tenant_id"],
        actor=user["email"],
        result="ok",
        details={"terms_version": TERMS_VERSION} if (needs_terms or student_terms) else None,
    )
    return _session_payload(user)


# ── Course sign-up links (forwardable, 2026-10) ─────────────────────────────
# A teacher can turn on one shareable link per course (original/join_links.py).
# Anyone who opens it creates their own student account and joins the course.
# Unlike a per-email invite it is not tied to one person, so it never takes
# over an account that already has a password.

JOIN_LINK_DEAD = (
    "This sign-up link is not active. It may have been turned off or replaced. "
    "Ask your teacher for the current link."
)
JOIN_EXISTING_ACCOUNT = (
    "An account with this email already exists. Sign in with your email and "
    "password, then open this sign-up link again to join the course. If you "
    "can't sign in, ask your teacher."
)
JOIN_PENDING_INVITE = (
    "Your teacher has already added this email to a course. Use the personal "
    "invite link your teacher sent you to set your password, or ask your "
    "teacher to resend it."
)
JOIN_OTHER_ACCOUNT = (
    "This email can't be used with this sign-up link. Ask your teacher to add you to the course."
)
_JOIN_CONSENT_REQUIRED = (
    "Please tick the box to say you have read the student notice and accept the terms."
)


def join_link_target(token: str) -> tuple[dict, dict] | None:
    """``(link, course)`` for an active link whose course still exists in the
    link's workspace, else None."""
    link = join_links_mod.find_active(token)
    if not link:
        return None
    course = _repo().get_bluebook_course(link["course_id"])
    if not course or course.get("tenant_id") != link["tenant_id"]:
        return None
    return link, course


def join_enrol(link: dict, course: dict, student_id: str, user: dict) -> None:
    """Put ``student_id`` on the link's course, within the free-tier cap.
    Mirrors roster_add: the cap counts only students on no roster yet, and a
    workspace with Original gets the profile record its roster reads."""
    tenant = course["tenant_id"]
    if rules.is_self_serve(_repo().get_tenant(tenant)):
        new = 0 if _repo().list_enrollments_for_student(student_id) else 1
        if _repo().count_enrolled_students(tenant) + new > rules.MAX_ENROLLED_STUDENTS:
            raise HTTPException(
                status_code=403,
                detail="This course is full. Ask your teacher.",
            )
    if "original" in principal_mod.tenant_products(tenant):
        _repo().get_or_create(student_id)
        _repo().set_display_name(
            student_id, user.get("name") or (user.get("email") or "").split("@")[0]
        )
    _repo().put_enrollment(course["id"], student_id, tenant)


@router.post("/auth/join/info")
def auth_join_info(body: JoinLinkInfoRequest, request: Request):
    """What the sign-up screen shows before anyone types: the course and
    its teacher. One answer for every link that cannot be used."""
    _throttle_login(request, "", scope="join")
    target = join_link_target(body.token)
    if not target:
        _record_login_failure(request, "", scope="join")
        raise HTTPException(status_code=404, detail=JOIN_LINK_DEAD)
    link, course = target
    teacher = _repo().get_user(link["created_by"]) or {}
    return {
        "course_name": course.get("name") or "",
        "course_code": course.get("code") or "",
        "teacher_name": teacher.get("name") or "",
    }


@router.post("/auth/join", status_code=201)
def auth_join(body: JoinLinkRequest, request: Request):
    """Create (or finish setting up) a student account from a course sign-up
    link, enrol it on the course, and sign the student in.

    - A new email: the account is created in the course's workspace, with the
      same student id a roster add would give it (derive_student_id).
    - Any email that already has an account is refused: one with a password
      (sign in instead), one the teacher added that has never set a password
      (use the personal invite link), and a teacher's or another workspace's.
      The link only ever sets the password on an account it just created.

    The student must tick the consent box; nothing is created without it.
    Failures count against a per-IP and per-email budget like invite
    redemption; successes do not, so a class on one school network is not
    throttled by its own sign-ups."""
    email = body.email.strip().lower()
    _throttle_login(request, email, scope="join")
    target = join_link_target(body.token)
    if not target:
        _record_login_failure(request, email, scope="join")
        raise HTTPException(status_code=400, detail=JOIN_LINK_DEAD)
    link, course = target
    tenant = course["tenant_id"]
    name = body.name.strip()[:120]
    if not name:
        raise HTTPException(status_code=422, detail="Please enter your name.")
    if not email or "@" not in email or len(email) > 254:
        raise HTTPException(status_code=422, detail="A valid email is required.")
    _check_new_password(body.password)
    if not body.accept_terms:
        raise HTTPException(status_code=422, detail=_JOIN_CONSENT_REQUIRED)

    sid = student_auth.derive_student_id(tenant, email)
    existing = _repo().get_user_by_email(email)
    if existing:
        if users_mod.is_activated(existing):
            _record_login_failure(request, email, scope="join")
            raise HTTPException(status_code=409, detail=JOIN_EXISTING_ACCOUNT)
        if existing["user_id"] != sid or existing["role"] != "student":
            _record_login_failure(request, email, scope="join")
            raise HTTPException(status_code=409, detail=JOIN_OTHER_ACCOUNT)
        # Added by the teacher but never activated: that account belongs to
        # its personal one-time invite. The link must not claim it.
        _record_login_failure(request, email, scope="join")
        raise HTTPException(status_code=409, detail=JOIN_PENDING_INVITE)

    # Cap before anything is written, so a full course creates no account.
    if rules.is_self_serve(_repo().get_tenant(tenant)):
        new = 0 if _repo().list_enrollments_for_student(sid) else 1
        if _repo().count_enrolled_students(tenant) + new > rules.MAX_ENROLLED_STUDENTS:
            raise HTTPException(status_code=403, detail="This course is full. Ask your teacher.")

    try:
        user, created = users_mod.create_student_account(tenant, email, name)
    except ValueError:
        _record_login_failure(request, email, scope="join")
        raise HTTPException(status_code=409, detail=JOIN_OTHER_ACCOUNT) from None
    if not created:
        # Raced with a roster add or another sign-up for this email: only an
        # account this request created may get its password here.
        raise HTTPException(
            status_code=409,
            detail=JOIN_EXISTING_ACCOUNT if users_mod.is_activated(user) else JOIN_PENDING_INVITE,
        )
    users_mod.set_password(user["user_id"], body.password)
    join_enrol(link, course, user["user_id"], user)
    _repo().log_audit(
        action="join_link_signup",
        student_id=user["user_id"],
        tenant_id=tenant,
        actor=user["email"],
        result="ok",
        details={
            "course_id": course["id"],
            "link_id": link["link_id"],
            "terms_version": TERMS_VERSION,
        },
    )
    return _session_payload(_repo().get_user(user["user_id"]) or user)


@router.post("/auth/password")
def auth_change_password(body: PasswordChangeRequest, request: Request):
    """Change your own password (any signed-in account, staff or student).

    Every session issued before the change stops working, this one included
    (T-79), so the reply carries a fresh sign-in for this browser."""
    p = getattr(request.state, "principal", None)
    user = _repo().get_user(p.user_id) if p is not None and not p.is_demo else None
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    _throttle_login(request, user["email"])
    if not users_mod.verify_password(body.current_password, user["password_hash"]):
        _record_login_failure(request, user["email"])
        raise HTTPException(status_code=401, detail="Current password is incorrect.")
    _check_new_password(body.new_password)
    users_mod.set_password(user["user_id"], body.new_password)
    _repo().log_audit(
        action="password_change", tenant_id=user["tenant_id"], actor=user["email"], result="ok"
    )
    return {"ok": True, **_session_payload(user)}


@router.post("/auth/register", status_code=201)
def auth_register(body: AuthRegisterRequest, request: Request):
    """
    Provision a staff user. Privileged: ALWAYS guarded (X-Guard-Token
    required) on a real deploy; open in demo for convenience.

    Unlike every other _require_guard call site, this route sits behind no
    other gate at all on a real deploy (T-64) — the tenant-isolation
    middleware's staff-only path list doesn't cover /auth/*, so the guard
    used to be optional (GUARD_DESTRUCTIVE, unset by default) and self-
    registration of a professor/admin/operator account for an arbitrary
    tenant was anonymously reachable on an unmodified pilot deploy.
    """
    _require_guard(request, force=_api()._IS_REAL_DEPLOY)
    email = body.email.strip()
    password = body.password
    role = body.role
    tenant_id = body.tenant_id.strip()
    name = body.name
    if not email or not password or not tenant_id:
        raise HTTPException(status_code=422, detail="email, password, and tenant_id are required")
    if role not in ("professor", "admin", "operator"):
        raise HTTPException(status_code=422, detail="role must be professor, admin, or operator")
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="password must be at least 8 characters")
    if _repo().get_user_by_email(email):
        raise HTTPException(status_code=409, detail="a user with that email already exists")
    user = users_mod.create_user(email, password, role, tenant_id, name)
    _repo().log_audit(
        action="user_register",
        tenant_id=tenant_id,
        actor=email,
        result="ok",
        details={"role": role},
    )
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "role": role,
        "tenant_id": tenant_id,
    }


# ── Student authentication (converged path) ──────────────────────────────────
# A student signs in with (institution, email). Their id is derived
# deterministically (institution-scoped email hash), their institution is
# auto-registered as a demo tenant, and they receive a signed, stateless
# session token. No password in the demo path — identity is the email +
# institution, which the v1 path can later harden with a real credential.


@router.post("/student-auth/login")
def student_login(body: StudentLoginRequest, request: Request):
    """
    Sign a student in. Body: { email, institution, name? }.

    Derives an institution-scoped student id, ensures the institution exists in
    the tenant registry (auto-provisioned as a demo tenant), creates the
    student record if new, and returns a signed session token.

    Demo-only. On a real deploy it returns 404: it takes no password, so it
    issued a session for any email at any existing institution (student
    impersonation), and it auto-created demo-environment tenants, which are
    anonymously readable. Real students sign in with an account
    (``/auth/login``) or arrive through a signed launch link.
    """
    if _api()._IS_REAL_DEPLOY:
        raise HTTPException(status_code=404, detail="Not found")
    email = body.email.strip()
    institution = body.institution.strip()
    name = body.name.strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="A valid email is required.")
    if not institution:
        raise HTTPException(status_code=422, detail="An institution is required.")

    tenant_id = student_auth.slugify(institution)
    student_id = student_auth.derive_student_id(institution, email)

    # Auto-provision the institution as a demo tenant (idempotent).
    if not _repo().get_tenant(tenant_id):
        _repo().put_tenant(
            tenant_id, institution, environment="demo", meta={"auto_provisioned": "student_login"}
        )

    # Ensure the student record exists so the dashboard has somewhere to read.
    _repo().get_or_create(student_id)
    # Record the display name so the professor roster shows a real person, not
    # the opaque tenant-scoped id.
    _repo().set_display_name(student_id, name or email.split("@")[0])

    token = student_auth.mint_session(student_id, name or email.split("@")[0])
    remote = getattr(request.client, "host", "unknown") if request.client else "unknown"
    _repo().log_audit(
        action="student_login", student_id=student_id, tenant_id=tenant_id, actor=remote
    )
    return {
        "token": token,
        "student_id": student_id,
        "name": name or email.split("@")[0],
        "tenant_id": tenant_id,
        "institution": institution,
    }


@router.get("/student-auth/me")
def student_me(request: Request):
    """
    Resolve the current student from the session token (Authorization: Bearer
    <token> or X-Student-Token header). 401 if missing/invalid/expired.
    """
    auth = request.headers.get("Authorization", "")
    token = (
        auth[7:]
        if auth.lower().startswith("bearer ")
        else request.headers.get("X-Student-Token", "")
    )
    session = student_auth.verify_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return {"student_id": session["sid"], "name": session.get("name", "")}


@router.post("/api/v1/auth/login")
def demo_login(body: DemoLoginRequest, request: Request):
    """
    Demo login endpoint.

    Maintenance backdoor: set MAINTENANCE_TOKEN env var to a strong random
    string. When the password matches, grants admin role and writes an audit
    log warning. Never hardcoded — rotate without a code deploy.

    Demo role routing (no real auth — demo only):
      'admin' in email → admin role
      'student' in email → student role
      anything else → professor role
    """
    # Demo-only surface: the tokens it mints are decorative (no real principal),
    # but leaving a role-granting login mounted on a real deploy is an
    # unnecessary attack surface. Real deploys use /auth/login and /lti/*.
    if _api()._IS_REAL_DEPLOY:
        raise HTTPException(status_code=404, detail="Not found")

    username = body.email or body.username
    password = body.password
    remote = getattr(request.client, "host", "unknown") if request.client else "unknown"

    # Maintenance backdoor — env var only, always audited.
    # hmac.compare_digest() is constant-time: prevents timing-oracle attacks
    # where an attacker measures response latency to guess the token byte-by-byte.
    if _api()._MAINTENANCE_TOKEN and hmac.compare_digest(
        password.encode(), _api()._MAINTENANCE_TOKEN.encode()
    ):
        _audit_maintenance_access(username or "__maintenance__", remote)
        return {
            "token": "maintenance-token",
            "role": "admin",
            "name": username or "Maintenance",
        }

    # Demo role routing (for the demo dashboard — not production auth)
    if "admin" in username.lower():
        role = "admin"
    elif "student" in username.lower():
        role = "student"
    else:
        role = "professor"

    return {"token": "demo-token", "role": role, "name": username or "Demo User"}


@router.post("/auth/password-reset/request")
def auth_password_reset_request(body: PasswordResetRequest, request: Request):
    """Email a one-time password-reset link. The response is identical
    whether or not the address has an account, so the form cannot reveal
    who is registered; it only says whether this site can send email at all
    (a public configuration fact) so the screen can point students to their
    teacher instead. Counted against its own per-IP and per-email budget."""
    email = (body.email or "").strip().lower()
    _throttle_login(request, email, scope="reset")
    _record_login_failure(request, email, scope="reset")
    configured = mailer.configured()
    user = _repo().get_user_by_email(email) if configured and "@" in email else None
    if user is not None:
        inv = invites_mod.issue(user["tenant_id"], user["user_id"], user["user_id"], reset=True)
        path = inv["invite_path"].replace("?invite=", "?reset=")
        sent = mailer.send_reset(email, mailer.absolute_url(path, str(request.base_url)))
        _repo().log_audit(
            action="password_reset_request",
            tenant_id=user["tenant_id"],
            student_id=user["user_id"] if user["role"] == "student" else None,
            actor=email,
            result="ok" if sent else "send_failed",
        )
    return {"ok": True, "mail": configured}
