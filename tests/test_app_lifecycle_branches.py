"""
Branch-coverage gap-fill for original/api.py + original/routers/_shared.py +
original/routers/health.py (Part 2 Task 5 of the branch-coverage plan,
.superpowers/sdd/p2-task-5-brief.md).

``lifespan`` never ran under the existing suite (0% function coverage,
0/12 branches) — every other live-stack test builds a ``TestClient`` without
entering it as a context manager, so FastAPI/Starlette never fires the ASGI
lifespan protocol. This file is the first to do ``with TestClient(app) as
client:`` against the loaded module, letting ``lifespan`` run for real with
its module-level globals (``_secret_key_pinned``, ``_IS_REAL_DEPLOY``,
``_repo``, …) monkeypatched per scenario — the same "flip the loaded app's
globals without reloading it" technique ``tests/test_pilot_lockdown.py``
already established for the rest of api.py's deploy-mode branches.

``_shared.py``'s four remaining arms and health.py's ``admin_health``
degraded-dependency arms are exercised by calling the plain functions
directly with hand-built fake ``Request``/``Repository`` objects — none of
them are ``async def`` route handlers with their own ASGI wiring, so a direct
call is simpler and faster than a full HTTP round trip, and sidesteps the
documented coverage.py "tracing lost after ``await request.form()`` behind
≥2 stacked BaseHTTPMiddleware" trap entirely (nothing here goes through the
app's middleware stack).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import original.ai_likelihood as ai_likelihood_mod
from original import api as api_mod
from original import principal as principal_mod
from original.routers import _shared as shared_mod
from original.routers import health as health_mod

# ─────────────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────────────


class _FakeLifespanRepo:
    """Stand-in for the ADR-002 Repository, controlling only ``db_path()``.

    ``lifespan`` calls ``_repo().db_path()`` to decide whether the in-app
    SQLite backup scheduler has anything to point at. A real
    ``PostgresRepository.db_path()`` raises ``NotImplementedError`` (WS-6 P5
    cutover); this fake reproduces exactly that shape without needing a real
    Postgres connection.
    """

    def __init__(self, db_path: Path | None = None, *, not_implemented: bool = False):
        self._db_path = db_path
        self._not_implemented = not_implemented

    def db_path(self):
        if self._not_implemented:
            raise NotImplementedError("Postgres backend has no SQLite file to back up")
        return self._db_path


def _fake_request(*, principal=None, headers=None, client=None):
    """A minimal duck-typed Request covering the attributes the four
    ``_shared.py`` helpers under test actually read: ``.state.principal``,
    ``.headers``, and (``_throttle_login`` only) ``.client``."""
    return SimpleNamespace(
        state=SimpleNamespace(principal=principal), headers=headers or {}, client=client
    )


def _staff_principal(role="professor"):
    return principal_mod.Principal(
        user_id="staff-1", role=role, tenant_id="acme", auth_method="session", is_demo=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# api.py: lifespan — 12/12 branches
#
# Arms (from coverage-baseline.json missing_branches for original/api.py):
#   [106,107] secret NOT pinned      [106,122] secret pinned (else)
#   [107,110] + real deploy -> raise [107,115] + not real deploy -> warn
#   [139,140] AI mode on             [139,156] AI mode off
#   [165,166] backup dir resolved    [165,172] backup dir None
#   [172,173] elif: sqlite backend   [172,174] elif: postgres backend (db_path None)
#   [175,176] cancel backup task     [175,-103] no backup task to cancel
# ─────────────────────────────────────────────────────────────────────────────


def test_lifespan_default_boot_closes_pinned_ai_off_no_backups(monkeypatch, tmp_path):
    """Pinned secret, demo mode, AI off, no BACKUP_DIR, SQLite backend.

    Closes [106,122] (secret pinned -> else), [139,156] (AI mode falsy),
    [165,172] (no BACKUP_DIR/not real deploy -> bdir None),
    [172,173] (elif db_path is not None -> "backups disabled" log),
    [175,-103] (no backup task was created -> nothing to cancel).
    """
    monkeypatch.setattr(api_mod, "_secret_key_pinned", True)
    monkeypatch.setattr(api_mod, "_IS_REAL_DEPLOY", False)
    monkeypatch.setattr(
        api_mod, "_repo", lambda: _FakeLifespanRepo(db_path=tmp_path / "profiles.db")
    )
    monkeypatch.delenv("AI_LIKELIHOOD_ENABLED", raising=False)
    monkeypatch.delenv("AI_LIKELIHOOD_SHADOW", raising=False)
    monkeypatch.delenv("BACKUP_DIR", raising=False)

    with TestClient(api_mod.app) as client:
        r = client.get("/health")
        assert r.status_code == 200


def test_lifespan_unpinned_warns_ai_on_backup_dir_set(monkeypatch, tmp_path):
    """Unpinned secret off a real deploy (warns, doesn't raise), AI mode on,
    BACKUP_DIR set -> the scheduler task is created and cancelled at shutdown.

    Closes [106,107] (secret NOT pinned), [107,115] (not real deploy -> warn),
    [139,140] (AI mode truthy), [165,166] (bdir resolved -> task created),
    [175,176] (backup task was created -> cancelled on shutdown).
    """
    monkeypatch.setattr(api_mod, "_secret_key_pinned", False)
    monkeypatch.setattr(api_mod, "_IS_REAL_DEPLOY", False)
    monkeypatch.setattr(
        api_mod, "_repo", lambda: _FakeLifespanRepo(db_path=tmp_path / "profiles.db")
    )
    monkeypatch.setattr(ai_likelihood_mod, "warm", lambda: True)
    monkeypatch.setenv("AI_LIKELIHOOD_ENABLED", "1")
    monkeypatch.delenv("AI_LIKELIHOOD_SHADOW", raising=False)
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("BACKUP_INTERVAL_MINUTES", "60")

    with TestClient(api_mod.app) as client:
        r = client.get("/health")
        assert r.status_code == 200
    # Context exit ran the shutdown half of lifespan (task.cancel()) without
    # raising — that's the [175,176] arm actually executing, not just reached.


def test_lifespan_raises_when_secret_unpinned_on_real_deploy(monkeypatch, tmp_path):
    """Fail-closed boot check (CLAUDE.md: SECRET_KEY must be stable off demo).

    Closes [107,110] — the only way to reach the raise.
    """
    monkeypatch.setattr(api_mod, "_secret_key_pinned", False)
    monkeypatch.setattr(api_mod, "_IS_REAL_DEPLOY", True)
    monkeypatch.setattr(
        api_mod, "_repo", lambda: _FakeLifespanRepo(db_path=tmp_path / "profiles.db")
    )

    with pytest.raises(RuntimeError, match="requires a stable SECRET_KEY"):
        with TestClient(api_mod.app):
            pass


def test_lifespan_postgres_backend_skips_backup_scheduler(monkeypatch):
    """Postgres backend: db_path() raises NotImplementedError, so ``_db_path``
    is None and the backup dir is never resolved at all.

    Closes [172,174] — the elif's False arm (db_path is None), reached only
    when the earlier ``if _bdir is not None`` is also False.
    """
    monkeypatch.setattr(api_mod, "_secret_key_pinned", True)
    monkeypatch.setattr(api_mod, "_IS_REAL_DEPLOY", False)
    monkeypatch.setattr(api_mod, "_repo", lambda: _FakeLifespanRepo(not_implemented=True))
    monkeypatch.delenv("AI_LIKELIHOOD_ENABLED", raising=False)
    monkeypatch.delenv("AI_LIKELIHOOD_SHADOW", raising=False)
    # BACKUP_DIR is irrelevant here: `_bdir = ... if _db_path else None` short
    # -circuits to None before resolve_backup_dir is ever called, regardless.
    monkeypatch.delenv("BACKUP_DIR", raising=False)

    with TestClient(api_mod.app) as client:
        r = client.get("/health")
        assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# api.py: _resolve_allowed_origins — 2 remaining arms
#   [216,224] ALLOWED_ORIGINS set, not a real-deploy-wildcard -> returned as-is
#   [225,226] ALLOWED_ORIGINS unset + real deploy -> fail-closed ([])
# ─────────────────────────────────────────────────────────────────────────────


def test_allowed_origins_explicit_list_returned_on_real_deploy(monkeypatch):
    """A properly-configured production CORS list (no wildcard) passes
    through unchanged — the complement of the existing wildcard-rejection
    test (test_pilot_lockdown.py::test_wildcard_origins_rejected_in_pilot),
    which only exercises the True arm of this same ``if``."""
    monkeypatch.setattr(api_mod, "_IS_REAL_DEPLOY", True)
    monkeypatch.setenv(
        "ALLOWED_ORIGINS", "https://original-pilot.onrender.com,https://admin.example.com"
    )
    assert api_mod._resolve_allowed_origins() == [
        "https://original-pilot.onrender.com",
        "https://admin.example.com",
    ]


def test_allowed_origins_production_unset_is_fail_closed(monkeypatch):
    """CLAUDE.md's ALLOWED_ORIGINS row: fails closed (no origin allowed) on a
    real deploy with the var unset, rather than falling back to '*'."""
    monkeypatch.setattr(api_mod, "_IS_REAL_DEPLOY", True)
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    assert api_mod._resolve_allowed_origins() == []


# ─────────────────────────────────────────────────────────────────────────────
# api.py: security_headers — HSTS arm ([257,258])
# ─────────────────────────────────────────────────────────────────────────────


def test_security_headers_adds_hsts_when_enabled(monkeypatch, live_client):
    monkeypatch.setattr(api_mod, "_ENABLE_HSTS", True)
    r = live_client.get("/health")
    assert r.status_code == 200
    assert r.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"


# ─────────────────────────────────────────────────────────────────────────────
# api.py: _resolve_app_version — remaining arm ([195,199])
# ─────────────────────────────────────────────────────────────────────────────


def test_resolve_app_version_falls_back_when_pyproject_has_no_version_line(monkeypatch):
    """Package metadata absent (dev checkout, no ``pip install -e .`` — true
    in this venv) AND the pyproject.toml text has no ``version = "..."``
    line to regex-match -> falls all the way through to the "0.1.0" literal.
    """

    class _FakePath:
        def resolve(self):
            return self

        @property
        def parent(self):
            return self

        def __truediv__(self, other):
            return self

        def read_text(self):
            return "# no version line in this file\n"

    monkeypatch.setattr(api_mod, "Path", lambda *a, **kw: _FakePath())
    assert api_mod._resolve_app_version() == "0.1.0"


def test_resolve_app_version_falls_back_when_pyproject_is_unreadable(monkeypatch):
    """api.py:[197,198] — `except OSError: pass`, distinct from the "no
    version line" test above (that one reads pyproject.toml successfully
    and finds no match; this one fails the read itself, e.g. a stripped
    deployment artifact missing the file)."""

    class _FakePath:
        def resolve(self):
            return self

        @property
        def parent(self):
            return self

        def __truediv__(self, other):
            return self

        def read_text(self):
            raise OSError("simulated missing pyproject.toml")

    monkeypatch.setattr(api_mod, "Path", lambda *a, **kw: _FakePath())
    assert api_mod._resolve_app_version() == "0.1.0"


# ─────────────────────────────────────────────────────────────────────────────
# routers/health.py: admin_health — 3/4 branches (degraded-dependency arms)
#   [68,70]  list_manifests() returned items -> latency list built
#   [73,74]  at least one real latency_ms -> average computed
#   [73,85]  items present but all latency_ms None -> average stays None
#   (bonus, line coverage only, not a counted branch arm):
#   manifest_stats()/list_manifests() raising -> degrade to {} / pass
# ─────────────────────────────────────────────────────────────────────────────


class _FakeHealthRepo:
    def __init__(
        self,
        *,
        manifest_stats_raises=False,
        list_manifests_raises=False,
        items=None,
        db_path=None,
    ):
        self._manifest_stats_raises = manifest_stats_raises
        self._list_manifests_raises = list_manifests_raises
        self._items = items if items is not None else []
        self._db_path = db_path

    def count(self):
        return 7

    def manifest_stats(self):
        if self._manifest_stats_raises:
            raise RuntimeError("manifest store unavailable")
        return {"total": 5, "by_action": {"escalate": 1, "schedule_conversation": 2}}

    def list_manifests(self, limit=20):
        if self._list_manifests_raises:
            raise RuntimeError("manifest listing unavailable")
        return {"items": self._items}

    def db_path(self):
        return self._db_path


def test_admin_health_degrades_when_manifest_stats_raises(monkeypatch, live_client, store_reset, tmp_path):
    monkeypatch.setattr(
        health_mod,
        "_repo",
        lambda: _FakeHealthRepo(manifest_stats_raises=True, db_path=tmp_path / "p.db"),
    )
    r = live_client.get("/admin/health")
    assert r.status_code == 200
    out = r.json()
    assert out["total_submissions"] == 0
    assert out["flagged_count"] == 0


def test_admin_health_degrades_when_list_manifests_raises(monkeypatch, live_client, store_reset, tmp_path):
    monkeypatch.setattr(
        health_mod,
        "_repo",
        lambda: _FakeHealthRepo(list_manifests_raises=True, db_path=tmp_path / "p.db"),
    )
    r = live_client.get("/admin/health")
    assert r.status_code == 200
    out = r.json()
    assert out["avg_latency_ms"] is None


def test_admin_health_averages_latency_when_present(monkeypatch, live_client, store_reset, tmp_path):
    items = [{"latency_ms": 120}, {"latency_ms": 80}, {"latency_ms": None}]
    monkeypatch.setattr(
        health_mod, "_repo", lambda: _FakeHealthRepo(items=items, db_path=tmp_path / "p.db")
    )
    r = live_client.get("/admin/health")
    assert r.status_code == 200
    out = r.json()
    assert out["avg_latency_ms"] == 100


def test_admin_health_latency_stays_none_when_all_items_lack_it(monkeypatch, live_client, store_reset, tmp_path):
    items = [{"latency_ms": None}, {"latency_ms": None}]
    monkeypatch.setattr(
        health_mod, "_repo", lambda: _FakeHealthRepo(items=items, db_path=tmp_path / "p.db")
    )
    r = live_client.get("/admin/health")
    assert r.status_code == 200
    out = r.json()
    assert out["avg_latency_ms"] is None


# ─────────────────────────────────────────────────────────────────────────────
# routers/_shared.py — four single arms. Each is a security control; every
# assertion below pins the DENY/downgrade side.
# ─────────────────────────────────────────────────────────────────────────────


def test_require_staff_rejects_role_outside_staff_set():
    """[96,97]: an authenticated, non-student, non-demo principal whose role
    still isn't one of _STAFF_ROLES is denied — e.g. a future/unknown role
    value that slipped past minting. Never falls through to `return p`."""
    principal = principal_mod.Principal(
        user_id="u1", role="teaching_assistant", tenant_id="acme", auth_method="session"
    )
    with pytest.raises(HTTPException) as exc_info:
        shared_mod._require_staff(_fake_request(principal=principal))
    assert exc_info.value.status_code == 403


def test_require_guard_503s_when_token_not_configured(monkeypatch):
    """[113,114]: GUARD_DESTRUCTIVE=1 but MAINTENANCE_TOKEN is empty — a
    misconfigured guard must fail closed (503), not silently accept every
    caller by falling through to an always-false comparison."""
    monkeypatch.setattr(api_mod, "_GUARD_DESTRUCTIVE", True)
    monkeypatch.setattr(api_mod, "_MAINTENANCE_TOKEN", "")
    with pytest.raises(HTTPException) as exc_info:
        shared_mod._require_guard(_fake_request())
    assert exc_info.value.status_code == 503


def test_throttle_login_clears_bucket_past_memory_bound(monkeypatch):
    """[245,246]: the per-IP attempt map is bounded to protect memory under
    address churn — once it exceeds 10,000 distinct IPs it is cleared rather
    than left to grow forever. Manipulates the module's own dict directly
    (monkeypatch-restored) instead of driving 10,000+ real requests."""
    prefilled = {f"198.51.100.{i % 256}-{i}": [] for i in range(10_000)}
    monkeypatch.setattr(shared_mod, "_login_attempts", prefilled)

    shared_mod._throttle_login(_fake_request(headers={}))

    # The 10,001st entry pushed it over the bound, so the whole map — this
    # request's own just-recorded entry included — was cleared.
    assert len(shared_mod._login_attempts) == 0


def test_authorize_provenance_denies_trust_when_no_principal_resolved():
    """[335,346]: a trusted provenance requested on a real (non-None) request
    that carries no resolved principal (e.g. bypassed the tenant-isolation
    middleware) is denied trust exactly like an unattested student — downgraded
    to 'unverified', never silently passed through."""
    request = _fake_request(headers={})
    assert request.state.principal is None
    result = shared_mod._authorize_provenance(request, "acme:student1", "proctored")
    assert result == ("unverified", True)
