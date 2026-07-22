"""
tests/conftest.py — Pytest fixtures for the live stack (original/api.py + demo/).

The v1 fixture family (SQLAlchemy db/client/institution/user/course/student +
JWT auth headers) was deleted with the dormant v1 API surface in WS-6 P6.
"""

from __future__ import annotations

# Set environment variables BEFORE any Original imports.
import os

os.environ.setdefault("ENVIRONMENT", "testing")
os.environ.setdefault("SECRET_KEY", "test-secret-key-" * 5)
# Safety default for the LIVE-schema engine (original/db/postgres_session.py
# reads DATABASE_URL from the environment): any stray, unguarded engine build
# in a test lands on a throwaway in-memory SQLite, never a real Postgres. The
# postgres-marked suites require an explicit postgresql:// URL and self-skip
# otherwise; CI's service container overrides this.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


import pytest
from fastapi.testclient import TestClient

# ── Live stack (original/api.py + demo/) shared fixtures ─────────────────────
# The live pilot backend is loaded once per session (run.load_legacy_demo_app()
# caches the module in sys.modules, exactly as run.py does at startup), then
# wrapped in a fresh TestClient per test. store_reset points original.store at
# a throwaway per-test SQLite file and clears the in-memory cache so tests
# don't bleed state — see WS-5 (docs/implementation/WS-5-test-depth.md §5.1).


@pytest.fixture(scope="session")
def live_app():
    import run  # repo-root launcher

    return run.load_legacy_demo_app()


@pytest.fixture
def live_client(live_app):
    return TestClient(live_app)


@pytest.fixture
def store_reset(tmp_path, monkeypatch):
    """Isolate original.store's SQLite file + in-memory cache for one test."""
    from original import store

    db_file = tmp_path / "test_profiles.db"
    monkeypatch.setenv("ORIGINAL_DB", str(db_file))
    monkeypatch.setattr(store, "_DB_PATH", db_file)
    store._GENRE_STATS_CACHE.clear()
    store._GENRE_STATS_CACHE.clear()

    yield store

    store._GENRE_STATS_CACHE.clear()
    store._GENRE_STATS_CACHE.clear()
