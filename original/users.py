"""
users.py — staff (professor / admin / operator) email+password auth (ADR-003, Phase 1.x).

Students authenticate via stateless ``student_auth`` sessions; this module is
for institution staff who log in with a password. Hashing uses stdlib
PBKDF2-HMAC-SHA256 so the demo deployment needs no extra crypto dependency
(``requirements-demo.txt`` omits passlib/bcrypt).

Hash format: ``pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>``

On successful authentication the caller mints a principal token
(``principal.mint_principal_token``) carrying ``{user_id, role, tenant_id}`` —
the same token every auth method (email/password now, LTI later) terminates in.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from typing import Dict, Optional

from . import store

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 240_000
# A well-formed dummy hash used to keep auth timing ~constant for unknown emails.
_DUMMY_HASH = f"{_ALGO}${_ITERATIONS}${'00' * 16}${'00' * 32}"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != _ALGO:
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def _user_id(tenant_id: str, email: str) -> str:
    """Deterministic, tenant-scoped user id (stable across re-provisioning)."""
    return uuid.uuid5(
        uuid.NAMESPACE_URL, f"{tenant_id}:{email.strip().lower()}"
    ).hex[:16]


def create_user(
    email: str, password: str, role: str, tenant_id: str, name: str = ""
) -> Dict:
    uid = _user_id(tenant_id, email)
    store.put_user(uid, email, hash_password(password), role, tenant_id, name)
    return {
        "user_id": uid,
        "email": email.strip().lower(),
        "role": role,
        "tenant_id": tenant_id,
        "name": name,
    }


def authenticate(email: str, password: str) -> Optional[Dict]:
    """Return the user (minus password) on success, else None."""
    rec = store.get_user_by_email(email)
    if not rec:
        # Equalise timing so a missing email isn't distinguishable from a wrong
        # password (mitigates account enumeration).
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, rec["password_hash"]):
        return None
    return {k: rec[k] for k in ("user_id", "email", "role", "tenant_id", "name")}
