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

_DEFAULT_TTL = 7 * 24 * 3600  # one week


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


def verify_session(token: str) -> dict | None:
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
    # A proctor attestation is signed with the same secret but is NOT a login
    # session — reject it here so it can only unlock a proctored baseline write,
    # never authenticate a request.
    if body.get("typ"):
        return None
    if float(body.get("exp", 0)) < time.time():
        return None
    return body


# ── Proctor attestation ───────────────────────────────────────────────────────
# A short-lived, signed grant that a *proctored* baseline write for a specific
# student is authorized. Minted server-side at exam launch (see lti.py) and
# presented by the exam client on POST /students/{id}/baseline. Because a bare
# student session token cannot forge it, a student cannot self-author
# high-trust (proctored/verified/canvas) samples into their own profile.

_PROCTOR_TTL = 6 * 3600  # one exam-day window


def mint_proctor_attestation(
    student_id: str, exam: str = "", ttl_seconds: int = _PROCTOR_TTL
) -> str:
    """Mint a signed proctor attestation authorizing one student's proctored
    baseline writes for a bounded window (issued at exam launch)."""
    body = {
        "typ": "proctor",
        "sid": student_id,
        "exam": exam,
        "exp": int(time.time()) + ttl_seconds,
    }
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    return f"{payload}.{_sign(payload)}"


def verify_proctor_attestation(token: str, student_id: str) -> bool:
    """True iff ``token`` is a valid, unexpired proctor attestation issued for
    exactly ``student_id``. Constant-time signature comparison."""
    if not token or "." not in token:
        return False
    payload, sig = token.split(".", 1)
    if not hmac.compare_digest(sig, _sign(payload)):
        return False
    try:
        body = json.loads(_unb64(payload))
    except Exception:
        return False
    if not isinstance(body, dict) or body.get("typ") != "proctor":
        return False
    if body.get("sid") != student_id:
        return False
    if float(body.get("exp", 0)) < time.time():
        return False
    return True


# ── Magic-link launch token ───────────────────────────────────────────────────
# A signed, self-contained launch credential the offline roster_links.py builds
# (one per student) for the no-Canvas fallback. Redeemed by GET /bluebook/launch,
# which trades it for a short session + a proctor attestation. Because it is
# signed, a student cannot forge a launch for an arbitrary id; because the real
# session/attestation are minted only at redemption, no long-lived bearer token
# is ever placed in the distributed URL.

_LAUNCH_TTL = 14 * 24 * 3600  # links are distributed, then used over the next days


def mint_launch_token(
    student_id: str,
    tenant: str,
    exam: str = "",
    name: str = "",
    ttl_seconds: int = _LAUNCH_TTL,
) -> str:
    """Mint a signed Bluebook magic-link launch token binding a student."""
    body = {
        "typ": "launch",
        "sid": student_id,
        "tid": tenant,
        "exam": exam,
        "name": name,
        "exp": int(time.time()) + ttl_seconds,
    }
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    return f"{payload}.{_sign(payload)}"


def verify_launch_token(token: str) -> dict | None:
    """Return the launch body ``{sid, tid, exam, name, exp}`` if valid and
    unexpired, else None. Constant-time signature comparison."""
    if not token or "." not in token:
        return None
    payload, sig = token.split(".", 1)
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    try:
        body = json.loads(_unb64(payload))
    except Exception:
        return None
    if not isinstance(body, dict) or body.get("typ") != "launch" or "sid" not in body:
        return None
    if float(body.get("exp", 0)) < time.time():
        return None
    return body
