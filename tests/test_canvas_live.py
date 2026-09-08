"""
tests/test_canvas_live.py — the live app's real Canvas import endpoints
(original/api.py + original/canvas/live_import.py), which replaced the old
inert demo stubs.

No network: Canvas is faked with httpx.MockTransport, injected through the
live_import.make_client() seam. Covers pagination, text-entry vs file-upload
extraction, the min-50-words floor, preview shape, already_imported flip,
provenance/auth-weight on imported samples, SHA-256 dedup, the
fetch-submission-text analyze path, the pinned no-config 400 guidance, and
Canvas failures surfacing as 502.

(The dormant v1 implementation keeps its own suite in tests/test_canvas.py.)
"""

from __future__ import annotations

import httpx
import pytest

from original import principal as pr
from original.canvas import live_import
from original.constants import AUTH_WEIGHTS

CANVAS_URL = "https://canvas.test"
TOKEN = "canvas-token"
COURSE = "C1"
USER = "U7"

# The three Canvas live-import routes require a real (non-demo) staff
# principal (`_require_non_demo_staff`) since they make an outbound network
# call to a caller-supplied canvas_url/access_token -- an SSRF primitive the
# demo sandbox's anonymous-staff convention should never have covered. Every
# test below that exercises the routes' business logic (not the auth gate
# itself, covered separately under "Authorization") carries this header.
# Role "operator" (a SUPER_ROLES member, see
# original/principal.py:assert_student_access) rather than "professor":
# these tests use flat, tenant-less student ids ("canvas_kid", "x", etc,
# this file's existing convention), and a tenant-scoped "professor"
# principal would be rejected by the tenant-isolation middleware's
# cross-tenant check before even reaching the route.
STAFF_TOKEN = pr.mint_principal_token("op-canvas-live", "operator", "canvaslive")
STAFF_HEADERS = {"Authorization": f"Bearer {STAFF_TOKEN}"}

# ≥50 words each, multi-sentence prose so the feature pipeline behaves.
TEXT_A = (
    "Grace and peace open nearly every Pauline letter, and the repetition is not "
    "accidental but theological. The writer returns again and again to the same "
    "vocabulary, the same cadence, the same habit of qualifying a bold claim with "
    "a gentle clause. Across a semester these habits compound into a recognizable "
    "voice, and it is that voice the system learns to know and defend with patience."
)
TEXT_B = (
    "The doctrine of creation is not merely a claim about beginnings; it is a "
    "claim about belonging. To say the world is made is to say the world is "
    "meant, and to say the world is meant is to place every creature inside a "
    "story larger than itself. The essay that follows traces this thought "
    "through three movements, each resting deliberately on the one before it."
)
SHORT_TEXT = "Far too short to import."


def _sub_text_entry(sub_id: int, body: str, assignment: str, submitted_at: str) -> dict:
    return {
        "id": sub_id,
        "submission_type": "online_text_entry",
        "body": body,
        "submitted_at": submitted_at,
        "assignment": {"name": assignment},
    }


def _sub_upload(sub_id: int, file_url: str, filename: str, assignment: str) -> dict:
    return {
        "id": sub_id,
        "submission_type": "online_upload",
        "submitted_at": "2026-02-14T00:00:00Z",
        "assignment": {"name": assignment},
        "attachments": [{"url": file_url, "display_name": filename}],
    }


def _make_transport() -> httpx.MockTransport:
    """Two-page submissions listing (Link-header pagination) + one file route."""
    subs_path = f"/api/v1/courses/{COURSE}/students/submissions"

    page1 = [
        _sub_text_entry(101, TEXT_A, "Essay One", "2026-01-15T00:00:00Z"),
        _sub_text_entry(103, SHORT_TEXT, "Tiny Reflection", "2026-01-20T00:00:00Z"),
    ]
    page2 = [_sub_upload(102, f"{CANVAS_URL}/files/essay.txt", "essay.txt", "Uploaded Essay")]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == f"Bearer {TOKEN}"
        if request.url.path == subs_path:
            if request.url.params.get("page") == "2":
                return httpx.Response(200, json=page2)
            return httpx.Response(
                200,
                json=page1,
                headers={"Link": f'<{CANVAS_URL}{subs_path}?page=2>; rel="next"'},
            )
        if request.url.path == "/files/essay.txt":
            return httpx.Response(200, content=TEXT_B.encode())
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


@pytest.fixture
def fake_canvas(monkeypatch):
    transport = _make_transport()
    monkeypatch.setattr(
        live_import,
        "make_client",
        lambda: httpx.AsyncClient(transport=transport, timeout=5.0),
    )


@pytest.fixture
def no_canvas_env(monkeypatch):
    monkeypatch.delenv("CANVAS_BASE_URL", raising=False)
    monkeypatch.delenv("CANVAS_API_TOKEN", raising=False)


def _body(**extra) -> dict:
    return {
        "canvas_course_id": COURSE,
        "canvas_user_id": USER,
        "canvas_url": CANVAS_URL,
        "access_token": TOKEN,
        **extra,
    }


def test_list_paginates_extracts_and_filters(live_client, store_reset, fake_canvas):
    r = live_client.post(
        "/canvas/baseline/canvas_kid/list-canvas-submissions",
        json=_body(),
        headers=STAFF_HEADERS,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    # 101 (text entry, page 1) + 102 (file upload, page 2); 103 filtered (<50 words)
    ids = {s["canvas_submission_id"] for s in data["submissions"]}
    assert ids == {"101", "102"}
    assert data["total"] == 2
    by_id = {s["canvas_submission_id"]: s for s in data["submissions"]}
    entry = by_id["101"]
    assert entry["assignment_name"] == "Essay One"
    assert entry["word_count"] == len(TEXT_A.split())
    assert entry["preview"].startswith(TEXT_A[:40])
    assert entry["already_imported"] is False
    upload = by_id["102"]
    assert upload["assignment_name"] == "Uploaded Essay"
    assert upload["word_count"] == len(TEXT_B.split())


def test_import_then_dedup_and_already_imported_flip(live_client, store_reset, fake_canvas):
    sid = "canvas_kid"
    r = live_client.post(
        f"/canvas/baseline/{sid}/import-baseline",
        json=_body(submission_ids=["101", "102", "999"]),
        headers=STAFF_HEADERS,
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["imported"] == 2
    assert out["skipped"] == 1  # 999 not found in Canvas response
    assert any("999" in e for e in out["errors"])
    assert out["provenance"] == "canvas"
    assert out["provenance_downgraded"] is False

    # Samples landed with canvas provenance + its trust weight.
    student = live_client.get(f"/students/{sid}").json()
    assert student["sample_count"] == 2
    provs = {s["provenance"] for s in student["samples"]}
    assert provs == {"canvas"}
    weights = {s["auth_weight"] for s in student["samples"]}
    assert weights == {AUTH_WEIGHTS["canvas"]}

    # Listing again marks both as already imported.
    r2 = live_client.post(
        f"/canvas/baseline/{sid}/list-canvas-submissions",
        json=_body(),
        headers=STAFF_HEADERS,
    )
    flags = {s["canvas_submission_id"]: s["already_imported"] for s in r2.json()["submissions"]}
    assert flags == {"101": True, "102": True}

    # Re-import is a clean dedup skip, not a duplicate sample.
    r3 = live_client.post(
        f"/canvas/baseline/{sid}/import-baseline",
        json=_body(submission_ids=["101"]),
        headers=STAFF_HEADERS,
    )
    assert r3.json()["imported"] == 0
    assert r3.json()["skipped"] == 1
    assert live_client.get(f"/students/{sid}").json()["sample_count"] == 2


def test_fetch_submission_text_for_analysis(live_client, store_reset, fake_canvas):
    r = live_client.post(
        "/canvas/baseline/canvas_kid/fetch-submission-text",
        json=_body(canvas_submission_id="102"),
        headers=STAFF_HEADERS,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["text"].startswith(TEXT_B[:40])
    assert data["word_count"] == len(TEXT_B.split())
    assert data["assignment_name"] == "Uploaded Essay"
    # Pure fetch — nothing stored.
    assert live_client.get("/students/canvas_kid").status_code == 404


def test_fetch_submission_text_rejects_short(live_client, store_reset, fake_canvas):
    r = live_client.post(
        "/canvas/baseline/canvas_kid/fetch-submission-text",
        json=_body(canvas_submission_id="103"),
        headers=STAFF_HEADERS,
    )
    assert r.status_code == 422
    assert "minimum" in r.json()["detail"].lower()


def test_no_config_gives_pinned_guidance_400(live_client, no_canvas_env):
    r = live_client.post(
        "/canvas/baseline/x/list-canvas-submissions",
        json={"canvas_course_id": COURSE, "canvas_user_id": USER},
        headers=STAFF_HEADERS,
    )
    assert r.status_code == 400
    assert r.json()["detail"] == live_import.NO_CONFIG_GUIDANCE


def test_missing_ids_422(live_client, fake_canvas):
    r = live_client.post(
        "/canvas/baseline/x/list-canvas-submissions",
        json={"canvas_url": CANVAS_URL, "access_token": TOKEN},
        headers=STAFF_HEADERS,
    )
    assert r.status_code == 422


def test_canvas_failure_becomes_502(live_client, store_reset, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "canvas exploded"})

    monkeypatch.setattr(
        live_import,
        "make_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0),
    )
    r = live_client.post(
        "/canvas/baseline/x/list-canvas-submissions", json=_body(), headers=STAFF_HEADERS
    )
    assert r.status_code == 502
    assert "Failed to fetch submissions from Canvas" in r.json()["detail"]


# ── Authorization ─────────────────────────────────────────────────────────────


@pytest.fixture
def real_deploy(monkeypatch):
    """Flip the loaded app into pilot behaviour without reloading it."""
    import original.api

    monkeypatch.setattr(original.api, "_IS_REAL_DEPLOY", True)
    yield


@pytest.mark.parametrize(
    "route",
    ["list-canvas-submissions", "import-baseline", "fetch-submission-text"],
)
def test_canvas_routes_reject_anonymous_on_real_deploy(
    live_client, store_reset, fake_canvas, real_deploy, route
):
    """Every /canvas/baseline/* route spends the institution's Canvas token, so
    none may be reachable anonymously on a pilot.

    Regression: these three had no auth check at all. `/canvas/` is not in
    _STAFF_ONLY_PREFIXES, and the middleware's assert_student_access allows a
    *flat* student id (no `tenant:` prefix) for the demo principal — so an
    unauthenticated caller reached Canvas with the institution's credential.

    403, not 401: since T-66's fix, assert_student_access denies a flat id
    for the anonymous demo principal on a real deploy directly in the
    tenant-isolation middleware, before the request ever reaches this
    handler's own _require_non_demo_staff check (which is what used to
    produce the 401) — one layer earlier, same refusal.
    """
    r = live_client.post(f"/canvas/baseline/anyflatid/{route}", json=_body())
    assert r.status_code == 403, r.text


def test_body_url_does_not_borrow_env_token(live_client, store_reset, monkeypatch):
    """A caller-supplied canvas_url must never be sent the *env* CANVAS_API_TOKEN.

    Regression: resolve_canvas_config resolved url and token independently, so
    {"canvas_url": "https://evil"} with no access_token reached the attacker's
    host carrying the institution's real Canvas credential.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    monkeypatch.setattr(
        live_import,
        "make_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0),
    )
    monkeypatch.setenv("CANVAS_BASE_URL", CANVAS_URL)
    monkeypatch.setenv("CANVAS_API_TOKEN", "institution-secret-token")

    r = live_client.post(
        "/canvas/baseline/x/list-canvas-submissions",
        json={
            "canvas_course_id": COURSE,
            "canvas_user_id": USER,
            "canvas_url": "https://evil.attacker.example",
        },
        headers=STAFF_HEADERS,
    )
    assert r.status_code == 400
    assert r.json()["detail"] == live_import.NO_CONFIG_GUIDANCE
    assert seen == [], "no request may leave the process for a body-supplied host"


def test_env_configured_host_still_uses_env_token(live_client, store_reset, monkeypatch):
    """The pairing rule must not break the normal env-configured deployment:
    no body credentials at all still resolves to the env host + env token."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    monkeypatch.setattr(
        live_import,
        "make_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0),
    )
    monkeypatch.setenv("CANVAS_BASE_URL", CANVAS_URL)
    monkeypatch.setenv("CANVAS_API_TOKEN", "institution-secret-token")

    r = live_client.post(
        "/canvas/baseline/x/list-canvas-submissions",
        json={"canvas_course_id": COURSE, "canvas_user_id": USER},
        headers=STAFF_HEADERS,
    )
    assert r.status_code == 200, r.text
    assert seen, "the env-configured host should still be called"
    assert seen[0].url.host == "canvas.test"
    assert seen[0].headers["authorization"] == "Bearer institution-secret-token"


# ── get_submission_text branch coverage (direct unit calls) ───────────────────
#
# The endpoint-level tests above already exercise the online_text_entry vs.
# online_upload split with a happy-path attachment. These call
# get_submission_text() directly — it takes the httpx.AsyncClient as a plain
# argument, so a MockTransport-backed client is the same seam already used by
# fake_canvas — to reach the remaining arms: an unrecognised submission_type,
# an empty text-entry body, an attachment with no usable url, an attachment
# fetch that fails with an HTTP error, an attachment whose bytes fail
# extraction, a too-short attachment followed by a good one on the same
# submission, and every attachment being exhausted without a usable result.


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)


async def test_make_client_returns_async_client():
    client = live_import.make_client()
    try:
        assert isinstance(client, httpx.AsyncClient)
    finally:
        await client.aclose()


async def test_get_submission_text_unknown_submission_type_returns_none():
    sub = {"id": 301, "submission_type": "online_quiz", "assignment": {"name": "Quiz"}}

    async with _client(lambda r: httpx.Response(404)) as client:
        text = await live_import.get_submission_text(sub, TOKEN, client)
    assert text is None


async def test_get_submission_text_empty_body_returns_none():
    sub = _sub_text_entry(302, "", "Blank Essay", "2026-01-01T00:00:00Z")

    async with _client(lambda r: httpx.Response(404)) as client:
        text = await live_import.get_submission_text(sub, TOKEN, client)
    assert text is None


async def test_get_submission_text_attachment_without_url_is_skipped():
    """Neither url nor preview_url present — the attachment is skipped without
    ever making an HTTP call, and the submission yields nothing."""
    sub = {
        "id": 303,
        "submission_type": "online_upload",
        "assignment": {"name": "No URL Essay"},
        "attachments": [{"display_name": "essay.txt"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP call should be made for an attachment without a url")

    async with _client(handler) as client:
        text = await live_import.get_submission_text(sub, TOKEN, client)
    assert text is None


async def test_get_submission_text_attachment_http_error_is_skipped():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="canvas storage exploded")

    sub = _sub_upload(304, f"{CANVAS_URL}/files/broken.txt", "broken.txt", "Broken Essay")

    async with _client(handler) as client:
        text = await live_import.get_submission_text(sub, TOKEN, client)
    assert text is None


async def test_get_submission_text_attachment_extraction_error_is_skipped():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not a real pdf")

    sub = _sub_upload(305, f"{CANVAS_URL}/files/broken.pdf", "broken.pdf", "Bad PDF Essay")

    async with _client(handler) as client:
        text = await live_import.get_submission_text(sub, TOKEN, client)
    assert text is None


async def test_get_submission_text_short_attachment_falls_through_to_next():
    """First attachment extracts to text under MIN_WORDS — the loop must
    continue to the second attachment rather than returning early."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("short.txt"):
            return httpx.Response(200, content=SHORT_TEXT.encode())
        return httpx.Response(200, content=TEXT_B.encode())

    sub = _sub_upload(306, f"{CANVAS_URL}/files/short.txt", "short.txt", "Two Attachment Essay")
    sub["attachments"].append(
        {"url": f"{CANVAS_URL}/files/full.txt", "display_name": "full.txt"}
    )

    async with _client(handler) as client:
        text = await live_import.get_submission_text(sub, TOKEN, client)
    assert text == TEXT_B


async def test_get_submission_text_all_attachments_exhausted_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=SHORT_TEXT.encode())

    sub = _sub_upload(307, f"{CANVAS_URL}/files/short.txt", "short.txt", "Too Short Essay")

    async with _client(handler) as client:
        text = await live_import.get_submission_text(sub, TOKEN, client)
    assert text is None
