"""
tests/test_cutover.py — WS-6 P5 cutover mechanism.

The cutover is shippable-inert: default behavior is unchanged (SQLite), and the
flip is a deliberate env-var change (REPO_BACKEND=postgres) an operator makes in
the maintenance window. These tests cover the mechanism:

  - backend selection + backend_name() (env logic)
  - /health.backend field
  - MAINTENANCE_MODE write-freeze middleware
  - pilot_smoke_test.run_smoke() logic
  - PG-gated regressions: the app actually serves reads from Postgres with
    ENVIRONMENT=pilot (the decoupling fix), and /admin/health survives the
    Postgres backend's db_path() NotImplementedError.
"""

from __future__ import annotations

import os

import pytest


# ── Backend selection (no Postgres connection needed to construct) ────────────
class TestBackendSelection:
    def test_backend_name_defaults_to_sqlite(self, monkeypatch):
        from original.repository import backend_name

        monkeypatch.delenv("REPO_BACKEND", raising=False)
        monkeypatch.delenv("REPO_SHADOW", raising=False)
        assert backend_name() == "sqlite"

    def test_backend_name_shadow(self, monkeypatch):
        from original.repository import backend_name

        monkeypatch.delenv("REPO_BACKEND", raising=False)
        monkeypatch.setenv("REPO_SHADOW", "postgres")
        assert backend_name() == "sqlite+shadow"

    def test_backend_name_postgres_wins_over_shadow(self, monkeypatch):
        from original.repository import backend_name

        monkeypatch.setenv("REPO_BACKEND", "postgres")
        monkeypatch.setenv("REPO_SHADOW", "postgres")
        assert backend_name() == "postgres"

    def test_get_repository_default_is_sqlite(self, monkeypatch):
        import original.repository as repo

        monkeypatch.delenv("REPO_BACKEND", raising=False)
        monkeypatch.delenv("REPO_SHADOW", raising=False)
        repo.reset_repository()
        assert isinstance(repo.get_repository("demo"), repo.SqliteRepository)
        repo.reset_repository()

    def test_get_repository_postgres_backend(self, monkeypatch):
        import original.repository as repo
        from original.postgres_repository import PostgresRepository

        monkeypatch.setenv("REPO_BACKEND", "postgres")
        repo.reset_repository()
        # Constructing PostgresRepository needs no live connection.
        assert isinstance(repo.get_repository("pilot"), PostgresRepository)
        repo.reset_repository()

    def test_get_repository_shadow_backend(self, monkeypatch):
        import original.repository as repo

        monkeypatch.delenv("REPO_BACKEND", raising=False)
        monkeypatch.setenv("REPO_SHADOW", "postgres")
        repo.reset_repository()
        assert isinstance(repo.get_repository("pilot"), repo.ShadowRepository)
        repo.reset_repository()


# ── /health backend field ────────────────────────────────────────────────────
class TestHealthBackendField:
    def test_health_reports_sqlite_by_default(self, live_client, store_reset, monkeypatch):
        import original.repository as repo

        monkeypatch.delenv("REPO_BACKEND", raising=False)
        monkeypatch.delenv("REPO_SHADOW", raising=False)
        repo.reset_repository()
        body = live_client.get("/health").json()
        assert body["status"] == "ok"
        assert body["backend"] == "sqlite"
        repo.reset_repository()


# ── Maintenance write-freeze middleware ───────────────────────────────────────
class TestMaintenanceMode:
    def test_writes_blocked_reads_open_when_on(self, live_client, store_reset, monkeypatch):
        monkeypatch.setenv("MAINTENANCE_MODE", "1")
        # Read stays open.
        assert live_client.get("/health").status_code == 200
        # Any write is frozen with 503 + Retry-After.
        resp = live_client.post("/students/demo:x/baseline", json={"text": "hello"})
        assert resp.status_code == 503
        assert resp.headers.get("Retry-After") == "120"
        assert "Maintenance in progress" in resp.json()["detail"]

    def test_writes_not_blocked_when_off(self, live_client, store_reset, monkeypatch):
        monkeypatch.delenv("MAINTENANCE_MODE", raising=False)
        resp = live_client.post("/tenants", json={})
        # Whatever the endpoint does (422 for the empty body here), it must NOT
        # be the maintenance 503.
        assert resp.status_code != 503
        assert "Maintenance in progress" not in resp.text


# ── pilot_smoke_test.run_smoke() logic ────────────────────────────────────────
class TestSmokeTestLogic:
    def _fetch(self, health: dict, student_status: int = 200):
        def fetch(path):
            if path == "/health":
                return 200, health
            return student_status, {}

        return fetch

    def test_pass_on_healthy_postgres(self):
        from scripts.pilot_smoke_test import run_smoke

        fetch = self._fetch({"status": "ok", "backend": "postgres", "students_in_store": 42})
        report = run_smoke(fetch, expect_count=42)
        assert report["ok"] is True
        assert all(c["ok"] for c in report["checks"])

    def test_fail_when_backend_still_sqlite(self):
        from scripts.pilot_smoke_test import run_smoke

        fetch = self._fetch({"status": "ok", "backend": "sqlite", "students_in_store": 42})
        report = run_smoke(fetch)
        assert report["ok"] is False
        assert any(c["check"] == "backend_is_postgres" and not c["ok"] for c in report["checks"])

    def test_fail_on_count_mismatch(self):
        from scripts.pilot_smoke_test import run_smoke

        fetch = self._fetch({"status": "ok", "backend": "postgres", "students_in_store": 40})
        report = run_smoke(fetch, expect_count=42)
        assert report["ok"] is False
        assert any(c["check"] == "student_count_matches" and not c["ok"] for c in report["checks"])

    def test_known_student_check_included_with_student_arg(self):
        from scripts.pilot_smoke_test import run_smoke

        fetch = self._fetch(
            {"status": "ok", "backend": "postgres", "students_in_store": 1}, student_status=200
        )
        report = run_smoke(fetch, student="sem:alice")
        assert any(c["check"] == "known_student_served" and c["ok"] for c in report["checks"])


# ── PG-gated cutover regressions ──────────────────────────────────────────────
def _postgres_available() -> bool:
    if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
        return False
    from original.db import postgres_session

    try:
        postgres_session.reset_engine()
        with postgres_session.get_engine().connect():
            return True
    except Exception:
        return False


@pytest.mark.postgres
class TestCutoverServesPostgres:
    def test_reads_come_from_postgres_with_environment_pilot(self, monkeypatch):
        """The core cutover proof + the ENVIRONMENT=pilot decoupling regression:
        get_repository(REPO_BACKEND=postgres) must serve real data even when
        ENVIRONMENT=pilot (which the dormant v1 Settings' Literal rejects -- the
        reason postgres_session reads DATABASE_URL from os.environ directly)."""
        if not _postgres_available():
            pytest.skip("no reachable Postgres — set DATABASE_URL to run the cutover regression")

        import original.repository as repo
        from original.db import postgres_session
        from original.db.models.live import LiveBase
        from original.postgres_repository import PostgresRepository

        engine = postgres_session.get_engine()
        LiveBase.metadata.drop_all(bind=engine)
        LiveBase.metadata.create_all(bind=engine)

        # ENVIRONMENT=pilot is exactly what broke the v1-Settings-coupled path.
        monkeypatch.setenv("ENVIRONMENT", "pilot")
        monkeypatch.setenv("REPO_BACKEND", "postgres")

        seed = PostgresRepository()
        seed.put_tenant("sem", "Seminary", environment="pilot")

        repo.reset_repository()
        active = repo.get_repository("pilot")
        assert isinstance(active, PostgresRepository)
        assert active.get_tenant("sem")["name"] == "Seminary"  # reads served from PG

        repo.reset_repository()
        LiveBase.metadata.drop_all(bind=engine)

    def test_admin_health_survives_postgres_db_path(self, live_client, monkeypatch):
        """Regression for the cutover-breaker: /admin/health calls
        _repo().db_path(), which PostgresRepository raises on. It must return
        200 (backup recency simply absent), not 500."""
        if not _postgres_available():
            pytest.skip("no reachable Postgres — set DATABASE_URL to run the cutover regression")

        import original.repository as repo
        from original.db import postgres_session
        from original.db.models.live import LiveBase

        engine = postgres_session.get_engine()
        LiveBase.metadata.drop_all(bind=engine)
        LiveBase.metadata.create_all(bind=engine)

        monkeypatch.setenv("REPO_BACKEND", "postgres")
        repo.reset_repository()
        resp = live_client.get("/admin/health")
        assert resp.status_code == 200
        assert resp.json()["last_backup_age_seconds"] is None  # no in-app SQLite backups on PG
        repo.reset_repository()
        LiveBase.metadata.drop_all(bind=engine)
