"""
lti.py — LTI 1.3 launch → Original principal (ADR-003, Phase 1.5).

Implements the LTI 1.3 / OIDC launch so an instructor (or admin/student) can open
Original directly from their LMS (Canvas, Blackboard, Moodle …). The launch
terminates in the SAME principal token used by email/password login, so the
tenant-isolation middleware enforces it identically.

Flow
────
1. ``/lti/login``  — OIDC third-party initiation. We redirect to the platform's
   auth endpoint with a signed ``state`` (carrying our ``nonce``) so the rest of
   the flow is stateless (no server-side session needed).
2. ``/lti/launch`` — the platform POSTs an ``id_token`` (RS256 JWT). We verify it
   against the platform's JWKS, check iss/aud/nonce/deployment, map LTI roles +
   the platform→tenant binding to a principal, mint a token, and hand it to the
   browser which stores it and enters the dashboard.
3. ``/lti/jwks``   — our tool's public key set (for platforms that verify tool
   requests / future LTI-AGS signing).

Heavy crypto deps (python-jose, cryptography) are imported lazily inside the
functions that need them, so the demo deployment — which omits them — still
imports this module; LTI endpoints simply return a clear error if unconfigured.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

from . import principal as principal_mod
from . import student_auth

# LTI 1.3 claim URIs
CLAIM_ROLES = "https://purl.imsglobal.org/spec/lti/claim/roles"
CLAIM_DEPLOYMENT = "https://purl.imsglobal.org/spec/lti/claim/deployment_id"
CLAIM_MESSAGE_TYPE = "https://purl.imsglobal.org/spec/lti/claim/message_type"
CLAIM_RESOURCE_LINK = "https://purl.imsglobal.org/spec/lti/claim/resource_link"
CLAIM_TARGET_LINK_URI = "https://purl.imsglobal.org/spec/lti/claim/target_link_uri"
CLAIM_CUSTOM = "https://purl.imsglobal.org/spec/lti/claim/custom"


def is_exam_launch(claims: Dict) -> bool:
    """True when the LMS launch targets a Bluebook examination.

    Detected from the resource link's target_link_uri pointing at /bluebook,
    or a custom claim (custom: { bluebook: 1 } or { exam_id: ... }) set on the
    LMS placement.
    """
    tlu = str(claims.get(CLAIM_TARGET_LINK_URI) or "")
    if "/bluebook" in tlu:
        return True
    custom = claims.get(CLAIM_CUSTOM)
    if isinstance(custom, dict) and (custom.get("bluebook") or custom.get("exam_id")):
        return True
    return False


class LtiError(Exception):
    """Recoverable LTI configuration / validation error → 4xx."""


# ── Signing (shared HMAC for the stateless `state` token) ─────────────────────

def _secret() -> bytes:
    return (os.environ.get("SECRET_KEY") or "demo-insecure-student-secret").encode()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(payload: str) -> str:
    return _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())


def mint_state(nonce: str, issuer: str, ttl_seconds: int = 600) -> str:
    body = {"nonce": nonce, "iss": issuer, "exp": int(time.time()) + ttl_seconds}
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    return f"{payload}.{_sign(payload)}"


def verify_state(state: str) -> Optional[Dict]:
    if not state or "." not in state:
        return None
    payload, sig = state.split(".", 1)
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    try:
        body = json.loads(_unb64(payload))
    except Exception:
        return None
    if float(body.get("exp", 0)) < time.time():
        return None
    return body


# ── Configuration ─────────────────────────────────────────────────────────────

def platforms() -> List[Dict]:
    try:
        data = json.loads(os.environ.get("LTI_PLATFORMS", "[]") or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def find_platform(issuer: str, client_id: Optional[str] = None) -> Optional[Dict]:
    cands = [p for p in platforms() if p.get("issuer") == issuer]
    if client_id is not None:
        exact = [p for p in cands if str(p.get("client_id")) == str(client_id)]
        if exact:
            return exact[0]
    return cands[0] if cands else None


def tool_url() -> str:
    return os.environ.get("LTI_TOOL_URL", "").rstrip("/")


def _private_key_pem() -> Optional[str]:
    pem = os.environ.get("LTI_PRIVATE_KEY", "")
    if pem:
        return pem.replace("\\n", "\n")
    path = os.environ.get("LTI_PRIVATE_KEY_FILE", "")
    if path and os.path.exists(path):
        try:
            return open(path, encoding="utf-8").read()
        except Exception:
            return None
    return None


def _kid() -> str:
    pem = _private_key_pem() or ""
    return hashlib.sha256(pem.encode()).hexdigest()[:16] if pem else "original-lti"


def public_jwks() -> Dict:
    """Tool public key set. Empty if no tool key is configured."""
    pem = _private_key_pem()
    if not pem:
        return {"keys": []}
    from cryptography.hazmat.primitives import serialization  # lazy

    key = serialization.load_pem_private_key(pem.encode(), password=None)
    nums = key.public_key().public_numbers()

    def b64u_int(n: int) -> str:
        b = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(b).decode().rstrip("=")

    return {"keys": [{
        "kty": "RSA", "alg": "RS256", "use": "sig", "kid": _kid(),
        "n": b64u_int(nums.n), "e": b64u_int(nums.e),
    }]}


# ── Platform JWKS (cached) ─────────────────────────────────────────────────────

_JWKS_CACHE: Dict[str, Dict] = {}


def fetch_jwks(url: str) -> Dict:
    if url in _JWKS_CACHE:
        return _JWKS_CACHE[url]
    with urllib.request.urlopen(url, timeout=8) as resp:  # noqa: S310 (trusted platform URL)
        data = json.loads(resp.read().decode())
    _JWKS_CACHE[url] = data
    return data


# ── OIDC login (step 1) ────────────────────────────────────────────────────────

def build_login_redirect(params: Dict) -> str:
    """Build the platform auth-redirect URL for the OIDC initiation."""
    issuer = params.get("iss") or ""
    client_id = params.get("client_id")
    platform = find_platform(issuer, client_id)
    if not platform:
        raise LtiError(f"unknown platform issuer '{issuer}'")
    nonce = secrets.token_urlsafe(16)
    q = {
        "scope": "openid",
        "response_type": "id_token",
        "response_mode": "form_post",
        "prompt": "none",
        "client_id": str(platform["client_id"]),
        "redirect_uri": tool_url() + "/lti/launch",
        "login_hint": params.get("login_hint", ""),
        "state": mint_state(nonce, issuer),
        "nonce": nonce,
    }
    if params.get("lti_message_hint"):
        q["lti_message_hint"] = params["lti_message_hint"]
    return platform["auth_login_url"] + "?" + urllib.parse.urlencode(q)


# ── Launch verification (step 2) ───────────────────────────────────────────────

def verify_launch(id_token: str, state: str) -> Dict:
    """Verify state + id_token; return the claims (with `_tenant_id`). Raises LtiError."""
    st = verify_state(state)
    if not st:
        raise LtiError("invalid or expired state")

    from jose import jwt as jose_jwt  # lazy (python-jose)

    unverified = jose_jwt.get_unverified_claims(id_token)
    issuer = unverified.get("iss")
    aud = unverified.get("aud")
    client_id = aud[0] if isinstance(aud, list) else aud
    platform = find_platform(issuer, client_id)
    if not platform:
        raise LtiError("unknown platform for id_token")

    jwks = fetch_jwks(platform["jwks_url"])
    header = jose_jwt.get_unverified_header(id_token)
    kid = header.get("kid")
    keys = jwks.get("keys", [])
    key = next((k for k in keys if k.get("kid") == kid), keys[0] if keys else None)
    if key is None:
        raise LtiError("no matching JWKS key")

    try:
        claims = jose_jwt.decode(
            id_token, key, algorithms=["RS256"],
            audience=str(platform["client_id"]), issuer=issuer,
        )
    except Exception as e:  # jose raises various JWTError subclasses
        raise LtiError(f"id_token verification failed: {e}")

    if claims.get("nonce") != st.get("nonce"):
        raise LtiError("nonce mismatch")

    deployment = claims.get(CLAIM_DEPLOYMENT)
    allowed = platform.get("deployment_ids") or []
    if allowed and deployment not in allowed:
        raise LtiError("unrecognised deployment_id")

    claims["_tenant_id"] = platform["tenant_id"]
    return claims


# ── Claims → principal ─────────────────────────────────────────────────────────

def role_from_claims(claims: Dict) -> str:
    roles = claims.get(CLAIM_ROLES) or []
    joined = " ".join(roles).lower()
    if "administrator" in joined:
        return "admin"
    if any(t in joined for t in ("instructor", "teacher", "faculty", "mentor")):
        return "professor"
    return "student"


def principal_from_claims(claims: Dict) -> Dict:
    """Map verified claims → a launch result.

    Returns ``{role, tenant_id, token, token_key, redirect, extra?, params?}``.
    For a Bluebook exam launch the redirect targets ``/bluebook/`` and the
    student is bound (``bluebook_student_id``) so the proctored baseline lands on
    their canonical profile; the exam title / candidate are passed as URL params
    the Bluebook bootstrap reads.
    """
    tenant = claims["_tenant_id"]
    role = role_from_claims(claims)
    sub = str(claims.get("sub") or "")
    email = claims.get("email") or ""
    name = claims.get("name") or claims.get("given_name") or ""
    exam = is_exam_launch(claims)
    resource = claims.get(CLAIM_RESOURCE_LINK) or {}
    exam_title = (resource.get("title") if isinstance(resource, dict) else "") or ""

    if role == "student":
        sid = student_auth.derive_student_id(tenant, email or f"{sub}@lti.local")
        token = student_auth.mint_session(sid, name)
        result = {
            "role": "student", "tenant_id": tenant, "token": token,
            "token_key": "original_session_token",
        }
        if exam:
            result["redirect"] = "/bluebook/"
            result["extra"] = {"bluebook_student_id": sid, "original_tenant": tenant}
            result["params"] = {k: v for k, v in
                                {"exam": exam_title, "candidate": name}.items() if v}
        else:
            result["redirect"] = "student.html"
        return result

    uid = hashlib.sha256(f"{tenant}:{sub}".encode()).hexdigest()[:16]
    token = principal_mod.mint_principal_token(uid, role, tenant)
    result = {
        "role": role, "tenant_id": tenant, "token": token,
        "token_key": "original_principal_token",
    }
    if exam:
        result["redirect"] = "/bluebook/"
    else:
        result["redirect"] = "admin.html" if role == "admin" else "professor.html"
    return result
