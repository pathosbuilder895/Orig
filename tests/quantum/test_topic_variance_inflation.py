"""Tests for topic-adaptive variance inflation (TOPIC_VARIANCE_INFLATION)."""

import numpy as np
import pytest

from original.constants import ALL_FEATURE_CODES, FEATURE_DIM, TOPIC_INFLATE_GAIN
from original.quantum.scoring import (
    ScoringConfig,
    _rms_z_from_z,
    _topic_inflation_vector,
    score,
)
from original.quantum.state import BaselineSample, StudentState


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


def test_rms_z_from_z_matches_inline_formula():
    rng = np.random.default_rng(20260806)
    z = rng.normal(0.0, 2.0, size=FEATURE_DIM)
    weight_vec = rng.uniform(0.5, 1.5, size=FEATURE_DIM)
    active = np.ones(FEATURE_DIM, dtype=bool)
    active[:5] = False
    n_active = int(active.sum())

    z_capped = np.clip(z, -4.0, 4.0)
    z_weighted = z_capped * weight_vec * active.astype(np.float64)
    expected = float(np.sqrt(np.sum(z_weighted**2) / n_active))

    assert _rms_z_from_z(z, weight_vec, active, n_active) == expected


def test_rms_z_from_z_winsorises_at_four_sigma():
    # A feature at z=100 must contribute exactly as much as one at z=4.
    weight_vec = np.ones(FEATURE_DIM)
    active = np.ones(FEATURE_DIM, dtype=bool)

    huge = np.zeros(FEATURE_DIM)
    huge[0] = 100.0
    capped = np.zeros(FEATURE_DIM)
    capped[0] = 4.0

    assert _rms_z_from_z(huge, weight_vec, active, FEATURE_DIM) == _rms_z_from_z(
        capped, weight_vec, active, FEATURE_DIM
    )


def test_rms_z_from_z_returns_zero_when_no_active_features():
    z = np.ones(FEATURE_DIM)
    weight_vec = np.ones(FEATURE_DIM)
    active = np.zeros(FEATURE_DIM, dtype=bool)
    assert _rms_z_from_z(z, weight_vec, active, 0) == 0.0


def test_default_config_is_off():
    assert ScoringConfig().topic_variance_inflation == "off"


@pytest.mark.parametrize(
    "env_value,expected",
    [
        ("0", "off"),
        ("1", "on"),
        ("on", "on"),
        ("shadow", "shadow"),
        ("", "off"),
        ("nonsense", "off"),
        ("SHADOW", "shadow"),
    ],
)
def test_from_env_parses_mode(monkeypatch, env_value, expected):
    monkeypatch.setenv("TOPIC_VARIANCE_INFLATION", env_value)
    assert ScoringConfig.from_env().topic_variance_inflation == expected


def test_from_env_defaults_off_when_unset(monkeypatch):
    monkeypatch.delenv("TOPIC_VARIANCE_INFLATION", raising=False)
    assert ScoringConfig.from_env().topic_variance_inflation == "off"


def _state_with_baseline(seed=11):
    """A StudentState with enough authenticated samples to score against."""
    rng = np.random.default_rng(seed)
    state = StudentState(student_id="topic-test")
    for i in range(5):
        state.add_sample(
            BaselineSample(
                text=f"baseline {i}",
                vector=np.clip(rng.normal(0.5, 0.05, size=FEATURE_DIM), 0.0, 1.0),
                provenance="proctored",
                auth_weight=1.0,
                assignment=f"a{i}",
            )
        )
    return state


def _score_with(state, vector, manifest, mode):
    return score(
        state,
        vector,
        {code: float(v) for code, v in zip(ALL_FEATURE_CODES, vector)},
        submission_id="s1",
        manifest=manifest,
        scoring_config=ScoringConfig(topic_variance_inflation=mode),
    )


def test_flag_off_is_unchanged_by_topic_distance():
    state = _state_with_baseline()
    rng = np.random.default_rng(99)
    vec = np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)

    off = _score_with(state, vec, _manifest(0.95), "off")
    assert off.topic_inflation_applied is False
    assert off.topic_mean_inflation is None


def test_below_floor_is_byte_identical_with_flag_on():
    state = _state_with_baseline()
    rng = np.random.default_rng(99)
    vec = np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)

    off = _score_with(state, vec, _manifest(0.10), "off")
    on = _score_with(state, vec, _manifest(0.10), "on")

    assert on.authorship.deviation_score == off.authorship.deviation_score
    assert on.recommendation.action == off.recommendation.action
    assert on.topic_inflation_applied is False


def test_high_topic_distance_lowers_the_deviation_score():
    state = _state_with_baseline()
    rng = np.random.default_rng(99)
    vec = np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)

    off = _score_with(state, vec, _manifest(0.95), "off")
    on = _score_with(state, vec, _manifest(0.95), "on")

    assert on.authorship.deviation_score < off.authorship.deviation_score
    assert on.topic_inflation_applied is True
    assert on.topic_distance == pytest.approx(0.95)
    assert on.topic_mean_inflation > 1.0


def test_typicality_refuses_to_run_under_inflation():
    state = _state_with_baseline()
    rng = np.random.default_rng(99)
    vec = np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)

    result = score(
        state,
        vec,
        {code: float(v) for code, v in zip(ALL_FEATURE_CODES, vec)},
        submission_id="s1",
        manifest=_manifest(0.95),
        scoring_config=ScoringConfig(
            topic_variance_inflation="on", typicality_scoring_enabled=True
        ),
    )
    # loo_distances are computed under an UN-inflated sigma; comparing an
    # inflated rms_z against them is apples-to-oranges, so the band must be
    # withheld rather than reported wrong.
    assert result.typicality_band is None


def test_impostor_pool_sigma_is_not_inflated():
    """
    The spec's highest-risk decision: only the CLAIMED-AUTHOR sigma is
    inflated. The impostor pool's sigma is already fit across many authors
    spanning many topics -- which is why llr_deviation_score survives a genre
    shift (AUC 0.863) while the raw score inverts (0.387) -- so inflating it
    too would re-open the asymmetry this correction exists to close.

    Guard, not a measurement: it pins the intent so a later refactor that
    threads `sigma` into _llr_deviation fails loudly here.
    """
    state = _state_with_baseline()
    rng = np.random.default_rng(99)
    vec = np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)
    impostor_stats = (np.full(FEATURE_DIM, 0.50), np.full(FEATURE_DIM, 0.08))
    feature_dict = {code: float(v) for code, v in zip(ALL_FEATURE_CODES, vec)}

    def _run(mode):
        return score(
            state,
            vec,
            feature_dict,
            submission_id="s1",
            manifest=_manifest(0.95),
            impostor_stats=impostor_stats,
            scoring_config=ScoringConfig(
                topic_variance_inflation=mode, null_model="impostor"
            ),
        )

    off = _run("off")
    on = _run("on")

    # rms_z_null is unchanged, so inflating the claimed-author side alone
    # must move llr DOWN (further toward "genuinely this author").
    # NOTE: llr_deviation_score lives on Layer7Output.authorship (see
    # AuthorshipSignal), not on Layer7Output directly -- the brief's draft
    # accessed it as `on.llr_deviation_score`, which raises AttributeError;
    # corrected here to match the actual dataclass shape.
    assert on.authorship.llr_deviation_score is not None
    assert on.authorship.llr_deviation_score < off.authorship.llr_deviation_score


def test_shadow_attaches_score_without_changing_the_verdict():
    state = _state_with_baseline()
    rng = np.random.default_rng(99)
    vec = np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)

    off = _score_with(state, vec, _manifest(0.95), "off")
    shadow = _score_with(state, vec, _manifest(0.95), "shadow")

    # The live verdict is untouched...
    assert shadow.authorship.deviation_score == off.authorship.deviation_score
    assert shadow.recommendation.action == off.recommendation.action
    assert shadow.topic_inflation_applied is False
    # ...but the corrected score is observable.
    assert shadow.deviation_score_inflated is not None
    assert shadow.deviation_score_inflated < off.authorship.deviation_score
    # And the diagnostics are recorded so the pilot d-distribution is
    # measurable from the audit log alone.
    assert shadow.topic_distance == pytest.approx(0.95)
    assert shadow.topic_mean_inflation > 1.0


def test_shadow_score_equals_the_on_mode_score():
    state = _state_with_baseline()
    rng = np.random.default_rng(99)
    vec = np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)

    shadow = _score_with(state, vec, _manifest(0.95), "shadow")
    on = _score_with(state, vec, _manifest(0.95), "on")

    # Shadow must predict exactly what enabling the flag would do, or it is
    # not a preview of anything.
    assert shadow.deviation_score_inflated == pytest.approx(
        on.authorship.deviation_score
    )


def test_no_shadow_score_below_the_floor():
    state = _state_with_baseline()
    rng = np.random.default_rng(99)
    vec = np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)
    shadow = _score_with(state, vec, _manifest(0.10), "shadow")
    assert shadow.deviation_score_inflated is None


def test_shadow_leaves_typicality_untouched():
    """
    Shadow must be inert. sigma is never multiplied in shadow, so rms_z is
    un-inflated and the comparison against loo_distances stays valid -- and
    typicality_band feeds _recommend() when IDENTITY_AXIS is on, so
    withholding it here would let shadow change an action.
    """
    state = _state_with_baseline()
    rng = np.random.default_rng(99)
    vec = np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)
    feature_dict = {code: float(v) for code, v in zip(ALL_FEATURE_CODES, vec)}

    def _run(mode):
        return score(
            state,
            vec,
            feature_dict,
            submission_id="s1",
            manifest=_manifest(0.95),
            scoring_config=ScoringConfig(
                topic_variance_inflation=mode, typicality_scoring_enabled=True
            ),
        )

    assert _run("shadow").typicality_band == _run("off").typicality_band
