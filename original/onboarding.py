"""Operator-side professor onboarding for an invitation-only deploy.

With SELF_SERVE_SIGNUP=0 nobody can create a workspace from the website, so
the operator provisions each invited professor: a private Bluebook-only
workspace, an account that cannot sign in yet, and a one-time invite link the
professor redeems to choose their own password (the same /bluebook/?invite=
flow students use). The operator never sees or sets the password."""

from __future__ import annotations

import secrets

from . import invites, mailer, users
from .bluebook_rules import SELF_SERVE_PLAN
from .repository import get_repository


def invite_professor(email: str, name: str = "", base_url: str = "") -> dict:
    normalized = (email or "").strip().lower()
    if not normalized or "@" not in normalized or len(normalized) > 254:
        raise ValueError("A valid email is required.")
    repo = get_repository()
    if repo.get_user_by_email(normalized):
        raise ValueError(f"An account with {normalized} already exists.")
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
    inv = invites.issue(tenant_id, user_id, "operator")
    link = mailer.absolute_url(inv["invite_path"], base_url)
    emailed = bool(mailer.configured() and mailer.send_professor_invite(normalized, link))
    repo.log_audit(
        action="professor_invite",
        tenant_id=tenant_id,
        actor="operator",
        result="ok",
        details={"emailed": emailed},
    )
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "email": normalized,
        "invite_link": link,
        "expires_at": inv["expires_at"],
        "emailed": emailed,
    }
