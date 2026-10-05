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
  2. Student **session** token (``student_auth.verify_session``). An
     account-backed session (``acct`` claim) is revoked once its ``users``
     row is gone — see ``_account_session_live``.
  3. **Demo / anonymous** fallback.

The signed-token scheme reuses ``student_auth``'s HMAC(SECRET_KEY) signing so
there is a single signing secret across the system.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from urllib.parse import unquote

from . import student_auth

log = logging.getLogger(__name__)

DEMO_TENANT = "demo"

# Roles that are cross-tenant by design (the operator "all schools" view).
SUPER_ROLES = frozenset({"operator", "super_admin"})

# Namespaced tenants whose student data the anonymous demo may read. Only
# tenants explicitly registered as "demo" qualify. Everything else — pilot,
# production, OR an unknown/unregistered tenant — is treated as real data and
# is hidden from anonymous callers (fail closed). Flat (non-namespaced) ids are
# the demo sandbox and are always readable; they never reach this check.
DEMO_VISIBLE_ENVIRONMENTS = frozenset({"demo"})

# Deploy modes where anonymous/demo access must never touch student data at
# all — mirrors api.py's _IS_REAL_DEPLOY.
_REAL_DEPLOY_ENVIRONMENTS = frozenset({"pilot", "staging", "production"})


def _is_real_deploy() -> bool:
    """Whether this process is a real (non-demo) deploy.

    Deferred, function-scoped import of ``original.api`` (not a module-level
    one — api.py already imports this module, so a top-level import here
    would cycle; ``get_repository()``'s lazy postgres_repository import is
    the same pattern for the same reason). Preferring api_mod._IS_REAL_DEPLOY
    over re-reading ORIGINAL_ENV directly keeps this in lockstep with the
    single source of truth every existing test already monkeypatches
    (``tests/test_pilot_lockdown.py``'s ``real_deploy`` fixture and its
    siblings) — two independently-computed "is this a real deploy" checks
    that could silently drift apart would be exactly the kind of gap this
    function exists to close. Falls back to reading the env var directly if
    api.py can't be imported (e.g. a unit test that never loads the app).
    """
    try:
        from . import api as api_mod

        return api_mod._IS_REAL_DEPLOY
    except ImportError:
        return os.environ.get("ORIGINAL_ENV") in _REAL_DEPLOY_ENVIRONMENTS


# Products a tenant can hold (Bluebook self-serve, 2026-09). A row that
# predates the products column, or whose products are unset, holds both — so
# nothing that worked before the column existed stops working. A tenant with
# no record (or a failed lookup) holds both only off a real deploy; on one it
# keeps its last known products, else Bluebook alone (see tenant_products).
ALL_PRODUCTS = frozenset({"original", "bluebook"})


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: str  # student | professor | admin | operator | super_admin | demo
    tenant_id: str  # "demo" for the anonymous sandbox
    auth_method: str  # "demo" | "session" | "principal-token" | "revoked"
    is_demo: bool = False
    # What the principal's tenant bought. Resolved per request from the
    # tenant record (cached, see tenant_products); enforced by the product
    # gate in api.py's tenant_isolation middleware.
    products: frozenset = ALL_PRODUCTS


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


def verify_principal_token(token: str) -> dict | None:
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


def tenant_of(student_id: str) -> str | None:
    """Tenant slug prefix before ':' — or None for a legacy flat id."""
    if not student_id or ":" not in student_id:
        return None
    return student_id.split(":", 1)[0]


_ENV_CACHE: dict[str, str | None] = {}
# tenant -> (products, expires_at on _clock, from_lookup). Entries expire
# because an operator script run from Render's shell writes the products row
# from another process and cannot clear this cache; the expiry is what lets
# that change reach the gate without a restart. ``from_lookup`` is True only
# for a value that came from a successful lookup (or a reuse of one), so a
# failed refresh can tell a real "last known" value from a cached fallback.
_PRODUCTS_CACHE: dict[str, tuple[frozenset, float, bool]] = {}
_PRODUCTS_CACHE_TTL_SECONDS = 30
# A failed lookup's fallback is cached only this long, so the next request
# soon tries the database again.
_PRODUCTS_RETRY_SECONDS = 5
_clock = time.monotonic


def invalidate_tenant_cache() -> None:
    """Clear the tenant→environment and tenant→products caches (call after a
    tenant is registered or its products change)."""
    _ENV_CACHE.clear()
    _PRODUCTS_CACHE.clear()


def tenant_products(tenant_id: str | None) -> frozenset:
    """Products the tenant holds. Cached for _PRODUCTS_CACHE_TTL_SECONDS.

    A record without products set predates the column and holds both. When
    the lookup fails or finds no record — indistinguishable on Postgres, whose
    get_tenant logs a database error and returns None — this fails closed: the
    tenant's last known products (even an expired entry), else Bluebook alone
    on a real deploy, so a database blip never grants Original to a
    Bluebook-only workspace. Off a real deploy the demo sandbox relies on
    unregistered tenants holding both, so they still do. Either fallback is
    cached for _PRODUCTS_RETRY_SECONDS only."""
    if not tenant_id or tenant_id == DEMO_TENANT:
        return ALL_PRODUCTS
    now = _clock()
    cached = _PRODUCTS_CACHE.get(tenant_id)
    if cached is not None and now < cached[1]:
        return cached[0]
    products = None
    try:
        from .repository import get_repository

        rec = get_repository().get_tenant(tenant_id)
        if rec is not None:
            products = frozenset(rec.get("products") or ()) & ALL_PRODUCTS or ALL_PRODUCTS
    except Exception:
        products = None
    if products is not None:
        _PRODUCTS_CACHE[tenant_id] = (products, now + _PRODUCTS_CACHE_TTL_SECONDS, True)
        return products
    real_deploy = _is_real_deploy()
    if cached is not None:
        # Reuse whatever is cached; call it "last known" only if it came from
        # a successful lookup, not from an earlier fallback.
        products, from_lookup = cached[0], cached[2]
        using = "last known" if from_lookup else ("bluebook only" if real_deploy else "all (demo)")
    else:
        from_lookup = False
        if real_deploy:
            products, using = frozenset({"bluebook"}), "bluebook only"
        else:
            products, using = ALL_PRODUCTS, "all (demo)"
    log.warning("tenant products lookup failed for %s; using %s", tenant_id, using)
    _PRODUCTS_CACHE[tenant_id] = (products, now + _PRODUCTS_RETRY_SECONDS, from_lookup)
    return products


def tenant_environment(slug: str) -> str | None:
    """Registered environment ('demo'/'pilot'/'production') or None if unknown. Cached."""
    if slug in _ENV_CACHE:
        return _ENV_CACHE[slug]
    env: str | None = None
    try:
        from .repository import get_repository

        rec = get_repository().get_tenant(slug)
        if rec:
            env = rec.get("environment")
    except Exception:
        env = None
    _ENV_CACHE[slug] = env
    return env


# ── Identity resolution ────────────────────────────────────────────────────────

# A validly signed student session whose account has since been erased. It
# must not fall back to the demo principal (off a real deploy that is the
# operator), so it resolves to an identity that matches no student id, no
# tenant, no staff role, and no product; the isolation middleware answers
# it with 401 before any handler runs.
REVOKED = Principal(
    user_id="",
    role="revoked",
    tenant_id="",
    auth_method="revoked",
    products=frozenset(),
)


def _account_session_live(sid: str) -> bool:
    """Whether an account-backed student session's login still exists.

    One primary-key lookup, paid only by sessions carrying the ``acct``
    claim (password login / invite redemption). Signed launch-link, LTI and
    demo sessions have no ``users`` row by design and never reach here. A
    lookup failure fails closed: this is an authorization check."""
    try:
        from .repository import get_repository

        user = get_repository().get_user(sid)
    except Exception:
        return False
    return user is not None and user.get("role") == "student"


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
            tid = str(body["tid"])
            return Principal(
                user_id=str(body["sub"]),
                role=str(body.get("role", "professor")),
                tenant_id=tid,
                auth_method="principal-token",
                products=tenant_products(tid),
            )
        # 2) Student session
        sess = student_auth.verify_session(tok)
        if sess:
            sid = str(sess.get("sid", ""))
            if sess.get("acct") and not _account_session_live(sid):
                return REVOKED
            tid = tenant_of(sid) or DEMO_TENANT
            return Principal(
                user_id=sid,
                role="student",
                tenant_id=tid,
                auth_method="session",
                products=tenant_products(tid),
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
        if _is_real_deploy():
            # On a real deploy, the ONLY anonymous carve-out left standing is
            # a tenant explicitly REGISTERED with environment="demo" — a
            # verified repository lookup (registering one itself requires
            # _require_guard on POST /tenants on a real deploy, so it's not
            # casually reachable). Flat ids (t is None) and the bare "demo"
            # tenant string (t == DEMO_TENANT) get no such verification —
            # they read as "demo sandbox" purely from the id's shape, which
            # is an invariant of how *legitimate* write paths behave, not
            # something this function can verify from the id alone (T-66).
            # If that assumption is ever violated (a bug elsewhere, or a
            # crafted request), trusting the id shape would make that
            # student's record readable, writable, and deletable by any
            # anonymous caller — so those two cases fail closed here even
            # though they're allowed below on a non-real deploy.
            if (
                t is not None
                and t != DEMO_TENANT
                and tenant_environment(t) in DEMO_VISIBLE_ENVIRONMENTS
            ):
                return
            raise TenantAccessError("anonymous access is not permitted on a real deploy")
        if t is None or t == DEMO_TENANT:
            return
        if tenant_environment(t) in DEMO_VISIBLE_ENVIRONMENTS:
            return
        raise TenantAccessError(f"demo principal cannot access tenant '{t}' (real data)")

    # Authenticated principals
    if principal.role in SUPER_ROLES:
        return  # operator / super-admin: cross-tenant by design

    # A student may only touch their OWN record (ADR-005). Scoping a student to
    # the whole tenant would let a logged-in student read a classmate's profile
    # via GET /students/<sameTenant:other> — a horizontal-authorization hole.
    # Staff roles (professor/admin) keep tenant-wide access below.
    if principal.role == "student":
        if student_id == principal.user_id:
            return
        raise TenantAccessError(f"student {principal.user_id} cannot access '{student_id}'")

    if t is not None and t == principal.tenant_id:
        return
    raise TenantAccessError(f"{principal.role}@{principal.tenant_id} cannot access '{student_id}'")


def assert_tenant_access(principal: Principal, tenant_id: str) -> None:
    """Raise ``TenantAccessError`` if ``principal`` may not read ``tenant_id``'s record.

    A staff principal may always read their own institution's tenant record.
    Cross-tenant reads require operator/super_admin (the "all schools"
    registry view — see ``SUPER_ROLES``). Callers are expected to have
    already rejected non-staff principals (e.g. via ``_require_staff``).
    """
    if principal.role in SUPER_ROLES:
        return  # operator / super-admin: cross-tenant by design
    if tenant_id == principal.tenant_id:
        return
    raise TenantAccessError(
        f"{principal.role}@{principal.tenant_id} cannot access tenant '{tenant_id}'"
    )


def extract_scoped_id(path: str) -> str | None:
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
