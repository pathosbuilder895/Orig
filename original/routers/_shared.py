"""Module-level helpers and state shared by the routers.

Moved verbatim out of ``original/api.py`` (WS-7.3 router split) so the router
modules can use them without importing ``original.api`` — api.py imports the
routers, so the reverse edge would be circular. ``original.api`` re-imports
every name defined here, which keeps ``original.api.<helper>`` resolving for
the scripts and tests that reach for it.

The deploy-mode flags (``ORIGINAL_ENV``, ``_IS_REAL_DEPLOY``,
``_GUARD_DESTRUCTIVE``, ``_MAINTENANCE_TOKEN``) deliberately did NOT move: see
``_api()`` below.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import sqlite3

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import principal as principal_mod
from .. import student_auth
from ..repository import get_repository
from ..schemas import (
    AiIndicatorOut,
    AiLikelihoodOut,
    AuthorshipSignalOut,
    BaselineConfidenceOut,
    ContextManifestOut,
    DomainSignalOut,
    EntanglementAnomalyOut,
    FeatureContributionOut,
    InterferenceDecompositionOut,
    Layer7OutputResponse,
    RecommendedActionOut,
    ScoringReportOut,
    TensionArcOut,
    TrajectoryConformanceOut,
)


def _api():
    """The ``original.api`` module, resolved at call time (never at import).

    ``ORIGINAL_ENV`` / ``_IS_REAL_DEPLOY`` / ``_GUARD_DESTRUCTIVE`` /
    ``_MAINTENANCE_TOKEN`` stay defined in ``original/api.py`` because tests
    monkeypatch them *there* on the loaded module —
    ``tests/test_pilot_lockdown.py``, ``tests/test_baseline_provenance_authz.py``
    and ``tests/test_bluebook_crud.py`` all flip the app into pilot behaviour
    that way. Code that moved out of api.py therefore reads those four values
    through this accessor instead of binding a copy at import time, which would
    silently freeze them at their boot values and change behaviour. Everything
    else the routers need is a function or a shared mutable object, whose
    identity survives a plain re-import.
    """
    from original import api

    return api


def _repo():
    """The persistence Repository (ADR-002 seam; backend from REPO_BACKEND)."""
    return get_repository()


# Staff roles allowed to touch instructor-only write surfaces that carry no
# student id in the path (so the tenant-isolation middleware can't scope them).
_STAFF_ROLES = frozenset({"professor", "admin", "operator", "super_admin"})


def _require_staff(request: Request) -> principal_mod.Principal:
    """Return the request's principal iff it is a staff account, else raise.

    Students are rejected in every environment. The anonymous demo principal is
    accepted only off real deploys (the zero-login sales sandbox); on a real
    deploy it is rejected — the same rule the tenant-isolation middleware
    applies to the staff-only paths. Callers that also need tenant scoping
    should follow this with ``principal_mod.assert_student_access``.
    """
    p = getattr(request.state, "principal", None)
    if p is None or p.role == "student":
        raise HTTPException(status_code=403, detail="Staff role required.")
    if p.is_demo and _api()._IS_REAL_DEPLOY:
        raise HTTPException(
            status_code=401,
            detail="Authentication required — sign in with a staff account.",
        )
    if p.role not in _STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Staff role required.")
    return p


def _require_guard(request: Request) -> None:
    """
    Raise 403 if GUARD_DESTRUCTIVE is on and the request lacks the correct
    X-Guard-Token header.  Call at the top of any endpoint that should be
    protected in pilot/production but open in demo mode.

    Uses the module-level `_MAINTENANCE_TOKEN` (read once at startup) so
    the value is consistent across the request lifetime and avoids repeated
    os.environ lookups.
    """
    if not _api()._GUARD_DESTRUCTIVE:
        return
    if not _api()._MAINTENANCE_TOKEN:
        raise HTTPException(
            status_code=503,
            detail=(
                "GUARD_DESTRUCTIVE=1 is set but MAINTENANCE_TOKEN is empty. "
                "Set MAINTENANCE_TOKEN to a strong secret to use guarded endpoints."
            ),
        )
    token = request.headers.get("X-Guard-Token", "")
    if not hmac.compare_digest(token.encode(), _api()._MAINTENANCE_TOKEN.encode()):
        raise HTTPException(
            status_code=403,
            detail="Destructive operation requires a valid X-Guard-Token header.",
        )


def _persist_or_503(state: StudentState) -> None:  # noqa: F821 -- StudentState is lazily imported (see quantum/state.py) to avoid a heavy import at module load
    """store.put(), mapping a raised sqlite3.Error to 503 for the caller.

    The in-memory cache already holds `state` by the time store.put() raises
    (put() writes _STORE before _persist()) — the mutation is not rolled
    back, only the disk write is reported as failed. Not persisted; retry.
    """
    try:
        _repo().put(state)
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=503,
            detail="storage temporarily unavailable — change was not persisted, please retry",
        ) from exc


# ── Email notification stub ───────────────────────────────────────────────────


def _send_notification_email(student_name: str, action: str, score: float) -> None:
    """Stub for SendGrid email notification. Replace with real implementation."""
    import logging

    log = logging.getLogger(__name__)
    log.info(
        "EMAIL NOTIFICATION [stub] → action=%s student=%s score=%.3f — "
        "integrate SendGrid here: https://docs.sendgrid.com/api-reference/mail-send/mail-send",
        action,
        student_name,
        score,
    )
    # TODO: Replace with actual SendGrid call:
    # from sendgrid import SendGridAPIClient
    # from sendgrid.helpers.mail import Mail
    # sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
    # message = Mail(from_email='noreply@original.ai', to_emails=professor_email, ...)
    # sg.send(message)


# Login throttle: sliding-window per-IP limit so /auth/login is not freely
# brute-forceable in pilot deployments. In-memory (single-process uvicorn) and
# stdlib-only, matching the app's dependency posture. PBKDF2's ~100ms verify
# cost plus this window makes online guessing impractical.
#
# Overridable via env (defaults unchanged — same opt-in pattern as
# GUARD_DESTRUCTIVE/SECRET_KEY): a real E2E suite legitimately provisions many
# distinct tenants/staff logins per run (tenant-isolation coverage needs
# multiple real logins per test), which exceeds 10/300s at full-suite scale
# on a single shared IP — not brute-forcing, just parallel test fixtures.
# CI sets LOGIN_THROTTLE_MAX_ATTEMPTS higher for the e2e job only; pilot/
# production are untouched unless someone deliberately sets these.
_LOGIN_WINDOW_SEC = int(os.environ.get("LOGIN_THROTTLE_WINDOW_SEC", "300"))
_LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_THROTTLE_MAX_ATTEMPTS", "10"))
_login_attempts: dict = {}  # ip -> [monotonic timestamps]


def _throttle_login(request: Request) -> None:
    import time as _time

    ip = getattr(request.client, "host", "unknown") if request.client else "unknown"
    now = _time.monotonic()
    window = [t for t in _login_attempts.get(ip, []) if now - t < _LOGIN_WINDOW_SEC]
    if len(window) >= _LOGIN_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in attempts. Try again in a few minutes.",
        )
    window.append(now)
    _login_attempts[ip] = window
    if len(_login_attempts) > 10_000:  # bound memory under address churn
        _login_attempts.clear()


def _render_launch_localstorage(ls: dict, redirect: str) -> HTMLResponse:
    """Server-render a page that seeds ``ls`` into localStorage then redirects.

    Shared by the LTI launch and the Bluebook magic-link launch so the token is
    handed to the browser server-side (never left sitting in the destination
    URL) and the app boots with its session/binding already in place.
    """
    sets = "".join(f"localStorage.setItem({json.dumps(k)},{json.dumps(v)});" for k, v in ls.items())
    html = (
        "<!doctype html><meta charset=utf-8><title>Bluebook · Original</title>"
        '<body style="font-family:Inter,system-ui;background:#001020;color:#C9A961;'
        'display:flex;align-items:center;justify-content:center;height:100vh;margin:0">'
        "<div style=\"font-family:'Cormorant Garamond',Georgia,serif;font-size:1.3rem\">Entering examination…</div>"
        f"<script>try{{{sets}}}catch(e){{}}"
        f"var u={json.dumps(redirect)};try{{window.top.location.replace(u);}}catch(e){{location.replace(u);}}"
        "</script></body>"
    )
    return HTMLResponse(html)


_MAGIC_SESSION_TTL = 12 * 3600  # a single exam-day sitting, not a week


def _bluebook_tenant(request: Request) -> str:
    p = getattr(request.state, "principal", None)
    if p and not p.is_demo:
        return p.tenant_id
    return principal_mod.DEMO_TENANT


def _int_or(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _require_student_session(request: Request) -> dict:
    """Resolve the signed-in student from the session token, or 401."""
    auth = request.headers.get("Authorization", "")
    token = (
        auth[7:]
        if auth.lower().startswith("bearer ")
        else request.headers.get("X-Student-Token", "")
    )
    session = student_auth.verify_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return session


# Provenances that carry weight into the baseline_mean (auth_weight > 0). A
# student must not be able to self-assert any of these — that would let them
# inject ghostwritten/AI text as trusted "voice" and drag their own baseline
# toward the very thing the system should flag. 'unverified' (weight 0.5) is
# the only self-assertable provenance.
_TRUSTED_PROVENANCE = frozenset({"proctored", "verified", "canvas"})


def _authorize_provenance(
    request: Request | None, student_id: str, requested: str
) -> tuple[str, bool]:
    """Resolve the *effective* provenance for a baseline write.

    Trusted provenances must be attested; an unattested student write is
    downgraded (never rejected — the sample is still recorded, just at the
    self-upload trust level). Rules:

      • unverified / unknown        → unchanged.
      • in-process server call (request is None, e.g. seed scripts) → unchanged
                                       (server authority, no HTTP principal).
      • authenticated staff principal → unchanged (professor/admin/operator/super).
      • anonymous demo principal    → unchanged OFF a real deploy (the zero-login
                                       sandbox); on a real deploy it is not
                                       authenticated, so it gets no trust and
                                       falls through to the attestation rule —
                                       same posture as ``_require_staff``.
      • student with a valid proctor attestation (``X-Proctor-Attestation``,
        minted server-side at exam launch) for THIS student → unchanged.
      • otherwise (student, no attestation) → downgraded to 'unverified'.

    Returns ``(effective_provenance, was_downgraded)``.
    """
    if requested not in _TRUSTED_PROVENANCE or request is None:
        return requested, False
    p = getattr(request.state, "principal", None)
    if p is not None:
        if p.is_demo:
            # The anonymous principal carries a synthetic staff role
            # ("operator" by default, see principal.py), so it must be settled
            # here and never reach the _STAFF_ROLES rule below — otherwise
            # dropping the Authorization header would buy *more* trust than
            # sending a real student session.
            if not _api()._IS_REAL_DEPLOY:
                return requested, False
        elif p.role in _STAFF_ROLES:
            return requested, False
    attestation = request.headers.get("X-Proctor-Attestation", "")
    if attestation and student_auth.verify_proctor_attestation(attestation, student_id):
        return requested, False
    return "unverified", True


# ── Serialisation helper ──────────────────────────────────────────────────────


def _to_response(r, arc=None, report=None) -> Layer7OutputResponse:
    """Convert internal dataclasses → Pydantic response model."""
    from ..explainer import explain

    # Phase 6: ScoringReport → ScoringReportOut. Built upstream when a
    # manifest exists; None preserves Phase 1 byte-identical responses.
    report_out: ScoringReportOut | None = None
    if report is not None:
        report_out = ScoringReportOut(**report.to_dict())

    return Layer7OutputResponse(
        student_id=r.student_id,
        submission_id=r.submission_id,
        authorship=AuthorshipSignalOut(
            authorship_probability=r.authorship.authorship_probability,
            deviation_score=r.authorship.deviation_score,
            llr_deviation_score=r.authorship.llr_deviation_score,
        ),
        trajectory=TrajectoryConformanceOut(
            direction=r.trajectory.direction,
            alignment=r.trajectory.alignment,
            confidence=r.trajectory.confidence,
            adjustment_factor=r.trajectory.adjustment_factor,
        ),
        interference=InterferenceDecompositionOut(
            total_probability=r.interference.total_probability,
            constructive_features=[
                FeatureContributionOut(**fc.__dict__) for fc in r.interference.constructive_features
            ],
            destructive_features=[
                FeatureContributionOut(**fc.__dict__) for fc in r.interference.destructive_features
            ],
            broken_entanglements=[
                EntanglementAnomalyOut(
                    feature_a=e.feature_a,
                    feature_b=e.feature_b,
                    tier_a=e.tier_a,
                    tier_b=e.tier_b,
                    anomaly_score=e.anomaly_score,
                    label=e.label,
                )
                for e in r.interference.broken_entanglements
            ],
            tier_breakdown=r.interference.tier_breakdown,
        ),
        baseline_confidence=BaselineConfidenceOut(
            purity=r.baseline_confidence.purity,
            sample_count=r.baseline_confidence.sample_count,
            authenticated_count=r.baseline_confidence.authenticated_count,
            effective_sample_count=r.baseline_confidence.effective_sample_count,
            trajectory_confidence=r.baseline_confidence.trajectory_confidence,
            # Closes the WS-7 S9 completeness gap flagged on the schema field:
            # scoring.py has always computed this; it was dropped here.
            von_neumann_entropy=r.baseline_confidence.von_neumann_entropy,
        ),
        domain=DomainSignalOut(
            theological_register_score=r.domain.theological_register_score,
            register_anomaly=r.domain.register_anomaly,
            confessional_balance=r.domain.confessional_balance,
        ),
        recommendation=RecommendedActionOut(
            action=r.recommendation.action,
            confidence=r.recommendation.confidence,
            rationale=r.recommendation.rationale,
        ),
        tension_arc=TensionArcOut(
            catastrophe_index=arc.catastrophe_index,
            resolution_ratio_mean=arc.resolution_ratio_mean,
            resolution_ratio_std=arc.resolution_ratio_std,
            mean_tension=arc.mean_tension,
            max_tension=arc.max_tension,
            authenticity_signal=arc.authenticity_signal,
            arc_flag=arc.arc_flag,
            arc_flag_reason=arc.arc_flag_reason,
            tension_series=arc.tension_series,
        )
        if arc is not None
        else None,
        feature_vector=r.feature_vector,
        baseline_vector=r.baseline_vector,
        catastrophic_drift=getattr(r, "catastrophic_drift", False),
        catastrophic_drift_rms_z=getattr(r, "catastrophic_drift_rms_z", 0.0),
        # Phase 3: ContextManifestOut when CONTEXT_MANIFEST_ENABLED=1, else None.
        context_manifest=(
            ContextManifestOut(**getattr(r, "context_manifest", None))
            if getattr(r, "context_manifest", None) is not None
            else None
        ),
        # Phase 6: ScoringReportOut when a manifest+report were built.
        report=report_out,
        # AI-likelihood: AiLikelihoodOut when AI_LIKELIHOOD_ENABLED=1 and the
        # detector produced a signal, else None (byte-identical when off).
        ai_likelihood=(
            AiLikelihoodOut(
                probability=r.ai_likelihood.probability,
                band=r.ai_likelihood.band,
                model_version=r.ai_likelihood.model_version,
                trained_on=r.ai_likelihood.trained_on,
                top_indicators=[
                    AiIndicatorOut(**ind.__dict__) for ind in r.ai_likelihood.top_indicators
                ],
            )
            if getattr(r, "ai_likelihood", None) is not None
            else None
        ),
        # Human-friendly explanation for professors/instructors
        human_explanation=explain(r),
    )


def _audit_maintenance_access(username: str, remote: str) -> None:
    """Write a warning-level log entry for every maintenance login."""
    import datetime

    log = logging.getLogger(__name__)
    log.warning(
        "MAINTENANCE ACCESS: user=%r remote=%s at %s",
        username,
        remote,
        datetime.datetime.utcnow().isoformat() + "Z",
    )
