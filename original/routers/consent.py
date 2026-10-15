"""Student consent, the teacher consent roster, and pilot agreements
(university beta MVP, 2026-10).

Every rule lives in original/consent/policy.py; these handlers only parse,
authorise, and call it. Student routes take the student from the session,
never from the path. No IP address or user agent is read or stored.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .. import principal as principal_mod
from ..consent import policy as consent_policy
from ..schemas import ConsentSubmitRequest, ConsentWithdrawRequest, PilotAgreementRequest
from ._shared import _repo, _require_staff
from .bluebook import _owned_course
from .bluebook_accounts import _require_student

router = APIRouter()


def _documents() -> list[dict]:
    return [
        {
            "scope": scope,
            "version": doc["version"],
            "title": doc["title"],
            "body": doc["body"],
            "body_sha256": consent_policy.body_sha256(scope),
            "draft": True,
        }
        for scope, doc in consent_policy.DOCUMENTS.items()
    ]


def _view(p: principal_mod.Principal) -> dict:
    st = consent_policy.status(p.tenant_id, p.user_id)
    user = _repo().get_user(p.user_id) or {}
    return {
        "required": consent_policy.consent_regime(p.tenant_id),
        "roster_name": user.get("name") or "",
        "documents": _documents(),
        **st,
        "blocked": consent_policy.student_block_reason(p.tenant_id, p.user_id),
    }


@router.get("/bluebook/me/consent")
def my_consent(request: Request):
    """The consent documents, this student's answer per scope, and which
    scopes still need an answer at the current version."""
    return _view(_require_student(request))


@router.post("/bluebook/me/consent")
def submit_consent(body: ConsentSubmitRequest, request: Request):
    p = _require_student(request)
    user = _repo().get_user(p.user_id) or {}
    if not consent_policy.names_match(body.typed_name, user.get("name") or ""):
        raise HTTPException(
            status_code=422,
            detail="Type your full name as it appears on your course roster.",
        )
    consent_policy.record_decisions(
        p.tenant_id,
        p.user_id,
        typed_name=" ".join(body.typed_name.split()),
        over_18=body.over_18,
        class_use=body.class_use,
        consistency=body.consistency,
    )
    return _view(p)


@router.post("/bluebook/me/consent/withdraw")
def withdraw_consent(body: ConsentWithdrawRequest, request: Request):
    """Withdraw a scope now. Default and only MVP mode: exclude (D8)."""
    p = _require_student(request)
    consent_policy.withdraw(p.tenant_id, p.user_id, body.scope)
    return _view(p)


@router.get("/bluebook/courses/{course_id}/consent")
def course_consent_roster(course_id: str, request: Request):
    """Teacher roster: per student, class use, Original on/off, version,
    date, and the alternative-assignment flag. Typed names are not shown and
    the declined scope is never named beyond "Original off"."""
    _require_staff(request)
    course = _owned_course(course_id, request)
    tenant = course["tenant_id"]
    ids = [e["student_id"] for e in _repo().list_enrollments_for_course(course_id)]
    users = {u["user_id"]: u for u in _repo().list_users_by_ids(ids)}
    rows = []
    for sid in ids:
        st = consent_policy.status(tenant, sid)
        cls = st["scopes"].get(consent_policy.SCOPE_CLASS_USE)
        rows.append(
            {
                "student_id": sid,
                "name": (users.get(sid) or {}).get("name") or "",
                "class_use": cls["decision"] if cls else "pending",
                "original": "on"
                if consent_policy.original_allowed(sid, tenant, course_id)
                else "off",
                "alternative_assignment": st["alternative_assignment"] or st["age_blocked"],
                "version": cls["version"] if cls else None,
                "answered_at": cls["at"] if cls else None,
            }
        )
    return {
        "course_id": course_id,
        "consent_required": consent_policy.consent_regime(tenant),
        "original_enabled": bool(course.get("original_enabled")),
        "students": rows,
    }


def _require_operator(request: Request) -> principal_mod.Principal:
    p = _require_staff(request)
    if not p.is_demo and p.role not in principal_mod.SUPER_ROLES:
        raise HTTPException(status_code=403, detail="Operator role required.")
    return p


@router.post("/tenants/{tenant_id}/agreements", status_code=201)
def record_agreement(tenant_id: str, body: PilotAgreementRequest, request: Request):
    """Record a school/department pilot agreement signed offline (D11)."""
    p = _require_operator(request)
    if _repo().get_tenant(tenant_id) is None:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found")
    return consent_policy.record_agreement(tenant_id, p.user_id, **body.model_dump())


@router.get("/tenants/{tenant_id}/agreements")
def list_agreements(tenant_id: str, request: Request):
    p = _require_staff(request)
    if p.role not in principal_mod.SUPER_ROLES and p.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required.")
    try:
        principal_mod.assert_tenant_access(p, tenant_id)
    except principal_mod.TenantAccessError:
        raise HTTPException(status_code=403, detail="Cross-tenant access denied.") from None
    return {
        "agreements": _repo().list_pilot_agreements(tenant_id),
        "current": consent_policy.current_agreement(tenant_id),
    }
