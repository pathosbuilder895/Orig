"""Operator-side professor onboarding for an invitation-only deploy.

With SELF_SERVE_SIGNUP=0 nobody can create a workspace from the website, so
the operator provisions each invited professor: a private Bluebook-only
workspace, an account that cannot sign in yet, and a one-time invite link the
professor redeems to choose their own password (the same /bluebook/?invite=
flow students use). The operator never sees or sets the password.

Running it again for a professor who has not set a password yet reissues the
link (same workspace; earlier links stop working). An activated account, or
an address that belongs to anyone other than a professor, is refused."""

from __future__ import annotations

import secrets

from . import invites, mailer, users
from .bluebook_rules import SELF_SERVE_PLAN
from .repository import get_repository

PROFESSOR_LINK_SUFFIX = "&terms=1"


def link_is_absolute(link: str) -> bool:
    """Only an absolute link can be clicked from an email. Without
    PUBLIC_BASE_URL or a base URL the link is a bare path."""
    return link.startswith(("https://", "http://"))


def _send_invite(user: dict, base_url: str, action: str) -> dict:
    """Issue (voiding any earlier link), email when possible, audit."""
    inv = invites.issue(user["tenant_id"], user["user_id"], "operator")
    # terms=1 tells the set-password screen to show the terms checkbox; the
    # server requires acceptance from an unactivated professor regardless.
    link = mailer.absolute_url(inv["invite_path"] + PROFESSOR_LINK_SUFFIX, base_url)
    emailed = bool(
        link_is_absolute(link)
        and mailer.configured()
        and mailer.send_professor_invite(user["email"], link)
    )
    get_repository().log_audit(
        action=action,
        tenant_id=user["tenant_id"],
        actor="operator",
        result="ok",
        details={"emailed": emailed},
    )
    return {
        "tenant_id": user["tenant_id"],
        "user_id": user["user_id"],
        "email": user["email"],
        "invite_link": link,
        "expires_at": inv["expires_at"],
        "emailed": emailed,
        "reissued": action == "professor_invite_reissue",
    }


def invite_professor(email: str, name: str = "", base_url: str = "") -> dict:
    normalized = (email or "").strip().lower()
    if not normalized or "@" not in normalized or len(normalized) > 254:
        raise ValueError("A valid email is required.")
    repo = get_repository()
    existing = repo.get_user_by_email(normalized)
    if existing:
        if existing.get("role") != "professor" or users.is_activated(existing):
            raise ValueError(f"An account with {normalized} already exists.")
        return _send_invite(existing, base_url, "professor_invite_reissue")
    display = (name or "").strip()[:200] or normalized.split("@")[0]
    tenant_id = f"t-{secrets.token_hex(6)}"
    repo.put_tenant(
        tenant_id,
        f"{display}'s workspace"[:200],
        environment="production",
        meta={"plan": SELF_SERVE_PLAN, "created_via": "operator_invite"},
    )
    repo.set_tenant_products(tenant_id, ["bluebook"])
    user_id = users._user_id(tenant_id, normalized)
    repo.put_user(user_id, normalized, users.INVITED_PASSWORD_HASH, "professor", tenant_id, display)
    user = {"user_id": user_id, "email": normalized, "tenant_id": tenant_id}
    return _send_invite(user, base_url, "professor_invite")
