"""Operator-side professor onboarding for an invitation-only deploy.

With SELF_SERVE_SIGNUP=0 nobody can create a workspace from the website, so
the operator provisions each invited professor: a private Bluebook-only
workspace, an account that cannot sign in yet, and a one-time invite link the
professor redeems to choose their own password (the same /bluebook/?invite=
flow students use). The operator never sees or sets the password.

Running it again for a professor who has not set a password yet reissues the
link (same workspace; earlier links stop working). An activated account, or
an address that belongs to anyone other than a professor, is refused.

Original is off unless the operator asks for it: ``with_original`` on a fresh
invite, or ``set_original`` for an existing professor's workspace."""

from __future__ import annotations

import secrets

from . import invites, mailer, users
from . import principal as principal_mod
from .bluebook_rules import SELF_SERVE_PLAN
from .repository import get_repository

PROFESSOR_LINK_SUFFIX = "&terms=1"

# Tenants these created_via values mark are one professor's own workspace;
# anything else (an institution registered through POST /tenants) may hold
# many professors, all of whom a product switch affects.
_PRIVATE_WORKSPACE_ORIGINS = frozenset({"operator_invite", "signup"})

ORIGINAL_NOT_VALIDATED = (
    "Original's comparisons are not validated for real student work yet "
    "(gap T-01: frequent false alarms with few baseline samples). Use it only "
    "with the owner's agreement and the institution's consent."
)


def _stored_products(tenant_id: str) -> list[str]:
    """The tenant's stored products, sorted. A record with unset products holds
    every product. Callers pass a tenant that has a record (invitation creates
    it first), so a missing record is not answered the way the server's
    product gate answers it (principal.tenant_products: on a real deploy the
    last known products, else Bluebook alone; in the demo, every product)."""
    rec = get_repository().get_tenant(tenant_id)
    return sorted((rec or {}).get("products") or principal_mod.ALL_PRODUCTS)


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
        "products": _stored_products(user["tenant_id"]),
    }


def invite_professor(
    email: str, name: str = "", base_url: str = "", with_original: bool = False
) -> dict:
    """Invite a professor. A fresh workspace holds Bluebook, plus Original
    only when ``with_original``; a reissue never changes products."""
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
    repo.set_tenant_products(tenant_id, ["bluebook", "original"] if with_original else ["bluebook"])
    user_id = users._user_id(tenant_id, normalized)
    repo.put_user(user_id, normalized, users.INVITED_PASSWORD_HASH, "professor", tenant_id, display)
    user = {"user_id": user_id, "email": normalized, "tenant_id": tenant_id}
    return _send_invite(user, base_url, "professor_invite")


def set_original(email: str, enabled: bool) -> dict:
    """Switch Original on or off for the workspace a staff account belongs to.

    Writes (and audits) only when the products actually change, and clears
    this process's tenant cache. Another process (the web service, when this
    runs from Render's shell) picks the change up when its products cache
    expires (principal._PRODUCTS_CACHE_TTL_SECONDS)."""
    normalized = (email or "").strip().lower()
    repo = get_repository()
    user = repo.get_user_by_email(normalized) if normalized else None
    if not user:
        raise ValueError(f"No account with {normalized or email}.")
    if user.get("role") == "student":
        raise ValueError(
            f"{normalized} is a student account. Original is switched per professor "
            "workspace; use the professor's email."
        )
    tenant_id = user["tenant_id"]
    rec = repo.get_tenant(tenant_id)
    if not rec:
        raise ValueError(f"The workspace {tenant_id} for {normalized} is not registered.")
    before = sorted(rec.get("products") or principal_mod.ALL_PRODUCTS)
    after = set(before) | {"original"} if enabled else set(before) - {"original"}
    products = sorted(after)
    if not products:
        raise ValueError("That would leave the workspace with no products.")
    changed = products != before
    if changed:
        if not repo.set_tenant_products(tenant_id, products):
            raise ValueError(f"The workspace {tenant_id} for {normalized} is not registered.")
        principal_mod.invalidate_tenant_cache()
        repo.log_audit(
            action="tenant_products_update",
            tenant_id=tenant_id,
            actor="operator",
            details={"products": products, "via": "set_products"},
        )
    return {
        "tenant_id": tenant_id,
        "tenant_name": rec.get("name") or "",
        "email": normalized,
        "before": before,
        "products": products,
        "changed": changed,
        "shared_workspace": (rec.get("meta") or {}).get("created_via")
        not in _PRIVATE_WORKSPACE_ORIGINS,
    }
