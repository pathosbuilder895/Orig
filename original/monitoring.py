"""monitoring.py — optional error reporting to Sentry.

Off unless ``SENTRY_DSN`` is set; without it ``sentry_sdk`` is never imported,
so the demo and test environments are unaffected and the package need not be
installed (it is in ``requirements-pilot.txt`` only).

What leaves the server is deliberately narrow, because a request body here is
a student's examination answer and a local variable can hold one:

- ``send_default_pii=False`` — no user ids, IPs, or cookies.
- ``max_request_body_size="never"`` — no request bodies.
- ``include_local_variables=False`` — stack frames carry no variable values.
- ``before_send`` strips whatever request data is still attached (headers,
  cookies, query string, body, URL) and keeps only the HTTP method.

Errors only: tracing stays off, including when a stale deployment variable
asks for it. Messages, breadcrumbs and custom context are not exported.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


def scrub_event(event: dict, hint: dict | None = None) -> dict:
    """Allow only diagnostic structure, never arbitrary application strings.

    Student prose can appear in exception values, log messages, breadcrumbs,
    URLs, custom context, or Pydantic validation errors even when body capture
    is disabled. Build a new event instead of trying to blacklist those paths.
    """
    safe = {
        key: event[key]
        for key in ("event_id", "timestamp", "platform", "level", "release", "environment")
        if key in event
    }
    request = event.get("request")
    if isinstance(request, dict) and request.get("method") in {
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "HEAD",
        "OPTIONS",
    }:
        safe["request"] = {"method": request["method"]}
    exception = event.get("exception")
    if isinstance(exception, dict):
        values = []
        for item in exception.get("values") or []:
            if not isinstance(item, dict):
                continue
            value = {"value": "Exception details withheld to protect student writing"}
            if isinstance(item.get("type"), str):
                value["type"] = item["type"]
            stack = item.get("stacktrace")
            if isinstance(stack, dict):
                value["stacktrace"] = {
                    "frames": [
                        {
                            key: frame[key]
                            for key in ("filename", "function", "lineno", "in_app")
                            if key in frame
                        }
                        for frame in stack.get("frames") or []
                        if isinstance(frame, dict)
                    ]
                }
            values.append(value)
        safe["exception"] = {"values": values}
    return safe


def drop_transaction(event: dict, hint: dict | None = None) -> None:
    """Tracing carries a separate payload; keep it disabled for classroom use."""
    return None


def init_sentry(env: dict | None = None) -> bool:
    """Initialise Sentry when ``SENTRY_DSN`` is set. Returns whether it did.
    Never raises: monitoring must not be able to stop the app booting."""
    env = os.environ if env is None else env
    dsn = (env.get("SENTRY_DSN") or "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        log.warning("SENTRY_DSN is set but sentry-sdk is not installed; error reporting is off.")
        return False
    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=env.get("ORIGINAL_ENV") or "demo",
            release=env.get("RENDER_GIT_COMMIT") or None,
            send_default_pii=False,
            max_request_body_size="never",
            include_local_variables=False,
            traces_sample_rate=0.0,
            before_send_transaction=drop_transaction,
            before_send=scrub_event,
        )
    except Exception as exc:  # a bad DSN must not take the service down
        log.warning("Sentry could not start (%s); error reporting is off.", type(exc).__name__)
        return False
    log.info("Sentry error reporting is on (no request bodies, no PII).")
    return True
