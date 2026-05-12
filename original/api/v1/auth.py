"""
api/v1/auth.py — Authentication endpoints.

Handles login, token refresh, logout, and user profile retrieval.
"""

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from original.auth.jwt import create_access_token, create_refresh_token, decode_token
from original.auth.password import verify_password
from original.core.config import get_settings
from original.core.exceptions import AuthError
from original.core.limiter import limiter
from original.api.deps import get_current_user
from original.db.models import RefreshToken, User
from original.db.session import get_db
from original.schemas_v1.auth import (
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _as_utc_aware(dt: datetime) -> datetime:
    """SQLite returns naive datetimes; Postgres may return aware. Normalize for comparisons."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@router.post("/login", response_model=TokenResponse, status_code=status.HTTP_200_OK, summary="Login", responses={401: {"description": "Invalid credentials"}, 429: {"description": "Rate limit exceeded (5/minute)"}})
@limiter.limit("5/minute")
def login(
    request: Request,
    body: LoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """
    Authenticate a user and issue tokens.

    Args:
        request: HTTP request (used by rate limiter)
        body: Login credentials
        db: Database session

    Returns:
        TokenResponse with access and refresh tokens

    Raises:
        AuthError: If credentials are invalid
    """
    # Look up user by email
    user = db.query(User).filter(User.email == body.email).first()
    if not user:
        raise AuthError(detail="Invalid email or password")

    # Verify password
    if not verify_password(body.password, user.hashed_password):
        raise AuthError(detail="Invalid email or password")

    # Check if user is active
    if not user.is_active:
        raise AuthError(detail="User account is disabled")

    # Update last login
    user.last_login = datetime.now(timezone.utc)
    db.commit()

    # Create tokens
    access_token = create_access_token(user)
    refresh_token, token_hash = create_refresh_token(user)

    # Store refresh token hash in database
    settings = get_settings()
    refresh_expires = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )

    db_token = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=refresh_expires,
    )
    db.add(db_token)
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh access token",
    responses={401: {"description": "Refresh token invalid or revoked"}},
)
def refresh_access_token(
    request: RefreshRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """
    Refresh an access token using a refresh token.

    Args:
        request: Refresh token
        db: Database session

    Returns:
        TokenResponse with new access token

    Raises:
        AuthError: If refresh token is invalid or expired
    """
    # Decode the refresh token
    try:
        token_data = decode_token(request.refresh_token)
    except AuthError:
        raise AuthError(detail="Invalid refresh token")

    # Verify token type
    if token_data.token_type != "refresh":
        raise AuthError(detail="Invalid token type")

    token_hash = hashlib.sha256(request.refresh_token.encode()).hexdigest()

    # Check if token exists and is valid
    db_token = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == token_hash)
        .first()
    )

    if not db_token:
        raise AuthError(detail="Refresh token not found")

    if db_token.revoked:
        raise AuthError(detail="Refresh token has been revoked")

    if _as_utc_aware(db_token.expires_at) < datetime.now(timezone.utc):
        raise AuthError(detail="Refresh token has expired")

    # Load the user
    user = db.query(User).filter(User.id == token_data.sub).first()
    if not user or not user.is_active:
        raise AuthError(detail="User not found or inactive")

    # Create new access token
    access_token = create_access_token(user)

    settings = get_settings()
    return TokenResponse(
        access_token=access_token,
        refresh_token=request.refresh_token,  # Return same refresh token
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Logout (revoke session)")
def logout(
    body: RefreshRequest,
    db: Session = Depends(get_db),
) -> None:
    """
    Revoke a refresh token (sign out this session).

    Send the same **refresh_token** returned from `/login` or `/refresh`.
    Idempotent: unknown or already-revoked tokens still return 204.
    """
    token_hash = hashlib.sha256(body.refresh_token.encode()).hexdigest()
    db_token = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == token_hash)
        .first()
    )
    if db_token and not db_token.revoked:
        db_token.revoked = True
        db_token.revoked_at = datetime.now(timezone.utc)
        db.commit()


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout all sessions",
    responses={401: {"description": "Bearer token required"}},
)
def logout_all(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Revoke **all** refresh tokens for the authenticated user (sign out everywhere).

    Requires a valid **access** token in `Authorization: Bearer ...`.
    """
    now = datetime.now(timezone.utc)
    tokens = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked == False,  # noqa: E712
        )
        .all()
    )
    for t in tokens:
        t.revoked = True
        t.revoked_at = now
    if tokens:
        db.commit()


@router.get("/me", response_model=UserResponse, status_code=status.HTTP_200_OK)
def get_current_user_info(user: User = Depends(get_current_user)) -> UserResponse:
    """Return the authenticated user's profile."""
    return UserResponse.model_validate(user)
