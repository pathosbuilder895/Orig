"""Tests for topic-adaptive variance inflation (TOPIC_VARIANCE_INFLATION)."""

import numpy as np
import pytest

from original.constants import ALL_FEATURE_CODES, FEATURE_DIM, TOPIC_INFLATE_GAIN
from original.quantum.scoring import _topic_inflation_vector


def _manifest(distance):
    return {"topic": {"baseline_distance": distance, "novelty": "high"}}


def test_returns_none_below_novelty_floor():
    # 0.25 is TOPIC_NOVELTY_BOUNDS["low"]; at or below it the multiplier
    # would be exactly 1.0, so the builder signals "skip the multiply".
    assert _topic_inflation_vector(_manifest(0.0)) is None
    assert _topic_inflation_vector(_manifest(0.10)) is None
    assert _topic_inflation_vector(_manifest(0.25)) is None


def test_returns_none_for_unusable_manifest():
    assert _topic_inflation_vector(None) is None
    assert _topic_inflation_vector({}) is None
    assert _topic_inflation_vector({"topic": {}}) is None
    assert _topic_inflation_vector(_manifest(None)) is None
    assert _topic_inflation_vector(_manifest("high")) is None
    assert _topic_inflation_vector(_manifest(float("nan"))) is None


def test_shape_and_dtype_above_floor():
    vec = _topic_inflation_vector(_manifest(0.9))
    assert vec is not None
    assert vec.shape == (FEATURE_DIM,)
    assert vec.dtype == np.float64
    assert len(ALL_FEATURE_CODES) == FEATURE_DIM


def test_multiplier_is_at_least_one_and_monotone():
    lo = _topic_inflation_vector(_manifest(0.5))
    hi = _topic_inflation_vector(_manifest(1.0))
    assert np.all(lo >= 1.0)
    assert np.all(hi >= lo)


def test_uniform_sensitivity_gives_exact_expected_value():
    # With the shipped (empty) TOPIC_SENSITIVITY table every feature reads
    # 1.0, so the multiplier is 1 + GAIN * d_eff everywhere.
    # d = 1.0 -> d_eff = (1.0 - 0.25) / 0.75 = 1.0
    vec = _topic_inflation_vector(_manifest(1.0))
    assert np.allclose(vec, 1.0 + TOPIC_INFLATE_GAIN)


def test_distance_is_clamped_to_unit_interval():
    # A distance above 1.0 must not produce a larger multiplier than d = 1.0.
    assert np.allclose(
        _topic_inflation_vector(_manifest(5.0)),
        _topic_inflation_vector(_manifest(1.0)),
    )
    # A negative distance reads as "no novelty", not as a shrink.
    assert _topic_inflation_vector(_manifest(-3.0)) is None
