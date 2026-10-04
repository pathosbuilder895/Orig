"""Tests for scripts/pg_backup_offbox.py — the off-box logical Postgres backup.

The unit tests need no database. The round-trip test (marked ``postgres``)
seeds every live table through the cutover tool, dumps it, wipes the schema,
restores the dump, and requires per-table checksum parity — the restore drill
docs/BLUEBOOK_LAUNCH_CHECKLIST.md asks an operator to run.
"""

from __future__ import annotations

import gzip
import json
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from scripts import pg_backup_offbox as pgb
from scripts.migrate_sqlite_to_pg import MIGRATORS
from tests.test_migration import fresh_pg, seeded_sqlite  # noqa: F401  (fixtures re-used)

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _empty_rows():
    return {m.name: [] for m in MIGRATORS}


# ── Encoding ──────────────────────────────────────────────────────────────────


def test_encode_decode_round_trips_types_json_would_lose():
    value = {
        "blob": b"\x00\xffstate",
        "when": NOW,
        "day": date(2026, 10, 1),
        "amount": Decimal("1.50"),
        "nested": [{"at": NOW}, 3, "x", None, True],
        "plain": {"a": 1},
    }
    wire = json.loads(json.dumps(pgb._encode(value)))
    assert pgb._decode(wire) == value


def test_encode_accepts_memoryview_and_tuple():
    assert pgb._decode(pgb._encode(memoryview(b"ab"))) == b"ab"
    assert pgb._encode((1, 2)) == [1, 2]


def test_decode_leaves_an_ordinary_one_key_dict_alone():
    assert pgb._decode({"type": "blur"}) == {"type": "blur"}


# ── Dump file ─────────────────────────────────────────────────────────────────


def test_write_then_read_dump_round_trips(tmp_path):
    rows = _empty_rows()
    rows["tenants"] = [{"tenant_id": "t1", "created_at": NOW, "meta": {"plan": "self_serve"}}]
    rows["audit_log"] = [{"id": 1, "at": NOW}, {"id": 2, "at": NOW}]
    path = tmp_path / "dump.jsonl.gz"
    header = pgb.write_dump(rows, path, NOW)

    assert header["format"] == pgb.FORMAT
    assert header["created_at"] == NOW.isoformat()
    assert header["tables"]["audit_log"]["rows"] == 2
    assert set(header["tables"]) == {m.name for m in MIGRATORS}

    got_header, got_rows = pgb.read_dump(path)
    assert got_header == header
    assert got_rows["tenants"] == rows["tenants"]
    assert got_rows["audit_log"] == rows["audit_log"]


def test_read_dump_rejects_a_file_that_is_not_a_backup(tmp_path):
    path = tmp_path / "junk.gz"
    with gzip.open(path, "wt") as fh:
        fh.write("not json\n")
    with pytest.raises(ValueError, match="unreadable header"):
        pgb.read_dump(path)

    with gzip.open(path, "wt") as fh:
        fh.write(json.dumps({"format": "something-else", "version": 1}) + "\n")
    with pytest.raises(ValueError, match="is not a"):
        pgb.read_dump(path)


def test_read_dump_rejects_an_unknown_table(tmp_path):
    path = tmp_path / "dump.jsonl.gz"
    pgb.write_dump(_empty_rows(), path, NOW)
    with gzip.open(path, "at") as fh:
        fh.write(json.dumps({"table": "not_a_table", "row": {}}) + "\n")
    with pytest.raises(ValueError, match="unknown table"):
        pgb.read_dump(path)


def test_dump_filename_is_timestamped():
    assert pgb.dump_filename(NOW) == "original-pg-20261001T120000Z.jsonl.gz"


# ── Restore guards (no database) ──────────────────────────────────────────────


class _FakeSession:
    pass


def _fake_scope():
    @contextmanager
    def scope():
        yield _FakeSession()

    return scope


def test_restore_refuses_a_non_empty_target(tmp_path, monkeypatch):
    path = tmp_path / "dump.jsonl.gz"
    pgb.write_dump(_empty_rows(), path, NOW)
    occupied = _empty_rows()
    occupied["tenants"] = [{"tenant_id": "already-here"}]
    monkeypatch.setattr(pgb, "read_all", lambda session: occupied)
    with pytest.raises(RuntimeError, match="not empty"):
        pgb.restore(_fake_scope(), path)


# ── CLI ───────────────────────────────────────────────────────────────────────

_OFFBOX = {
    "BACKUP_OFFBOX_ENABLED": "1",
    "BACKUP_OFFBOX_BUCKET": "bucket",
    "BACKUP_OFFBOX_ENDPOINT": "https://s3.example.test",
    "BACKUP_OFFBOX_ACCESS_KEY_ID": "AKIDEXAMPLE",
    "BACKUP_OFFBOX_SECRET_ACCESS_KEY": "test-secret",
}


@pytest.fixture
def cli_env(monkeypatch):
    for key in list(_OFFBOX) + ["DATABASE_URL"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/unused")
    import original.db.postgres_session as ps

    monkeypatch.setattr(ps, "session_scope", _fake_scope())
    rows = _empty_rows()
    rows["tenants"] = [{"tenant_id": "t1"}]
    monkeypatch.setattr(pgb, "read_all", lambda session: rows)
    return monkeypatch


def test_main_fails_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert pgb.main([]) == 1


def test_main_is_a_no_op_when_upload_is_not_configured(cli_env, tmp_path):
    uploads = []
    cli_env.setattr(pgb, "upload", lambda cfg, path: uploads.append(path))
    assert pgb.main([]) == 0
    assert uploads == []


def test_main_reports_missing_upload_settings_as_a_no_op(cli_env):
    cli_env.setenv("BACKUP_OFFBOX_ENABLED", "1")
    assert pgb.main([]) == 0


def test_main_require_upload_fails_when_not_configured(cli_env):
    assert pgb.main(["--require-upload"]) == 1
    cli_env.setenv("BACKUP_OFFBOX_ENABLED", "1")
    assert pgb.main(["--require-upload"]) == 1


def test_main_keeps_a_local_dump_with_out_and_no_upload(cli_env, tmp_path):
    out = tmp_path / "kept.jsonl.gz"
    assert pgb.main(["--out", str(out)]) == 0
    _, rows = pgb.read_dump(out)
    assert rows["tenants"] == [{"tenant_id": "t1"}]


def test_main_uploads_then_removes_the_temp_dump(cli_env):
    for k, v in _OFFBOX.items():
        cli_env.setenv(k, v)
    uploaded = []

    def fake_upload(cfg, path):
        assert path.exists()
        assert path.name.startswith(pgb.FILE_PREFIX)
        uploaded.append(path)

    cli_env.setattr(pgb, "upload", fake_upload)
    assert pgb.main(["--require-upload"]) == 0
    assert len(uploaded) == 1
    assert not uploaded[0].exists()


def test_main_returns_1_when_the_upload_fails(cli_env):
    for k, v in _OFFBOX.items():
        cli_env.setenv(k, v)

    def boom(cfg, path):
        raise RuntimeError("off-box upload failed: HTTP 403")

    cli_env.setattr(pgb, "upload", boom)
    assert pgb.main([]) == 1


def test_main_restore_reports_parity(cli_env, tmp_path):
    path = tmp_path / "dump.jsonl.gz"
    pgb.write_dump(_empty_rows(), path, NOW)
    cli_env.setattr(
        pgb,
        "restore",
        lambda scope, p: {
            "parity": True,
            "tables": [{"table": "tenants", "expected": 0, "restored": 0, "ok": True}],
        },
    )
    assert pgb.main(["--restore", str(path)]) == 0
    cli_env.setattr(
        pgb,
        "restore",
        lambda scope, p: {
            "parity": False,
            "tables": [{"table": "tenants", "expected": 1, "restored": 0, "ok": False}],
        },
    )
    assert pgb.main(["--restore", str(path)]) == 1


def test_main_restore_fails_cleanly_on_a_bad_file(cli_env, tmp_path):
    assert pgb.main(["--restore", str(tmp_path / "missing.jsonl.gz")]) == 1


# ── Round trip through a real Postgres ────────────────────────────────────────


@pytest.mark.postgres
def test_dump_wipe_restore_round_trip_has_parity(seeded_sqlite, fresh_pg, tmp_path):  # noqa: F811
    from original.db import postgres_session
    from original.db.models.live import LiveBase
    from original.db.postgres_session import session_scope
    from scripts.migrate_sqlite_to_pg import migrate

    assert migrate(seeded_sqlite)["parity"] is True
    with session_scope() as session:
        before = pgb.read_all(session)
    assert sum(len(r) for r in before.values()) > 0

    path = tmp_path / "dump.jsonl.gz"
    pgb.write_dump(before, path)

    engine = postgres_session.get_engine()
    LiveBase.metadata.drop_all(bind=engine)
    LiveBase.metadata.create_all(bind=engine)

    report = pgb.restore(session_scope, path)
    assert report["parity"] is True, report
    assert {t["table"] for t in report["tables"]} == {m.name for m in MIGRATORS}

    with pytest.raises(RuntimeError, match="not empty"):
        pgb.restore(session_scope, path)
