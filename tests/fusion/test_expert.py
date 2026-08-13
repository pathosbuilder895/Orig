"""Orchestration: centering, fusion, and every abstain path."""

from __future__ import annotations

import json
import logging

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.fusion import artifact as artifact_module
from original.fusion import peers
from original.fusion.expert import FusedScoreResult, predict_fused_score
from original.quantum.state import BaselineSample, StudentState

_EXPERT_LOGGER = "original.fusion.expert"


def _expert_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """WARNING+ records emitted by the expert module during the captured call.

    Used to discriminate an expected abstain (no WARNING; the guard returns
    cleanly) from a masked crash (the blanket handler logs a WARNING with
    the same None return value). A guard that has been deleted lets
    execution fall through to an AttributeError that the blanket handler
    converts to None — this is what should make these tests fail.
    """
    return [
        record
        for record in caplog.records
        if record.name == _EXPERT_LOGGER and record.levelno >= logging.WARNING
    ]


_LONG = (
    "However, a reader might ask why these claims have been made; therefore we reply "
    "that the argument is careful and that it is also sound. "
) * 40

_OTHER = (
    "The cat sat. Rain fell. Dogs ran fast! Birds sing loud songs. "
    "Short bursts everywhere. No subordination here at all. "
) * 40


def _state(student_id: str, *, samples: int = 3, words: str = _LONG) -> StudentState:
    state = StudentState(student_id=student_id)
    rng = np.random.default_rng(abs(hash(student_id)) % (2**32))
    for index in range(samples):
        state.add_sample(
            BaselineSample(
                text=words,
                vector=rng.uniform(0.3, 0.7, FEATURE_DIM),
                provenance="proctored",
                auth_weight=1.0,
                assignment=f"{student_id}-{index}",
            )
        )
    return state


@pytest.fixture()
def fixture_artifact(tmp_path, monkeypatch):
    mu, sd, weights = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [1.0, 1.0, 1.0]
    reference_inputs = [[0.1, 0.2, 0.3]]
    payload = {
        "schema_version": 1,
        "channel_order": ["peer_centered_z", "compression", "function_word_network"],
        "mu": mu,
        "sd": sd,
        "weights": weights,
        "intercept": 0.0,
        "threshold_fa5": 0.5,
        "threshold_fa1": 1.5,
        "reference_inputs": reference_inputs,
        "reference_outputs": [float(np.dot(reference_inputs[0], weights))],
        "provenance": {"dataset": "unit-test"},
    }
    path = tmp_path / "fused.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setenv("FUSED_SCORE_MODEL_PATH", str(path))
    artifact_module.reset_for_tests()
    peers.reset_cache_for_tests()
    yield path
    artifact_module.reset_for_tests()
    peers.reset_cache_for_tests()


def _cohort(n: int = 12) -> list[StudentState]:
    return [_state(f"t1:peer{i}") for i in range(n)]


def test_returns_a_populated_result_when_everything_is_available(fixture_artifact):
    claimed = _state("t1:alice")
    result = predict_fused_score(_LONG[:4000], claimed, [claimed] + _cohort())
    assert isinstance(result, FusedScoreResult)
    assert result.reference_profiles == 8
    assert result.baseline_samples == 3
    assert set(result.channels) == {"peer_centered_z", "compression", "function_word_network"}
    assert set(result.all_channels) == {
        "peer_centered_z",
        "compression",
        "function_word_network",
    }
    assert 0.0 <= result.probability_different_author <= 1.0
    assert result.band in {"consistent", "inconclusive", "divergent"}
    assert result.model_version == "v1"
    assert result.trained_on == "unit-test"


def test_probability_is_the_sigmoid_of_the_log_odds(fixture_artifact):
    claimed = _state("t1:alice")
    result = predict_fused_score(_LONG[:4000], claimed, [claimed] + _cohort())
    expected = 1.0 / (1.0 + np.exp(-result.fused_log_odds))
    assert result.probability_different_author == pytest.approx(expected, abs=1e-6)


def test_channel_values_are_peer_centered(fixture_artifact):
    """A probe in the claimed author's own style scores below the peer mean."""
    claimed = _state("t1:alice")
    cohort = [_state(f"t1:peer{i}", words=_OTHER) for i in range(12)]
    result = predict_fused_score(_LONG[:4000], claimed, [claimed] + cohort)
    assert result is not None
    assert result.channels["compression"] < 0.0


def test_result_is_deterministic(fixture_artifact):
    claimed = _state("t1:alice")
    cohort = [claimed] + _cohort()
    first = predict_fused_score(_LONG[:4000], claimed, cohort)
    second = predict_fused_score(_LONG[:4000], claimed, cohort)
    assert first == second


def test_supplied_probe_vector_avoids_re_extraction(fixture_artifact, monkeypatch):
    """The scoring path hands over the vector it already has; we must use it."""
    import original.features.pipeline as pipeline

    calls = {"n": 0}
    real = pipeline.feature_vector

    def counting(text):
        calls["n"] += 1
        return real(text)

    monkeypatch.setattr(pipeline, "feature_vector", counting)
    claimed = _state("t1:alice")
    supplied = np.asarray(real(_LONG[:4000]), dtype=np.float64)
    calls["n"] = 0
    result = predict_fused_score(
        _LONG[:4000], claimed, [claimed] + _cohort(), probe_vector=supplied
    )
    assert result is not None
    assert calls["n"] == 0, "probe_vector was ignored and features were re-extracted"


def test_supplied_and_extracted_vectors_agree(fixture_artifact):
    from original.features.pipeline import feature_vector

    claimed = _state("t1:alice")
    cohort = [claimed] + _cohort()
    supplied = np.asarray(feature_vector(_LONG[:4000]), dtype=np.float64)
    with_vector = predict_fused_score(_LONG[:4000], claimed, cohort, probe_vector=supplied)
    without = predict_fused_score(_LONG[:4000], claimed, cohort)
    assert with_vector == without


def test_abstains_on_short_probe(fixture_artifact, caplog):
    claimed = _state("t1:alice")
    with caplog.at_level(logging.DEBUG, logger=_EXPERT_LOGGER):
        result = predict_fused_score("too short", claimed, [claimed] + _cohort())
    assert result is None
    assert not _expert_warnings(caplog), "expected abstain, not a masked crash"


def test_abstains_below_three_text_carrying_baselines(fixture_artifact, caplog):
    claimed = _state("t1:alice", samples=2)
    with caplog.at_level(logging.DEBUG, logger=_EXPERT_LOGGER):
        result = predict_fused_score(_LONG[:4000], claimed, [claimed] + _cohort())
    assert result is None
    assert not _expert_warnings(caplog), "expected abstain, not a masked crash"


def test_abstains_below_eight_peers(fixture_artifact, caplog):
    claimed = _state("t1:alice")
    with caplog.at_level(logging.DEBUG, logger=_EXPERT_LOGGER):
        result = predict_fused_score(_LONG[:4000], claimed, [claimed] + _cohort(5))
    assert result is None
    assert not _expert_warnings(caplog), "expected abstain, not a masked crash"


def test_abstains_when_the_artifact_is_unavailable(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("FUSED_SCORE_MODEL_PATH", str(tmp_path / "absent.json"))
    artifact_module.reset_for_tests()
    peers.reset_cache_for_tests()
    claimed = _state("t1:alice")
    with caplog.at_level(logging.DEBUG, logger=_EXPERT_LOGGER):
        result = predict_fused_score(_LONG[:4000], claimed, [claimed] + _cohort())
    assert result is None
    assert not _expert_warnings(caplog), "expected abstain, not a masked crash"


def test_abstains_on_probe_vector_shape_mismatch(fixture_artifact, caplog):
    """Guard 5: ``_probe_vector`` returns None when the caller-supplied vector's
    shape doesn't match the claimed student's baseline shape."""
    claimed = _state("t1:alice")
    wrong_shape = np.ones(FEATURE_DIM - 1, dtype=np.float64)
    with caplog.at_level(logging.DEBUG, logger=_EXPERT_LOGGER):
        result = predict_fused_score(
            _LONG[:4000], claimed, [claimed] + _cohort(), probe_vector=wrong_shape
        )
    assert result is None
    assert not _expert_warnings(caplog), "expected abstain, not a masked crash"


def test_never_raises_when_a_channel_explodes(fixture_artifact, monkeypatch, caplog):
    monkeypatch.setattr(
        "original.fusion.expert.compression_distance",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    claimed = _state("t1:alice")
    with caplog.at_level(logging.DEBUG, logger=_EXPERT_LOGGER):
        result = predict_fused_score(_LONG[:4000], claimed, [claimed] + _cohort())
    assert result is None
    # This *is* a genuine failure: the blanket handler must surface it at
    # WARNING with a traceback, unlike the expected-abstain paths above.
    warnings = _expert_warnings(caplog)
    assert len(warnings) == 1
    assert warnings[0].exc_info is not None
    assert "boom" in warnings[0].getMessage()


def test_honours_a_two_channel_artifact(tmp_path, monkeypatch):
    mu, sd, weights = [0.0, 0.0], [1.0, 1.0], [1.0, 1.0]
    payload = {
        "schema_version": 1,
        "channel_order": ["peer_centered_z", "compression"],
        "mu": mu,
        "sd": sd,
        "weights": weights,
        "intercept": 0.0,
        "threshold_fa5": 0.5,
        "threshold_fa1": 1.5,
        "reference_inputs": [[0.1, 0.2]],
        "reference_outputs": [float(np.dot([0.1, 0.2], weights))],
        "provenance": {"dataset": "unit-test-2ch"},
    }
    path = tmp_path / "fused2.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setenv("FUSED_SCORE_MODEL_PATH", str(path))
    artifact_module.reset_for_tests()
    peers.reset_cache_for_tests()
    claimed = _state("t1:alice")
    result = predict_fused_score(_LONG[:4000], claimed, [claimed] + _cohort())
    assert result is not None
    assert set(result.channels) == {"peer_centered_z", "compression"}
    # I1, 2026-08 fix pass: function_word_network is computed on every call
    # regardless of channel_order (see channels.py's note on why it's kept),
    # and discarding that computed value before persistence wastes the exact
    # cost the ablation-revisit the spec calls for depends on. `all_channels`
    # must carry every computed channel even though only two feed the model.
    assert set(result.all_channels) == {
        "peer_centered_z",
        "compression",
        "function_word_network",
    }
    # The fused log-odds must not change because of this — only what gets
    # persisted grows.
    assert set(result.channels) == {"peer_centered_z", "compression"}


def test_channels_are_paired_with_their_own_weight_by_name(tmp_path, monkeypatch):
    """Regression guard for dict-keyed (not positional) channel/weight alignment.

    Every other artifact fixture in this file uses uniform weights, or a
    ``channel_order`` that happens to already match
    ``channels.CHANNEL_NAMES``. Either property hides a regression from
    name-based lookup to positional zipping: uniform weights make the dot
    product order-insensitive, and a matching order makes "by name" and "by
    position" produce the same values. This artifact uses asymmetric
    weights *and* a ``channel_order`` that reverses the first two canonical
    channels (``compression`` before ``peer_centered_z``), so pairing by
    position instead of by name changes the number.
    """
    channel_order = ["compression", "peer_centered_z"]
    mu, sd, weights, intercept = [0.0, 0.0], [1.0, 1.0], [7.0, 2.0], 0.3
    reference_inputs = [[0.1, 0.2]]
    payload = {
        "schema_version": 1,
        "channel_order": channel_order,
        "mu": mu,
        "sd": sd,
        "weights": weights,
        "intercept": intercept,
        "threshold_fa5": 0.5,
        "threshold_fa1": 1.5,
        "reference_inputs": reference_inputs,
        "reference_outputs": [float(np.dot(reference_inputs[0], weights) + intercept)],
        "provenance": {"dataset": "unit-test-alignment"},
    }
    path = tmp_path / "fused_alignment.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setenv("FUSED_SCORE_MODEL_PATH", str(path))
    artifact_module.reset_for_tests()
    peers.reset_cache_for_tests()
    claimed = _state("t1:alice")
    result = predict_fused_score(_LONG[:4000], claimed, [claimed] + _cohort())
    assert result is not None
    assert set(result.channels) == {"compression", "peer_centered_z"}

    # Ground truth computed independently: pair each channel's *own*
    # centered value with its *own* weight, by name (mu=0, sd=1 here, so
    # standardization is a no-op and this is just weights . centered +
    # intercept).
    expected = (
        weights[0] * result.channels["compression"]
        + weights[1] * result.channels["peer_centered_z"]
        + intercept
    )
    assert result.fused_log_odds == pytest.approx(expected, abs=1e-4)

    # Sanity: pairing the SAME centered values positionally against the
    # OTHER channel's weight must give a materially different number, or
    # this test couldn't actually detect the regression it targets.
    wrong_by_position = (
        weights[0] * result.channels["peer_centered_z"]
        + weights[1] * result.channels["compression"]
        + intercept
    )
    assert result.fused_log_odds != pytest.approx(wrong_by_position, abs=1e-4)
