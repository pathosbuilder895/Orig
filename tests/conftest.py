"""
tests/conftest.py — Pytest fixtures for the live stack (original/api.py + demo/).

The v1 fixture family (SQLAlchemy db/client/institution/user/course/student +
JWT auth headers) was deleted with the dormant v1 API surface in WS-6 P6.
"""

from __future__ import annotations

# Set environment variables BEFORE any Original imports.
import os

# Pins the DORMANT v1 pydantic Settings (original/core/config.py, reached only
# via original/cli/{delete_student,security_audit}.py) to its "testing" tier.
# The LIVE stack does not read ENVIRONMENT at all — since WS-7.4 its only
# deploy-mode variable is ORIGINAL_ENV. Verified: the full suite is green with
# this line deleted (Settings just falls back to its "development" default), so
# it is belt-and-braces for the dormant config, not a live-stack requirement.
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


# ── Postgres reachability (T-51) ──────────────────────────────────────────────
# Formerly five near-identical `_postgres_available()` / `_postgres_session_
# available()` copies (test_repository_contract.py, test_migration.py,
# test_shadow_repository.py, test_cutover.py, test_persistence_error_arms.py).
# Consolidated into one fixture so a Postgres-marked test anywhere in the
# suite gets the same reachability check, including the schema bootstrap that
# only test_persistence_error_arms.py's variant used to do.
@pytest.fixture(scope="session")
def postgres_available() -> bool:
    """True iff DATABASE_URL points at Postgres and it's actually reachable.

    Deliberately checked at fixture-setup time (not import time) so
    monkeypatching DATABASE_URL mid-session (or CI wiring up the service
    container after collection) both work — this module sets a sqlite
    default above at import time specifically so any stray, unguarded engine
    build lands on a throwaway in-memory SQLite rather than a real Postgres;
    only a real, explicit postgresql:// DATABASE_URL at the moment a test
    first asks should ever make this true.

    Session-scoped: the check itself (reset_engine() + a real connect) is
    identical no matter which test asks first, so paying its cost more than
    once per session buys nothing.

    Reachability-only — this fixture does NOT touch the live schema. Sibling
    files (test_migration.py's ``fresh_pg``, two tests in test_cutover.py)
    drop the live schema in their own teardown once their tests finish, so a
    session-scoped one-time ``create_all`` here would go stale the moment
    one of those runs first. Any Postgres-gated test/fixture that needs the
    schema to exist must request the function-scoped ``postgres_schema``
    fixture below instead, which re-asserts it on every single request.
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url.startswith("postgresql"):
        return False
    from original.db import postgres_session

    try:
        postgres_session.reset_engine()
        engine = postgres_session.get_engine()
        with engine.connect():
            pass
        return True
    except Exception:
        return False


@pytest.fixture
def postgres_schema(postgres_available: bool):
    """Ensures the live Postgres schema exists for one test, and returns the
    engine it was ensured on.

    Function-scoped (unlike ``postgres_available`` above): unconditionally
    re-runs ``LiveBase.metadata.create_all`` on every request
    (``checkfirst=True`` by default, so it's a cheap no-op when the schema
    is already present) rather than once per session, because sibling files
    (test_migration.py's ``fresh_pg``, two tests in test_cutover.py) drop
    the live schema in their own teardown — a test that only needs
    reachability-plus-schema-exists, and doesn't otherwise manage its own
    schema, should request this fixture rather than
    ``postgres_available`` alone.

    Skips with the same "uninformative" reason as every other
    Postgres-gated fixture/test in this suite when no Postgres is reachable.
    """
    if not postgres_available:
        pytest.skip(
            "uninformative — no reachable Postgres; set DATABASE_URL to a "
            "postgresql:// instance to run this test"
        )
    from original.db import postgres_session
    from original.db.models.live import LiveBase

    engine = postgres_session.get_engine()
    LiveBase.metadata.create_all(bind=engine)
    return engine


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


@pytest.fixture
def pilot_env(live_app, monkeypatch):
    """Put the loaded live app into real-deploy (pilot) mode.

    Mirrors tests/test_pilot_lockdown.py's `real_deploy` fixture exactly —
    same module (original.api), same attribute (_IS_REAL_DEPLOY) — via
    monkeypatch, so it self-reverts on teardown. Yields nothing.
    """
    import original.api

    monkeypatch.setattr(original.api, "_IS_REAL_DEPLOY", True)
    yield


@pytest.fixture
def principal_headers():
    """Factory fixture: make(sub, role, tenant_id) -> Authorization header dict.

    Mints a signed principal token the same way tests/test_tenant_isolation.py's
    `_auth` helper does, via original.principal.mint_principal_token.
    """
    from original import principal as pr

    def make(sub: str, role: str, tenant_id: str) -> dict:
        token = pr.mint_principal_token(sub, role, tenant_id)
        return {"Authorization": f"Bearer {token}"}

    return make
