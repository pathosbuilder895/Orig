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

This is an in-memory store — fine for the single-process demo server. The
production V1 path would persist to SQLite alongside the student store.
Lost on process restart, which is acceptable: Bbook still holds the
authoritative record (the Exam row with externalRequestId), and Original
can re-fetch state via bbook_client.fetch_status() if needed.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Literal, Optional


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


def make_external_id() -> str:
    """Generate a fresh idempotency key (UUID4)."""
    return str(uuid.uuid4())


def record(req: BaselineRequest) -> None:
    """Insert or replace the request in the registry."""
    with _lock:
        _registry[req.external_request_id] = req
        ids = _by_student.setdefault(req.student_id, [])
        if req.external_request_id not in ids:
            ids.append(req.external_request_id)


def get(external_request_id: str) -> Optional[BaselineRequest]:
    with _lock:
        return _registry.get(external_request_id)


def list_pending() -> List[BaselineRequest]:
    """Return all requests with status='pending' (oldest first)."""
    now = time.time()
    out: List[BaselineRequest] = []
    with _lock:
        for r in _registry.values():
            if r.status != "pending":
                continue
            # Auto-expire on read
            if r.expires_at and r.expires_at < now:
                r.status = "expired"
                continue
            out.append(r)
    out.sort(key=lambda r: r.requested_at)
    return out


def list_all() -> List[BaselineRequest]:
    """Return all requests (newest first), regardless of status."""
    with _lock:
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
        ids = _by_student.get(student_id, [])
        for ext_id in ids:
            r = _registry.get(ext_id)
            if r and r.status == "pending":
                r.status = "completed"
                r.completed_at = now
                completed.append(r)
    return completed


def mark_failed(external_request_id: str, error: str) -> None:
    """Mark a single request as failed (Bbook call exploded, etc.)."""
    with _lock:
        r = _registry.get(external_request_id)
        if r:
            r.status = "failed"
            r.error = error
