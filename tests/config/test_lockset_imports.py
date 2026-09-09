"""T-07 — unit-level twin of the lockset boot matrix.

docs/testing/08-config-deploy-readiness.md §2. Every other test in this repo
runs in a dev venv that has every dependency installed; Render's pilot
service installs ``requirements-pilot.lock.txt``, which pins neither
``sqlalchemy`` nor ``psycopg2-binary`` nor ``alembic``. Setting
``REPO_BACKEND=postgres`` (or ``REPO_SHADOW=postgres``) there makes
``original.repository.get_repository()`` raise ``ImportError`` at boot —
which ``original/api.py:159`` does not handle, because it catches only
``NotImplementedError``.

The probe (``tests/config/lockset_probe.py``) runs in a subprocess with a
clean ``sys.modules`` behind a ``sys.meta_path`` finder built from the
lockset's own pins, so no venv has to be built to ask the question.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

PILOT_LOCKSET = ["requirements-pilot.lock.txt"]
# The dev environment: the dev lockset plus the runtime deps the dev venv also
# installs (the pilot lockset carries the transitive runtime pins that
# requirements.txt, a direct-dependency file, does not) plus requirements.txt,
# which is where sqlalchemy / psycopg2-binary / alembic are pinned.
DEV_LOCKSET = [
    "requirements-dev.lock.txt",
    "requirements-pilot.lock.txt",
    "requirements.txt",
]

_BLOCKED_RE = re.compile(r"^BLOCKED: (.+)$", re.MULTILINE)


def _run_probe(
    lockset: list[str], env_overrides: dict[str, str], tmp_path: Path
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("REPO_BACKEND", "REPO_SHADOW")}
    # Keep the probe off the real profiles.db; SqliteRepository opens lazily,
    # but a stray boot-time write would be a side effect of a read-only test.
    env["ORIGINAL_DB"] = str(tmp_path / "probe.db")
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "tests.config.lockset_probe", *lockset],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def _why(result: subprocess.CompletedProcess[str]) -> str:
    """The blocked module line if the finder refused an import, else the raw
    stderr — so the failure names the missing dependency, not just an exit code."""
    match = _BLOCKED_RE.search(result.stderr)
    if match:
        return f"blocked import: {match.group(1)}"
    return f"exit {result.returncode}, stderr:\n{result.stderr.strip()}"


@pytest.mark.boot
@pytest.mark.parametrize(
    ("env_overrides", "expected_backend"),
    [
        pytest.param({"REPO_BACKEND": "sqlite"}, "sqlite", id="repo_backend_sqlite"),
        pytest.param(
            {"REPO_BACKEND": "postgres"}, "postgres", id="repo_backend_postgres"
        ),
        pytest.param(
            {"REPO_SHADOW": "postgres"}, "sqlite+shadow", id="repo_shadow_postgres"
        ),
    ],
)
def test_pilot_lockset_can_import_selected_backend(
    env_overrides: dict[str, str], expected_backend: str, tmp_path: Path
) -> None:
    """T-07, FIXED: the pilot lockset could not import the Postgres backend.

    An install of ``requirements-pilot.lock.txt`` alone must be able to reach
    ``get_repository()`` for whichever backend the deploy env selects. Closed
    by adding the Postgres deps (sqlalchemy/psycopg2-binary/alembic) to
    requirements-pilot.txt/.lock.txt.
    """
    result = _run_probe(PILOT_LOCKSET, env_overrides, tmp_path)

    assert (
        result.returncode == 0
    ), f"requirements-pilot.lock.txt cannot boot with {env_overrides}: {_why(result)}"
    assert json.loads(result.stdout)["backend"] == expected_backend


@pytest.mark.boot
def test_dev_lockset_imports_postgres_backend(tmp_path: Path) -> None:
    """Control for T-07: the finder is not what blocks the Postgres import.

    Same subprocess, same ``sys.meta_path`` finder, only the allowlist
    changes — built from the dev environment's requirements, which do pin
    ``sqlalchemy`` / ``psycopg2-binary`` / ``alembic``. GREEN, so a red arm
    above is a missing pin in the pilot lockset, not a harness artefact.
    """
    result = _run_probe(DEV_LOCKSET, {"REPO_BACKEND": "postgres"}, tmp_path)

    assert result.returncode == 0, f"the finder itself blocked the import: {_why(result)}"
    assert json.loads(result.stdout)["backend"] == "postgres"
