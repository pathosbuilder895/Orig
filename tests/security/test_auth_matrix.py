"""tests/security/test_auth_matrix.py — T-26: auth matrix skeleton.

One parametrised test over (representative route × role), asserting the
observed HTTP status against a committed table (``auth_matrix.json``) so a
future change to the auth policy shows up as a reviewed diff instead of a
silent surprise. This is a **skeleton**: one route per router (the 12
modules under ``original/routers/``, excluding ``__init__.py`` and
``_shared.py``), not full route coverage.

The table is filled from *observation*, not from the desired policy — this
file pins what the code does today, holes included. Where an observed cell
reproduces one of the already-catalogued gaps (T-02, T-63 — see the
docstrings in ``test_cross_tenant_read.py``), the route's JSON entry carries
a ``_note`` naming the gap; the file is still green, because it asserts the
*observed* value, not the desired one.

Roles and how each is minted
-----------------------------
* ``anonymous``       — no Authorization header at all.
* ``student_own``     — ``mint_principal_token(student_a, "student", TENANT_A)``.
* ``student_other``   — ``mint_principal_token(student_b, "student", TENANT_B)``,
  used against routes that name tenant A's resources.
* ``professor_own``   — tenant A staff (``two_tenants["headers_a"]``).
* ``professor_other`` — tenant B staff (``two_tenants["headers_b"]``).
* ``operator``        — a SUPER_ROLES principal, tenant A (cross-tenant by
  design — see ``original/principal.py``).
* ``tampered``        — a validly-shaped, validly-expiring professor token
  with one character of its HMAC signature flipped.
* ``expired``         — a professor token minted with a negative
  ``ttl_seconds`` (see ``mint_principal_token``), so ``exp`` is already in
  the past at request time.

Note on student *sessions*: ``original/student_auth.py`` mints a different
token type (``verify_session``) than the signed principal tokens this file
uses for ``student_own``/``student_other`` (``verify_principal_token``, via
``original.principal.mint_principal_token(..., role="student", ...)``). Only
``/me/*`` reads a session token (``_require_student_session`` in
``original/routers/_shared.py``); a principal token never satisfies it. That
is why ``GET /me/voice`` — the only GET under the ``me`` router — comes back
401 for *every* role in this table, student roles included: it is not a
student-session token, so it is rejected the same as anonymous. This is an
observed, honest result, not a bug in the harness — a session-token variant
of this matrix is out of scope for the skeleton.

JSON table shape: ``{"<METHOD> <path-template>": {"<role>": <status>, "_note": "..."}}``.
Path templates use ``{A}`` / ``{B}`` / ``{A_student}`` placeholders,
substituted at test time from the ``two_tenants`` fixture (tenant A's id,
tenant B's id, and tenant A's baselined student id respectively). A route
whose template carries a query string (``?exam_session_id=...``) keeps it
literally — no placeholder substitution happens there.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from original import principal as pr

pytestmark = pytest.mark.security

_MATRIX_PATH = Path(__file__).parent / "auth_matrix.json"
_MATRIX: dict[str, dict] = json.loads(_MATRIX_PATH.read_text())

ROLES = [
    "anonymous",
    "student_own",
    "student_other",
    "professor_own",
    "professor_other",
    "operator",
    "tampered",
    "expired",
]

# route key -> the original/routers/ module (minus .py) it belongs to. Every
# module in this map is exercised by test_completeness_all_routers_covered;
# every module under original/routers/ (minus __init__.py, _shared.py) must
# appear here at least once.
ROUTE_ROUTER: dict[str, str] = {
    "GET /admin/audit": "admin",
    "GET /auth/me": "auth",
    "GET /bluebook/exams": "bluebook",
    "GET /health": "health",
    "POST /import/courses/{A}-course1/turnitin-csv": "imports",
    "GET /lti/jwks": "lti_routes",
    "GET /me/voice": "me",
    "GET /proctor/park/status?exam_session_id=nonexistent": "proctor",
    "GET /students/{A_student}": "students",
    "GET /baseline-requests/pending": "students_baseline",
    "POST /students/{A_student}/score": "students_scoring",
    "GET /tenants/{A}/stats": "tenants",
}

# Derived from the filesystem, not a literal: a 13th router module added
# under original/routers/ fails the completeness test until the table
# carries a representative route for it.
_ROUTERS_DIR = Path(__file__).resolve().parents[2] / "original" / "routers"
_ALL_ROUTER_MODULES = frozenset(
    path.stem
    for path in _ROUTERS_DIR.glob("*.py")
    if path.stem not in {"__init__", "_shared"}
)

# Routes that take a body other than "none" when the request is expected to
# reach the handler (i.e. every role, including the ones that get rejected
# before the body is even looked at — a syntactically valid body keeps the
# test honest: rejection has to come from auth, not from a 422 on an
# unrelated field).
_SCORE_BODY = {"text": "x" * 400, "assignment": "auth-matrix-probe"}


def _split_method_template(key: str) -> tuple[str, str]:
    method, template = key.split(" ", 1)
    return method, template


def _resolve_path(template: str, *, tenant_a: str, tenant_b: str, student_a: str) -> str:
    return (
        template.replace("{A_student}", student_a)
        .replace("{A}", tenant_a)
        .replace("{B}", tenant_b)
    )


def _role_headers(role: str, tenants: dict) -> dict:
    tenant_a = tenants["tenant_a"]
    tenant_b = tenants["tenant_b"]
    student_a = tenants["student_a"]
    student_b = tenants["student_b"]

    if role == "anonymous":
        return {}
    if role == "student_own":
        tok = pr.mint_principal_token(student_a, "student", tenant_a)
        return {"Authorization": f"Bearer {tok}"}
    if role == "student_other":
        tok = pr.mint_principal_token(student_b, "student", tenant_b)
        return {"Authorization": f"Bearer {tok}"}
    if role == "professor_own":
        return tenants["headers_a"]
    if role == "professor_other":
        return tenants["headers_b"]
    if role == "operator":
        tok = pr.mint_principal_token("op_matrix", "operator", tenant_a)
        return {"Authorization": f"Bearer {tok}"}
    if role == "tampered":
        tok = pr.mint_principal_token(f"prof_{tenant_a}", "professor", tenant_a)
        payload, sig = tok.split(".", 1)
        flipped_char = "A" if sig[0] != "A" else "B"
        return {"Authorization": f"Bearer {payload}.{flipped_char}{sig[1:]}"}
    if role == "expired":
        tok = pr.mint_principal_token(
            f"prof_{tenant_a}", "professor", tenant_a, ttl_seconds=-3600
        )
        return {"Authorization": f"Bearer {tok}"}
    raise ValueError(f"unknown role {role!r}")


def _send(live_client, method: str, path: str, headers: dict):
    if method == "GET":
        return live_client.get(path, headers=headers)
    if method == "POST":
        if "/import/courses/" in path and path.endswith("/turnitin-csv"):
            # Empty CSV: brief-mandated body for the imports representative
            # route (imports has no GET). Authorized roles observe a 422
            # ("CSV is empty or has no data rows"), which is still a
            # meaningful, auth-distinguishing status.
            return live_client.post(
                path, headers=headers, files={"file": ("empty.csv", "", "text/csv")}
            )
        if path.endswith("/score"):
            return live_client.post(path, headers=headers, json=_SCORE_BODY)
        raise AssertionError(f"no POST body rule for {path}")
    raise AssertionError(f"unhandled method {method}")


# ── 1. The parametrised matrix ─────────────────────────────────────────────

_CASES = [
    (route_key, role)
    for route_key in _MATRIX
    for role in ROLES
]


@pytest.mark.parametrize(
    "route_key,role", _CASES, ids=[f"{k} [{r}]" for k, r in _CASES]
)
def test_auth_matrix(pilot_env, store_reset, live_client, two_tenants, route_key, role):
    expected = _MATRIX[route_key][role]
    method, template = _split_method_template(route_key)
    path = _resolve_path(
        template,
        tenant_a=two_tenants["tenant_a"],
        tenant_b=two_tenants["tenant_b"],
        student_a=two_tenants["student_a"],
    )
    headers = _role_headers(role, two_tenants)
    resp = _send(live_client, method, path, headers)
    assert resp.status_code == expected, (
        f"{route_key} [{role}] -> {resp.status_code}, expected {expected}. "
        f"Body: {resp.text[:300]}"
    )


# ── 2. Completeness: every router has >= 1 route in the table ──────────────


def test_completeness_all_routers_covered():
    covered = set(ROUTE_ROUTER.values())
    missing = _ALL_ROUTER_MODULES - covered
    assert not missing, f"routers with no auth-matrix entry: {sorted(missing)}"
    # Every table key is mapped to a real router, and every router in the map
    # is a module actually present under original/routers/ — catches typos both ways.
    unknown = covered - _ALL_ROUTER_MODULES
    assert not unknown, f"ROUTE_ROUTER names unknown router modules: {sorted(unknown)}"
    assert set(_MATRIX) == set(ROUTE_ROUTER), (
        "auth_matrix.json keys and ROUTE_ROUTER keys have drifted apart: "
        f"json-only={set(_MATRIX) - set(ROUTE_ROUTER)}, "
        f"map-only={set(ROUTE_ROUTER) - set(_MATRIX)}"
    )


# ── 3. Anti-staleness: every route key must resolve to a live route ────────

# Dummy substitution values for the placeholder check: any single-path-segment
# string works, since Starlette's default str converter matches anything
# without a "/". Using fixture-independent dummies keeps this test cheap (no
# tenant provisioning) and structural: it fails on a renamed/removed route
# regardless of tenant plumbing.
_DUMMY_A = "dummytenanta"
_DUMMY_B = "dummytenantb"
_DUMMY_A_STUDENT = "dummytenanta:dummystudent"


def _route_exists(live_app, method: str, concrete_path: str) -> bool:
    path_only = concrete_path.split("?", 1)[0]
    for route in live_app.routes:
        methods = getattr(route, "methods", None)
        path_regex: re.Pattern | None = getattr(route, "path_regex", None)
        if methods is None or path_regex is None:
            continue
        if method in methods and path_regex.fullmatch(path_only):
            return True
    return False


@pytest.mark.parametrize("route_key", list(_MATRIX), ids=list(_MATRIX))
def test_anti_staleness_route_exists(live_app, route_key):
    method, template = _split_method_template(route_key)
    concrete_path = _resolve_path(
        template, tenant_a=_DUMMY_A, tenant_b=_DUMMY_B, student_a=_DUMMY_A_STUDENT
    )
    assert _route_exists(live_app, method, concrete_path), (
        f"{route_key} does not resolve to any live route "
        f"({method} {concrete_path.split('?', 1)[0]}) — renamed or removed?"
    )
