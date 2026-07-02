"""
tests/test_pilot_preflight.py — the pre-deployment checklist script.

Calls main([...]) directly with a monkeypatched environment + tmp DB so no
test touches the real profiles.db or the process env.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "pilot_preflight", _ROOT / "scripts" / "pilot_preflight.py")
pilot_preflight = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pilot_preflight)


@pytest.fixture()
def pilot_env(tmp_path, monkeypatch):
    """A fully-provisioned pilot environment against a tmp DB."""
    monkeypatch.setenv("ORIGINAL_ENV", "pilot")
    monkeypatch.setenv("SECRET_KEY", "x" * 64)
    monkeypatch.setenv("GUARD_DESTRUCTIVE", "1")
    monkeypatch.setenv("MAINTENANCE_TOKEN", "maint-token")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://original-pilot.onrender.com")
    monkeypatch.delenv("AI_LIKELIHOOD_ENABLED", raising=False)
    monkeypatch.delenv("AI_LIKELIHOOD_SHADOW", raising=False)
    return tmp_path / "preflight.db"


def _run(db, *extra):
    return pilot_preflight.main(["--db", str(db), *extra])


def test_fully_provisioned_pilot_passes(pilot_env, capsys):
    # Detector artifact is committed in-repo, so warm() should succeed;
    # backups are WARN-only.
    assert _run(pilot_env) == 0
    out = capsys.readouterr().out
    assert "READY" in out
    assert "0 failed" in out


def test_missing_secret_key_fails(pilot_env, monkeypatch, capsys):
    monkeypatch.delenv("SECRET_KEY")
    assert _run(pilot_env) == 1
    out = capsys.readouterr().out
    assert "[FAIL] SECRET_KEY" in out
    assert "NOT READY" in out


def test_wildcard_origins_fails(pilot_env, monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    assert _run(pilot_env) == 1


def test_demo_profile_downgrades_env_failures_to_warn(tmp_path, monkeypatch):
    monkeypatch.setenv("ORIGINAL_ENV", "demo")
    for var in ("SECRET_KEY", "GUARD_DESTRUCTIVE", "MAINTENANCE_TOKEN",
                "ALLOWED_ORIGINS", "AI_LIKELIHOOD_ENABLED", "AI_LIKELIHOOD_SHADOW"):
        monkeypatch.delenv(var, raising=False)
    assert _run(tmp_path / "demo.db", "--env", "demo") == 0


def test_stale_backups_warn_not_fail(pilot_env, tmp_path, monkeypatch, capsys):
    bdir = tmp_path / "backups"
    bdir.mkdir()
    old = bdir / "profiles-20200101-000000.db"
    old.write_text("stale")
    import os
    os.utime(old, (0, 0))   # epoch — definitely older than 26h
    assert _run(pilot_env, "--backup-dir", str(bdir)) == 0
    assert "[WARN] backups" in capsys.readouterr().out


def test_detector_flag_on_with_missing_artifact_fails(pilot_env, monkeypatch, tmp_path):
    monkeypatch.setenv("AI_LIKELIHOOD_SHADOW", "1")
    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(tmp_path / "missing.joblib"))
    assert _run(pilot_env) == 1
    # reset the singleton so later tests see a clean detector
    from original.ai_likelihood import reset_for_tests
    reset_for_tests()
