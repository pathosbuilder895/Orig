"""
core/logging.py — Structured JSON logging for the Original API.

Every log line is a JSON object with consistent fields:
  timestamp, level, logger, message, request_id, user_id,
  institution_id, endpoint, latency_ms, status_code, ...

Usage:
    from original.core.logging import get_logger
    log = get_logger(__name__)
    log.info("Submission scored", extra={"student_id": sid, "deviation": 0.91})
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any, Dict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ── Context variables ─────────────────────────────────────────────────────────
# These are set per-request and automatically included in every log line.
_request_id: ContextVar[str] = ContextVar("request_id", default="")
_user_id:     ContextVar[str] = ContextVar("user_id",    default="")
_institution: ContextVar[str] = ContextVar("institution", default="")


def set_request_context(request_id: str, user_id: str = "", institution: str = "") -> None:
    _request_id.set(request_id)
    _user_id.set(user_id)
    _institution.set(institution)


# ── JSON formatter ────────────────────────────────────────────────────────────

class JSONFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        base: Dict[str, Any] = {
            "timestamp":      self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%fZ"),
            "level":          record.levelname,
            "logger":         record.name,
            "message":        record.getMessage(),
            "request_id":     _request_id.get() or None,
            "user_id":        _user_id.get() or None,
            "institution_id": _institution.get() or None,
        }

        # Merge any extra fields passed via log.info("msg", extra={...})
        for key, value in record.__dict__.items():
            if key not in {
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "id", "levelname", "levelno", "lineno", "module",
                "msecs", "message", "msg", "name", "pathname", "process",
                "processName", "relativeCreated", "stack_info", "thread", "threadName",
            } and not key.startswith("_"):
                base[key] = value

        if record.exc_info:
            base["exception"] = self.formatException(record.exc_info)

        return json.dumps(base, default=str)


class PlainFormatter(logging.Formatter):
    """Human-readable formatter for local development."""
    FMT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"

    def __init__(self) -> None:
        super().__init__(fmt=self.FMT, datefmt="%H:%M:%S")


# ── Logger factory ────────────────────────────────────────────────────────────

def configure_logging(level: str = "INFO", use_json: bool = True) -> None:
    """Call once at application startup."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter() if use_json else PlainFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level, logging.INFO))

    # Quieten noisy third-party loggers
    for noisy in ("uvicorn.access", "sqlalchemy.engine", "passlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


# ── Request logging middleware ────────────────────────────────────────────────

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs every incoming request and outgoing response as JSON.
    Attaches a unique request_id to each request and injects it
    into the response headers for client-side correlation.
    """

    def __init__(self, app, *, skip_paths: tuple = ("/health", "/readiness")) -> None:
        super().__init__(app)
        self.skip_paths = skip_paths
        self._log = get_logger("original.http")

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        if request.url.path in self.skip_paths:
            return await call_next(request)

        # Honour X-Request-ID from upstream proxy / load balancer; generate if absent.
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        set_request_context(request_id)

        start = time.perf_counter()
        status_code = 500

        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            # Echo the request ID back so callers can correlate logs.
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception:
            raise
        finally:
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            self._log.info(
                "request",
                extra={
                    "method":      request.method,
                    "path":        request.url.path,
                    "status_code": status_code,
                    "latency_ms":  latency_ms,
                    "client_ip":   request.client.host if request.client else None,
                    "user_agent":  request.headers.get("user-agent"),
                },
            )
