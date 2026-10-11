"""Alembic migration hygiene for the live schema (T-10).

The pilot builds its Postgres schema with ``alembic upgrade head``
(render.yaml ``preDeployCommand``, pinned by tests/test_render_blueprint.py),
while every other Postgres test builds it with
``LiveBase.metadata.create_all``. Nothing checked that the two agree, so a
model change without a migration (or the reverse) would pass the whole suite
and only show up on the first deploy. These tests pin:

* the migration graph has exactly one head, so ``upgrade head`` is
  unambiguous;
* ``upgrade head`` on an empty database produces exactly ``LiveBase.metadata``
  (``compare_metadata`` finds nothing to autogenerate);
* ``downgrade base`` undoes every revision, and a second ``upgrade head``
  rebuilds the same tables and columns.

Each database test gets its own throwaway database, created and dropped here,
so its ``alembic_version`` table never meets the shared database that the
truncate/create_all fixtures in tests/conftest.py manage.
"""

from __future__ import annotations

import os
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import NullPool

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from original.db.models.live import LiveBase
from tests.test_tenant_products_default_migration import _restore_logging, _snapshot_logging

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _config() -> Config:
    # Same Config as tests/test_tenant_products_default_migration.py:
    # alembic/env.py takes the database from DATABASE_URL, not from here.
    cfg = Config(os.path.join(_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_ROOT, "alembic"))
    return cfg


def _heads() -> tuple[str, ...]:
    return tuple(ScriptDirectory.from_config(_config()).get_heads())


def test_migration_graph_has_a_single_head():
    """Two heads make ``alembic upgrade head`` fail on deploy ("Multiple
    head revisions are present"). Reading the scripts runs no env.py, so this
    needs no database."""
    heads = _heads()
    assert len(heads) == 1, f"alembic has {len(heads)} heads: {heads}; add a merge revision"


@pytest.fixture
def scratch_db(postgres_available, monkeypatch):
    """A new, empty database on the configured Postgres server, dropped at
    teardown. DATABASE_URL points at it for the test, which is how
    alembic/env.py picks its target."""
    if not postgres_available:
        pytest.skip(
            "uninformative: no reachable Postgres; set DATABASE_URL to a "
            "postgresql:// instance to run this test"
        )
    server = sa.engine.make_url(os.environ["DATABASE_URL"])
    name = f"alembic_t10_{uuid.uuid4().hex[:12]}"
    # CREATE/DROP DATABASE cannot run inside a transaction.
    admin = sa.create_engine(server, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = server.set(database=name)
    engine = sa.create_engine(url, poolclass=NullPool)
    monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
    # env.py's fileConfig rewires process-wide logging on every in-process
    # run; hand the process back as it was, as
    # tests/test_tenant_products_default_migration.py does.
    logging_before = _snapshot_logging()
    try:
        yield engine, _config()
    finally:
        _restore_logging(logging_before)
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _schema(engine) -> dict[str, dict[str, str]]:
    """Every table in the public schema, with each column's type."""
    inspector = sa.inspect(engine)
    return {
        table: {col["name"]: str(col["type"]) for col in inspector.get_columns(table)}
        for table in inspector.get_table_names()
    }


# Drift the test is allowed to find. Empty: when it landed (2026-10-11) the
# test found one real case (bluebook_submissions.submission_uuid was a UNIQUE
# constraint in the model but a partial unique index in migration
# 7c4d1e88a3b5), fixed in the model the same day. Add an entry only with a
# comment saying why the difference is deliberate.
KNOWN_DRIFT_T10: set = set()


def _describe(entry) -> tuple | str:
    """A comparable summary of one ``compare_metadata`` entry."""
    if isinstance(entry, tuple) and entry and isinstance(entry[0], str):
        kind, obj = entry[0], entry[1]
        if kind in ("add_index", "remove_index"):
            return (kind, obj.table.name, obj.name)
        if kind in ("add_constraint", "remove_constraint"):
            return (kind, obj.table.name, tuple(c.name for c in obj.columns))
    return repr(entry)


@pytest.mark.postgres
def test_upgrade_head_builds_exactly_the_live_metadata(scratch_db):
    """T-10: what ``alembic upgrade head`` builds is what ``LiveBase.metadata``
    declares, apart from any deliberate difference recorded in
    KNOWN_DRIFT_T10 (none today)."""
    engine, cfg = scratch_db
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        assert context.get_current_heads() == _heads()
        diff = compare_metadata(context, LiveBase.metadata)
    found = [_describe(entry) for entry in diff]
    assert sorted(found, key=repr) == sorted(KNOWN_DRIFT_T10, key=repr), (
        "alembic upgrade head and LiveBase.metadata disagree beyond KNOWN_DRIFT_T10; "
        f"write a migration for the model change (or fix the model): {diff}"
    )


@pytest.mark.postgres
def test_downgrade_base_then_upgrade_head_round_trips(scratch_db):
    engine, cfg = scratch_db
    command.upgrade(cfg, "head")
    first = _schema(engine)
    # Not vacuous: the first upgrade built every live table.
    assert set(first) - {"alembic_version"} == set(LiveBase.metadata.tables)

    command.downgrade(cfg, "base")
    assert set(_schema(engine)) == {"alembic_version"}, "downgrade base left tables behind"

    command.upgrade(cfg, "head")
    assert _schema(engine) == first
