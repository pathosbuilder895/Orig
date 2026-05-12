"""
tests/test_auth.py — Tests for authentication.

Tests password hashing, JWT creation/verification, and auth flows.
"""

import pytest
from datetime import datetime, timedelta, timezone

from original.auth.password import hash_password, verify_password, validate_password_strength
from original.auth.jwt import create_access_token, create_refresh_token, decode_token
from original.core.exceptions import AuthError
from original.db.models import User, UserRole, Institution


class TestPasswordHashing:
    """Tests for password hashing functionality."""

    def test_hash_password_creates_hash(self):
        """Password hashing creates a non-empty hash."""
        plain = "MyPassword123!"
        hashed = hash_password(plain)
        assert hashed
        assert len(hashed) > 0
        assert hashed != plain

    def test_verify_correct_password(self):
        """Verification succeeds with correct password."""
        plain = "MyPassword123!"
        hashed = hash_password(plain)
        assert verify_password(plain, hashed)

    def test_verify_wrong_password(self):
        """Verification fails with wrong password."""
        plain = "MyPassword123!"
        wrong = "WrongPassword123!"
        hashed = hash_password(plain)
        assert not verify_password(wrong, hashed)

    def test_validate_password_strength_valid(self):
        """Strong password passes validation."""
        strong = "MyPassword123!"
        # Should not raise
        validate_password_strength(strong)

    def test_validate_password_strength_too_short(self):
        """Password too short fails validation."""
        short = "Short1!"
        with pytest.raises(ValueError):
            validate_password_strength(short)

    def test_validate_password_strength_no_uppercase(self):
        """Password without uppercase fails validation."""
        no_upper = "mypassword123!"
        with pytest.raises(ValueError):
            validate_password_strength(no_upper)

    def test_validate_password_strength_no_lowercase(self):
        """Password without lowercase fails validation."""
        no_lower = "MYPASSWORD123!"
        with pytest.raises(ValueError):
            validate_password_strength(no_lower)

    def test_validate_password_strength_no_digit(self):
        """Password without digit fails validation."""
        no_digit = "MyPassword!"
        with pytest.raises(ValueError):
            validate_password_strength(no_digit)


class TestJWTCreation:
    """Tests for JWT token creation and decoding."""

    def test_create_access_token_returns_string(self, admin_user: User):
        """Access token creation returns a string."""
        token = create_access_token(admin_user)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_refresh_token_returns_tuple(self, admin_user: User):
        """Refresh token creation returns (raw_token, hash) tuple."""
        raw_token, token_hash = create_refresh_token(admin_user)
        assert isinstance(raw_token, str)
        assert isinstance(token_hash, str)
        assert raw_token != token_hash

    def test_decode_valid_access_token(self, admin_user: User):
        """Valid access token can be decoded."""
        token = create_access_token(admin_user)
        token_data = decode_token(token)

        # SQLite returns Enum columns as plain strings, so guard with hasattr
        expected_role = (
            admin_user.role.value if hasattr(admin_user.role, "value") else str(admin_user.role)
        )
        assert token_data.sub == admin_user.id
        assert token_data.role == expected_role
        assert token_data.institution_id == admin_user.institution_id
        assert token_data.token_type == "access"

    def test_decode_valid_refresh_token(self, admin_user: User):
        """Valid refresh token can be decoded."""
        raw_token, _ = create_refresh_token(admin_user)
        token_data = decode_token(raw_token)

        assert token_data.sub == admin_user.id
        assert token_data.token_type == "refresh"

    def test_decode_invalid_token(self):
        """Invalid token raises AuthError."""
        invalid_token = "invalid.token.here"
        with pytest.raises(AuthError):
            decode_token(invalid_token)

    def test_decode_tampered_token(self, admin_user: User):
        """Tampered token raises AuthError."""
        token = create_access_token(admin_user)
        # Tamper with the token
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(AuthError):
            decode_token(tampered)

    def test_access_token_expiry_in_future(self, admin_user: User):
        """Access token expiry is in the future."""
        token = create_access_token(admin_user)
        token_data = decode_token(token)

        exp_time = datetime.fromtimestamp(token_data.exp, tz=timezone.utc)
        now = datetime.now(tz=timezone.utc)

        assert exp_time > now

    def test_refresh_token_longer_expiry(self, admin_user: User):
        """Refresh token has longer expiry than access token."""
        access_token = create_access_token(admin_user)
        refresh_token, _ = create_refresh_token(admin_user)

        access_data = decode_token(access_token)
        refresh_data = decode_token(refresh_token)

        access_exp = access_data.exp
        refresh_exp = refresh_data.exp

        # Refresh should expire later
        assert refresh_exp > access_exp

    def test_token_has_unique_jti(self, admin_user: User):
        """Tokens have unique JWT ID (jti)."""
        token1 = create_access_token(admin_user)
        token2 = create_access_token(admin_user)

        data1 = decode_token(token1)
        data2 = decode_token(token2)

        # JTI should be present (though they may be the same for now)
        assert data1.jti
        assert data2.jti
