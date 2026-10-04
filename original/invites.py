"""invites.py — one-time set-password links (Bluebook self-serve, 2026-09).

A teacher adding a student to a course, or an operator resetting a teacher,
issues an invite. The raw token appears only in the returned path; the
database keeps its sha256, so a leaked database cannot mint logins. Issuing
voids every earlier unredeemed invite for the same user. Redeeming checks the
hash, expiry, and single use, then sets the password.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from .repository import get_repository

INVITE_TTL = timedelta(days=14)
# The Bluebook SPA reads ?invite= and shows its set-password screen.
INVITE_PATH = "/bluebook/?invite="


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue(tenant_id: str, user_id: str, created_by: str, course_id: str | None = None) -> dict:
    """Void earlier invites for ``user_id`` and issue a fresh one. Returns
    ``{"invite_path", "expires_at", "invite_id"}``; the raw token lives only
    in ``invite_path``."""
    repo = get_repository()
    repo.void_invites_for_user(user_id)
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expires = now + INVITE_TTL
    invite_id = uuid.uuid4().hex
    repo.put_invite(
        {
            "invite_id": invite_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "course_id": course_id,
            "token_hash": token_hash(token),
            "created_by": created_by,
            "created_at": now.isoformat(),
            "expires_at": expires.isoformat(),
        }
    )
    return {
        "invite_path": INVITE_PATH + token,
        "expires_at": expires.isoformat(),
        "invite_id": invite_id,
    }


def redeem(token: str) -> dict | None:
    """Consume a valid invite. Returns the invite dict on success, else None
    for every failure (unknown, expired, voided, already used) — the caller
    reports them identically so the route cannot be used to probe tokens.
    The single-use update is atomic, so two concurrent redemptions of one
    token cannot both succeed."""
    if not token:
        return None
    repo = get_repository()
    inv = repo.get_invite_by_hash(token_hash(token))
    if not inv or inv.get("redeemed_at") or inv.get("voided_at"):
        return None
    expires = datetime.fromisoformat(str(inv["expires_at"]).replace("Z", "+00:00"))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= datetime.now(UTC):
        return None
    if not repo.redeem_invite(inv["invite_id"]):
        return None
    return inv
