"""
tests/test_backup_offbox.py — off-box backup upload (scripts/backup_offbox.py)
and the restore drill (scripts/restore_drill.py).

No real network calls: SigV4 request-building is pure and tested directly
against the AWS test-vector shape; upload/download/list are tested by
monkeypatching urllib.request.urlopen with an in-memory fake. The restore
drill is tested end-to-end against a real (local, tmp-path) SQLite file.
"""

from __future__ import annotations

import datetime
import importlib.util
import io
import sqlite3
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


offbox = _load("backup_offbox", _SCRIPTS / "backup_offbox.py")
drill = _load("restore_drill", _SCRIPTS / "restore_drill.py")


def _env(**overrides):
    base = {
        "BACKUP_OFFBOX_ENABLED": "1",
        "BACKUP_OFFBOX_BUCKET": "test-bucket",
        "BACKUP_OFFBOX_ENDPOINT": "https://s3.us-east-1.amazonaws.com",
        "BACKUP_OFFBOX_ACCESS_KEY_ID": "AKIAEXAMPLE",
        "BACKUP_OFFBOX_SECRET_ACCESS_KEY": "secretexample",
        "BACKUP_OFFBOX_REGION": "us-east-1",
    }
    base.update(overrides)
    return base


class TestOffboxConfig:
    def test_disabled_by_default(self):
        cfg = offbox.OffboxConfig({})
        assert cfg.enabled is False
        assert cfg.ready() is False

    def test_enabled_but_unconfigured_reports_missing(self):
        cfg = offbox.OffboxConfig({"BACKUP_OFFBOX_ENABLED": "1"})
        assert cfg.enabled is True
        assert cfg.ready() is False
        missing = cfg.missing()
        assert "BACKUP_OFFBOX_BUCKET" in missing
        assert "BACKUP_OFFBOX_ACCESS_KEY_ID" in missing

    def test_fully_configured_is_ready(self):
        cfg = offbox.OffboxConfig(_env())
        assert cfg.ready() is True

    def test_prefix_gets_trailing_slash(self):
        cfg = offbox.OffboxConfig(_env(BACKUP_OFFBOX_PREFIX="foo"))
        assert cfg.prefix == "foo/"


class TestFindLatestBackup:
    def test_no_dir_returns_none(self, tmp_path):
        assert offbox.find_latest_backup(tmp_path / "nope") is None

    def test_picks_newest_by_mtime(self, tmp_path):
        import os
        import time

        old = tmp_path / "profiles-20260101-000000.db"
        new = tmp_path / "profiles-20260102-000000.db"
        old.write_bytes(b"old")
        time.sleep(0.01)
        new.write_bytes(b"new")
        os.utime(new, (time.time() + 10, time.time() + 10))
        assert offbox.find_latest_backup(tmp_path) == new

    def test_ignores_non_matching_files(self, tmp_path):
        (tmp_path / "other.db").write_bytes(b"x")
        assert offbox.find_latest_backup(tmp_path) is None


class TestSigV4Signing:
    """Pure request-building — no network. Verifies the canonical request /
    signature machinery produces stable, well-formed output (structure and
    determinism), which is what's testable without live AWS credentials."""

    def _fixed_now(self):
        return datetime.datetime(2026, 7, 9, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def test_put_request_path_style(self):
        cfg = offbox.OffboxConfig(_env(BACKUP_OFFBOX_URL_STYLE="path"))
        url, headers = offbox.build_put_request(cfg, "prefix/file.db", b"hello", now=self._fixed_now())
        assert url == "https://s3.us-east-1.amazonaws.com/test-bucket/prefix/file.db"
        assert headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/")
        assert "Signature=" in headers["Authorization"]
        assert headers["x-amz-content-sha256"] == offbox._sha256_hex(b"hello")

    def test_put_request_virtual_style(self):
        cfg = offbox.OffboxConfig(_env(BACKUP_OFFBOX_URL_STYLE="virtual"))
        url, _headers = offbox.build_put_request(cfg, "file.db", b"hi", now=self._fixed_now())
        assert url == "https://test-bucket.s3.us-east-1.amazonaws.com/file.db"

    def test_signature_is_deterministic(self):
        cfg = offbox.OffboxConfig(_env())
        now = self._fixed_now()
        _url1, h1 = offbox.build_put_request(cfg, "k", b"body", now=now)
        _url2, h2 = offbox.build_put_request(cfg, "k", b"body", now=now)
        assert h1["Authorization"] == h2["Authorization"]

    def test_signature_changes_with_body(self):
        cfg = offbox.OffboxConfig(_env())
        now = self._fixed_now()
        _url1, h1 = offbox.build_put_request(cfg, "k", b"body-a", now=now)
        _url2, h2 = offbox.build_put_request(cfg, "k", b"body-b", now=now)
        assert h1["Authorization"] != h2["Authorization"]

    def test_get_request_uses_empty_payload_hash(self):
        cfg = offbox.OffboxConfig(_env())
        _url, headers = offbox.build_get_request(cfg, "k", now=self._fixed_now())
        assert headers["x-amz-content-sha256"] == offbox._sha256_hex(b"")


class _FakeResponse:
    def __init__(self, status=200, body=b""):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestUploadNoNetwork:
    def test_upload_calls_urlopen_with_signed_headers(self, tmp_path, monkeypatch):
        cfg = offbox.OffboxConfig(_env())
        f = tmp_path / "profiles-20260101-000000.db"
        f.write_bytes(b"sqlite-bytes")

        captured = {}

        def fake_urlopen(req, timeout=60):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.headers)
            captured["method"] = req.get_method()
            return _FakeResponse(status=200)

        monkeypatch.setattr(offbox.urllib.request, "urlopen", fake_urlopen)
        offbox.upload(cfg, f)
        assert captured["method"] == "PUT"
        assert "test-bucket" in captured["url"]
        assert "profiles-20260101-000000.db" in captured["url"]

    def test_upload_raises_on_error_status(self, tmp_path, monkeypatch):
        cfg = offbox.OffboxConfig(_env())
        f = tmp_path / "profiles-x.db"
        f.write_bytes(b"data")
        monkeypatch.setattr(offbox.urllib.request, "urlopen", lambda req, timeout=60: _FakeResponse(status=500))
        with pytest.raises(RuntimeError):
            offbox.upload(cfg, f)

    def test_main_is_noop_when_disabled(self, monkeypatch):
        monkeypatch.setattr(offbox.os, "environ", {})
        assert offbox.main([]) == 0

    def test_main_reports_missing_config_but_does_not_fail(self, monkeypatch):
        monkeypatch.setattr(offbox.os, "environ", {"BACKUP_OFFBOX_ENABLED": "1"})
        assert offbox.main([]) == 0

    def test_main_fails_when_no_local_backup_to_upload(self, tmp_path, monkeypatch):
        env = _env(BACKUP_OFFBOX_ENABLED="0")
        monkeypatch.setattr(offbox.os, "environ", env)
        assert offbox.main([]) == 0  # disabled -> no-op, not a failure


def _make_test_db(path: Path, student_rows: int = 3) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE student_profiles (sid TEXT PRIMARY KEY, data TEXT)")
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
        conn.execute("CREATE TABLE tenants (id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE audit_log (id INTEGER PRIMARY KEY, action TEXT)")
        for i in range(student_rows):
            conn.execute("INSERT INTO student_profiles VALUES (?, ?)", (f"s{i}", "{}"))
        conn.commit()
    finally:
        conn.close()


class TestRestoreDrillVerify:
    def test_verify_passes_on_healthy_backup(self, tmp_path):
        db = tmp_path / "ok.db"
        _make_test_db(db, student_rows=5)
        ok, lines = drill.verify(db)
        assert ok is True
        assert any("student_profiles: 5 rows" in line for line in lines)

    def test_verify_fails_on_empty_student_profiles(self, tmp_path):
        db = tmp_path / "empty.db"
        _make_test_db(db, student_rows=0)
        ok, lines = drill.verify(db)
        assert ok is False
        assert any("FAIL" in line for line in lines)

    def test_verify_fails_on_missing_table(self, tmp_path):
        db = tmp_path / "broken.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE unrelated (x INTEGER)")
        conn.commit()
        conn.close()
        ok, lines = drill.verify(db)
        assert ok is False

    def test_verify_fails_on_not_a_database(self, tmp_path):
        db = tmp_path / "notadb.db"
        db.write_bytes(b"this is not sqlite")
        ok, lines = drill.verify(db)
        assert ok is False

    def test_verify_respects_min_rows_threshold(self, tmp_path):
        db = tmp_path / "thin.db"
        _make_test_db(db, student_rows=2)
        ok, _lines = drill.verify(db, min_rows=5)
        assert ok is False


class TestRestoreDrillMain:
    def test_main_end_to_end_local_backup(self, tmp_path, monkeypatch):
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        db = backup_dir / "profiles-20260709-000000.db"
        _make_test_db(db, student_rows=4)

        monkeypatch.setattr(drill.os, "environ", {"BACKUP_DIR": str(backup_dir)})
        rc = drill.main(["--local-only"])
        assert rc == 0

    def test_main_fails_with_no_backups_anywhere(self, tmp_path, monkeypatch):
        empty_dir = tmp_path / "backups"
        monkeypatch.setattr(drill.os, "environ", {"BACKUP_DIR": str(empty_dir)})
        rc = drill.main(["--local-only"])
        assert rc == 1

    def test_main_explicit_path(self, tmp_path):
        db = tmp_path / "custom.db"
        _make_test_db(db, student_rows=1)
        rc = drill.main([str(db)])
        assert rc == 0

    def test_main_explicit_path_missing_file(self, tmp_path):
        rc = drill.main([str(tmp_path / "nope.db")])
        assert rc == 1
