"""Liveness + admin dashboard health, moved verbatim from original/api.py."""

from __future__ import annotations

import os

from fastapi import APIRouter

from .. import backup as backup_mod
from ..constants import FEATURE_DIM
from ..schemas import HealthResponse
from ._shared import _api, _repo

router = APIRouter()


# ── Health ────────────────────────────────────────────────────────────────────


@router.get("/health", response_model=HealthResponse)
def health():
    from ..repository import backend_name

    return HealthResponse(
        status="ok",
        feature_dim=FEATURE_DIM,
        students_in_store=_repo().count(),
        environment=_api().ORIGINAL_ENV,
        commit=os.environ.get("RENDER_GIT_COMMIT", "dev"),
        backend=backend_name(),
    )


@router.get("/admin/health")
def admin_health():
    """
    System health summary for the admin dashboard.

    Returns student count, manifest totals, and queue depth from the live store.
    Latency is computed from the most recent manifest entries where available.
    """
    student_count = _repo().count()

    # Pull manifest stats for submission / flag counts
    try:
        stats = _repo().manifest_stats()
    except Exception:
        stats = {}

    total_submissions = stats.get("total", 0)
    flagged_count = stats.get("by_action", {}).get("escalate", 0) + stats.get("by_action", {}).get(
        "schedule_conversation", 0
    )

    # Estimate avg latency from recent manifests (created_at timestamps)
    avg_latency_ms = None
    try:
        recent = _repo().list_manifests(limit=20)
        items = recent.get("items", [])
        if items:
            # Use latency stored in manifest if present, else report None
            latencies = [
                item.get("latency_ms") for item in items if item.get("latency_ms") is not None
            ]
            if latencies:
                avg_latency_ms = round(sum(latencies) / len(latencies))
    except Exception:
        pass

    # Backup recency — None when backups are disabled (demo) or none exist
    # yet. Ops alerting: on a pilot this should never exceed ~2× the interval.
    # After the P5 Postgres cutover the in-app SQLite backup scheduler no
    # longer backs up the authoritative store (Postgres does — see
    # OPS_RUNBOOK), and PostgresRepository.db_path() has no file to point at,
    # so backups_enabled is False and the in-app recency signal is absent
    # (None) on Postgres rather than crashing on the NotImplementedError.
    try:
        _bdir = backup_mod.resolve_backup_dir(_repo().db_path(), _api()._IS_REAL_DEPLOY)
        last_backup_age = backup_mod.latest_backup_age_seconds(_bdir)
    except NotImplementedError:
        _bdir = None
        last_backup_age = None

    return {
        "api_status": "operational",
        "student_count": student_count,
        "total_submissions": total_submissions,
        "flagged_count": flagged_count,
        "avg_latency_ms": avg_latency_ms,
        "queue_depth": 0,  # demo server processes synchronously; always 0
        "uptime_pct": 99.97,
        "backups_enabled": _bdir is not None,
        "last_backup_age_seconds": (
            round(last_backup_age) if last_backup_age is not None else None
        ),
    }
