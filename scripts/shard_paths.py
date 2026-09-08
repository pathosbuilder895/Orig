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

Output is shell-quoted (`shlex.quote`), so callers must `eval` it. That
matters only in a local worktree: the macOS Finder duplicates below are the
one source of paths containing spaces, and they are gitignored, so on a CI
checkout the output never needs quoting at all.
"""

from __future__ import annotations

import glob
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


def pytest_args(shard: str) -> list[str]:
    """The pytest argument list for `shard` (selection + --ignore entries)."""
    duplicate_ignores = [f"--ignore={p}" for p in finder_duplicates()]

    if shard != "rest":
        return expand(shard) + duplicate_ignores

    owned: set[str] = set()
    for other in SHARD_NAMES:
        if other == "rest":
            continue
        # Only paths under tests/ can be reached by `rest`'s `tests/` root;
        # ignoring anything else would be noise.
        owned.update(p for p in expand(other) if p.startswith("tests/"))
    return ["tests/"] + [f"--ignore={p}" for p in sorted(owned)] + duplicate_ignores


def main(argv: list[str]) -> int:
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
