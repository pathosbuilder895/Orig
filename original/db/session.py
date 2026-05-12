"""
db/session.py — SQLAlchemy engine and session factory.

Provides the database engine, SessionLocal factory, and FastAPI dependency.
Handles SQLite compatibility automatically.
"""

from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from original.core.config import get_settings
from original.core.logging import get_logger

from .base import Base

log = get_logger(__name__)


def get_engine():
    """Create and return the SQLAlchemy engine."""
    settings = get_settings()
    db_url = settings.DATABASE_URL

    # SQLite compatibility: disable pool settings
    if db_url.startswith("sqlite"):
        engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            echo=settings.DEBUG,
        )
    else:
        # PostgreSQL with connection pooling
        engine = create_engine(
            db_url,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_recycle=settings.DB_POOL_RECYCLE,
            echo=settings.DEBUG,
        )

    return engine


# Create the engine and session factory once
_engine = get_engine()
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=_engine,
)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a database session.
    Automatically closes the session after the request.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """
    Create all tables defined in the models.
    Safe to call multiple times (idempotent).
    Models must be imported so SQLAlchemy registers them with Base.metadata.
    """
    # Import all models to ensure they're registered with Base before create_all
    import original.db.models  # noqa: F401

    log.info("Initializing database tables...")
    Base.metadata.create_all(bind=_engine)
    log.info("Database tables initialized")


def drop_db() -> None:
    """Drop all tables (development/testing only)."""
    log.warning("Dropping all database tables...")
    Base.metadata.drop_all(bind=_engine)
    log.warning("All database tables dropped")
