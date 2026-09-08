#!/usr/bin/env python3
"""Single source of truth for the CI pytest shard membership (T-46).

`.github/workflows/test.yml` splits the old single serial `pytest` job into
three path-based shards — `core`, `api`, `rest` — plus a `coverage-combine`
job that enforces the ≥98 floor on the *combined* number. Shard membership is
defined ONCE, here, in `SHARDS`; the workflow and the Makefile both ask this
script for a shard's pytest arguments rather than repeating path lists.

    $ python scripts/shard_paths.py core
    tests/context tests/fusion tests/quantum tests/validation validation/test_tier10_optional.py

Why paths and not `pytest-xdist` hashing: a directory/file shard is
reproducible. When `pytest-api` goes red you re-run exactly
`python -m pytest $(python scripts/shard_paths.py api)` locally and get the
same selection. A hash shard depends on worker count and collection order.

Why `rest` is expressed as `tests/` MINUS the other two shards' paths (rather
than an explicit list of what is left): a new file added to `tests/` root can
then never be silently un-run. Under an explicit-list `rest`, forgetting to
add the file means no shard collects it and CI stays green on a test nobody
runs. `tests/test_shard_partition.py` pins that property — the three shard
selections must partition the full blocking collection exactly.

Any `tests/` file containing `@pytest.mark.postgres` is routed into `api` —
the only shard with a Postgres service — even if its directory/glob entry
would otherwise place it in `core` or `rest` (see `postgres_marked_files()`).
`core`/`rest` get an `--ignore` for each such file so it still runs exactly
once; `tests/test_shard_partition.py::test_every_postgres_marked_file_is_in_the_api_shard`
pins this by collection, not by reading the grep.

Two ways to run a shard:

    $ python scripts/shard_paths.py --run core -m "not blocker" -q
        execs `python -m pytest <core's args> -m "not blocker" -q` via
        `os.execv` — no shell, no quoting round-trip. This is what CI and the
        Makefile use.

    $ python scripts/shard_paths.py core
        prints the shell-quoted (`shlex.quote`) argument list for a human to
        paste into their own command. Quoting matters only in a local
        worktree: the macOS Finder duplicates below are the one source of
        paths containing spaces, and they are gitignored, so a CI checkout
        never needs it.
"""

from __future__ import annotations

import glob
import os
import re
import shlex
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------
# THE source of truth. Entries may be directories, files, or globs; globs are
# expanded at run time so that a newly added `tests/test_bluebook_x.py` lands
# in the `api` shard automatically instead of falling through to `rest`.
# --------------------------------------------------------------------------
SHARDS: dict[str, list[str] | str] = {
    # Heavy numeric/pipeline packages. `tests/fusion/test_wiring.py` (six
    # cases at 72-82s each) dominates this shard — see
    # docs/testing/09-test-infrastructure-ci.md §1.2.
    "core": [
        "tests/quantum",
        "tests/context",
        "tests/fusion",
        "tests/validation",
        "validation/test_tier10_optional.py",
    ],
    # HTTP surface, persistence, and the suites that need a real Postgres
    # (tests/test_repository_contract.py parametrizes over a "postgres"
    # backend). This is the ONLY shard the workflow gives a Postgres service.
    "api": [
        "tests/test_*api*.py",
        "tests/test_*router*.py",
        "tests/test_bluebook*.py",
        "tests/test_pilot*.py",
        "tests/test_cutover*.py",
        "tests/test_repository_contract*.py",
        "tests/test_shadow*.py",
        "tests/test_migration*.py",
        "tests/test_persistence*.py",
        # No matches today; the alembic suite is expected here when it lands.
        "tests/test_alembic*.py",
        "tests/security",
        "tests/config",
        "tests/perf",
    ],
    # Everything else under tests/. Expressed as the root with --ignore for
    # every path the other two shards own (see module docstring).
    "rest": "tests/",
}

SHARD_NAMES = tuple(SHARDS)

# macOS Finder duplicates ("test_tier1 2.py"). They are gitignored (`* 2.*` in
# .gitignore), so a CI checkout has none and `finder_duplicates()` returns []
# there — but pytest happily collects them in a local worktree, which would
# both double the local work and desynchronise the shard partition. Deleting
# them needs the owner's permission, so they are deselected instead.
_FINDER_DUPLICATE_RE = re.compile(r".* \d+\.py$")

# Matches the decorator whether it's bare (`@pytest.mark.postgres`) or
# parametrized-looking (it never takes args today, but don't require that).
# Match only real marker USAGE -- a decorator line, a module-level
# ``pytestmark`` assignment, or ``marks=pytest.mark.postgres`` inside a
# ``pytest.param`` -- never a mention in a docstring or assertion message
# (tests/test_shard_partition.py talks about the marker without using it).
_POSTGRES_MARKER_RE = re.compile(
    r"^\s*@pytest\.mark\.postgres\b"
    r"|^\s*pytestmark\s*=.*pytest\.mark\.postgres\b"
    r"|marks\s*=\s*\[?\s*pytest\.mark\.postgres\b",
    re.MULTILINE,
)


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def finder_duplicates() -> list[str]:
    """Repo-relative paths of Finder-duplicate test files under tests/.

    Empty on CI. Every shard ignores the whole set (an ignore for a path
    outside the shard's own tree is a harmless no-op) so that all four
    selections — the three shards and the full blocking set — are filtered
    identically.
    """
    tests_dir = REPO_ROOT / "tests"
    if not tests_dir.is_dir():
        return []
    return sorted(
        _rel(p) for p in tests_dir.rglob("*.py") if _FINDER_DUPLICATE_RE.match(p.name)
    )


def postgres_marked_files() -> list[str]:
    """Repo-relative paths of every `tests/` file that references
    `pytest.mark.postgres` in its source, grepped at run time.

    A maintained list would silently go stale the next time someone adds a
    postgres-marked test; grepping means a new one is routed to `api` (the
    only shard with a Postgres service) with no edit to this file. Finder
    duplicates are excluded — they're gitignored copies of files already
    counted under their real name.
    """
    tests_dir = REPO_ROOT / "tests"
    if not tests_dir.is_dir():
        return []
    duplicates = set(finder_duplicates())
    found: list[str] = []
    for path in tests_dir.rglob("*.py"):
        rel = _rel(path)
        if rel in duplicates:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _POSTGRES_MARKER_RE.search(text):
            found.append(rel)
    return sorted(found)


def expand(shard: str) -> list[str]:
    """Concrete, repo-relative paths this shard selects.

    Globs are expanded against the working tree; Finder duplicates and
    non-existent literal entries are dropped. `rest` is definitionally
    "tests/ minus the others" and expands to just `tests/`.
    """
    spec = SHARDS[shard]
    if isinstance(spec, str):
        return [spec]

    duplicates = set(finder_duplicates())
    paths: list[str] = []
    for entry in spec:
        if any(ch in entry for ch in "*?["):
            paths.extend(
                sorted(
                    _rel(Path(match))
                    for match in glob.glob(str(REPO_ROOT / entry))
                    if _rel(Path(match)) not in duplicates
                )
            )
        elif (REPO_ROOT / entry).exists():
            paths.append(entry)
    return sorted(dict.fromkeys(paths))


def api_selections() -> list[str]:
    """Concrete paths the `api` shard selects.

    `api`'s own glob/literal entries, plus every postgres-marked test file
    anywhere under `tests/` — even one that a directory entry elsewhere
    (e.g. `core`'s `tests/validation`) would otherwise own. `api` is the only
    shard the workflow gives a Postgres service, so this is what makes a
    `@pytest.mark.postgres` test actually run against one in CI instead of
    self-skipping silently in `core` or `rest`.
    """
    selections = set(expand("api"))
    selections.update(postgres_marked_files())
    return sorted(selections)


def pytest_args(shard: str) -> list[str]:
    """The pytest argument list for `shard` (selection + --ignore entries)."""
    duplicate_ignores = [f"--ignore={p}" for p in finder_duplicates()]
    # Harmless no-op for a shard that never selected the file in the first
    # place — same convention as duplicate_ignores above.
    postgres_ignores = [f"--ignore={p}" for p in postgres_marked_files()]

    if shard == "api":
        return api_selections() + duplicate_ignores

    if shard == "core":
        return expand(shard) + postgres_ignores + duplicate_ignores

    # rest
    owned: set[str] = set()
    for other in SHARD_NAMES:
        if other == "rest":
            continue
        # `api`'s postgres-routed files count as owned too, or `rest` would
        # collect them a second time from its subtractive `tests/` root.
        other_paths = api_selections() if other == "api" else expand(other)
        # Only paths under tests/ can be reached by `rest`'s `tests/` root;
        # ignoring anything else would be noise.
        owned.update(p for p in other_paths if p.startswith("tests/"))
    return ["tests/"] + [f"--ignore={p}" for p in sorted(owned)] + duplicate_ignores


def build_argv(shard: str, extra: list[str]) -> list[str]:
    """The argv `--run` execs for `shard`, plus any caller-supplied `extra`
    pytest arguments. Shared with the print-mode path (`pytest_args`) so the
    two modes cannot drift apart — see
    `tests/test_shard_partition.py::test_run_mode_matches_print_mode_argv`.
    """
    return [sys.executable, "-m", "pytest", *pytest_args(shard), *extra]


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "--run":
        if len(argv) < 3 or argv[2] not in SHARDS:
            print(
                f"usage: {Path(argv[0]).name} --run {{{'|'.join(SHARD_NAMES)}}} "
                "[pytest args...]",
                file=sys.stderr,
            )
            return 2
        shard, extra = argv[2], argv[3:]
        os.execv(sys.executable, build_argv(shard, extra))
        return 1  # unreachable on success: execv replaces this process

    if len(argv) != 2 or argv[1] not in SHARDS:
        print(
            f"usage: {Path(argv[0]).name} {{{'|'.join(SHARD_NAMES)}}}",
            file=sys.stderr,
        )
        return 2
    print(" ".join(shlex.quote(arg) for arg in pytest_args(argv[1])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
