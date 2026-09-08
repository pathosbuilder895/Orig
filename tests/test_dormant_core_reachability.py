"""Thin reachability tests for the dormant v1 core modules (branch-coverage
part 3, task 5): ``original/core/config.py``, ``original/core/logging.py``,
``original/core/security.py``.

Scope note (see the task brief / plan): these three modules are DORMANT v1
surface. ``original/core/config.py`` and ``original/core/logging.py`` are
kept alive only because ``original/cli/delete_student.py`` and
``original/cli/security_audit.py`` import from them (Settings, get_logger).
``original/core/security.py`` (``SecurityHeadersMiddleware``,
``_docs_relaxed_csp``) is not imported by anything at all in the live stack
or the CLI tools — it is pure dead code kept around pending deletion (see
``pyproject.toml``). Nothing here is meant to pin behaviour beyond making
each branch arm run once; see the task report for the arm-by-arm mapping.

Isolation notes:
* ``Settings`` reads env vars/`.env` at construction time. Every Settings()
  call below passes every field the validator reads explicitly as a
  constructor kwarg, so none of these tests depend on (or mutate) process
  environment variables.
* ``Settings._ALLOWED_ORIGINS_STR`` is a leading-underscore pydantic
  *private* attribute — invisible to both env-var sourcing and constructor
  kwargs (confirmed by direct experiment; matches the note already recorded
  in ``tests/test_security_audit_cli.py``). The only way to vary it is to
  assign the instance attribute directly after construction, which is a
  plain, unvalidated attribute set (pydantic v2 private attrs are not
  revalidated on assignment). Where a test needs a non-default value for
  ``validate_production_secrets`` to observe, it mutates the attribute and
  then calls the validator method directly (it is a plain bound method,
  callable outside of pydantic's construction path).
* ``configure_logging`` mutates the global ``logging.root`` handler list.
  Tests save and restore it (and the root level) so this file doesn't leak
  handlers into later tests.
"""

from __future__ import annotations

import io
import json
import logging
from types import SimpleNamespace

import pydantic
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from original.core.config import Settings
from original.core.logging import (
    JSONFormatter,
    PlainFormatter,
    RequestLoggingMiddleware,
    configure_logging,
    get_logger,
    set_request_context,
)
from original.core.security import (
    _CSP_API,
    _CSP_DOCS,
    SecurityHeadersMiddleware,
    _docs_relaxed_csp,
)

# ── Shared valid-in-production field values ──────────────────────────────────
# Deliberately distinct from every "placeholder" value the validator checks
# for, so a test that isn't targeting a given arm doesn't accidentally trip
# it and mask the arm under test.
_GOOD_SECRET_KEY = "s" * 40
_GOOD_ADMIN_PASSWORD = "a-real-strong-password-xyz"
_GOOD_DATABASE_URL = "postgresql://user:pw@dbhost:5432/original_db"


def _raises_validation_error(**kwargs) -> str:
    """Construct Settings(ENVIRONMENT='production', **kwargs) and return the
    first validation error message, or fail the test if none was raised."""
    with pytest.raises(pydantic.ValidationError) as exc_info:
        Settings(ENVIRONMENT="production", **kwargs)
    return str(exc_info.value)


# ═══════════════════════════════════════════════════════════════════════════
# original/core/config.py — Settings.validate_production_secrets (14 arms)
#   plus Settings.ALLOWED_ORIGINS property (2 arms)
# ═══════════════════════════════════════════════════════════════════════════


class TestValidateProductionSecrets:
    def test_non_production_environment_skips_all_checks(self):
        """Arm 1-False: ENVIRONMENT != 'production' — the whole validator body
        is a no-op regardless of how bad the other fields are."""
        settings = Settings(
            ENVIRONMENT="testing",
            SECRET_KEY="short",
            FIRST_ADMIN_PASSWORD="changeme123!",
        )
        assert settings.ENVIRONMENT == "testing"

    def test_short_secret_key_raises(self):
        """Arm 2-True."""
        msg = _raises_validation_error(
            SECRET_KEY="short",
            FIRST_ADMIN_PASSWORD=_GOOD_ADMIN_PASSWORD,
            DATABASE_URL=_GOOD_DATABASE_URL,
            CANVAS_WEBHOOK_SECRET="",
        )
        assert "SECRET_KEY must be at least 32 chars" in msg

    def test_placeholder_secret_key_raises(self):
        """Arm 3-True (len >= 32 so arm 2 passes, but contains CHANGE_ME)."""
        msg = _raises_validation_error(
            SECRET_KEY="CHANGE_ME" + "x" * 30,
            FIRST_ADMIN_PASSWORD=_GOOD_ADMIN_PASSWORD,
            DATABASE_URL=_GOOD_DATABASE_URL,
            CANVAS_WEBHOOK_SECRET="",
        )
        assert "still contains placeholder" in msg

    def test_default_admin_password_raises(self):
        """Arm 4-True (default FIRST_ADMIN_PASSWORD left unchanged)."""
        msg = _raises_validation_error(
            SECRET_KEY=_GOOD_SECRET_KEY,
            DATABASE_URL=_GOOD_DATABASE_URL,
            CANVAS_WEBHOOK_SECRET="",
        )
        assert "FIRST_ADMIN_PASSWORD must be changed" in msg

    def test_placeholder_database_url_raises(self):
        """Arm 5-True."""
        msg = _raises_validation_error(
            SECRET_KEY=_GOOD_SECRET_KEY,
            FIRST_ADMIN_PASSWORD=_GOOD_ADMIN_PASSWORD,
            DATABASE_URL="postgresql://CHANGE_ME:pw@dbhost/original_db",
            CANVAS_WEBHOOK_SECRET="",
        )
        assert "DATABASE_URL still contains placeholder" in msg

    def test_placeholder_canvas_webhook_secret_raises(self):
        """Arm 6-True (CANVAS_WEBHOOK_SECRET truthy AND contains CHANGE_ME)."""
        msg = _raises_validation_error(
            SECRET_KEY=_GOOD_SECRET_KEY,
            FIRST_ADMIN_PASSWORD=_GOOD_ADMIN_PASSWORD,
            DATABASE_URL=_GOOD_DATABASE_URL,
            CANVAS_WEBHOOK_SECRET="CHANGE_ME_webhook",
        )
        assert "CANVAS_WEBHOOK_SECRET still contains placeholder" in msg

    def test_localhost_only_origins_raise(self):
        """Arm 7-True. _ALLOWED_ORIGINS_STR can't be set via env/kwargs (see
        module docstring), so the default localhost-only origins are what
        production would actually see unless something mutates the private
        attribute — this is the realistic failure mode."""
        msg = _raises_validation_error(
            SECRET_KEY=_GOOD_SECRET_KEY,
            FIRST_ADMIN_PASSWORD=_GOOD_ADMIN_PASSWORD,
            DATABASE_URL=_GOOD_DATABASE_URL,
            CANVAS_WEBHOOK_SECRET="",
        )
        assert "ALLOWED_ORIGINS is not configured for production" in msg

    def test_all_checks_pass_returns_self(self):
        """Arms 2..6-False and arm 7-False (the full-pass path, ending in
        `return self`). Reaching arm 7-False requires a non-localhost
        ALLOWED_ORIGINS, which (per the module docstring) can only be
        produced by mutating the private attribute directly and then
        re-invoking the validator method — the constructor path can't reach
        it, since env vars and kwargs both silently no-op against it."""
        settings = Settings(
            ENVIRONMENT="testing",
            SECRET_KEY=_GOOD_SECRET_KEY,
            FIRST_ADMIN_PASSWORD=_GOOD_ADMIN_PASSWORD,
            DATABASE_URL=_GOOD_DATABASE_URL,
            CANVAS_WEBHOOK_SECRET="",
        )
        settings.ENVIRONMENT = "production"
        settings._ALLOWED_ORIGINS_STR = "https://example.edu"

        result = settings.validate_production_secrets()

        assert result is settings


class TestAllowedOriginsProperty:
    def test_parses_comma_separated_string(self):
        """isinstance-True arm: the normal, only-reachable-in-production
        case — _ALLOWED_ORIGINS_STR is always a str via any public API."""
        settings = Settings()
        assert settings.ALLOWED_ORIGINS == [
            "http://localhost:3000",
            "http://localhost:8080",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ]

    def test_passes_through_non_string_unchanged(self):
        """isinstance-False arm. Defensive fallback for a non-str value —
        unreachable through env vars or the constructor (the field is typed
        `str` and the private attr ignores both), so exercised the same way
        as the arm above: direct attribute assignment."""
        settings = Settings()
        settings._ALLOWED_ORIGINS_STR = ["https://a.example", "https://b.example"]
        assert settings.ALLOWED_ORIGINS == ["https://a.example", "https://b.example"]


# ═══════════════════════════════════════════════════════════════════════════
# original/core/logging.py
# ═══════════════════════════════════════════════════════════════════════════


def test_set_request_context():
    set_request_context("req-1", user_id="user-1", institution="inst-1")
    from original.core.logging import _institution, _request_id, _user_id

    assert _request_id.get() == "req-1"
    assert _user_id.get() == "user-1"
    assert _institution.get() == "inst-1"


def _formatter_logger():
    """A throwaway logger + JSONFormatter handler writing to an in-memory
    stream, mirroring the module's own documented usage pattern."""
    logger = logging.getLogger("test.core_logging.jsonformatter")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)
    return logger, stream


class TestJSONFormatter:
    def test_format_basic_message_no_extras_no_exc_info(self):
        """for-loop over record.__dict__ with every key filtered out (all
        standard LogRecord attrs are in the exclusion set); exc_info-False
        arm."""
        logger, stream = _formatter_logger()
        logger.info("hello world")
        payload = json.loads(stream.getvalue())
        assert payload["message"] == "hello world"
        assert payload["level"] == "INFO"
        assert "exception" not in payload

    def test_format_includes_extra_fields(self):
        """Inner if-True arm: a key from `extra={...}` is not in the
        exclusion set and doesn't start with '_', so it gets merged in."""
        logger, stream = _formatter_logger()
        logger.info("scored", extra={"student_id": 42, "deviation": 0.91})
        payload = json.loads(stream.getvalue())
        assert payload["student_id"] == 42
        assert payload["deviation"] == 0.91

    def test_format_includes_exception_when_exc_info_present(self):
        """exc_info-True arm."""
        logger, stream = _formatter_logger()
        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("failed")
        payload = json.loads(stream.getvalue())
        assert "exception" in payload
        assert "boom" in payload["exception"]


def test_plain_formatter_formats_a_record():
    formatter = PlainFormatter()
    record = logging.LogRecord(
        name="test.plain",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    assert "hello" in formatted
    assert "[INFO]" in formatted


class TestConfigureLogging:
    """configure_logging mutates the global root logger — save/restore its
    handlers and level around each test so this file doesn't leak state."""

    @pytest.fixture(autouse=True)
    def _restore_root_logger(self):
        original_handlers = logging.root.handlers[:]
        original_level = logging.root.level
        yield
        logging.root.handlers[:] = original_handlers
        logging.root.setLevel(original_level)

    def test_use_json_true_installs_json_formatter(self):
        """Ternary True arm."""
        configure_logging(level="DEBUG", use_json=True)
        assert len(logging.root.handlers) == 1
        assert isinstance(logging.root.handlers[0].formatter, JSONFormatter)
        assert logging.root.level == logging.DEBUG

    def test_use_json_false_installs_plain_formatter(self):
        """Ternary False arm."""
        configure_logging(level="INFO", use_json=False)
        assert len(logging.root.handlers) == 1
        assert isinstance(logging.root.handlers[0].formatter, PlainFormatter)


def test_get_logger_returns_stdlib_logger():
    logger = get_logger("original.test.dormant")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "original.test.dormant"


def _make_request_logging_app():
    async def home(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", home), Route("/health", home)])
    app.add_middleware(RequestLoggingMiddleware)
    return app


class TestRequestLoggingMiddleware:
    def test_skip_path_bypasses_logging_and_request_id(self, caplog):
        """if-True arm: request.url.path in self.skip_paths."""
        client = TestClient(_make_request_logging_app())
        with caplog.at_level(logging.INFO, logger="original.http"):
            resp = client.get("/health")
        assert resp.status_code == 200
        assert "X-Request-ID" not in resp.headers
        assert not any(r.name == "original.http" for r in caplog.records)

    def test_normal_path_logs_and_sets_request_id(self, caplog):
        """if-False arm: normal path goes through the try/finally, sets the
        response header, and logs one 'request' line."""
        client = TestClient(_make_request_logging_app())
        with caplog.at_level(logging.INFO, logger="original.http"):
            resp = client.get("/")
        assert resp.status_code == 200
        assert "X-Request-ID" in resp.headers
        assert any(
            r.name == "original.http" and r.getMessage() == "request"
            for r in caplog.records
        )


# ═══════════════════════════════════════════════════════════════════════════
# original/core/security.py — fully dead code, imported by nothing else
# ═══════════════════════════════════════════════════════════════════════════


class TestDocsRelaxedCsp:
    @pytest.mark.parametrize(
        "path",
        ["/api", "/api/"],
    )
    def test_bare_api_root_is_relaxed(self, path):
        """Arm 1-True."""
        assert _docs_relaxed_csp(path) is True

    def test_openapi_json_is_relaxed(self):
        """Arm 1-False, arm 2-True."""
        assert _docs_relaxed_csp("/api/openapi.json") is True

    @pytest.mark.parametrize(
        "path",
        ["/api/docs", "/api/docs/", "/api/redoc", "/api/reference/x"],
    )
    def test_docs_subpaths_are_relaxed(self, path):
        """Arm 1-False, arm 2-False, arm 3-True."""
        assert _docs_relaxed_csp(path) is True

    def test_unrelated_api_path_is_strict(self):
        """Arms 1, 2, 3 all False — the terminal `return False`."""
        assert _docs_relaxed_csp("/students/1/score") is False


def _make_security_headers_app(environment: str, *, set_server_header: bool = False):
    async def home(request):
        resp = PlainTextResponse("ok")
        if set_server_header:
            resp.headers["server"] = "test-server"
        return resp

    async def docs(request):
        return PlainTextResponse("docs")

    app = Starlette(routes=[Route("/", home), Route("/api/docs", docs)])
    settings = SimpleNamespace(ENVIRONMENT=environment)
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)
    return app


class TestSecurityHeadersMiddleware:
    def test_non_production_api_path_gets_strict_csp_and_no_hsts(self):
        """if self._production False arm; also exercises the try/except
        KeyError deletion of a 'server' header that Starlette never sets."""
        client = TestClient(_make_security_headers_app("testing"))
        resp = client.get("/")
        assert resp.headers["content-security-policy"] == _CSP_API
        assert "strict-transport-security" not in resp.headers
        assert resp.headers["x-content-type-options"] == "nosniff"

    def test_production_docs_path_gets_relaxed_csp_and_hsts(self):
        """if self._production True arm; docs-path CSP branch; and the
        try/except's success path (a real 'server' header present to
        delete)."""
        client = TestClient(
            _make_security_headers_app("production", set_server_header=True)
        )
        resp = client.get("/api/docs")
        assert resp.headers["content-security-policy"] == _CSP_DOCS
        assert "strict-transport-security" in resp.headers
        assert "server" not in resp.headers
