"""
baseline_requests.py — in-memory registry of pending proctored baseline requests.

When a professor on professor.html clicks "Request proctored baseline" for a
student, Original POSTs to Bbook to provision a one-off magic-link exam, then
records the outstanding request here. The demo dashboard polls
GET /baseline-requests/pending to render a "Pending baselines" widget.

When a matching baseline (provenance='proctored') is subsequently added for
that student via /students/{id}/baseline (the Phase 1 sync handoff from
Bbook), we auto-mark the request as 'completed' so it disappears from the
pending list.

The registry is durable: every mutation writes through to SQLite (via
``original.store``), and the in-memory cache is hydrated from SQLite on first
use. Pending requests therefore survive a process restart. Bbook still holds
the authoritative record (the Exam row with externalRequestId), so SQLite is a
fast local mirror, not the source of truth.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, asdict, field, fields as dataclass_fields
from typing import Dict, List, Literal, Optional

from . import store

log = logging.getLogger(__name__)


Status = Literal["pending", "completed", "expired", "failed"]


@dataclass
class BaselineRequest:
    external_request_id: str
    student_id: str
    student_email: str
    student_name: str
    exam_title: str
    bbook_exam_id: Optional[str]
    magic_link: Optional[str]
    requested_at: float                # unix epoch seconds
    expires_at: Optional[float]        # unix epoch seconds; None if unknown
    requested_by: Optional[str] = None
    status: Status = "pending"
    completed_at: Optional[float] = None
    email_delivered: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        # Stable ISO datetimes for the frontend
        d["requested_at_iso"] = _iso(self.requested_at)
        d["expires_at_iso"] = _iso(self.expires_at) if self.expires_at else None
        d["completed_at_iso"] = _iso(self.completed_at) if self.completed_at else None
        return d


def _iso(epoch: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


# ── Module-level registry ────────────────────────────────────────────────────

_lock = threading.Lock()
_registry: Dict[str, BaselineRequest] = {}   # external_request_id → request
_by_student: Dict[str, List[str]] = {}       # student_id → list of external_request_ids
_hydrated = False


_FIELD_NAMES = {f.name for f in dataclass_fields(BaselineRequest)}


def _persist(req: BaselineRequest) -> None:
    """Write a request through to durable storage (best-effort)."""
    try:
        store.put_baseline_request(
            external_request_id=req.external_request_id,
            student_id=req.student_id,
            status=req.status,
            requested_at=req.requested_at,
            data_json=json.dumps(asdict(req)),
        )
    except Exception:
        log.exception("persist baseline request %s failed", req.external_request_id)


def _ensure_hydrated() -> None:
    """Load persisted requests into the in-memory cache once, on first use."""
    global _hydrated
    if _hydrated:
        return
    try:
        for d in store.load_baseline_requests():
            payload = {k: v for k, v in d.items() if k in _FIELD_NAMES}
            req = BaselineRequest(**payload)
            _registry[req.external_request_id] = req
            _by_student.setdefault(req.student_id, []).append(req.external_request_id)
    except Exception:
        log.exception("hydrate baseline requests failed")
    finally:
        _hydrated = True


def _reset_cache() -> None:
    """Test hook — drop the in-memory cache so the next call re-hydrates."""
    global _hydrated
    with _lock:
        _registry.clear()
        _by_student.clear()
        _hydrated = False


def make_external_id() -> str:
    """Generate a fresh idempotency key (UUID4)."""
    return str(uuid.uuid4())


def record(req: BaselineRequest) -> None:
    """Insert or replace the request in the registry (and persist it)."""
    with _lock:
        _ensure_hydrated()
        _registry[req.external_request_id] = req
        ids = _by_student.setdefault(req.student_id, [])
        if req.external_request_id not in ids:
            ids.append(req.external_request_id)
    _persist(req)


def get(external_request_id: str) -> Optional[BaselineRequest]:
    with _lock:
        _ensure_hydrated()
        return _registry.get(external_request_id)


def list_pending() -> List[BaselineRequest]:
    """Return all requests with status='pending' (oldest first)."""
    now = time.time()
    out: List[BaselineRequest] = []
    expired: List[BaselineRequest] = []
    with _lock:
        _ensure_hydrated()
        for r in _registry.values():
            if r.status != "pending":
                continue
            # Auto-expire on read
            if r.expires_at and r.expires_at < now:
                r.status = "expired"
                expired.append(r)
                continue
            out.append(r)
    for r in expired:          # persist the expiry transition
        _persist(r)
    out.sort(key=lambda r: r.requested_at)
    return out


def list_all() -> List[BaselineRequest]:
    """Return all requests (newest first), regardless of status."""
    with _lock:
        _ensure_hydrated()
        items = list(_registry.values())
    items.sort(key=lambda r: r.requested_at, reverse=True)
    return items


def mark_completed_for_student(student_id: str) -> List[BaselineRequest]:
    """
    Mark every pending request for this student as completed.

    Called when a new authenticated baseline (proctored / verified) is
    successfully added — the assumption is that the latest sample fulfils
    any outstanding request. Returns the list of requests that were
    transitioned (empty if none were pending).
    """
    completed: List[BaselineRequest] = []
    now = time.time()
    with _lock:
        _ensure_hydrated()
        ids = _by_student.get(student_id, [])
        for ext_id in ids:
            r = _registry.get(ext_id)
            if r and r.status == "pending":
                r.status = "completed"
                r.completed_at = now
                completed.append(r)
    for r in completed:
        _persist(r)
    return completed


def mark_failed(external_request_id: str, error: str) -> None:
    """Mark a single request as failed (Bbook call exploded, etc.)."""
    target: Optional[BaselineRequest] = None
    with _lock:
        _ensure_hydrated()
        r = _registry.get(external_request_id)
        if r:
            r.status = "failed"
            r.error = error
            target = r
    if target:
        _persist(target)
