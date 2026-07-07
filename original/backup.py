"""
In-app SQLite backup scheduler.

Render web services have no crontab and Render cron-job services cannot mount
another service's persistent disk, so the runbook's ``backup_db.sh`` cron has
nowhere to run in production. This module does the same consistent online
backup (SQLite ``.backup`` API — safe under WAL while the server is running,
never ``cp``) from inside the web process, on an asyncio timer started by the
API lifespan.

Configuration (env):
    BACKUP_DIR              destination directory. Empty → disabled in demo;
                            defaults to ``<db dir>/backups`` on real deploys
                            (pilot/staging/production).
    BACKUP_INTERVAL_MINUTES timer period (default 30).
    BACKUP_KEEP             newest copies retained after pruning (default 48).

``scripts/backup_db.sh`` remains the manual/local tool; both write the same
``profiles-YYYYmmdd-HHMMSS.db`` naming scheme so the preflight recency check
and the restore drill work identically against either producer.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

BACKUP_PREFIX = "profiles-"


def resolve_backup_dir(db_path: Path, is_real_deploy: bool) -> Path | None:
    """The destination directory, or None when backups are disabled.

    Explicit ``BACKUP_DIR`` always wins (any environment). Otherwise real
    deploys default to a ``backups/`` sibling of the database so the pilot
    is protected even if the operator forgets the env var; demo stays off.
    """
    raw = os.environ.get("BACKUP_DIR", "").strip()
    if raw:
        return Path(raw)
    if is_real_deploy:
        return db_path.parent / "backups"
    return None


def run_backup(db_path: Path, dest_dir: Path, keep: int = 48) -> Path | None:
    """One consistent online backup + prune. Never raises.

    Returns the path written, or None (missing DB / failure — logged).
    """
    try:
        if not db_path.exists():
            log.info("backup: no database at %s — nothing to back up", db_path)
            return None
        dest_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = dest_dir / f"{BACKUP_PREFIX}{ts}.db"
        src = sqlite3.connect(str(db_path), timeout=10.0)
        try:
            dst = sqlite3.connect(str(out))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        pruned = _prune(dest_dir, keep)
        log.info("backup: wrote %s (pruned %d old)", out.name, pruned)
        return out
    except Exception:
        log.exception("backup: failed for %s -> %s", db_path, dest_dir)
        return None


def _prune(dest_dir: Path, keep: int) -> int:
    """Delete all but the newest ``keep`` backups. Returns count removed."""
    backups = sorted(
        dest_dir.glob(f"{BACKUP_PREFIX}*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for old in backups[max(keep, 1) :]:
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def latest_backup_age_seconds(dest_dir: Path | None) -> float | None:
    """Age of the newest backup, or None when none exist / backups disabled."""
    if dest_dir is None or not dest_dir.is_dir():
        return None
    newest = None
    for p in dest_dir.glob(f"{BACKUP_PREFIX}*.db"):
        mtime = p.stat().st_mtime
        if newest is None or mtime > newest:
            newest = mtime
    if newest is None:
        return None
    return max(0.0, time.time() - newest)


async def backup_loop(db_path: Path, dest_dir: Path, interval_minutes: float, keep: int) -> None:
    """Run forever: back up immediately, then every ``interval_minutes``.

    The immediate first run means a fresh deploy has a backup within seconds,
    and the preflight/monitoring age check is meaningful from minute one.
    run_backup() never raises, so the loop only exits via cancellation.
    """
    while True:
        await asyncio.to_thread(run_backup, db_path, dest_dir, keep)
        await asyncio.sleep(max(60.0, interval_minutes * 60.0))
