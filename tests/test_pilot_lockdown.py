"""
Pilot lockdown tests — the go-live security gate.

Proves the invariants a seminary deployment depends on:
  1. Tenant writes are guarded, and a pilot tenant can never be downgraded
     to demo (which would make its FERPA data anonymously readable).
  2. On real deploys, unscoped surfaces (roster, /admin/*, /tenants,
     baseline-request queues) require an authenticated staff principal.
  3. Demo-only artifacts (seed.db, lab pages) 404 on real deploys, the v1
     demo login is unmounted, and a '*' CORS origin refuses to boot.
  4. Seeding synthetic data is impossible when ORIGINAL_ENV is real.
  5. FERPA deletion purges the display name and the student's audit-log
     history (one deletion-receipt row is written afterwards).
  6. The in-app backup scheduler writes consistent, pruned copies.

Every pilot-only behaviour is toggled via module globals on the loaded
legacy app (monkeypatch), so the anonymous demo — covered by the rest of
the suite — stays byte-identical.

Uses the shared live_app/live_client fixtures from conftest.py (WS-5 §5.1)
instead of re-deriving `run.load_legacy_demo_app()` at module scope.
"""

import re
import sqlite3

import pytest

import run  # repo-root launcher
from original import principal as pr
from original import backup as backup_mod
from original import store

GUARD_TOKEN = "test-guard-token"
GUARD = {"X-Guard-Token": GUARD_TOKEN}

# ~140 words — comfortably above any baseline minimum.
LONG_TEXT = (
    "The doctrine of justification by faith stands at the center of the gospel. "
    "When Paul writes to the Romans, he labors to show that righteousness comes "
    "not by works of the law but through faith in Christ alone. This conviction "
    "shaped the Reformation and continues to shape pastoral practice today. "
    "A careful reader notices how the argument unfolds in stages, each building "
    "on the last, until the conclusion becomes unavoidable. The voice here is "
    "deliberate and measured, favoring long subordinate clauses and a vocabulary "
    "drawn from systematic theology. Such patterns, repeated across many essays, "
    "form a fingerprint as distinctive as handwriting. The seminary student who "
    "writes this way in September will, absent intervention, write this way in "
    "May, and that continuity is precisely what we set out to measure and to "
    "protect with patience and with care."
)


def _auth(token: str):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def api_mod(live_app):
    """The loaded app module (plain original.api since WS-6 P6)."""
    import original.api

    return original.api


@pytest.fixture
def real_deploy(api_mod, monkeypatch):
    """Flip the loaded app into pilot behaviour without reloading it."""
    monkeypatch.setattr(api_mod, "_IS_REAL_DEPLOY", True)
    yield


@pytest.fixture
def guarded(api_mod, monkeypatch):
    monkeypatch.setattr(api_mod, "_GUARD_DESTRUCTIVE", True)
    monkeypatch.setattr(api_mod, "_MAINTENANCE_TOKEN", GUARD_TOKEN)
    yield


# ── 0. Testing-Phase-A findings (T-64/T-65/T-66) ──────────────────────────────


def test_register_refuses_anonymous_on_real_deploy(real_deploy, api_mod, monkeypatch, live_client):
    """T-64: /auth/register used to be reachable anonymously on a real deploy
    unless an operator separately opted into GUARD_DESTRUCTIVE — nothing sets
    that by default, so self-provisioning a staff account for an arbitrary
    tenant was open on an unmodified pilot deploy."""
    monkeypatch.setattr(api_mod, "_MAINTENANCE_TOKEN", GUARD_TOKEN)
    r = live_client.post(
        "/auth/register",
        json={
            "email": "attacker@evil.example",
            "password": "hunter2222",
            "tenant_id": "lockacme",
            "role": "professor",
        },
    )
    assert r.status_code == 403, r.text


def test_register_works_with_guard_token_on_real_deploy(
    real_deploy, api_mod, monkeypatch, live_client, store_reset
):
    """The forced guard on a real deploy is satisfiable with the right
    X-Guard-Token, not an unconditional lockout."""
    monkeypatch.setattr(api_mod, "_MAINTENANCE_TOKEN", GUARD_TOKEN)
    r = live_client.post(
        "/auth/register",
        json={
            "email": "legit.t64@acmeu.edu",
            "password": "s3cret-passw0rd",
            "tenant_id": "lockacme",
            "role": "professor",
        },
        headers=GUARD,
    )
    assert r.status_code == 201, r.text


def test_bluebook_session_refuses_anonymous_on_real_deploy(real_deploy, live_client):
    """T-65: POST /bluebook/exams/{exam_id}/session had no auth check at all —
    any exam under the demo tenant (any staff principal can mint one) could
    have its sitting anonymously opened, pinning a server-side deadline for
    an arbitrary caller-supplied student_id."""
    prof = pr.mint_principal_token("prof_t65", "professor", "demo")
    r = live_client.post("/bluebook/exams", json={"title": "Midterm"}, headers=_auth(prof))
    assert r.status_code == 201, r.text
    exam_id = r.json()["id"]

    r = live_client.post(
        f"/bluebook/exams/{exam_id}/session", json={"student_id": "attacker-flat-id"}
    )
    assert r.status_code in (401, 403), r.text


def test_flat_id_student_delete_refused_anonymously_on_real_deploy(real_deploy, live_client):
    """T-66: assert_student_access's flat-id/demo-tenant carve-out had no
    real-deploy check at all, so a flat id read as 'demo sandbox data' in
    every environment including pilot/production — anonymously readable,
    writable, and deletable."""
    r = live_client.delete("/students/some-flat-id")
    assert r.status_code in (401, 403), r.text


# ── 1. Tenant writes ──────────────────────────────────────────────────────────


def test_tenant_write_requires_guard(guarded, live_client):
    body = {"tenant_id": "lockacme", "name": "Lock Acme", "environment": "pilot"}
    r = live_client.post("/tenants", json=body)
    assert r.status_code == 403
    r = live_client.post("/tenants", json=body, headers=GUARD)
    assert r.status_code == 201, r.text


def test_tenant_downgrade_to_demo_refused(guarded, live_client):
    live_client.post(
        "/tenants",
        json={"tenant_id": "lockpilot", "name": "Lock Pilot", "environment": "pilot"},
        headers=GUARD,
    )
    r = live_client.post(
        "/tenants",
        json={"tenant_id": "lockpilot", "name": "Lock Pilot", "environment": "demo"},
        headers=GUARD,
    )
    assert r.status_code == 409
    assert "downgrade" in r.json()["detail"].lower()
    # Same-environment update stays allowed.
    r = live_client.post(
        "/tenants",
        json={"tenant_id": "lockpilot", "name": "Lock Pilot Renamed", "environment": "pilot"},
        headers=GUARD,
    )
    assert r.status_code == 201, r.text


def test_fresh_demo_tenant_still_creatable(guarded, live_client):
    """Registering a brand-new demo tenant (with the guard) keeps working."""
    r = live_client.post(
        "/tenants",
        json={"tenant_id": "lockdemo", "name": "Lock Demo", "environment": "demo"},
        headers=GUARD,
    )
    assert r.status_code == 201, r.text


# ── 2. Staff-only surfaces on real deploys ────────────────────────────────────

STAFF_ONLY_GETS = [
    "/students",
    "/tenants",
    "/admin/audit",
    "/admin/manifests",
    "/admin/corrections",
    "/baseline-requests/pending",
]


@pytest.mark.parametrize("path", STAFF_ONLY_GETS)
def test_anonymous_blocked_on_staff_paths_in_pilot(real_deploy, live_client, path):
    r = live_client.get(path)
    assert r.status_code == 401, f"{path} -> {r.status_code}"


def test_staff_principal_passes_in_pilot(real_deploy, live_client):
    prof = pr.mint_principal_token("prof_lock", "professor", "lockacme")
    r = live_client.get("/students", headers=_auth(prof))
    assert r.status_code == 200, r.text
    op = pr.mint_principal_token("op_lock", "operator", "lockacme")
    r = live_client.get("/tenants", headers=_auth(op))
    assert r.status_code == 200, r.text


def test_student_principal_blocked_on_staff_paths_in_pilot(real_deploy, live_client):
    stu = pr.mint_principal_token("lockacme:bob", "student", "lockacme")
    r = live_client.get("/students", headers=_auth(stu))
    assert r.status_code == 401


def test_demo_keeps_anonymous_roster(live_client):
    """No real_deploy fixture → demo behaviour unchanged."""
    r = live_client.get("/students")
    assert r.status_code == 200


# ── 2b. Endpoint-level staff gate on the admin router ─────────────────────────
# The §2 middleware only runs when ORIGINAL_ENV is real. Correction rows carry
# student_id, so — exactly like /admin/audit — the handler keeps its own staff
# check: it additionally rejects STUDENT principals in the demo, and it still
# holds if a deploy is ever misconfigured with ORIGINAL_ENV unset.


def test_admin_corrections_rejects_student_principal_in_demo(live_client):
    """A student must never enumerate corrections, even in the demo sandbox.

    `x-demo-role` drives the anonymous principal's role, so this exercises the
    handler's `_require_staff` check without needing a real student login
    (same technique as tests/test_tenants_api_coverage.py).
    """
    r = live_client.get("/admin/corrections", headers={"x-demo-role": "student"})
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "Staff role required."


def test_admin_corrections_rejects_signed_in_student_in_demo(live_client):
    """An authenticated student principal is refused on the same grounds.

    Covers the non-demo principal branch of `_require_staff` (is_demo=False,
    role="student"), which the x-demo-role header cannot reach.
    """
    stu = pr.mint_principal_token("corracme:bob", "student", "corracme")
    r = live_client.get("/admin/corrections", headers=_auth(stu))
    assert r.status_code == 403, r.text


def test_admin_corrections_keeps_anonymous_demo_readable(live_client):
    """The zero-login demo sandbox is unchanged — its principal is staff-role."""
    r = live_client.get("/admin/corrections")
    assert r.status_code == 200, r.text


def test_admin_corrections_rejects_anonymous_in_pilot(real_deploy, live_client):
    """On a real deploy an unauthenticated caller gets 401, never correction rows."""
    r = live_client.get("/admin/corrections")
    assert r.status_code == 401, r.text


def test_admin_corrections_allows_staff_principal_in_pilot(real_deploy, live_client):
    """A signed-in professor still reads the list the CorrectionPanel UI needs."""
    prof = pr.mint_principal_token("prof_corr", "professor", "corracme")
    r = live_client.get("/admin/corrections", headers=_auth(prof))
    assert r.status_code == 200, r.text


# ── 2c. Cross-tenant scoping on /admin/audit, /admin/manifests, /admin/corrections
# Previously any staff principal, regardless of tenant, could read every
# institution's rows on these three endpoints -- audit actions, manifest
# rows (which carry student_id and divergence scores), and correction rows.


def test_admin_audit_is_scoped_to_the_callers_tenant(live_client, store_reset):
    store.log_audit(action="score", student_id="tenscope-a:alice", tenant_id="tenscope-a")
    store.log_audit(action="score", student_id="tenscope-b:bob", tenant_id="tenscope-b")

    prof_a = pr.mint_principal_token("prof-a", "professor", "tenscope-a")
    r = live_client.get("/admin/audit", headers=_auth(prof_a))
    assert r.status_code == 200, r.text
    ids = {item["student_id"] for item in r.json()["items"]}
    assert "tenscope-a:alice" in ids
    assert "tenscope-b:bob" not in ids

    operator = pr.mint_principal_token("op-1", "operator", "tenscope-a")
    r = live_client.get("/admin/audit", headers=_auth(operator))
    ids = {item["student_id"] for item in r.json()["items"]}
    assert "tenscope-a:alice" in ids and "tenscope-b:bob" in ids


def test_admin_manifests_is_scoped_to_the_callers_tenant(live_client, store_reset):
    store.put_manifest("sub-a1", "tenscope-a:alice", {"flags": []}, divergence_score=0.1)
    store.put_manifest("sub-b1", "tenscope-b:bob", {"flags": []}, divergence_score=0.1)

    prof_a = pr.mint_principal_token("prof-a", "professor", "tenscope-a")
    r = live_client.get("/admin/manifests", headers=_auth(prof_a))
    assert r.status_code == 200, r.text
    ids = {item["student_id"] for item in r.json()["items"]}
    assert "tenscope-a:alice" in ids
    assert "tenscope-b:bob" not in ids

    operator = pr.mint_principal_token("op-1", "operator", "tenscope-a")
    r = live_client.get("/admin/manifests", headers=_auth(operator))
    ids = {item["student_id"] for item in r.json()["items"]}
    assert "tenscope-a:alice" in ids and "tenscope-b:bob" in ids


def test_admin_corrections_is_scoped_to_the_callers_tenant(live_client, store_reset):
    store.put_correction("sub-a2", True, student_id="tenscope-a:alice")
    store.put_correction("sub-b2", True, student_id="tenscope-b:bob")

    prof_a = pr.mint_principal_token("prof-a", "professor", "tenscope-a")
    r = live_client.get("/admin/corrections", headers=_auth(prof_a))
    assert r.status_code == 200, r.text
    ids = {item["student_id"] for item in r.json()["items"]}
    assert "tenscope-a:alice" in ids
    assert "tenscope-b:bob" not in ids

    operator = pr.mint_principal_token("op-1", "operator", "tenscope-a")
    r = live_client.get("/admin/corrections", headers=_auth(operator))
    ids = {item["student_id"] for item in r.json()["items"]}
    assert "tenscope-a:alice" in ids and "tenscope-b:bob" in ids


# The rest of the admin router carries the same gate, for the same reasons.
# /admin/manifests is the sharpest case — manifest rows carry student_id and the
# endpoint takes a student_id filter, so it is the exposure class /admin/audit
# and /admin/corrections already guard against. The calibration-lab and
# tuned-threshold surfaces are staff tooling that steers scoring globally.
# docs/API_REFERENCE.md has documented every one of these as "Principal (staff)"
# since it was written; these tests make the code match that contract.
#
# Each row is (method, path, json body, status a *staff* caller should get).
# The bodies are deliberately unsatisfiable — an unknown dataset label and a
# nonexistent run id — so the two POSTs prove the gate without starting a real
# calibration run or writing a threshold set. A staff caller therefore lands on
# the handler's own 422/404, which is itself the proof the gate let them past.
ADMIN_STAFF_ONLY_ENDPOINTS = [
    # Lives in routers/health.py, not routers/admin.py — the reason a by-hand
    # sweep of the admin router missed it. See the route walk below.
    ("GET", "/admin/health", None, 200),
    ("GET", "/admin/manifests", None, 200),
    ("GET", "/admin/manifests/stats", None, 200),
    ("GET", "/admin/lab/datasets", None, 200),
    ("GET", "/admin/calibration/runs", None, 200),
    ("GET", "/admin/calibration/runs/999999", None, 404),
    ("GET", "/admin/calibration/runs/999999/suggestions", None, 404),
    ("GET", "/admin/tuned-thresholds", None, 200),
    ("GET", "/admin/tuned-thresholds/history", None, 200),
    ("POST", "/admin/calibration/run", {"dataset_label": "totally_made_up"}, 422),
    (
        "POST",
        "/admin/calibration/runs/999999/apply",
        {"no_action": 0.4, "monitor": 0.6, "escalate": 0.8},
        404,
    ),
]

# Readable ids in pytest output ("…[GET-/admin/manifests]") instead of body dicts.
_ENDPOINT_IDS = [f"{m}-{p}" for m, p, _b, _s in ADMIN_STAFF_ONLY_ENDPOINTS]


def _call(client, method, path, body, headers=None):
    """Issue one request from the ADMIN_STAFF_ONLY_ENDPOINTS table."""
    if method == "POST":
        return client.post(path, json=body, headers=headers or {})
    return client.get(path, headers=headers or {})


@pytest.mark.parametrize(
    "method,path,body,staff_status", ADMIN_STAFF_ONLY_ENDPOINTS, ids=_ENDPOINT_IDS
)
def test_admin_endpoint_rejects_student_principal_in_demo(
    live_client, method, path, body, staff_status
):
    """A student must never reach admin tooling, even in the demo sandbox.

    `x-demo-role` drives the anonymous principal's role, so this exercises each
    handler's `_require_staff` check without needing a real student login.
    """
    r = _call(live_client, method, path, body, headers={"x-demo-role": "student"})
    assert r.status_code == 403, f"{method} {path} -> {r.status_code}: {r.text}"
    assert r.json()["detail"] == "Staff role required."


@pytest.mark.parametrize(
    "method,path,body,staff_status", ADMIN_STAFF_ONLY_ENDPOINTS, ids=_ENDPOINT_IDS
)
def test_admin_endpoint_rejects_signed_in_student_in_demo(
    live_client, method, path, body, staff_status
):
    """An authenticated student principal is refused on the same grounds.

    Covers the non-demo branch of `_require_staff` (is_demo=False,
    role="student"), which the x-demo-role header cannot reach.
    """
    stu = pr.mint_principal_token("adminacme:bob", "student", "adminacme")
    r = _call(live_client, method, path, body, headers=_auth(stu))
    assert r.status_code == 403, f"{method} {path} -> {r.status_code}: {r.text}"


@pytest.mark.parametrize(
    "method,path,body,staff_status", ADMIN_STAFF_ONLY_ENDPOINTS, ids=_ENDPOINT_IDS
)
def test_admin_endpoint_keeps_anonymous_demo_working(
    live_client, method, path, body, staff_status
):
    """The zero-login demo sandbox is unchanged — its principal is staff-role.

    This is what keeps demo/admin.html, demo/admin-context.html, demo/lab.html
    and demo/professor.html working without an Authorization header.
    """
    r = _call(live_client, method, path, body)
    assert r.status_code == staff_status, f"{method} {path} -> {r.status_code}: {r.text}"


@pytest.mark.parametrize(
    "method,path,body,staff_status", ADMIN_STAFF_ONLY_ENDPOINTS, ids=_ENDPOINT_IDS
)
def test_admin_endpoint_rejects_anonymous_in_pilot(
    real_deploy, live_client, method, path, body, staff_status
):
    """On a real deploy an unauthenticated caller gets 401, never admin data."""
    r = _call(live_client, method, path, body)
    assert r.status_code == 401, f"{method} {path} -> {r.status_code}: {r.text}"


@pytest.mark.parametrize(
    "method,path,body,staff_status", ADMIN_STAFF_ONLY_ENDPOINTS, ids=_ENDPOINT_IDS
)
def test_admin_endpoint_allows_staff_principal_in_pilot(
    real_deploy, live_client, method, path, body, staff_status
):
    """A signed-in professor still reaches every surface the admin UIs need."""
    prof = pr.mint_principal_token("prof_admin", "professor", "adminacme")
    r = _call(live_client, method, path, body, headers=_auth(prof))
    assert r.status_code == staff_status, f"{method} {path} -> {r.status_code}: {r.text}"


def test_no_admin_route_answers_a_student_principal(live_app, live_client):
    """Every /admin/* route refuses a student — enumerated from the app itself.

    ADMIN_STAFF_ONLY_ENDPOINTS above is hand-maintained, so it only covers the
    routes someone remembered to add. This walks the app's own route table
    instead, which means a new /admin/* endpoint is covered the day it is
    added, wherever its router lives. (It is how /admin/health was found: that
    one sits in routers/health.py rather than routers/admin.py, so it was
    missed by both the table above and a by-hand sweep of the admin router.)

    Asserts only "not a success": FastAPI validates a request body *before*
    calling the handler, so a POST carrying a placeholder body can legitimately
    be refused as 422 rather than 403. The table-driven tests above pin the
    exact status per endpoint; this pins the invariant that no /admin/* route
    ever answers a student with 2xx.
    """
    checked = []
    for route in live_app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/admin/"):
            continue
        # Path params get an id that resolves to nothing; the gate must fire
        # regardless of whether the row exists.
        concrete = re.sub(r"\{[^}]+\}", "999999", path)
        for method in sorted(set(getattr(route, "methods", set())) - {"HEAD", "OPTIONS"}):
            r = live_client.request(method, concrete, json={}, headers={"x-demo-role": "student"})
            assert r.status_code >= 400, f"{method} {concrete} -> {r.status_code}: {r.text}"
            checked.append(f"{method} {concrete}")
    # Sanity: the walk actually reached the admin router rather than matching
    # nothing and passing vacuously.
    assert len(checked) >= 12, checked


# ── 3. Demo surfaces disabled on real deploys ─────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/seed.db",
        "/lab.html",
        "/playground.html",
        "/validation_report.json",
        "/prototypes",
        "/prototypes/",
        "/prototypes/index.html",
        "/prototypes/prototype.js",
        "/bluebook/bluebook.bundle.js.map",  # T-06
    ],
)
def test_demo_statics_404_in_pilot(real_deploy, live_client, path):
    assert live_client.get(path).status_code == 404


def test_prototype_prefix_gate_is_path_boundary_safe(api_mod):
    assert api_mod._is_demo_only_static_path("/prototypes/network-pulse-engine.js")
    assert not api_mod._is_demo_only_static_path("/prototypes-public")


def test_v1_demo_login_unmounted_in_pilot(real_deploy, live_client):
    r = live_client.post("/api/v1/auth/login", json={"email": "x@y.z", "password": "p"})
    assert r.status_code == 404


def test_v1_demo_login_works_in_demo(live_client):
    r = live_client.post("/api/v1/auth/login", json={"email": "prof@y.z", "password": "p"})
    assert r.status_code == 200
    assert r.json()["role"] == "professor"


def test_health_reports_environment(live_client):
    r = live_client.get("/health")
    assert r.status_code == 200
    assert r.json()["environment"] == "demo"


def test_wildcard_origins_rejected_in_pilot(real_deploy, api_mod, monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="wildcard"):
        api_mod._resolve_allowed_origins()


def test_wildcard_origins_fine_in_demo(api_mod, monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "")
    assert api_mod._resolve_allowed_origins() == ["*"]


# ── 4. Seeder refusal ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("env", ["pilot", "staging", "production"])
def test_seeder_refuses_real_env(monkeypatch, env):
    monkeypatch.setenv("ORIGINAL_ENV", env)
    with pytest.raises(SystemExit, match="Refusing to seed"):
        run.seed_demo_store()


# ── 5. FERPA deletion completeness ────────────────────────────────────────────


def test_delete_purges_display_name_and_audit_history(live_client):
    sid = "lockdel_bob"
    r = live_client.post(
        f"/students/{sid}/baseline",
        json={"text": LONG_TEXT, "assignment": "a1"},
    )
    assert r.status_code == 200, r.text
    store.set_display_name(sid, "Bob Example")
    store.log_audit(action="score", student_id=sid, actor="test")

    inv = live_client.get(f"/students/{sid}/data-inventory").json()
    assert inv["data_categories"]["display_name"]["on_file"] is True
    assert inv["data_categories"]["audit_log_entries"]["count"] >= 1

    r = live_client.delete(f"/students/{sid}")
    assert r.status_code == 200, r.text
    assert "display name" in r.json()["message"]

    with store._get_conn() as conn:
        names = conn.execute(
            "SELECT COUNT(*) FROM student_names WHERE student_id = ?", (sid,)
        ).fetchone()[0]
        audits = conn.execute(
            "SELECT action FROM audit_log WHERE student_id = ?", (sid,)
        ).fetchall()
    assert names == 0
    # Exactly one row survives: the deletion receipt written after the purge.
    assert [a[0] for a in audits] == ["student_delete"]


# ── 6. Backup module ──────────────────────────────────────────────────────────


def _make_db(path):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    conn.close()


def test_run_backup_writes_consistent_copy(tmp_path):
    db = tmp_path / "profiles.db"
    _make_db(db)
    dest = tmp_path / "backups"
    out = backup_mod.run_backup(db, dest, keep=48)
    assert out is not None and out.exists()
    assert out.name.startswith(backup_mod.BACKUP_PREFIX)
    conn = sqlite3.connect(str(out))
    assert conn.execute("SELECT x FROM t").fetchone()[0] == 42
    conn.close()


def test_run_backup_prunes_to_keep(tmp_path):
    db = tmp_path / "profiles.db"
    _make_db(db)
    dest = tmp_path / "backups"
    dest.mkdir()
    # Pre-seed 5 fake old backups with distinct mtimes.
    for i in range(5):
        p = dest / f"{backup_mod.BACKUP_PREFIX}202001010000{i:02d}.db"
        p.write_bytes(b"old")
        import os as _os

        _os.utime(p, (1000 + i, 1000 + i))
    backup_mod.run_backup(db, dest, keep=3)
    remaining = sorted(dest.glob(f"{backup_mod.BACKUP_PREFIX}*.db"))
    assert len(remaining) == 3


def test_run_backup_missing_db_is_noop(tmp_path):
    assert backup_mod.run_backup(tmp_path / "nope.db", tmp_path / "b", keep=3) is None
    assert not (tmp_path / "b").exists()


def test_latest_backup_age(tmp_path):
    assert backup_mod.latest_backup_age_seconds(None) is None
    dest = tmp_path / "backups"
    assert backup_mod.latest_backup_age_seconds(dest) is None
    dest.mkdir()
    (dest / f"{backup_mod.BACKUP_PREFIX}fresh.db").write_bytes(b"x")
    age = backup_mod.latest_backup_age_seconds(dest)
    assert age is not None and age < 60


def test_resolve_backup_dir(tmp_path, monkeypatch):
    db = tmp_path / "data" / "profiles.db"
    monkeypatch.setenv("BACKUP_DIR", "")
    assert backup_mod.resolve_backup_dir(db, is_real_deploy=False) is None
    assert backup_mod.resolve_backup_dir(db, is_real_deploy=True) == db.parent / "backups"
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "elsewhere"))
    assert backup_mod.resolve_backup_dir(db, is_real_deploy=False) == tmp_path / "elsewhere"


def test_admin_health_reports_backup_age(live_client):
    r = live_client.get("/admin/health")
    assert r.status_code == 200
    body = r.json()
    assert "backups_enabled" in body
    assert "last_backup_age_seconds" in body


# ── Backup module — remaining branch arms (p3-task-4 sweep) ─────────────────
# The tests above exercise the happy paths (consistent copy, pruning, missing
# db, resolve_backup_dir). These close the arms they don't: the outer
# except in run_backup, _prune's per-file OSError swallow, and the two
# distinct "no age" cases in latest_backup_age_seconds (dir absent vs. dir
# present but empty of matching backups) plus its multi-file loop.


def test_run_backup_handles_internal_failure_gracefully(tmp_path):
    """A file that exists but isn't a real SQLite database makes
    ``src.backup(dst)`` raise (DatabaseError) — the outer ``except Exception``
    must catch it and degrade to None, never propagate."""
    db = tmp_path / "profiles.db"
    db.write_bytes(b"not a real sqlite database at all")
    dest = tmp_path / "backups"
    result = backup_mod.run_backup(db, dest, keep=3)
    assert result is None


def test_prune_ignores_oserror_on_unlink(tmp_path, monkeypatch):
    """A file that vanishes (or is locked) between glob() and unlink() must
    not blow up pruning — the per-file OSError is swallowed and the count
    of files actually removed reflects that."""
    import os
    from pathlib import Path

    dest = tmp_path / "backups"
    dest.mkdir()
    for i in range(5):
        p = dest / f"{backup_mod.BACKUP_PREFIX}2020010100{i:04d}.db"
        p.write_bytes(b"old")
        os.utime(p, (1000 + i, 1000 + i))

    def _raise(self, *a, **kw):
        raise OSError("locked")

    monkeypatch.setattr(Path, "unlink", _raise)
    removed = backup_mod._prune(dest, keep=1)
    assert removed == 0
    assert len(list(dest.glob(f"{backup_mod.BACKUP_PREFIX}*.db"))) == 5


def test_latest_backup_age_second_file_older_does_not_reset_max(tmp_path, monkeypatch):
    """The loop's ``if newest is None or mtime > newest`` must be able to
    evaluate False on a later item (a later glob match that is actually
    OLDER than the running max) without disturbing the tracked newest —
    real-filesystem glob order isn't guaranteed, so this pins the order
    with a fake glob rather than relying on directory-entry ordering."""
    import time
    from pathlib import Path

    dest = tmp_path / "backups"
    dest.mkdir()

    class _FakeStat:
        def __init__(self, mtime):
            self.st_mtime = mtime

    class _FakeMatch:
        def __init__(self, mtime):
            self._mtime = mtime

        def stat(self):
            return _FakeStat(self._mtime)

    now = time.time()
    # First match is the newest; second is much older — the second
    # iteration's comparison must come back False (no new max).
    fakes = [_FakeMatch(now - 5), _FakeMatch(now - 10_000)]
    monkeypatch.setattr(Path, "glob", lambda self, pattern: iter(fakes))

    age = backup_mod.latest_backup_age_seconds(dest)
    assert age is not None
    assert age < 60  # anchored to the first (newer) fake, not the older one


def test_latest_backup_age_existing_dir_with_no_matching_files_is_none(tmp_path):
    """A backups directory that exists but holds no ``profiles-*.db`` files
    is a distinct arm from 'the directory doesn't exist at all' — both must
    return None, but only the latter short-circuits on is_dir()."""
    dest = tmp_path / "backups"
    dest.mkdir()
    (dest / "unrelated.txt").write_bytes(b"x")
    assert backup_mod.latest_backup_age_seconds(dest) is None
