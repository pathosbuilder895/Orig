"""
tests/security/test_ssrf.py — "make the server fetch my URL."

docs/testing/04-security-adversarial.md §1.4. Canvas import
(`original/routers/imports.py:list_canvas_submissions`) accepts a
body-supplied ``canvas_url`` — ``original.canvas.live_import.resolve_canvas_config``
only requires that a body token accompany a body host (see
tests/test_canvas_live.py::test_body_url_does_not_borrow_env_token and
::test_env_configured_host_still_uses_env_token for that credential-pairing
behaviour; not duplicated here). It does not validate that the host is
public, so a staff caller can point the server at localhost, an RFC-1918
address, the cloud metadata endpoint, or a ``file://`` URI and the server
will make the request.

Reuses the ``two_tenants`` fixture (tests/security/conftest.py) for
provisioning; per this task's setup, requests target tenant A's baselined
student with tenant A's staff headers.
"""

from __future__ import annotations

import httpx
import pytest

from original.canvas import live_import

pytestmark = pytest.mark.security

ATTACKER_URLS = [
    "http://localhost:8001",
    "http://127.0.0.1",
    "http://169.254.169.254/latest/meta-data",
    "http://10.0.0.1",
    "http://192.168.1.1",
    "http://[::1]",
    "file:///etc/passwd",
]


def _body(canvas_url: str) -> dict:
    return {
        "canvas_url": canvas_url,
        "access_token": "t",
        "canvas_course_id": "1",
        "canvas_user_id": "2",
    }


def _recording_transport() -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    return httpx.MockTransport(handler), seen


@pytest.mark.blocker
@pytest.mark.parametrize("attacker_url", ATTACKER_URLS)
def test_canvas_import_refuses_private_and_local_urls(
    two_tenants, live_client, monkeypatch, attacker_url
):
    """T-05: Canvas import fetches caller-supplied private/loopback/metadata URLs (SSRF).

    The server does not validate ``canvas_url``'s host before dialing it, so
    a staff caller can direct the outbound request at localhost, an
    RFC-1918 address, the cloud metadata IP, or a ``file://`` URI. A fixed
    server would 4xx here *before* touching the transport — this asserts
    both the status and that the mocked transport was never invoked, so a
    red result here means the host really was contacted, not just that some
    other check happened to reject it first.
    """
    transport, seen = _recording_transport()
    monkeypatch.setattr(
        live_import,
        "make_client",
        lambda: httpx.AsyncClient(transport=transport, timeout=5.0),
    )

    try:
        r = live_client.post(
            f"/canvas/baseline/{two_tenants['student_a']}/list-canvas-submissions",
            json=_body(attacker_url),
            headers=two_tenants["headers_a"],
        )
        status, body_text = r.status_code, r.text
    except Exception as exc:
        # A file:// body URL currently crashes the client downstream of the
        # transport call rather than surfacing a clean HTTP response — but
        # by then the mocked transport has already recorded the request, so
        # the assertion below still names the hole precisely.
        status, body_text = None, f"<unhandled exception before a response: {exc!r}>"

    # This must be the assertion that fails: the recorded-request list is
    # the direct witness that the server dialed the attacker-supplied host
    # before (if ever) rejecting it, not an inference from status alone.
    assert seen == [], (
        f"server contacted {attacker_url!r} — recorded requests: "
        f"{[str(req.url) for req in seen]}"
    )
    assert status is not None and 400 <= status < 500, (
        f"expected a 4xx refusal for {attacker_url!r}, got {status!r}: {body_text}"
    )


def test_canvas_import_control_public_url_is_contacted(two_tenants, live_client, monkeypatch):
    """Green control: a public Canvas host IS reached through this seam.

    Proves the mocked transport is live and the endpoint really does dial
    out for an ordinary request — so an empty recorded-request list in the
    red cases above is evidence of a refusal, not a broken monkeypatch.
    """
    transport, seen = _recording_transport()
    monkeypatch.setattr(
        live_import,
        "make_client",
        lambda: httpx.AsyncClient(transport=transport, timeout=5.0),
    )

    r = live_client.post(
        f"/canvas/baseline/{two_tenants['student_a']}/list-canvas-submissions",
        json=_body("https://canvas.example.edu"),
        headers=two_tenants["headers_a"],
    )
    assert r.status_code == 200, r.text
    assert seen, "expected the public host to be contacted"
    assert seen[0].url.host == "canvas.example.edu"
