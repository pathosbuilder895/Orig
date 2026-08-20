#!/usr/bin/env python
"""
scripts/changed_tests.py — Map changed files to their associated tests, and
optionally run them. This is the backend of the `changed-tests` pre-push hook
in .pre-commit-config.yaml.

Usage:
    git diff --name-only @{push}.. | .venv/bin/python scripts/changed_tests.py
    .venv/bin/python scripts/changed_tests.py --from-git --run

Mapping heuristics (pinned by tests/test_changed_tests_mapping.py):
  1. A changed tests/**/test_*.py selects itself.
  2. A changed Python module (under original/, scripts/, or the repo root)
     selects: tests named after it (tests/**/test_<stem>*.py), tests whose
     text contains its dotted path (imports, monkeypatch string targets),
     and tests importing it as `from <parent> import ... <stem>`.
  3. tests/**/conftest.py, pytest.ini, or requirements* changes emit a
     warning instead of a selection — that is full-suite territory, and a
     pre-push hook should not run for 12 minutes.
  4. Deleted files and non-Python files select nothing. demo/bluebook JSX
     freshness has its own hook; `make e2e` stays manual.

Known gap, by design: tests that reach a module only through fixtures or
HTTP (e.g. live_client exercising original/api.py routes) carry no textual
reference to it and are not selected. This hook is a fast pre-push net —
CI's full suite remains the real gate.

In --run mode, if DATABASE_URL is unset and a local Postgres answers on
localhost:5432 (see scripts/local_postgres.sh), it is exported automatically
so postgres-marked tests in the selection run instead of self-skipping.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_PG_URL = "postgresql://original:original@localhost:5432/original_test"

_INFRA_FILES = {"pytest.ini", "setup.cfg", "pyproject.toml"}


def _dotted_module(rel: str) -> tuple[str, str]:
    """Return (dotted_path, stem) for a repo-relative .py path.

    original/quantum/scoring.py -> ("original.quantum.scoring", "scoring")
    original/fusion/__init__.py -> ("original.fusion", "fusion")
    run.py                      -> ("run", "run")
    """
    parts = Path(rel).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts), parts[-1]


def _test_corpus(repo_root: Path) -> list[tuple[str, str]]:
    """All (relpath, text) pairs under tests/ — read once, scanned per module."""
    corpus = []
    tests_root = repo_root / "tests"
    if not tests_root.is_dir():
        return corpus
    for p in sorted(tests_root.rglob("*.py")):
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        corpus.append((p.relative_to(repo_root).as_posix(), text))
    return corpus


def _is_test_file(rel: str) -> bool:
    return rel.startswith("tests/") and Path(rel).name.startswith("test_") and rel.endswith(".py")


def _matchers_for(dotted: str, stem: str) -> list[re.Pattern]:
    """Regexes that mean 'this test file touches module <dotted>'."""
    if "." in dotted:
        parent = dotted.rsplit(".", 1)[0]
        return [
            # import original.quantum.scoring / from original.quantum.scoring
            # import / monkeypatch.setattr("original.quantum.scoring.score", …)
            re.compile(rf"\b{re.escape(dotted)}\b"),
            # from original.quantum import state, scoring
            re.compile(rf"from\s+{re.escape(parent)}\s+import\s[^\n]*\b{re.escape(stem)}\b"),
        ]
    # Repo-root single-segment module (run.py): a bare-word match would hit
    # ordinary prose ("running"), so anchor on actual import statements.
    return [
        re.compile(rf"(?m)^\s*import\s+{re.escape(dotted)}\b"),
        re.compile(rf"(?m)^\s*from\s+{re.escape(dotted)}\s+import\b"),
    ]


def map_changed_to_tests(changed: list[str], repo_root: Path) -> tuple[list[str], list[str]]:
    """Map changed repo-relative paths to test files. Returns (tests, warnings)."""
    selected: set[str] = set()
    warnings: list[str] = []
    corpus: list[tuple[str, str]] | None = None  # lazy — only built if needed

    for raw in changed:
        rel = Path(raw.strip()).as_posix()
        if not rel:
            continue

        name = Path(rel).name
        if name == "conftest.py" and (rel.startswith("tests/") or rel == "conftest.py"):
            warnings.append(
                f"{rel}: test-infrastructure (conftest) changed — the hook cannot "
                "scope this; consider a full `make test` before merging"
            )
            continue
        if name in _INFRA_FILES or name.startswith("requirements"):
            warnings.append(
                f"{rel}: test/build infrastructure changed — consider a full `make test`"
            )
            continue

        if not (repo_root / rel).is_file():
            continue  # deleted or renamed away — nothing to run for it

        if _is_test_file(rel):
            selected.add(rel)
            continue

        if not rel.endswith(".py") or rel.startswith("tests/"):
            continue  # non-Python, or test helpers that aren't test_*.py

        dotted, stem = _dotted_module(rel)
        found_for_module: set[str] = set()

        for cand in (repo_root / "tests").rglob(f"test_{stem}*.py"):
            found_for_module.add(cand.relative_to(repo_root).as_posix())

        if corpus is None:
            corpus = _test_corpus(repo_root)
        matchers = _matchers_for(dotted, stem)
        for test_rel, text in corpus:
            if not _is_test_file(test_rel):
                continue
            if any(m.search(text) for m in matchers):
                found_for_module.add(test_rel)

        if found_for_module:
            selected.update(found_for_module)
        else:
            warnings.append(
                f"no tests mapped for {rel} — if it has tests, name them "
                f"tests/**/test_{stem}*.py or import the module directly"
            )

    return sorted(selected), warnings


def changed_from_git() -> list[str]:
    """Files changed in the commits being pushed.

    Prefers pre-commit's PRE_COMMIT_FROM_REF/TO_REF (exactly the pushed
    range), then @{push}.., then origin/main...HEAD for brand-new branches.
    """
    from_ref = os.environ.get("PRE_COMMIT_FROM_REF")
    to_ref = os.environ.get("PRE_COMMIT_TO_REF")
    ranges = []
    if from_ref and to_ref:
        ranges.append(f"{from_ref}..{to_ref}")
    ranges += ["@{push}..", "origin/main...HEAD"]
    for rng in ranges:
        proc = subprocess.run(
            ["git", "diff", "--name-only", rng],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        if proc.returncode == 0:
            return [line for line in proc.stdout.splitlines() if line.strip()]
    return []


def _local_postgres_reachable() -> bool:
    try:
        with socket.create_connection(("localhost", 5432), timeout=1):
            return True
    except OSError:
        return False


def main(argv: list[str]) -> int:
    run = "--run" in argv
    from_git = "--from-git" in argv

    changed = changed_from_git() if from_git else [line for line in sys.stdin.read().splitlines() if line.strip()]
    tests, warnings = map_changed_to_tests(changed, REPO_ROOT)

    for w in warnings:
        print(f"changed-tests: warning: {w}", file=sys.stderr)

    if not run:
        for t in tests:
            print(t)
        return 0

    codes = []
    if tests:
        env = os.environ.copy()
        if not env.get("DATABASE_URL") and _local_postgres_reachable():
            env["DATABASE_URL"] = LOCAL_PG_URL
            print("changed-tests: local Postgres detected — postgres-marked tests will run")
        print(f"changed-tests: running {len(tests)} mapped test file(s)")
        codes.append(
            subprocess.run(
                [sys.executable, "-m", "pytest", "-q", *tests],
                cwd=REPO_ROOT, env=env,
            ).returncode
        )
    else:
        print("changed-tests: no Python tests mapped to the pushed changes")

    app_changed = any(Path(c).as_posix().startswith("app/") for c in changed)
    if app_changed:
        if (REPO_ROOT / "app" / "node_modules").is_dir():
            print("changed-tests: app/ changed — running its vitest suite")
            codes.append(
                subprocess.run(["npm", "--prefix", "app", "test"], cwd=REPO_ROOT).returncode
            )
        else:
            print(
                "changed-tests: warning: app/ changed but app/node_modules is "
                "missing — run `cd app && npm ci && npm test`",
                file=sys.stderr,
            )

    return max(codes, default=0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
