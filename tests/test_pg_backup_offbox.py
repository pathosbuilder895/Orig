"""Tests for scripts/pg_backup_offbox.py — the off-box logical Postgres backup.

The unit tests need no database. The round-trip test (marked ``postgres``)
seeds every live table through the cutover tool, dumps it, wipes the schema,
restores the dump, and requires per-table checksum parity — the restore drill
docs/BLUEBOOK_LAUNCH_CHECKLIST.md asks an operator to run.
"""

from __future__ import annotations

import gzip
import json
import tempfile
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from cryptography.fernet import Fernet

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
    "BACKUP_ENCRYPTION_KEY": Fernet.generate_key().decode(),
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

    attempted = []

    def boom(cfg, path):
        attempted.append(path)
        raise RuntimeError("off-box upload failed: HTTP 403")

    cli_env.setattr(pgb, "upload", boom)
    assert pgb.main([]) == 1
    assert len(attempted) == 1
    enc = attempted[0]
    assert enc.name.endswith(pgb.ENC_SUFFIX)
    assert not enc.exists()  # the encrypted copy is cleaned up after a failed upload
    assert not enc.with_name(enc.name[: -len(pgb.ENC_SUFFIX)]).exists()  # and so is the plaintext


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


def test_encrypt_then_decrypt_round_trips(tmp_path):
    key = Fernet.generate_key().decode()
    plain = tmp_path / "dump.jsonl.gz"
    pgb.write_dump(_empty_rows(), plain, NOW)
    enc = pgb.encrypt_file(plain, key)
    assert enc.name == "dump.jsonl.gz.fernet"
    assert enc.read_bytes()[:2] != plain.read_bytes()[:2]
    out = pgb.decrypt_file(enc, key, tmp_path / "back.jsonl.gz")
    assert out.read_bytes() == plain.read_bytes()


def test_decrypt_with_the_wrong_key_raises_a_clear_error(tmp_path):
    plain = tmp_path / "dump.jsonl.gz"
    pgb.write_dump(_empty_rows(), plain, NOW)
    enc = pgb.encrypt_file(plain, Fernet.generate_key().decode())
    with pytest.raises(ValueError, match="could not be decrypted"):
        pgb.decrypt_file(enc, Fernet.generate_key().decode(), tmp_path / "back.jsonl.gz")
    assert not (tmp_path / "back.jsonl.gz").exists()


def test_require_upload_fails_without_an_encryption_key(cli_env):
    for k, v in _OFFBOX.items():
        cli_env.setenv(k, v)
    cli_env.delenv("BACKUP_ENCRYPTION_KEY")
    cli_env.setattr(pgb, "upload", lambda cfg, path: None)
    assert pgb.main(["--require-upload"]) == 1


def test_upload_is_refused_without_a_key_even_when_not_required(cli_env):
    for k, v in _OFFBOX.items():
        cli_env.setenv(k, v)
    cli_env.delenv("BACKUP_ENCRYPTION_KEY")
    reads = []
    cli_env.setattr(pgb, "read_all", lambda session: reads.append(session) or _empty_rows())
    cli_env.setattr(pgb, "upload", lambda cfg, path: pytest.fail("must not upload plaintext"))
    assert pgb.main([]) == 1
    assert pgb.main(["--out", "unused.jsonl.gz"]) == 1
    assert reads == []  # refused before the database was read


def test_main_uploads_only_the_encrypted_file(cli_env):
    for k, v in _OFFBOX.items():
        cli_env.setenv(k, v)
    uploaded = []

    def fake_upload(cfg, path):
        assert path.name.endswith(".jsonl.gz.fernet")
        uploaded.append((path, path.read_bytes()))

    cli_env.setattr(pgb, "upload", fake_upload)
    assert pgb.main(["--require-upload"]) == 0
    assert len(uploaded) == 1
    path, data = uploaded[0]
    assert not path.exists()
    assert not path.with_name(path.name[: -len(".fernet")]).exists()
    assert Fernet(_OFFBOX["BACKUP_ENCRYPTION_KEY"].encode()).decrypt(data)[:2] == b"\x1f\x8b"


def test_a_malformed_encryption_key_fails_fast_before_any_dump(cli_env, tmp_path):
    for k, v in _OFFBOX.items():
        cli_env.setenv(k, v)
    cli_env.setenv("BACKUP_ENCRYPTION_KEY", "not-a-fernet-key")
    cli_env.setattr(tempfile, "tempdir", str(tmp_path))
    cli_env.setattr(
        pgb, "read_all", lambda session: pytest.fail("must not read the database first")
    )
    cli_env.setattr(pgb, "upload", lambda cfg, path: pytest.fail("must not upload"))
    assert pgb.main(["--require-upload"]) == 1
    assert list(tmp_path.iterdir()) == []  # no dump of any kind left behind


def test_restore_decrypts_a_fernet_file(cli_env, tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    cli_env.setattr(tempfile, "tempdir", str(scratch))
    cli_env.setenv("BACKUP_ENCRYPTION_KEY", _OFFBOX["BACKUP_ENCRYPTION_KEY"])
    plain = tmp_path / "dump.jsonl.gz"
    pgb.write_dump(_empty_rows(), plain, NOW)
    enc = pgb.encrypt_file(plain, _OFFBOX["BACKUP_ENCRYPTION_KEY"])
    seen = []

    def fake_restore(scope, p):
        seen.append((pgb.read_dump(p)[0]["format"], p.parent, p.stat().st_mode & 0o777))
        return {"parity": True, "tables": []}

    cli_env.setattr(pgb, "restore", fake_restore)
    assert pgb.main(["--restore", str(enc)]) == 0
    assert seen == [(pgb.FORMAT, scratch, 0o600)]  # a private temp file, not a guessable name
    assert list(scratch.iterdir()) == []  # plaintext not left behind


def test_restore_removes_the_temp_file_when_decryption_fails(cli_env, tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    cli_env.setattr(tempfile, "tempdir", str(scratch))
    plain = tmp_path / "dump.jsonl.gz"
    pgb.write_dump(_empty_rows(), plain, NOW)
    enc = pgb.encrypt_file(plain, Fernet.generate_key().decode())
    cli_env.setenv("BACKUP_ENCRYPTION_KEY", Fernet.generate_key().decode())  # the wrong key
    cli_env.setattr(pgb, "restore", lambda scope, p: pytest.fail("must not restore"))
    assert pgb.main(["--restore", str(enc)]) == 1
    assert list(scratch.iterdir()) == []


def test_restore_of_a_fernet_file_without_the_key_fails_cleanly(cli_env, tmp_path):
    plain = tmp_path / "dump.jsonl.gz"
    pgb.write_dump(_empty_rows(), plain, NOW)
    enc = pgb.encrypt_file(plain, Fernet.generate_key().decode())
    cli_env.delenv("BACKUP_ENCRYPTION_KEY", raising=False)
    assert pgb.main(["--restore", str(enc)]) == 1


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


def test_the_pilot_declares_the_backup_crypto_dependency_directly():
    """The backup job imports Fernet. cryptography must be a direct pilot
    requirement, not a passenger of python-jose (kept only for deferred LTI),
    and pinned at the lock's version so the lock stays consistent."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    direct = (root / "requirements-pilot.txt").read_text()
    lock = (root / "requirements-pilot.lock.txt").read_text()
    pinned = re.search(r"^cryptography==(\S+)$", lock, flags=re.MULTILINE)
    assert pinned, "requirements-pilot.lock.txt does not pin cryptography"
    assert re.search(rf"^cryptography=={re.escape(pinned.group(1))}\s*$", direct, re.MULTILINE)
    entry = lock.split(f"cryptography=={pinned.group(1)}\n", 1)[1].split("\n", 3)
    assert any("-r requirements-pilot.txt" in line for line in entry[:3]), entry[:3]
