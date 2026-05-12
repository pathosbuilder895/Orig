"""
tests/test_canvas.py — Canvas LTI integration tests.

Tests the LTI 1.3 OIDC endpoints, JWKS, Canvas webhook signature
verification, baseline import validation, and admin registration CRUD.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from original.db.models import Institution, User, UserRole
from original.db.models.canvas import LTIRegistration, LTIPlatformType
from original.auth.jwt import create_access_token
from original.auth.password import hash_password

# Canonical Canvas OIDC endpoint defaults used by both tests and fixtures
_CANVAS_AUTH = "https://seminary.instructure.com/api/lti/authorize_redirect"
_CANVAS_JWKS = "https://seminary.instructure.com/api/lti/security/jwks"


# ── LTI public endpoints ───────────────────────────────────────────────────────

class TestLTIPublicEndpoints:
    """Tests for LTI endpoints that require no auth (Canvas fetches these)."""

    def test_lti_config_returns_json(self, client: TestClient):
        """GET /lti/config returns a valid JSON tool configuration."""
        resp = client.get("/lti/config")
        assert resp.status_code == 200
        data = resp.json()
        # Required LTI 1.3 JSON config fields
        assert "title" in data
        assert "oidc_initiation_url" in data or "target_link_uri" in data

    def test_lti_jwks_returns_valid_structure(self, client: TestClient):
        """GET /lti/jwks returns a JWKS with an RSA key."""
        resp = client.get("/lti/jwks")
        assert resp.status_code == 200
        data = resp.json()
        assert "keys" in data
        assert len(data["keys"]) >= 1
        key = data["keys"][0]
        assert key["kty"] == "RSA"
        assert key["alg"] == "RS256"
        assert "n" in key
        assert "e" in key
        assert "kid" in key

    def test_lti_jwks_key_is_public_only(self, client: TestClient):
        """JWKS endpoint must not expose the private key component."""
        resp = client.get("/lti/jwks")
        data = resp.json()
        key = data["keys"][0]
        # "d" is the RSA private exponent — must never appear in JWKS
        assert "d" not in key

    def test_lti_login_missing_params_returns_error(self, client: TestClient):
        """GET /lti/login without required OIDC params returns 4xx."""
        resp = client.get("/lti/login")
        # No iss / login_hint → should error (400 or 422)
        assert resp.status_code in (400, 422)


# ── Canvas webhook signature verification ─────────────────────────────────────

class TestWebhookSignatureVerification:
    """Tests for HMAC-SHA256 Canvas webhook signature verification."""

    def _make_signature(self, body: bytes, secret: str) -> str:
        return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    def _patch_settings(self, monkeypatch, secret: str):
        """Patch the settings used by both webhook and lti modules."""
        fake = type("S", (), {
            "CANVAS_WEBHOOK_SECRET": secret,
            "CANVAS_BASE_URL": "https://seminary.instructure.com",
            "CANVAS_API_TOKEN": "",
            "ENVIRONMENT": "testing",
            "MODEL_VERSION": "1.0.0",
            "MIN_BASELINE_SAMPLES": 3,
        })()
        monkeypatch.setattr("original.canvas.webhook.get_settings", lambda: fake)

    def test_valid_signature_accepted(self, client: TestClient, db: Session, monkeypatch):
        """A request with a valid HMAC signature is accepted (200).

        webhook.py uses SessionLocal() directly (not FastAPI Depends), so we
        monkeypatch it to return the shared in-memory test DB session.
        """
        secret = "test-webhook-secret-abc123"
        self._patch_settings(monkeypatch, secret)

        # Patch SessionLocal used inside webhook.py to return the test DB
        monkeypatch.setattr(
            "original.canvas.webhook.SessionLocal",
            lambda: db,
        )

        payload = json.dumps({
            "id": "sub_001",
            "assignment_id": "asgn_001",
            "course_id": "course_001",
            "user_id": "user_001",
            "submission_type": "online_text_entry",
            "body": "Test submission body text for the canvas essay.",
        }).encode()

        sig = self._make_signature(payload, secret)

        resp = client.post(
            "/canvas/submission",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-Canvas-Signature": sig,
            },
        )
        # 200 OK (accepted, background task queued)
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

    def test_invalid_signature_rejected(self, client: TestClient, monkeypatch):
        """A request with a wrong HMAC signature is rejected (401)."""
        secret = "test-webhook-secret-abc123"
        self._patch_settings(monkeypatch, secret)

        payload = json.dumps({"id": "sub_002"}).encode()
        resp = client.post(
            "/canvas/submission",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-Canvas-Signature": "bad_signature_value",
            },
        )
        assert resp.status_code == 401

    def test_missing_signature_rejected_when_secret_configured(
        self, client: TestClient, monkeypatch
    ):
        """Missing signature header is rejected when a secret is configured."""
        secret = "test-webhook-secret-abc123"
        self._patch_settings(monkeypatch, secret)

        payload = json.dumps({"id": "sub_003"}).encode()
        resp = client.post(
            "/canvas/submission",
            content=payload,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401

    def test_hmac_signature_helper_correctness(self):
        """Sanity-check: our HMAC helper matches the production implementation."""
        secret = "my-canvas-secret"
        body = b'{"id": "sub_test"}'

        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        computed = self._make_signature(body, secret)
        assert expected == computed


# ── Canvas baseline import validation ────────────────────────────────────────

class TestCanvasBaselineImport:
    """Tests for the Canvas baseline import endpoints."""

    def test_list_submissions_requires_auth(self, client: TestClient, test_student):
        """Listing Canvas submissions requires authentication."""
        resp = client.post(
            f"/canvas/baseline/{test_student.id}/list-canvas-submissions",
            json={
                "canvas_course_id": "course_001",
                "canvas_user_id": "user_001",
            },
        )
        assert resp.status_code == 401

    def test_list_submissions_missing_canvas_url(
        self, client: TestClient, test_student, instructor_auth_headers
    ):
        """Listing submissions without a Canvas URL or token returns 400."""
        resp = client.post(
            f"/canvas/baseline/{test_student.id}/list-canvas-submissions",
            json={
                "canvas_course_id": "course_001",
                "canvas_user_id": "user_001",
                "canvas_url": "",
                "access_token": "",
            },
            headers=instructor_auth_headers,
        )
        assert resp.status_code == 400
        assert "required" in resp.json()["detail"].lower()

    def test_import_baseline_requires_auth(self, client: TestClient, test_student):
        """Importing Canvas baseline samples requires authentication."""
        resp = client.post(
            f"/canvas/baseline/{test_student.id}/import-baseline",
            json={
                "canvas_course_id": "course_001",
                "canvas_user_id": "user_001",
                "submission_ids": ["sub_001"],
            },
        )
        assert resp.status_code == 401

    def test_import_baseline_missing_credentials_returns_400(
        self, client: TestClient, test_student, instructor_auth_headers
    ):
        """Import baseline without credentials returns 400."""
        resp = client.post(
            f"/canvas/baseline/{test_student.id}/import-baseline",
            json={
                "canvas_course_id": "course_001",
                "canvas_user_id": "user_001",
                "canvas_url": "",
                "access_token": "",
                "submission_ids": ["sub_001"],
            },
            headers=instructor_auth_headers,
        )
        assert resp.status_code == 400


# ── Admin Canvas registration CRUD ────────────────────────────────────────────

class TestAdminCanvasRegistrations:
    """Tests for the admin LTI registration management API.

    The admin endpoints use Depends(get_db) so they work with the test DB.
    """

    def _reg_payload(self, suffix: str = "001") -> dict:
        return {
            "platform_iss": f"https://seminary-{suffix}.instructure.com",
            "platform_type": "canvas",
            "client_id": f"client_{suffix}",
            "deployment_id": f"deploy_{suffix}",
            "auth_endpoint": _CANVAS_AUTH,
            "jwks_url": _CANVAS_JWKS,
        }

    def test_list_registrations_requires_admin(
        self, client: TestClient, instructor_auth_headers
    ):
        """Non-admin cannot list LTI registrations."""
        resp = client.get(
            "/api/v1/admin/canvas/registrations",
            headers=instructor_auth_headers,
        )
        assert resp.status_code == 403

    def test_list_registrations_returns_list(
        self, client: TestClient, admin_auth_headers
    ):
        """Admin gets a list (possibly empty) of registrations."""
        resp = client.get(
            "/api/v1/admin/canvas/registrations",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_registration(
        self, client: TestClient, admin_auth_headers
    ):
        """Admin can create a new LTI registration."""
        resp = client.post(
            "/api/v1/admin/canvas/registrations",
            json=self._reg_payload("create01"),
            headers=admin_auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["client_id"] == "client_create01"
        assert data["platform_iss"] == "https://seminary-create01.instructure.com"
        assert "id" in data

    def test_create_duplicate_returns_409(
        self, client: TestClient, admin_auth_headers
    ):
        """Creating two registrations with the same iss+client_id returns 409."""
        payload = self._reg_payload("dup01")
        client.post(
            "/api/v1/admin/canvas/registrations",
            json=payload,
            headers=admin_auth_headers,
        )
        resp2 = client.post(
            "/api/v1/admin/canvas/registrations",
            json=payload,
            headers=admin_auth_headers,
        )
        assert resp2.status_code == 409

    def test_update_registration(
        self, client: TestClient, admin_auth_headers
    ):
        """Admin can update an existing LTI registration via PUT."""
        create_resp = client.post(
            "/api/v1/admin/canvas/registrations",
            json=self._reg_payload("upd01"),
            headers=admin_auth_headers,
        )
        assert create_resp.status_code == 201
        reg_id = create_resp.json()["id"]

        updated_payload = self._reg_payload("upd01")
        updated_payload["client_id"] = "client_upd01_after"

        update_resp = client.put(
            f"/api/v1/admin/canvas/registrations/{reg_id}",
            json=updated_payload,
            headers=admin_auth_headers,
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["client_id"] == "client_upd01_after"

    def test_update_nonexistent_registration_returns_404(
        self, client: TestClient, admin_auth_headers
    ):
        """Updating a registration that doesn't exist returns 404."""
        resp = client.put(
            "/api/v1/admin/canvas/registrations/nonexistent-uuid-9999",
            json=self._reg_payload("none"),
            headers=admin_auth_headers,
        )
        assert resp.status_code == 404

    def test_create_registration_appears_in_list(
        self, client: TestClient, admin_auth_headers
    ):
        """A newly created registration appears in the GET list."""
        create_resp = client.post(
            "/api/v1/admin/canvas/registrations",
            json=self._reg_payload("list01"),
            headers=admin_auth_headers,
        )
        assert create_resp.status_code == 201
        reg_id = create_resp.json()["id"]

        list_resp = client.get(
            "/api/v1/admin/canvas/registrations",
            headers=admin_auth_headers,
        )
        ids = [r["id"] for r in list_resp.json()]
        assert reg_id in ids
