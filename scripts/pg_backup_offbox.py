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
   same no-op-without-config rule). With BACKUP_ENCRYPTION_KEY set (required
   whenever an upload is configured) the dump is Fernet-encrypted first and
   only the .fernet file is uploaded; --restore decrypts a .fernet file with the same
   key. With upload configured and no key the run fails before it reads the
   database, so a plaintext dump is never uploaded. A file written with
   ``--out`` is an unencrypted local copy.
3. **Restore** (``--restore FILE``) loads a dump into an EMPTY database that
   ``alembic upgrade head`` has provisioned, through each migrator's
   ``to_model`` in ``MIGRATORS`` order (tenants first, flushing per table for
   foreign keys) — the cutover tool's own write path. It refuses a database
   that already holds rows, and then re-reads every table and compares
   checksums against the dump, so a restore reports parity the same way a
   cutover does.
4. **Download** (``--download-latest DEST_DIR``) lists the bucket under
   ``BACKUP_OFFBOX_PREFIX``, picks the newest ``original-pg-*.jsonl.gz.fernet``
   by the timestamp in its name, saves it in DEST_DIR and prints its path, for
   ``--restore`` to take. It needs the bucket settings but not DATABASE_URL or
   BACKUP_OFFBOX_ENABLED.

Values the canonical rows carry that JSON cannot (bytes, datetimes) are tagged
so a restore gets back exactly the type it dumped.

Usage:
    DATABASE_URL=... scripts/pg_backup_offbox.py                  # dump + upload
    DATABASE_URL=... scripts/pg_backup_offbox.py --out FILE       # dump only
    DATABASE_URL=... scripts/pg_backup_offbox.py --restore FILE   # restore drill
    BACKUP_OFFBOX_*=... scripts/pg_backup_offbox.py --download-latest DIR  # fetch for the drill

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
import re
import sys
import tempfile
import urllib.error
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

if __package__ in (None, ""):  # run as a file: make `scripts` and `original` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.backup_offbox import (  # noqa: E402
    OffboxConfig,
    download_latest,
    list_keys,
    upload,
)
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


# ── Encryption ────────────────────────────────────────────────────────────────
# The dump holds every student answer. It is encrypted before it leaves
# Render, with a key that lives only in Render's env and the owner's password
# manager, so the bucket provider never holds readable student text.

ENC_SUFFIX = ".fernet"


def encrypt_file(src: Path, key: str) -> Path:
    from cryptography.fernet import Fernet

    dst = src.with_name(src.name + ENC_SUFFIX)
    dst.write_bytes(Fernet(key.encode()).encrypt(src.read_bytes()))
    return dst


def decrypt_file(src: Path, key: str, dst: Path) -> Path:
    from cryptography.fernet import Fernet, InvalidToken

    try:
        dst.write_bytes(Fernet(key.encode()).decrypt(src.read_bytes()))
    except InvalidToken as exc:
        raise ValueError(f"{src} could not be decrypted with BACKUP_ENCRYPTION_KEY") from exc
    return dst


# ── Download (restore drill) ──────────────────────────────────────────────────
# Fetches the newest encrypted dump back out of the bucket with the same SigV4
# client the upload uses (scripts/backup_offbox.py list_keys/download_latest).

BACKUP_NAME = re.compile(
    re.escape(FILE_PREFIX) + r"(\d{8}T\d{6}Z)\.jsonl\.gz" + re.escape(ENC_SUFFIX)
)
# One ListObjectsV2 call returns at most this many keys, oldest name first, and
# list_keys() does not page. The checklist's 35-day lifecycle rule keeps the
# bucket far below it; a listing this long may be missing the newest dumps.
LIST_PAGE_LIMIT = 1000


def newest_backup_key(keys: list[str], prefix: str) -> str | None:
    """The newest encrypted dump directly under ``prefix``, judged by the
    timestamp in its file name, or None when no key matches."""
    newest, newest_at = None, None
    for key in keys:
        if not key.startswith(prefix):
            continue
        match = BACKUP_NAME.fullmatch(key[len(prefix) :])
        if match is None:
            continue
        try:
            at = datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ")
        except ValueError:  # shaped like a timestamp but not one (month 13)
            continue
        if newest_at is None or at > newest_at:
            newest, newest_at = key, at
    return newest


def download_newest(cfg: OffboxConfig, dest_dir: Path) -> Path:
    """Download the newest encrypted dump under ``cfg.prefix`` into
    ``dest_dir`` (created if needed) and return the local path. Raises
    LookupError when nothing under the prefix matches."""
    keys = list_keys(cfg)
    if len(keys) >= LIST_PAGE_LIMIT:
        log.warning(
            "pg download: the listing returned %d keys, the most one request returns; "
            "newer backups may be missing from it. Check the bucket's lifecycle rule.",
            len(keys),
        )
    key = newest_backup_key(keys, cfg.prefix)
    if key is None:
        raise LookupError(
            f"no {FILE_PREFIX}*.jsonl.gz{ENC_SUFFIX} object under {cfg.bucket}/{cfg.prefix} "
            "(the original-pg-backup job uses BACKUP_OFFBOX_PREFIX=original-pg-backups/)"
        )
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / key[len(cfg.prefix) :]
    download_latest(cfg, dest, key)
    return dest


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


def _download_latest_cli(dest_dir: Path) -> int:
    """--download-latest: needs the bucket settings only. BACKUP_OFFBOX_ENABLED
    gates the scheduled upload, so a download does not require it."""
    cfg = OffboxConfig(os.environ)
    missing = cfg.missing()
    if missing:
        log.error("pg download: bucket not configured (missing %s).", ", ".join(missing))
        return 1
    try:
        path = download_newest(cfg, dest_dir)
    except (LookupError, urllib.error.URLError, OSError, RuntimeError) as exc:
        log.error("pg download: %s", exc)
        return 1
    print(path)  # stdout carries only the path, so a shell can capture it
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--out", help="write the dump here (kept); default is a temp file, uploaded then removed"
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--restore", metavar="FILE", help="restore FILE into an empty database and verify it"
    )
    action.add_argument(
        "--download-latest",
        metavar="DEST_DIR",
        help="download the newest encrypted backup from the bucket into DEST_DIR and print "
        "its path (restore drill; needs the BACKUP_OFFBOX_* bucket settings, not DATABASE_URL)",
    )
    parser.add_argument(
        "--require-upload",
        action="store_true",
        help="fail (exit 1) instead of no-op when upload is not configured — for the scheduled job",
    )
    args = parser.parse_args(argv)

    if args.download_latest:
        return _download_latest_cli(Path(args.download_latest))

    if not os.environ.get("DATABASE_URL", "").strip():
        log.error("pg backup: DATABASE_URL is not set.")
        return 1
    key = os.environ.get("BACKUP_ENCRYPTION_KEY", "").strip()

    from original.db.postgres_session import session_scope

    if args.restore:
        src = Path(args.restore)
        decrypted: Path | None = None
        try:
            if src.name.endswith(ENC_SUFFIX):
                if not key:
                    raise ValueError(f"{src} is encrypted and BACKUP_ENCRYPTION_KEY is not set")
                # A fresh 0600 file, not a predictable name in a shared temp dir.
                fd, tmp_name = tempfile.mkstemp(suffix=".jsonl.gz")
                os.close(fd)
                decrypted = Path(tmp_name)
                src = decrypt_file(src, key, decrypted)
            report = restore(session_scope, src)
        except (OSError, ValueError, RuntimeError) as exc:
            log.error("pg restore: %s", exc)
            return 1
        finally:
            if decrypted is not None:  # never leave the plaintext dump behind
                decrypted.unlink(missing_ok=True)
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
    if cfg.ready() and not key:
        # The bucket must never hold readable student text, so an upload without
        # a key is refused whether or not --require-upload was passed.
        log.error(
            "pg backup: upload is configured but BACKUP_ENCRYPTION_KEY is not set — "
            "refusing to upload an unencrypted dump."
        )
        return 1
    if cfg.ready():
        # Reject a malformed key now, not after the full database read.
        from cryptography.fernet import Fernet

        try:
            Fernet(key.encode())
        except ValueError as exc:
            log.error("pg backup: BACKUP_ENCRYPTION_KEY is not a valid Fernet key: %s", exc)
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
            enc = encrypt_file(path, key)  # the key is guaranteed set above
            try:
                upload(cfg, enc)  # stored under its own file name
            finally:
                enc.unlink(missing_ok=True)
        elif args.out:
            log.info("pg backup: upload not configured — dump kept locally only.")
    except (urllib.error.URLError, OSError, RuntimeError, ValueError) as exc:
        log.error("pg backup: failed: %s", exc)
        return 1
    finally:
        if not keep and path.exists():
            path.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
