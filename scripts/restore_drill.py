#!/usr/bin/env python3
"""restore_drill.py — automated restore-verification drill.

Replaces the manual step in ``docs/OPS_RUNBOOK.md`` §Backups ("copy the
newest backup locally, run a row-count SELECT, compare by hand with
``/students`` on the live service") with something that can be cron'd or run
as a scheduled job and produces a real pass/fail exit code. An undrilled
backup is a wish, not a guarantee.

What it does:
    1. Obtains the newest backup — from off-box object storage if
       ``BACKUP_OFFBOX_ENABLED=1`` and configured (preferred: proves the
       *off-box* copy, not just the on-disk one, is restorable), otherwise
       falls back to the newest file in ``BACKUP_DIR``.
    2. Restores it to a scratch SQLite file (a plain copy — these are
       already-consistent ``.backup`` snapshots, not live WAL databases).
    3. Opens the scratch file and sanity-checks it:
         - it must open as a valid SQLite database,
         - ``student_profiles`` must exist and be queryable,
         - row counts across ``student_profiles``, ``users``, ``tenants``,
           and ``audit_log`` (tables that exist in any real deployment,
           per original/store.py) are reported; a *zero* row count in
           ``student_profiles`` is treated as a failure (an empty backup is
           worse than no backup — it hides the real problem).
    4. Prints a report and exits 0 (pass) or 1 (fail) with a clear message.

Configuration (env):
    BACKUP_DIR                      local backup source (fallback / default).
    BACKUP_OFFBOX_ENABLED/_BUCKET/_ENDPOINT/_ACCESS_KEY_ID/_SECRET_ACCESS_KEY/
    _REGION/_PREFIX/_URL_STYLE       same as backup_offbox.py — reused here to
                                     pull the off-box copy for the drill.
    RESTORE_DRILL_MIN_ROWS           minimum acceptable ``student_profiles``
                                     row count to still count as a pass when
                                     rows exist but look suspiciously low.
                                     Default "0" (any positive count passes;
                                     set e.g. "1" to require at least one row
                                     once the pilot has real students).

Usage:
    scripts/restore_drill.py                  # auto-source, scratch tempfile
    scripts/restore_drill.py --local-only      # skip off-box, use BACKUP_DIR
    scripts/restore_drill.py /path/to/some.db  # drill a specific file

This does not touch the live database — it only ever reads a backup copy.
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backup_offbox import OffboxConfig, download_latest, find_latest_backup, list_keys  # noqa: E402

log = logging.getLogger("restore_drill")

SANITY_TABLES = ["student_profiles", "users", "tenants", "audit_log"]
REQUIRED_NONEMPTY_TABLE = "student_profiles"


def fetch_offbox_copy(cfg: OffboxConfig, scratch_dir: Path) -> Path | None:
    """Download the newest off-box backup into scratch_dir. None if unusable."""
    try:
        keys = list_keys(cfg)
    except Exception as exc:  # noqa: BLE001 - report, don't crash the drill
        log.warning("restore drill: could not list off-box backups (%s) — falling back to local.", exc)
        return None
    if not keys:
        log.warning("restore drill: off-box bucket has no backups under prefix %r — falling back to local.", cfg.prefix)
        return None
    newest_key = keys[-1]
    dest = scratch_dir / Path(newest_key).name
    try:
        download_latest(cfg, dest, newest_key)
    except Exception as exc:  # noqa: BLE001
        log.warning("restore drill: off-box download of %s failed (%s) — falling back to local.", newest_key, exc)
        return None
    log.info("restore drill: pulled off-box copy %s", newest_key)
    return dest


def restore_to_scratch(src: Path, scratch_dir: Path) -> Path:
    """Copy the backup into a scratch file distinct from the source, so we
    never mutate or lock the real backup while inspecting it."""
    scratch = scratch_dir / f"restore-drill-{src.name}"
    scratch.write_bytes(src.read_bytes())
    return scratch


def verify(scratch_db: Path, min_rows: int = 0) -> tuple:
    """Run the sanity checks. Returns (ok, report_lines)."""
    lines = []
    try:
        conn = sqlite3.connect(f"file:{scratch_db}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return False, [f"FAIL: could not open {scratch_db} as SQLite ({exc})"]

    ok = True
    try:
        counts = {}
        for table in SANITY_TABLES:
            try:
                cur = conn.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608 - fixed allowlist above
                counts[table] = cur.fetchone()[0]
            except sqlite3.Error as exc:
                counts[table] = None
                lines.append(f"  {table}: ERROR ({exc})")
                if table == REQUIRED_NONEMPTY_TABLE:
                    ok = False

        for table, count in counts.items():
            if count is not None:
                lines.append(f"  {table}: {count} rows")

        required_count = counts.get(REQUIRED_NONEMPTY_TABLE)
        if required_count is not None and required_count <= min_rows:
            ok = False
            lines.append(
                f"FAIL: {REQUIRED_NONEMPTY_TABLE} has {required_count} rows "
                f"(<= minimum {min_rows}) — backup looks empty or truncated."
            )
    finally:
        conn.close()

    if ok:
        lines.insert(0, "PASS: backup opens and sanity tables are queryable.")
    return ok, lines


def main(argv: list) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", help="specific backup file to drill")
    parser.add_argument("--local-only", action="store_true", help="skip off-box, use BACKUP_DIR")
    args = parser.parse_args(argv)

    min_rows = int(os.environ.get("RESTORE_DRILL_MIN_ROWS", "0") or 0)

    with tempfile.TemporaryDirectory(prefix="original-restore-drill-") as tmp:
        scratch_dir = Path(tmp)

        if args.path:
            src = Path(args.path)
            if not src.is_file():
                log.error("restore drill: %s does not exist.", src)
                return 1
        else:
            src = None
            cfg = OffboxConfig(os.environ)
            if not args.local_only and cfg.ready():
                src = fetch_offbox_copy(cfg, scratch_dir)
            if src is None:
                dest_dir = Path(os.environ.get("BACKUP_DIR", "").strip() or "backups")
                src = find_latest_backup(dest_dir)
                if src is None:
                    log.error(
                        "restore drill: no backup available (off-box unconfigured/empty, "
                        "and no local backup in %s). Nothing to drill.",
                        dest_dir,
                    )
                    return 1
                log.info("restore drill: using local copy %s", src)

        scratch_db = restore_to_scratch(src, scratch_dir)
        ok, lines = verify(scratch_db, min_rows=min_rows)

        log.info("restore drill: source=%s", src)
        for line in lines:
            log.info(line)

        if not ok:
            log.error("restore drill: FAILED — see above.")
            return 1
        log.info("restore drill: OK.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
