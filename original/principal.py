"""
principal.py — request identity + tenant-isolation enforcement (ADR-003, Phase 1).

Design goals
────────────
* **Additive & demo-safe.** With no credentials, every request resolves to an
  anonymous *demo* principal that keeps today's behaviour: the synthetic demo
  sandbox (flat student ids) and demo-environment tenants stay fully readable,
  so the zero-login sales demo is untouched.
* **Real tenants are isolated.** An authenticated, non-super principal can only
  touch student ids under its own ``{tenant_id}:`` prefix. Pilot/production
  tenant data is invisible to the anonymous demo.

Enforcement is centralised in a single middleware (see ``api.py``) rather than
sprinkled across endpoints, so the demo cannot silently break and there is one
place to audit.

Identity sources, in priority order (``resolve_principal``):
  1. Signed **principal token** (professor / admin / operator) — issued by the
     email/password or LTI login (Phase 1.x). Carries ``{sub, role, tid}``.
  2. Student **session** token (``student_auth.verify_session``).
  3. **Demo / anonymous** fallback.

The signed-token scheme reuses ``student_auth``'s HMAC(SECRET_KEY) signing so
there is a single signing secret across the system.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import unquote

from . import student_auth

DEMO_TENANT = "demo"

# Roles that are cross-tenant by design (the operator "all schools" view).
SUPER_ROLES = frozenset({"operator", "super_admin"})

# Namespaced tenants whose student data the anonymous demo may read. Only
# tenants explicitly registered as "demo" qualify. Everything else — pilot,
# production, OR an unknown/unregistered tenant — is treated as real data and
# is hidden from anonymous callers (fail closed). Flat (non-namespaced) ids are
# the demo sandbox and are always readable; they never reach this check.
DEMO_VISIBLE_ENVIRONMENTS = frozenset({"demo"})


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: str            # student | professor | admin | operator | super_admin | demo
    tenant_id: str       # "demo" for the anonymous sandbox
    auth_method: str     # "demo" | "session" | "principal-token"
    is_demo: bool = False


class TenantAccessError(PermissionError):
    """Raised when a principal attempts to access another tenant's data."""


# ── Signed principal token (professor / admin / operator) ─────────────────────

def _secret() -> bytes:
    # Shares the signing secret with student_auth; same dev fallback so the demo
    # works without SECRET_KEY (startup warns when it's unset).
    return (os.environ.get("SECRET_KEY") or "demo-insecure-student-secret").encode()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(payload: str) -> str:
    return _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())


def mint_principal_token(
    user_id: str, role: str, tenant_id: str, ttl_seconds: int = 8 * 3600
) -> str:
    """Mint a signed token for a professor/admin/operator principal.

    Phase 1.x (email/password) and Phase 1.5 (LTI) both call this after
    verifying credentials, so every auth method terminates in the same token.
    """
    body = {
        "sub": user_id,
        "role": role,
        "tid": tenant_id,
        "exp": int(time.time()) + ttl_seconds,
    }
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    return f"{payload}.{_sign(payload)}"


def verify_principal_token(token: str) -> Optional[Dict]:
    """Return ``{sub, role, tid, exp}`` if valid+unexpired, else None."""
    if not token or "." not in token:
        return None
    payload, sig = token.split(".", 1)
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    try:
        body = json.loads(_unb64(payload))
    except Exception:
        return None
    if not isinstance(body, dict) or "sub" not in body or "tid" not in body:
        return None
    if float(body.get("exp", 0)) < time.time():
        return None
    return body


# ── Tenant helpers ────────────────────────────────────────────────────────────

def tenant_of(student_id: str) -> Optional[str]:
    """Tenant slug prefix before ':' — or None for a legacy flat id."""
    if not student_id or ":" not in student_id:
        return None
    return student_id.split(":", 1)[0]


_ENV_CACHE: Dict[str, Optional[str]] = {}


def invalidate_tenant_cache() -> None:
    """Clear the tenant→environment cache (call after a tenant is registered)."""
    _ENV_CACHE.clear()


def tenant_environment(slug: str) -> Optional[str]:
    """Registered environment ('demo'/'pilot'/'production') or None if unknown. Cached."""
    if slug in _ENV_CACHE:
        return _ENV_CACHE[slug]
    env: Optional[str] = None
    try:
        from . import store
        rec = store.get_tenant(slug)
        if rec:
            env = rec.get("environment")
    except Exception:
        env = None
    _ENV_CACHE[slug] = env
    return env


# ── Identity resolution ────────────────────────────────────────────────────────

def _bearer(request) -> str:
    h = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if h.lower().startswith("bearer "):
        return h[7:].strip()
    return request.headers.get("x-session-token") or ""


def resolve_principal(request) -> Principal:
    """Resolve the request's principal. Never raises — falls back to demo."""
    tok = _bearer(request)

    # 1) Signed principal token (professor / admin / operator)
    if tok:
        body = verify_principal_token(tok)
        if body:
            return Principal(
                user_id=str(body["sub"]),
                role=str(body.get("role", "professor")),
                tenant_id=str(body["tid"]),
                auth_method="principal-token",
            )
        # 2) Student session
        sess = student_auth.verify_session(tok)
        if sess:
            sid = str(sess.get("sid", ""))
            return Principal(
                user_id=sid,
                role="student",
                tenant_id=tenant_of(sid) or DEMO_TENANT,
                auth_method="session",
            )

    # 3) Demo / anonymous sandbox
    role = request.headers.get("x-demo-role") or "operator"
    return Principal(
        user_id="demo",
        role=role,
        tenant_id=DEMO_TENANT,
        auth_method="demo",
        is_demo=True,
    )


# ── Authorization ──────────────────────────────────────────────────────────────

def assert_student_access(principal: Principal, student_id: str) -> None:
    """Raise ``TenantAccessError`` if ``principal`` may not touch ``student_id``."""
    t = tenant_of(student_id)

    if principal.is_demo:
        # Anonymous demo sandbox: flat ids, the reserved "demo:" namespace, and
        # tenants explicitly registered as "demo".
        if t is None or t == DEMO_TENANT:
            return
        if tenant_environment(t) in DEMO_VISIBLE_ENVIRONMENTS:
            return
        raise TenantAccessError(
            f"demo principal cannot access tenant '{t}' (real data)"
        )

    # Authenticated principals
    if principal.role in SUPER_ROLES:
        return  # operator / super-admin: cross-tenant by design
    if t is not None and t == principal.tenant_id:
        return
    raise TenantAccessError(
        f"{principal.role}@{principal.tenant_id} cannot access '{student_id}'"
    )


def extract_scoped_id(path: str) -> Optional[str]:
    """Return the tenant-scoped identity id embedded in a request path, else None.

    Covers ``/students/{id}/...`` and ``/canvas/baseline/{id}/...``. The list
    endpoint ``/students`` (no id) returns None and is scoped in its handler.
    """
    parts = [unquote(p) for p in path.split("/") if p]
    if len(parts) >= 2 and parts[0] == "students":
        return parts[1]
    if len(parts) >= 3 and parts[0] == "canvas" and parts[1] == "baseline":
        return parts[2]
    return None
