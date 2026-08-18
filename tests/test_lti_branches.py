"""
Branch-coverage tests for original/lti.py and original/routers/lti_routes.py
(the LIVE LTI 1.3 surface — the dormant v1 /canvas/lti/* is out of scope, see
CLAUDE.md's "Two backends exist" note). tests/test_lti.py already exercises
the main success/reject paths at the HTTP layer through the full app; this
file closes the remaining branch arms: _private_key_pem's env-source
resolution, public_jwks/fetch_jwks configured-vs-not, verify_state's
malformed/expired arms, verify_launch's unknown-platform/no-matching-key
arms, build_login_redirect's lti_message_hint passthrough, find_platform's
fallback-to-first-candidate arm, is_exam_launch's custom-claim arm,
principal_from_claims' display-name-skip arm, and lti_routes.py's
lti_login/lti_launch request-validation and redirect-param arms.

original/lti.py's functions are plain synchronous code — tested by calling
them directly, no HTTP client involved.

original/routers/lti_routes.py's handlers are tested at the HTTP layer, but
through a bare FastAPI app that mounts *only* lti_routes.router, rather than
the full run.load_legacy_demo_app() stack test_lti.py uses. This is not a
shortcut around "call through the HTTP layer" — it is a workaround for a
verified coverage.py measurement gap:

    The full app wraps every route in 4 stacked middlewares (CORS,
    security_headers, tenant_isolation, maintenance_write_freeze —
    original/api.py). lti_login and lti_launch both do a bare
    `await request.form()` directly in their own function body (unlike
    FastAPI-native Form()/File() parameters, whose await happens in
    Starlette's own routing code *before* the handler is invoked). Once >=2
    Starlette BaseHTTPMiddleware layers are stacked in front of a handler
    that awaits inside its own frame, coverage.py stops recording line hits
    for everything in that frame *after* the await — confirmed by a minimal
    2-line reproduction (a bare FastAPI app with 1 middleware traces fully;
    the same app with 2 stacked middlewares loses the post-await lines) and
    by inline print()s inside lti_routes.py itself: the code provably runs
    (prints fire, correct redirect URLs are returned, assertions pass) while
    coverage.py still reports those lines as never executed. This reproduces
    identically through TestClient and through a bare httpx.AsyncClient +
    ASGITransport (i.e. it is not a TestClient-portal-thread artifact), and
    is unaffected by `concurrency=thread`/`sysmon` coverage settings.

    None of CORS/security-headers/tenant-isolation/maintenance-freeze gate
    or alter anything under test here: tenant_isolation is a no-op for
    /lti/* paths (not in _STAFF_ONLY_PREFIXES/_STAFF_ONLY_EXACT, and
    extract_scoped_id() doesn't match an LTI path), CORS/security-headers
    only touch response headers, and maintenance_write_freeze only acts when
    MAINTENANCE_MODE=1 (unset here). api.py mounts the identical
    `lti_routes.router.routes` objects onto the live app
    (`app.router.routes.extend(lti_routes.router.routes)`), so mounting the
    bare router is a faithful HTTP-level exercise of the same production
    route objects — real TestClient request, real FastAPI routing/dependency
    injection, real status codes and response bodies — just without the
    unrelated outer middlewares that trigger the measurement blind spot.
"""

from __future__ import annotations

import base64
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from original import lti
from original.routers import lti_routes

ISSUER = "https://canvas.test.instructure.com"
CLIENT_ID = "12500000000000123"
DEPLOYMENT = "1:deadbeef"
TENANT = "northfield"
JWKS_URL = "https://canvas.test/api/lti/security/jwks"


@pytest.fixture(scope="module")
def keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

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

    jwk = {
        "kty": "RSA",
        "alg": "RS256",
        "use": "sig",
        "kid": "test-kid-1",
        "n": b64u_int(nums.n),
        "e": b64u_int(nums.e),
    }
    return pem, jwk


def _id_token(
    pem,
    *,
    roles,
    nonce,
    sub="lms-user-1",
    email="dr@northfield.edu",
    aud=CLIENT_ID,
    iss=ISSUER,
    dep=DEPLOYMENT,
    exp_delta=600,
    extra=None,
):
    """Same idiom as tests/test_lti.py::_id_token."""
    from jose import jwt as jose_jwt

    now = int(time.time())
    claims = {
        "iss": iss,
        "aud": aud,
        "sub": sub,
        "email": email,
        "name": "Dr Test",
        "nonce": nonce,
        "iat": now,
        "exp": now + exp_delta,
        lti.CLAIM_DEPLOYMENT: dep,
        lti.CLAIM_MESSAGE_TYPE: "LtiResourceLinkRequest",
        lti.CLAIM_ROLES: roles,
    }
    if extra:
        claims.update(extra)
    return jose_jwt.encode(claims, pem, algorithm="RS256", headers={"kid": "test-kid-1"})


# ══════════════════════════════════════════════════════════════════════════
# original/lti.py — pure functions, called directly
# ══════════════════════════════════════════════════════════════════════════


# ── _private_key_pem: 4/4 (LTI_PRIVATE_KEY set x LTI_PRIVATE_KEY_FILE set&exists) ──


def test_private_key_pem_inline_env_wins_and_unescapes_newlines(monkeypatch):
    monkeypatch.setenv("LTI_PRIVATE_KEY", "line1\\nline2")
    monkeypatch.delenv("LTI_PRIVATE_KEY_FILE", raising=False)
    assert lti._private_key_pem() == "line1\nline2"


def test_private_key_pem_neither_source_set_returns_none(monkeypatch):
    monkeypatch.delenv("LTI_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("LTI_PRIVATE_KEY_FILE", raising=False)
    assert lti._private_key_pem() is None


def test_private_key_pem_file_source_used_when_inline_unset(monkeypatch, tmp_path):
    key_file = tmp_path / "key.pem"
    key_file.write_text("file-contents-of-the-key")
    monkeypatch.delenv("LTI_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("LTI_PRIVATE_KEY_FILE", str(key_file))
    assert lti._private_key_pem() == "file-contents-of-the-key"


def test_private_key_pem_file_path_set_but_missing_returns_none(monkeypatch, tmp_path):
    monkeypatch.delenv("LTI_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("LTI_PRIVATE_KEY_FILE", str(tmp_path / "does-not-exist.pem"))
    assert lti._private_key_pem() is None


def test_private_key_pem_file_read_error_returns_none(monkeypatch, tmp_path):
    # tmp_path is a directory: os.path.exists() is True but open() raises
    # IsADirectoryError — exercises the try/except around the file read
    # (bonus: statement coverage for lines 140-143, not a distinct branch).
    monkeypatch.delenv("LTI_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("LTI_PRIVATE_KEY_FILE", str(tmp_path))
    assert lti._private_key_pem() is None


# ── public_jwks: 2/2 (unconfigured vs configured) ───────────────────────────


def test_public_jwks_unconfigured_returns_empty_keys(monkeypatch):
    monkeypatch.delenv("LTI_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("LTI_PRIVATE_KEY_FILE", raising=False)
    assert lti.public_jwks() == {"keys": []}


def test_public_jwks_configured_publishes_matching_jwk(monkeypatch, keypair):
    pem, _ = keypair
    monkeypatch.setenv("LTI_PRIVATE_KEY", pem)
    monkeypatch.delenv("LTI_PRIVATE_KEY_FILE", raising=False)

    jwks = lti.public_jwks()
    assert len(jwks["keys"]) == 1
    key = jwks["keys"][0]
    assert key["kty"] == "RSA" and key["alg"] == "RS256" and key["use"] == "sig"
    assert key["kid"] == lti._kid()

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: F401 (type context)

    real_key = serialization.load_pem_private_key(pem.encode(), password=None)
    nums = real_key.public_key().public_numbers()

    def _b64u_int(s: str) -> int:
        return int.from_bytes(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)), "big")

    assert _b64u_int(key["n"]) == nums.n
    assert _b64u_int(key["e"]) == nums.e


# ── fetch_jwks: 2/2 (cached vs not) — real urllib.request.urlopen is stubbed,
# no real network I/O.  Isolates the module-level _JWKS_CACHE around each test
# so these don't leak into (or get clobbered by) any other test module. ──────


@pytest.fixture(autouse=True)
def _isolate_jwks_cache():
    lti._JWKS_CACHE.clear()
    yield
    lti._JWKS_CACHE.clear()


def test_fetch_jwks_uncached_fetches_and_populates_cache(monkeypatch):
    payload = json.dumps({"keys": [{"kid": "k1"}]}).encode()

    class _FakeResp:
        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    calls = []

    def fake_urlopen(url, timeout=8):
        calls.append((url, timeout))
        return _FakeResp()

    monkeypatch.setattr(lti.urllib.request, "urlopen", fake_urlopen)
    result = lti.fetch_jwks("https://platform.example/jwks")
    assert result == {"keys": [{"kid": "k1"}]}
    assert calls == [("https://platform.example/jwks", 8)]
    assert lti._JWKS_CACHE["https://platform.example/jwks"] == result


def test_fetch_jwks_cached_short_circuits_without_network_call(monkeypatch):
    lti._JWKS_CACHE["https://platform.example/jwks"] = {"keys": [{"kid": "cached"}]}

    def fail_urlopen(*a, **k):
        raise AssertionError("fetch_jwks must not hit the network when already cached")

    monkeypatch.setattr(lti.urllib.request, "urlopen", fail_urlopen)
    result = lti.fetch_jwks("https://platform.example/jwks")
    assert result == {"keys": [{"kid": "cached"}]}


# ── verify_state: malformed / expired arms ──────────────────────────────────


def test_verify_state_no_dot_returns_none():
    assert lti.verify_state("not-a-valid-state-token") is None


def test_verify_state_empty_returns_none():
    assert lti.verify_state("") is None


def test_verify_state_expired_returns_none():
    state = lti.mint_state("nonce-expired", "https://issuer.example", ttl_seconds=-10)
    assert lti.verify_state(state) is None


def test_verify_state_corrupt_json_payload_returns_none():
    # Correctly signed, but the payload doesn't decode to JSON — exercises
    # the try/except around json.loads (bonus statement coverage).
    payload = lti._b64(b"not-json-at-all")
    state = f"{payload}.{lti._sign(payload)}"
    assert lti.verify_state(state) is None


# ── platforms(): malformed LTI_PLATFORMS JSON — not a branch (no missing
# branches on this function) but closes the last 2 stray statement lines. ──


def test_platforms_malformed_json_returns_empty_list(monkeypatch):
    monkeypatch.setenv("LTI_PLATFORMS", "{not valid json")
    assert lti.platforms() == []


# ── find_platform: fallback-to-first-candidate when client_id doesn't match ─


def test_find_platform_falls_back_to_first_candidate_on_client_id_mismatch(monkeypatch):
    monkeypatch.setenv(
        "LTI_PLATFORMS",
        json.dumps([{"issuer": ISSUER, "client_id": "the-configured-client-id"}]),
    )
    result = lti.find_platform(ISSUER, "some-other-client-id")
    assert result is not None
    assert result["client_id"] == "the-configured-client-id"


# ── is_exam_launch: custom-claim arm (no /bluebook target_link_uri) ─────────


def test_is_exam_launch_custom_bluebook_flag_without_target_link_uri():
    claims = {
        lti.CLAIM_TARGET_LINK_URI: "https://lms.example/course/assignment/123",
        lti.CLAIM_CUSTOM: {"bluebook": 1},
    }
    assert lti.is_exam_launch(claims) is True


def test_is_exam_launch_custom_exam_id_without_target_link_uri():
    assert lti.is_exam_launch({lti.CLAIM_CUSTOM: {"exam_id": "final-2026"}}) is True


# ── build_login_redirect: lti_message_hint passthrough ──────────────────────


def test_build_login_redirect_passes_through_lti_message_hint(monkeypatch):
    monkeypatch.setenv(
        "LTI_PLATFORMS",
        json.dumps(
            [
                {
                    "issuer": ISSUER,
                    "client_id": CLIENT_ID,
                    "auth_login_url": "https://canvas.test/authorize",
                }
            ]
        ),
    )
    url = lti.build_login_redirect(
        {
            "iss": ISSUER,
            "client_id": CLIENT_ID,
            "login_hint": "u1",
            "lti_message_hint": "resourcelink-42",
        }
    )
    assert "lti_message_hint=resourcelink-42" in url


# ── verify_launch: unknown-platform / no-matching-JWKS-key arms ────────────


def test_verify_launch_unknown_platform_for_id_token(monkeypatch, keypair):
    pem, _ = keypair
    monkeypatch.delenv("LTI_PLATFORMS", raising=False)
    state = lti.mint_state("n1", "https://unconfigured.example")
    token = _id_token(
        pem,
        roles=["http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"],
        nonce="n1",
        iss="https://unconfigured.example",
        aud="unknown-client-id",
    )
    with pytest.raises(lti.LtiError, match="unknown platform"):
        lti.verify_launch(token, state)


def test_verify_launch_no_matching_jwks_key(monkeypatch, keypair):
    pem, _ = keypair
    monkeypatch.setenv(
        "LTI_PLATFORMS",
        json.dumps(
            [{"issuer": ISSUER, "client_id": CLIENT_ID, "jwks_url": JWKS_URL, "tenant_id": TENANT}]
        ),
    )
    monkeypatch.setattr(lti, "fetch_jwks", lambda url: {"keys": []})
    state = lti.mint_state("n2", ISSUER)
    token = _id_token(
        pem,
        roles=["http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"],
        nonce="n2",
    )
    with pytest.raises(lti.LtiError, match="no matching JWKS key"):
        lti.verify_launch(token, state)


def test_verify_launch_signature_verification_failure(monkeypatch, keypair):
    """A different keypair signs the token; the platform's JWKS still
    publishes the original public key under the SAME kid, so a key IS found
    (skipping the "no matching key" arm above) but jose's actual signature
    check fails inside jwt.decode — not one of the 21 target branches (no
    branch pair on a bare try/except), but closes the remaining 2 statement
    lines in verify_launch's decode-failure handler."""
    pem, jwk = keypair
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_pem = wrong_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()

    monkeypatch.setenv(
        "LTI_PLATFORMS",
        json.dumps(
            [{"issuer": ISSUER, "client_id": CLIENT_ID, "jwks_url": JWKS_URL, "tenant_id": TENANT}]
        ),
    )
    monkeypatch.setattr(lti, "fetch_jwks", lambda url: {"keys": [jwk]})
    state = lti.mint_state("n3", ISSUER)
    token = _id_token(
        wrong_pem,
        roles=["http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"],
        nonce="n3",
    )
    with pytest.raises(lti.LtiError, match="id_token verification failed"):
        lti.verify_launch(token, state)


# ── principal_from_claims: display-name-skip arm ────────────────────────────


def test_principal_from_claims_no_name_skips_display_name_update(monkeypatch):
    def _boom():
        raise AssertionError("get_repository() must not be called when name is empty")

    monkeypatch.setattr("original.repository.get_repository", _boom)
    claims = {
        "_tenant_id": TENANT,
        lti.CLAIM_ROLES: ["http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"],
        "sub": "lms-user-99",
        "email": "noname@northfield.edu",
    }
    result = lti.principal_from_claims(claims)
    assert result["role"] == "student"
    assert result["redirect"] == "student.html"


def test_principal_from_claims_display_name_update_failure_is_swallowed(monkeypatch):
    class _RaisingRepo:
        def set_display_name(self, sid, name):
            raise RuntimeError("simulated repository failure")

    monkeypatch.setattr("original.repository.get_repository", lambda: _RaisingRepo())
    claims = {
        "_tenant_id": TENANT,
        lti.CLAIM_ROLES: ["http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"],
        "sub": "lms-user-100",
        "email": "hasname@northfield.edu",
        "name": "Real Name",
    }
    # The display-name write is best-effort (except: pass) — a repository
    # failure must not prevent the launch itself from succeeding.
    result = lti.principal_from_claims(claims)
    assert result["role"] == "student"
    assert result["token"]


# ══════════════════════════════════════════════════════════════════════════
# original/routers/lti_routes.py — HTTP layer via a bare router-only app
# (see the module docstring for why this isn't run.load_legacy_demo_app())
# ══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def lti_client():
    bare_app = FastAPI()
    bare_app.include_router(lti_routes.router)
    return TestClient(bare_app)


@pytest.fixture
def platform_env(monkeypatch, keypair):
    """Real platform + JWKS config, matching tests/test_lti.py's `configure`."""
    pem, jwk = keypair
    monkeypatch.setenv("LTI_TOOL_URL", "https://app.northfield.edu")
    monkeypatch.setenv(
        "LTI_PLATFORMS",
        json.dumps(
            [
                {
                    "issuer": ISSUER,
                    "client_id": CLIENT_ID,
                    "jwks_url": JWKS_URL,
                    "auth_login_url": "https://canvas.test/api/lti/authorize_redirect",
                    "deployment_ids": [DEPLOYMENT],
                    "tenant_id": TENANT,
                    "name": "Northfield Canvas",
                }
            ]
        ),
    )
    monkeypatch.setattr(lti, "fetch_jwks", lambda url: {"keys": [jwk]})
    return pem


# ── lti_login: 1/2 missing (GET vs POST) ────────────────────────────────────


def test_lti_login_get_request_also_redirects(lti_client, platform_env):
    """The LTI spec requires /lti/login to accept both GET and POST — the
    `if request.method == "POST":` branch's False arm (skip form parsing)
    was never exercised (existing tests only POST)."""
    r = lti_client.get(
        "/lti/login",
        params={"iss": ISSUER, "client_id": CLIENT_ID, "login_hint": "u1"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"].startswith("https://canvas.test/api/lti/authorize_redirect")


def test_lti_login_unknown_issuer_400(lti_client):
    r = lti_client.post(
        "/lti/login",
        data={"iss": "https://evil.example", "login_hint": "u1"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "LTI login error" in r.json()["detail"]


# ── lti_launch: 4/4 missing ─────────────────────────────────────────────────


def test_lti_launch_missing_id_token_400(lti_client):
    r = lti_client.post("/lti/launch", data={"state": "whatever"})
    assert r.status_code == 400
    assert "missing id_token or state" in r.json()["detail"]


def test_lti_launch_missing_state_400(lti_client):
    r = lti_client.post("/lti/launch", data={"id_token": "whatever"})
    assert r.status_code == 400
    assert "missing id_token or state" in r.json()["detail"]


def test_lti_launch_rejected_launch_401(lti_client, platform_env):
    """Both id_token and state are present (the False arm of the missing-field
    check) but the launch itself is invalid — nonce mismatch."""
    pem = platform_env
    state = lti.mint_state("the-real-nonce", ISSUER)
    token = _id_token(
        pem,
        roles=["http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"],
        nonce="a-different-nonce",
    )
    r = lti_client.post("/lti/launch", data={"id_token": token, "state": state})
    assert r.status_code == 401
    assert "LTI launch rejected" in r.json()["detail"]


def test_lti_launch_import_error_surfaces_as_501(lti_client, monkeypatch):
    """Demo deployments that omit python-jose: verify_launch raises ImportError
    (module docstring), which the router maps to a 501, not a 500."""

    def _boom(*a, **k):
        raise ImportError("python-jose is not installed")

    monkeypatch.setattr(lti, "verify_launch", _boom)
    r = lti_client.post("/lti/launch", data={"id_token": "x", "state": "y"})
    assert r.status_code == 501
    assert "python-jose" in r.json()["detail"]


def test_lti_launch_non_exam_launch_has_no_query_params_appended(
    lti_client, platform_env, store_reset
):
    pem = platform_env
    nonce = "nonce-success-1"
    state = lti.mint_state(nonce, ISSUER)
    token = _id_token(
        pem,
        roles=["http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"],
        nonce=nonce,
    )
    r = lti_client.post("/lti/launch", data={"id_token": token, "state": state})
    assert r.status_code == 200, r.text
    assert "professor.html" in r.text
    # params is {} for a non-exam launch, so the "?..." branch is skipped.
    assert "professor.html?" not in r.text


def test_lti_launch_exam_launch_appends_query_params(lti_client, platform_env, store_reset):
    pem = platform_env
    nonce = "nonce-exam-1"
    state = lti.mint_state(nonce, ISSUER)
    token = _id_token(
        pem,
        roles=["http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"],
        nonce=nonce,
        extra={
            lti.CLAIM_TARGET_LINK_URI: "https://app.northfield.edu/bluebook/",
            lti.CLAIM_RESOURCE_LINK: {"id": "rl-1", "title": "Ethics Final"},
        },
    )
    r = lti_client.post("/lti/launch", data={"id_token": token, "state": state})
    assert r.status_code == 200, r.text
    # redirect ("/bluebook/") ends with "/" and params is non-empty -> the
    # query string gets appended.
    assert "/bluebook/?exam=" in r.text


# ── lti_jwks (not in the 21 missing branches — 0 branches — but cheap to close) ──


def test_lti_jwks_returns_public_jwks(lti_client, monkeypatch):
    monkeypatch.delenv("LTI_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("LTI_PRIVATE_KEY_FILE", raising=False)
    r = lti_client.get("/lti/jwks")
    assert r.status_code == 200
    assert r.json() == {"keys": []}
