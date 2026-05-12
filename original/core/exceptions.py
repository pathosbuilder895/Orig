"""
core/exceptions.py — Custom exception classes for the Original API.

All exceptions inherit from OriginalError and include an HTTP status code,
error code, and detail message. FastAPI exception handlers convert these
to standardized JSON responses.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from .logging import get_logger, _request_id

log = get_logger(__name__)


class OriginalError(Exception):
    """Base exception for all Original API errors."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "internal_error"
    detail: str = "An internal error occurred"

    def __init__(
        self,
        detail: Optional[str] = None,
        error_code: Optional[str] = None,
        status_code: Optional[int] = None,
    ) -> None:
        if detail is not None:
            self.detail = detail
        if error_code is not None:
            self.error_code = error_code
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.detail)


class NotFoundError(OriginalError):
    """404 — Resource not found."""

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"
    detail = "Resource not found"


class ConflictError(OriginalError):
    """409 — Resource already exists."""

    status_code = status.HTTP_409_CONFLICT
    error_code = "conflict"
    detail = "Resource already exists"


class AuthError(OriginalError):
    """401 — Authentication failed."""

    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "auth_error"
    detail = "Authentication failed"


class ForbiddenError(OriginalError):
    """403 — Insufficient permissions."""

    status_code = status.HTTP_403_FORBIDDEN
    error_code = "forbidden"
    detail = "Insufficient permissions"


class ValidationError(OriginalError):
    """422 — Request validation failed."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "validation_error"
    detail = "Request validation failed"


class InsufficientBaselineError(OriginalError):
    """422 — Student has insufficient baseline samples for scoring."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "insufficient_baseline"
    detail = "Student has insufficient baseline samples for reliable scoring"


async def original_error_handler(
    request: Request, exc: OriginalError
) -> JSONResponse:
    """Convert OriginalError to JSON response."""
    request_id = _request_id.get() or "unknown"
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error_code": exc.error_code,
            "detail": exc.detail,
            "request_id": request_id,
        },
    )


async def generic_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Fallback handler for unhandled exceptions."""
    request_id = _request_id.get() or "unknown"
    log.error(
        "unhandled_exception",
        extra={
            "error_type": type(exc).__name__,
            "error_detail": str(exc),
        },
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error_code": "internal_error",
            "detail": "An internal error occurred. Please contact support.",
            "request_id": request_id,
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all custom exception handlers with the FastAPI app."""
    app.add_exception_handler(OriginalError, original_error_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
