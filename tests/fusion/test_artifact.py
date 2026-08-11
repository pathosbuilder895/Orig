"""The loader must fail closed: a partially-trusted model is worse than none."""

from __future__ import annotations

import json

import numpy as np
import pytest

from original.fusion import artifact as artifact_module


def _standardized_log_odds(values, mu, sd, weights, intercept) -> float:
    """The real standardized formula, computed independently of artifact.py."""
    standardized = (np.array(values) - np.array(mu)) / np.array(sd)
    return float(np.dot(standardized, weights) + intercept)


def _valid_payload() -> dict:
    # mu/sd deliberately non-trivial (distinct, non-zero, not all equal) so
    # that (values - mu) / sd is NOT the identity transform: a test built on
    # this fixture can only pass if the standardization is actually applied.
    mu = [1.5, -2.0, 0.25]
    sd = [2.0, 0.5, 4.0]
    weights = [1.0, 2.0, -0.5]
    intercept = 0.25
    reference_inputs = [[0.1, 0.2, 0.3], [-0.4, 0.5, 0.0]]
    reference_outputs = [
        _standardized_log_odds(x, mu, sd, weights, intercept) for x in reference_inputs
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
    payload = _valid_payload()
    write_artifact(payload)
    loaded = artifact_module.load_artifact()
    values = np.array([0.1, 0.2, 0.3])
    expected = _standardized_log_odds(
        values, payload["mu"], payload["sd"], payload["weights"], payload["intercept"]
    )
    # Sanity check that the fixture is actually exercising standardization —
    # if this fails, the fixture regressed back to an identity transform and
    # the test above would no longer be able to catch a broken formula.
    raw_dot = float(np.dot(values, payload["weights"]) + payload["intercept"])
    assert expected != pytest.approx(raw_dot)
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


def test_duplicate_channel_name_fails_closed(write_artifact):
    """A repeated channel name (e.g. ["compression", "compression"]) would
    otherwise pass every other check: both names are known, mu/sd/weights
    still line up length-wise with channel_order, and the reference
    self-check is internally consistent with the wrong model — it just
    silently double-counts one channel and drops another (Minor, 2026-08 fix
    pass)."""
    payload = _valid_payload()
    payload["channel_order"] = ["compression", "compression"]
    payload["mu"], payload["sd"], payload["weights"] = [0.0, 0.0], [1.0, 1.0], [1.0, 1.0]
    payload["reference_inputs"] = [[0.1, 0.2]]
    payload["reference_outputs"] = [
        float(np.dot([0.1, 0.2], [1.0, 1.0]) + payload["intercept"])
    ]
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


def test_zero_sd_fails_closed(write_artifact):
    payload = _valid_payload()
    payload["sd"][0] = 0.0
    write_artifact(payload)
    assert artifact_module.load_artifact() is None


def test_negative_sd_fails_closed(write_artifact):
    payload = _valid_payload()
    payload["sd"][1] = -2.0
    write_artifact(payload)
    assert artifact_module.load_artifact() is None


def test_nan_in_mu_fails_closed(write_artifact):
    payload = _valid_payload()
    payload["mu"][1] = float("nan")
    write_artifact(payload)
    assert artifact_module.load_artifact() is None


def test_nan_in_weights_fails_closed(write_artifact):
    payload = _valid_payload()
    payload["weights"][0] = float("nan")
    write_artifact(payload)
    assert artifact_module.load_artifact() is None


def test_nan_in_intercept_fails_closed(write_artifact):
    payload = _valid_payload()
    payload["intercept"] = float("nan")
    write_artifact(payload)
    assert artifact_module.load_artifact() is None


def test_reference_drift_comparison_is_nan_safe(write_artifact):
    """Regression: the reference-drift comparison must not be fooled by NaN.
    This is the only guard on reference_inputs/reference_outputs, and it uses
    the NaN-safe form (np.all(... <= tol) rather than naive max() > tol), since
    NaN > x always returns False and would silently pass.

    Inject NaN directly into reference_inputs (which has no upstream finiteness
    guard) to prove the drift comparison itself fails closed on non-finite
    values. The injected NaN propagates through log_odds() into got, where
    |nan - expected| <= tol is False, causing np.all(...) to fail and the
    loader to close.
    """
    payload = _valid_payload()
    payload["reference_inputs"][0][0] = float("nan")
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
