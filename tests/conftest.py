"""
tests/conftest.py — Pytest fixtures for testing.

Provides database, authentication, and API client fixtures.
"""

from __future__ import annotations

# Set environment variables BEFORE any Original imports so that
# get_settings() / db/session.py module-level initialisation use
# test values rather than reading the on-disk .env file.
import os
os.environ.setdefault("ENVIRONMENT", "testing")
os.environ.setdefault("SECRET_KEY", "test-secret-key-" * 5)
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("FIRST_ADMIN_PASSWORD", "TestAdmin123!")

import hashlib
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from original.auth.jwt import create_access_token, create_refresh_token
from original.auth.password import hash_password
from original.core.config import Settings
from original.db.base import Base
from original.db.session import get_db
from original.main import app
from original.db.models import (
    Institution,
    User,
    UserRole,
    Course,
    Student,
    RefreshToken,
)


@pytest.fixture(scope="session")
def settings():
    """Override settings for testing."""
    return Settings(
        DATABASE_URL="sqlite:///:memory:",
        ENVIRONMENT="testing",
        DEBUG=True,
        LOG_JSON=False,
        SECRET_KEY="test-secret-key-" * 5,
    )


@pytest.fixture
def db(settings):
    """Create an in-memory SQLite database for testing."""
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
        # StaticPool ensures all connections share the same in-memory DB instance
        poolclass=StaticPool,
    )
    # Import all models so they register with Base.metadata before create_all
    import original.db.models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    session = SessionLocal()

    yield session

    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(db: Session):
    """FastAPI TestClient with overridden database dependency."""

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    yield TestClient(app)

    app.dependency_overrides.clear()


@pytest.fixture
def test_institution(db: Session) -> Institution:
    """Create a test institution."""
    institution = Institution(
        name="Test Seminary",
        subdomain="test",
    )
    db.add(institution)
    db.commit()
    db.refresh(institution)
    return institution


@pytest.fixture
def admin_user(db: Session, test_institution: Institution) -> User:
    """Create a test admin user."""
    user = User(
        email="admin@test.com",
        hashed_password=hash_password("Admin123!"),
        full_name="Test Admin",
        role=UserRole.ADMIN,
        institution_id=test_institution.id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def instructor_user(db: Session, test_institution: Institution) -> User:
    """Create a test instructor user."""
    user = User(
        email="instructor@test.com",
        hashed_password=hash_password("Instructor123!"),
        full_name="Test Instructor",
        role=UserRole.INSTRUCTOR,
        institution_id=test_institution.id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def test_course(db: Session, test_institution: Institution, instructor_user: User) -> Course:
    """Create a test course."""
    course = Course(
        name="Advanced Theology",
        code="THEO 501",
        institution_id=test_institution.id,
        instructor_id=instructor_user.id,
        semester="Spring 2026",
        is_active=True,
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


@pytest.fixture
def test_student(db: Session, test_institution: Institution) -> Student:
    """Create a test student."""
    student = Student(
        external_id="STU001",
        full_name="John Doe",
        email="john@test.com",
        institution_id=test_institution.id,
        is_active=True,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


@pytest.fixture
def admin_auth_headers(admin_user: User) -> dict:
    """Get authorization headers for admin user."""
    token = create_access_token(admin_user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def instructor_auth_headers(instructor_user: User) -> dict:
    """Get authorization headers for instructor user."""
    token = create_access_token(instructor_user)
    return {"Authorization": f"Bearer {token}"}
