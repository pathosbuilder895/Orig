"""Public-launch hardening for the Bluebook self-serve site (2026-09-28).

Each test pins one hole the launch audit found on the live stack:

* ``POST /student-auth/login`` issued a session for any email at any existing
  institution with no password. It is demo-only now.
* A signed-in student could list the institution's submissions, courses, and
  exam prompts. Those reads are staff-only now.
* The login throttle counted successes and keyed on the socket peer, which on
  Render is the proxy, so one class signing in could lock out the site (T-20).
  It now counts failures, per forwarded client IP and per email.
* Nothing bounded request bodies (``original/body_limit.py``).
* FastAPI's interactive docs mapped every route on the public internet.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from original import student_auth
from original.body_limit import BodySizeLimitMiddleware

PW = "s3cret-passw0rd"


@pytest.fixture
def api_mod(live_app):
    import original.api

    return original.api


@pytest.fixture(autouse=True)
def _reset_login_throttle(live_app):
    import original.api as _api

    _api._login_attempts.clear()
    yield
    _api._login_attempts.clear()


def _student_headers(tenant: str = "acme", email: str = "stu@acme.edu") -> dict:
    sid = student_auth.derive_student_id(tenant, email)
    return {"Authorization": f"Bearer {student_auth.mint_session(sid, 'Stu')}"}


# ── Impersonation ─────────────────────────────────────────────────────────────


def test_student_auth_login_is_404_on_real_deploy(pilot_env, store_reset, live_client):
    r = live_client.post(
        "/student-auth/login", json={"email": "victim@acme.edu", "institution": "acme"}
    )
    assert r.status_code == 404


def test_student_auth_login_still_works_in_demo(store_reset, live_client):
    r = live_client.post(
        "/student-auth/login", json={"email": "demo@example.edu", "institution": "Demo U"}
    )
    assert r.status_code == 200
    assert r.json()["token"]


# ── Staff-only Bluebook reads ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    ["/bluebook/submissions", "/bluebook/courses", "/bluebook/exams", "/bluebook/exams/x1"],
)
def test_student_cannot_read_teacher_lists(store_reset, live_client, path):
    r = live_client.get(path, headers=_student_headers())
    assert r.status_code == 403, r.text


@pytest.mark.parametrize("path", ["/bluebook/submissions", "/bluebook/courses", "/bluebook/exams"])
def test_anonymous_cannot_read_teacher_lists_on_real_deploy(
    pilot_env, store_reset, live_client, path
):
    assert live_client.get(path).status_code == 401


def test_staff_still_reads_lists(store_reset, live_client, principal_headers):
    h = principal_headers("prof-1", "professor", "acme")
    for path in ("/bluebook/submissions", "/bluebook/courses", "/bluebook/exams"):
        assert live_client.get(path, headers=h).status_code == 200, path


# ── Login throttle ────────────────────────────────────────────────────────────


def _register(live_client, email: str, tenant: str = "acme") -> None:
    from original import users as users_mod

    users_mod.create_user(email, PW, "professor", tenant, "Dr Test")


def test_successful_logins_do_not_consume_the_budget(store_reset, live_client):
    _register(live_client, "ok@acme.edu")
    codes = [
        live_client.post("/auth/login", json={"email": "ok@acme.edu", "password": PW}).status_code
        for _ in range(15)
    ]
    assert codes == [200] * 15


def test_distinct_forwarded_clients_have_separate_buckets(pilot_env, store_reset, live_client):
    """On a real deploy every request arrives from Render's proxy. Ten
    failures from one forwarded client must not lock out a different one."""
    for i in range(10):
        live_client.post(
            "/auth/login",
            json={"email": f"nobody{i}@acme.edu", "password": "wrong"},
            headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.1"},
        )
    _register(live_client, "teacher@acme.edu")
    r = live_client.post(
        "/auth/login",
        json={"email": "teacher@acme.edu", "password": PW},
        headers={"X-Forwarded-For": "198.51.100.9, 10.0.0.1"},
    )
    assert r.status_code == 200, r.text


def test_rotating_forwarded_ip_cannot_bypass_per_email_bucket(pilot_env, store_reset, live_client):
    """X-Forwarded-For is client-controlled, so the per-email bucket is what
    actually caps guesses against one account."""
    _register(live_client, "target@acme.edu")
    codes = [
        live_client.post(
            "/auth/login",
            json={"email": "target@acme.edu", "password": "wrong"},
            headers={"X-Forwarded-For": f"203.0.113.{i}"},
        ).status_code
        for i in range(11)
    ]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429


def test_forwarded_header_ignored_off_real_deploy(api_mod):
    from types import SimpleNamespace

    from original.routers import _shared

    req = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.7"}, client=SimpleNamespace(host="127.0.0.1")
    )
    assert _shared._client_ip(req) == "127.0.0.1"


def test_real_deploy_without_forwarded_header_uses_socket_peer(api_mod, monkeypatch):
    from types import SimpleNamespace

    from original.routers import _shared

    monkeypatch.setattr(api_mod, "_IS_REAL_DEPLOY", True)
    req = SimpleNamespace(headers={}, client=None)
    assert _shared._client_ip(req) == "unknown"


# ── Body cap ──────────────────────────────────────────────────────────────────


def _run_asgi(mw, *, headers, chunks):
    sent: list[dict] = []
    queue = [
        {"type": "http.request", "body": c, "more_body": i < len(chunks) - 1}
        for i, c in enumerate(chunks)
    ]

    async def receive():
        return queue.pop(0)

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "headers": headers}
    asyncio.run(mw(scope, receive, send))
    return sent


def test_declared_oversize_body_is_413_before_the_app_runs():
    called = []

    async def app(scope, receive, send):
        called.append(True)

    sent = _run_asgi(
        BodySizeLimitMiddleware(app, max_bytes=10),
        headers=[(b"content-length", b"11")],
        chunks=[b"x" * 11],
    )
    assert not called
    assert sent[0]["status"] == 413


def test_streamed_oversize_body_raises_413():
    async def app(scope, receive, send):
        while True:
            m = await receive()
            if not m.get("more_body"):
                break

    with pytest.raises(HTTPException) as exc:
        _run_asgi(
            BodySizeLimitMiddleware(app, max_bytes=10),
            headers=[],
            chunks=[b"x" * 6, b"x" * 6],
        )
    assert exc.value.status_code == 413


def test_body_under_cap_passes_through():
    got = []

    async def app(scope, receive, send):
        got.append((await receive())["body"])

    _run_asgi(
        BodySizeLimitMiddleware(app, max_bytes=10),
        headers=[(b"content-length", b"bad")],
        chunks=[b"hello"],
    )
    assert got == [b"hello"]


def test_non_http_scope_passes_through():
    got = []

    async def app(scope, receive, send):
        got.append(scope["type"])

    asyncio.run(BodySizeLimitMiddleware(app)({"type": "lifespan"}, None, None))
    assert got == ["lifespan"]


def test_oversize_request_is_413_through_the_app(live_client):
    from original import body_limit

    big = b"x" * (body_limit.MAX_REQUEST_BYTES + 1)
    r = live_client.post("/auth/login", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413


# ── API docs ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_hidden_on_real_deploy(pilot_env, live_client, path):
    assert live_client.get(path).status_code == 404


def test_api_docs_served_in_demo(live_client):
    assert live_client.get("/openapi.json").status_code == 200
