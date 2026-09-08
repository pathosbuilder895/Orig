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
      1 at least one blocker test PASSED, or was skipped without an
        "uninformative" reason.
      2 the run of the blocker suite itself broke (pytest exited something
        other than 0/1/5, or produced no readable junit results) — not a
        policy verdict either way.
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
    outcome: str  # "passed" | "failed" | "error" | "skipped" | "uninformative"


def parse_junit(xml_text: str) -> list[BlockerResult]:
    """Parse a pytest --junitxml report into one result per <testcase>.

    A <skipped> testcase is split into two distinct outcomes based on its
    skip message, not left as one bare "skipped": a certification test may
    legitimately call `pytest.skip("uninformative — <reason>")` when a
    sample-size floor isn't met (the plan's three-valued pass/fail/
    uninformative rule), and that must not be conflated with a blocker test
    someone skipped to dodge the known-red policy without saying why.
    """
    root = ET.fromstring(xml_text)
    results = []
    for case in root.iter("testcase"):
        if case.find("failure") is not None:
            outcome = "failed"
        elif case.find("error") is not None:
            outcome = "error"
        else:
            skipped = case.find("skipped")
            if skipped is None:
                outcome = "passed"
            else:
                message = skipped.get("message") or ""
                outcome = "uninformative" if "uninformative" in message.lower() else "skipped"
        results.append(
            BlockerResult(case.get("classname", ""), case.get("name", ""), outcome)
        )
    return results


def decide(results: list[BlockerResult]) -> int:
    """The known-red policy: exit 1 if any blocker test PASSED, or if any
    was skipped without an "uninformative" reason (skipping is not a way to
    make a red test green); otherwise exit 0 — including "uninformative"
    outcomes, which count like fail/error, and the "zero collected" case,
    which is a notice, not a failure.
    """
    if any(r.outcome in ("passed", "skipped") for r in results):
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


def run_blocker_tests(repo_root: Path) -> tuple[int, str | None, str]:
    """Run `pytest -m blocker`, capturing everything main() needs to tell a
    policy verdict apart from a broken run: the process's own exit code, the
    junit report text (None if the file was never written), and the
    combined stdout/stderr for the error path to show.
    """
    with tempfile.TemporaryDirectory() as tmp:
        junit_path = Path(tmp) / "known-red-junit.xml"
        proc = subprocess.run(
            [
                sys.executable, "-m", "pytest", "tests/", "-m", "blocker", "-q",
                f"--junitxml={junit_path}", "-p", "no:cacheprovider",
            ],
            cwd=repo_root, capture_output=True, text=True,
        )
        junit_text = junit_path.read_text() if junit_path.is_file() else None
        captured = proc.stdout + proc.stderr
        return proc.returncode, junit_text, captured


def report_and_decide(
    returncode: int, junit_text: str | None, captured: str, repo_root: Path
) -> int:
    """Turn a pytest run's raw outcome into the known-red exit code.

    Exit 5 ("no tests collected") is the legitimate "no blocker tests exist"
    notice. Exit 0 or 1 means tests actually ran, so their junit report is
    trusted and handed to the (pure) `decide()` policy. Anything else —
    another exit code, or no junit file at all — means the run of the
    blocker suite itself broke; that is never a policy verdict, so it is
    reported as a hard error instead of being read as "nothing to check" or
    silently folded into "all passed/failed as expected".
    """
    if returncode == 5:
        print("known-red: no tests carry @pytest.mark.blocker — nothing to check.")
        return 0

    if returncode not in (0, 1) or junit_text is None:
        print(captured)
        reason = (
            f"pytest exited {returncode}" if returncode not in (0, 1)
            else "no junit report was written"
        )
        print(
            f"\nknown-red: {reason} running the blocker suite itself — the "
            "run broke; this is not a policy verdict."
        )
        return 2

    results = parse_junit(junit_text)

    if not results:
        print(captured)
        print(
            f"\nknown-red: pytest exited {returncode} but zero <testcase> "
            "results were parsed from its junit report — the run broke; "
            "this is not a policy verdict, not 'nothing to check'."
        )
        return 2

    print(f"{'gap-id':<10} {'test id':<70} outcome")
    for r in results:
        print(f"{gap_id_for(r, repo_root):<10} {r.classname + '::' + r.name:<70} {r.outcome}")

    code = decide(results)
    if code == 1:
        if any(r.outcome == "passed" for r in results):
            print(
                "\nknown-red: at least one @pytest.mark.blocker test PASSED — "
                "these gaps appear closed; remove @pytest.mark.blocker and move "
                "the register row to green."
            )
        if any(r.outcome == "skipped" for r in results):
            print(
                "\nknown-red: blocker test skipped without an `uninformative` "
                "reason — skipping is not a way to make a red test green."
            )
    return code


def main() -> int:
    returncode, junit_text, captured = run_blocker_tests(REPO_ROOT)
    return report_and_decide(returncode, junit_text, captured, REPO_ROOT)


if __name__ == "__main__":
    sys.exit(main())
