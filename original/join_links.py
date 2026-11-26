"""join_links.py — forwardable course sign-up links (Bluebook self-serve, 2026-10).

A per-email invite (``invites.py``) belongs to one student and works once.
A join link belongs to a course: anyone who opens it can create their own
student account (name, email, password, consent) and land on that course.
The teacher turns it on, copies it, turns it off, or replaces it; it is off
until they turn it on and has no expiry.

Storage follows the invite rule: the database keeps only the sha256 of the
token, so a leaked database cannot be used to join a course. So that the
teacher can see and copy the same link again later, the token is not random
but derived from the row's ``link_id`` with an HMAC keyed by ``SECRET_KEY``
(the same signing secret sessions use). Rotating ``SECRET_KEY`` therefore
breaks every join link; the teacher view reports that and the teacher gets
a new link with "Replace link".

One active link per course. Turning the link off, replacing it, or deleting
the course voids it, and a voided token never works again.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import uuid
from datetime import UTC, datetime

from .repository import get_repository

# The Bluebook SPA reads ?join= and shows its course sign-up screen.
JOIN_PATH = "/bluebook/?join="


def _secret() -> bytes:
    # Same secret and dev fallback as student_auth / principal.
    return (os.environ.get("SECRET_KEY") or "demo-insecure-student-secret").encode()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_for(link_id: str) -> str:
    digest = hmac.new(_secret(), f"bluebook-join-link|{link_id}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _view(link: dict | None) -> dict:
    """What the teacher sees. ``join_path`` is None when the link is off, or
    when the stored hash no longer matches (``SECRET_KEY`` changed)."""
    if not link:
        return {"enabled": False, "join_path": None, "created_at": None, "needs_replacing": False}
    token = token_for(link["link_id"])
    ok = hmac.compare_digest(token_hash(token), link["token_hash"])
    return {
        "enabled": True,
        "join_path": JOIN_PATH + token if ok else None,
        "created_at": link["created_at"],
        "needs_replacing": not ok,
    }


def current(course_id: str) -> dict:
    return _view(get_repository().active_join_link_for_course(course_id))


def _create(tenant_id: str, course_id: str, created_by: str) -> dict:
    link_id = uuid.uuid4().hex
    rec = {
        "link_id": link_id,
        "tenant_id": tenant_id,
        "course_id": course_id,
        "token_hash": token_hash(token_for(link_id)),
        "created_by": created_by,
        "created_at": datetime.now(UTC).isoformat(),
    }
    get_repository().put_join_link(rec)
    return rec


def enable(tenant_id: str, course_id: str, created_by: str) -> dict:
    """Turn the course's link on. Idempotent: an active link is kept (so a
    second click does not break a link already sent out)."""
    link = get_repository().active_join_link_for_course(course_id)
    if link and not _view(link)["needs_replacing"]:
        return _view(link)
    if link:
        get_repository().void_join_links_for_course(course_id)
    return _view(_create(tenant_id, course_id, created_by))


def regenerate(tenant_id: str, course_id: str, created_by: str) -> dict:
    """Void the current link and issue a new one."""
    get_repository().void_join_links_for_course(course_id)
    return _view(_create(tenant_id, course_id, created_by))


def disable(course_id: str) -> int:
    return get_repository().void_join_links_for_course(course_id)


def find_active(token: str) -> dict | None:
    """The active link ``token`` opens, or None for every failure (unknown,
    turned off, replaced) so the routes cannot be used to tell them apart."""
    token = (token or "").strip()
    if not token or len(token) > 128:
        return None
    link = get_repository().get_join_link_by_hash(token_hash(token))
    if not link or link.get("voided_at"):
        return None
    return link
