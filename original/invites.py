"""invites.py — one-time set-password links (Bluebook self-serve, 2026-09).

A teacher adding a student to a course, or an operator resetting a teacher,
issues an invite. The raw token appears only in the returned path; the
database keeps its sha256, so a leaked database cannot mint logins. Issuing
voids earlier unredeemed invites for the same user (see ``issue`` for which).
Redeeming checks the hash, expiry, and single use, then sets the password.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from .repository import get_repository

INVITE_TTL = timedelta(days=14)
# A link for an account that already has a password is a password reset. It
# lasts a day, whatever INVITE_NO_EXPIRY says: a reset link that waits in an
# inbox for weeks is a way into someone's account (T-79).
RESET_TTL = timedelta(hours=24)
# INVITE_NO_EXPIRY=1 (e.g. for a closed alpha) issues links that stay valid
# until they are used or revoked. Revoke a link by reissuing it (voids the
# old one), removing the student from the course, or deleting the tenant.
# Stored as a far-future timestamp so no schema or redeem change is needed.
NO_EXPIRY_AT = datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)


def no_expiry() -> bool:
    return os.environ.get("INVITE_NO_EXPIRY", "").strip().lower() in {"1", "true", "yes", "on"}


# The Bluebook SPA reads ?invite= and shows its set-password screen.
INVITE_PATH = "/bluebook/?invite="


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue(
    tenant_id: str,
    user_id: str,
    created_by: str,
    course_id: str | None = None,
    *,
    keep_other_courses: bool = False,
    reset: bool = False,
) -> dict:
    """Void earlier invites for ``user_id`` and issue a fresh one. Returns
    ``{"invite_path", "expires_at", "invite_id"}``; the raw token lives only
    in ``invite_path``.

    ``keep_other_courses`` is for a student who has not set a password yet:
    only earlier links for ``course_id`` are voided, so adding them to a
    second course leaves the first course's link working (T-78). Whichever
    link they use first voids the rest (``auth_invite_redeem``). Without it
    every earlier link is voided, as a password reset must.

    ``reset`` marks a link for an account that already has a password: it
    lasts ``RESET_TTL``."""
    repo = get_repository()
    repo.void_invites_for_user(user_id, course_id if keep_other_courses and course_id else None)
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    if reset:
        expires = now + RESET_TTL
    else:
        expires = NO_EXPIRY_AT if no_expiry() else now + INVITE_TTL
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


def find_redeemable(token: str) -> dict | None:
    """The invite ``token`` would redeem right now, without consuming it, or
    None for every failure (unknown, expired, voided, already used). Lets a
    caller refuse a request (e.g. terms not accepted) and leave the link
    usable."""
    if not token:
        return None
    inv = get_repository().get_invite_by_hash(token_hash(token))
    if not inv or inv.get("redeemed_at") or inv.get("voided_at"):
        return None
    expires = datetime.fromisoformat(str(inv["expires_at"]).replace("Z", "+00:00"))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= datetime.now(UTC):
        return None
    return inv


def redeem(token: str) -> dict | None:
    """Consume a valid invite. Returns the invite dict on success, else None
    for every failure (unknown, expired, voided, already used) — the caller
    reports them identically so the route cannot be used to probe tokens.
    The single-use update is atomic, so two concurrent redemptions of one
    token cannot both succeed."""
    inv = find_redeemable(token)
    if not inv or not get_repository().redeem_invite(inv["invite_id"]):
        return None
    return inv
