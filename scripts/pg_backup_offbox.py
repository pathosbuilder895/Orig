#!/usr/bin/env python3
"""pg_backup_offbox.py — logical backup of the live Postgres database, off-box.

The Postgres twin of ``scripts/backup_offbox.py``. Once ``REPO_BACKEND=postgres``
the in-app SQLite backup scheduler is a no-op, and Render's own managed-Postgres
backups live with the same provider as the database. This script writes an
independent copy somewhere else:

1. **Dump.** Every live table is read through the cutover tool's migrators
   (``scripts/migrate_sqlite_to_pg.py`` ``MIGRATORS``, ``read_pg``) — the same
   canonical rows its parity check compares — into one gzipped JSON-lines file:
   a header line, then one ``{"table": ..., "row": ...}`` line per row.
2. **Upload.** The file is PUT to S3-compatible storage with the SigV4 signer
   in ``scripts/backup_offbox.py`` (same ``BACKUP_OFFBOX_*`` configuration,
   same no-op-without-config rule).
3. **Restore** (``--restore FILE``) loads a dump into an EMPTY database that
   ``alembic upgrade head`` has provisioned, through each migrator's
   ``to_model`` in ``MIGRATORS`` order (tenants first, flushing per table for
   foreign keys) — the cutover tool's own write path. It refuses a database
   that already holds rows, and then re-reads every table and compares
   checksums against the dump, so a restore reports parity the same way a
   cutover does.

Values the canonical rows carry that JSON cannot (bytes, datetimes) are tagged
so a restore gets back exactly the type it dumped.

Usage:
    DATABASE_URL=... scripts/pg_backup_offbox.py                  # dump + upload
    DATABASE_URL=... scripts/pg_backup_offbox.py --out FILE       # dump only
    DATABASE_URL=... scripts/pg_backup_offbox.py --restore FILE   # restore drill

Exit codes: 0 on success or a clean no-op (upload disabled/unconfigured — the
dump is still written when ``--out`` is given), 1 on any failure. The scheduled
job passes ``--require-upload`` so a missing bucket setting is a failure Render
shows, not a silent nightly no-op.

Intended wiring: the ``original-pg-backup`` cron job in ``render.yaml``, daily.
See docs/BLUEBOOK_LAUNCH_CHECKLIST.md for the bucket setup and restore drill.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import logging
import os
import sys
import tempfile
import urllib.error
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

if __package__ in (None, ""):  # run as a file: make `scripts` and `original` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.backup_offbox import OffboxConfig, upload  # noqa: E402
from scripts.migrate_sqlite_to_pg import MIGRATORS, _checksum  # noqa: E402

log = logging.getLogger("pg_backup_offbox")

FORMAT = "original-pg-logical-backup"
FORMAT_VERSION = 1
FILE_PREFIX = "original-pg-"


# ── Encoding ──────────────────────────────────────────────────────────────────


def _encode(value):
    """JSON-safe form of a canonical-row value, tagged when JSON would lose
    the type."""
    if isinstance(value, bytes | bytearray | memoryview):
        return {"__bytes__": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, date):
        return {"__date__": value.isoformat()}
    if isinstance(value, Decimal):
        return {"__decimal__": str(value)}
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_encode(v) for v in value]
    return value


def _decode(value):
    if isinstance(value, dict):
        if len(value) == 1:
            ((tag, raw),) = value.items()
            if tag == "__bytes__":
                return base64.b64decode(raw)
            if tag == "__datetime__":
                return datetime.fromisoformat(raw)
            if tag == "__date__":
                return date.fromisoformat(raw)
            if tag == "__decimal__":
                return Decimal(raw)
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


# ── Dump ──────────────────────────────────────────────────────────────────────


def read_all(session) -> dict[str, list[dict]]:
    """Every live table's canonical rows, keyed by migrator name."""
    return {m.name: m.read_pg(session) for m in MIGRATORS}


def write_dump(rows: dict[str, list[dict]], path: Path, now: datetime | None = None) -> dict:
    """Write ``rows`` as gzipped JSON lines. Returns the header (with per-table
    counts and checksums)."""
    now = now or datetime.now(UTC)
    header = {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "created_at": now.isoformat(),
        "tables": {
            m.name: {"rows": len(rows[m.name]), "checksum": _checksum(rows[m.name], m.pk)}
            for m in MIGRATORS
        },
    }
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps(header, sort_keys=True) + "\n")
        for m in MIGRATORS:
            for row in rows[m.name]:
                fh.write(
                    json.dumps(
                        {"table": m.name, "row": _encode(row)}, sort_keys=True, ensure_ascii=False
                    )
                    + "\n"
                )
    return header


def read_dump(path: Path) -> tuple[dict, dict[str, list[dict]]]:
    """(header, rows by table) from a dump file. Raises ValueError on a file
    that is not one of ours, or names a table this code does not know."""
    known = {m.name for m in MIGRATORS}
    rows: dict[str, list[dict]] = {name: [] for name in known}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        first = fh.readline()
        try:
            header = json.loads(first)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} is not a backup (unreadable header)") from exc
        if header.get("format") != FORMAT or header.get("version") != FORMAT_VERSION:
            raise ValueError(f"{path} is not a {FORMAT} v{FORMAT_VERSION} file")
        for line in fh:
            item = json.loads(line)
            if item["table"] not in known:
                raise ValueError(f"backup names an unknown table: {item['table']}")
            rows[item["table"]].append(_decode(item["row"]))
    return header, rows


def dump_filename(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return f"{FILE_PREFIX}{now.strftime('%Y%m%dT%H%M%SZ')}.jsonl.gz"


# ── Restore ───────────────────────────────────────────────────────────────────


def restore(session_scope, path: Path) -> dict:
    """Load ``path`` into an empty database, then verify per-table parity.

    Returns {"parity": bool, "tables": [{table, expected, restored, ok}]}.
    Raises RuntimeError if the target already holds any rows."""
    header, rows = read_dump(path)
    with session_scope() as session:
        present = {name: len(r) for name, r in read_all(session).items() if r}
    if present:
        raise RuntimeError(f"restore target is not empty: {present}")

    with session_scope() as session:
        # Per-table flush, tenants first, for the same FK reason migrate() gives.
        for m in MIGRATORS:
            for row in rows[m.name]:
                session.add(m.to_model(row))
            session.flush()

    with session_scope() as session:
        after = read_all(session)
    tables, all_ok = [], True
    for m in MIGRATORS:
        expected = header["tables"].get(m.name, {"rows": 0, "checksum": _checksum([], m.pk)})
        got = {"rows": len(after[m.name]), "checksum": _checksum(after[m.name], m.pk)}
        ok = expected == got
        all_ok = all_ok and ok
        tables.append(
            {"table": m.name, "expected": expected["rows"], "restored": got["rows"], "ok": ok}
        )
    return {"parity": all_ok, "tables": tables}


# ── CLI ───────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--out", help="write the dump here (kept); default is a temp file, uploaded then removed"
    )
    parser.add_argument(
        "--restore", metavar="FILE", help="restore FILE into an empty database and verify it"
    )
    parser.add_argument(
        "--require-upload",
        action="store_true",
        help="fail (exit 1) instead of no-op when upload is not configured — for the scheduled job",
    )
    args = parser.parse_args(argv)

    if not os.environ.get("DATABASE_URL", "").strip():
        log.error("pg backup: DATABASE_URL is not set.")
        return 1

    from original.db.postgres_session import session_scope

    if args.restore:
        try:
            report = restore(session_scope, Path(args.restore))
        except (OSError, ValueError, RuntimeError) as exc:
            log.error("pg restore: %s", exc)
            return 1
        for t in report["tables"]:
            log.info(
                "  %-28s %6d / %-6d %s",
                t["table"],
                t["restored"],
                t["expected"],
                "ok" if t["ok"] else "MISMATCH",
            )
        log.info("restore parity: %s", "OK" if report["parity"] else "FAILED")
        return 0 if report["parity"] else 1

    cfg = OffboxConfig(os.environ)
    if args.require_upload and not cfg.ready():
        log.error(
            "pg backup: upload required but not configured (%s).",
            "BACKUP_OFFBOX_ENABLED != 1"
            if not cfg.enabled
            else "missing " + ", ".join(cfg.missing()),
        )
        return 1
    if not args.out and not cfg.ready():
        log.info(
            "pg backup: upload not configured (%s) and no --out given — no-op.",
            "disabled" if not cfg.enabled else "missing " + ", ".join(cfg.missing()),
        )
        return 0

    now = datetime.now(UTC)
    if args.out:
        path, keep = Path(args.out), True
    else:
        path, keep = Path(tempfile.gettempdir()) / dump_filename(now), False
    try:
        with session_scope() as session:
            rows = read_all(session)
        header = write_dump(rows, path, now)
        total = sum(t["rows"] for t in header["tables"].values())
        log.info(
            "pg backup: wrote %d rows across %d tables to %s", total, len(header["tables"]), path
        )
        if cfg.ready():
            upload(cfg, path)  # stored under its own file name
        elif args.out:
            log.info("pg backup: upload not configured — dump kept locally only.")
    except (urllib.error.URLError, OSError, RuntimeError) as exc:
        log.error("pg backup: failed: %s", exc)
        return 1
    finally:
        if not keep and path.exists():
            path.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
