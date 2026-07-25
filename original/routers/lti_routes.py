"""LTI 1.3 login / launch / JWKS endpoints, moved verbatim from original/api.py."""

from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from ._shared import _render_launch_localstorage, _repo

router = APIRouter()


# ── LTI 1.3 launch (ADR-003, Phase 1.5) ───────────────────────────────────────
# Lets an LMS (Canvas/Blackboard/Moodle) launch Original directly. The launch
# terminates in the same principal token as email/password login. Crypto deps
# are imported lazily, so the demo (which omits python-jose) still boots; the
# endpoints return a clear error until LTI is configured.


@router.api_route("/lti/login", methods=["GET", "POST"])
async def lti_login(request: Request):
    from .. import lti

    params = dict(request.query_params)
    if request.method == "POST":
        form = await request.form()
        params.update({k: str(v) for k, v in form.items()})
    try:
        url = lti.build_login_redirect(params)
    except lti.LtiError as e:
        raise HTTPException(status_code=400, detail=f"LTI login error: {e}") from e
    return RedirectResponse(url, status_code=302)


@router.post("/lti/launch")
async def lti_launch(request: Request):
    from .. import lti

    form = await request.form()
    id_token = str(form.get("id_token", ""))
    state = str(form.get("state", ""))
    if not id_token or not state:
        raise HTTPException(status_code=400, detail="missing id_token or state")
    try:
        claims = lti.verify_launch(id_token, state)
    except lti.LtiError as e:
        raise HTTPException(status_code=401, detail=f"LTI launch rejected: {e}") from e
    except ImportError as exc:
        raise HTTPException(
            status_code=501,
            detail="LTI requires python-jose, which is not installed in this deployment.",
        ) from exc
    p = lti.principal_from_claims(claims)
    _repo().log_audit(
        action="lti_launch",
        tenant_id=p["tenant_id"],
        actor=str(claims.get("sub", "")),
        result="ok",
        details={"role": p["role"], "redirect": p.get("redirect")},
    )
    # All localStorage keys the destination needs (token + identity + any binding).
    ls = {
        p["token_key"]: p["token"],
        "original_role": p["role"],
        "original_tenant": p["tenant_id"],
    }
    ls.update(p.get("extra") or {})
    redirect = p.get("redirect") or "professor.html"
    params = p.get("params") or {}
    if params and redirect.endswith("/"):
        redirect = redirect + "?" + urllib.parse.urlencode(params)
    return _render_launch_localstorage(ls, redirect)


@router.get("/lti/jwks")
def lti_jwks():
    from .. import lti

    return lti.public_jwks()
