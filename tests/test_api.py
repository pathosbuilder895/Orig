"""
tests/test_api.py — Integration tests for API endpoints.

Tests full request/response flows including auth, baseline, and scoring.
"""

import pytest
from fastapi.testclient import TestClient

from original.db.models import BaselineSample, Provenance, Submission


SAMPLE_TEXT = """
The theological implications of divine omniscience remain contested among scholars.
Some argue that foreknowledge does not entail determinism, while others contend that
true omniscience requires knowledge of all future events, which would seem to imply
a predetermined course of history. Medieval theologians like Thomas Aquinas proposed
sophisticated accounts of divine knowledge that transcend temporal limitations. Modern
philosophy has grappled with these issues through various metaphysical frameworks.
The problem of evil compounds these difficulties. If God is truly omniscient and
omnipotent, the existence of suffering becomes philosophically problematic. Various
theodicies have been advanced to reconcile divine attributes with the empirical reality
of suffering. Yet none have achieved universal philosophical acceptance.
""".strip()

DIFFERENT_TEXT = """
The study of rhetoric in classical antiquity provides insights into persuasion techniques.
Aristotle distinguished between logical, emotional, and ethical appeals. Roman orators
like Cicero and Quintilian developed sophisticated theories of eloquence. Medieval scholars
preserved classical rhetorical texts, ensuring their transmission to the modern world.
Renaissance humanists recovered and celebrated classical rhetorical traditions. Modern
communication studies builds on these ancient foundations. Persuasion remains central to
politics, law, and commerce. Digital media has transformed how rhetorical principles apply.
Social media algorithms shape discourse in novel ways. Authentic communication requires
awareness of both classical techniques and contemporary dynamics.
""".strip()


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_health_check(self, client: TestClient):
        """Health check endpoint returns 200."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_readiness_check(self, client: TestClient):
        """Readiness check endpoint returns 200."""
        response = client.get("/readiness")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"

    def test_root_redirects_to_api_docs(self, client: TestClient):
        """GET / redirects to interactive OpenAPI docs (Docker has no static index)."""
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"].rstrip("/").endswith("/api/docs")

    def test_api_docs_trailing_slash_gets_docs_csp(self, client: TestClient):
        """Trailing /api/docs/ must not get default-src 'none' (breaks Swagger assets)."""
        response = client.get("/api/docs/", follow_redirects=False)
        assert response.status_code == 307
        csp = response.headers.get("content-security-policy", "")
        assert "cdn.jsdelivr.net" in csp

    def test_scalar_reference_page(self, client: TestClient):
        """Scalar API reference HTML is served with relaxed docs CSP."""
        response = client.get("/api/reference")
        assert response.status_code == 200
        assert "Scalar.createApiReference" in response.text
        assert "cdn.jsdelivr.net" in response.headers.get("content-security-policy", "")

    def test_api_docs_hub(self, client: TestClient):
        """GET /api lists doc UIs so bare /api is not a 404."""
        response = client.get("/api")
        assert response.status_code == 200
        assert "/api/docs" in response.text
        assert "/api/reference" in response.text

    def test_api_reference_trailing_slash_redirects(self, client: TestClient):
        response = client.get("/api/reference/", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers.get("location", "").rstrip("/").endswith("/api/reference")


class TestAuthEndpoints:
    """Tests for authentication endpoints."""

    def test_login_success(self, client: TestClient, instructor_user):
        """Login with valid credentials succeeds."""
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": instructor_user.email,
                "password": "Instructor123!",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    def test_login_wrong_password(self, client: TestClient, instructor_user):
        """Login with wrong password fails."""
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": instructor_user.email,
                "password": "WrongPassword123!",
            },
        )
        assert response.status_code == 401
        data = response.json()
        assert data["error_code"] == "auth_error"

    def test_login_nonexistent_user(self, client: TestClient):
        """Login with nonexistent email fails."""
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": "nonexistent@test.com",
                "password": "Password123!",
            },
        )
        assert response.status_code == 401

    def test_refresh_success(self, client: TestClient, instructor_user):
        """Refresh returns a new access token when refresh token is valid."""
        login = client.post(
            "/api/v1/auth/login",
            json={
                "email": instructor_user.email,
                "password": "Instructor123!",
            },
        )
        assert login.status_code == 200
        refresh_token = login.json()["refresh_token"]
        response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert response.status_code == 200
        assert "access_token" in response.json()

    def test_logout_revokes_refresh_token(self, client: TestClient, instructor_user):
        """After logout, refresh with the same token fails."""
        login = client.post(
            "/api/v1/auth/login",
            json={
                "email": instructor_user.email,
                "password": "Instructor123!",
            },
        )
        assert login.status_code == 200
        refresh_token = login.json()["refresh_token"]
        out = client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh_token},
        )
        assert out.status_code == 204
        response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert response.status_code == 401

    def test_logout_idempotent_unknown_token(self, client: TestClient):
        """Logout with unknown token still returns 204."""
        response = client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "not-a-valid-jwt"},
        )
        assert response.status_code == 204

    def test_logout_all_requires_auth(self, client: TestClient):
        """Logout-all without Bearer token returns 401."""
        response = client.post("/api/v1/auth/logout-all")
        assert response.status_code == 401

    def test_logout_all_revokes_all_sessions(
        self, client: TestClient, instructor_user, db
    ):
        """Two refresh tokens for one user; logout-all invalidates both.

        No POST /login here — earlier tests already consume the per-minute login budget.
        """
        from datetime import datetime, timedelta, timezone

        from original.auth.jwt import create_access_token, create_refresh_token
        from original.core.config import get_settings
        from original.db.models import RefreshToken

        settings = get_settings()
        rt_a, hash_a = create_refresh_token(instructor_user)
        rt_b, hash_b = create_refresh_token(instructor_user)
        assert rt_a != rt_b
        exp = datetime.now(timezone.utc) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )
        db.add(
            RefreshToken(
                user_id=instructor_user.id,
                token_hash=hash_a,
                expires_at=exp,
            )
        )
        db.add(
            RefreshToken(
                user_id=instructor_user.id,
                token_hash=hash_b,
                expires_at=exp,
            )
        )
        db.commit()

        access = create_access_token(instructor_user)
        out = client.post(
            "/api/v1/auth/logout-all",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert out.status_code == 204
        for rt in (rt_a, rt_b):
            response = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": rt},
            )
            assert response.status_code == 401

    def test_login_rate_limiting(self, client: TestClient, instructor_user):
        """Multiple failed login attempts are eventually rate limited.

        Note: previous test methods in this class may have already consumed
        some of the 5/minute budget from 'testclient', so we simply verify
        that 429 is triggered within 10 attempts rather than asserting the
        exact request on which it fires.
        """
        got_rate_limited = False
        for _ in range(10):
            response = client.post(
                "/api/v1/auth/login",
                json={
                    "email": instructor_user.email,
                    "password": "WrongPassword123!",
                },
            )
            if response.status_code == 429:
                got_rate_limited = True
                break
            assert response.status_code == 401, (
                f"Expected 401 or 429, got {response.status_code}"
            )
        assert got_rate_limited, "Expected to be rate limited within 10 attempts"


class TestStudentEndpoints:
    """Tests for student management endpoints."""

    def test_list_students_requires_auth(self, client: TestClient):
        """List students requires authentication."""
        response = client.get("/api/v1/students/")
        assert response.status_code == 401

    def test_list_students_success(
        self, client: TestClient, instructor_auth_headers, test_student
    ):
        """List students returns student data."""
        response = client.get(
            "/api/v1/students/",
            headers=instructor_auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

    def test_get_student_success(
        self, client: TestClient, instructor_auth_headers, test_student
    ):
        """Get specific student returns student data."""
        response = client.get(
            f"/api/v1/students/{test_student.id}",
            headers=instructor_auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_student.id
        assert data["full_name"] == test_student.full_name


class TestSubmissionEndpoints:
    """Tests for submission and scoring endpoints."""

    def test_add_baseline_requires_auth(self, client: TestClient, test_student):
        """Adding baseline requires authentication."""
        response = client.post(
            f"/api/v1/submissions/{test_student.id}/baseline",
            json={
                "text": SAMPLE_TEXT,
                "assignment": "essay1",
                "provenance": "verified",
            },
        )
        assert response.status_code == 401

    def test_add_baseline_success(
        self, client: TestClient, instructor_auth_headers, test_student, db
    ):
        """Adding a baseline sample succeeds."""
        response = client.post(
            f"/api/v1/submissions/{test_student.id}/baseline",
            headers=instructor_auth_headers,
            json={
                "text": SAMPLE_TEXT,
                "assignment": "essay1",
                "provenance": "verified",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["sample_id"]
        assert data["student_id"] == test_student.id
        assert data["word_count"] > 0
        assert data["feature_count"] == 103

    def test_add_baseline_duplicate_detection(
        self, client: TestClient, instructor_auth_headers, test_student
    ):
        """Adding same text twice returns conflict."""
        # Add first time
        response1 = client.post(
            f"/api/v1/submissions/{test_student.id}/baseline",
            headers=instructor_auth_headers,
            json={
                "text": SAMPLE_TEXT,
                "assignment": "essay1",
                "provenance": "verified",
            },
        )
        assert response1.status_code == 201

        # Add second time (same text)
        response2 = client.post(
            f"/api/v1/submissions/{test_student.id}/baseline",
            headers=instructor_auth_headers,
            json={
                "text": SAMPLE_TEXT,
                "assignment": "essay1",
                "provenance": "verified",
            },
        )
        assert response2.status_code == 409

    def test_score_requires_sufficient_baseline(
        self, client: TestClient, instructor_auth_headers, test_student
    ):
        """Scoring requires minimum baseline samples."""
        # Try to score with no baseline
        response = client.post(
            f"/api/v1/submissions/{test_student.id}/score",
            headers=instructor_auth_headers,
            json={
                "text": SAMPLE_TEXT,
                "assignment": "submission1",
            },
        )
        assert response.status_code == 422
        data = response.json()
        assert data["error_code"] == "insufficient_baseline"

    def test_score_with_baseline(
        self, client: TestClient, instructor_auth_headers, test_student
    ):
        """Scoring with sufficient baseline succeeds."""
        # Add 3 baseline samples
        for i in range(3):
            client.post(
                f"/api/v1/submissions/{test_student.id}/baseline",
                headers=instructor_auth_headers,
                json={
                    "text": SAMPLE_TEXT + f" Sample {i}.",
                    "assignment": f"baseline{i}",
                    "provenance": "verified",
                },
            )

        # Score a submission
        response = client.post(
            f"/api/v1/submissions/{test_student.id}/score",
            headers=instructor_auth_headers,
            json={
                "text": DIFFERENT_TEXT,
                "assignment": "submission1",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["submission_id"]
        assert data["student_id"] == test_student.id
        assert "deviation_score" in data
        assert "authorship_probability" in data
        assert 0.0 <= data["deviation_score"] <= 1.0
        assert 0.0 <= data["authorship_probability"] <= 1.0

    def test_score_idempotency(
        self, client: TestClient, instructor_auth_headers, test_student
    ):
        """Scoring same text twice returns cached result."""
        # Setup baseline
        for i in range(3):
            client.post(
                f"/api/v1/submissions/{test_student.id}/baseline",
                headers=instructor_auth_headers,
                json={
                    "text": SAMPLE_TEXT + f" Sample {i}.",
                    "assignment": f"baseline{i}",
                    "provenance": "verified",
                },
            )

        # Score first time
        response1 = client.post(
            f"/api/v1/submissions/{test_student.id}/score",
            headers=instructor_auth_headers,
            json={
                "text": DIFFERENT_TEXT,
                "assignment": "submission1",
            },
        )
        assert response1.status_code == 201
        submission_id_1 = response1.json()["submission_id"]

        # Score same text again
        response2 = client.post(
            f"/api/v1/submissions/{test_student.id}/score",
            headers=instructor_auth_headers,
            json={
                "text": DIFFERENT_TEXT,
                "assignment": "submission1",
            },
        )
        assert response2.status_code == 201
        submission_id_2 = response2.json()["submission_id"]

        # Should return same submission ID (cached)
        assert submission_id_1 == submission_id_2

    def test_record_instructor_decision(
        self, client: TestClient, instructor_auth_headers, test_student
    ):
        """Recording instructor decision succeeds."""
        # Setup baseline
        for i in range(3):
            client.post(
                f"/api/v1/submissions/{test_student.id}/baseline",
                headers=instructor_auth_headers,
                json={
                    "text": SAMPLE_TEXT + f" Sample {i}.",
                    "assignment": f"baseline{i}",
                    "provenance": "verified",
                },
            )

        # Score a submission
        score_response = client.post(
            f"/api/v1/submissions/{test_student.id}/score",
            headers=instructor_auth_headers,
            json={
                "text": DIFFERENT_TEXT,
                "assignment": "submission1",
            },
        )
        submission_id = score_response.json()["submission_id"]

        # Record decision
        response = client.post(
            f"/api/v1/submissions/{test_student.id}/submissions/{submission_id}/decision",
            headers=instructor_auth_headers,
            json={
                "action": "monitor",
                "notes": "Requires further review",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["action"] == "monitor"
        assert data["notes"] == "Requires further review"
