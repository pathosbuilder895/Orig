#!/usr/bin/env python
"""
scripts/known_red.py — Policy check for @pytest.mark.blocker tests, the
backend of CI's `known-red` job (docs/testing/10-gap-register.md).

A blocker test pins a documented open product gap and is EXPECTED to fail
on this branch — excluded from the blocking `pytest` job via
`-m "not blocker"` and run here instead, blocking on a different question:
are these gaps still open? A blocker test that starts passing means its gap
may have been closed without the register or marker being updated.

Usage: .venv/bin/python scripts/known_red.py
Exit: 0 all blocker tests failed/errored, or none were collected (notice).
      1 at least one blocker test PASSED.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GAP_ID_RE = re.compile(r"T-\d+")


@dataclass(frozen=True)
class BlockerResult:
    classname: str
    name: str
    outcome: str  # "passed" | "failed" | "error" | "skipped"


def parse_junit(xml_text: str) -> list[BlockerResult]:
    """Parse a pytest --junitxml report into one result per <testcase>."""
    root = ET.fromstring(xml_text)
    results = []
    for case in root.iter("testcase"):
        if case.find("failure") is not None:
            outcome = "failed"
        elif case.find("error") is not None:
            outcome = "error"
        elif case.find("skipped") is not None:
            outcome = "skipped"
        else:
            outcome = "passed"
        results.append(
            BlockerResult(case.get("classname", ""), case.get("name", ""), outcome)
        )
    return results


def decide(results: list[BlockerResult]) -> int:
    """The known-red policy: any PASS fails the job; otherwise it succeeds
    (including the "zero collected" case — that is a notice, not a failure).
    """
    if any(r.outcome == "passed" for r in results):
        return 1
    return 0


def _resolve_source(classname: str, repo_root: Path) -> tuple[Path, list[str]] | None:
    """Map a junit `classname` (module path, + class name(s) for a method,
    e.g. "tests.test_foo.TestBar") to (source file, remaining dotted path).
    Tries the longest prefix as a file first, since a module segment can
    share a name with an enclosing directory."""
    parts = classname.split(".")
    for cut in range(len(parts), 0, -1):
        candidate = repo_root.joinpath(*parts[:cut]).with_suffix(".py")
        if candidate.is_file():
            return candidate, parts[cut:]
    return None


def _find_docstring(file_path: Path, dotted: list[str]) -> str | None:
    """Walk file_path's AST along `dotted` (class/function names) for a
    docstring, without importing the module (test modules can carry heavy
    fixtures/side effects on import)."""
    try:
        tree = ast.parse(file_path.read_text())
    except (OSError, SyntaxError):
        return None
    node: ast.AST = tree
    for part in dotted:
        found = None
        for child in ast.iter_child_nodes(node):
            if (
                isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and child.name == part
            ):
                found = child
                break
        if found is None:
            return None
        node = found
    return ast.get_docstring(node)


def gap_id_for(result: BlockerResult, repo_root: Path) -> str:
    """Best-effort gap id from the test's docstring first line; "?" if the
    source can't be resolved or carries no T-<n> docstring."""
    resolved = _resolve_source(result.classname, repo_root)
    if resolved is None:
        return "?"
    file_path, dotted_prefix = resolved
    base_name = result.name.split("[", 1)[0]  # strip parametrize id suffix
    doc = _find_docstring(file_path, [*dotted_prefix, base_name])
    if not doc:
        return "?"
    first_line = doc.strip().splitlines()[0]
    match = GAP_ID_RE.search(first_line)
    return match.group(0) if match else "?"


def run_blocker_tests(repo_root: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        junit_path = Path(tmp) / "known-red-junit.xml"
        subprocess.run(
            [
                sys.executable, "-m", "pytest", "tests/", "-m", "blocker", "-q",
                f"--junitxml={junit_path}", "-p", "no:cacheprovider",
            ],
            cwd=repo_root,
        )
        return junit_path.read_text()


def main() -> int:
    results = parse_junit(run_blocker_tests(REPO_ROOT))

    if not results:
        print("known-red: no tests carry @pytest.mark.blocker — nothing to check.")
        return 0

    print(f"{'gap-id':<10} {'test id':<70} outcome")
    for r in results:
        print(f"{gap_id_for(r, REPO_ROOT):<10} {r.classname + '::' + r.name:<70} {r.outcome}")

    code = decide(results)
    if code == 1:
        print(
            "\nknown-red: at least one @pytest.mark.blocker test PASSED — "
            "these gaps appear closed; remove @pytest.mark.blocker and move "
            "the register row to green."
        )
    return code


if __name__ == "__main__":
    sys.exit(main())
