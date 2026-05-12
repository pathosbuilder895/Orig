"""
auth/jwt.py — JWT token creation and verification.

Uses python-jose for JWT handling.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from jose import JWTError, jwt

from original.core.config import get_settings
from original.core.exceptions import AuthError
from original.db.models import User

TokenType = Literal["access", "refresh"]


@dataclass
class TokenData:
    """Decoded JWT token data."""

    sub: str  # user_id
    role: str
    institution_id: str
    token_type: TokenType
    jti: str  # JWT ID (unique identifier)
    exp: int  # expiration timestamp
    iat: int  # issued-at timestamp


def create_access_token(user: User) -> str:
    """
    Create a short-lived access token.

    Args:
        user: User object

    Returns:
        Encoded JWT token
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    data = {
        "sub": user.id,
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "institution_id": user.institution_id,
        "token_type": "access",
        "jti": user.id,  # Simplified JTI
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
    }

    token = jwt.encode(
        data,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    return token


def create_refresh_token(user: User) -> tuple[str, str]:
    """
    Create a long-lived refresh token.

    Args:
        user: User object

    Returns:
        Tuple of (raw_token, token_hash)
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    data = {
        "sub": user.id,
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "institution_id": user.institution_id,
        "token_type": "refresh",
        "jti": str(uuid.uuid4()),
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
    }

    raw_token = jwt.encode(
        data,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

    # Hash the token for storage in the database
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    return raw_token, token_hash


def decode_token(token: str) -> TokenData:
    """
    Decode and validate a JWT token.

    Args:
        token: Encoded JWT token

    Returns:
        Decoded token data

    Raises:
        AuthError: If token is invalid or expired
    """
    settings = get_settings()

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
    except JWTError as e:
        raise AuthError(detail="Invalid or expired token", error_code="invalid_token")

    return TokenData(
        sub=payload.get("sub"),
        role=payload.get("role"),
        institution_id=payload.get("institution_id"),
        token_type=payload.get("token_type"),
        jti=payload.get("jti"),
        exp=payload.get("exp"),
        iat=payload.get("iat"),
    )
