"""Longitudinal drift is additive, conservative, and chronology-aware."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import numpy as np

from original.constants import FEATURE_DIM
from original.quantum.longitudinal import (
    DRIFT_FEATURE_CODES,
    LongitudinalConfig,
    _change_point_diagnostic,
    _forward_errors,
    _parse_datetime,
    _word_count,
    analyze_longitudinal_drift,
    trend_aware_typicality,
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


# ── trend_aware_typicality ────────────────────────────────────────────────


def test_trend_aware_typicality_disabled_is_exactly_absent():
    state = StudentState("s")
    assert trend_aware_typicality(
        state, np.full(FEATURE_DIM, 0.5), config=LongitudinalConfig()
    ) is None


def test_trend_aware_typicality_insufficient_history_abstains():
    state = StudentState("s")
    for i in range(5):
        state.add_sample(_sample(np.full(FEATURE_DIM, 0.5), i * 30))
    result = trend_aware_typicality(state, np.full(FEATURE_DIM, 0.5), config=_config())
    assert result is not None
    assert not result.eligible
    assert result.selected_model == "insufficient_history"
    assert result.p_far is None and result.p_central is None


def test_trend_aware_typicality_flags_a_genuine_outlier():
    """A submission that looks nothing like the student's baseline -- flat
    OR drifting -- must still read as atypical (low p_far)."""
    state = StudentState("s")
    for i in range(8):
        vector = np.full(FEATURE_DIM, 0.5)
        vector += (i % 2) * 0.002  # tiny, non-directional noise -> constant model
        state.add_sample(_sample(vector, i * 30))

    outlier = np.full(FEATURE_DIM, 0.5)
    from original.quantum.longitudinal import _DRIFT_INDICES

    outlier[_DRIFT_INDICES] = 0.5 + 3.0  # far outside anything seen
    result = trend_aware_typicality(
        state, outlier, submitted_at="2025-09-01", config=_config()
    )
    assert result is not None and result.eligible
    assert result.selected_model == "constant"
    # 1/(N+1) is the conformal quantization floor at N=8 loo samples (see
    # typicality.py's module docstring) -- the most extreme value reachable.
    assert result.p_far == 1 / (result.loo_n + 1)


def test_trend_aware_typicality_does_not_flag_a_genuine_drift_continuation():
    """The central claim: a submission that is simply the NEXT point on a
    real, validated trend must read as typical under the trend-aware
    reference, even though it would read as far-from-baseline under a flat
    mean. This is the exact gap between loo_distances (flat, recency-
    weighted mean) and this function (fitted trajectory)."""
    from original.quantum.longitudinal import _DRIFT_INDICES

    state = StudentState("s")
    for i in range(10):
        vector = np.full(FEATURE_DIM, 0.30)
        vector[_DRIFT_INDICES] = 0.30 + i * 0.025
        state.add_sample(_sample(vector, i * 30))

    # The next point on the SAME line -- a genuine continuation, not a jump.
    probe = np.full(FEATURE_DIM, 0.30)
    probe[_DRIFT_INDICES] = 0.30 + 10 * 0.025
    result = trend_aware_typicality(
        state,
        probe,
        submitted_at=(date(2025, 1, 1) + timedelta(days=300)).isoformat(),
        config=_config(),
    )
    assert result is not None and result.eligible
    assert result.selected_model == "gradual_drift"
    # Typical under the trend-aware reference: neither tail should fire.
    assert result.band == "no_action"
    assert result.p_far > 0.2
    assert result.p_central > 0.2


def test_trend_aware_typicality_never_mutates_state():
    state = StudentState("s")
    for i in range(7):
        state.add_sample(_sample(np.full(FEATURE_DIM, 0.4 + i * 0.01), i * 30))
    before = len(state.samples)
    trend_aware_typicality(
        state, np.full(FEATURE_DIM, 0.9), submitted_at="2025-06-01", config=_config()
    )
    assert len(state.samples) == before


# ── LongitudinalConfig.from_env / dataclass.to_dict ─────────────────────────
# Both are real production call sites, not decoration: students_scoring.py
# calls LongitudinalConfig.from_env(); routers/_shared.py does
# DriftAnalysisOut(**r.drift_analysis.to_dict()) and
# TrendAwareTypicalityOut(**r.trend_aware_typicality.to_dict()).


def test_config_from_env_reads_all_three_variables(monkeypatch):
    monkeypatch.setenv("LONGITUDINAL_DRIFT_ENABLED", "1")
    monkeypatch.setenv("LONGITUDINAL_MIN_SAMPLES", "9")
    monkeypatch.setenv("LONGITUDINAL_CHANGEPOINT_MIN_SAMPLES", "20")
    config = LongitudinalConfig.from_env()
    assert config.enabled is True
    assert config.min_samples_for_trend == 9
    assert config.min_samples_for_change_point == 20


def test_drift_analysis_to_dict_matches_production_unpacking():
    state = StudentState("s")
    for i in range(8):
        vector = np.full(FEATURE_DIM, 0.5)
        vector += (i % 2) * 0.002
        state.add_sample(_sample(vector, i * 30))
    result = analyze_longitudinal_drift(
        state, np.full(FEATURE_DIM, 0.5), submitted_at="2025-09-01", config=_config()
    )
    assert result is not None
    payload = result.to_dict()
    assert isinstance(payload, dict)
    assert payload["eligible"] is True
    assert payload["selected_model"] == result.selected_model
    assert payload["interpretation"] == result.interpretation


def test_trend_aware_typicality_to_dict_matches_production_unpacking():
    state = StudentState("s")
    for i in range(8):
        vector = np.full(FEATURE_DIM, 0.5)
        vector += (i % 2) * 0.002
        state.add_sample(_sample(vector, i * 30))
    result = trend_aware_typicality(
        state, np.full(FEATURE_DIM, 0.5), submitted_at="2025-09-01", config=_config()
    )
    assert result is not None
    payload = result.to_dict()
    assert isinstance(payload, dict)
    assert payload["eligible"] is True
    assert payload["band"] == result.band


# ── _parse_datetime ──────────────────────────────────────────────────────────
# Verified directly (not hand-derived -- these are the actual return values):
#   _parse_datetime("2025-06-15T10:00:00Z")       -> 2025-06-15 10:00:00+00:00
#   _parse_datetime("2025-06-15T10:00:00+05:00")  -> 2025-06-15 05:00:00+00:00
#   _parse_datetime("not-a-real-date")             -> None


def test_parse_datetime_accepts_z_suffix():
    # Exercises the `raw.endswith("Z")` True arm (line 127): "Z" is rewritten
    # to "+00:00" before fromisoformat. No other existing test uses a
    # Z-suffixed string.
    parsed = _parse_datetime("2025-06-15T10:00:00Z")
    assert parsed == datetime(2025, 6, 15, 10, 0, 0, tzinfo=UTC)


def test_parse_datetime_accepts_explicit_utc_offset():
    # +05:00 is 5 hours ahead of UTC, so 10:00 local -> 05:00 UTC.
    # fromisoformat already attaches a tzinfo for this input, so
    # `parsed.tzinfo is None` is False and the naive->UTC assignment on
    # line 133 is skipped (the 132->134 branch this file's fresh coverage
    # run flagged as never taken) -- distinct from the Z-suffix case above,
    # which also ends up tz-aware but via the string-rewrite path instead.
    parsed = _parse_datetime("2025-06-15T10:00:00+05:00")
    assert parsed == datetime(2025, 6, 15, 5, 0, 0, tzinfo=UTC)


def test_parse_datetime_returns_none_for_unparseable_garbage():
    # datetime.fromisoformat raises ValueError on non-ISO text; the parser
    # catches it and abstains rather than propagating.
    assert _parse_datetime("not-a-real-date") is None


# ── _word_count ──────────────────────────────────────────────────────────────


def test_word_count_falls_back_to_text_when_stored_value_is_not_coercible():
    # Verified: int("not-a-number") raises ValueError, caught by the
    # `except (TypeError, ValueError): pass`, falling through to
    # len(text.split()) == 5.
    sample = BaselineSample(
        text="one two three four five",
        vector=np.zeros(3),
        provenance="verified",
        auth_weight=1.0,
        word_count="not-a-number",
    )
    assert _word_count(sample) == 5


def test_word_count_uses_text_length_when_stored_is_none():
    # `stored is not None` False arm (139->144): every other test's _sample()
    # helper sets word_count=400, so this is the only place the "legacy
    # sample, word_count never backfilled" path -- skipping the int()
    # attempt entirely rather than raising on int(None) -- gets exercised.
    sample = BaselineSample(
        text="alpha beta gamma",
        vector=np.zeros(3),
        provenance="verified",
        auth_weight=1.0,
        word_count=None,
    )
    assert _word_count(sample) == 3


# ── _forward_errors ──────────────────────────────────────────────────────────


def test_forward_errors_returns_infinite_with_fewer_than_four_observations():
    # The forward-chaining loop is `range(4, len(t))`; with len(t) == 3 it
    # never runs, constant_errors/trend_errors both stay empty, and the
    # function returns (inf, inf) rather than averaging an empty list.
    t = np.array([0.0, 0.1, 0.2])
    values = np.zeros((3, 4))
    constant_error, trend_error = _forward_errors(t, values, _config())
    assert constant_error == math.inf
    assert trend_error == math.inf


# ── _change_point_diagnostic ─────────────────────────────────────────────────


def test_change_point_diagnostic_reports_no_split_when_bic_never_improves():
    # 12 samples (meets min_samples_for_change_point) with small,
    # non-directional per-sample noise and no genuine regime shift.
    # Verified directly: every candidate split's two-segment BIC is worse
    # (larger) than the single-mean BIC over this data, so
    # best_improvement never exceeds 0 (measured -70.47) and no split index
    # is returned -- the `best_improvement <= 0` arm (line 234).
    n_drift = len(DRIFT_FEATURE_CODES)
    noise = [
        0.0, 0.002, -0.001, 0.0015, -0.0018, 0.0011,
        -0.0009, 0.0021, -0.0013, 0.0017, -0.0006, 0.0008,
    ]
    values = np.stack([np.full(n_drift, 0.4 + noise[i]) for i in range(12)])
    cp_index, cp_evidence = _change_point_diagnostic(
        values, _config(min_samples_for_change_point=12)
    )
    assert cp_index is None
    assert cp_evidence is not None and cp_evidence <= 0


# ── analyze_longitudinal_drift: eligibility ladder ──────────────────────────


def test_time_span_too_short_abstains():
    # 6 dated, authenticated samples clears min_samples_for_trend, but all
    # fall within 5 days -- under min_span_days (60) -- so eligibility fails
    # on the span check specifically, distinct from the sample-count check.
    state = StudentState("s")
    for i in range(6):
        state.add_sample(_sample(np.full(FEATURE_DIM, 0.5), i))
    result = analyze_longitudinal_drift(
        state, np.full(FEATURE_DIM, 0.5), config=_config()
    )
    assert result is not None
    assert not result.eligible
    assert result.reason == "insufficient_time_span"
    assert result.dated_sample_count == 6
    assert result.span_days == 5


def test_target_time_before_history_clamps_to_first_sample():
    # submitted_at parses to a date before the earliest eligible sample.
    # Verified: without the clamp this would make extrapolation_days
    # negative; with it (line 297), target_time == first and
    # extrapolation_days == 0 exactly.
    state = StudentState("s")
    for i in range(8):
        state.add_sample(_sample(np.full(FEATURE_DIM, 0.5), i * 30))
    result = analyze_longitudinal_drift(
        state, np.full(FEATURE_DIM, 0.5), submitted_at="2024-01-01", config=_config()
    )
    assert result is not None and result.eligible
    assert result.extrapolation_days == 0


def test_extrapolation_beyond_cap_is_clamped():
    # submitted_at is ~4.5 years after the last sample -- far beyond
    # max_extrapolation_days (365) -- so target_time and extrapolation_days
    # both clamp to the cap (lines 300-301) rather than extrapolating an
    # arbitrarily distant trend. Verified: extrapolation_days == 365 exactly,
    # not the much larger raw day count "2030-01-01" minus the last sample
    # would otherwise produce.
    state = StudentState("s")
    for i in range(8):
        state.add_sample(_sample(np.full(FEATURE_DIM, 0.5), i * 30))
    result = analyze_longitudinal_drift(
        state,
        np.full(FEATURE_DIM, 0.5),
        submitted_at="2030-01-01",
        config=_config(max_extrapolation_days=365),
    )
    assert result is not None and result.eligible
    assert result.extrapolation_days == 365


def test_analyze_treats_nonfinite_constant_error_as_zero_improvement():
    # Only 3 dated samples (min_samples_for_trend lowered to 3 here so
    # eligibility still passes): _forward_errors' loop never runs (see
    # test_forward_errors_returns_infinite_with_fewer_than_four_observations)
    # and returns (inf, inf). analyze_longitudinal_drift must treat that
    # non-finite constant_error as "no measurable improvement" (line 306:
    # improvement = 0.0) rather than computing (inf - inf) / inf (nan) or
    # raising. Verified: predictive_improvement == 0.0, constant model wins.
    state = StudentState("s")
    for i in range(3):
        state.add_sample(_sample(np.full(FEATURE_DIM, 0.5), i * 45))  # span 90 days
    result = analyze_longitudinal_drift(
        state,
        np.full(FEATURE_DIM, 0.5),
        submitted_at=(date(2025, 1, 1) + timedelta(days=90)).isoformat(),
        config=_config(min_samples_for_trend=3),
    )
    assert result is not None and result.eligible
    assert result.dated_sample_count == 3
    assert result.predictive_improvement == 0.0
    assert result.selected_model == "constant"


# ── analyze_longitudinal_drift: interpretation arms ─────────────────────────


def test_late_large_jump_reads_as_unexplained_discontinuity():
    """A step confined to the last two of twelve samples. Verified
    numerically: historical_deviation=0.951, predicted_current_deviation=
    0.727, change_point_index=8, change_point_evidence=114.16. A linear
    trend partially explains the jump (relief = 0.951-0.727 = 0.224 >= 0.10)
    but predicted_current_deviation stays >= 0.60, so the 'drift_compatible'
    arm's `predicted_deviation < 0.60` leg fails; historical_deviation is
    far above 0.40, so 'stable_consistent' fails too. The change-point
    diagnostic (n=12 meets min_samples_for_change_point) finds a genuine,
    strong split (evidence 114.16 > 10.0), so that arm fires next."""
    from original.quantum.longitudinal import _DRIFT_INDICES

    state = StudentState("s")
    for i in range(12):
        vector = np.full(FEATURE_DIM, 0.4)
        vector[_DRIFT_INDICES] = 0.35 if i < 10 else 1.2
        state.add_sample(_sample(vector, i * 30))
    probe = np.full(FEATURE_DIM, 0.4)
    probe[_DRIFT_INDICES] = 1.2
    result = analyze_longitudinal_drift(
        state,
        probe,
        submitted_at=(date(2025, 1, 1) + timedelta(days=390)).isoformat(),
        config=_config(min_samples_for_change_point=12),
    )
    assert result is not None and result.eligible
    assert result.change_point_index is not None
    assert result.change_point_evidence is not None and result.change_point_evidence > 10.0
    assert result.predicted_current_deviation >= 0.60
    assert result.interpretation == "unexplained_discontinuity"


def test_moderate_deviation_with_no_trend_reads_as_no_supported_drift():
    """A submission meaningfully off the baseline but not dramatically so,
    against a flat, noisy 8-sample history (below the 12-sample
    change-point floor, so change_point_index is always None here).
    Verified numerically: historical_deviation == predicted_current_deviation
    == 0.479 (selected model is 'constant', so the predicted reference IS
    the historical mean). That clears the 0.40 'stable_consistent' floor but
    stays under the 0.60 'unexplained_change' bar, and there is no change
    point to report -- so none of the first four interpretation arms can
    fire and control falls through to the final 'no_supported_drift' else
    (line 340)."""
    from original.quantum.longitudinal import _DRIFT_INDICES

    noise = [0.0, 0.03, -0.02, 0.025, -0.015, 0.01, -0.03, 0.02]
    state = StudentState("s")
    for i in range(8):
        vector = np.full(FEATURE_DIM, 0.4)
        vector[_DRIFT_INDICES] = 0.4 + noise[i]
        state.add_sample(_sample(vector, i * 30))
    probe = np.full(FEATURE_DIM, 0.4)
    probe[_DRIFT_INDICES] = 0.4 + 0.02
    result = analyze_longitudinal_drift(
        state,
        probe,
        submitted_at=(date(2025, 1, 1) + timedelta(days=240)).isoformat(),
        config=_config(),
    )
    assert result is not None and result.eligible
    assert result.selected_model == "constant"
    assert result.change_point_index is None
    assert 0.40 <= result.historical_deviation < 0.60
    assert result.historical_deviation == result.predicted_current_deviation
    assert result.interpretation == "no_supported_drift"


# ── trend_aware_typicality: remaining arms ──────────────────────────────────


def test_trend_aware_typicality_treats_nonfinite_constant_error_as_zero_improvement():
    # Mirrors test_analyze_treats_nonfinite_constant_error_as_zero_improvement
    # but for trend_aware_typicality's own _forward_errors call (line 424):
    # n=3 (the hard eligibility floor) means len(t) < 4, so constant_error is
    # inf and improvement must be forced to 0.0 rather than propagating nan.
    state = StudentState("s")
    for i in range(3):
        state.add_sample(_sample(np.full(FEATURE_DIM, 0.5), i * 45))
    result = trend_aware_typicality(
        state,
        np.full(FEATURE_DIM, 0.5),
        submitted_at=(date(2025, 1, 1) + timedelta(days=90)).isoformat(),
        config=_config(min_samples_for_trend=3),
    )
    assert result is not None and result.eligible
    assert result.loo_n == 3
    assert result.selected_model == "constant"


def test_trend_aware_typicality_target_time_before_history_clamps_to_first_sample():
    # Mirrors analyze_longitudinal_drift's clamp: submitted_at earlier than
    # the first eligible sample must not compute a negative target_t (line
    # 454). The submission vector is identical to the (near-)constant
    # baseline, so once clamped to t=0 it reads as fully typical: verified
    # p_far == 1.0 (theoretical maximum -- see the conformal quantization
    # note in test_trend_aware_typicality_flags_a_genuine_outlier).
    state = StudentState("s")
    for i in range(8):
        vector = np.full(FEATURE_DIM, 0.5)
        vector += (i % 2) * 0.002
        state.add_sample(_sample(vector, i * 30))
    result = trend_aware_typicality(
        state, np.full(FEATURE_DIM, 0.5), submitted_at="2024-01-01", config=_config()
    )
    assert result is not None and result.eligible
    assert result.band == "no_action"
    assert result.p_far == 1.0
