"""Behavioral tests for original/cli/security_audit.py (branch-coverage part 3, task 2).

``original/cli/security_audit.py`` was 0% covered — the largest single-file
branch gap in the repo (76 missing branches). It is a runnable self-audit CLI
that reads the dormant v1 pydantic ``Settings`` (``original/core/config.py``,
reached only via this module and ``original/cli/delete_student.py``), scans
the repo tree for raw-SQL patterns, and shells out to ``pip audit``.

Isolation techniques used below (none of them touch the real repo tree, real
network, or a real ``pip-audit`` subprocess):

* ``check_jwt_config`` / ``check_rate_limiting`` / ``check_tls_readiness`` /
  ``check_database_security`` / ``check_cors_configuration`` all start with
  ``settings = get_settings()``. ``get_settings`` is ``@lru_cache``-memoised
  process-wide, so rather than fight that cache with env vars (which, for
  ``ALLOWED_ORIGINS``, doesn't even work — ``Settings._ALLOWED_ORIGINS_STR``
  is a leading-underscore pydantic *private* attribute, invisible to
  pydantic-settings' env-var sourcing; confirmed by direct experiment: setting
  the ``ALLOWED_ORIGINS`` env var has zero effect on
  ``Settings().ALLOWED_ORIGINS``, which always resolves to the four
  hard-coded localhost defaults), every test monkeypatches the ``get_settings``
  name this module imported to return a plain ``SimpleNamespace`` stub with
  exactly the attributes the check under test reads. This is the same
  technique already used in ``tests/test_persistence_error_arms.py`` for
  ``original/db/session.py``'s identical lru_cache problem.

* ``check_raw_sql`` and ``check_input_validation`` both compute
  ``repo_root = Path(__file__).parent.parent.parent`` — there is no
  parameter or seam to inject a scan root through. ``__file__`` here is a
  bare name resolved from the *module's* globals at call time (confirmed by
  direct experiment), so monkeypatching the module attribute
  ``security_audit.__file__`` to point at a ``tmp_path`` tree shaped like
  ``<tmp>/fake_repo/original/cli/security_audit.py`` redirects
  ``repo_root`` to ``<tmp>/fake_repo`` without touching the real filesystem.

* ``check_pip_audit`` monkeypatches ``subprocess.run`` with canned
  ``CompletedProcess`` results or raised exceptions — never a real
  ``pip audit`` invocation.

* ``run_all_checks`` orchestration is tested by monkeypatching each
  ``check_*`` *instance* attribute to a trivial stub that appends directly
  to ``self.issues`` / ``self.warnings`` (or raises), decoupling the
  orchestration branches (all-green / warning-only / issue-found /
  exception-caught) from the correctness of the individual checks, which is
  covered separately above.

The module-level ``if __name__ == "__main__": sys.exit(main())`` guard
(lines 414-415) is intentionally left uncovered. Exercising it would require
running the file as ``__main__`` (via ``runpy`` or a subprocess), which
re-imports a *second*, independent ``SecurityAudit`` class the test-side
monkeypatches above cannot reach — so it would run the real, unstubbed
audit: a real scan of the actual repo tree and a real ``pip audit``
subprocess attempt, exactly what this task's brief says not to do. It is
also standard, non-branching Python script boilerplate carrying no
project-specific logic. ``main()`` itself is fully covered directly.

No bug in a ``check_*`` method was found (each one's "pass" arm and
"finding" arm both reachably fire, and none crashes on its happy path).
One inert-but-harmless quirk noted for the record: ``main()``'s
``--exit-code`` flag is parsed into ``parsed_args.exit_code`` but never
read anywhere — ``run_all_checks()`` already unconditionally returns 1
when ``self.issues`` is non-empty, with or without the flag. It doesn't
change behavior (the CLI does what its help text promises either way), so
it isn't a "check can never fire" class of bug and doesn't block this task;
``test_main_exit_code_flag_is_accepted_but_inert`` documents it directly.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from original.cli import security_audit
from original.cli.security_audit import SecurityAudit

# ── Settings stub helper ──────────────────────────────────────────────────────

_SETTINGS_DEFAULTS = dict(
    ACCESS_TOKEN_EXPIRE_MINUTES=15,
    REFRESH_TOKEN_EXPIRE_DAYS=7,
    SECRET_KEY="x" * 40,
    ALGORITHM="HS256",
    RATE_LIMIT_DEFAULT="60/minute",
    RATE_LIMIT_AUTH="5/minute",
    RATE_LIMIT_SCORING="10/minute",
    ENVIRONMENT="development",
    ORIGINAL_BASE_URL="http://localhost:8000",
    DEBUG=False,
    DATABASE_URL="sqlite:///./dev.db",
    ALLOWED_ORIGINS=["http://localhost:3000"],
)


def _settings(**overrides):
    values = dict(_SETTINGS_DEFAULTS)
    values.update(overrides)
    return SimpleNamespace(**values)


def _patch_settings(monkeypatch, **overrides):
    monkeypatch.setattr(security_audit, "get_settings", lambda: _settings(**overrides))


@pytest.fixture
def audit():
    return SecurityAudit(verbose=True)


# ── _print_info ──────────────────────────────────────────────────────────────


def test_print_info_suppressed_when_not_verbose(capsys):
    """Every check_* test below uses the verbose=True `audit` fixture, so
    this covers _print_info's if self.verbose: False arm on its own."""
    quiet_audit = SecurityAudit(verbose=False)
    quiet_audit._print_info("should not appear")
    assert capsys.readouterr().out == ""


# ── check_jwt_config ─────────────────────────────────────────────────────────


def test_jwt_config_all_reasonable_values_pass(audit, monkeypatch, capsys):
    _patch_settings(
        monkeypatch,
        ACCESS_TOKEN_EXPIRE_MINUTES=15,
        REFRESH_TOKEN_EXPIRE_DAYS=7,
        SECRET_KEY="s" * 40,
        ALGORITHM="HS256",
    )
    audit.check_jwt_config()
    assert audit.issues == []
    assert audit.warnings == []
    assert any("Access token expiry is reasonable" in p for p in audit.passes)
    assert any("Refresh token expiry is reasonable" in p for p in audit.passes)
    assert any("SECRET_KEY is strong" in p for p in audit.passes)
    assert any("JWT algorithm is HS256" in p for p in audit.passes)


def test_jwt_config_short_expiry_long_refresh_weak_secret_wrong_algorithm(audit, monkeypatch):
    _patch_settings(
        monkeypatch,
        ACCESS_TOKEN_EXPIRE_MINUTES=3,  # < 5 -> warn
        REFRESH_TOKEN_EXPIRE_DAYS=45,  # > 30 -> warn
        SECRET_KEY="short",  # < 32 chars -> issue
        ALGORITHM="RS256",  # != HS256 -> warn
    )
    audit.check_jwt_config()
    assert any("very short" in w for w in audit.warnings)
    assert any("very long" in w and "Refresh" in w for w in audit.warnings)
    assert any("SECRET_KEY is too short" in i for i in audit.issues)
    assert any("JWT algorithm is RS256" in w for w in audit.warnings)


def test_jwt_config_access_token_expiry_too_long(audit, monkeypatch):
    """Separate case for the ACCESS_TOKEN_EXPIRE_MINUTES > 60 elif arm --
    the < 5 branch above short-circuits it, so it needs its own value."""
    _patch_settings(monkeypatch, ACCESS_TOKEN_EXPIRE_MINUTES=90)
    audit.check_jwt_config()
    assert any("very long" in w and "Access" in w for w in audit.warnings)


# ── check_raw_sql ────────────────────────────────────────────────────────────


def _point_repo_root_at(monkeypatch, fake_repo):
    """Redirect check_raw_sql/check_input_validation's repo_root computation
    (Path(__file__).parent.parent.parent) at a tmp_path tree shaped like the
    real original/cli/ layout, without touching the real filesystem."""
    fake_module_file = fake_repo / "original" / "cli" / "security_audit.py"
    monkeypatch.setattr(security_audit, "__file__", str(fake_module_file))


def test_raw_sql_clean_tree_reports_no_issues(audit, monkeypatch, tmp_path_factory):
    # NOTE: deliberately tmp_path_factory.mktemp(...) rather than the tmp_path
    # fixture. tmp_path names its directory after the test function (e.g.
    # ".../test_raw_sql_clean_tree_reports_no_issues0/..."), and since
    # repo_root's *absolute* path is what check_raw_sql string-matches
    # against, a base dir starting with "test_" makes "/test" in str(py_file)
    # true for every single file scanned -- silently skipping everything,
    # including files this test means to actually exercise. Confirmed by
    # direct experiment. "sqlscan" avoids the "test" substring entirely.
    fake_repo = tmp_path_factory.mktemp("sqlscan") / "fake_repo"

    clean_pkg = fake_repo / "clean_pkg"
    clean_pkg.mkdir(parents=True)
    (clean_pkg / "ok.py").write_text("x = 1\ndef add(a, b):\n    return a + b\n")

    # Path containing the literal "/test" segment -- skipped by the
    # "/test" in str(py_file) arm even though it contains an offender.
    test_dir = fake_repo / "test"
    test_dir.mkdir(parents=True)
    (test_dir / "other_offender.py").write_text('cursor.execute("SELECT 1")\n')

    # Filename starting with test_ -- skipped by the other half of the "or".
    somepkg = fake_repo / "somepkg"
    somepkg.mkdir(parents=True)
    (somepkg / "test_ignored.py").write_text('cursor.execute("SELECT 1")\n')

    # Invalid UTF-8 -- exercises the read_text() except branch; must not
    # crash and must not count as an issue.
    binpkg = fake_repo / "binpkg"
    binpkg.mkdir(parents=True)
    (binpkg / "weird.py").write_bytes(b"\xff\xfe\x00\x01garbage")

    _point_repo_root_at(monkeypatch, fake_repo)

    audit.check_raw_sql()

    assert audit.issues == []
    assert any("No obvious raw SQL patterns detected" in p for p in audit.passes)


def test_raw_sql_detects_offenders_and_skips_commented_line(audit, monkeypatch, tmp_path_factory):
    # See the NOTE in test_raw_sql_clean_tree_reports_no_issues above -- must
    # not use the tmp_path fixture here, its directory name starts with
    # "test_" and would make check_raw_sql skip every file as if it were a
    # test file.
    fake_repo = tmp_path_factory.mktemp("sqlscan") / "fake_repo"
    pkg = fake_repo / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "bad.py").write_text(
        "def run(sid):\n"
        '    cursor.execute("SELECT * FROM foo WHERE id = %s" % sid)\n'
        '    # cursor.execute("SELECT * FROM commented_out_table")\n'
        '    stmt = text("SELECT * FROM bar")\n'
        "    return stmt\n"
    )

    _point_repo_root_at(monkeypatch, fake_repo)

    audit.check_raw_sql()

    assert len(audit.issues) == 1
    # Two live matches (the .execute( line via pattern 1, the text( line via
    # pattern 2); the commented-out .execute( line is excluded.
    assert "Found 2 potential raw SQL usage(s)" in audit.issues[0]


# ── check_rate_limiting ──────────────────────────────────────────────────────


def test_rate_limiting_all_strict_values_pass(audit, monkeypatch):
    _patch_settings(
        monkeypatch,
        RATE_LIMIT_DEFAULT="60/minute",
        RATE_LIMIT_AUTH="5/minute",
        RATE_LIMIT_SCORING="10/minute",
    )
    audit.check_rate_limiting()
    assert audit.warnings == []
    assert any("Default rate limit is reasonable" in p for p in audit.passes)
    assert any("Auth rate limit is strict" in p for p in audit.passes)
    assert any("Scoring rate limit is strict" in p for p in audit.passes)


def test_rate_limiting_permissive_values_warn(audit, monkeypatch):
    _patch_settings(
        monkeypatch,
        RATE_LIMIT_DEFAULT="30/minute",  # not 60/minute -> warn
        RATE_LIMIT_AUTH="100/minute",  # not 5/minute, > 10 -> warn (else arm)
        RATE_LIMIT_SCORING="50/minute",  # > 10 -> no print at all (missing else)
    )
    audit.check_rate_limiting()
    assert any("Default rate limit is 30/minute" in w for w in audit.warnings)
    assert any("very permissive" in w for w in audit.warnings)
    # Scoring rate limit has no message in either list when > 10 -- the
    # "if" has no else, this is the branch-not-taken arm.
    assert not any("Scoring" in p for p in audit.passes)
    assert not any("Scoring" in w for w in audit.warnings)


def test_rate_limiting_auth_reasonable_but_not_exactly_5_per_minute(audit, monkeypatch):
    """Covers the elif int(...) <= 10 arm specifically (not the first
    "5/minute" substring branch, and not the permissive else branch)."""
    _patch_settings(monkeypatch, RATE_LIMIT_AUTH="8/minute")
    audit.check_rate_limiting()
    assert any("Auth rate limit is reasonable" in p for p in audit.passes)


# ── check_input_validation ───────────────────────────────────────────────────


def test_input_validation_schemas_file_missing(audit, monkeypatch, tmp_path):
    fake_repo = tmp_path / "fake_repo_no_schemas"
    fake_repo.mkdir()
    _point_repo_root_at(monkeypatch, fake_repo)

    audit.check_input_validation()

    assert any("original/schemas.py not found" in w for w in audit.warnings)


def test_input_validation_schemas_file_has_validators(audit, monkeypatch, tmp_path):
    fake_repo = tmp_path / "fake_repo_with_validators"
    original_dir = fake_repo / "original"
    original_dir.mkdir(parents=True)
    (original_dir / "schemas.py").write_text(
        "from pydantic import field_validator\n\nclass Foo:\n    pass\n"
    )
    _point_repo_root_at(monkeypatch, fake_repo)

    audit.check_input_validation()

    assert any("Pydantic validators found" in p for p in audit.passes)


def test_input_validation_schemas_file_has_no_validators(audit, monkeypatch, tmp_path):
    fake_repo = tmp_path / "fake_repo_no_validators"
    original_dir = fake_repo / "original"
    original_dir.mkdir(parents=True)
    (original_dir / "schemas.py").write_text("class Foo:\n    bar: str\n")
    _point_repo_root_at(monkeypatch, fake_repo)

    audit.check_input_validation()

    assert any("No obvious input validators found" in w for w in audit.warnings)


# ── check_pip_audit ──────────────────────────────────────────────────────────


def _patch_subprocess_run(monkeypatch, fn):
    monkeypatch.setattr(security_audit.subprocess, "run", fn)


def test_pip_audit_clean(audit, monkeypatch):
    _patch_subprocess_run(
        monkeypatch,
        lambda *a, **k: subprocess.CompletedProcess(args=a, returncode=0, stdout="", stderr=""),
    )
    audit.check_pip_audit()
    assert any("No known vulnerabilities" in p for p in audit.passes)


def test_pip_audit_finds_vulnerabilities(audit, monkeypatch):
    _patch_subprocess_run(
        monkeypatch,
        lambda *a, **k: subprocess.CompletedProcess(
            args=a,
            returncode=1,
            stdout='{"vulnerabilities": ["found a Vulnerable package"]}',
            stderr="",
        ),
    )
    audit.check_pip_audit()
    assert any("pip audit found potential vulnerabilities" in w for w in audit.warnings)


def test_pip_audit_nonzero_no_vulnerable_text_prints_nothing(audit, monkeypatch):
    """returncode < 0 (e.g. killed by signal) with no 'vulnerable' substring
    in stdout hits the inner condition's False arm -- no message at all."""
    _patch_subprocess_run(
        monkeypatch,
        lambda *a, **k: subprocess.CompletedProcess(args=a, returncode=-9, stdout="", stderr=""),
    )
    audit.check_pip_audit()
    assert audit.passes == []
    assert audit.warnings == []
    assert audit.issues == []


def test_pip_audit_not_installed(audit, monkeypatch):
    def raise_fnf(*a, **k):
        raise FileNotFoundError()

    _patch_subprocess_run(monkeypatch, raise_fnf)
    audit.check_pip_audit()
    assert any("pip audit not installed" in w for w in audit.warnings)


def test_pip_audit_times_out(audit, monkeypatch):
    def raise_timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd=["pip", "audit"], timeout=30)

    _patch_subprocess_run(monkeypatch, raise_timeout)
    audit.check_pip_audit()
    assert any("pip audit timed out" in w for w in audit.warnings)


def test_pip_audit_unexpected_exception(audit, monkeypatch):
    def raise_other(*a, **k):
        raise ValueError("boom")

    _patch_subprocess_run(monkeypatch, raise_other)
    audit.check_pip_audit()
    assert any("pip audit check failed: boom" in w for w in audit.warnings)


# ── check_tls_readiness ──────────────────────────────────────────────────────


def test_tls_readiness_non_production(audit, monkeypatch):
    _patch_settings(monkeypatch, ENVIRONMENT="development")
    audit.check_tls_readiness()
    assert any("non-production" in p for p in audit.passes)
    assert audit.issues == []


def test_tls_readiness_production_https_and_debug_off_passes(audit, monkeypatch):
    _patch_settings(
        monkeypatch,
        ENVIRONMENT="production",
        ORIGINAL_BASE_URL="https://original.example.com",
        DEBUG=False,
    )
    audit.check_tls_readiness()
    assert any("Production base URL is HTTPS" in p for p in audit.passes)
    assert any("DEBUG mode is disabled" in p for p in audit.passes)
    assert audit.issues == []


def test_tls_readiness_production_http_and_debug_on_fails(audit, monkeypatch):
    _patch_settings(
        monkeypatch,
        ENVIRONMENT="production",
        ORIGINAL_BASE_URL="http://original.example.com",
        DEBUG=True,
    )
    audit.check_tls_readiness()
    assert any("not HTTPS" in i for i in audit.issues)
    assert any("DEBUG mode is enabled in production" in i for i in audit.issues)


# ── check_database_security ──────────────────────────────────────────────────


def test_database_security_sqlite_development_ok(audit, monkeypatch):
    _patch_settings(monkeypatch, DATABASE_URL="sqlite:///./dev.db", ENVIRONMENT="development")
    audit.check_database_security()
    assert any("SQLite used in development" in p for p in audit.passes)
    assert audit.issues == []


def test_database_security_sqlite_production_is_an_issue(audit, monkeypatch):
    _patch_settings(monkeypatch, DATABASE_URL="sqlite:///./prod.db", ENVIRONMENT="production")
    audit.check_database_security()
    assert any("SQLite detected in production" in i for i in audit.issues)


def test_database_security_postgres_with_sslmode_ok(audit, monkeypatch):
    _patch_settings(
        monkeypatch,
        DATABASE_URL="postgresql://u:p@host/db?sslmode=require",
        ENVIRONMENT="production",
    )
    audit.check_database_security()
    assert any("PostgreSQL detected" in p for p in audit.passes)
    assert any("SSL/TLS configured" in p for p in audit.passes)


def test_database_security_postgres_no_sslmode_production_warns(audit, monkeypatch):
    _patch_settings(
        monkeypatch,
        DATABASE_URL="postgresql://u:p@host/db",
        ENVIRONMENT="production",
    )
    audit.check_database_security()
    assert any("SSL/TLS not explicitly configured" in w for w in audit.warnings)


def test_database_security_postgres_no_sslmode_non_production_prints_nothing_extra(
    audit, monkeypatch
):
    """Non-production Postgres without sslmode hits neither the ok-sslmode
    arm nor the production-warn arm -- the missing-else branch."""
    _patch_settings(
        monkeypatch,
        DATABASE_URL="postgresql://u:p@host/db",
        ENVIRONMENT="development",
    )
    audit.check_database_security()
    assert any("PostgreSQL detected" in p for p in audit.passes)
    assert not any("SSL" in w for w in audit.warnings)
    assert not any("SSL" in p for p in audit.passes)


def test_database_security_unknown_db_type_warns(audit, monkeypatch):
    _patch_settings(monkeypatch, DATABASE_URL="mysql://u:p@host/db", ENVIRONMENT="development")
    audit.check_database_security()
    assert any("Unknown database type" in w for w in audit.warnings)


# ── check_cors_configuration ─────────────────────────────────────────────────


def test_cors_wildcard_is_an_issue(audit, monkeypatch):
    _patch_settings(monkeypatch, ALLOWED_ORIGINS=["*"])
    audit.check_cors_configuration()
    assert any("allow all origins" in i for i in audit.issues)


def test_cors_localhost_in_production_warns(audit, monkeypatch):
    _patch_settings(
        monkeypatch,
        ALLOWED_ORIGINS=["http://localhost:3000"],
        ENVIRONMENT="production",
    )
    audit.check_cors_configuration()
    assert any("localhost allowed in production" in w for w in audit.warnings)


def test_cors_no_localhost_no_wildcard_is_ok(audit, monkeypatch):
    """Covers the first half of the `and` (localhost in origins) being
    False, falling straight through to the else."""
    _patch_settings(
        monkeypatch,
        ALLOWED_ORIGINS=["https://original.example.com"],
        ENVIRONMENT="production",
    )
    audit.check_cors_configuration()
    assert any("CORS origins are restricted" in p for p in audit.passes)


def test_cors_localhost_but_not_production_is_ok(audit, monkeypatch):
    """Covers the second half of the `and` (ENVIRONMENT == production)
    being False after the first half was True."""
    _patch_settings(
        monkeypatch,
        ALLOWED_ORIGINS=["http://localhost:3000"],
        ENVIRONMENT="development",
    )
    audit.check_cors_configuration()
    assert any("CORS origins are restricted" in p for p in audit.passes)


# ── print_summary ────────────────────────────────────────────────────────────


def test_print_summary_all_green(audit, capsys):
    audit.print_summary()
    out = capsys.readouterr().out
    assert "Passes:   0" in out
    assert "Warnings: 0" in out
    assert "Issues:   0" in out
    assert "[ISSUES]" not in out
    assert "[WARNINGS]" not in out


def test_print_summary_with_findings(audit, capsys):
    audit.issues.append("bad thing happened")
    audit.warnings.append("mildly concerning thing")
    audit.passes.append("something went fine")
    audit.print_summary()
    out = capsys.readouterr().out
    assert "Passes:   1" in out
    assert "Warnings: 1" in out
    assert "Issues:   1" in out
    assert "[ISSUES]" in out
    assert "- bad thing happened" in out
    assert "[WARNINGS]" in out
    assert "- mildly concerning thing" in out


# ── run_all_checks ───────────────────────────────────────────────────────────

_ALL_CHECK_NAMES = [
    "check_jwt_config",
    "check_raw_sql",
    "check_rate_limiting",
    "check_input_validation",
    "check_pip_audit",
    "check_tls_readiness",
    "check_database_security",
    "check_cors_configuration",
]


def _stub_all_checks(monkeypatch, audit_obj, overrides=None):
    """Replace every check_* the orchestration calls with a no-op, except
    names present in `overrides`, which get that specific callable instead.
    Because these are plain functions assigned onto the *instance* (not the
    class), calling audit_obj.check_x() finds them directly in
    audit_obj.__dict__ without going through the descriptor/binding
    protocol -- so the stubs take zero arguments, not (self)."""
    overrides = overrides or {}
    for name in _ALL_CHECK_NAMES:
        monkeypatch.setattr(audit_obj, name, overrides.get(name, lambda: None))


def test_run_all_checks_all_green(monkeypatch):
    audit_obj = SecurityAudit()
    _stub_all_checks(monkeypatch, audit_obj)
    fake_log = Mock()
    monkeypatch.setattr(security_audit, "log", fake_log)

    rc = audit_obj.run_all_checks()

    assert rc == 0
    assert audit_obj.issues == []
    assert audit_obj.warnings == []
    fake_log.info.assert_called_once_with("Security audit completed successfully")
    fake_log.warning.assert_not_called()
    fake_log.exception.assert_not_called()


def test_run_all_checks_warning_only(monkeypatch):
    audit_obj = SecurityAudit()

    def warn_check():
        audit_obj._print_warn("something to keep an eye on")

    _stub_all_checks(monkeypatch, audit_obj, overrides={"check_jwt_config": warn_check})
    fake_log = Mock()
    monkeypatch.setattr(security_audit, "log", fake_log)

    rc = audit_obj.run_all_checks()

    assert rc == 0
    assert audit_obj.issues == []
    assert len(audit_obj.warnings) == 1
    fake_log.info.assert_called_once_with("Security audit completed with 1 warning(s)")
    fake_log.warning.assert_not_called()


def test_run_all_checks_with_issue_returns_1(monkeypatch):
    audit_obj = SecurityAudit()

    def err_check():
        audit_obj._print_err("something is actually broken")

    _stub_all_checks(monkeypatch, audit_obj, overrides={"check_jwt_config": err_check})
    fake_log = Mock()
    monkeypatch.setattr(security_audit, "log", fake_log)

    rc = audit_obj.run_all_checks()

    assert rc == 1
    assert len(audit_obj.issues) == 1
    fake_log.warning.assert_called_once_with("Security audit found 1 issue(s)")
    fake_log.info.assert_not_called()


def test_run_all_checks_catches_exception_and_returns_1(monkeypatch, capsys):
    audit_obj = SecurityAudit()

    def boom():
        raise RuntimeError("kaboom")

    # Only the first check needs stubbing -- it raises before any later
    # check in the sequence is ever called.
    monkeypatch.setattr(audit_obj, "check_jwt_config", boom)
    fake_log = Mock()
    monkeypatch.setattr(security_audit, "log", fake_log)

    rc = audit_obj.run_all_checks()

    out = capsys.readouterr().out
    assert rc == 1
    assert "Audit failed: kaboom" in out
    fake_log.exception.assert_called_once_with("Security audit failed")


# ── main() ───────────────────────────────────────────────────────────────────


def test_main_default_flags_and_return_value(monkeypatch):
    captured = {}

    def fake_run_all_checks(self):
        captured["verbose"] = self.verbose
        captured["fix"] = self.fix
        return 0

    monkeypatch.setattr(SecurityAudit, "run_all_checks", fake_run_all_checks)

    rc = security_audit.main([])

    assert rc == 0
    assert captured == {"verbose": False, "fix": False}


def test_main_verbose_and_fix_flags_wire_through(monkeypatch):
    captured = {}

    def fake_run_all_checks(self):
        captured["verbose"] = self.verbose
        captured["fix"] = self.fix
        return 1

    monkeypatch.setattr(SecurityAudit, "run_all_checks", fake_run_all_checks)

    rc = security_audit.main(["--verbose", "--fix"])

    assert rc == 1
    assert captured == {"verbose": True, "fix": True}


def test_main_exit_code_flag_is_accepted_but_inert(monkeypatch):
    """--exit-code parses cleanly (argparse accepts it) but main() never
    reads parsed_args.exit_code -- the return value is run_all_checks()'s
    return value either way. Documents the quirk rather than hiding it."""

    def fake_run_all_checks(self):
        return 1

    monkeypatch.setattr(SecurityAudit, "run_all_checks", fake_run_all_checks)

    rc_with_flag = security_audit.main(["--exit-code"])
    rc_without_flag = security_audit.main([])

    assert rc_with_flag == rc_without_flag == 1
