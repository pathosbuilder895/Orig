"""
Staff email+password auth tests (ADR-003, Phase 1.x).

Covers register → login → /auth/me, failure modes, and that a real login token
mints a principal the tenant-isolation middleware enforces.
"""

import pytest
from fastapi.testclient import TestClient

# The app lives in the plainly-imported original.api module (WS-6 P6
# dissolved the module-shadowing importlib hack). tests/context/test_drift.py
# loads private fresh copies mid-suite, but this module reference (where our
# `app` actually lives) stays valid.
import original.api as _legacy_mod
import run
from original import principal as pr

app = run.load_legacy_demo_app()
client = TestClient(app)

EMAIL = "prof.auth@acmeu.edu"
PW = "s3cret-passw0rd"
TENANT = "acmeu"

LONG_TEXT = (
    "Grace and peace are the twin notes that open nearly every Pauline letter, "
    "and their repetition is not accidental but theological. The writer returns "
    "again and again to the same vocabulary, the same cadence, the same habit of "
    "qualifying a bold claim with a gentle clause. Across a semester these habits "
    "compound into a recognizable voice, and it is that voice, not any single "
    "sentence, that the system learns to know and to defend with care and patience."
)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module", autouse=True)
def provision():
    # demo mode: GUARD_DESTRUCTIVE off → register is open
    client.post(
        "/auth/register",
        json={
            "email": EMAIL,
            "password": PW,
            "role": "professor",
            "tenant_id": TENANT,
            "name": "Dr Auth",
        },
    )
    yield


def test_login_success_returns_token_and_tenant():
    r = client.post("/auth/login", json={"email": EMAIL, "password": PW})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "professor"
    assert body["tenant_id"] == TENANT
    assert body["token"]
    # token verifies and carries the right claims
    claims = pr.verify_principal_token(body["token"])
    assert claims and claims["tid"] == TENANT and claims["role"] == "professor"


def test_login_wrong_password_denied():
    r = client.post("/auth/login", json={"email": EMAIL, "password": "nope"})
    assert r.status_code == 401


def test_login_unknown_email_denied():
    r = client.post("/auth/login", json={"email": "ghost@nowhere.edu", "password": PW})
    assert r.status_code == 401


def test_login_missing_fields_422():
    r = client.post("/auth/login", json={"email": EMAIL})
    assert r.status_code == 422


def test_login_empty_email_is_the_handlers_own_422():
    """A blank string (not an omitted key) passes pydantic's `str` type check
    and reaches auth_login's own `if not email or not password` guard — a
    different branch from test_login_missing_fields_422's pydantic-level 422
    above, which never enters the handler body at all."""
    r = client.post("/auth/login", json={"email": "", "password": PW})
    assert r.status_code == 422
    assert "required" in r.json()["detail"]


def test_duplicate_register_conflict():
    r = client.post(
        "/auth/register",
        json={"email": EMAIL, "password": PW, "role": "professor", "tenant_id": TENANT},
    )
    assert r.status_code == 409


def test_register_empty_tenant_id_is_422():
    """Blank tenant_id (not omitted) reaches the handler's own
    `if not email or not password or not tenant_id` guard."""
    r = client.post(
        "/auth/register",
        json={"email": "blank@acmeu.edu", "password": PW, "role": "professor", "tenant_id": ""},
    )
    assert r.status_code == 422
    assert "required" in r.json()["detail"]


def test_register_invalid_role_rejected():
    r = client.post(
        "/auth/register",
        json={
            "email": "badrole@acmeu.edu",
            "password": PW,
            "role": "student",
            "tenant_id": TENANT,
        },
    )
    assert r.status_code == 422
    assert "role must be" in r.json()["detail"]


def test_register_short_password_rejected():
    r = client.post(
        "/auth/register",
        json={
            "email": "x@acmeu.edu",
            "password": "short",
            "role": "professor",
            "tenant_id": TENANT,
        },
    )
    assert r.status_code == 422


def test_me_requires_auth():
    assert client.get("/auth/me").status_code == 401
    token = client.post("/auth/login", json={"email": EMAIL, "password": PW}).json()["token"]
    r = client.get("/auth/me", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["tenant_id"] == TENANT
    assert r.json()["auth_method"] == "principal-token"


def test_login_throttled_after_repeated_attempts():
    """Per-IP sliding window: the 11th attempt inside the window gets 429."""
    legacy = _legacy_mod
    legacy._login_attempts.clear()
    try:
        codes = [
            client.post("/auth/login", json={"email": EMAIL, "password": "wrong"}).status_code
            for _ in range(11)
        ]
        assert all(c == 401 for c in codes[:10]), codes
        assert codes[10] == 429, codes
    finally:
        legacy._login_attempts.clear()  # don't poison other tests' window


def test_logged_in_professor_is_tenant_scoped_end_to_end():
    """The token from /auth/login is enforced by the isolation middleware."""
    token = client.post("/auth/login", json={"email": EMAIL, "password": PW}).json()["token"]
    # can create + read within own tenant
    sid = f"{TENANT}:essay1"
    assert (
        client.post(
            f"/students/{sid}/baseline",
            json={"text": LONG_TEXT, "assignment": "a1"},
            headers=_auth(token),
        ).status_code
        == 200
    )
    assert client.get(f"/students/{sid}", headers=_auth(token)).status_code == 200
    # cannot reach another tenant
    assert client.get("/students/otheru:essay1", headers=_auth(token)).status_code == 403
