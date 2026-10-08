"""The three CI pytest shards must partition the blocking collection exactly.

`.github/workflows/test.yml` runs `pytest-core`, `pytest-api` and
`pytest-rest` in parallel and enforces the coverage floor on the combined
result. That is only sound if every test the old single job ran is run by
exactly one shard. Two ways it could silently stop being true:

* **A test runs nowhere.** A new file added to `tests/` root that nobody
  remembers to shard would leave CI green on a test that never executes.
  `scripts/shard_paths.py` prevents this structurally (`rest` is `tests/`
  MINUS the other two shards' paths), and this test pins it.
* **A test runs twice.** Harmless for correctness, but it inflates wall time
  and makes a flake look like it failed in two shards.

Cost: four `pytest --collect-only` subprocesses (~15 s each). Collection only
— nothing here executes a test.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Same import pattern as tests/test_changed_tests_mapping.py: scripts/ is not
# a package, and loading by path avoids mutating sys.path for the whole
# session.
_spec = importlib.util.spec_from_file_location(
    "shard_paths", REPO_ROOT / "scripts" / "shard_paths.py"
)
shard_paths = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shard_paths)

# The blocking selection, verbatim from the workflow and the Makefile's
# `test` target.
BLOCKING_MARKERS = "not blocker and not certification"
FULL_SET_PATHS = ["tests/", "validation/test_tier10_optional.py"]

# `pytest --collect-only -q` prints one nodeid per line, then a blank line and
# a summary ("3273/3448 tests collected ... in 12.34s"). Nodeids always carry
# a "::" and start at column 0.
_NODEID_RE = re.compile(r"^\S.*::\S")


def _collect(args: list[str]) -> set[str]:
    """Return the set of nodeids `pytest --collect-only` yields for `args`."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("COV_CORE")}
    # Do not let an outer coverage run (the `rest` shard measures coverage)
    # steer this subprocess's data file.
    env.pop("COVERAGE_FILE", None)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            *args,
            "-m",
            BLOCKING_MARKERS,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    if proc.returncode != 0:
        pytest.fail(
            "collection failed for args "
            f"{args!r} (rc={proc.returncode})\n"
            f"--- stdout ---\n{proc.stdout[-4000:]}\n"
            f"--- stderr ---\n{proc.stderr[-4000:]}"
        )
    return {line for line in proc.stdout.splitlines() if _NODEID_RE.match(line)}


@pytest.fixture(scope="module")
def collections() -> dict[str, set[str]]:
    """Nodeid sets for the full blocking collection and each shard, computed
    once and shared across this module's tests -- collection is the ~15s/call
    cost this file exists to spend, and there's no reason to pay it twice for
    the full set + three shards in one test and the same four again in
    another.
    """
    duplicate_ignores = [f"--ignore={p}" for p in shard_paths.finder_duplicates()]
    full = _collect(FULL_SET_PATHS + duplicate_ignores)
    shards = {
        name: _collect(shard_paths.pytest_args(name)) for name in shard_paths.SHARD_NAMES
    }
    return {"full": full, **shards}


def test_shards_partition_the_blocking_collection(collections, capsys) -> None:
    full = collections["full"]
    assert full, "the full blocking collection came back empty"

    shards = {name: collections[name] for name in shard_paths.SHARD_NAMES}

    with capsys.disabled():
        print()
        for name, nodeids in shards.items():
            print(f"  shard {name:<5} {len(nodeids):>5} tests")
        print(f"  {'union':<11} {len(set().union(*shards.values())):>5} tests")
        print(f"  {'full set':<11} {len(full):>5} tests")
        duplicates = shard_paths.finder_duplicates()
        if duplicates:
            print(
                f"  ({len(duplicates)} local Finder duplicates deselected on "
                "both sides; a CI checkout has none)"
            )

    names = list(shards)
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            overlap = shards[left] & shards[right]
            assert not overlap, (
                f"shards {left!r} and {right!r} both collect "
                f"{len(overlap)} test(s), e.g. {sorted(overlap)[:5]}"
            )

    union = set().union(*shards.values())
    unsharded = full - union
    assert not unsharded, (
        f"{len(unsharded)} test(s) are collected by the full blocking set but "
        f"by NO shard — they would never run in CI, e.g. {sorted(unsharded)[:5]}"
    )
    extra = union - full
    assert not extra, (
        f"{len(extra)} test(s) are collected by a shard but not by the full "
        f"blocking set, e.g. {sorted(extra)[:5]}"
    )


def test_rest_shard_is_expressed_as_ignores_not_an_explicit_list() -> None:
    """`rest` must stay subtractive, or a new file can be silently un-run."""
    args = shard_paths.pytest_args("rest")
    selections = [a for a in args if not a.startswith("--ignore=")]
    assert selections == ["tests/"], (
        "rest must select the tests/ root and subtract the other shards with "
        f"--ignore; it selects {selections!r}"
    )
    assert any(a.startswith("--ignore=") for a in args)


def test_every_postgres_marked_file_is_in_the_api_shard(collections) -> None:
    """A `@pytest.mark.postgres` test only gets a real Postgres to run
    against in the `api` shard (the one job the workflow gives a Postgres
    service). A file landing anywhere else self-skips silently instead of
    failing loud -- this pins that every postgres-marked file's nodeids come
    back from `api`'s collection, and from no other shard's.
    """
    marked = shard_paths.postgres_marked_files()
    assert marked, "expected at least one tests/ file using @pytest.mark.postgres"

    api_nodeids = collections["api"]
    other_nodeids: set[str] = set()
    for name in shard_paths.SHARD_NAMES:
        if name != "api":
            other_nodeids |= collections[name]

    for path in marked:
        prefix = f"{path}::"
        in_api = any(nodeid.startswith(prefix) for nodeid in api_nodeids)
        stray = sorted(n for n in other_nodeids if n.startswith(prefix))
        assert in_api, f"{path} uses @pytest.mark.postgres but collects nothing in the api shard"
        assert not stray, (
            f"{path} uses @pytest.mark.postgres but also collects in a "
            f"non-api shard: {stray[:5]}"
        )


def test_run_mode_matches_print_mode_argv() -> None:
    """`--run` execs the same argv the print mode would print, for every
    shard -- so the two modes cannot silently drift apart.
    """
    extra = ["-m", "not blocker and not certification", "--durations=25"]
    for name in shard_paths.SHARD_NAMES:
        argv = shard_paths.build_argv(name, extra)
        assert argv == [
            sys.executable,
            "-m",
            "pytest",
            *shard_paths.pytest_args(name),
            *extra,
        ]
