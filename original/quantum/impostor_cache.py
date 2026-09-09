"""Short-lived cache for report-only characteristic-weight shadow pools.

The enabled scoring mode deliberately does not use this cache. Shadow mode
only needs a representative preview, while repeatedly deserializing the full
profile table on every request is an avoidable soak cost.
"""

from __future__ import annotations

import time
from threading import Lock

from ..principal import tenant_of

TTL_SECONDS = 30.0
_CACHE: dict[tuple[str | None, str], tuple[float, object]] = {}
_LOCK = Lock()


def get(student_id: str):
    key = (tenant_of(student_id), student_id)
    with _LOCK:
        item = _CACHE.get(key)
        if item is None:
            return False, None
        created, value = item
        if time.monotonic() - created > TTL_SECONDS:
            _CACHE.pop(key, None)
            return False, None
        return True, value


def put(student_id: str, value) -> None:
    with _LOCK:
        _CACHE[(tenant_of(student_id), student_id)] = (time.monotonic(), value)


def invalidate(student_id: str | None = None) -> None:
    """Bust one tenant after a baseline write, or everything in tests/ops."""
    with _LOCK:
        if student_id is None:
            _CACHE.clear()
            return
        tenant = tenant_of(student_id)
        for key in [key for key in _CACHE if key[0] == tenant]:
            _CACHE.pop(key, None)
