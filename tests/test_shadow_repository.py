"""
tests/test_shadow_repository.py — WS-6 P4 REPO_SHADOW=postgres mirror.

Exercises the ShadowRepository through the real get_repository() wiring:
writes mirror to the shadow Postgres backend, reads come from the primary
SQLite backend, and a shadow-side failure is logged as a divergence without
disturbing the authoritative primary write.

Postgres-gated like the other P4/P3 suites: self-skips without a reachable
DATABASE_URL. Marked @pytest.mark.postgres.
"""

from __future__ import annotations

import logging
import os

import pytest

pytestmark = pytest.mark.postgres


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


@pytest.fixture
def shadow_repo(tmp_path, monkeypatch):
    """A get_repository() resolved in REPO_SHADOW=postgres mode: primary
    SQLite (isolated temp file) + shadow Postgres (fresh live schema)."""
    if not _postgres_available():
        pytest.skip("no reachable Postgres — set DATABASE_URL to run the shadow tests")

    from original import repository, store
    from original.db import postgres_session
    from original.db.models.live import LiveBase

    # Isolate the primary SQLite backend.
    db_file = tmp_path / "shadow_primary.db"
    monkeypatch.setenv("ORIGINAL_DB", str(db_file))
    monkeypatch.setattr(store, "_DB_PATH", db_file)
    store._GENRE_STATS_CACHE.clear()
    store._GENRE_STATS_CACHE.clear()

    # Fresh shadow Postgres schema.
    engine = postgres_session.get_engine()
    LiveBase.metadata.drop_all(bind=engine)
    LiveBase.metadata.create_all(bind=engine)

    monkeypatch.setenv("REPO_SHADOW", "postgres")
    repository.reset_repository()
    repo = repository.get_repository("pilot")
    yield repo
    repository.reset_repository()
    store._GENRE_STATS_CACHE.clear()
    LiveBase.metadata.drop_all(bind=engine)


class TestShadowMirror:
    def test_resolves_to_shadow_repository(self, shadow_repo):
        from original.repository import ShadowRepository

        assert isinstance(shadow_repo, ShadowRepository)

    def test_write_mirrors_to_postgres(self, shadow_repo):
        from original.postgres_repository import PostgresRepository

        shadow_repo.put_tenant("sem", "Seminary", environment="pilot", meta={"x": 1})

        # Primary (SQLite) has it — that's the read path.
        assert shadow_repo.get_tenant("sem")["name"] == "Seminary"
        # Shadow (Postgres) independently has it too.
        pg = PostgresRepository()
        assert pg.get_tenant("sem")["name"] == "Seminary"
        assert pg.get_tenant("sem")["environment"] == "pilot"

    def test_reads_come_from_primary_not_shadow(self, shadow_repo):
        from original.postgres_repository import PostgresRepository

        # Write straight to the shadow only (bypassing the mirror), so the two
        # backends disagree. The ShadowRepository must read the PRIMARY's value.
        PostgresRepository().put_tenant("ghost", "Shadow Only", environment="demo")
        assert shadow_repo.get_tenant("ghost") is None  # primary never got it

    def test_shadow_failure_is_logged_not_raised(self, shadow_repo, monkeypatch, caplog):
        # Force the shadow write to raise; the primary write must still succeed
        # and the caller must see no exception — only a logged divergence.
        def _boom(*args, **kwargs):
            raise RuntimeError("simulated shadow-backend outage")

        monkeypatch.setattr(shadow_repo._shadow, "put_tenant", _boom)
        with caplog.at_level(logging.WARNING):
            shadow_repo.put_tenant("resilient", "Still Works", environment="pilot")

        assert shadow_repo.get_tenant("resilient")["name"] == "Still Works"  # primary unaffected
        assert any("REPO_SHADOW divergence" in r.message for r in caplog.records)

    def test_reads_are_not_mirrored(self, shadow_repo, monkeypatch):
        # A read must never touch the shadow — assert the shadow's method is
        # never invoked for a read call.
        called = {"n": 0}

        original_get = shadow_repo._shadow.get_tenant

        def _counting_get(*args, **kwargs):
            called["n"] += 1
            return original_get(*args, **kwargs)

        monkeypatch.setattr(shadow_repo._shadow, "get_tenant", _counting_get)
        shadow_repo.get_tenant("anything")
        assert called["n"] == 0, "read call must not reach the shadow backend"

    def test_get_or_create_is_mirrored(self, shadow_repo):
        from original.postgres_repository import PostgresRepository

        # get_or_create mutates (inserts an empty state), so it's mirrored.
        shadow_repo.get_or_create("sem:newbie")
        assert PostgresRepository().get("sem:newbie") is not None


class TestWriteMethodSet:
    def test_write_methods_are_all_real_repository_methods(self):
        from original.repository import _WRITE_METHODS, SqliteRepository

        for name in _WRITE_METHODS:
            assert hasattr(SqliteRepository, name), f"{name} is not a Repository method"

    def test_obvious_reads_are_not_in_write_set(self):
        from original.repository import _WRITE_METHODS

        for read in ("get", "list_ids", "count", "get_tenant", "list_tenants", "get_manifest"):
            assert read not in _WRITE_METHODS
