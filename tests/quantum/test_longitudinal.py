"""Longitudinal drift is additive, conservative, and chronology-aware."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from original.constants import FEATURE_DIM
from original.quantum.longitudinal import (
    DRIFT_FEATURE_CODES,
    LongitudinalConfig,
    analyze_longitudinal_drift,
)
from original.quantum.state import BaselineSample, StudentState


def _sample(vector: np.ndarray, day: int, *, auth_weight: float = 1.0) -> BaselineSample:
    return BaselineSample(
        text="word " * 400,
        vector=vector.copy(),
        provenance="verified",
        auth_weight=auth_weight,
        submitted_at=(date(2025, 1, 1) + timedelta(days=day)).isoformat(),
        word_count=400,
    )


def _config(**kwargs) -> LongitudinalConfig:
    values = dict(
        enabled=True,
        min_samples_for_trend=6,
        min_samples_for_change_point=12,
        min_span_days=60,
        min_words=300,
        ridge_strength=0.25,
        min_predictive_improvement=0.02,
    )
    values.update(kwargs)
    return LongitudinalConfig(**values)


def test_disabled_is_exactly_absent():
    state = StudentState("s")
    assert analyze_longitudinal_drift(
        state, np.full(FEATURE_DIM, 0.5), config=LongitudinalConfig()
    ) is None


def test_insufficient_history_abstains():
    state = StudentState("s")
    for i in range(5):
        state.add_sample(_sample(np.full(FEATURE_DIM, 0.5), i * 30))
    result = analyze_longitudinal_drift(
        state, np.full(FEATURE_DIM, 0.5), config=_config()
    )
    assert result is not None
    assert not result.eligible
    assert result.interpretation == "insufficient_history"


def test_constant_history_selects_constant_model():
    state = StudentState("s")
    for i in range(8):
        vector = np.full(FEATURE_DIM, 0.5)
        vector += (i % 2) * 0.002
        state.add_sample(_sample(vector, i * 30))
    result = analyze_longitudinal_drift(
        state,
        np.full(FEATURE_DIM, 0.5),
        submitted_at="2025-09-01",
        config=_config(),
    )
    assert result is not None and result.eligible
    assert result.selected_model == "constant"
    assert result.interpretation == "stable_consistent"


def test_supported_gradual_drift_reduces_current_deviation():
    state = StudentState("s")
    n_drift_features = len(DRIFT_FEATURE_CODES)
    for i in range(10):
        vector = np.full(FEATURE_DIM, 0.30)
        # All selected drift dimensions move smoothly while the remainder stays
        # fixed.  DRIFT_FEATURE_CODES retain canonical ordering, so locating by
        # membership is intentionally avoided in the production implementation.
        from original.quantum.longitudinal import _DRIFT_INDICES

        vector[_DRIFT_INDICES] = 0.30 + i * 0.025
        state.add_sample(_sample(vector, i * 30))

    probe = np.full(FEATURE_DIM, 0.30)
    probe[_DRIFT_INDICES] = 0.30 + 10 * 0.025
    result = analyze_longitudinal_drift(
        state,
        probe,
        submitted_at=(date(2025, 1, 1) + timedelta(days=300)).isoformat(),
        config=_config(),
    )
    assert n_drift_features > 0
    assert result is not None and result.eligible
    assert result.selected_model == "gradual_drift"
    assert result.predicted_current_deviation < result.historical_deviation
    assert result.drift_relief > 0


def test_probe_never_mutates_or_enters_student_history():
    state = StudentState("s")
    for i in range(7):
        state.add_sample(_sample(np.full(FEATURE_DIM, 0.4 + i * 0.01), i * 30))
    before_ids = [id(sample) for sample in state.samples]
    before_vectors = [sample.vector.copy() for sample in state.samples]
    analyze_longitudinal_drift(
        state, np.full(FEATURE_DIM, 0.9), submitted_at="2025-12-01", config=_config()
    )
    assert [id(sample) for sample in state.samples] == before_ids
    assert len(state.samples) == 7
    for sample, before in zip(state.samples, before_vectors):
        np.testing.assert_array_equal(sample.vector, before)


def test_unverified_and_undated_samples_do_not_create_eligibility():
    state = StudentState("s")
    for i in range(6):
        sample = _sample(np.full(FEATURE_DIM, 0.5), i * 30, auth_weight=0.0)
        state.add_sample(sample)
    for _ in range(6):
        sample = _sample(np.full(FEATURE_DIM, 0.5), 0)
        sample.submitted_at = ""
        state.add_sample(sample)
    result = analyze_longitudinal_drift(
        state, np.full(FEATURE_DIM, 0.5), config=_config()
    )
    assert result is not None
    assert not result.eligible
    assert result.dated_sample_count == 0


def test_resolved_genre_requires_like_for_like_history():
    state = StudentState("genre")
    for i in range(6):
        sample = _sample(np.full(FEATURE_DIM, 0.5), i * 30)
        sample.genre = "sermon"
        state.add_sample(sample)
    result = analyze_longitudinal_drift(
        state,
        np.full(FEATURE_DIM, 0.5),
        submission_genre="scholarly_essay",
        config=_config(),
    )
    assert result is not None and not result.eligible
    assert result.dated_sample_count == 0


def test_shifting_every_date_preserves_model_and_scores():
    def build(offset: int) -> StudentState:
        state = StudentState(f"s-{offset}")
        for i in range(8):
            state.add_sample(_sample(np.full(FEATURE_DIM, 0.3 + i * 0.01), offset + i * 30))
        return state

    a = analyze_longitudinal_drift(
        build(0), np.full(FEATURE_DIM, 0.38), submitted_at="2025-09-01", config=_config()
    )
    b = analyze_longitudinal_drift(
        build(365), np.full(FEATURE_DIM, 0.38), submitted_at="2026-09-01", config=_config()
    )
    assert a is not None and b is not None
    assert a.selected_model == b.selected_model
    assert a.historical_deviation == b.historical_deviation
    assert abs(a.predicted_current_deviation - b.predicted_current_deviation) < 1e-12


def test_long_history_can_report_an_unexplained_change_point():
    from original.quantum.longitudinal import _DRIFT_INDICES

    state = StudentState("change")
    for i in range(14):
        vector = np.full(FEATURE_DIM, 0.4)
        vector[_DRIFT_INDICES] = 0.35 if i < 7 else 0.75
        state.add_sample(_sample(vector, i * 30))
    probe = np.full(FEATURE_DIM, 0.4)
    probe[_DRIFT_INDICES] = 0.75
    result = analyze_longitudinal_drift(
        state,
        probe,
        submitted_at="2026-03-01",
        config=_config(min_samples_for_change_point=12),
    )
    assert result is not None and result.eligible
    assert result.change_point_index == 7
    assert result.change_point_evidence is not None and result.change_point_evidence > 0
