"""
tests/test_no_xfail.py, the suite carries no ``xfail`` (T-54).

docs/testing/09 §4: a known-red test is *red*, marked ``blocker`` and run by
the ``known-red`` job (``scripts/known_red.py``), which fails the day it
unexpectedly passes. ``xfail`` would hide the same test in the blocking run
and keep CI green whether or not the gap is ever fixed, so it is banned here
rather than by convention.

AST-based, like ``tests/test_known_red_policy.py``: the word appearing in a
string or a comment (this module's own fixtures, the flake-policy prose)
does not count. Only an applied ``pytest.mark.xfail`` (decorator,
``marks=``, ``pytestmark``) or a ``pytest.xfail(...)`` call does.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNED = ("tests", "validation")


def _xfail_uses(source: str) -> list[int]:
    """Line numbers where ``source`` applies ``xfail``."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        # pytest.mark.xfail, with or without a call
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "xfail"
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "mark"
        ):
            lines.append(node.lineno)
        # pytest.xfail("reason") inside a test body
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "xfail"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "pytest"
        ):
            lines.append(node.lineno)
    return sorted(lines)


def test_detector_catches_every_form():
    source = (
        "import pytest\n"
        "@pytest.mark.xfail(reason='x')\n"
        "def test_a(): pass\n"
        "@pytest.mark.xfail\n"
        "def test_b(): pass\n"
        "pytestmark = pytest.mark.xfail\n"
        "def test_c():\n"
        "    pytest.xfail('later')\n"
        "@pytest.mark.parametrize('v', [pytest.param(1, marks=pytest.mark.xfail)])\n"
        "def test_d(v): pass\n"
    )
    assert _xfail_uses(source) == [2, 4, 6, 8, 9]


def test_detector_ignores_strings_and_comments():
    source = (
        "# never use xfail here\n"
        "DOC = 'pytest.mark.xfail is banned'\n"
        "def test_a():\n"
        "    assert 'xfail' in DOC\n"
    )
    assert _xfail_uses(source) == []


def test_no_xfail_in_the_suite():
    offenders = []
    for top in SCANNED:
        for path in sorted((REPO_ROOT / top).rglob("*.py")):
            try:
                source = path.read_text()
            except OSError:
                continue
            try:
                lines = _xfail_uses(source)
            except SyntaxError:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            offenders += [f"{rel}:{line}" for line in lines]
    assert offenders == [], (
        "xfail is banned (docs/testing/09 §4); mark a known-red test "
        "`blocker` with its gap id instead: " + ", ".join(offenders)
    )
