"""
canvas/lti.py — LTI 1.3 OIDC routes for Canvas integration.

Implements the full LTI 1.3 OpenID Connect (OIDC) launch flow:

  1. GET/POST /lti/login      — OIDC initiation (Canvas → tool)
     Tool generates state/nonce, redirects to Canvas authorization endpoint.

  2. POST     /lti/launch     — OIDC callback (Canvas → tool)
     Tool validates the id_token JWT, extracts LTI claims, dispatches to
     resource-link launch or Deep Linking handler.

  3. GET      /lti/jwks       — Public JWKS (Canvas fetches this to verify tool JWTs)

  4. POST     /lti/deep-link  — Deep Linking response
     Tool builds and signs an LtiDeepLinkingResponse JWT that registers
     Original as a Document Processor for the chosen Canvas assignment.

  5. GET      /lti/config     — Tool configuration JSON
     JSON document Canvas admins can paste into Developer Keys → LTI.

Canvas LTI 1.3 reference:
  https://canvas.instructure.com/doc/api/file.lti_dev_key_config.html
  https://www.imsglobal.org/spec/lti/v1p3
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jose import JWTError, jwt as jose_jwt
from sqlalchemy.orm import Session

from original.canvas.keys import get_jwks, get_kid, sign_jwt
from original.core.config import get_settings
from original.core.logging import get_logger
from original.db.session import SessionLocal
from original.db.models.canvas import LTIRegistration, LTINonce

log = get_logger(__name__)
router = APIRouter(prefix="/lti", tags=["Canvas LTI"])

# LTI 1.3 claim namespaces
_NS = "https://purl.imsglobal.org/spec/lti/claim"
_DL_NS = "https://purl.imsglobal.org/spec/lti-dl/claim"
_MSG_RESOURCE = f"{_NS}/message_type"
_MSG_DEEP = "LtiDeepLinkingRequest"
_MSG_LAUNCH = "LtiResourceLinkRequest"

# ── LTI context dataclass (normalised across platforms) ───────────────────────
from dataclasses import dataclass, field as dc_field


@dataclass
class LTIContext:
    """
    Platform-agnostic LTI 1.3 context extracted from a validated id_token.

    _parse_claims() normalises Canvas and Blackboard claim differences into
    this structure so downstream code is platform-independent.
    """
    iss: str
    sub: str                        # user identifier on the platform
    platform_type: str              # "canvas" | "blackboard" | "generic"
    message_type: str               # "LtiResourceLinkRequest" | "LtiDeepLinkingRequest"
    context_id: str                 # course/context identifier
    context_label: str = ""
    context_title: str = ""
    roles: list = dc_field(default_factory=list)
    deployment_id: str = ""
    resource_link_id: str = ""
    deep_linking_settings: dict = dc_field(default_factory=dict)
    custom: dict = dc_field(default_factory=dict)
    raw_claims: dict = dc_field(default_factory=dict)


def _parse_claims(claims: dict, registration: "LTIRegistration") -> LTIContext:
    """
    Normalise LTI 1.3 id_token claims from Canvas or Blackboard into LTIContext.

    Canvas differences vs Blackboard:
      - Canvas: iss is per-instance (e.g. https://seminary.instructure.com)
      - Blackboard: iss is always https://blackboard.com (global)
      - Canvas: context claim uses "id" key
      - Blackboard: context claim also uses "id" — same as Canvas (IMS standard)
      - Both use the same roles claim path
    """
    platform_type = getattr(registration, "platform_type", "canvas") or "canvas"
    iss = claims.get("iss", "")

    # Detect platform from iss if not set on registration
    if not platform_type or platform_type == "generic":
        if "blackboard.com" in iss or "anthology.com" in iss:
            platform_type = "blackboard"
        elif "instructure.com" in iss or "canvas" in iss.lower():
            platform_type = "canvas"
        else:
            platform_type = "generic"

    context = claims.get(f"{_NS}/context", {}) or {}
    # Both Canvas and Blackboard use "id" in the context claim (IMS standard)
    context_id = context.get("id", "")

    roles = claims.get(f"https://purl.imsglobal.org/spec/lti/claim/roles", [])
    resource_link = claims.get(f"{_NS}/resource_link", {}) or {}
    dl_settings = claims.get(f"{_DL_NS}/deep_linking_settings", {}) or {}

    return LTIContext(
        iss=iss,
        sub=claims.get("sub", ""),
        platform_type=platform_type,
        message_type=claims.get(f"{_NS}/message_type", ""),
        context_id=context_id,
        context_label=context.get("label", ""),
        context_title=context.get("title", ""),
        roles=roles,
        deployment_id=claims.get(f"{_NS}/deployment_id", ""),
        resource_link_id=resource_link.get("id", ""),
        deep_linking_settings=dl_settings,
        custom=claims.get(f"{_NS}/custom", {}),
        raw_claims=claims,
    )


# ── JWKS endpoint ─────────────────────────────────────────────────────────────

@router.get("/jwks", summary="Public JWKS for Canvas JWT verification")
def jwks_endpoint():
    """Return the tool's RS256 public key set.  Canvas fetches this to verify JWTs."""
    return get_jwks()


# ── Tool configuration JSON ────────────────────────────────────────────────────

@router.get("/config", summary="LTI 1.3 tool configuration JSON")
def tool_config(request: Request):
    """
    Return the Canvas LTI 1.3 Developer Key configuration JSON.

    Paste this URL into Canvas Admin → Developer Keys → + LTI Key → Paste JSON.
    """
    settings = get_settings()
    base = str(request.base_url).rstrip("/")
    return {
        "title": "Original — Authorship Integrity",
        "description": (
            "Stylometric authorship verification for academic integrity. "
            "Returns two reports per submission: authorship deviation score "
            "and AI-writing signal, displayed in SpeedGrader."
        ),
        "oidc_initiation_url": f"{base}/lti/login",
        "target_link_uri": f"{base}/lti/launch",
        "public_jwk_url": f"{base}/lti/jwks",
        "scopes": [
            # Minimum necessary — read submission, post score
            "https://purl.imsglobal.org/spec/lti-ags/scope/score",
            "https://purl.imsglobal.org/spec/lti-ags/scope/result.readonly",
            "https://purl.imsglobal.org/spec/lti-nrps/scope/contextmembership.readonly",
        ],
        "extensions": [
            {
                "platform": "canvas.instructure.com",
                "settings": {
                    "platform": "canvas.instructure.com",
                    "privacy_level": settings.LTI_PRIVACY_LEVEL,
                    "placements": [
                        {
                            "placement": "assignment_configuration",
                            "message_type": "LtiDeepLinkingRequest",
                            "target_link_uri": f"{base}/lti/launch",
                        },
                        {
                            "placement": "course_navigation",
                            "message_type": "LtiResourceLinkRequest",
                            "target_link_uri": f"{base}/lti/launch",
                            "text": "Original Integrity",
                            "visibility": "admins",
                        },
                    ],
                },
            }
        ],
        "custom_fields": {},
    }


# ── OIDC Login (Step 1) ────────────────────────────────────────────────────────

@router.api_route(
    "/login",
    methods=["GET", "POST"],
    summary="LTI 1.3 OIDC initiation endpoint",
)
async def lti_login(
    request: Request,
    iss: Optional[str] = Query(None),
    login_hint: Optional[str] = Query(None),
    target_link_uri: Optional[str] = Query(None),
    lti_message_hint: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    lti_deployment_id: Optional[str] = Query(None),
):
    """
    Step 1 of LTI 1.3 OIDC launch.

    Canvas sends the user here first.  We generate a state nonce, store it,
    then redirect to Canvas's authorization endpoint.
    """
    # Support form POST as well as query string GET
    if request.method == "POST":
        form = await request.form()
        iss = iss or form.get("iss")
        login_hint = login_hint or form.get("login_hint")
        target_link_uri = target_link_uri or form.get("target_link_uri")
        lti_message_hint = lti_message_hint or form.get("lti_message_hint")
        client_id = client_id or form.get("client_id")
        lti_deployment_id = lti_deployment_id or form.get("lti_deployment_id")

    if not iss or not login_hint or not target_link_uri:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required OIDC params: iss, login_hint, target_link_uri",
        )

    # Look up registered platform
    db = SessionLocal()
    try:
        registration = _find_registration(db, iss, client_id, lti_deployment_id)
        if not registration:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unregistered LTI platform: {iss}. Register via admin → Canvas → LTI Registration.",
            )

        # Generate state and nonce
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)

        # Store nonce (expires in 10 minutes)
        _store_nonce(db, nonce, state, registration.id)

        # Build redirect to Canvas authorization endpoint
        params = {
            "scope": "openid",
            "response_type": "id_token",
            "client_id": registration.client_id,
            "redirect_uri": str(request.base_url).rstrip("/") + "/lti/launch",
            "login_hint": login_hint,
            "lti_message_hint": lti_message_hint or "",
            "state": state,
            "nonce": nonce,
            "response_mode": "form_post",
            "prompt": "none",
        }

        auth_url = f"{registration.auth_endpoint}?{urlencode(params)}"
        log.info("LTI OIDC login initiated", extra={"iss": iss, "client_id": client_id})
        return RedirectResponse(url=auth_url, status_code=302)
    finally:
        db.close()


# ── OIDC Launch callback (Step 2) ─────────────────────────────────────────────

@router.post("/launch", summary="LTI 1.3 OIDC launch callback")
async def lti_launch(
    request: Request,
    id_token: str = Form(...),
    state: str = Form(...),
):
    """
    Step 2 of LTI 1.3 OIDC launch.

    Canvas POSTs the signed id_token JWT here.  We:
      1. Decode the header to get 'kid' and 'iss'
      2. Look up the registration and fetch Canvas JWKS
      3. Validate the JWT signature and claims
      4. Consume the nonce (replay prevention)
      5. Dispatch to Deep Linking or resource link handler
    """
    db = SessionLocal()
    try:
        # Decode header without verification to get iss + kid
        try:
            header = jose_jwt.get_unverified_header(id_token)
            unverified = jose_jwt.get_unverified_claims(id_token)
        except JWTError as exc:
            raise HTTPException(400, f"Malformed id_token: {exc}")

        iss = unverified.get("iss")
        aud = unverified.get("aud")
        kid = header.get("kid")

        # Find registration
        client_id = aud if isinstance(aud, str) else (aud[0] if aud else None)
        registration = _find_registration(db, iss, client_id)
        if not registration:
            raise HTTPException(400, f"Unregistered platform: {iss}")

        # Fetch Canvas public JWKS and find matching key
        canvas_public_key = await _fetch_canvas_jwk(registration.jwks_url, kid)
        if not canvas_public_key:
            raise HTTPException(400, "Could not find matching key in Canvas JWKS")

        # Validate the JWT
        try:
            claims = jose_jwt.decode(
                id_token,
                canvas_public_key,
                algorithms=["RS256"],
                audience=registration.client_id,
                issuer=iss,
            )
        except JWTError as exc:
            raise HTTPException(400, f"JWT validation failed: {exc}")

        # Validate and consume nonce (replay prevention)
        nonce = claims.get("nonce")
        if not _consume_nonce(db, nonce, state, registration.id):
            raise HTTPException(400, "Invalid or expired nonce")

        # Dispatch based on message type
        message_type = claims.get(f"{_NS}/message_type", "")
        log.info(
            "LTI launch validated",
            extra={"message_type": message_type, "iss": iss},
        )

        if message_type == _MSG_DEEP:
            return _handle_deep_link_launch(claims, registration, request)
        else:
            return _handle_resource_link_launch(claims, registration, request)

    finally:
        db.close()


# ── Deep Linking response (Step 3 for Document Processor setup) ──────────────

@router.post("/deep-link", summary="Deep Linking content selection response")
async def deep_link_response(
    request: Request,
    deep_link_jwt: str = Form(...),
):
    """
    Instructor selects 'Original' as a document processor for this assignment.

    Receives the deep link settings from our own mini-form (posted from the
    deep-link selection page), builds an LtiDeepLinkingResponse JWT, and
    returns a self-submitting HTML form that posts back to Canvas.
    """
    db = SessionLocal()
    try:
        # Decode the deep link context JWT we issued at launch
        settings_ = get_settings()
        try:
            ctx = jose_jwt.decode(
                deep_link_jwt,
                settings_.SECRET_KEY,
                algorithms=["HS256"],
            )
        except JWTError as exc:
            raise HTTPException(400, f"Invalid deep link context: {exc}")

        registration = db.query(LTIRegistration).filter(
            LTIRegistration.id == ctx["registration_id"]
        ).first()
        if not registration:
            raise HTTPException(400, "Registration not found")

        now = int(time.time())
        # Build Deep Linking Response JWT
        dl_response = {
            "iss": ctx["client_id"],           # tool is now the issuer
            "aud": [ctx["iss"]],               # platform is the audience
            "iat": now,
            "exp": now + 600,
            "nonce": secrets.token_urlsafe(16),
            f"{_NS}/message_type": "LtiDeepLinkingResponse",
            f"{_NS}/version": "1.3.0",
            f"{_NS}/deployment_id": ctx["deployment_id"],
            f"{_DL_NS}/content_items": [
                {
                    "type": "ltiResourceLink",
                    "title": "Original — Authorship Integrity",
                    "url": str(request.base_url).rstrip("/") + "/lti/launch",
                    "custom": {
                        "canvas_assignment_id": "$Canvas.assignment.id",
                        "canvas_course_id": "$Canvas.course.id",
                        "canvas_user_id": "$Canvas.user.id",
                    },
                    # Document Processor attachment flag
                    "iframe": {"width": 0, "height": 0},
                }
            ],
            f"{_DL_NS}/return_url": ctx["return_url"],
        }

        signed = sign_jwt(dl_response)

        # Return a self-submitting form that posts the JWT back to Canvas
        return_url = ctx["return_url"]
        html = f"""<!DOCTYPE html>
<html><head><title>Connecting to Canvas...</title></head>
<body>
<p>Setting up Original in Canvas — please wait...</p>
<form id="f" action="{return_url}" method="POST">
  <input type="hidden" name="JWT" value="{signed}"/>
</form>
<script>document.getElementById('f').submit();</script>
</body></html>"""
        return HTMLResponse(content=html)
    finally:
        db.close()


# ── Canvas registration verification ─────────────────────────────────────────

@router.get(
    "/registrations/{registration_id}/verify",
    summary="Verify a Canvas LTI registration is working",
    tags=["Canvas LTI"],
)
async def verify_registration(registration_id: str):
    """
    Test a registered LTI platform by making a lightweight Canvas API call
    (fetch /api/v1/users/self).

    Returns {ok: true, canvas_user: {...}} on success or {ok: false, error: "..."}.
    Useful for admins to confirm a token is valid immediately after setup.
    """
    db = SessionLocal()
    try:
        registration = db.query(LTIRegistration).filter(
            LTIRegistration.id == registration_id,
        ).first()
        if not registration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Registration not found.",
            )
        if not registration.api_token:
            return JSONResponse({"ok": False, "error": "No API token configured on this registration."})

        # Derive Canvas base URL from platform_iss
        canvas_url = registration.platform_iss.rstrip("/")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{canvas_url}/api/v1/users/self",
                    headers={"Authorization": f"Bearer {registration.api_token}"},
                )
                resp.raise_for_status()
                canvas_user = resp.json()
        except httpx.HTTPStatusError as exc:
            return JSONResponse({
                "ok": False,
                "error": f"Canvas returned HTTP {exc.response.status_code}: {exc.response.text[:200]}",
            })
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)[:300]})

        return JSONResponse({
            "ok": True,
            "registration_id": registration.id,
            "platform_iss": registration.platform_iss,
            "canvas_user": {
                "id": canvas_user.get("id"),
                "name": canvas_user.get("name"),
                "email": canvas_user.get("email"),
            },
        })
    finally:
        db.close()


# ── Blackboard LTI 1.3 configuration JSON ─────────────────────────────────────

@router.get(
    "/blackboard/config",
    summary="Blackboard LTI 1.3 tool configuration JSON",
    tags=["Canvas LTI"],
)
def blackboard_tool_config(request: Request):
    """
    Return a Blackboard-specific LTI 1.3 tool configuration JSON.

    Blackboard uses a different JSON format than Canvas.
    Paste this URL into Blackboard: Administrator → LTI Tool Providers → Register by URL,
    or navigate to this endpoint and copy the JSON into Blackboard's manual registration.

    Reference: https://docs.anthology.com/docs/blackboard/lti/registration
    """
    settings = get_settings()
    base = str(request.base_url).rstrip("/")
    return {
        "name": "Original — Authorship Integrity",
        "description": (
            "Stylometric authorship verification for academic integrity. "
            "Original does not build AI training databases — it measures whether "
            "this submission matches this student's own authenticated writing voice."
        ),
        "oidc_initiation_url": f"{base}/lti/login",
        "target_link_uri": f"{base}/lti/launch",
        "public_jwk_url": f"{base}/lti/jwks",
        "extensions": {
            "blackboard.com": {
                "privacy_level": settings.LTI_PRIVACY_LEVEL,
                "placements": [
                    {
                        "placement": "course_tool",
                        "message_type": "LtiResourceLinkRequest",
                        "target_link_uri": f"{base}/lti/launch",
                        "label": "Original Integrity",
                    },
                    {
                        "placement": "base_navigation",
                        "message_type": "LtiDeepLinkingRequest",
                        "target_link_uri": f"{base}/lti/launch",
                        "label": "Attach Original",
                    },
                ],
            }
        },
        "scopes": [
            "https://purl.imsglobal.org/spec/lti-ags/scope/score",
            "https://purl.imsglobal.org/spec/lti-ags/scope/result.readonly",
            "https://purl.imsglobal.org/spec/lti-nrps/scope/contextmembership.readonly",
        ],
    }


# ── Blackboard AGS (Assignment and Grade Services) submission events ──────────

@router.post(
    "/ags/submissions",
    summary="Receive Blackboard AGS score/submission events",
    tags=["Canvas LTI"],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def blackboard_ags_submission(request: Request):
    """
    Handle Blackboard LTI Advantage AGS score submission events.

    Blackboard pushes score events to this endpoint via AGS rather than
    a separate webhook (unlike Canvas's Document Processor webhook).

    Payload reference:
      https://www.imsglobal.org/spec/lti-ags/v2p0

    The AGS Score payload contains:
      - userId: Blackboard user identifier (maps to student.external_id)
      - scoreGiven / scoreMaximum: grades (not used by Original for scoring)
      - comment: optional submission text if posted as comment
      - activityProgress / gradingProgress: pipeline status

    On receipt we acknowledge immediately (204) and queue async scoring.
    In this implementation we log the event and return — wire up your task
    queue (Celery, ARQ, etc.) here for production use.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    log.info(
        "Blackboard AGS submission event received",
        extra={
            "user_id": body.get("userId"),
            "timestamp": body.get("timestamp"),
            "activity_progress": body.get("activityProgress"),
        },
    )

    # TODO: queue async scoring task
    # Example:  await queue.enqueue("score_blackboard_submission", payload=body)

    return  # 204 No Content


# ── Internal helpers ──────────────────────────────────────────────────────────

def _find_registration(
    db: Session,
    iss: str,
    client_id: Optional[str] = None,
    deployment_id: Optional[str] = None,
) -> Optional[LTIRegistration]:
    q = db.query(LTIRegistration).filter(
        LTIRegistration.platform_iss == iss,
        LTIRegistration.is_active == True,
    )
    if client_id:
        q = q.filter(LTIRegistration.client_id == client_id)
    if deployment_id:
        q = q.filter(LTIRegistration.deployment_id == deployment_id)
    return q.first()


def _store_nonce(db: Session, nonce: str, state: str, registration_id: str) -> None:
    n = LTINonce(
        nonce=hashlib.sha256(nonce.encode()).hexdigest(),
        state=state,
        registration_id=registration_id,
        expires_at=int(time.time()) + 600,  # 10 minutes
    )
    db.add(n)
    db.commit()


def _consume_nonce(db: Session, nonce: str, state: str, registration_id: str) -> bool:
    """Return True and delete the nonce record if valid; False otherwise."""
    h = hashlib.sha256(nonce.encode()).hexdigest()
    record = db.query(LTINonce).filter(
        LTINonce.nonce == h,
        LTINonce.state == state,
        LTINonce.registration_id == registration_id,
    ).first()
    if not record:
        return False
    if record.expires_at < int(time.time()):
        db.delete(record)
        db.commit()
        return False
    db.delete(record)
    db.commit()
    return True


async def _fetch_canvas_jwk(jwks_url: str, kid: Optional[str]) -> Optional[Dict]:
    """Fetch Canvas platform JWKS and return the key matching kid."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(jwks_url)
            resp.raise_for_status()
            keys = resp.json().get("keys", [])
    except Exception as exc:
        log.error("Failed to fetch Canvas JWKS", extra={"url": jwks_url, "error": str(exc)})
        return None

    if kid:
        for key in keys:
            if key.get("kid") == kid:
                return key
    return keys[0] if keys else None


def _handle_deep_link_launch(
    claims: Dict,
    registration: LTIRegistration,
    request: Request,
) -> HTMLResponse:
    """Show the instructor a confirmation page before posting back to Canvas."""
    settings_ = get_settings()
    return_url = claims.get(f"{_DL_NS}/claim/deep_linking_settings", {}).get(
        "deep_link_return_url", ""
    )
    # Issue a short-lived context JWT our /lti/deep-link endpoint can verify
    ctx_jwt = jose_jwt.encode(
        {
            "registration_id": registration.id,
            "iss": claims["iss"],
            "client_id": registration.client_id,
            "deployment_id": claims.get(f"{_NS}/deployment_id", ""),
            "return_url": return_url,
            "exp": int(time.time()) + 300,
        },
        settings_.SECRET_KEY,
        algorithm="HS256",
    )
    base = str(request.base_url).rstrip("/")
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>Attach Original to this assignment</title>
  <style>
    body{{font-family:system-ui,sans-serif;max-width:520px;margin:4rem auto;padding:1rem;color:#1a1a1a;}}
    .card{{border:1px solid #ddd;border-radius:8px;padding:2rem;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,.08);}}
    h2{{margin-top:0;font-size:1.2rem;}}
    p{{color:#555;font-size:.9rem;line-height:1.6;}}
    .btn{{display:inline-block;background:#1e3d2f;color:#f7f3ea;padding:.65rem 1.4rem;border:none;border-radius:5px;font-size:.9rem;cursor:pointer;text-decoration:none;}}
    .btn:hover{{background:#243d30;}}
  </style>
</head>
<body>
  <div class="card">
    <h2>Attach Original to this assignment</h2>
    <p>Original will automatically analyse every student submission and return
    an <strong>Authorship Deviation</strong> report and an <strong>AI-Writing Signal</strong>
    report to SpeedGrader.</p>
    <p>No submission text is indexed into a global database. Reports are stored
    only within your institution's data policy settings.</p>
    <form action="{base}/lti/deep-link" method="POST">
      <input type="hidden" name="deep_link_jwt" value="{ctx_jwt}"/>
      <button type="submit" class="btn">Attach Original to this assignment</button>
    </form>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


def _handle_resource_link_launch(
    claims: Dict,
    registration: LTIRegistration,
    request: Request,
) -> RedirectResponse:
    """
    Standard resource link launch (e.g. course navigation placement).
    Redirect instructor to Original's dashboard.
    """
    base = str(request.base_url).rstrip("/")
    # In production, exchange for a short-lived token tied to the Canvas user context
    return RedirectResponse(url=f"{base}/original-dashboard.html", status_code=302)
