"""
tests/test_env_example.py: ``.env.example`` matches the flags (T-56).

docs/testing/08 §3: ``.env.example`` names every flag in CLAUDE.md's
"Environment Flags" table, and no variable the code never reads. An
operator copies this file to configure a deploy, so a missing row is a
setting they cannot find and a stale row is a setting that silently does
nothing. (The termsim rewrite once dropped the four ``DB_POOL_*`` rows; the
file later lacked the ten rows added for signup, mail, evidence and
backups.)

"The code reads it" is checked as: the name appears as a string literal in
a ``.py`` file under ``original/``, ``scripts/`` or ``run.py``. That covers
``os.environ.get("X")`` and every helper that takes the name as an
argument, without a list of accessor spellings to keep current.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_NAME = re.compile(r"^([A-Z][A-Z0-9_]+)=", re.MULTILINE)
_FLAG_ROW = re.compile(r"^\| `([A-Z][A-Z0-9_]+)` \|", re.MULTILINE)

# CLAUDE.md rows that are deliberately not environment variables. Each must
# stay unread by the code (pinned below), so an entry here cannot hide a
# real setting that went missing from .env.example.
NOT_ENV_VARS = {
    "TOPIC_INFLATE_GAIN": "a constant in original/constants.py",
    "SENTRY_TRACES_SAMPLE_RATE": "ignored on purpose: tracing is always off",
}


def _env_example_names() -> set[str]:
    return set(_NAME.findall((REPO_ROOT / ".env.example").read_text()))


def _claude_md_flag_names() -> set[str]:
    text = (REPO_ROOT / "CLAUDE.md").read_text()
    start = text.index("## Environment Flags")
    end = text.index("\n## ", start + 1)
    return set(_FLAG_ROW.findall(text[start:end]))


def _code_string_literals() -> set[str]:
    files = [REPO_ROOT / "run.py"]
    for top in ("original", "scripts"):
        files += sorted((REPO_ROOT / top).rglob("*.py"))
    found: set[str] = set()
    for path in files:
        try:
            tree = ast.parse(path.read_text())
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.add(node.value)
    return found


def test_the_sources_parse():
    # Guards the two parsers below against silently matching nothing.
    assert "ORIGINAL_ENV" in _env_example_names()
    assert {"ORIGINAL_ENV", "SECRET_KEY", "NULL_MODEL"} <= _claude_md_flag_names()


def test_every_documented_flag_is_in_env_example():
    missing = sorted(_claude_md_flag_names() - _env_example_names() - set(NOT_ENV_VARS))
    assert missing == [], f"CLAUDE.md documents these but .env.example lacks them: {missing}"


def test_env_example_names_only_variables_the_code_reads():
    literals = _code_string_literals()
    unread = sorted(n for n in _env_example_names() if n not in literals)
    assert unread == [], f".env.example names variables no code reads: {unread}"


def test_the_exempt_rows_really_are_not_read_from_the_environment():
    for name in NOT_ENV_VARS:
        assert name in _claude_md_flag_names(), f"{name}: no CLAUDE.md row left to exempt"
        assert name not in _env_example_names(), f"{name} is exempt but listed in .env.example"
    # TOPIC_INFLATE_GAIN appears as an identifier, never as a string literal;
    # if code ever reads it from the environment, the literal shows up here.
    assert not set(NOT_ENV_VARS) & _code_string_literals()
