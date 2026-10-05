"""New tenant rows default to Bluebook only (alembic a7d3c9e1b5f2).

Postgres inserts a placeholder tenants row for any write that names an
unregistered tenant (PostgresRepository._ensure_tenant_exists). With the old
default of both products such a workspace held Original without an operator
switching it on.
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from tests.test_migration import _postgres_available

pytestmark = pytest.mark.postgres

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _reset(engine) -> None:
    from original.db.models.live import LiveBase

    LiveBase.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))


@pytest.fixture
def migrated():
    if not _postgres_available():
        pytest.skip("no reachable Postgres — set DATABASE_URL to run the migration test")
    from original.db import postgres_session

    engine = postgres_session.get_engine()
    _reset(engine)
    cfg = Config(os.path.join(_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_ROOT, "alembic"))
    command.upgrade(cfg, "head")
    yield engine, cfg
    _reset(engine)


def _insert_default(conn, tenant_id: str):
    conn.execute(
        sa.text(
            "INSERT INTO tenants (tenant_id, name, environment, created_at) "
            "VALUES (:t, :t, 'pilot', now())"
        ),
        {"t": tenant_id},
    )
    return _products(conn, tenant_id)


def _products(conn, tenant_id: str):
    return conn.execute(
        sa.text("SELECT products_json FROM tenants WHERE tenant_id = :t"), {"t": tenant_id}
    ).scalar_one()


def test_new_rows_default_to_bluebook_only(migrated):
    engine, _cfg = migrated
    with engine.begin() as conn:
        assert _insert_default(conn, "after-upgrade") == ["bluebook"]


def test_downgrade_restores_the_old_default_and_keeps_existing_rows(migrated):
    engine, cfg = migrated
    with engine.begin() as conn:
        _insert_default(conn, "made-under-new-default")
    command.downgrade(cfg, "f4c9a2d71b30")
    with engine.begin() as conn:
        assert _insert_default(conn, "after-downgrade") == ["original", "bluebook"]
        assert _products(conn, "made-under-new-default") == ["bluebook"]
