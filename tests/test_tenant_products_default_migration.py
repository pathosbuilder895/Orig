"""New tenant rows default to Bluebook only (alembic a7d3c9e1b5f2).

Postgres inserts a placeholder tenants row for any write that names an
unregistered tenant (PostgresRepository._ensure_tenant_exists). With the old
default of both products such a workspace held Original without an operator
switching it on.
"""

from __future__ import annotations

import logging
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


def _snapshot_logging():
    """The process's logging set-up, as alembic/env.py's fileConfig finds it.

    Even with ``disable_existing_loggers=False``, fileConfig replaces the root
    logger's handlers (pytest's capture handlers included), sets root to WARN,
    switches every existing logger's ``disabled`` flag off, and resets level,
    handlers and propagation on loggers under the ones alembic.ini names."""
    root = logging.getLogger()
    loggers = {
        name: (lg.level, list(lg.handlers), lg.propagate, lg.disabled)
        for name, lg in list(logging.Logger.manager.loggerDict.items())
        if isinstance(lg, logging.Logger)
    }
    return list(root.handlers), root.level, loggers


def _restore_logging(snapshot) -> None:
    handlers, level, loggers = snapshot
    root = logging.getLogger()
    root.handlers[:] = handlers
    root.setLevel(level)
    for name, (lg_level, lg_handlers, propagate, disabled) in loggers.items():
        lg = logging.Logger.manager.loggerDict.get(name)
        if not isinstance(lg, logging.Logger):
            continue
        lg.setLevel(lg_level)
        lg.handlers[:] = lg_handlers
        lg.propagate = propagate
        lg.disabled = disabled


def _migrated():
    if not _postgres_available():
        pytest.skip("no reachable Postgres — set DATABASE_URL to run the migration test")
    from original.db import postgres_session

    engine = postgres_session.get_engine()
    # Taken before any in-process Alembic run (the upgrade here, and a test's
    # own downgrade) and put back in teardown, so later tests in the same
    # process, caplog-based ones above all, see logging as it was.
    logging_before = _snapshot_logging()
    try:
        _reset(engine)
        cfg = Config(os.path.join(_ROOT, "alembic.ini"))
        cfg.set_main_option("script_location", os.path.join(_ROOT, "alembic"))
        command.upgrade(cfg, "head")
        yield engine, cfg
        _reset(engine)
    finally:
        _restore_logging(logging_before)
    # Loggers Alembic created itself are new, not changed; compare the rest.
    handlers, level, loggers = _snapshot_logging()
    assert (handlers, level) == logging_before[:2]
    assert {name: loggers[name] for name in logging_before[2]} == logging_before[2]


@pytest.fixture
def migrated():
    yield from _migrated()


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


def test_alembic_runs_leave_process_logging_as_they_found_it():
    """alembic/env.py's fileConfig replaces the root logger's handlers, sets
    root to WARN and re-enables loggers, even with disable_existing_loggers
    False. The fixture must hand the process back as it found it, or every
    later caplog-based test in the run inherits Alembic's logging."""
    root = logging.getLogger()
    probe = logging.getLogger("tests.migration_logging_probe")
    probe.disabled = True  # fileConfig would switch this back on
    before = (list(root.handlers), root.level)
    try:
        steps = _migrated()
        next(steps)  # set-up: Alembic has run in-process
        # Not vacuous: Alembic really did change the process's logging.
        assert list(root.handlers) != before[0] or probe.disabled is False
        with pytest.raises(StopIteration):
            next(steps)  # teardown
        assert (list(root.handlers), root.level) == before
        assert probe.disabled is True
    finally:
        probe.disabled = False
