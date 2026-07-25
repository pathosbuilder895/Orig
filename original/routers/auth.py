"""Staff / student / demo authentication, moved verbatim from original/api.py."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, HTTPException, Request

from .. import principal as principal_mod
from .. import student_auth
from .. import users as users_mod
from ..schemas import (
    AuthLoginRequest,
    AuthRegisterRequest,
    DemoLoginRequest,
    StudentLoginRequest,
)
from ._shared import (
    _api,
    _audit_maintenance_access,
    _repo,
    _require_guard,
    _throttle_login,
)

router = APIRouter()


# ── Staff auth: email + password → principal token (ADR-003, Phase 1.x) ───────
# Professors / admins / operators log in here. Students use student_auth.
# Every method (this, and LTI later) mints the same principal token, which the
# tenant-isolation middleware then enforces. Demo needs no login — anonymous
# requests resolve to the demo principal and keep working.


@router.post("/auth/login")
def auth_login(body: AuthLoginRequest, request: Request):
    _throttle_login(request)
    email = body.email.strip()
    password = body.password
    if not email or not password:
        raise HTTPException(status_code=422, detail="email and password are required")
    user = users_mod.authenticate(email, password)
    if not user:
        _repo().log_audit(action="login", actor=email, result="denied")
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = principal_mod.mint_principal_token(user["user_id"], user["role"], user["tenant_id"])
    _repo().log_audit(action="login", tenant_id=user["tenant_id"], actor=user["email"], result="ok")
    return {
        "token": token,
        "role": user["role"],
        "tenant_id": user["tenant_id"],
        "name": user["name"],
        "email": user["email"],
    }


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
    }


@router.post("/auth/register", status_code=201)
def auth_register(body: AuthRegisterRequest, request: Request):
    """
    Provision a staff user. Privileged: guarded by GUARD_DESTRUCTIVE in
    pilot/production (X-Guard-Token required); open in demo for convenience.
    """
    _require_guard(request)
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
    """
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
async def demo_login(body: DemoLoginRequest, request: Request):
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
