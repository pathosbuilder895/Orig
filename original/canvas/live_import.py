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

import ipaddress
import logging
import os
import socket
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from original.upload_utils import extract_text_from_bytes

log = logging.getLogger(__name__)

# Exact local DNS names rejected by _reject_non_public_host, regardless of
# their apparent public-suffix. "ip6-localhost" is the /etc/hosts alias for
# ::1 on many Linux distros.
_LOCAL_HOSTNAMES = {"localhost", "ip6-localhost"}
# Suffixes rejected the same way: any name ending in one of these is a local
# name by convention (RFC 6762 for .local; .localhost is the reserved TLD
# from RFC 2606 that browsers already special-case).
_LOCAL_HOSTNAME_SUFFIXES = (".localhost", ".local")

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


def _reject_non_public_host(canvas_url: str) -> None:
    """SSRF guard: refuse a ``canvas_url`` whose host is not a plausible
    public Canvas instance, before any client is constructed or request made.

    Rejects:
      - any scheme other than http/https (e.g. ``file://``, which has no
        meaningful "host" to dial at all);
      - a URL with no parseable hostname;
      - an IP literal — including legacy BSD-style numeric encodings
        (decimal, hex, octal, and shorthand a.b/a dotted forms, e.g.
        "2130706433", "0x7f000001", "017700000001", "127.1", "0xa.0.0.1" —
        none of these are valid input to ``ipaddress.ip_address``, but
        ``socket.inet_aton`` accepts them the same way the C library's
        numeric-address parsing historically has) — that is loopback,
        private (RFC 1918), link-local (this is what catches the
        169.254.169.254 cloud-metadata address), reserved, multicast, or
        unspecified;
      - the obvious local DNS names: exactly "localhost" or "ip6-localhost",
        or any name ending in ".localhost" or ".local".
    Anything else — an ordinary public DNS name — is allowed.

    Deliberately a literal, pre-resolution check: it decides name hosts from
    the name alone and never calls socket.getaddrinfo/gethostbyname, so the
    allow-path never depends on live DNS resolution (a public-looking name
    that doesn't resolve in this environment, e.g. in CI, must still be
    allowed) — inet_aton below is a local syntactic parse of numeric forms,
    not a network lookup, so this holds even for the numeric-encoding check.
    Residual, explicitly out of scope: a public DNS name that *resolves* to
    a private/loopback address (DNS rebinding, or an internal host given a
    public-looking name) is NOT caught by this check and would require
    validating the connected-to address at request time instead of the URL
    text. This closes the direct body-supplied IP/localhost/file vector
    (including its numeric-IPv4-encoding variants) only — it does not make
    Canvas import SSRF-proof.
    """
    parsed = urlparse(canvas_url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400,
            detail=f"Canvas URL must use http or https, not {parsed.scheme!r}.",
        )

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="Canvas URL has no host.")

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None
        try:
            # Not a strict dotted-quad/IPv6 literal -- but legacy numeric
            # IPv4 forms (decimal/hex/octal/shorthand-dotted) are also not
            # valid ipaddress.ip_address() input, and httpx/the stdlib
            # resolver will still dial them as an IP. inet_aton is a pure
            # string parse (no DNS query), so this never depends on network
            # access or live resolution -- it either accepts the numeric
            # syntax and hands back 4 packed bytes, or raises OSError for
            # anything that isn't a legacy-numeric IPv4 form (including
            # ordinary DNS names).
            packed = socket.inet_aton(hostname)
        except OSError:
            packed = None
        if packed is not None:
            ip = ipaddress.ip_address(packed)

    if ip is not None:
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise HTTPException(
                status_code=400,
                detail="Canvas URL may not target a private, loopback, or link-local address.",
            )
    elif hostname in _LOCAL_HOSTNAMES or hostname.endswith(_LOCAL_HOSTNAME_SUFFIXES):
        raise HTTPException(
            status_code=400,
            detail="Canvas URL may not target a local hostname.",
        )


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

    # SSRF guard (T-05): applied to the resolved host regardless of whether
    # it came from the request body or CANVAS_BASE_URL — see live_import.py
    # module docs / CLAUDE.md for why the env-configured-host carve-out
    # wasn't needed: no committed test configures a private env host.
    _reject_non_public_host(canvas_url)

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
