"""Tenant (institution) registry, moved verbatim from original/api.py."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .. import principal as principal_mod
from .. import student_auth
from ..schemas import CreateTenantRequest, TenantProductsRequest
from ._shared import _repo, _require_guard, _require_staff

router = APIRouter()


def _validate_products(products) -> list[str]:
    cleaned = sorted({str(p).strip().lower() for p in products or []})
    if not cleaned or not set(cleaned) <= principal_mod.ALL_PRODUCTS:
        raise HTTPException(
            status_code=422,
            detail="products must be a non-empty subset of: bluebook, original",
        )
    return cleaned


# ── Tenant registry ───────────────────────────────────────────────────────────
# Phase 0 foundation: lightweight per-institution metadata stored in SQLite.
# Lets demo operator register schools with an environment label (demo/pilot/
# production) before Postgres multi-tenancy is needed.


@router.post("/tenants", status_code=201)
def create_tenant(body: CreateTenantRequest, request: Request):
    """
    Register or update a tenant (institution) record.

    Required body fields:
        tenant_id   — stable slug (e.g. 'seminary-of-dallas')
        name        — human-readable institution name

    Optional body fields:
        environment — 'demo' | 'pilot' | 'production'  (default: 'demo')
        meta        — arbitrary dict of metadata (contact email, LMS URL, etc.)
                      Capped at 10 keys, values must be strings ≤ 500 chars.

    When GUARD_DESTRUCTIVE=1, requires X-Guard-Token. Tenant writes are as
    sensitive as deletions: updating an existing pilot tenant's environment
    to 'demo' would make its student data anonymously readable.
    """
    _require_guard(request)
    tenant_id = body.tenant_id.strip()
    name = body.name.strip()
    if not tenant_id or not name:
        raise HTTPException(status_code=422, detail="tenant_id and name are required")
    # Student ids are derived as f"{slugify(tenant)}:{hash}", so a tenant id
    # that is not its own slug would put its students under a different
    # prefix than the tenant — outside its own isolation boundary.
    if student_auth.slugify(tenant_id) != tenant_id:
        raise HTTPException(
            status_code=422,
            detail="tenant_id must be a lowercase slug (letters, digits, hyphens)",
        )
    products = _validate_products(body.products) if body.products is not None else None
    if len(tenant_id) > 80 or len(name) > 200:
        raise HTTPException(status_code=422, detail="tenant_id max 80 chars, name max 200 chars")
    environment = body.environment
    if environment not in ("demo", "pilot", "production"):
        raise HTTPException(
            status_code=422, detail="environment must be 'demo', 'pilot', or 'production'"
        )
    # Never downgrade a real tenant to demo — demo tenants are anonymously
    # readable, so a downgrade silently exposes FERPA-protected records.
    # Recovering from a genuine mislabel is a deliberate operator action:
    # delete the tenant's students first, then re-register.
    existing = _repo().get_tenant(tenant_id)
    if (
        existing
        and existing.get("environment") in ("pilot", "production")
        and environment == "demo"
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Refusing to downgrade tenant '{tenant_id}' from "
                f"'{existing.get('environment')}' to 'demo' — demo tenants are "
                "anonymously readable. Delete the tenant's students first if "
                "this is intentional."
            ),
        )
    # Validate meta payload — prevents unbounded JSON storage
    meta = body.meta or {}
    if not isinstance(meta, dict):
        raise HTTPException(status_code=422, detail="meta must be a JSON object")
    if len(meta) > 10:
        raise HTTPException(status_code=422, detail="meta must have at most 10 keys")
    meta = {str(k)[:80]: str(v)[:500] for k, v in list(meta.items())[:10]}
    _repo().put_tenant(tenant_id, name, environment=environment, meta=meta)
    if products is not None:
        _repo().set_tenant_products(tenant_id, products)
    principal_mod.invalidate_tenant_cache()  # env may have changed → drop stale cache
    _repo().log_audit(
        action="tenant_register",
        tenant_id=tenant_id,
        details={"name": name, "environment": environment},
    )
    return {"tenant_id": tenant_id, "name": name, "environment": environment}


@router.get("/tenants")
def list_tenants(request: Request, environment: str = ""):
    """
    List all registered tenants, optionally filtered by environment.

    Staff-only (any role) — this intentionally stays cross-tenant-visible
    rather than scoped to SUPER_ROLES, matching the existing professor.html
    Settings-panel registry view that lists/registers institutions. It was
    previously reachable with NO auth check at all; this closes that gap
    without changing who can see it.
    """
    principal = _require_staff(request)
    tenants = _repo().list_tenants(environment=environment or None)
    # Self-serve (2026-09): any teacher can now sign up, so a cross-tenant
    # registry would list every other teacher's workspace. Only operators
    # (and the demo sandbox) see all tenants; everyone else sees their own.
    if principal.is_demo or principal.role in principal_mod.SUPER_ROLES:
        return tenants
    return [t for t in tenants if t.get("tenant_id") == principal.tenant_id]


@router.patch("/tenants/{tenant_id}")
def update_tenant_products(tenant_id: str, body: TenantProductsRequest, request: Request):
    """Change which products a tenant holds — the upgrade path from
    Bluebook-only to Bluebook + Original. Operator only, and guarded like
    POST /tenants: widening a tenant's products widens what it can reach."""
    _require_guard(request)
    principal = _require_staff(request)
    if not principal.is_demo and principal.role not in principal_mod.SUPER_ROLES:
        raise HTTPException(status_code=403, detail="Operator role required.")
    products = _validate_products(body.products)
    if not _repo().set_tenant_products(tenant_id, products):
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found")
    principal_mod.invalidate_tenant_cache()
    _repo().log_audit(
        action="tenant_products_update", tenant_id=tenant_id, details={"products": products}
    )
    return _repo().get_tenant(tenant_id)


@router.get("/tenants/{tenant_id}")
def get_tenant(tenant_id: str, request: Request):
    """Get a single tenant record. Cross-tenant reads require operator/super_admin."""
    principal = _require_staff(request)
    try:
        principal_mod.assert_tenant_access(principal, tenant_id)
    except principal_mod.TenantAccessError:
        raise HTTPException(status_code=403, detail="Cross-tenant access denied.") from None
    t = _repo().get_tenant(tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found")
    return t


@router.get("/tenants/{tenant_id}/stats")
def tenant_stats(tenant_id: str, request: Request):
    """
    Aggregate statistics for a tenant — student count, submission volume,
    action breakdown, last active timestamp.

    Used by the operator dashboard to show all-schools-at-a-glance (operator/
    super_admin principals are cross-tenant by design); any other staff role
    may only fetch stats for its own tenant.
    """
    principal = _require_staff(request)
    try:
        principal_mod.assert_tenant_access(principal, tenant_id)
    except principal_mod.TenantAccessError:
        raise HTTPException(status_code=403, detail="Cross-tenant access denied.") from None
    t = _repo().get_tenant(tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found")
    return _repo().tenant_stats(tenant_id)


@router.delete("/tenants/{tenant_id}/students", status_code=200)
def delete_tenant_students(tenant_id: str, request: Request):
    """
    FERPA-safe bulk deletion of all students belonging to a tenant.

    Iterates list_ids_for_tenant() plus the tenant's Bluebook-only students
    (no Original profile) and calls delete_student() for each — the same code
    path as individual deletion, so all linked records (fidelity scores,
    manifests, corrections, audit rows, Bluebook rows) are purged.

    Requires operator/super_admin — or, for any other staff role, that the
    caller's own tenant matches ``tenant_id`` — in addition to the existing
    X-Guard-Token requirement when GUARD_DESTRUCTIVE=1. Previously this was
    guarded ONLY by the shared guard token (a no-op when GUARD_DESTRUCTIVE is
    unset), so any staff principal could bulk-delete any other tenant's
    entire roster; this closes that gap.
    """
    principal = _require_staff(request)
    try:
        principal_mod.assert_tenant_access(principal, tenant_id)
    except principal_mod.TenantAccessError:
        raise HTTPException(status_code=403, detail="Cross-tenant access denied.") from None
    _require_guard(request)
    t = _repo().get_tenant(tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found")
    result = _repo().delete_tenant_students(tenant_id)
    # Bulk-erased every student in this tenant — bust the whole
    # CHARACTERISTIC_WEIGHTS=shadow pool cache (original/quantum/
    # impostor_cache.py) rather than each id individually; a full clear is
    # the module's own documented ops-path use of invalidate(None).
    from ..quantum import impostor_cache

    impostor_cache.invalidate(None)
    return {
        "tenant_id": tenant_id,
        "deleted_count": result["deleted_count"],
        "failed_ids": result["failed_ids"],
        "message": (
            f"Deleted {result['deleted_count']} student(s) from '{tenant_id}'. "
            + (f"Failed: {result['failed_ids']}" if result["failed_ids"] else "")
        ).strip(),
    }
