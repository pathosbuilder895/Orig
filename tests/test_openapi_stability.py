"""The generated OpenAPI schema must be byte-identical across processes.

Why a subprocess test: FastAPI derives an implicit ``operationId`` from
``list(route.methods)[0]`` — the iteration order of a **set**. Python randomises
string hashing per interpreter, so that order is fixed for the life of one
process but varies between processes. A same-process "call ``app.openapi()``
twice" assertion would therefore always pass and catch nothing; only separate
interpreters expose the churn.

We drive ``PYTHONHASHSEED`` explicitly rather than relying on chance. Against the
pre-fix code the two-verb ``/lti/login`` route flipped between
``lti_login_lti_login_get`` (seeds 0, 1) and ``lti_login_lti_login_post``
(seeds 2-5), so this sweep fails deterministically without the explicit
``operation_id="lti_login"`` on that route.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Hash seeds that provably straddle both set-iteration orders of {"GET", "POST"}.
HASH_SEEDS = ["0", "1", "2", "3", "4", "5"]

# Child program: import the live app, serialise its schema deterministically,
# and write it to the path given as argv[1]. Writing to a file (not stdout)
# keeps app logging and warnings from corrupting the payload.
_CHILD = """
import json, sys
from original.api import app
schema = app.openapi()
with open(sys.argv[1], "w") as fh:
    json.dump(schema, fh, sort_keys=True)
"""


def _openapi_in_subprocess(hash_seed: str, out_path: Path, env_extra: dict) -> str:
    """Generate the OpenAPI schema in a fresh interpreter; return the JSON text."""
    env = dict(env_extra)
    env["PYTHONHASHSEED"] = hash_seed
    env["PYTHONPATH"] = str(REPO_ROOT)
    # Keep each child's SQLite side effects inside tmp_path, never the repo.
    env["ORIGINAL_DB"] = str(out_path.parent / f"schema-{hash_seed}.db")

    result = subprocess.run(
        [sys.executable, "-c", _CHILD, str(out_path)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert (
        result.returncode == 0
    ), f"schema generation failed (PYTHONHASHSEED={hash_seed}):\n{result.stderr}"
    return out_path.read_text()


@pytest.fixture(scope="module")
def _base_env() -> dict:
    """A minimal, inherited-PATH environment for the child interpreters."""
    import os

    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")
    return {k: v for k, v in os.environ.items() if k in keep}


def test_openapi_schema_is_identical_across_processes(tmp_path, _base_env):
    """Two separate interpreters must serialise byte-identical schemas."""
    first = _openapi_in_subprocess(HASH_SEEDS[0], tmp_path / "first.json", _base_env)
    second = _openapi_in_subprocess(HASH_SEEDS[-1], tmp_path / "second.json", _base_env)

    assert first == second, (
        "OpenAPI schema differs between processes — some operationId or ordering "
        "is derived from per-process set/dict iteration order."
    )


def test_openapi_schema_is_stable_across_hash_seeds(tmp_path, _base_env):
    """Sweep the seeds that straddle both {'GET','POST'} iteration orders."""
    schemas = {
        seed: _openapi_in_subprocess(seed, tmp_path / f"schema-{seed}.json", _base_env)
        for seed in HASH_SEEDS
    }

    distinct = set(schemas.values())
    if len(distinct) > 1:
        # Name the offending operationIds so the failure is actionable.
        by_seed = {
            seed: {
                f"{method.upper()} {path}": op.get("operationId")
                for path, ops in json.loads(text)["paths"].items()
                for method, op in ops.items()
            }
            for seed, text in schemas.items()
        }
        reference = by_seed[HASH_SEEDS[0]]
        churn = {
            key
            for seed_map in by_seed.values()
            for key, value in seed_map.items()
            if reference.get(key) != value
        }
        pytest.fail(f"OpenAPI schema is not reproducible; unstable operations: {sorted(churn)}")


def test_lti_login_operation_id_is_pinned(tmp_path, _base_env):
    """The two-verb /lti/login route carries its explicit, stable operationId."""
    text = _openapi_in_subprocess(HASH_SEEDS[0], tmp_path / "pinned.json", _base_env)
    paths = json.loads(text)["paths"]

    login = paths["/lti/login"]
    assert set(login) == {"get", "post"}, "LTI requires both verbs on /lti/login"
    for method, operation in login.items():
        assert (
            operation["operationId"] == "lti_login"
        ), f"/lti/login {method.upper()} lost its pinned operation_id"
