"""
student_auth.py — lightweight, stateless student authentication.

Two responsibilities:

1. **Identity derivation.** A student's id is derived deterministically from
   (institution, email): ``{tenant_slug}:{sha256(email)[:16]}``. This is
   FERPA-friendly (the email never appears in the id or in URLs — only an
   opaque hash), institution-scoped (two schools can both have
   jane@example.com without collision), and consistent with the multi-tenant
   ``{tenant_id}:{local_id}`` convention used for tenant scoping. The same
   formula is shared with the Bbook identity bridge.

2. **Sessions.** A signed, stateless session token: ``<payload>.<hmac>``,
   where payload is base64url(JSON{sid, name, exp}) and the signature is
   HMAC-SHA256 over the payload keyed by SECRET_KEY. No session table — the
   token verifies itself. Tamper or expiry → rejected.

This is the demo/pilot path. The v1 Postgres path uses full JWT (see
original/api/v1/auth.py); both can derive the same student id, so a student
provisioned in either system resolves identically.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from typing import Optional, Dict


_DEFAULT_TTL = 7 * 24 * 3600   # one week


def _secret() -> bytes:
    # Falls back to a fixed dev secret so the demo works without SECRET_KEY,
    # but the startup check warns when SECRET_KEY is unset (see api.py).
    return (os.environ.get("SECRET_KEY") or "demo-insecure-student-secret").encode()


def slugify(text: str) -> str:
    """Turn an institution name into a stable tenant slug."""
    s = (text or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "default"


def derive_student_id(institution: str, email: str) -> str:
    """
    Deterministic, institution-scoped, FERPA-friendly student id.

    Returns ``{tenant_slug}:{16-hex}`` — the prefix ties the student to a
    tenant (so list_ids_for_tenant / tenant_stats see them) and the hash
    hides the email.
    """
    tenant = slugify(institution)
    digest = hashlib.sha256(f"{tenant}:{(email or '').strip().lower()}".encode()).hexdigest()[:16]
    return f"{tenant}:{digest}"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(payload: str) -> str:
    return _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())


def mint_session(student_id: str, name: str = "", ttl_seconds: int = _DEFAULT_TTL) -> str:
    """Mint a signed session token for a student."""
    body = {"sid": student_id, "name": name, "exp": int(time.time()) + ttl_seconds}
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    return f"{payload}.{_sign(payload)}"


def verify_session(token: str) -> Optional[Dict]:
    """
    Return the session body {sid, name, exp} if the token is valid and
    unexpired, else None. Constant-time signature comparison.
    """
    if not token or "." not in token:
        return None
    payload, sig = token.split(".", 1)
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    try:
        body = json.loads(_unb64(payload))
    except Exception:
        return None
    if not isinstance(body, dict) or "sid" not in body:
        return None
    if float(body.get("exp", 0)) < time.time():
        return None
    return body
