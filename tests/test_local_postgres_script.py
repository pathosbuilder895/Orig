"""
tests/test_local_postgres_script.py: `scripts/local_postgres.sh run`, the
per-run throwaway database behind `make test-postgres`.

Parallel worktrees share one local container, and tests that drop the live
schema (tests/test_migration.py's fresh_pg) wiped another run's tables when
everyone used the shared original_test database. A fake `docker` on PATH
records what the script asks of the container, so this needs no Docker.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "local_postgres.sh"
SHARED_URL = "postgresql://original:original@localhost:5432/original_test"
SCRATCH_URL = re.compile(
    r"postgresql://original:original@localhost:5432/(original_test_tmp_\d+_[0-9a-f]{8})"
)

# Logs every call; `createdb` fails when FAIL_CREATEDB is set.
FAKE_DOCKER = """#!/usr/bin/env bash
echo "docker $*" >> "$EVENT_LOG"
if [ "$1" = exec ] && [ "$3" = createdb ] && [ -n "${FAIL_CREATEDB:-}" ]; then
    echo "createdb: permission denied to create database" >&2
    exit 1
fi
exit 0
"""


@pytest.fixture
def fake_docker(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    log = tmp_path / "events.log"
    log.touch()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "EVENT_LOG": str(log),
    }
    env.pop("FAIL_CREATEDB", None)
    return env, log


def _run(env, *args):
    return subprocess.run(
        ["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=30
    )


# The command under test records the DATABASE_URL it was given in the same
# log as the docker calls, so the order create -> command -> drop is visible.
_RECORD_URL = 'echo "command $DATABASE_URL" >> "$EVENT_LOG"'


def test_run_gives_the_command_its_own_database_and_drops_it_after(fake_docker):
    env, log = fake_docker
    proc = _run(env, "run", "--", "sh", "-c", _RECORD_URL)
    assert proc.returncode == 0, proc.stderr

    events = log.read_text().splitlines()
    assert len(events) == 3, events
    create, command, drop = events
    match = SCRATCH_URL.fullmatch(command.removeprefix("command "))
    assert match, command
    name = match.group(1)
    assert create == f"docker exec original-postgres createdb -U original {name}"
    assert drop == f"docker exec original-postgres dropdb -U original --force --if-exists {name}"


def test_run_drops_the_database_and_keeps_the_exit_code_when_the_command_fails(fake_docker):
    env, log = fake_docker
    proc = _run(env, "run", "--", "sh", "-c", f"{_RECORD_URL}; exit 3")
    assert proc.returncode == 3
    events = log.read_text().splitlines()
    assert events[-1].startswith("docker exec original-postgres dropdb ")


def test_run_names_differ_between_runs(fake_docker):
    env, log = fake_docker
    _run(env, "run", "--", "sh", "-c", _RECORD_URL)
    _run(env, "run", "--", "sh", "-c", _RECORD_URL)
    urls = [e.removeprefix("command ") for e in log.read_text().splitlines() if e.startswith("command ")]
    assert len(urls) == 2
    assert urls[0] != urls[1]


def test_run_falls_back_to_the_shared_database_with_a_warning(fake_docker):
    env, log = fake_docker
    env["FAIL_CREATEDB"] = "1"
    proc = _run(env, "run", "--", "sh", "-c", _RECORD_URL)
    assert proc.returncode == 0
    events = log.read_text().splitlines()
    assert f"command {SHARED_URL}" in events
    assert not any("dropdb" in e for e in events)
    assert "warning" in proc.stderr


def test_run_without_a_command_is_a_usage_error(fake_docker):
    env, log = fake_docker
    proc = _run(env, "run")
    assert proc.returncode == 2
    assert "usage" in proc.stderr
    assert log.read_text() == ""


def test_url_still_prints_the_shared_database(fake_docker):
    # `$(local_postgres.sh url)` ends before the caller's tests start, so it
    # cannot own a throwaway database's cleanup; it stays a plain printer.
    env, log = fake_docker
    proc = _run(env, "url")
    assert proc.returncode == 0
    assert proc.stdout.strip() == SHARED_URL
    assert log.read_text() == ""
