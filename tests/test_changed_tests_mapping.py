"""
tests/test_changed_tests_mapping.py — Unit tests for scripts/changed_tests.py,
the changed-file → test-file mapper behind the pre-push hook.

The mapper is a heuristic (naming convention + import scan), not a proof of
coverage — these tests pin down exactly which heuristics it promises, so the
hook's behavior stays predictable as the repo grows.

TestScratchDatabase covers `--run`'s per-run throwaway Postgres database
(parallel worktrees share one local container, and tests/test_migration.py's
drop_all used to wipe another run's tables mid-run). Its server calls are
faked, so it needs no Docker; the one real round trip is postgres-marked.
"""

from __future__ import annotations

import importlib.util
import os
import re
import signal
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "changed_tests", REPO_ROOT / "scripts" / "changed_tests.py"
)
changed_tests = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(changed_tests)


def _mk(root: Path, rel: str, content: str = "") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


class TestMapping:
    def test_changed_test_file_maps_to_itself(self, tmp_path):
        _mk(tmp_path, "tests/quantum/test_scoring.py", "def test_x(): pass\n")
        tests, _ = changed_tests.map_changed_to_tests(
            ["tests/quantum/test_scoring.py"], tmp_path
        )
        assert tests == ["tests/quantum/test_scoring.py"]

    def test_source_module_maps_via_naming_convention(self, tmp_path):
        _mk(tmp_path, "original/quantum/scoring.py", "def score(): pass\n")
        _mk(tmp_path, "tests/quantum/test_scoring.py", "def test_x(): pass\n")
        tests, _ = changed_tests.map_changed_to_tests(
            ["original/quantum/scoring.py"], tmp_path
        )
        assert "tests/quantum/test_scoring.py" in tests

    def test_source_module_maps_via_dotted_import_scan(self, tmp_path):
        _mk(tmp_path, "original/quantum/scoring.py", "def score(): pass\n")
        _mk(
            tmp_path,
            "tests/test_layer7.py",
            "from original.quantum.scoring import score\n",
        )
        tests, _ = changed_tests.map_changed_to_tests(
            ["original/quantum/scoring.py"], tmp_path
        )
        assert "tests/test_layer7.py" in tests

    def test_from_parent_import_form_detected(self, tmp_path):
        _mk(tmp_path, "original/quantum/scoring.py", "def score(): pass\n")
        _mk(
            tmp_path,
            "tests/test_indirect.py",
            "from original.quantum import state, scoring\n",
        )
        tests, _ = changed_tests.map_changed_to_tests(
            ["original/quantum/scoring.py"], tmp_path
        )
        assert "tests/test_indirect.py" in tests

    def test_monkeypatch_string_target_detected(self, tmp_path):
        _mk(tmp_path, "original/quantum/scoring.py", "def score(): pass\n")
        _mk(
            tmp_path,
            "tests/test_patcher.py",
            'def test_y(monkeypatch):\n'
            '    monkeypatch.setattr("original.quantum.scoring.score", lambda: 1)\n',
        )
        tests, _ = changed_tests.map_changed_to_tests(
            ["original/quantum/scoring.py"], tmp_path
        )
        assert "tests/test_patcher.py" in tests

    def test_prefix_module_name_does_not_false_match(self, tmp_path):
        _mk(tmp_path, "original/store.py", "def get(): pass\n")
        _mk(
            tmp_path,
            "tests/test_other.py",
            "from original.storefront import checkout\n",
        )
        tests, _ = changed_tests.map_changed_to_tests(["original/store.py"], tmp_path)
        assert tests == []

    def test_repo_root_module_needs_import_anchor(self, tmp_path):
        _mk(tmp_path, "run.py", "def main(): pass\n")
        _mk(tmp_path, "tests/test_launcher.py", "import run\n")
        _mk(tmp_path, "tests/test_unrelated.py", "def test_running_total(): pass\n")
        tests, _ = changed_tests.map_changed_to_tests(["run.py"], tmp_path)
        assert "tests/test_launcher.py" in tests
        assert "tests/test_unrelated.py" not in tests

    def test_package_init_maps_to_package_importers(self, tmp_path):
        _mk(tmp_path, "original/fusion/__init__.py", "X = 1\n")
        _mk(tmp_path, "tests/test_fused.py", "from original.fusion import X\n")
        tests, _ = changed_tests.map_changed_to_tests(
            ["original/fusion/__init__.py"], tmp_path
        )
        assert "tests/test_fused.py" in tests

    def test_conftest_change_warns_without_mapping(self, tmp_path):
        _mk(tmp_path, "tests/conftest.py", "import pytest\n")
        tests, warnings = changed_tests.map_changed_to_tests(
            ["tests/conftest.py"], tmp_path
        )
        assert tests == []
        assert any("conftest" in w for w in warnings)

    def test_deleted_changed_file_is_skipped(self, tmp_path):
        _mk(tmp_path, "tests/test_alive.py", "def test_a(): pass\n")
        tests, _ = changed_tests.map_changed_to_tests(
            ["original/gone.py", "tests/test_alive.py"], tmp_path
        )
        assert tests == ["tests/test_alive.py"]

    def test_source_with_no_mapped_tests_warns(self, tmp_path):
        _mk(tmp_path, "original/orphan.py", "def f(): pass\n")
        _mk(tmp_path, "tests/test_other.py", "import original.other\n")
        tests, warnings = changed_tests.map_changed_to_tests(
            ["original/orphan.py"], tmp_path
        )
        assert tests == []
        assert any("original/orphan.py" in w for w in warnings)

    def test_results_deduplicated_and_sorted(self, tmp_path):
        _mk(tmp_path, "original/quantum/scoring.py", "def score(): pass\n")
        _mk(
            tmp_path,
            "tests/quantum/test_scoring.py",
            "from original.quantum.scoring import score\n",
        )
        _mk(tmp_path, "tests/test_aaa.py", "import original.quantum.scoring\n")
        tests, _ = changed_tests.map_changed_to_tests(
            ["original/quantum/scoring.py", "tests/quantum/test_scoring.py"], tmp_path
        )
        assert tests == ["tests/test_aaa.py", "tests/quantum/test_scoring.py"] or tests == sorted(
            {"tests/test_aaa.py", "tests/quantum/test_scoring.py"}
        )

    def test_non_python_changes_map_to_nothing(self, tmp_path):
        _mk(tmp_path, "docs/notes.md", "# notes\n")
        _mk(tmp_path, "demo/bluebook/App.jsx", "// jsx\n")
        tests, _ = changed_tests.map_changed_to_tests(
            ["docs/notes.md", "demo/bluebook/App.jsx"], tmp_path
        )
        assert tests == []


# ── --run: per-run scratch database ──────────────────────────────────────────

# Hand-written, not read from the module: the URL the tests must see.
_SERVER = "postgresql://original:original@localhost:5432"
_SHARED_URL = f"{_SERVER}/original_test"


class _FakeRun:
    """Stands in for subprocess.run. Records the DATABASE_URL pytest would
    have been given, and which scratch databases were already dropped at that
    moment (so a drop-before-run bug cannot pass)."""

    def __init__(self, server):
        self.server = server
        self.returncode = 0
        self.during = None  # optional callable, run mid-"pytest"
        self.calls = []

    def __call__(self, cmd, cwd=None, env=None):
        self.calls.append(
            SimpleNamespace(
                cmd=cmd,
                db_url=(env or {}).get("DATABASE_URL"),
                dropped_so_far=list(self.server.dropped),
            )
        )
        if self.during:
            self.during()
        return SimpleNamespace(returncode=self.returncode)


@pytest.fixture
def hook(monkeypatch):
    """main() with one mapped test, a reachable local Postgres, no caller
    DATABASE_URL, a fake pytest subprocess and a fake database server."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(changed_tests, "changed_from_git", lambda: ["original/x.py"])
    monkeypatch.setattr(
        changed_tests, "map_changed_to_tests", lambda changed, root: (["tests/test_x.py"], [])
    )
    monkeypatch.setattr(changed_tests, "_local_postgres_reachable", lambda: True)

    server = SimpleNamespace(created=[], dropped=[], create_error=None, drop_error=None)

    def create(name):
        if server.create_error:
            raise server.create_error
        server.created.append(name)

    def drop(name):
        if server.drop_error:
            raise server.drop_error
        server.dropped.append(name)

    monkeypatch.setattr(changed_tests, "_create_scratch_db", create)
    monkeypatch.setattr(changed_tests, "_drop_scratch_db", drop)
    run = _FakeRun(server)
    monkeypatch.setattr(changed_tests, "subprocess", SimpleNamespace(run=run))
    return SimpleNamespace(server=server, run=run)


def _run_hook():
    return changed_tests.main(["--from-git", "--run"])


class TestScratchDatabase:
    def test_pytest_runs_against_its_own_database_dropped_afterwards(self, hook):
        assert _run_hook() == 0
        (name,) = hook.server.created
        (call,) = hook.run.calls
        assert call.db_url == f"{_SERVER}/{name}"
        assert call.db_url != _SHARED_URL
        assert call.dropped_so_far == []
        assert hook.server.dropped == [name]

    def test_scratch_names_are_unique_and_recognisable(self, hook):
        _run_hook()
        _run_hook()
        first, second = hook.server.created
        assert first != second
        for name in (first, second):
            # Safe unquoted identifier, under Postgres's 63-byte limit, and a
            # prefix no hand-made database (original_test_bb, ...) carries.
            assert re.fullmatch(r"original_test_tmp_\d+_[0-9a-f]{8}", name)
            assert len(name) <= 63

    def test_failing_run_still_drops_and_keeps_exit_code(self, hook):
        hook.run.returncode = 1
        assert _run_hook() == 1
        assert len(hook.server.created) == 1
        assert hook.server.dropped == hook.server.created

    def test_interrupted_run_still_drops(self, hook):
        def interrupt():
            raise KeyboardInterrupt

        hook.run.during = interrupt
        with pytest.raises(KeyboardInterrupt):
            _run_hook()
        assert len(hook.server.created) == 1
        assert hook.server.dropped == hook.server.created

    def test_sigterm_during_run_still_drops(self, hook):
        # A harmless handler stands in for the default, so a regression that
        # stops main() installing its own fails this test instead of
        # terminating the whole pytest process.
        caught = []

        def outer(signum, frame):
            caught.append(signum)

        before = signal.signal(signal.SIGTERM, outer)
        try:
            hook.run.during = lambda: os.kill(os.getpid(), signal.SIGTERM)
            with pytest.raises(SystemExit) as exc:
                _run_hook()
            assert exc.value.code == 128 + signal.SIGTERM
            assert caught == []
            assert len(hook.server.created) == 1
            assert hook.server.dropped == hook.server.created
            assert signal.getsignal(signal.SIGTERM) is outer
        finally:
            signal.signal(signal.SIGTERM, before)

    def test_caller_database_url_is_left_alone(self, hook, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://me:pw@db.example:6543/mine")
        assert _run_hook() == 0
        assert hook.run.calls[0].db_url == "postgresql://me:pw@db.example:6543/mine"
        assert hook.server.created == []
        assert hook.server.dropped == []

    def test_no_local_postgres_sets_no_database_url(self, hook, monkeypatch):
        monkeypatch.setattr(changed_tests, "_local_postgres_reachable", lambda: False)
        assert _run_hook() == 0
        assert hook.run.calls[0].db_url is None
        assert hook.server.created == []

    def test_no_mapped_tests_creates_no_database(self, hook, monkeypatch):
        monkeypatch.setattr(changed_tests, "map_changed_to_tests", lambda changed, root: ([], []))
        assert _run_hook() == 0
        assert hook.run.calls == []
        assert hook.server.created == []

    def test_create_failure_falls_back_to_shared_database_with_warning(self, hook, capsys):
        hook.server.create_error = RuntimeError("permission denied to create database")
        assert _run_hook() == 0
        assert hook.run.calls[0].db_url == _SHARED_URL
        assert hook.server.dropped == []
        err = capsys.readouterr().err
        assert "warning" in err
        assert "permission denied to create database" in err

    def test_drop_failure_warns_with_the_name_and_keeps_exit_code(self, hook, capsys):
        hook.server.drop_error = RuntimeError("database is being accessed")
        assert _run_hook() == 0
        (name,) = hook.server.created
        err = capsys.readouterr().err
        assert "warning" in err
        assert name in err


class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql):
        self.conn.executed.append((sql, self.conn.autocommit))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConnection:
    def __init__(self, dsn, kwargs):
        self.dsn = dsn
        self.kwargs = kwargs
        self.autocommit = False
        self.executed = []
        self.closed = False

    def cursor(self):
        return _FakeCursor(self)

    def close(self):
        self.closed = True


@pytest.fixture
def fake_psycopg2(monkeypatch):
    connections = []

    def connect(dsn, **kwargs):
        conn = _FakeConnection(dsn, kwargs)
        connections.append(conn)
        return conn

    monkeypatch.setitem(sys.modules, "psycopg2", SimpleNamespace(connect=connect))
    return connections


class TestScratchDatabaseSql:
    def test_create_runs_outside_a_transaction_on_the_maintenance_db(self, fake_psycopg2):
        changed_tests._create_scratch_db("original_test_tmp_42_0123abcd")
        (conn,) = fake_psycopg2
        assert conn.dsn == f"{_SERVER}/postgres"
        assert conn.kwargs.get("connect_timeout")  # never hang a push
        # CREATE DATABASE refuses to run inside a transaction block.
        assert conn.executed == [('CREATE DATABASE "original_test_tmp_42_0123abcd"', True)]
        assert conn.closed

    def test_drop_forces_out_connections_a_killed_run_left_behind(self, fake_psycopg2):
        changed_tests._drop_scratch_db("original_test_tmp_42_0123abcd")
        (conn,) = fake_psycopg2
        assert conn.dsn == f"{_SERVER}/postgres"
        assert conn.executed == [
            ('DROP DATABASE IF EXISTS "original_test_tmp_42_0123abcd" WITH (FORCE)', True)
        ]
        assert conn.closed


@pytest.mark.postgres
def test_scratch_database_round_trip_on_real_postgres(postgres_available):
    """Real CREATE/DROP against the server the hook targets (CI's service
    container, or the local one): proves WITH (FORCE) drops a database that
    still has an open connection, which a killed pytest run leaves behind."""
    url = urlparse(os.environ.get("DATABASE_URL", ""))
    if not postgres_available or (url.hostname, url.port, url.username) not in {
        ("localhost", 5432, "original"),
        ("127.0.0.1", 5432, "original"),
    }:
        pytest.skip(
            "uninformative: needs the original/original Postgres on "
            "localhost:5432 that the hook targets"
        )
    import psycopg2

    with changed_tests.scratch_database() as scratch_url:
        name = scratch_url.rsplit("/", 1)[1]
        assert name.startswith("original_test_tmp_")
        lingering = psycopg2.connect(scratch_url)
    try:
        admin = psycopg2.connect(f"{_SERVER}/postgres", connect_timeout=5)
        try:
            with admin.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
                assert cur.fetchone() is None
        finally:
            admin.close()
    finally:
        lingering.close()
