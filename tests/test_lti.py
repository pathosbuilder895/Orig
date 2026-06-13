"""
LTI 1.3 launch tests (ADR-003, Phase 1.5).

Spins up a fake LMS platform: generates an RSA keypair, signs an id_token,
serves the matching JWK (via monkeypatched fetch), and drives /lti/launch.
Proves the launch mints a tenant-scoped principal and rejects tampering.
"""

import base64
import json
import re
import time

import pytest
from fastapi.testclient import TestClient

import run
from original import principal as pr
from original import lti

app = run.load_legacy_demo_app()
client = TestClient(app)

ISSUER = "https://canvas.test.instructure.com"
CLIENT_ID = "12500000000000123"
DEPLOYMENT = "1:deadbeef"
TENANT = "northfield"
JWKS_URL = "https://canvas.test/api/lti/security/jwks"


@pytest.fixture(scope="module")
def keypair():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    nums = key.public_key().public_numbers()

    def b64u_int(n):
        b = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(b).decode().rstrip("=")

    jwk = {"kty": "RSA", "alg": "RS256", "use": "sig", "kid": "test-kid-1",
           "n": b64u_int(nums.n), "e": b64u_int(nums.e)}
    return pem, jwk


@pytest.fixture(autouse=True)
def configure(monkeypatch, keypair):
    pem, jwk = keypair
    monkeypatch.setenv("LTI_TOOL_URL", "https://app.northfield.edu")
    monkeypatch.setenv("LTI_PLATFORMS", json.dumps([{
        "issuer": ISSUER, "client_id": CLIENT_ID, "jwks_url": JWKS_URL,
        "auth_login_url": "https://canvas.test/api/lti/authorize_redirect",
        "deployment_ids": [DEPLOYMENT], "tenant_id": TENANT, "name": "Northfield Canvas",
    }]))
    monkeypatch.setattr(lti, "fetch_jwks", lambda url: {"keys": [jwk]})
    yield


def _id_token(pem, *, roles, nonce, sub="lms-user-1", email="dr@northfield.edu",
              aud=CLIENT_ID, iss=ISSUER, dep=DEPLOYMENT, exp_delta=600, extra=None):
    from jose import jwt as jose_jwt
    now = int(time.time())
    claims = {
        "iss": iss, "aud": aud, "sub": sub, "email": email, "name": "Dr Test",
        "nonce": nonce, "iat": now, "exp": now + exp_delta,
        lti.CLAIM_DEPLOYMENT: dep,
        lti.CLAIM_MESSAGE_TYPE: "LtiResourceLinkRequest",
        lti.CLAIM_ROLES: roles,
    }
    if extra:
        claims.update(extra)
    return jose_jwt.encode(claims, pem, algorithm="RS256", headers={"kid": "test-kid-1"})


def _launch(pem, roles):
    nonce = "nonce-abc-123"
    state = lti.mint_state(nonce, ISSUER)
    token = _id_token(pem, roles=roles, nonce=nonce)
    return client.post("/lti/launch", data={"id_token": token, "state": state})


def _extract(html, key):
    m = re.search(re.escape(key) + r'","([^"]+)"', html)
    return m.group(1) if m else None


def test_instructor_launch_mints_professor_principal(keypair):
    pem, _ = keypair
    r = _launch(pem, ["http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"])
    assert r.status_code == 200, r.text
    assert "professor.html" in r.text
    token = _extract(r.text, "original_principal_token")
    claims = pr.verify_principal_token(token)
    assert claims and claims["tid"] == TENANT and claims["role"] == "professor"


def test_admin_launch_mints_admin_principal(keypair):
    pem, _ = keypair
    r = _launch(pem, ["http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator"])
    assert r.status_code == 200
    assert "admin.html" in r.text
    claims = pr.verify_principal_token(_extract(r.text, "original_principal_token"))
    assert claims["role"] == "admin" and claims["tid"] == TENANT


def test_student_exam_launch_into_bluebook(keypair):
    """A student launch targeting /bluebook binds the student and enters Bluebook."""
    pem, _ = keypair
    nonce = "exam-nonce"
    state = lti.mint_state(nonce, ISSUER)
    token = _id_token(
        pem, roles=["http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"],
        nonce=nonce,
        extra={
            lti.CLAIM_TARGET_LINK_URI: "https://app.northfield.edu/bluebook/",
            lti.CLAIM_RESOURCE_LINK: {"id": "rl-1", "title": "Ethics Final"},
        },
    )
    r = client.post("/lti/launch", data={"id_token": token, "state": state})
    assert r.status_code == 200, r.text
    assert "/bluebook/" in r.text          # redirected into Bluebook
    assert "bluebook_student_id" in r.text  # the student is bound
    assert "exam=Ethics" in r.text          # exam title passed as a param
    assert "original_session_token" in r.text


def test_instructor_exam_launch_into_bluebook(keypair):
    """An instructor launch targeting /bluebook enters the Bluebook dashboard."""
    pem, _ = keypair
    nonce = "exam-nonce-2"
    state = lti.mint_state(nonce, ISSUER)
    token = _id_token(
        pem, roles=["http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"],
        nonce=nonce,
        extra={lti.CLAIM_TARGET_LINK_URI: "https://app.northfield.edu/bluebook/"},
    )
    r = client.post("/lti/launch", data={"id_token": token, "state": state})
    assert r.status_code == 200
    assert "/bluebook/" in r.text
    assert "original_principal_token" in r.text


def test_student_launch_mints_session(keypair):
    pem, _ = keypair
    r = _launch(pem, ["http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"])
    assert r.status_code == 200
    assert "student.html" in r.text
    assert _extract(r.text, "original_session_token")  # student session present


def test_invalid_state_rejected(keypair):
    pem, _ = keypair
    token = _id_token(pem, roles=["...#Instructor"], nonce="x")
    r = client.post("/lti/launch", data={"id_token": token, "state": "forged.sig"})
    assert r.status_code == 401


def test_nonce_mismatch_rejected(keypair):
    pem, _ = keypair
    state = lti.mint_state("the-real-nonce", ISSUER)
    token = _id_token(pem, roles=["...#Instructor"], nonce="a-different-nonce")
    r = client.post("/lti/launch", data={"id_token": token, "state": state})
    assert r.status_code == 401


def test_unknown_deployment_rejected(keypair):
    pem, _ = keypair
    nonce = "n2"
    state = lti.mint_state(nonce, ISSUER)
    token = _id_token(pem, roles=["...#Instructor"], nonce=nonce, dep="9:unregistered")
    r = client.post("/lti/launch", data={"id_token": token, "state": state})
    assert r.status_code == 401


def test_login_redirects_to_platform():
    r = client.post("/lti/login", data={"iss": ISSUER, "login_hint": "u1", "client_id": CLIENT_ID},
                    follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://canvas.test/api/lti/authorize_redirect")
    assert "response_mode=form_post" in loc and "nonce=" in loc and "state=" in loc


def test_login_unknown_issuer_400():
    r = client.post("/lti/login", data={"iss": "https://evil.example", "login_hint": "u1"},
                    follow_redirects=False)
    assert r.status_code == 400
