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
from .features.pipeline import feature_vector
from .quantum.scoring import ScoringConfig
from .quantum.scoring import score as quantum_score
from .quantum.state import BaselineSample

# Helpers and shared state that moved to original/routers/_shared.py in the WS-7.3
# router split. Re-imported here because `original.api.<helper>` is still a live
# call site: scripts/seed_pilot.py, and tests that reach into the app module.
from .routers import (
    auth,
    bluebook,
    health,
    lti_routes,
    me,
    students,
    students_baseline,
    students_scoring,
    tenants,
)
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

# Re-exported: scripts/seed_pilot.py binds original.api.add_baseline /
# original.api.score_submission to drive ingestion in-process.
from .routers.students_baseline import add_baseline  # noqa: F401
from .routers.students_scoring import score_submission  # noqa: F401
from .schemas import (
    ApplyThresholdsRequest,
    BlendResultOut,
    CalibrationRunCreatedResponse,
    CalibrationRunDetail,
    CalibrationRunListResponse,
    CalibrationRunRequest,
    CalibrationRunSummary,
    CorrectionListResponse,
    CorrectionRequest,
    CorrectionResponse,
    DatasetInfo,
    ManifestListItem,
    ManifestListResponse,
    ManifestStatsResponse,
    SuggestionItem,
    SuggestionsResponse,
    TestScoreRequest,
    TestScoreResponse,
    TunedThresholdsListResponse,
    TunedThresholdsRecord,
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
app.router.routes.extend(students_scoring.router.routes)
app.router.routes.extend(tenants.router.routes)
app.router.routes.extend(me.router.routes)
