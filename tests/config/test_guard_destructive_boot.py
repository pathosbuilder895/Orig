"""T-23: ``GUARD_DESTRUCTIVE=1`` outside a real deploy refuses to boot.

docs/SECURITY_REAUDIT_2026-07-09.md follow-up #5, gap-register row T-23.
The destructive-endpoint guard is a real-deploy control. With ORIGINAL_ENV
anything other than pilot/staging/production (including unset, which means
demo), the demo surfaces stay open (anonymous sandbox access, and the demo
login that takes MAINTENANCE_TOKEN as an admin password), so a boot that
logged the destructive endpoints as GUARDED would give a false sense of
protection. The app now refuses to start instead, from the same ``lifespan``
check that refuses an unpinned SECRET_KEY on a real deploy.

Two halves, mirroring the SECRET_KEY refusal's tests:

* In-process: flip the loaded app module's globals and enter ``lifespan``
  with ``with TestClient(app)``, the technique
  ``tests/test_app_lifecycle_branches.py`` uses. Fast, and it is what the
  combined coverage run measures.
* Subprocess: a child interpreter imports ``original.api`` from a real
  environment, so ``ORIGINAL_ENV`` unset is tested as unset rather than as a
  monkeypatched ``"demo"``. The boot matrix's ``demo-guard-destructive``
  cell (``.github/workflows/boot-matrix.yml``) is the end-to-end twin that
  runs ``python run.py`` against the pilot lockset.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from original import api as api_mod

REPO_ROOT = Path(__file__).resolve().parents[2]


class _NoSqliteRepo:
    """``lifespan`` asks ``_repo().db_path()`` whether there is a SQLite file
    to back up. Raising ``NotImplementedError`` is the Postgres shape (the
    real pilot's backend), which skips the in-app backup scheduler, so these
    tests start no background task and touch no database."""

    def db_path(self):
        raise NotImplementedError("no SQLite file")


@pytest.fixture
def boot_globals(monkeypatch):
    """A pinned SECRET_KEY and no SQLite backups, so the only boot check that
    can fire is the one under test."""
    monkeypatch.setattr(api_mod, "_secret_key_pinned", True)
    monkeypatch.setattr(api_mod, "_repo", lambda: _NoSqliteRepo())
    monkeypatch.delenv("AI_LIKELIHOOD_ENABLED", raising=False)
    monkeypatch.delenv("AI_LIKELIHOOD_SHADOW", raising=False)


# ─────────────────────────────────────────────────────────────────────────────
# In-process: the lifespan check itself
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("original_env", ["demo", "prod", "dev"])
def test_guard_destructive_outside_real_deploy_refuses_boot(
    boot_globals, monkeypatch, original_env
):
    """``demo`` is the default; ``prod`` and ``dev`` are the typos and
    near-misses an operator might set, none of which ``_IS_REAL_DEPLOY``
    accepts."""
    monkeypatch.setattr(api_mod, "ORIGINAL_ENV", original_env)
    monkeypatch.setattr(api_mod, "_IS_REAL_DEPLOY", False)
    monkeypatch.setattr(api_mod, "_GUARD_DESTRUCTIVE", True)

    with pytest.raises(RuntimeError) as excinfo:
        with TestClient(api_mod.app):
            pass

    message = str(excinfo.value)
    # The boot matrix's refuse cell greps the server log for this fragment.
    assert "GUARD_DESTRUCTIVE" in message
    # Tells the operator which environment it saw.
    assert f"ORIGINAL_ENV={original_env}" in message


@pytest.mark.parametrize("original_env", ["pilot", "staging", "production"])
def test_guard_destructive_on_real_deploy_boots(boot_globals, monkeypatch, original_env):
    """The pilot runs exactly this (render.yaml: ORIGINAL_ENV=pilot,
    GUARD_DESTRUCTIVE=1); it must keep booting."""
    monkeypatch.setattr(api_mod, "ORIGINAL_ENV", original_env)
    monkeypatch.setattr(api_mod, "_IS_REAL_DEPLOY", True)
    monkeypatch.setattr(api_mod, "_GUARD_DESTRUCTIVE", True)

    with TestClient(api_mod.app) as client:
        assert client.get("/health").status_code == 200


def test_demo_without_guard_still_boots(boot_globals, monkeypatch):
    """The demo default (guard off) is untouched by the refusal."""
    monkeypatch.setattr(api_mod, "ORIGINAL_ENV", "demo")
    monkeypatch.setattr(api_mod, "_IS_REAL_DEPLOY", False)
    monkeypatch.setattr(api_mod, "_GUARD_DESTRUCTIVE", False)

    with TestClient(api_mod.app) as client:
        assert client.get("/health").status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Subprocess: from a real environment, including ORIGINAL_ENV unset
# ─────────────────────────────────────────────────────────────────────────────

# Runs the app's lifespan in a clean interpreter. A refusal prints the
# exception's own message behind a marker, so the assertion is on what the
# check raised and not on some other log line that happens to mention
# GUARD_DESTRUCTIVE (the boot log names it on every start).
_CHILD = """
import sys
from fastapi.testclient import TestClient
import original.api as api
try:
    with TestClient(api.app):
        print("BOOTED")
except RuntimeError as exc:
    print("REFUSED: " + str(exc))
    sys.exit(1)
"""

# Everything that could steer the child's boot from the parent environment.
_STRIPPED_ENV = (
    "ORIGINAL_ENV",
    "GUARD_DESTRUCTIVE",
    "SECRET_KEY",
    "ALLOWED_ORIGINS",
    "REPO_BACKEND",
    "REPO_SHADOW",
    "DATABASE_URL",
    "BACKUP_DIR",
    "AI_LIKELIHOOD_ENABLED",
    "AI_LIKELIHOOD_SHADOW",
    "SENTRY_DSN",
)


def _boot_child(env_overrides: dict[str, str], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in _STRIPPED_ENV}
    # A scratch store: a real-deploy boot starts the SQLite backup scheduler
    # next to the database, and that must not be the checkout's profiles.db.
    env["ORIGINAL_DB"] = str(tmp_path / "profiles.db")
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", _CHILD],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.boot
@pytest.mark.parametrize(
    "env_overrides",
    [
        pytest.param({"GUARD_DESTRUCTIVE": "1"}, id="original_env_unset"),
        pytest.param({"ORIGINAL_ENV": "demo", "GUARD_DESTRUCTIVE": "1"}, id="original_env_demo"),
    ],
)
def test_child_refuses_guard_destructive_outside_real_deploy(env_overrides, tmp_path):
    result = _boot_child(env_overrides, tmp_path)

    assert result.returncode == 1, (
        f"expected a refusal, got exit {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr[-2000:]}"
    )
    refused = [line for line in result.stdout.splitlines() if line.startswith("REFUSED: ")]
    assert refused, f"no refusal line in stdout:\n{result.stdout}"
    assert "GUARD_DESTRUCTIVE" in refused[0]
    # Unset ORIGINAL_ENV means demo (api.py's default), and the message says so.
    assert "ORIGINAL_ENV=demo" in refused[0]


@pytest.mark.boot
def test_child_boots_guard_destructive_on_pilot(tmp_path):
    result = _boot_child(
        {
            "ORIGINAL_ENV": "pilot",
            "GUARD_DESTRUCTIVE": "1",
            "SECRET_KEY": "test-only-secret-not-for-any-deploy",
        },
        tmp_path,
    )

    assert result.returncode == 0, (
        f"pilot with GUARD_DESTRUCTIVE=1 must boot, got exit {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr[-2000:]}"
    )
    assert "BOOTED" in result.stdout.splitlines()
