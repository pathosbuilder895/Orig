"""policy.py — the ONE consent policy for the university beta (2026-10).

Every decision about whether a student's writing may reach Original, and
whether a student may use Collections at all, is made here and nowhere else.
Routers never re-implement any part of it; they call:

* ``original_allowed(student_id, tenant_id=None, course_id=None) -> bool``
  — the Original gate. In a consent-regime tenant it is the conjunction of
  (1) the tenant holds the ``original`` product, (2) the teacher switched
  Original on for the course (``bluebook_courses.original_enabled``, default
  off), and (3) the student's own ``consistency`` consent is ``granted`` at
  the current document version. Outside a consent regime it returns True and
  leaves the existing product gate (api.py middleware) in charge, so the
  independent-teacher pilot behaves exactly as before.
* ``require_original(...)`` — the same gate, raising 403
  ``original_not_available`` (a distinct state from INCONCLUSIVE).
* ``filter_pool(states)`` — drops non-consenting students from any peer /
  cohort pool, so opted-out writing is never anyone's reference either.
* ``student_block_reason(tenant_id, student_id)`` — consulted by the
  tenant-isolation middleware for every student request, so new student
  routes are covered without touching them.
* ``require_agreement(tenant_id)`` — called inside ``invites.issue``, the one
  function every student invite path goes through.

A tenant is in the consent regime when ``meta.tenant_type == "university"``
or ``meta.consent_required`` is true. No IP address or user agent is stored
anywhere in this module; consent rows are append-only.

The document texts below are PLACEHOLDERS: "DRAFT — pending counsel review".
Bump a scope's ``version`` when counsel's text lands; students then re-consent
to that scope only.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException

from .. import principal as principal_mod
from ..repository import get_repository

SCOPE_CLASS_USE = "class_use"
SCOPE_CONSISTENCY = "consistency"
SCOPE_AGE = "age"
SCOPES = (SCOPE_CLASS_USE, SCOPE_CONSISTENCY, SCOPE_AGE)

GRANTED, DECLINED, WITHDRAWN = "granted", "declined", "withdrawn"

DRAFT_BANNER = "DRAFT — pending counsel review"

# scope -> {version, title, body}. Placeholder wording, deliberately plain.
DOCUMENTS: dict[str, dict[str, str]] = {
    SCOPE_CLASS_USE: {
        "version": "2026-10-12-draft",
        "title": "Using Collections for this course",
        "body": (
            f"{DRAFT_BANNER}. Your instructor uses Original Collections to give and "
            "collect timed writing for this course. Your answers, the time you "
            "started and finished, and lockdown notices (such as leaving the exam "
            "window) are stored so your instructor can grade them. No keystrokes "
            "are recorded. If you say no, your instructor will arrange an "
            "alternative assignment with no penalty."
        ),
    },
    SCOPE_CONSISTENCY: {
        "version": "2026-10-12-draft",
        "title": "Writing-consistency feature (in testing)",
        "body": (
            f"{DRAFT_BANNER}. Optional. Original is a feature in testing that "
            "compares a new piece of your writing with earlier writing your "
            "instructor approved, as a conversation starter. It is off unless you "
            "and your instructor both turn it on. Saying no has no effect on your "
            "grade. You can withdraw at any time; your writing is then excluded "
            "and never used as a reference."
        ),
    },
    SCOPE_AGE: {
        "version": "2026-10-12-draft",
        "title": "Age",
        "body": f"{DRAFT_BANNER}. I confirm that I am 18 years of age or older.",
    },
}


def body_sha256(scope: str) -> str:
    return hashlib.sha256(DOCUMENTS[scope]["body"].encode()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ── Regime ────────────────────────────────────────────────────────────────────


def consent_regime(tenant_id: str | None) -> bool:
    """Whether student consent governs this tenant (university beta)."""
    if not tenant_id or tenant_id == principal_mod.DEMO_TENANT:
        return False
    rec = get_repository().get_tenant(tenant_id)
    meta = (rec or {}).get("meta") or {}
    # POST /tenants caps meta values to strings, so accept "true" as well.
    flag = meta.get("consent_required")
    return meta.get("tenant_type") == "university" or flag is True or flag in ("true", "1")


# ── Student status ────────────────────────────────────────────────────────────


def latest(tenant_id: str, student_id: str) -> dict[str, dict]:
    """scope -> newest record for this student."""
    out: dict[str, dict] = {}
    for r in get_repository().list_consent_records(tenant_id, student_id):
        out[r["scope"]] = r  # list is oldest-first, so the last one wins
    return out


def status(tenant_id: str, student_id: str) -> dict:
    cur = latest(tenant_id, student_id)
    needs = [
        s
        for s in SCOPES
        if s not in cur
        or cur[s]["doc_version"] != DOCUMENTS[s]["version"]
        # A withdrawal is an answer: the student is not asked again for it.
        and not (s in cur and cur[s]["decision"] == WITHDRAWN and s != SCOPE_AGE)
    ]
    age = cur.get(SCOPE_AGE)
    cls = cur.get(SCOPE_CLASS_USE)
    con = cur.get(SCOPE_CONSISTENCY)
    return {
        "needs": needs,
        "age_blocked": bool(age and age["decision"] != GRANTED),
        "alternative_assignment": bool(cls and cls["decision"] != GRANTED),
        "original_consent": bool(
            con
            and con["decision"] == GRANTED
            and con["doc_version"] == DOCUMENTS[SCOPE_CONSISTENCY]["version"]
        ),
        "scopes": {
            s: {"decision": r["decision"], "version": r["doc_version"], "at": r["created_at"]}
            for s, r in cur.items()
        },
    }


def student_block_reason(tenant_id: str | None, student_id: str) -> str | None:
    """Why this student may not use Collections right now, or None.

    ``age_blocked`` > ``consent_required`` > ``alternative_assignment``."""
    if not consent_regime(tenant_id):
        return None
    st = status(tenant_id, student_id)
    if st["age_blocked"]:
        return "age_blocked"
    if SCOPE_AGE in st["needs"] or SCOPE_CLASS_USE in st["needs"]:
        return "consent_required"
    if st["alternative_assignment"]:
        return "alternative_assignment"
    return None


BLOCK_MESSAGES = {
    "age_blocked": "Collections is for students 18 or older. Please talk to your instructor.",
    "consent_required": "Please review and answer the consent screen first.",
    "alternative_assignment": (
        "You chose not to use Collections. Your instructor will arrange an alternative."
    ),
}


# ── The Original gate ─────────────────────────────────────────────────────────


def _course_enabled(tenant_id: str, student_id: str, course_id: str | None) -> bool:
    repo = get_repository()
    if course_id:
        ids = [course_id]
    else:
        ids = [e["course_id"] for e in repo.list_enrollments_for_student(student_id)]
    for cid in ids:
        c = repo.get_bluebook_course(cid)
        if c and c.get("tenant_id") == tenant_id and c.get("original_enabled"):
            return True
    return False


def original_allowed(
    student_id: str, tenant_id: str | None = None, course_id: str | None = None
) -> bool:
    """THE Original gate. See module docstring."""
    tenant = tenant_id or principal_mod.tenant_of(student_id)
    if not consent_regime(tenant):
        return True
    if "original" not in principal_mod.tenant_products(tenant):
        return False
    if not _course_enabled(tenant, student_id, course_id):
        return False
    return status(tenant, student_id)["original_consent"]


NOT_AVAILABLE = {
    "code": "original_not_available",
    "message": "Original is not available for this student.",
}


def require_original(
    student_id: str, tenant_id: str | None = None, course_id: str | None = None
) -> None:
    if not original_allowed(student_id, tenant_id, course_id):
        raise HTTPException(status_code=403, detail=NOT_AVAILABLE)


def filter_pool(states: list) -> list:
    """Drop every state whose student may not feed Original (peer pools)."""
    regime: dict[str | None, bool] = {}
    out = []
    for st in states:
        sid = getattr(st, "student_id", "")
        t = principal_mod.tenant_of(sid)
        if t not in regime:
            regime[t] = consent_regime(t)
        if not regime[t] or original_allowed(sid, t):
            out.append(st)
    return out


# ── Writes ────────────────────────────────────────────────────────────────────


def _append(tenant_id, student_id, scope, decision, typed_name="", course_id=None) -> dict:
    rec = {
        "record_id": uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "student_id": student_id,
        "course_id": course_id,
        "scope": scope,
        "decision": decision,
        "doc_version": DOCUMENTS[scope]["version"],
        "body_sha256": body_sha256(scope),
        "typed_name": typed_name,
        "age_attested": scope == SCOPE_AGE and decision == GRANTED,
        "created_at": _now(),
    }
    repo = get_repository()
    repo.append_consent_record(rec)
    action = {GRANTED: "consent_grant", DECLINED: "consent_decline"}.get(
        decision, "consent_withdraw"
    )
    repo.log_audit(
        action=action,
        tenant_id=tenant_id,
        student_id=student_id,
        actor=student_id,
        details={"scope": scope, "version": rec["doc_version"]},
    )
    return rec


def names_match(typed: str, roster: str) -> bool:
    norm = lambda s: " ".join((s or "").split()).casefold()  # noqa: E731
    return bool(norm(typed)) and (not norm(roster) or norm(typed) == norm(roster))


def record_decisions(
    tenant_id: str,
    student_id: str,
    *,
    typed_name: str,
    over_18: bool,
    class_use: bool,
    consistency: bool = False,
) -> dict:
    """Record the consent screen. Unanswered optional scopes default to off.
    Only scopes whose current version is not yet answered are written."""
    st = status(tenant_id, student_id)
    needs = set(st["needs"])
    if SCOPE_AGE in needs:
        _append(tenant_id, student_id, SCOPE_AGE, GRANTED if over_18 else DECLINED, typed_name)
        if not over_18:
            return status(tenant_id, student_id)
    elif st["age_blocked"]:
        return st

    def _write(scope: str, want: bool) -> None:
        cur = st["scopes"].get(scope, {}).get("decision")
        # Answer an unanswered scope, or let a student opt back in later.
        if scope in needs or (want and cur != GRANTED):
            _append(tenant_id, student_id, scope, GRANTED if want else DECLINED, typed_name)

    _write(SCOPE_CLASS_USE, class_use)
    _write(SCOPE_CONSISTENCY, bool(consistency and class_use))
    return status(tenant_id, student_id)


def withdraw(tenant_id: str, student_id: str, scope: str) -> dict:
    """Withdraw a scope (D8 default: exclude). Withdrawing ``consistency``
    zeroes the auth weight of every baseline sample, so none is ever a
    reference again (a thin baseline then reads INCONCLUSIVE through the
    existing path); the samples are kept, marked, not deleted. Withdrawing
    ``class_use`` sets the alternative-assignment flag and also withdraws
    ``consistency``."""
    _append(tenant_id, student_id, scope, WITHDRAWN)
    if scope == SCOPE_CLASS_USE:
        cur = latest(tenant_id, student_id).get(SCOPE_CONSISTENCY)
        if cur and cur["decision"] == GRANTED:
            _append(tenant_id, student_id, SCOPE_CONSISTENCY, WITHDRAWN)
    exclude_baseline(student_id)
    return status(tenant_id, student_id)


def exclude_baseline(student_id: str) -> int:
    """Mark every contributing baseline sample excluded (auth_weight 0)."""
    repo = get_repository()
    state = repo.get(student_id)
    if state is None:
        return 0
    n = 0
    stamp = _now()
    for s in state.samples:
        if s.auth_weight > 0:
            s.auth_weight = 0.0
            s.context_manifest = {**(s.context_manifest or {}), "consent_excluded_at": stamp}
            n += 1
    if n:
        state._rho = state._purity = state._trajectory = state._loo_distances = None
        repo.put(state)
    return n


# ── Pilot agreement ───────────────────────────────────────────────────────────


def current_agreement(tenant_id: str) -> dict | None:
    rows = [a for a in get_repository().list_pilot_agreements(tenant_id) if not a["superseded_at"]]
    return rows[-1] if rows else None


AGREEMENT_REQUIRED = {
    "code": "agreement_required",
    "message": "Your department's pilot agreement isn't on file yet.",
}


def require_agreement(tenant_id: str) -> None:
    """Student invites in a consent-regime tenant need an agreement on file."""
    if consent_regime(tenant_id) and current_agreement(tenant_id) is None:
        raise HTTPException(status_code=409, detail=AGREEMENT_REQUIRED)


def record_agreement(tenant_id: str, recorded_by: str, **fields) -> dict:
    rec = {
        "agreement_id": uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "recorded_by": recorded_by,
        "recorded_at": _now(),
        **fields,
    }
    repo = get_repository()
    repo.put_pilot_agreement(rec)
    repo.log_audit(
        action="pilot_agreement_recorded",
        tenant_id=tenant_id,
        actor=recorded_by,
        details={"doc_version": rec["doc_version"], "agreement_id": rec["agreement_id"]},
    )
    return rec
