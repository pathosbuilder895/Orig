"""
api.py — FastAPI application for the dashboard demo and pilot-compatible server.

Endpoints
─────────
GET  /health
GET  /students                                      list all student IDs
GET  /students/{id}                                 student state summary
POST /students/{id}/baseline                        add a baseline sample (text)
POST /students/{id}/baseline/upload-batch           add multiple files as baseline
POST /students/{id}/score                           score a submission → Layer 7
POST /students/{id}/upload                          extract text from a single file
POST /import/courses/{course_id}/turnitin-csv       import Turnitin CSV export
POST /canvas/baseline/{id}/list-canvas-submissions  list past Canvas submissions for student
POST /canvas/baseline/{id}/import-baseline          import selected Canvas submissions as baseline

In demo mode, anonymous sandbox access remains available for the seeded sales
demo. In pilot/production modes, real tenant data is protected by the Principal
tenant-isolation middleware, stable SECRET_KEY requirement, locked CORS, and
guarded destructive operations.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import backup as backup_mod
from . import principal as principal_mod

# `store` itself: no call site in this module reaches it directly anymore
# (WS-6 P1 — all persistence goes through `_repo()`). Kept as a re-export
# because several tests patch `<api module>.store._DB_PATH` / call
# `<api module>.store.*` directly for fixture setup.
from . import (
    store,  # noqa: F401
)
from .routers import (
    admin,
    auth,
    bluebook,
    health,
    imports,
    lti_routes,
    me,
    proctor,
    students,
    students_baseline,
    students_scoring,
    tenants,
)

# Helpers and shared state that moved to original/routers/_shared.py in the WS-7.3
# router split. Re-imported here because `original.api.<helper>` is still a live
# call site: scripts/seed_pilot.py, and tests that reach into the app module.
from .routers._shared import (
    _LOGIN_MAX_ATTEMPTS,  # noqa: F401
    _LOGIN_WINDOW_SEC,  # noqa: F401
    _MAGIC_SESSION_TTL,  # noqa: F401
    _STAFF_ROLES,  # noqa: F401
    _TRUSTED_PROVENANCE,  # noqa: F401
    _audit_maintenance_access,  # noqa: F401
    _authorize_provenance,  # noqa: F401
    _bluebook_tenant,  # noqa: F401
    _int_or,  # noqa: F401
    _login_attempts,  # noqa: F401
    _persist_or_503,  # noqa: F401
    _render_launch_localstorage,  # noqa: F401
    _repo,  # noqa: F401
    _require_guard,  # noqa: F401
    _require_staff,  # noqa: F401
    _require_student_session,  # noqa: F401
    _send_notification_email,  # noqa: F401
    _throttle_login,  # noqa: F401
    _to_response,  # noqa: F401
    log_email_sender_status,  # noqa: F401
)

# Re-exported: scripts/seed_pilot.py binds original.api.add_baseline /
# original.api.score_submission to drive ingestion in-process.
from .routers.students_baseline import add_baseline  # noqa: F401
from .routers.students_scoring import score_submission  # noqa: F401

# NOTE: .env is loaded by the run.py entrypoint (not at import) so importing the
# app in tests/other contexts never pollutes os.environ for the v1 Settings.

# Deployment mode for the legacy/demo app: "demo" (default, zero-login sandbox),
# "pilot", or "production". Controls CORS defaults, the SECRET_KEY fail-fast,
# and security headers. Distinct from the v1 app's ENVIRONMENT setting.
ORIGINAL_ENV = os.environ.get("ORIGINAL_ENV", "demo").strip().lower()
_IS_REAL_DEPLOY = ORIGINAL_ENV in ("pilot", "staging", "production")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _log = logging.getLogger(__name__)
    if not _secret_key_pinned:
        if _IS_REAL_DEPLOY:
            # Fail closed: a random per-process key silently invalidates every
            # token on restart and is unacceptable outside the demo sandbox.
            raise RuntimeError(
                f"ORIGINAL_ENV={ORIGINAL_ENV} requires a stable SECRET_KEY. "
                "Set it in the environment or .env: "
                'python -c "import secrets; print(secrets.token_urlsafe(64))"'
            )
        _log.warning(
            "SECRET_KEY is not set — using a per-process random value. "
            "JWTs will be invalidated on every restart. "
            "Set SECRET_KEY in your environment or .env file for a stable key: "
            '  python -c "import secrets; print(secrets.token_urlsafe(64))"'
        )
    else:
        _log.info("SECRET_KEY is pinned from environment — JWT tokens survive restarts.")
    _log.info("ORIGINAL_ENV=%s — CORS=%s", ORIGINAL_ENV, _ALLOWED_ORIGINS)
    _log.info(
        "GUARD_DESTRUCTIVE=%s — destructive endpoints are %s.",
        _GUARD_DESTRUCTIVE,
        "GUARDED (X-Guard-Token required)" if _GUARD_DESTRUCTIVE else "open (demo mode)",
    )
    # Tells an operator who exported SENDGRID_API_KEY that no email is sent.
    # No-ops when the key is unset. See routers/_shared.py.
    log_email_sender_status()
    _ai_mode = (
        "enabled"
        if os.environ.get("AI_LIKELIHOOD_ENABLED") == "1"
        else "shadow"
        if os.environ.get("AI_LIKELIHOOD_SHADOW") == "1"
        else None
    )
    if _ai_mode:
        from .ai_likelihood import warm as _ai_warm

        _log.info(
            "AI-likelihood detector mode=%s — %s.",
            _ai_mode,
            "ready" if _ai_warm() else "unavailable (see warning above)",
        )
    # In-app backup scheduler — production has no crontab (Render web service),
    # so the periodic consistent .backup runs inside this process. Demo stays
    # off unless BACKUP_DIR is set explicitly. See original/backup.py.
    #
    # After the P5 Postgres cutover the authoritative store is Postgres, whose
    # backups are managed externally (Render managed + pg_dump — see
    # OPS_RUNBOOK), and PostgresRepository.db_path() has no SQLite file to
    # point at. Skip the in-app scheduler entirely in that case rather than
    # crash startup on the NotImplementedError.
    _backup_task = None
    try:
        _db_path = _repo().db_path()
    except NotImplementedError:
        _db_path = None
        _log.info(
            "Backups: in-app SQLite scheduler off (Postgres backend; backups managed externally)."
        )
    _bdir = backup_mod.resolve_backup_dir(_db_path, _IS_REAL_DEPLOY) if _db_path else None
    if _bdir is not None:
        _interval = float(os.environ.get("BACKUP_INTERVAL_MINUTES", "30") or 30)
        _keep = int(os.environ.get("BACKUP_KEEP", "48") or 48)
        _backup_task = asyncio.create_task(
            backup_mod.backup_loop(_db_path, _bdir, _interval, _keep)
        )
        _log.info("Backups: every %.0f min to %s (keep %d).", _interval, _bdir, _keep)
    elif _db_path is not None:
        _log.info("Backups: disabled (demo mode, no BACKUP_DIR set).")
    yield
    if _backup_task is not None:
        _backup_task.cancel()


def _resolve_app_version() -> str:
    """pyproject.toml is the single source of truth (D7) — read via package
    metadata rather than hardcoding a second literal here. Most real
    environments (a bare checkout, `python run.py`) never run
    `pip install -e .`, so package metadata is routinely absent; in that case
    parse pyproject.toml directly rather than silently falling back to a
    second hand-maintained literal that can drift from it. The bare literal
    below is a last resort for the case pyproject.toml itself is unreadable
    (e.g. a stripped-down deployment artifact)."""
    try:
        return importlib.metadata.version("original")
    except importlib.metadata.PackageNotFoundError:
        pass
    try:
        pyproject_text = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
        match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject_text)
        if match:
            return match.group(1)
    except OSError:
        pass
    return "0.1.0"


app = FastAPI(
    title="Original — Authorship Integrity API",
    version=_resolve_app_version(),
    description="Quantum stylometric authorship analysis for seminary submissions.",
    lifespan=lifespan,
)


# CORS: demo allows any origin; pilot/production must list origins explicitly
# via ALLOWED_ORIGINS (comma-separated). Falls back to "*" only in demo.
def _resolve_allowed_origins():
    raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if raw:
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        if _IS_REAL_DEPLOY and "*" in origins:
            # An operator typing ALLOWED_ORIGINS=* would silently reopen the
            # exact hole the empty-default closes. Fail loudly at boot instead.
            raise RuntimeError(
                "ALLOWED_ORIGINS must list explicit https origins on a real "
                "deploy — a '*' wildcard is not allowed when "
                f"ORIGINAL_ENV={ORIGINAL_ENV}."
            )
        return origins
    if _IS_REAL_DEPLOY:
        return []  # locked down: no origin allowed until configured
    return ["*"]


_ALLOWED_ORIGINS = _resolve_allowed_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Security headers ──────────────────────────────────────────────────────────
# Always-safe headers on every response. HSTS is opt-in (ENABLE_HSTS=1) since it
# only makes sense once TLS terminates in front of the app. X-Frame-Options is
# SAMEORIGIN (not DENY) so LTI launches can render inside an LMS that we allow
# via a CSP frame-ancestors directive at deploy time.
_ENABLE_HSTS = os.environ.get("ENABLE_HSTS", "0") == "1"


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # LTI launches render inside the LMS iframe, so don't frame-block them.
    # (Restrict embedders at deploy time via a CSP frame-ancestors directive.)
    if not request.url.path.startswith("/lti/"):
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    if _ENABLE_HSTS:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return resp


# ── Tenant-isolation middleware (ADR-003, Phase 1) ────────────────────────────
# Resolves the request principal once and enforces tenant boundaries on every
# student-scoped path in ONE place. Additive by construction: with no
# credentials the principal is the anonymous demo principal, which is allowed
# over flat ids + demo-environment tenants — i.e. today's demo is unchanged.
# Real (pilot/production) tenant data is only reachable by an authenticated
# principal of that tenant (or a super/operator role). See original/principal.py.

# Unscoped surfaces that must never be anonymously readable outside demo:
# rosters, audit logs, manifests, corrections, calibration, tenant registry,
# proctoring queues, bulk import, and the internal scoring test endpoint.
# extract_scoped_id() can't cover these (no student id in the path), so on
# real deploys the middleware requires an authenticated staff principal.
# /submissions/{id}/correct also lives here: its path carries a submission id,
# not a student id, so the middleware blocks anonymous/student callers on real
# deploys while the handler adds staff-role + tenant scoping in every env.
_STAFF_ONLY_EXACT = frozenset({"/students", "/tenants", "/baseline-requests", "/test/score"})
_STAFF_ONLY_PREFIXES = (
    "/admin/",
    "/tenants/",
    "/baseline-requests/",
    "/import/",
    "/submissions/",
)

# Demo-only static artifacts that must not be downloadable from a real deploy:
# the synthetic seed database, internal lab/playground/admin pages, and
# validation report JSONs. They live in demo/ because the demo serves them;
# the pilot serves the same directory, so the app blocks them by path.
# admin-context.html is internal tooling with no access control of its own
# (same Research-nav family as the already-gated lab.html/playground.html);
# onboard.html has zero inbound links from the rest of the demo (dead page).
# NOT gated: student-coach.html (student.html actively window.open()s it) and
# operator.html (index.html redirects operator-role sign-ins there, so a real
# deploy needs it reachable; its data comes from /admin/* and /tenants/*
# endpoints that the staff-only middleware already protects).
_DEMO_ONLY_STATICS = frozenset(
    {
        "/seed.db",
        "/lab.html",
        "/playground.html",
        "/admin-context.html",
        "/onboard.html",
        "/validation_report.json",
        "/validation_similarity.json",
        "/validation_thresholds.json",
    }
)
_DEMO_ONLY_STATIC_PREFIXES = frozenset({"/prototypes"})


def _is_demo_only_static_path(path: str) -> bool:
    """Return whether *path* belongs to a demo-only static surface.

    Exact-file gates cover the legacy one-off artifacts above. Prefix gates
    cover self-contained prototype directories, including their index pages,
    JavaScript modules, stylesheets, images, and any future nested assets. The
    explicit path-boundary check avoids accidentally hiding a legitimate path
    such as ``/prototypes-public``.
    """
    normalized = path.rstrip("/") or "/"
    if normalized in _DEMO_ONLY_STATICS:
        return True
    return any(
        normalized == prefix or normalized.startswith(f"{prefix}/")
        for prefix in _DEMO_ONLY_STATIC_PREFIXES
    )


def _is_staff_only_path(path: str) -> bool:
    p = path.rstrip("/") or "/"
    return p in _STAFF_ONLY_EXACT or path.startswith(_STAFF_ONLY_PREFIXES)


@app.middleware("http")
async def tenant_isolation(request: Request, call_next):
    principal = principal_mod.resolve_principal(request)
    request.state.principal = principal
    if _IS_REAL_DEPLOY and _is_demo_only_static_path(request.url.path):
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    if _IS_REAL_DEPLOY and _is_staff_only_path(request.url.path):
        if principal.is_demo or principal.role == "student":
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required — sign in with a staff account."},
            )
    scoped_id = principal_mod.extract_scoped_id(request.url.path)
    if scoped_id is not None:
        try:
            principal_mod.assert_student_access(principal, scoped_id)
        except principal_mod.TenantAccessError:
            return JSONResponse(
                status_code=403,
                content={"detail": "Cross-tenant access denied."},
            )
    return await call_next(request)


# ── Maintenance-mode write freeze (WS-6 P5 cutover) ───────────────────────────
# During the P5 cutover window the operator sets MAINTENANCE_MODE=1 to freeze
# writes while the final SQLite→Postgres sync runs and get_repository() is
# flipped, so the two stores can't diverge mid-copy. Reads stay open (GET/HEAD/
# OPTIONS) so /health and monitoring keep working. Read at request time so the
# flag takes effect on the env-var flip's restart (and is unit-testable).
# Off (unset) by default — this is inert until an operator opens a window.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@app.middleware("http")
async def maintenance_write_freeze(request: Request, call_next):
    if os.environ.get("MAINTENANCE_MODE") == "1" and request.method not in _SAFE_METHODS:
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Maintenance in progress — writes are temporarily frozen while the "
                    "service completes a scheduled migration. Please retry shortly."
                )
            },
            headers={"Retry-After": "120"},
        )
    return await call_next(request)


# ── Startup: SECRET_KEY stability check ───────────────────────────────────────
# Warn operators if SECRET_KEY is not pinned in the environment.
# A random per-process key means all JWTs issued by a prior process are
# immediately invalidated on restart — silent auth breakage that's hard to
# debug in a real deployment. Demo mode is expected to be ephemeral; any
# other environment should pin a stable key via the SECRET_KEY env var.

_secret_key_pinned: bool = bool(os.environ.get("SECRET_KEY", ""))

# ── GUARD_DESTRUCTIVE flag ────────────────────────────────────────────────────
# When GUARD_DESTRUCTIVE=1, three high-risk endpoints (student deletion,
# calibration threshold apply, and baseline-request list) require a
# matching X-Guard-Token header.  This lets pilot-mode deployments protect
# dangerous operations without a full JWT/RBAC stack.
#
# Demo mode leaves this unset so the frontend works without credentials.
# Pilot/production operators should:
#   1. Set MAINTENANCE_TOKEN to a strong random string
#   2. Set GUARD_DESTRUCTIVE=1
#   3. The X-Guard-Token header value must equal MAINTENANCE_TOKEN

_GUARD_DESTRUCTIVE: bool = os.environ.get("GUARD_DESTRUCTIVE", "0") == "1"


# ── Demo auth (no real session / JWT — maintenance backdoor) ──────────────────
#
# MAINTENANCE_TOKEN — set this env var to a strong random string to enable
# the maintenance backdoor. NEVER hardcode a value here. Generate with:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
#
# When presented, grants admin role AND writes a warning-level audit log entry
# so every maintenance access is traceable. Rotate via env var change + restart.
_MAINTENANCE_TOKEN = os.environ.get("MAINTENANCE_TOKEN", "")


# ── Routers ───────────────────────────────────────────────────────────────────
# The route handlers live in original/routers/ (WS-7.3). Their routes are
# spliced onto the app's own router, in the order they were declared in the
# pre-split api.py.
#
# Deliberately not app.include_router(): FastAPI 0.139 records an include as a
# lazy `_IncludedRouter` marker in `app.routes` instead of copying the routes
# in, and `app.routes` is an introspection surface here — the route-inventory
# guard in tests/test_bluebook_crud.py walks it and reads `.path`/`.methods`.
# Extending keeps `app.routes` the flat list of APIRoute objects that the
# `@app.get(...)` decorators used to build, so nothing downstream can tell the
# split happened.
app.router.routes.extend(health.router.routes)
app.router.routes.extend(auth.router.routes)
app.router.routes.extend(lti_routes.router.routes)
app.router.routes.extend(bluebook.router.routes)
app.router.routes.extend(students.router.routes)
app.router.routes.extend(students_baseline.router.routes)
app.router.routes.extend(students_scoring.router.routes)
app.router.routes.extend(tenants.router.routes)
app.router.routes.extend(me.router.routes)
app.router.routes.extend(imports.router.routes)
app.router.routes.extend(admin.router.routes)
# T8 QR phone-park. Additive and inert until a professor calls
# /proctor/park/open — no flag, no startup cost, no effect on any other route.
app.router.routes.extend(proctor.router.routes)
