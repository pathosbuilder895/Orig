"""The committed artifact must load under the production loader."""

from __future__ import annotations

import json

from original.fusion.artifact import (
    DEFAULT_ARTIFACT_PATH,
    EXPECTED_SCHEMA_VERSION,
    load_artifact,
    reset_for_tests,
)
from original.fusion.channels import CHANNEL_NAMES


def test_shipped_artifact_exists():
    assert DEFAULT_ARTIFACT_PATH.exists(), f"missing {DEFAULT_ARTIFACT_PATH}"


def test_shipped_artifact_loads_under_the_production_loader(monkeypatch):
    monkeypatch.delenv("FUSED_SCORE_MODEL_PATH", raising=False)
    reset_for_tests()
    loaded = load_artifact()
    reset_for_tests()
    assert loaded is not None, "committed artifact failed validation"
    assert all(name in CHANNEL_NAMES for name in loaded.channel_order)
    assert loaded.threshold_fa5 < loaded.threshold_fa1


def test_shipped_artifact_records_its_provenance():
    payload = json.loads(DEFAULT_ARTIFACT_PATH.read_text())
    assert payload["schema_version"] == EXPECTED_SCHEMA_VERSION
    provenance = payload["provenance"]
    assert provenance["n_references"] == 8
    assert provenance["n_development_authors"] >= 100
    assert provenance["dataset"]
    assert provenance["trained"]
