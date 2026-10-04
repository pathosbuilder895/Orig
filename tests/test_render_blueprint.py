"""Pins the launch shape of render.yaml (docs/BLUEBOOK_LAUNCH_CHECKLIST.md).

A blueprint is deployed by clicking, not by CI, so nothing else would notice
an edit that reattaches the SQLite disk, skips migrations, or commits a
secret's value."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

BLUEPRINT = yaml.safe_load((Path(__file__).resolve().parents[1] / "render.yaml").read_text())
SERVICES = {s["name"]: s for s in BLUEPRINT["services"]}
SECRETS = {
    "SECRET_KEY",
    "MAINTENANCE_TOKEN",
    "SENDGRID_API_KEY",
    "SENTRY_DSN",
    "LTI_PRIVATE_KEY",
    "BBOOK_EXTERNAL_SECRET",
    "BACKUP_OFFBOX_ACCESS_KEY_ID",
    "BACKUP_OFFBOX_SECRET_ACCESS_KEY",
}


def _env(service: str) -> dict[str, dict]:
    return {e["key"]: e for e in SERVICES[service]["envVars"]}


def test_pilot_runs_on_managed_postgres_and_migrates_before_each_deploy():
    pilot = SERVICES["original-pilot"]
    env = _env("original-pilot")
    assert env["REPO_BACKEND"]["value"] == "postgres"
    assert env["DATABASE_URL"]["fromDatabase"]["name"] == "original-db"
    assert pilot["preDeployCommand"] == "alembic upgrade head"
    assert "disk" not in pilot
    assert "requirements-pilot.lock.txt" in pilot["buildCommand"]
    assert env["ORIGINAL_ENV"]["value"] == "pilot"
    assert [d["name"] for d in BLUEPRINT["databases"]] == ["original-db"]
    assert BLUEPRINT["databases"][0]["plan"] != "free"  # free Postgres expires


def test_launch_settings_are_declared_for_the_dashboard():
    env = _env("original-pilot")
    for key in ("SENDGRID_API_KEY", "MAIL_FROM", "PUBLIC_BASE_URL", "SENTRY_DSN"):
        assert env[key].get("sync") is False, key


def test_classroom_release_does_not_enable_research_scoring():
    env = _env("original-pilot")
    for key in (
        "CONTEXT_MANIFEST_ENABLED", "ADAPTIVE_WEIGHTS_ENABLED",
        "STYLE_AUTHORSHIP_ENABLED", "FUSED_SCORE_ENABLED",
        "FUSED_SCORE_SHADOW", "LONGITUDINAL_DRIFT_ENABLED",
    ):
        assert env[key]["value"] == "0", key


@pytest.mark.parametrize("service", sorted(SERVICES))
def test_no_secret_value_is_committed(service):
    for key, entry in _env(service).items():
        if key in SECRETS:
            assert "value" not in entry and entry.get("sync") is False, f"{service}:{key}"


def test_backup_job_fails_loudly_when_unconfigured():
    job = SERVICES["original-pg-backup"]
    assert job["type"] == "cron"
    assert job["startCommand"] == "python scripts/pg_backup_offbox.py --require-upload"
    assert _env("original-pg-backup")["DATABASE_URL"]["fromDatabase"]["name"] == "original-db"


def test_deferred_lti_is_not_configured_on_the_pilot():
    """Canvas/LTI is deferred: the blueprint must not invite an operator to
    fill in keys that would make /lti/* launches live."""
    env = _env("original-pilot")
    assert not [key for key in env if key.startswith("LTI_")]
