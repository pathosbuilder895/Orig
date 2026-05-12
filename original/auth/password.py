"""
auth/password.py — Password hashing and validation.

Uses bcrypt for secure password hashing.
"""

from __future__ import annotations

import re

from passlib.context import CryptContext

# Bcrypt context for password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Password requirements
PASSWORD_REGEX = re.compile(
    r"^(?=.*[A-Z])(?=.*[a-z])(?=.*\d).{8,}$"
)


def hash_password(plain: str) -> str:
    """
    Hash a plain-text password using bcrypt.

    Args:
        plain: Plain-text password

    Returns:
        Hashed password
    """
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """
    Verify a plain-text password against a hash.

    Args:
        plain: Plain-text password
        hashed: Hashed password from the database

    Returns:
        True if password matches, False otherwise
    """
    return pwd_context.verify(plain, hashed)


def validate_password_strength(plain: str) -> None:
    """
    Validate password strength.

    Requires:
    - At least 8 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 digit

    Args:
        plain: Plain-text password

    Raises:
        ValueError: If password does not meet requirements
    """
    if not PASSWORD_REGEX.match(plain):
        raise ValueError(
            "Password must be at least 8 characters with 1 uppercase, "
            "1 lowercase, and 1 digit"
        )
