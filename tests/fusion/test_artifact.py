"""The loader must fail closed: a partially-trusted model is worse than none."""

from __future__ import annotations

import json

import numpy as np
import pytest

from original.fusion import artifact as artifact_module


def _valid_payload() -> dict:
    mu = [0.0, 0.0, 0.0]
    sd = [1.0, 1.0, 1.0]
    weights = [1.0, 2.0, -0.5]
    intercept = 0.25
    reference_inputs = [[0.1, 0.2, 0.3], [-0.4, 0.5, 0.0]]
    reference_outputs = [
        float(np.dot((np.array(x) - mu) / np.array(sd), weights) + intercept)
        for x in reference_inputs
    ]
    return {
        "schema_version": 1,
        "channel_order": ["peer_centered_z", "compression", "function_word_network"],
        "mu": mu,
        "sd": sd,
        "weights": weights,
        "intercept": intercept,
        "threshold_fa5": 0.5,
        "threshold_fa1": 1.5,
        "reference_inputs": reference_inputs,
        "reference_outputs": reference_outputs,
        "provenance": {"dataset": "unit-test", "n_development_authors": 120},
    }


@pytest.fixture()
def write_artifact(tmp_path, monkeypatch):
    def _write(payload):
        path = tmp_path / "fused.json"
        path.write_text(json.dumps(payload))
        monkeypatch.setenv("FUSED_SCORE_MODEL_PATH", str(path))
        artifact_module.reset_for_tests()
        return path

    artifact_module.reset_for_tests()
    yield _write
    artifact_module.reset_for_tests()


def test_valid_artifact_loads(write_artifact):
    write_artifact(_valid_payload())
    loaded = artifact_module.load_artifact()
    assert loaded is not None
    assert loaded.channel_order == ("peer_centered_z", "compression", "function_word_network")
    assert loaded.intercept == pytest.approx(0.25)


def test_log_odds_is_the_standardized_dot_product(write_artifact):
    write_artifact(_valid_payload())
    loaded = artifact_module.load_artifact()
    values = np.array([0.1, 0.2, 0.3])
    expected = float(np.dot(values, [1.0, 2.0, -0.5]) + 0.25)
    assert loaded.log_odds(values) == pytest.approx(expected)


def test_band_boundaries_follow_the_thresholds(write_artifact):
    write_artifact(_valid_payload())
    loaded = artifact_module.load_artifact()
    assert loaded.band(0.4) == "consistent"
    assert loaded.band(0.5) == "inconclusive"
    assert loaded.band(1.4) == "inconclusive"
    assert loaded.band(1.5) == "divergent"


def test_missing_file_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("FUSED_SCORE_MODEL_PATH", str(tmp_path / "absent.json"))
    artifact_module.reset_for_tests()
    assert artifact_module.load_artifact() is None


def test_schema_version_drift_fails_closed(write_artifact):
    payload = _valid_payload()
    payload["schema_version"] = 2
    write_artifact(payload)
    assert artifact_module.load_artifact() is None


def test_unknown_channel_name_fails_closed(write_artifact):
    payload = _valid_payload()
    payload["channel_order"] = ["peer_centered_z", "compression", "astrology"]
    write_artifact(payload)
    assert artifact_module.load_artifact() is None


def test_weight_length_mismatch_fails_closed(write_artifact):
    payload = _valid_payload()
    payload["weights"] = [1.0, 2.0]
    write_artifact(payload)
    assert artifact_module.load_artifact() is None


def test_reference_prediction_drift_fails_closed(write_artifact):
    payload = _valid_payload()
    payload["reference_outputs"] = [value + 0.01 for value in payload["reference_outputs"]]
    write_artifact(payload)
    assert artifact_module.load_artifact() is None


def test_non_monotone_thresholds_fail_closed(write_artifact):
    payload = _valid_payload()
    payload["threshold_fa5"], payload["threshold_fa1"] = 1.5, 0.5
    write_artifact(payload)
    assert artifact_module.load_artifact() is None


def test_two_channel_artifact_is_accepted(write_artifact):
    payload = _valid_payload()
    payload["channel_order"] = ["peer_centered_z", "compression"]
    payload["mu"], payload["sd"], payload["weights"] = [0.0, 0.0], [1.0, 1.0], [1.0, 2.0]
    payload["reference_inputs"] = [[0.1, 0.2], [-0.4, 0.5]]
    payload["reference_outputs"] = [
        float(np.dot(x, [1.0, 2.0]) + payload["intercept"]) for x in payload["reference_inputs"]
    ]
    write_artifact(payload)
    loaded = artifact_module.load_artifact()
    assert loaded is not None
    assert loaded.channel_order == ("peer_centered_z", "compression")


def test_result_is_cached_after_first_load(write_artifact):
    path = write_artifact(_valid_payload())
    first = artifact_module.load_artifact()
    path.unlink()
    assert artifact_module.load_artifact() is first
