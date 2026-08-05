"""
canvas/live_import.py — Canvas Submissions API client for the live demo app.

Adapted from canvas/baseline_import.py (the v1 implementation) with the v1
dependencies removed: no SQLAlchemy session, no instructor JWT, no
pydantic-settings. Configuration comes from the request body with an
environment fallback (CANVAS_BASE_URL / CANVAS_API_TOKEN), and storage is the
caller's concern — this module only talks to Canvas and extracts text.

Used by the /canvas/baseline/{student_id}/* endpoints in original/api.py,
which replaced the old inert demo stubs. baseline_import.py stays untouched:
the dormant v1 app (original/main.py) and tests/test_canvas.py still use it.

Canvas Submissions API reference:
  https://canvas.instructure.com/doc/api/submissions.html
"""

from __future__ import annotations

import logging
import os

import httpx
from fastapi import HTTPException

from original.upload_utils import extract_text_from_bytes

log = logging.getLogger(__name__)

# Pinned by tests/test_canvas_live.py — the honest demo-mode guidance shown
# when no Canvas credentials are configured anywhere.
NO_CONFIG_GUIDANCE = (
    "Canvas integration requires a Canvas base URL and API token — set "
    "CANVAS_BASE_URL and CANVAS_API_TOKEN in the environment, or supply "
    "access_token in the request. Use the 'Drop files' or 'Paste text' "
    "options to add baselines manually."
)

# A submission must carry at least this many words to be usable as a baseline
# sample or analysis target (mirrors the v1 importer's floor).
MIN_WORDS = 50


def resolve_canvas_config(body_url: str | None, body_token: str | None) -> tuple[str, str]:
    """Resolve (canvas_url, access_token) from request body with env fallback.

    The two halves are resolved as a *pair*, not independently: CANVAS_API_TOKEN
    is a credential issued for CANVAS_BASE_URL, so it is only ever sent to that
    host. A request naming a different host must bring its own token — otherwise
    a caller-supplied ``canvas_url`` would redirect the institution's Canvas
    credential to any host it names.

    Raises HTTPException(400) with the pinned guidance text when either half
    is missing — the demo-honesty contract the old stub used to provide.
    """
    env_url = os.environ.get("CANVAS_BASE_URL", "").strip().rstrip("/")
    env_token = os.environ.get("CANVAS_API_TOKEN", "").strip()
    canvas_url = (body_url or env_url).strip().rstrip("/")
    body_token = (body_token or "").strip()

    if body_token:
        access_token = body_token
    elif canvas_url and canvas_url == env_url:
        access_token = env_token
    else:
        # A body-supplied host with no body-supplied token: the env token is not
        # ours to lend. Fall through to the guidance 400 rather than leak it.
        access_token = ""

    if not canvas_url or not access_token:
        raise HTTPException(status_code=400, detail=NO_CONFIG_GUIDANCE)
    return canvas_url, access_token


def make_client() -> httpx.AsyncClient:
    """Build the HTTP client. Single seam for tests to monkeypatch with a
    client backed by httpx.MockTransport — production behavior is one plain
    client with the same timeout the v1 importer used."""
    return httpx.AsyncClient(timeout=30.0)


async def fetch_submissions(
    client: httpx.AsyncClient,
    canvas_url: str,
    access_token: str,
    course_id: str,
    user_id: str,
    submission_ids: list[str] | None = None,
) -> list[dict]:
    """Fetch a student's submissions for a course, following Link-header
    pagination. With submission_ids, narrows to those submissions (the
    import path); without, lists text/upload submissions (the browse path).

    Canvas transport or HTTP errors surface as HTTPException(502).
    """
    list_url = f"{canvas_url}/api/v1/courses/{course_id}/students/submissions"
    params: dict = {
        "student_ids[]": user_id,
        "include[]": ["assignment", "attachments"],
        "per_page": 50,
    }
    if submission_ids:
        params["submission_ids[]"] = submission_ids
    else:
        params["submission_types[]"] = ["online_text_entry", "online_upload"]

    subs: list[dict] = []
    try:
        next_url: str | None = list_url
        while next_url:
            resp = await client.get(
                next_url,
                headers={"Authorization": f"Bearer {access_token}"},
                params=params if next_url == list_url else None,
            )
            resp.raise_for_status()
            subs.extend(resp.json())
            link_header = resp.headers.get("Link", "")
            next_url = None
            for part in link_header.split(","):
                if 'rel="next"' in part:
                    next_url = part.split(";")[0].strip().strip("<>")
                    break
    except httpx.HTTPError as exc:
        log.error("Failed to fetch Canvas submissions: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch submissions from Canvas: {exc}",
        ) from exc
    return subs


async def get_submission_text(
    sub: dict,
    access_token: str,
    client: httpx.AsyncClient,
) -> str | None:
    """Extract usable text from one Canvas submission object, or None.

    online_text_entry → the body verbatim; online_upload → download each
    attachment and extract via the shared upload_utils extractor until one
    yields >= MIN_WORDS words. Attachment failures are logged and skipped —
    a bad attachment must not fail a whole listing.
    """
    sub_type = sub.get("submission_type", "")

    if sub_type == "online_text_entry":
        body = sub.get("body") or ""
        return body if body.strip() else None

    if sub_type == "online_upload":
        for att in sub.get("attachments", []) or []:
            url = att.get("url") or att.get("preview_url") or ""
            name = att.get("display_name") or att.get("filename") or ""
            if not url:
                continue
            try:
                resp = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
                resp.raise_for_status()
                text = extract_text_from_bytes(resp.content, name)
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("Canvas attachment %s skipped: %s", name, exc)
                continue
            if text and len(text.split()) >= MIN_WORDS:
                return text

    return None


def assignment_name_of(sub: dict, fallback: str = "Unknown Assignment") -> str:
    """Human label for a submission's assignment, tolerating absent fields."""
    assignment = sub.get("assignment") or {}
    return assignment.get("name") or fallback
