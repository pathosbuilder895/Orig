"""
tests/security/test_unauthenticated_writes.py — "I have no token."

docs/testing/04-security-adversarial.md §1.2. Route-table driven: every
write route (POST/PUT/PATCH/DELETE) on the live app must refuse an
anonymous caller under a real deploy (``pilot_env``), unless it is on the
``ANONYMOUS_ALLOWLIST`` (routes that are genuinely meant to be reachable
with no principal) or it is one of the three routes with their own
dedicated red test below.

Path-parameter substitution: a ``/students/{id}/...`` or
``/canvas/baseline/{id}/...`` route is tenant-isolation middleware's
territory (``extract_scoped_id`` + ``assert_student_access``,
original/principal.py), and that middleware treats a *flat* (tenant-less)
id as the anonymous demo sandbox on purpose, in every environment — see
``tests/test_tenant_isolation.py::test_demo_flat_student_round_trip`` and
the "Additive by construction" comment block at original/api.py's
tenant-isolation middleware. Substituting a flat id there would rediscover
that already-tested, intentional behaviour and misreport it as a new hole.
So those two path shapes get a real, *tenant-scoped* but nonexistent id
(built from the ``two_tenants`` fixture's registered pilot tenant) instead
of the generic "x" the brief suggests for every other path parameter —
this is what actually exercises "does a real deploy protect real tenant
data," which is the property this file is testing.
"""

from __future__ import annotations

import re

import pytest

from original import principal as pr

pytestmark = pytest.mark.security

# ── Anonymous-by-design allowlist ─────────────────────────────────────────────
# path -> reason, verified against the handler (see the comment at each row).
ANONYMOUS_ALLOWLIST: dict[str, str] = {
    # Login/launch entry points: reachable with no principal by definition —
    # that's the whole point of a login endpoint.
    "/auth/login": "login entry point; issues the principal, so it cannot require one",
    "/student-auth/login": "student login entry point; same reasoning as /auth/login",
    "/lti/login": "OIDC pre-auth step of an LTI launch; runs before any principal exists",
    "/lti/launch": (
        "LTI launch endpoint; authenticates via its own RSA-signed id_token/state "
        "verification (original/lti.py), not a principal header"
    ),
    # Dormant v1 stack: unmounted under a real deploy. original/api.py mounts
    # /api/v1/* only off real-deploy (see run.py / api.py and
    # tests/test_pilot_lockdown.py::test_v1_demo_login_unmounted_in_pilot),
    # so under pilot_env this route 404s regardless of auth — not a hole,
    # but also not a 401/403, so it can't sit in the generic sweep either.
    "/api/v1/auth/login": "dormant v1 stack; unmounted (404) under a real deploy",
    # Capability-token authenticated, not principal-authenticated: verified
    # against original/routers/proctor.py:beat, whose docstring states
    # "Anonymous by design" — the phone never has a login, and the scanned
    # park_token (a 128-bit secrets.token_urlsafe capability) is the only
    # credential the endpoint ever checks.
    "/proctor/park/beat": (
        "capability-token authenticated (park_token is the credential, not a "
        "principal); documented anonymous-by-design in original/routers/proctor.py"
    ),
}

# ── Known holes with their own dedicated red test, below ─────────────────────
# Excluded from the generic sweep so that only the red tests carry `blocker`
# (per the brief's "split" instruction) — the generic sweep stays green and
# unmarked, exactly like test_static_tree.py's forbidden-path sweep pulls its
# one known-red case into its own function instead of parametrizing it in.
RED_ROUTES: set[tuple[str, str]] = {
    ("POST", "/bluebook/submissions"),  # T-03
    ("POST", "/auth/register"),  # T-64
    ("POST", "/bluebook/exams/{exam_id}/session"),  # T-65
}

# ── The generic green sweep ───────────────────────────────────────────────────
# Every other write route on the live app. Hand-maintained (matching the
# house style of test_pilot_lockdown.py's ADMIN_STAFF_ONLY_ENDPOINTS); the
# completeness test below is what catches a new route nobody added here.
GENERIC_ROUTES: list[tuple[str, str]] = [
    ("DELETE", "/proctor/park/{exam_session_id}"),
    ("DELETE", "/students/{student_id}"),
    ("DELETE", "/tenants/{tenant_id}/students"),
    ("POST", "/admin/calibration/run"),
    ("POST", "/admin/calibration/runs/{run_id}/apply"),
    ("POST", "/bluebook/courses"),
    ("POST", "/bluebook/exams"),
    ("POST", "/canvas/baseline/{student_id}/fetch-submission-text"),
    ("POST", "/canvas/baseline/{student_id}/import-baseline"),
    ("POST", "/canvas/baseline/{student_id}/list-canvas-submissions"),
    ("POST", "/import/courses/{course_id}/turnitin-csv"),
    ("POST", "/me/formation/advance"),
    ("POST", "/me/work"),
    ("POST", "/proctor/park/open"),
    ("POST", "/students/{student_id}/baseline"),
    ("POST", "/students/{student_id}/baseline/upload-batch"),
    ("POST", "/students/{student_id}/formation"),
    ("POST", "/students/{student_id}/formation/advance"),
    ("POST", "/students/{student_id}/request-baseline"),
    ("POST", "/students/{student_id}/score"),
    ("POST", "/students/{student_id}/score/blend"),
    ("POST", "/students/{student_id}/upload"),
    ("POST", "/submissions/{submission_id}/correct"),
    ("POST", "/tenants"),
    ("POST", "/test/score"),
]

# Routes whose Pydantic body model has a required field, so an empty `{}`
# 422s before any auth check runs (FastAPI validates the body before calling
# the endpoint, and these paths are NOT behind the tenant-isolation
# middleware's staff-only/scoped-id gates, which run before body parsing).
# Verified in each handler that the auth check happens once the body is
# valid — see original/routers/bluebook.py (_require_staff), me.py
# (_require_student_session), proctor.py (_require_staff) — so a minimal
# valid body is required to actually exercise that check instead of masking
# it behind a 422.
JSON_BODIES: dict[str, dict] = {
    "/bluebook/courses": {"name": "c"},
    "/bluebook/exams": {"title": "t"},
    "/me/work": {"text": "t"},
    "/proctor/park/open": {"exam_session_id": "e1"},
}

# UploadFile-based routes: (form field name, is-list).
FILE_ROUTES: dict[str, tuple[str, bool]] = {
    "/students/{student_id}/upload": ("file", False),
    "/students/{student_id}/baseline/upload-batch": ("files", True),
    "/import/courses/{course_id}/turnitin-csv": ("file", False),
}

_PATH_PARAM_RE = re.compile(r"\{[^}]+\}")


def _is_student_scoped(path: str) -> bool:
    """True for the two path shapes original.principal.extract_scoped_id covers."""
    return path.startswith("/students/{") or path.startswith("/canvas/baseline/{")


def _concrete_path(path: str, tenant_scoped_id: str) -> str:
    """Fill in path params: the first param of a student-scoped route gets a
    real (but nonexistent) tenant-scoped id; every other param gets "x"
    (course/run/exam/tenant/submission ids — none of these carry tenant
    semantics, so a placeholder is exactly what the brief asks for)."""
    if _is_student_scoped(path):
        path = _PATH_PARAM_RE.sub(tenant_scoped_id, path, count=1)
    return _PATH_PARAM_RE.sub("x", path)


def _send(live_client, method: str, path: str, concrete: str):
    if path in FILE_ROUTES:
        field, is_list = FILE_ROUTES[path]
        if is_list:
            kw = {"files": [(field, ("x.txt", b"x", "text/plain"))]}
        else:
            kw = {"files": {field: ("x.txt", b"x", "text/plain")}}
        return live_client.request(method, concrete, **kw)
    return live_client.request(method, concrete, json=JSON_BODIES.get(path, {}))


# ── 1. Route-table completeness ───────────────────────────────────────────────


def test_every_write_route_is_allowlisted_or_covered(live_app):
    """Every POST/PUT/PATCH/DELETE route is allowlisted, red, or in the sweep.

    Walks the app's own route table (not the hand-maintained lists above) so
    a new write route lands here the day it is added, wherever its router
    lives — the same rationale as
    test_pilot_lockdown.py::test_no_admin_route_answers_a_student_principal.
    """
    from starlette.routing import Route

    covered = set(GENERIC_ROUTES) | RED_ROUTES
    allowlisted_paths = set(ANONYMOUS_ALLOWLIST)
    write_methods = {"POST", "PUT", "PATCH", "DELETE"}

    missing = []
    seen = 0
    for route in live_app.routes:
        if not isinstance(route, Route):
            continue
        path = route.path
        for method in sorted(set(route.methods or []) - {"HEAD", "OPTIONS"}):
            if method not in write_methods:
                continue
            seen += 1
            if path in allowlisted_paths:
                continue
            if (method, path) in covered:
                continue
            missing.append(f"{method} {path}")
    assert missing == [], f"write routes neither allowlisted nor covered: {missing}"
    # Sanity: the walk actually found routes rather than matching nothing.
    assert seen == len(GENERIC_ROUTES) + len(RED_ROUTES) + len(ANONYMOUS_ALLOWLIST), (
        seen,
        len(GENERIC_ROUTES) + len(RED_ROUTES) + len(ANONYMOUS_ALLOWLIST),
    )


def test_no_stale_entries_in_hand_maintained_lists(live_app):
    """Every hand-maintained (method, path) still names a route that exists.

    Catches the opposite drift from the completeness test above: an entry
    here for a route that was renamed or removed, silently no longer
    testing anything.
    """
    from starlette.routing import Route

    live_write_routes = {
        (method, route.path)
        for route in live_app.routes
        if isinstance(route, Route)
        for method in (set(route.methods or []) - {"HEAD", "OPTIONS"})
        if method in {"POST", "PUT", "PATCH", "DELETE"}
    }
    live_paths = {path for _, path in live_write_routes}

    for method, path in GENERIC_ROUTES:
        assert (method, path) in live_write_routes, f"stale GENERIC_ROUTES entry: {method} {path}"
    for method, path in RED_ROUTES:
        assert (method, path) in live_write_routes, f"stale RED_ROUTES entry: {method} {path}"
    for path in ANONYMOUS_ALLOWLIST:
        assert path in live_paths, f"stale ANONYMOUS_ALLOWLIST entry: {path}"


# ── 2. The generic green sweep ────────────────────────────────────────────────


@pytest.mark.parametrize("method,path", GENERIC_ROUTES, ids=[f"{m}_{p}" for m, p in GENERIC_ROUTES])
def test_unauthenticated_write_refused(pilot_env, two_tenants, live_client, method, path):
    """No principal -> 401/403 on every route not allowlisted or already red."""
    tenant_scoped_id = f"{two_tenants['tenant_a']}:ghost-nonexistent"
    concrete = _concrete_path(path, tenant_scoped_id)
    r = _send(live_client, method, path, concrete)
    assert r.status_code in (401, 403), f"{method} {concrete} -> {r.status_code}: {r.text}"


# ── 3. Known/newly-found holes, one dedicated test each ──────────────────────


@pytest.mark.blocker
def test_bluebook_submissions_refuses_anonymous_write(pilot_env, store_reset, live_client):
    """T-03: POST /bluebook/submissions records a sat exam with no principal.

    original/routers/bluebook.py:bluebook_record_submission calls
    ``_bluebook_tenant(request)`` (original/routers/_shared.py), which
    silently falls back to ``principal_mod.DEMO_TENANT`` for any caller
    without a principal-token/session — including on a real deploy, since
    this handler has no ``_require_staff``/``_require_student_session``
    call at all. The path also isn't covered by the tenant-isolation
    middleware's staff-only prefixes (those match ``/submissions/``, the
    per-submission-correction surface, not ``/bluebook/submissions``).
    """
    r = live_client.post(
        "/bluebook/submissions",
        json={"candidate": "Attacker", "exam_title": "Final", "word_count": 500},
    )
    assert r.status_code in (401, 403), f"expected a refusal, got {r.status_code}: {r.text}"


@pytest.mark.blocker
def test_auth_register_refuses_anonymous_registration(pilot_env, store_reset, live_client):
    """T-64: POST /auth/register anonymously provisions a staff account.

    original/routers/auth.py:auth_register calls only ``_require_guard``,
    which is a no-op unless the ``GUARD_DESTRUCTIVE`` env var is set — it
    never checks ``_IS_REAL_DEPLOY``. The docstring claims this is "guarded
    by GUARD_DESTRUCTIVE in pilot/production" as though that followed from
    being a real deploy, but ``pilot_env`` (this test's real-deploy fixture,
    matching what a pilot boot actually sets) does not set
    ``GUARD_DESTRUCTIVE`` — nothing does, unless an operator opts in
    separately. An anonymous caller can self-provision a professor/admin/
    operator account for an arbitrary tenant on an unmodified pilot
    deploy.
    """
    r = live_client.post(
        "/auth/register",
        json={
            "email": "attacker@evil.example",
            "password": "hunter2222",
            "tenant_id": "probeC",
            "role": "professor",
        },
    )
    assert r.status_code in (401, 403), f"expected a refusal, got {r.status_code}: {r.text}"


@pytest.mark.blocker
def test_bluebook_session_open_refuses_anonymous_write(
    pilot_env, store_reset, live_client, principal_headers
):
    """T-65: POST /bluebook/exams/{exam_id}/session opens a sitting with no principal.

    original/routers/bluebook.py:bluebook_start_session has no
    ``_require_staff``/``_require_student_session`` call — it resolves the
    caller's tenant via the same demo-defaulting ``_bluebook_tenant`` as
    T-03 and only checks that the target exam's ``tenant_id`` matches.
    An anonymous caller's tenant always resolves to ``"demo"``, so any exam
    created under the ``"demo"`` tenant (any staff principal can mint one —
    "demo" is just a string, not a registered/verified tenant) has its
    exam-day sittings anonymously openable, pinning a server-side deadline
    for an arbitrary ``student_id`` supplied by the caller.
    """
    prof = principal_headers("prof_demo_exam_t65", "professor", pr.DEMO_TENANT)
    r = live_client.post("/bluebook/exams", json={"title": "Midterm"}, headers=prof)
    assert r.status_code == 201, r.text
    exam_id = r.json()["id"]

    r = live_client.post(
        f"/bluebook/exams/{exam_id}/session", json={"student_id": "attacker-flat-id"}
    )
    assert r.status_code in (401, 403), f"expected a refusal, got {r.status_code}: {r.text}"
