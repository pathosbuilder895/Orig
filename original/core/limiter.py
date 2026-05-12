"""
core/limiter.py — Rate limiting setup using SlowAPI.

Provides a configured Limiter instance and helper decorators
for different rate limit tiers.
"""

from __future__ import annotations

from functools import wraps
from typing import Callable, Optional

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from .config import get_settings

# Create the limiter with remote address as the key
limiter = Limiter(key_func=get_remote_address)


def rate_limit_handler(request: Request, exc: Exception) -> None:
    """
    Handler for rate limit exceeded errors.
    SlowAPI will convert this to a 429 response.
    """
    pass  # SlowAPI handles the response automatically


def get_rate_limit_decorator(rate_limit: str) -> Callable:
    """
    Return a decorator that applies a rate limit.

    Args:
        rate_limit: A string like "5/minute", "100/hour", etc.
    """

    def decorator(func: Callable) -> Callable:
        return limiter.limit(rate_limit)(func)

    return decorator


# Named decorators for common endpoints
def scoring_limit() -> Callable:
    """Rate limit for compute-heavy scoring endpoints."""
    settings = get_settings()
    return get_rate_limit_decorator(settings.RATE_LIMIT_SCORING)


def auth_limit() -> Callable:
    """Rate limit for authentication endpoints (brute-force protection)."""
    settings = get_settings()
    return get_rate_limit_decorator(settings.RATE_LIMIT_AUTH)


def default_limit() -> Callable:
    """Default rate limit for general API endpoints."""
    settings = get_settings()
    return get_rate_limit_decorator(settings.RATE_LIMIT_DEFAULT)
