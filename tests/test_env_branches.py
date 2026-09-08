"""
tests/test_env_branches.py — original/_env.py, the dependency-free .env loader.

The legacy demo app has no python-dotenv dependency (requirements-demo.txt
intentionally omits it — ADR-003), so `_env.load_env_file` is the only thing
standing between a pilot operator dropping a `.env` file and SECRET_KEY /
ALLOWED_ORIGINS / ORIGINAL_ENV / LTI_* actually getting picked up. It has no
dedicated test file yet (grepped: nothing in tests/ imports it) even though
it is exercised implicitly at process startup — these are direct unit tests
against one tmp_path `.env` fixture per parsing arm.
"""

from __future__ import annotations

import os

import pytest

from original import _env


@pytest.fixture(autouse=True)
def _cleanup_envtest_keys():
    """`load_env_file` writes straight to the real `os.environ` via
    `setdefault()`, which `monkeypatch.delenv()` called *before* the write
    can't retroactively track for auto-revert. Every test in this file uses
    an `ENVTEST_`-prefixed (or `export `-prefixed) key, so sweep those on
    teardown instead of hand-rolling try/finally per test.
    """
    yield
    for key in list(os.environ):
        if key.startswith("ENVTEST_") or key.startswith("export ENVTEST_"):
            del os.environ[key]


def test_file_absent_returns_false(tmp_path):
    missing = tmp_path / "nope.env"
    assert not missing.exists()
    assert _env.load_env_file(missing) is False


def test_empty_file_returns_true_with_no_lines(tmp_path):
    envfile = tmp_path / ".env"
    envfile.write_text("")
    assert _env.load_env_file(envfile) is True


def test_blank_comment_and_equalsless_lines_are_skipped(tmp_path):
    envfile = tmp_path / ".env"
    envfile.write_text("\n" "   \n" "# a full-line comment\n" "NOT_A_KV_PAIR_NO_EQUALS\n")
    assert _env.load_env_file(envfile) is True
    # The blank/comment/no-equals lines never produced an env var.
    assert "NOT_A_KV_PAIR_NO_EQUALS" not in os.environ


def test_line_with_empty_key_is_not_set(tmp_path):
    """`=somevalue` parses to an empty key — `if key:` must skip it (not
    call `os.environ.setdefault("", ...)`)."""
    envfile = tmp_path / ".env"
    envfile.write_text("=orphan_value_with_no_key\n")
    assert _env.load_env_file(envfile) is True
    assert "" not in os.environ


def test_export_prefixed_and_plain_kv_lines_parse(tmp_path):
    envfile = tmp_path / ".env"
    envfile.write_text("export ENVTEST_EXPORTED=exported_value\nENVTEST_PLAIN=plain_value\n")
    assert _env.load_env_file(envfile) is True
    # The loader has no special-cased `export` handling — the whole left-hand
    # side (including the literal word "export") becomes the key. Documented
    # here so a future reader isn't surprised by it.
    assert os.environ["export ENVTEST_EXPORTED"] == "exported_value"
    assert os.environ["ENVTEST_PLAIN"] == "plain_value"


def test_quoted_values_keep_hash_and_strip_quotes(tmp_path, monkeypatch):
    envfile = tmp_path / ".env"
    envfile.write_text(
        'ENVTEST_DQUOTE="value with a # hash inside"\n' "ENVTEST_SQUOTE='single quoted'\n"
    )
    monkeypatch.delenv("ENVTEST_DQUOTE", raising=False)
    monkeypatch.delenv("ENVTEST_SQUOTE", raising=False)
    assert _env.load_env_file(envfile) is True
    assert os.environ["ENVTEST_DQUOTE"] == "value with a # hash inside"
    assert os.environ["ENVTEST_SQUOTE"] == "single quoted"


def test_unquoted_value_with_inline_comment_is_stripped(tmp_path, monkeypatch):
    envfile = tmp_path / ".env"
    envfile.write_text("ENVTEST_INLINE=bar # trailing comment\n")
    monkeypatch.delenv("ENVTEST_INLINE", raising=False)
    assert _env.load_env_file(envfile) is True
    assert os.environ["ENVTEST_INLINE"] == "bar"


def test_unquoted_value_without_hash_has_no_special_stripping(tmp_path, monkeypatch):
    envfile = tmp_path / ".env"
    envfile.write_text("ENVTEST_NOHASH=justavalue\n")
    monkeypatch.delenv("ENVTEST_NOHASH", raising=False)
    assert _env.load_env_file(envfile) is True
    assert os.environ["ENVTEST_NOHASH"] == "justavalue"


def test_existing_environment_variable_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVTEST_PREEXISTING", "original_value")
    envfile = tmp_path / ".env"
    envfile.write_text("ENVTEST_PREEXISTING=from_dotenv_should_be_ignored\n")
    assert _env.load_env_file(envfile) is True
    assert os.environ["ENVTEST_PREEXISTING"] == "original_value"


def test_unreadable_file_returns_false_via_the_outer_except(tmp_path):
    """A read failure anywhere in the body (not just a missing file) must
    still degrade to `False`, never raise — this is what the outer
    `except Exception` guards. Invalid UTF-8 bytes make `.read_text(encoding
    ="utf-8")` raise `UnicodeDecodeError`, which is a clean way to trigger it
    without touching filesystem permissions (fragile/platform-dependent)."""
    envfile = tmp_path / ".env"
    envfile.write_bytes(b"\xff\xfe\x00KEY=value\x00\xff")
    assert _env.load_env_file(envfile) is False


def test_default_path_used_when_none_given(monkeypatch):
    """No `path` argument → falls back to `_REPO_ROOT / ".env"`.

    The real repo root almost certainly has no `.env` checked in, so this
    just exercises the default-path branch and accepts either outcome.
    """
    result = _env.load_env_file()
    assert isinstance(result, bool)
