"""
core/security.py — Security headers middleware.

Adds hardened HTTP response headers to every response:
  - Strict-Transport-Security (HSTS, production only)
  - X-Content-Type-Options
  - X-Frame-Options
  - Content-Security-Policy
  - Referrer-Policy
  - Permissions-Policy
  - X-XSS-Protection (legacy header, belt-and-suspenders)

These headers cost nothing and defend against a broad class of
browser-level attacks.  They are the first thing any external
security audit checks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

if TYPE_CHECKING:
    from original.core.config import Settings


# Content-Security-Policy used for Swagger / ReDoc docs pages.
# 'unsafe-inline' is required by both UIs; the actual API routes
# return JSON (no HTML) so this relaxation only affects browsers
# that open the docs UI directly.
_CSP_DOCS = (
    "default-src 'self'; "
    "img-src 'self' data: https:; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "frame-ancestors 'none'"
)

# Strict CSP for all non-docs routes (pure JSON API — no scripts needed).
_CSP_API = "default-src 'none'; frame-ancestors 'none'"

def _docs_relaxed_csp(path: str) -> bool:
    """Swagger/ReDoc/Scalar/OpenAPI and any subpaths need the permissive docs CSP (not default-src 'none')."""
    if path in ("/api", "/api/"):
        return True
    if path == "/api/openapi.json":
        return True
    if path.startswith("/api/docs") or path.startswith("/api/redoc") or path.startswith("/api/reference"):
        return True
    return False


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Inject hardened security headers on every response.

    Parameters
    ----------
    app        : the ASGI application to wrap
    settings   : application Settings; controls HSTS and environment checks
    """

    def __init__(self, app, settings: "Settings") -> None:
        super().__init__(app)
        self._production = settings.ENVIRONMENT == "production"

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)

        # ── Always-on headers ─────────────────────────────────────────────
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )

        # ── Content-Security-Policy ────────────────────────────────────────
        path = request.url.path
        csp = _CSP_DOCS if _docs_relaxed_csp(path) else _CSP_API
        response.headers["Content-Security-Policy"] = csp

        # ── HSTS: production only (HTTP in dev/staging is fine) ────────────
        if self._production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )

        # ── Remove leaky server header if present ─────────────────────────
        try:
            del response.headers["server"]
        except KeyError:
            pass

        return response
