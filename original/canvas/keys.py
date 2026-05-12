"""
canvas/keys.py — RSA-256 key management for LTI 1.3.

LTI 1.3 requires RS256-signed JWTs.  This module generates and caches
an RSA key pair used to:
  - Sign Deep Linking response JWTs sent to Canvas
  - Expose a JWKS endpoint so Canvas can verify our signatures

Key persistence:
  Set LTI_PRIVATE_KEY_PEM in the environment (multi-line PEM, newlines
  replaced with \\n) to reuse the same key across container restarts.
  If absent, a new key is generated at startup (fine for single-instance
  development; set the env var for production).

Usage:
    from original.canvas.keys import get_jwks, sign_jwt
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from functools import lru_cache
from typing import Any, Dict

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from jose import jwt as jose_jwt


_KEY_SIZE = 2048


def _b64url(n: int) -> str:
    """Encode an integer as base64url (no padding), as required by JWK spec."""
    length = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode()


@lru_cache(maxsize=1)
def _load_key_pair():
    """
    Load or generate the RSA key pair.  Cached for the process lifetime.

    Returns:
        (private_key, kid, public_jwk_dict)
    """
    pem_env = os.environ.get("LTI_PRIVATE_KEY_PEM", "").replace("\\n", "\n").strip()

    if pem_env:
        private_key = serialization.load_pem_private_key(
            pem_env.encode(),
            password=None,
            backend=default_backend(),
        )
    else:
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=_KEY_SIZE,
            backend=default_backend(),
        )

    pub = private_key.public_key()
    pub_numbers = pub.public_numbers()

    # Derive a stable key ID from the public modulus
    kid = hashlib.sha256(str(pub_numbers.n).encode()).hexdigest()[:16]

    jwk: Dict[str, Any] = {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _b64url(pub_numbers.n),
        "e": _b64url(pub_numbers.e),
    }

    return private_key, kid, jwk


def get_private_key_pem() -> bytes:
    """Return the private key as PEM bytes (for jose signing)."""
    private_key, _, _ = _load_key_pair()
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )


def get_kid() -> str:
    """Return the key ID string."""
    _, kid, _ = _load_key_pair()
    return kid


def get_jwks() -> Dict[str, Any]:
    """Return the JWKS document (public key set) for the /lti/jwks endpoint."""
    _, _, jwk = _load_key_pair()
    return {"keys": [jwk]}


def sign_jwt(claims: Dict[str, Any]) -> str:
    """
    Sign a JWT with the tool's RS256 private key.

    Args:
        claims: JWT payload dict (must include 'iss', 'aud', 'exp', etc.)

    Returns:
        Compact serialized JWT string
    """
    _, kid, _ = _load_key_pair()
    return jose_jwt.encode(
        claims,
        get_private_key_pem(),
        algorithm="RS256",
        headers={"kid": kid},
    )


def export_public_key_pem() -> str:
    """Return the public key as PEM string (useful for Canvas registration)."""
    private_key, _, _ = _load_key_pair()
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
