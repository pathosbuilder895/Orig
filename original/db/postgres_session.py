"""
db/postgres_session.py — SQLAlchemy engine/session factory for the LIVE
pilot schema (WS-6 P3), targeting ``LiveBase`` (``original/db/models/live.py``)
— NOT the dormant v1 ``Base`` (see ``db/session.py``, which stays v1-only).

Mirrors the same ``DATABASE_URL`` + pooling settings ``alembic/env.py``
already uses for the live schema, so a single env var configures both
migrations and the repository.

The engine is built lazily on first use, not at import time. This module is
imported by ``original/postgres_repository.py`` (``PostgresRepository``) —
kept out of ``original/repository.py`` itself, which ``api.py`` always
imports regardless of active backend, specifically so a plain SQLite demo/
pilot process never pays for a Postgres engine/pool (or the sqlalchemy
import) it may never use.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from original.core.logging import get_logger

from .models.live import LiveBase

log = get_logger(__name__)

_engine = None
_SessionLocal: sessionmaker | None = None

# Default connection URL. Overridden by DATABASE_URL in every real environment;
# this fallback only lets the sqlite-variant test path resolve a URL locally.
_DEFAULT_DATABASE_URL = "postgresql://original:original@localhost:5432/original_db"


def get_engine():
    """Build (once, lazily) and return the SQLAlchemy engine for LiveBase.

    Reads DATABASE_URL + pool settings straight from the environment, NOT via
    ``original.core.config.Settings``. That Settings object is the dormant v1
    config: its ``ENVIRONMENT`` field is a strict ``Literal`` that rejects the
    live app's own values (``demo``/``pilot``), so routing the live Postgres
    engine through its validation crashes exactly at the P5 cutover, when
    ENVIRONMENT=pilot and Postgres is finally the backend. ``alembic/env.py``
    already reads DATABASE_URL directly for the same reason; this matches it.
    """
    global _engine
    if _engine is None:
        db_url = os.environ.get("DATABASE_URL") or _DEFAULT_DATABASE_URL
        echo = os.environ.get("DEBUG", "").lower() in ("1", "true")
        if db_url.startswith("sqlite"):
            # Supports pointing the live schema at a throwaway SQLite file in
            # tests without a real Postgres instance — production always uses
            # a postgresql:// URL.
            _engine = create_engine(db_url, connect_args={"check_same_thread": False}, echo=echo)
        else:
            _engine = create_engine(
                db_url,
                pool_size=int(os.environ.get("DB_POOL_SIZE", "10") or 10),
                max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "20") or 20),
                pool_recycle=int(os.environ.get("DB_POOL_RECYCLE", "3600") or 3600),
                echo=echo,
            )
        log.info("Live-schema engine created for %s", db_url.split("@")[-1])
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return _SessionLocal


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """One session per call, committed on success, rolled back on error.

    Mirrors ``store.py``'s ``_get_conn()`` connection-per-call idiom rather
    than FastAPI's session-per-request DI — ``PostgresRepository`` methods
    aren't route handlers and don't naturally receive per-request context,
    and this keeps SQLite/Postgres backends behaviorally symmetric (each
    repository call is its own transaction).
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all live-schema tables. Idempotent. Tests/local dev only —
    the pilot deploy provisions via alembic (see alembic/env.py)."""
    log.info("Initializing live-schema tables...")
    LiveBase.metadata.create_all(bind=get_engine())
    log.info("Live-schema tables initialized")


def drop_db() -> None:
    """Drop all live-schema tables. Tests/local dev only."""
    log.warning("Dropping all live-schema tables...")
    LiveBase.metadata.drop_all(bind=get_engine())
    log.warning("All live-schema tables dropped")


def reset_engine() -> None:
    """Drop the cached engine/session-factory singletons.

    Test isolation: each test process/fixture that points ``DATABASE_URL``
    at a fresh target needs a fresh engine, not the first one this process
    ever built.
    """
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
