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
original/principal.py). The generic sweep below (section 2) substitutes a
real, *tenant-scoped* but nonexistent id (``{tenant}:ghost-nonexistent``,
built from the ``two_tenants`` fixture's registered pilot tenant) for the
first parameter of these two path shapes, instead of the generic "x" the
brief suggests for every other path parameter — that's what exercises
"does a real deploy protect one tenant's data from another," and it stays
green.

That is a *different* question from "what happens with a flat id," and the
two must not be conflated: ``original.principal.assert_student_access``
returns (permits) whenever the caller is the anonymous demo principal and
the target id is flat (``tenant_of(id) is None``) — with **no
``_IS_REAL_DEPLOY`` branch at all**, unlike ``_require_staff`` and the
tenant-isolation middleware's own staff-only path list
(``original/api.py:_is_staff_only_path``), which does not cover
``/students/{id}/...`` routes individually. So on an unmodified pilot
deploy, a flat id is anonymously writable and deletable — confirmed
empirically (not just by reading the code) against all 8 routes below that
can actually reach the check. This is tracked as **T-66** and covered by
``test_flat_id_student_write_permitted`` (section 2b). It is a real,
open gap, not "already-tested, intentional behaviour" — the only test that
previously exercised a flat id at all
(``tests/test_tenant_isolation.py::test_demo_flat_student_round_trip``)
runs in the demo environment, which never sets ``_IS_REAL_DEPLOY`` and so
says nothing about a real deploy.

``/students/{id}/request-baseline`` is excluded from T-66's route list: it
503s on missing Bbook config regardless of id shape or auth, so that
failure mode isn't evidence of a bypass. The three
``/canvas/baseline/{id}/...`` routes are also excluded: each calls its own
``_require_staff`` before touching ``student_id`` at all, so they 401
regardless of id shape — verified empirically, see the comment above
``FLAT_ID_ROUTES``.
"""

from __future__ import annotations

import re

import numpy as np
import pytest

from original import principal as pr

pytestmark = pytest.mark.security

# ── Anonymous-by-design allowlist ─────────────────────────────────────────────
# (method, path) -> reason, verified against the handler (see the comment at
# each row). Keyed by method, not just path, so a route that mixes an
# anonymous-by-design method with a write method that ISN'T (e.g. a future
# DELETE added to a path that only allowlists POST today) doesn't silently
# inherit the allowlisting — every method on a path used to be exempted by
# path alone, which the completeness/staleness tests below could not catch.
ANONYMOUS_ALLOWLIST: dict[tuple[str, str], str] = {
    # Login/launch entry points: reachable with no principal by definition —
    # that's the whole point of a login endpoint.
    ("POST", "/auth/login"): "login entry point; issues the principal, so it cannot require one",
    ("POST", "/student-auth/login"): "student login entry point; same reasoning as /auth/login",
    # /lti/login is registered for GET and POST; GET isn't a write method so
    # it never reaches this table, but the POST arm needs its own entry.
    ("POST", "/lti/login"): "OIDC pre-auth step of an LTI launch; runs before any principal exists",
    ("POST", "/lti/launch"): (
        "LTI launch endpoint; authenticates via its own RSA-signed id_token/state "
        "verification (original/lti.py), not a principal header"
    ),
    # Dormant v1 stack: unmounted under a real deploy. original/api.py mounts
    # /api/v1/* only off real-deploy (see run.py / api.py and
    # tests/test_pilot_lockdown.py::test_v1_demo_login_unmounted_in_pilot),
    # so under pilot_env this route 404s regardless of auth — not a hole,
    # but also not a 401/403, so it can't sit in the generic sweep either.
    ("POST", "/api/v1/auth/login"): "dormant v1 stack; unmounted (404) under a real deploy",
    # Capability-token authenticated, not principal-authenticated: verified
    # against original/routers/proctor.py:beat, whose docstring states
    # "Anonymous by design" — the phone never has a login, and the scanned
    # park_token (a 128-bit secrets.token_urlsafe capability) is the only
    # credential the endpoint ever checks.
    ("POST", "/proctor/park/beat"): (
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
    allowlisted = set(ANONYMOUS_ALLOWLIST)  # (method, path) tuples
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
            if (method, path) in allowlisted:
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
    for method, path in GENERIC_ROUTES:
        assert (method, path) in live_write_routes, f"stale GENERIC_ROUTES entry: {method} {path}"
    for method, path in RED_ROUTES:
        assert (method, path) in live_write_routes, f"stale RED_ROUTES entry: {method} {path}"
    for method, path in ANONYMOUS_ALLOWLIST:
        assert (method, path) in live_write_routes, (
            f"stale ANONYMOUS_ALLOWLIST entry: {method} {path}"
        )
    for method, path in FLAT_ID_ROUTES:
        assert (method, path) in live_write_routes, f"stale FLAT_ID_ROUTES entry: {method} {path}"


# ── 2. The generic green sweep ────────────────────────────────────────────────


@pytest.mark.parametrize("method,path", GENERIC_ROUTES, ids=[f"{m}_{p}" for m, p in GENERIC_ROUTES])
def test_unauthenticated_write_refused(pilot_env, two_tenants, live_client, method, path):
    """No principal -> 401/403 on every route not allowlisted or already red."""
    tenant_scoped_id = f"{two_tenants['tenant_a']}:ghost-nonexistent"
    concrete = _concrete_path(path, tenant_scoped_id)
    r = _send(live_client, method, path, concrete)
    assert r.status_code in (401, 403), f"{method} {concrete} -> {r.status_code}: {r.text}"


# ── 2b. Flat-id student writes: T-66 ──────────────────────────────────────────
# The two path shapes _concrete_path treats specially above get a SECOND,
# separate probe here: a genuinely flat id ("x"), not a tenant-scoped
# nonexistent one. original.principal.assert_student_access permits the
# anonymous demo principal over any flat id with no _IS_REAL_DEPLOY branch at
# all (see the module docstring) — these 8 routes are the ones that actually
# reach that check and are empirically writable/deletable with no principal.
#
# Excluded, both verified empirically rather than assumed from the code:
#   - /students/{id}/request-baseline: 503s on missing Bbook config
#     regardless of id shape or auth, so a non-401/403 there isn't evidence
#     of a bypass.
#   - the three /canvas/baseline/{id}/... routes: each calls its own
#     _require_staff (original/routers/imports.py) before ever looking at
#     student_id, so they 401 for a flat id exactly as they do for a
#     tenant-scoped one — this is the "own staff check" case the module
#     docstring refers to.
FLAT_ID_ROUTES: list[tuple[str, str]] = [
    ("POST", "/students/{student_id}/baseline"),
    ("POST", "/students/{student_id}/baseline/upload-batch"),
    ("POST", "/students/{student_id}/upload"),
    ("POST", "/students/{student_id}/score"),
    ("POST", "/students/{student_id}/score/blend"),
    ("POST", "/students/{student_id}/formation"),
    ("POST", "/students/{student_id}/formation/advance"),
    ("DELETE", "/students/{student_id}"),
]

FLAT_ID_STUDENT_ID = "x"

# text bodies for the routes whose Pydantic model requires a non-empty
# "text" field — same masking hazard as JSON_BODIES above: an empty {}
# 422s before assert_student_access's permit is ever exercised.
FLAT_ID_JSON_BODIES: dict[str, dict] = {
    "/students/{student_id}/baseline": {"text": "word " * 150},
    "/students/{student_id}/score": {"text": "word " * 150},
    "/students/{student_id}/score/blend": {"text": "word " * 150},
}


def _seed_flat_id_state(path: str, student_id: str) -> None:
    """Pre-seed only what a route needs to reach the write/delete itself,
    rather than fail earlier on an unrelated precondition: DELETE needs a
    student to delete, formation/advance needs an open pathway, and
    score/score-blend need an existing baseline to score against (a bare
    get_or_create isn't enough — verified empirically, both 404
    "Add baseline samples first" without this). Seeded directly via the
    repository, not through another anonymous call, so this test doesn't
    depend on any of the other T-66 routes to set itself up.
    """
    from original.constants import FEATURE_DIM
    from original.quantum.state import BaselineSample, StudentState
    from original.repository import get_repository

    repo = get_repository()
    if path == "/students/{student_id}":
        repo.get_or_create(student_id)
    elif path == "/students/{student_id}/formation/advance":
        repo.open_formation_pathway(student_id)
    elif path in (
        "/students/{student_id}/score",
        "/students/{student_id}/score/blend",
    ):
        state = StudentState(student_id=student_id)
        state.add_sample(
            BaselineSample(
                text="seed baseline sample for the flat-id scoring probe " * 3,
                vector=np.random.default_rng(0).random(FEATURE_DIM).astype(np.float64),
                provenance="verified",
                auth_weight=1.0,
                assignment="seed",
            )
        )
        repo.put(state)


@pytest.mark.parametrize("method,path", FLAT_ID_ROUTES, ids=[f"{m}_{p}" for m, p in FLAT_ID_ROUTES])
def test_flat_id_student_write_permitted(pilot_env, store_reset, live_client, method, path):
    """T-66: anonymous flat-id student writes and deletes are permitted on a real deploy.

    original/principal.py:assert_student_access returns (permits) whenever
    the caller is the anonymous demo principal AND the target id is flat
    (``tenant_of(id) is None``) — with no ``_IS_REAL_DEPLOY`` check at all,
    unlike ``_require_staff`` and the tenant-isolation middleware's own
    staff-only path list (``original/api.py:_is_staff_only_path``), which
    doesn't cover ``/students/{id}/...`` routes individually. So a flat id
    reads as "the demo sandbox" in every environment including
    pilot/production: anyone who knows or guesses one can write to, or
    delete, that record with no credentials at all.
    """
    _seed_flat_id_state(path, FLAT_ID_STUDENT_ID)
    concrete = path.replace("{student_id}", FLAT_ID_STUDENT_ID)
    if path in FILE_ROUTES:
        field, is_list = FILE_ROUTES[path]
        if is_list:
            kw = {"files": [(field, ("x.txt", b"x", "text/plain"))]}
        else:
            kw = {"files": {field: ("x.txt", b"x", "text/plain")}}
        r = live_client.request(method, concrete, **kw)
    else:
        r = live_client.request(method, concrete, json=FLAT_ID_JSON_BODIES.get(path, {}))
    assert r.status_code in (401, 403), f"{method} {concrete} -> {r.status_code}: {r.text}"


# ── 3. Known/newly-found holes, one dedicated test each ──────────────────────


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


def test_auth_register_refuses_anonymous_registration(
    pilot_env, monkeypatch, store_reset, live_client
):
    """T-64, FIXED: POST /auth/register used to accept an anonymous caller
    on a real deploy — ``_require_guard`` was a no-op unless an operator
    separately set ``GUARD_DESTRUCTIVE``, and this route sat behind no
    other gate (unlike every other staff-only surface, which the
    tenant-isolation middleware's path list already covers). Closed by
    routing through ``force=_IS_REAL_DEPLOY`` (original/routers/auth.py),
    the same mechanism T-66 below documents for the write endpoints.

    MAINTENANCE_TOKEN must be set here — force=True still needs a real
    token configured to distinguish "refused" (403) from "misconfigured
    deploy" (503); ``pilot_env`` alone only flips ``_IS_REAL_DEPLOY``.
    """
    import original.api

    monkeypatch.setattr(original.api, "_MAINTENANCE_TOKEN", "test-guard-token-197")
    r = live_client.post(
        "/auth/register",
        json={
            "email": "attacker@evil.example",
            "password": "hunter2222",
            "tenant_id": "probeC",
            "role": "professor",
        },
    )
    assert r.status_code == 403, f"expected a refusal, got {r.status_code}: {r.text}"


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
