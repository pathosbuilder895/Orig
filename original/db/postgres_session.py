"""
db/postgres_session.py — SQLAlchemy engine/session factory for the LIVE
pilot schema (WS-6 P3), targeting ``LiveBase`` (``original/db/models/live.py``)
— NOT the dormant v1 ``Base`` (see ``db/session.py``, which stays v1-only).

Mirrors the same ``DATABASE_URL`` + pooling settings ``alembic/env.py``
already uses for the live schema, so a single env var configures both
migrations and the repository.

The engine is built lazily on first use, not at import time. This module is
imported transitively by ``original/repository.py`` (``PostgresRepository``),
which ``api.py`` always imports even when the active backend is SQLite-only
— eager construction here would mean every process pays for a Postgres
engine/pool it may never use.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from original.core.config import get_settings
from original.core.logging import get_logger

from .models.live import LiveBase

log = get_logger(__name__)

_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    """Build (once, lazily) and return the SQLAlchemy engine for LiveBase."""
    global _engine
    if _engine is None:
        settings = get_settings()
        db_url = settings.DATABASE_URL
        if db_url.startswith("sqlite"):
            # Supports pointing the live schema at a throwaway SQLite file in
            # tests without a real Postgres instance — production always uses
            # a postgresql:// URL.
            _engine = create_engine(
                db_url, connect_args={"check_same_thread": False}, echo=settings.DEBUG
            )
        else:
            _engine = create_engine(
                db_url,
                pool_size=settings.DB_POOL_SIZE,
                max_overflow=settings.DB_MAX_OVERFLOW,
                pool_recycle=settings.DB_POOL_RECYCLE,
                echo=settings.DEBUG,
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
