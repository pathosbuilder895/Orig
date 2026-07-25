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
import csv
import dataclasses
import importlib.metadata
import io
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
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
from . import voice as voice_mod
from .features.pipeline import extract_features, feature_vector
from .quantum.scoring import ScoringConfig
from .quantum.scoring import score as quantum_score
from .quantum.state import BaselineSample

# Helpers and shared state that moved to original/routers/_shared.py in the WS-7.3
# router split. Re-imported here because `original.api.<helper>` is still a live
# call site: scripts/seed_pilot.py, and tests that reach into the app module.
from .routers import auth, bluebook, health, lti_routes, students, students_baseline
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
)
from .routers.students_baseline import add_baseline
from .schemas import (
    AddSampleRequest,
    ApplyThresholdsRequest,
    BlendDetectionRequest,
    BlendResultOut,
    CalibrationRunCreatedResponse,
    CalibrationRunDetail,
    CalibrationRunListResponse,
    CalibrationRunRequest,
    CalibrationRunSummary,
    CorrectionListResponse,
    CorrectionRequest,
    CorrectionResponse,
    CreateTenantRequest,
    DatasetInfo,
    Layer7OutputResponse,
    ManifestListItem,
    ManifestListResponse,
    ManifestStatsResponse,
    ScoreSubmissionRequest,
    SuggestionItem,
    SuggestionsResponse,
    TestScoreRequest,
    TestScoreResponse,
    TunedThresholdsListResponse,
    TunedThresholdsRecord,
    VoiceSubmitRequest,
    VoiceSubmitResult,
    VoiceView,
    WindowScoreOut,
)
from .tension_arc import analyze_tension_arc

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


def _is_staff_only_path(path: str) -> bool:
    p = path.rstrip("/") or "/"
    return p in _STAFF_ONLY_EXACT or path.startswith(_STAFF_ONLY_PREFIXES)


@app.middleware("http")
async def tenant_isolation(request: Request, call_next):
    principal = principal_mod.resolve_principal(request)
    request.state.principal = principal
    if _IS_REAL_DEPLOY and request.url.path in _DEMO_ONLY_STATICS:
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


# ── Tenant registry ───────────────────────────────────────────────────────────
# Phase 0 foundation: lightweight per-institution metadata stored in SQLite.
# Lets demo operator register schools with an environment label (demo/pilot/
# production) before Postgres multi-tenancy is needed.


@app.post("/tenants", status_code=201)
def create_tenant(body: CreateTenantRequest, request: Request):
    """
    Register or update a tenant (institution) record.

    Required body fields:
        tenant_id   — stable slug (e.g. 'seminary-of-dallas')
        name        — human-readable institution name

    Optional body fields:
        environment — 'demo' | 'pilot' | 'production'  (default: 'demo')
        meta        — arbitrary dict of metadata (contact email, LMS URL, etc.)
                      Capped at 10 keys, values must be strings ≤ 500 chars.

    When GUARD_DESTRUCTIVE=1, requires X-Guard-Token. Tenant writes are as
    sensitive as deletions: updating an existing pilot tenant's environment
    to 'demo' would make its student data anonymously readable.
    """
    _require_guard(request)
    tenant_id = body.tenant_id.strip()
    name = body.name.strip()
    if not tenant_id or not name:
        raise HTTPException(status_code=422, detail="tenant_id and name are required")
    if len(tenant_id) > 80 or len(name) > 200:
        raise HTTPException(status_code=422, detail="tenant_id max 80 chars, name max 200 chars")
    environment = body.environment
    if environment not in ("demo", "pilot", "production"):
        raise HTTPException(
            status_code=422, detail="environment must be 'demo', 'pilot', or 'production'"
        )
    # Never downgrade a real tenant to demo — demo tenants are anonymously
    # readable, so a downgrade silently exposes FERPA-protected records.
    # Recovering from a genuine mislabel is a deliberate operator action:
    # delete the tenant's students first, then re-register.
    existing = _repo().get_tenant(tenant_id)
    if (
        existing
        and existing.get("environment") in ("pilot", "production")
        and environment == "demo"
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Refusing to downgrade tenant '{tenant_id}' from "
                f"'{existing.get('environment')}' to 'demo' — demo tenants are "
                "anonymously readable. Delete the tenant's students first if "
                "this is intentional."
            ),
        )
    # Validate meta payload — prevents unbounded JSON storage
    meta = body.meta or {}
    if not isinstance(meta, dict):
        raise HTTPException(status_code=422, detail="meta must be a JSON object")
    if len(meta) > 10:
        raise HTTPException(status_code=422, detail="meta must have at most 10 keys")
    meta = {str(k)[:80]: str(v)[:500] for k, v in list(meta.items())[:10]}
    _repo().put_tenant(tenant_id, name, environment=environment, meta=meta)
    principal_mod.invalidate_tenant_cache()  # env may have changed → drop stale cache
    _repo().log_audit(
        action="tenant_register",
        tenant_id=tenant_id,
        details={"name": name, "environment": environment},
    )
    return {"tenant_id": tenant_id, "name": name, "environment": environment}


@app.get("/tenants")
def list_tenants(request: Request, environment: str = ""):
    """
    List all registered tenants, optionally filtered by environment.

    Staff-only (any role) — this intentionally stays cross-tenant-visible
    rather than scoped to SUPER_ROLES, matching the existing professor.html
    Settings-panel registry view that lists/registers institutions. It was
    previously reachable with NO auth check at all; this closes that gap
    without changing who can see it.
    """
    _require_staff(request)
    return _repo().list_tenants(environment=environment or None)


@app.get("/tenants/{tenant_id}")
def get_tenant(tenant_id: str, request: Request):
    """Get a single tenant record. Cross-tenant reads require operator/super_admin."""
    principal = _require_staff(request)
    try:
        principal_mod.assert_tenant_access(principal, tenant_id)
    except principal_mod.TenantAccessError:
        raise HTTPException(status_code=403, detail="Cross-tenant access denied.") from None
    t = _repo().get_tenant(tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found")
    return t


@app.get("/tenants/{tenant_id}/stats")
def tenant_stats(tenant_id: str, request: Request):
    """
    Aggregate statistics for a tenant — student count, submission volume,
    action breakdown, last active timestamp.

    Used by the operator dashboard to show all-schools-at-a-glance (operator/
    super_admin principals are cross-tenant by design); any other staff role
    may only fetch stats for its own tenant.
    """
    principal = _require_staff(request)
    try:
        principal_mod.assert_tenant_access(principal, tenant_id)
    except principal_mod.TenantAccessError:
        raise HTTPException(status_code=403, detail="Cross-tenant access denied.") from None
    t = _repo().get_tenant(tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found")
    return _repo().tenant_stats(tenant_id)


@app.delete("/tenants/{tenant_id}/students", status_code=200)
def delete_tenant_students(tenant_id: str, request: Request):
    """
    FERPA-safe bulk deletion of all students belonging to a tenant.

    Iterates list_ids_for_tenant() and calls store.delete_student() for each —
    the same code path as individual deletion, so all linked records
    (fidelity scores, manifests, corrections, audit rows) are purged.

    Requires operator/super_admin — or, for any other staff role, that the
    caller's own tenant matches ``tenant_id`` — in addition to the existing
    X-Guard-Token requirement when GUARD_DESTRUCTIVE=1. Previously this was
    guarded ONLY by the shared guard token (a no-op when GUARD_DESTRUCTIVE is
    unset), so any staff principal could bulk-delete any other tenant's
    entire roster; this closes that gap.
    """
    principal = _require_staff(request)
    try:
        principal_mod.assert_tenant_access(principal, tenant_id)
    except principal_mod.TenantAccessError:
        raise HTTPException(status_code=403, detail="Cross-tenant access denied.") from None
    _require_guard(request)
    t = _repo().get_tenant(tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found")
    result = _repo().delete_tenant_students(tenant_id)
    return {
        "tenant_id": tenant_id,
        "deleted_count": result["deleted_count"],
        "failed_ids": result["failed_ids"],
        "message": (
            f"Deleted {result['deleted_count']} student(s) from '{tenant_id}'. "
            + (f"Failed: {result['failed_ids']}" if result["failed_ids"] else "")
        ).strip(),
    }


# ── ADR-005: the student read-model (redacting, token-resolved, no id in path) ─
# The student dashboard talks ONLY to these /me/* endpoints. They resolve the
# student from the session token (never an id in the path, so id-tampering and
# cross-student reads are structurally impossible) and return display-ready,
# formation-register documents with every forbidden internal projected away in
# original/voice.py. The rich /students/{id}, /score, and /admin/* surfaces are
# unchanged — they remain the STAFF surface, just unreachable by this client.


@app.get("/me/voice", response_model=VoiceView)
def my_voice(request: Request):
    """
    The complete, redacted VoiceView for the signed-in student.

    Resolves the student from the session token, gathers their internal state
    (baseline vector, scoring manifests, tutor corrections, formation pathway)
    and projects it through original.voice into a display-ready document. No
    feature codes, raw divergence/deviation, purity, sample counts, action
    enums, or thresholds ever cross the wire.
    """
    session = _require_student_session(request)
    sid = str(session["sid"])
    name = str(session.get("name", "") or "")

    state = _repo().get(sid)
    if state is not None:
        from .constants import ALL_FEATURE_CODES

        baseline_vector = {
            code: float(state.baseline_mean[i]) for i, code in enumerate(ALL_FEATURE_CODES)
        }
        sample_count = state.sample_count
        authenticated_count = state.authenticated_count
    else:
        baseline_vector = {}
        sample_count = 0
        authenticated_count = 0

    manifests = _repo().list_manifests(student_id=sid, limit=50).get("items", [])
    corrections = _repo().list_corrections(student_id=sid, limit=20).get("items", [])
    pathway = _repo().get_formation_pathway(sid)

    view = voice_mod.project_voice_view(
        name=name,
        baseline_vector=baseline_vector,
        sample_count=sample_count,
        authenticated_count=authenticated_count,
        manifests=manifests,
        corrections=corrections,
        pathway=pathway,
    )
    return VoiceView(**view)


@app.post("/me/work", response_model=VoiceSubmitResult)
def my_work(request: Request, body: VoiceSubmitRequest):
    """
    Submit a piece of writing as the signed-in student.

    Adds the text to the student's body of work and scores it server-side, then
    returns ONLY the redacted formation-register result (headline + supportive
    summary + steady-dimension affirmations + whether a review opportunity
    opened). The raw Layer-7 payload never leaves the server.
    """
    session = _require_student_session(request)
    sid = str(session["sid"])
    name = str(session.get("name", "") or "")

    # Ensure a record exists, then add this piece to the body of work. The
    # student-submitted piece is always 'unverified' (self-upload trust), so the
    # provenance gate is a no-op here — pass the request through for its signature.
    _repo().get_or_create(sid)
    try:
        add_baseline(
            sid,
            AddSampleRequest(text=body.text, assignment=body.title, provenance="unverified"),
            request,
        )
    except HTTPException:
        # A too-short or otherwise rejected sample shouldn't 500 the student; the
        # scoring step below will simply return the "not yet analysed" result.
        pass

    try:
        layer7 = score_submission(
            sid, ScoreSubmissionRequest(text=body.text, assignment=body.title)
        )
    except HTTPException:
        # No authenticated baseline yet (or student not scorable) — saved, not scored.
        return VoiceSubmitResult(
            headline="Saved to your body of work.",
            summary="This piece has been added to your formation record. Your voice "
            "profile builds as you submit more work.",
            steady=[],
            review_opportunity=False,
        )

    result = voice_mod.project_submission_result(layer7, name)
    return VoiceSubmitResult(**result)


@app.post("/me/formation/advance", response_model=VoiceView)
def my_formation_advance(request: Request):
    """
    Advance the signed-in student's formation pathway by one session, then
    return the refreshed VoiceView. Token-resolved; no id in the path. Opens a
    pathway first if none is active (mirrors the dashboard's idempotent flow).
    """
    session = _require_student_session(request)
    sid = str(session["sid"])

    repo = _repo()
    if not repo.get_formation_pathway(sid):
        repo.open_formation_pathway(sid, submission_id=None, reason=None)
    repo.advance_formation_pathway(sid)
    # Hand back the fresh, redacted view so the client re-renders from one source.
    return my_voice(request)


@app.get("/admin/audit")
def list_audit_log(
    request: Request,
    student_id: str = "",
    action: str = "",
    limit: int = 100,
    offset: int = 0,
):
    """
    Query the system audit log. Staff-only: the tenant-isolation middleware
    already 401s anonymous callers on real deploys (tests/test_pilot_lockdown);
    the explicit guard here additionally rejects STUDENT tokens in the demo —
    audit rows carry other students' identifiers.

    Optional filters:
        student_id — restrict to a specific student
        action     — restrict to a specific action type
                     (baseline_add, score, student_delete, correction,
                      threshold_apply, tenant_register, bulk_delete)

    Results are ordered most-recent-first.
    """
    _require_staff(request)
    limit = min(limit, 500)
    return _repo().list_audit(
        student_id=student_id or None,
        action=action or None,
        limit=limit,
        offset=offset,
    )


# ── Score submission ──────────────────────────────────────────────────────────


@app.post("/students/{student_id}/score", response_model=Layer7OutputResponse)
def score_submission(student_id: str, req: ScoreSubmissionRequest, force: bool = False):
    state = _repo().get(student_id)
    if state is None:
        raise HTTPException(
            status_code=404, detail=f"Student '{student_id}' not found. Add baseline samples first."
        )
    if state.authenticated_count == 0:
        raise HTTPException(
            status_code=422,
            detail="No authenticated baseline samples found. "
            "Add at least one 'proctored' or 'verified' sample first.",
        )

    # Check cache only if force is False (allow cache bypass with force=True)
    submission_id = req.submission_id or f"{student_id}_submission_{state.sample_count}"
    if not force:
        # Check for cached result (stub for future caching implementation)
        existing_result = None  # TODO: retrieve from cache by submission_id
        if existing_result:
            return _to_response(existing_result)

    # ── Phase 5: adaptive-context orchestrator (env-flag gated) ───────────────
    # When both CONTEXT_MANIFEST_ENABLED and ADAPTIVE_WEIGHTS_ENABLED are
    # unset, the orchestrator short-circuits to plain extract_features +
    # feature_vector, preserving Phase 1 byte-identical behaviour.
    enable_manifest = os.environ.get("CONTEXT_MANIFEST_ENABLED") == "1"
    enable_adaptive = os.environ.get("ADAPTIVE_WEIGHTS_ENABLED") == "1"

    try:
        from .context.pipeline import run_adaptive_pipeline

        adaptive = run_adaptive_pipeline(
            text=req.text,
            state=state,
            submission_id=submission_id,
            keystroke_data=req.keystroke_data,
            enable_manifest=enable_manifest,
            enable_adaptive_weights=enable_adaptive,
        )
        feat_dict = adaptive.feat_dict
        vec = adaptive.vector
        manifest = adaptive.manifest
        adaptive_weights = adaptive.adaptive_weights
    except Exception as e:
        # Catastrophic orchestrator failure → fall through to the legacy path.
        # This guarantees that nothing in the new context layer can take down
        # the scoring endpoint, no matter how broken a resolver gets.
        logging.getLogger(__name__).warning(
            "Adaptive pipeline failed for %s: %s — falling back to Phase 1",
            submission_id,
            e,
        )
        feat_dict = extract_features(req.text, keystroke_data=req.keystroke_data)
        vec = feature_vector(req.text, keystroke_data=req.keystroke_data)
        manifest = None
        adaptive_weights = None

    manifest_dict = manifest.to_dict() if manifest is not None else None
    # n_tokens: thread the actual word count into the scorer so the Gaussian
    # wave packet attenuation in encode_amplitudes is proportional to the
    # real submission length, not a fixed default.
    _n_tokens = len(req.text.split())

    # ── Explicit null model (rank-and-null work, production wiring) ───────────
    # NULL_MODEL=impostor: pool authenticated baseline vectors from the
    # claimed student's same-tenant peers into a diagonal-Gaussian impostor
    # cohort (original/quantum/null_pool.py); quantum_score() then attaches
    # llr_deviation_score — "fits this student vs fits a typical classmate".
    # None below the cold-start floors (3 peers / 5 vectors) and on any
    # failure; never changes deviation_score or the recommended action.
    _scoring_config_env = ScoringConfig.from_env()

    _impostor_stats = None
    if _scoring_config_env.null_model == "impostor":
        try:
            from .quantum.null_pool import build_impostor_stats

            _impostor_stats = build_impostor_stats(student_id, _repo().all_states())
        except Exception:
            logging.getLogger(__name__).exception(
                "impostor pool build failed for %s — llr score skipped", student_id
            )

    # ── ScoringConfig persistence lookups (WS-7 step 1) ───────────────────────
    # scoring.py no longer reaches into store directly — resolve the same two
    # lookups here, gated behind the same flags scoring.py used to check
    # internally, and pass the results through.
    _authentic_fidelities = None
    if _scoring_config_env.amplitude_scoring_enabled:
        _authentic_fidelities = _repo().get_authentic_fidelities(student_id)
    _genre_stats = None
    if _scoring_config_env.bayesian_prior_enabled and state.sample_count < 10:
        _genre = (
            state.samples[-1].genre
            if state.samples and getattr(state.samples[-1], "genre", None)
            else None
        )
        if _genre:
            _genre_stats = _repo().get_genre_stats(_genre)
    _scoring_config = dataclasses.replace(
        _scoring_config_env,
        authentic_fidelities=_authentic_fidelities,
        genre_stats=_genre_stats,
    )

    result = quantum_score(
        state=state,
        submission_vector=vec,
        feature_dict=feat_dict,
        submission_id=submission_id,
        adaptive_weights=adaptive_weights,
        manifest=manifest_dict,
        n_tokens=_n_tokens,
        impostor_stats=_impostor_stats,
        scoring_config=_scoring_config,
    )

    # ── AI-likelihood (corpus-level second scoring mode, report-only) ─────────
    # Two modes, one persistence call site:
    #   AI_LIKELIHOOD_SHADOW=1  → compute + persist ONLY. result.ai_likelihood
    #     stays None, so narrative/explainer/response can never see it —
    #     silent real-world FPR measurement (scripts/shadow_report.py).
    #   AI_LIKELIHOOD_ENABLED=1 → attach to the result AND persist (strict
    #     superset: enablement is one env flip with unbroken data continuity).
    # Attached before report/narrative assembly so downstream explanation
    # layers can see it when enabled. Scores the same `vec` — no second
    # extraction. predict_ai_likelihood never raises; None when unavailable.
    _ai_enabled = os.environ.get("AI_LIKELIHOOD_ENABLED") == "1"
    _ai_shadow = os.environ.get("AI_LIKELIHOOD_SHADOW") == "1"
    if _ai_enabled or _ai_shadow:
        from .ai_likelihood import predict_ai_likelihood

        _ai_res = predict_ai_likelihood(vec)
        if _ai_enabled:
            result.ai_likelihood = _ai_res
        if _ai_res is not None:
            # Deliberately outside the quantum_fidelity > 0 gate below —
            # shadow rows must persist for every scored submission.
            try:
                _repo().put_ai_likelihood_score(
                    submission_id=submission_id,
                    student_id=student_id,
                    probability=_ai_res.probability,
                    band=_ai_res.band,
                    model_version=_ai_res.model_version,
                )
            except Exception:
                logging.getLogger(__name__).exception(
                    "ai_likelihood persistence failed for %s", submission_id
                )

    # ── Persist quantum fidelity for conformal calibration ───────────────────
    # Stores every scored fidelity so get_authentic_fidelities() can build
    # a calibration set for the conformal p-value on future submissions.
    # "Authentic" is approximated as action == no_action here; the instructor
    # corrections flow (put_correction + is_correct=True) should override
    # this for any verdict the professor marks as wrong.
    if result.authorship.quantum_fidelity > 0:
        try:
            _repo().put_fidelity_score(
                submission_id=submission_id,
                student_id=student_id,
                fidelity=result.authorship.quantum_fidelity,
                is_authentic=(result.recommendation.action == "no_action"),
            )
        except Exception as _e:
            logging.getLogger(__name__).debug(
                "put_fidelity_score skipped for %s: %s",
                submission_id,
                _e,
            )

    # ── Persist manifest to audit log when one was built ──────────────────────
    if manifest is not None:
        try:
            _repo().put_manifest(
                submission_id=submission_id,
                student_id=student_id,
                manifest=manifest,
                divergence_score=result.authorship.deviation_score,
                action=result.recommendation.action,
            )
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Manifest audit-log write failed for %s: %s",
                submission_id,
                e,
            )

    # ── Phase 6: human-readable audit report (only when manifest exists) ──────
    # Built from the same triplet that drove the score: Layer7Output (math),
    # ContextManifest (directives), StudentState (sample provenance). When
    # there is no manifest (flag off), no report is produced — response stays
    # byte-identical to Phase 1.
    report = None
    if manifest is not None:
        try:
            from .context.report import build_report

            report = build_report(result, manifest, state, n_tokens=_n_tokens)
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Report assembly failed for %s: %s",
                submission_id,
                e,
            )

    # ── Tension Arc (runs alongside quantum score, independent signal) ────────
    arc = analyze_tension_arc(req.text, baseline_kappa=state.baseline_kappa)

    # ── Email notification stub for escalate/schedule_conversation actions ────
    action = result.recommendation.action
    overall_score = result.authorship.authorship_probability
    if action in ("escalate", "schedule_conversation"):
        _send_notification_email(student_name=student_id, action=action, score=overall_score)

    # ── Audit log — best-effort, never raises ─────────────────────────────────
    try:
        _repo().log_audit(
            action="score",
            student_id=student_id,
            details={
                "submission_id": submission_id,
                "deviation_score": round(result.authorship.deviation_score, 4),
                "recommendation": action,
                "sample_count": state.sample_count,
            },
        )
    except Exception:
        pass

    return _to_response(result, arc, report=report)


# ── Score audit log (best-effort, never raises) ───────────────────────────────
# Wire audit logging after the return object is built so any exception here
# cannot corrupt the response. The try/except is intentional insurance.


# ── Phase 7: sliding-window blend detection ──────────────────────────────────


@app.post(
    "/students/{student_id}/score/blend",
    response_model=BlendResultOut,
)
def score_blend(student_id: str, req: BlendDetectionRequest):
    """
    Detect mid-document fingerprint shifts (collaboration / AI insertion /
    advisor edits) by scoring overlapping token windows separately.

    Cost is N× the regular `/score` endpoint (one full feature extraction
    per window) — kept on a separate route so callers opt in explicitly.
    """
    state = _repo().get(student_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Student '{student_id}' not found. Add baseline samples first.",
        )
    if state.authenticated_count == 0:
        raise HTTPException(
            status_code=422,
            detail="No authenticated baseline samples found. "
            "Add at least one 'proctored' or 'verified' sample first.",
        )

    from .context.blend import detect_blend

    submission_id = req.submission_id or f"{student_id}_blend_{state.sample_count}"
    result = detect_blend(
        text=req.text,
        state=state,
        window_tokens=req.window_tokens,
        overlap=req.overlap,
        submission_id=submission_id,
    )
    return BlendResultOut(
        blend_detected=result.blend_detected,
        blend_index=result.blend_index,
        shift_positions=list(result.shift_positions),
        per_section=[
            WindowScoreOut(start=w.start, end=w.end, score=w.score, confidence=w.confidence)
            for w in result.per_section
        ],
        n_tokens=result.n_tokens,
        fallback_reason=result.fallback_reason,
    )


# ── Turnitin CSV import ───────────────────────────────────────────────────────


@app.post("/import/courses/{course_id}/turnitin-csv")
async def import_turnitin_csv(course_id: str, file: UploadFile = File(...)):
    """
    Parse a Turnitin admin CSV export and create student/submission stubs.

    Expected columns (Turnitin default export):
      Last Name, First Name, Student ID, Assignment Title, Date Submitted,
      Similarity, File Name
    """
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig", errors="replace")  # handle BOM
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not decode CSV: {exc}") from exc

    reader = csv.DictReader(io.StringIO(text))
    # Normalise header keys: lowercase, strip whitespace
    rows = []
    for row in reader:
        rows.append({k.strip().lower(): v.strip() for k, v in row.items()})

    if not rows:
        raise HTTPException(status_code=422, detail="CSV is empty or has no data rows.")

    total_rows = len(rows)
    matched_students = 0
    created_students = 0
    flagged_submissions = 0
    unmatched_rows = 0
    errors: list[str] = []

    # Possible column names across Turnitin export versions
    def _col(row: dict, *candidates: str) -> str:
        for c in candidates:
            if c in row and row[c]:
                return row[c]
        return ""

    for i, row in enumerate(rows, 1):
        last = _col(row, "last name", "lastname", "surname")
        first = _col(row, "first name", "firstname")
        sid = _col(row, "student id", "studentid", "id", "user id")
        name = f"{first} {last}".strip() or sid or f"Student_{i}"

        if not (last or first or sid):
            unmatched_rows += 1
            errors.append(f"Row {i}: could not identify student (no name or ID)")
            continue

        student_id = sid or name.lower().replace(" ", "_")

        state = _repo().get(student_id)
        if state is None:
            state = _repo().get_or_create(student_id)
            created_students += 1
        else:
            matched_students += 1

        flagged_submissions += 1  # stub — no text yet, needs file upload

    return {
        "total_rows": total_rows,
        "matched_students": matched_students,
        "created_students": created_students,
        "flagged_submissions": flagged_submissions,
        "unmatched_rows": unmatched_rows,
        "errors": errors,
    }


# ── Canvas baseline import (not available in the pilot server) ────────────────
# These used to return demo placeholder JSON with a 200 status, which reads
# as success to any client that doesn't inspect the body. 501 is honest about
# there being no real Canvas integration on this server (WS-7 step 5). The
# professor.html call sites check r.ok and surface the detail string.


@app.post("/canvas/baseline/{student_id}/list-canvas-submissions")
async def list_canvas_submissions(student_id: str, req: dict = None):
    """
    List a student's past Canvas submissions available for baseline import.
    Not implemented on this server — use 'Drop files' or 'Paste text' instead.
    """
    raise HTTPException(501, "Canvas import not available in the pilot server")


@app.post("/canvas/baseline/{student_id}/import-baseline")
async def import_canvas_baseline(student_id: str, req: dict = None):
    """Not implemented on this server — see list_canvas_submissions."""
    raise HTTPException(501, "Canvas import not available in the pilot server")


# ══════════════════════════════════════════════════════════════════════════════
# PR 7: admin / dashboard / playground / corrections
# ══════════════════════════════════════════════════════════════════════════════


@app.get("/admin/manifests", response_model=ManifestListResponse)
def admin_list_manifests(
    student_id: str | None = None,
    action: str | None = None,
    flag: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    Paginated list of context manifests from the audit log.
    All filters are optional.
    """
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=422, detail="limit must be in [1, 1000]")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be ≥ 0")
    res = _repo().list_manifests(
        student_id=student_id,
        action=action,
        flag=flag,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return ManifestListResponse(
        total=res["total"],
        limit=res["limit"],
        offset=res["offset"],
        items=[ManifestListItem(**i) for i in res["items"]],
    )


@app.get("/admin/manifests/stats", response_model=ManifestStatsResponse)
def admin_manifest_stats(
    since: str | None = None,
    until: str | None = None,
):
    """Roll-up counts for the admin dashboard summary cards."""
    return ManifestStatsResponse(**_repo().manifest_stats(since=since, until=until))


@app.post(
    "/submissions/{submission_id}/correct",
    response_model=CorrectionResponse,
)
def submit_correction(submission_id: str, req: CorrectionRequest, request: Request):
    """
    Record an instructor correction on a scoring verdict.

    The correction is keyed by submission_id; auto-fills student_id +
    original action/divergence from the manifest audit log when those
    were not supplied. Multiple corrections per submission are allowed
    (e.g. an initial flag + a later override) — the most recent row wins
    when the retraining job (PR 8) consumes them.

    Authorization: corrections flip the authenticity labels that feed
    conformal calibration and threshold tuning, so this is a staff-only
    write. A non-super staff principal may only correct submissions whose
    student is in its own tenant (operator/super are cross-tenant by design).
    """
    principal = _require_staff(request)
    # Tenant-scope the correction to the submission's student. Resolve the owner
    # the same way put_correction back-fills it (manifest, then the score audit
    # row); when the submission is unknown there is no cross-tenant target to
    # protect, so a staff principal is allowed through and the row is written
    # with a null student_id (unchanged behaviour).
    owner_id = _repo().submission_student_id(submission_id)
    if owner_id is not None:
        try:
            principal_mod.assert_student_access(principal, owner_id)
        except principal_mod.TenantAccessError:
            raise HTTPException(status_code=403, detail="Cross-tenant access denied.") from None

    # Validate the optional verdict / action enums to catch typos in the
    # dashboard form before they pollute the training set.
    if req.corrected_verdict is not None and req.corrected_verdict not in (
        "authentic",
        "uncertain",
        "anomalous",
    ):
        raise HTTPException(
            status_code=422,
            detail='corrected_verdict must be "authentic" | "uncertain" | "anomalous"',
        )
    if req.corrected_action is not None and req.corrected_action not in (
        "no_action",
        "monitor",
        "schedule_conversation",
        "escalate",
    ):
        raise HTTPException(
            status_code=422,
            detail='corrected_action must be "no_action" | "monitor" | '
            '"schedule_conversation" | "escalate"',
        )

    correction_id = _repo().put_correction(
        submission_id=submission_id,
        is_correct=req.is_correct,
        student_id=owner_id,
        corrected_verdict=req.corrected_verdict,
        corrected_action=req.corrected_action,
        reviewer=req.reviewer,
        notes=req.notes,
    )
    if correction_id is None:
        raise HTTPException(status_code=500, detail="Failed to persist correction")

    # Round-trip the inserted row so the response carries the auto-filled
    # student_id / original_action / created_at fields the form didn't have.
    listed = _repo().list_corrections(submission_id=submission_id, limit=1)
    if not listed["items"]:
        raise HTTPException(
            status_code=500, detail="Correction inserted but not found on read-back"
        )
    # The most recent (and only matching) row is the one we just wrote.
    latest = listed["items"][0]

    # /admin/audit's own docstring promises "correction" as a filterable
    # action type — log it so that contract is actually true (WS-9).
    _repo().log_audit(
        action="correction",
        student_id=latest.get("student_id"),
        actor=req.reviewer,
        result="ok",
        details={"submission_id": submission_id, "is_correct": req.is_correct},
    )

    # ── Close the conformal feedback loop ────────────────────────────────────
    # Determine whether this correction establishes the submission as authentic,
    # then update the fidelity_scores row so the conformal calibration set
    # reflects real instructor labels rather than the automated heuristic.
    #
    # Rules:
    #   is_correct=True  + original was "no_action"   → confirmed authentic
    #   is_correct=True  + original was not "no_action" → confirmed anomalous
    #   is_correct=False + corrected_verdict/action is authentic → now authentic
    #   is_correct=False + no clear corrected label → assume anomalous
    try:
        _orig_action = latest.get("original_action") or ""
        if req.is_correct:
            _is_now_authentic = _orig_action == "no_action"
        else:
            _is_now_authentic = (
                req.corrected_verdict == "authentic" or req.corrected_action == "no_action"
            )
        _repo().update_fidelity_authenticity(submission_id, _is_now_authentic)
    except Exception as _fid_exc:
        # Non-fatal: the correction row was saved; the fidelity update is
        # best-effort. Log at DEBUG so production noise stays low.
        logging.getLogger(__name__).debug(
            "fidelity authenticity update skipped for %s: %s",
            submission_id,
            _fid_exc,
        )

    return CorrectionResponse(**latest)


@app.get("/admin/corrections", response_model=CorrectionListResponse)
def admin_list_corrections(
    submission_id: str | None = None,
    student_id: str | None = None,
    is_correct: bool | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """List corrections with optional filters."""
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=422, detail="limit must be in [1, 1000]")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be ≥ 0")
    res = _repo().list_corrections(
        submission_id=submission_id,
        student_id=student_id,
        is_correct=is_correct,
        limit=limit,
        offset=offset,
    )
    return CorrectionListResponse(
        total=res["total"],
        limit=res["limit"],
        offset=res["offset"],
        items=[CorrectionResponse(**i) for i in res["items"]],
    )


@app.post("/test/score", response_model=TestScoreResponse)
def test_score(req: TestScoreRequest):
    """
    Playground endpoint — runs the full adaptive pipeline on inline text
    + inline baselines, **with no DB writes**. The two adaptive feature
    flags default to True regardless of the server's env-var config so
    callers always see the full output. Optionally also runs blend
    detection on the same submission.

    Use cases:
        - Demo / "kick the tires" UI on `/playground.html`
        - Reproducing a bug report's manifest without persisting
        - Tuning resolver thresholds in a quick feedback loop
    """
    if not req.baseline_texts:
        raise HTTPException(
            status_code=422,
            detail="baseline_texts must be non-empty (need at least one sample to score against)",
        )
    if len(req.baseline_texts) > 10:
        raise HTTPException(
            status_code=422,
            detail="baseline_texts capped at 10 — playground only",
        )

    # Build a synthetic, in-memory StudentState. Verified provenance + 1.0
    # auth_weight so every supplied text contributes to the density matrix.
    synth_samples = []
    for i, t in enumerate(req.baseline_texts):
        if not (t or "").strip():
            continue
        try:
            v = feature_vector(t)
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"baseline_texts[{i}] feature extraction failed: {exc}",
            ) from exc
        synth_samples.append(
            BaselineSample(
                text=t,
                vector=v,
                provenance="verified",
                auth_weight=1.0,
                assignment=f"playground_{i}",
                submitted_at="",
            )
        )
    if not synth_samples:
        raise HTTPException(status_code=422, detail="All baseline_texts were empty after stripping")

    from .quantum.state import StudentState as _SS

    synth_state = _SS(student_id="__playground__", samples=synth_samples)

    # ── Run the adaptive pipeline (always force flags ON for playground) ──────
    from .context.pipeline import run_adaptive_pipeline

    adaptive = run_adaptive_pipeline(
        text=req.text,
        state=synth_state,
        submission_id=req.submission_id,
        keystroke_data=req.keystroke_data,
        enable_manifest=req.enable_manifest,
        enable_adaptive_weights=req.enable_adaptive_weights,
    )
    manifest_dict = adaptive.manifest.to_dict() if adaptive.manifest is not None else None
    layer7 = quantum_score(
        state=synth_state,
        submission_vector=adaptive.vector,
        feature_dict=adaptive.feat_dict,
        submission_id=req.submission_id,
        adaptive_weights=adaptive.adaptive_weights,
        manifest=manifest_dict,
        n_tokens=len(req.text.split()),
        # Synthetic in-memory student has no store record — no authentic
        # fidelities or genre to fetch, but flags still come from env
        # for parity with the pre-WS-7 live os.environ reads.
        scoring_config=ScoringConfig.from_env(),
    )

    # ── Optional: build the report (Phase 6) ──────────────────────────────────
    report = None
    if adaptive.manifest is not None:
        try:
            from .context.report import build_report

            report = build_report(layer7, adaptive.manifest, synth_state)
        except Exception as e:
            logging.getLogger(__name__).warning("playground report failed: %s", e)

    # Tension arc (cheap, runs alongside).
    arc = analyze_tension_arc(req.text)

    layer7_resp = _to_response(layer7, arc=arc, report=report)

    # ── Optional: sliding-window blend detection ──────────────────────────────
    blend_resp = None
    if req.enable_blend:
        from .context.blend import detect_blend

        try:
            br = detect_blend(
                text=req.text,
                state=synth_state,
                submission_id=req.submission_id,
            )
            blend_resp = BlendResultOut(
                blend_detected=br.blend_detected,
                blend_index=br.blend_index,
                shift_positions=list(br.shift_positions),
                per_section=[
                    WindowScoreOut(start=w.start, end=w.end, score=w.score, confidence=w.confidence)
                    for w in br.per_section
                ],
                n_tokens=br.n_tokens,
                fallback_reason=br.fallback_reason,
            )
        except Exception as e:
            logging.getLogger(__name__).warning("playground blend failed: %s", e)

    return TestScoreResponse(layer7=layer7_resp, blend=blend_resp)


# ══════════════════════════════════════════════════════════════════════════════
# PR 8: Calibration Lab
# ══════════════════════════════════════════════════════════════════════════════


@app.get("/admin/lab/datasets", response_model=list[DatasetInfo])
def admin_lab_datasets():
    """List the datasets the lab knows how to run (Federalist, multi-author, …)."""
    from .lab.datasets import list_datasets

    return [DatasetInfo(**d) for d in list_datasets()]


@app.post("/admin/calibration/run", response_model=CalibrationRunCreatedResponse, status_code=202)
def admin_run_calibration(req: CalibrationRunRequest):
    """
    Kick off a calibration run in the background and return its row id.

    The run executes on a single-worker thread pool, so multiple requests
    queue rather than overlap. Poll ``GET /admin/calibration/runs/{id}``
    to see when status flips to ``completed`` or ``failed``.
    """
    from .lab.runner import trigger_run

    run_id, error = trigger_run(
        dataset_label=req.dataset_label,
        run_label=req.run_label,
        max_scoring=req.max_scoring,
        thresholds=req.thresholds,
    )
    if run_id is None:
        raise HTTPException(status_code=422, detail=error or "Failed to start run")
    return CalibrationRunCreatedResponse(
        run_id=run_id,
        status="running",
        dataset_label=req.dataset_label,
    )


@app.get("/admin/calibration/runs", response_model=CalibrationRunListResponse)
def admin_list_calibration_runs(
    status: str | None = None,
    dataset_label: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List calibration runs (newest first), with optional filters."""
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be in [1, 500]")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be ≥ 0")
    res = _repo().list_calibration_runs(
        status=status,
        dataset_label=dataset_label,
        limit=limit,
        offset=offset,
    )
    return CalibrationRunListResponse(
        total=res["total"],
        limit=res["limit"],
        offset=res["offset"],
        items=[CalibrationRunSummary(**i) for i in res["items"]],
    )


@app.get("/admin/calibration/runs/{run_id}", response_model=CalibrationRunDetail)
def admin_get_calibration_run(run_id: int, include_report: bool = True):
    """Fetch one run with optional report inclusion."""
    res = _repo().get_calibration_run(run_id, include_report=include_report)
    if res is None:
        raise HTTPException(status_code=404, detail=f"calibration run {run_id} not found")
    return CalibrationRunDetail(**res)


@app.get("/admin/calibration/runs/{run_id}/suggestions", response_model=SuggestionsResponse)
def admin_run_suggestions(run_id: int):
    """
    Run the suggestion engine over a finished calibration + the corrections
    feedback log. Returns recommended threshold + tier-weight changes with
    explanatory rationale + per-suggestion confidence.
    """
    res = _repo().get_calibration_run(run_id, include_report=True)
    if res is None:
        raise HTTPException(status_code=404, detail=f"calibration run {run_id} not found")
    if res.get("status") != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"run {run_id} is {res.get('status')}; suggestions require status=completed",
        )

    from .lab.suggestions import generate_suggestions

    # Pull current thresholds from active tuned set if available; fall back
    # to Phase-1 defaults.
    active = _repo().get_active_tuned_thresholds()
    if active is not None:
        current = {
            "no_action": active["no_action"],
            "monitor": active["monitor"],
            "escalate": active["escalate"],
        }
    else:
        current = None

    corrections = _repo().list_corrections(limit=1000)["items"]
    out = generate_suggestions(
        report=res["report"] or {},
        corrections=corrections,
        current_thresholds=current,
    )
    return SuggestionsResponse(
        suggestions=[SuggestionItem(**s) for s in out["suggestions"]],
        summary=out["summary"],
    )


@app.post("/admin/calibration/runs/{run_id}/apply", response_model=TunedThresholdsRecord)
def admin_apply_thresholds(run_id: int, req: ApplyThresholdsRequest, request: Request):
    """
    Persist a new active threshold set sourced from a calibration run.

    Versioned in ``tuned_thresholds_v2`` — older sets remain for audit.
    The latest row by ``created_at`` is the in-effect active set;
    in-process scoring reads it on demand.

    When GUARD_DESTRUCTIVE=1, requires X-Guard-Token header — applying new
    thresholds changes system behaviour globally and should only be allowed
    for admins in pilot/production mode.
    """
    _require_guard(request)
    res = _repo().get_calibration_run(run_id, include_report=False)
    if res is None:
        raise HTTPException(status_code=404, detail=f"calibration run {run_id} not found")

    new_id = _repo().put_tuned_thresholds(
        no_action=req.no_action,
        monitor=req.monitor,
        escalate=req.escalate,
        verdict_authentic_below=req.verdict_authentic_below,
        verdict_anomalous_at_or_above=req.verdict_anomalous_at_or_above,
        source="calibration_run",
        source_run_id=run_id,
        notes=req.notes,
        provenance={
            "dataset_label": res.get("dataset_label"),
            "auc_at_apply": res.get("auc"),
            "n_essays_scored": res.get("n_essays_scored"),
            "applied_at_run_id": run_id,
        },
    )
    if new_id is None:
        raise HTTPException(status_code=500, detail="Failed to persist tuned thresholds")
    active = _repo().get_active_tuned_thresholds()
    return TunedThresholdsRecord(**active)


@app.get("/admin/tuned-thresholds", response_model=Optional[TunedThresholdsRecord])
def admin_get_tuned_thresholds():
    """Return the currently-active tuned thresholds (or null if none set)."""
    active = _repo().get_active_tuned_thresholds()
    return TunedThresholdsRecord(**active) if active else None


# ── Demo auth (no real session / JWT — maintenance backdoor) ──────────────────
#
# MAINTENANCE_TOKEN — set this env var to a strong random string to enable
# the maintenance backdoor. NEVER hardcode a value here. Generate with:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
#
# When presented, grants admin role AND writes a warning-level audit log entry
# so every maintenance access is traceable. Rotate via env var change + restart.
_MAINTENANCE_TOKEN = os.environ.get("MAINTENANCE_TOKEN", "")


@app.get("/admin/tuned-thresholds/history", response_model=TunedThresholdsListResponse)
def admin_list_tuned_thresholds(limit: int = 50, offset: int = 0):
    """Audit list of all tuned-threshold versions ever applied."""
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be in [1, 500]")
    res = _repo().list_tuned_thresholds(limit=limit, offset=offset)
    return TunedThresholdsListResponse(
        total=res["total"],
        limit=res["limit"],
        offset=res["offset"],
        items=[TunedThresholdsRecord(**i) for i in res["items"]],
    )


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
