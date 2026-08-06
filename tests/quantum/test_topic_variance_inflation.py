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


def test_returns_none_when_topic_resolution_is_degraded():
    # Finding 1b: resolve_topic returns baseline_distance=0.5 (the maximum
    # reachable distance) on every failure path -- missing sklearn, empty
    # baseline, centroid underflow, internal exception -- without raising,
    # so those failures never reach run_resolvers' _errors list. Without
    # this check a resolver failure would silently apply the single
    # strongest possible sigma widening to the submission it should be
    # LEAST confident about.
    degraded_manifest = {
        "topic": {"baseline_distance": 0.5, "novelty": "medium", "degraded": True}
    }
    assert _topic_inflation_vector(degraded_manifest) is None

    # A high, non-degraded distance still inflates -- the guard is specific
    # to the degraded marker, not to baseline_distance == 0.5 in general.
    healthy_manifest = {
        "topic": {"baseline_distance": 0.5, "novelty": "high", "degraded": False}
    }
    assert _topic_inflation_vector(healthy_manifest) is not None

    # A resolver_outputs dict that predates this fix (no "degraded" key at
    # all) must not be treated as degraded -- .get("degraded") reads falsy
    # and the existing distance-based logic applies unchanged.
    legacy_manifest = _manifest(0.5)
    assert _topic_inflation_vector(legacy_manifest) is not None


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


def test_destructive_features_unchanged_between_off_and_on():
    """
    Finding 2: inflation shrinks z, which can push a feature's |z| below
    _decompose's +-1.0 destructive threshold. destructive_features is an
    *explanation* surface (which features moved), while inflation is a
    claim about *certainty* -- widening the band should change how alarmed
    rms_z/deviation_score make us, not what we tell the professor moved.
    _decompose must therefore always be fed the un-inflated z, so
    destructive_features (and the ghostwriting-escalate forcing that reads
    it in _recommend) stay identical regardless of topic_variance_inflation.
    """
    state = _state_with_baseline()
    rng = np.random.default_rng(99)
    # Same fixture as test_high_topic_distance_lowers_the_deviation_score:
    # baseline ~N(0.5, 0.05), submission ~N(0.62, 0.05) -> per-feature z is
    # large enough (~2.4) to land solidly past the +-1.0 destructive
    # threshold under "off", and the d=0.95 topic distance produces enough
    # inflation to pull many of those features back under the threshold if
    # _decompose were (incorrectly) fed the inflated z.
    vec = np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)

    off = _score_with(state, vec, _manifest(0.95), "off")
    on = _score_with(state, vec, _manifest(0.95), "on")

    assert on.topic_inflation_applied is True  # confirm inflation actually fired
    off_destructive = [f.code for f in off.interference.destructive_features]
    on_destructive = [f.code for f in on.interference.destructive_features]
    assert len(off_destructive) > 0, "fixture must produce destructive features to test anything"
    assert on_destructive == off_destructive

    # Same guarantee for constructive_features -- _decompose's classification
    # of EVERY feature (not just the top-5 destructive list) must be
    # unaffected, since a shrunk z could just as easily push a feature INTO
    # the constructive band (|z| < 0.5) as out of the destructive one.
    off_constructive = [f.code for f in off.interference.constructive_features]
    on_constructive = [f.code for f in on.interference.constructive_features]
    assert on_constructive == off_constructive


def test_fidelity_conformal_pvalue_suppressed_when_sigma_inflated():
    """
    Finding 3: quantum_fidelity is computed under sigma_eff (baseline_std_
    override=sigma is the INFLATED sigma at the amplitude-scoring call
    site), but conformal_pvalue(F, authentic_fidelities) compares that F
    against a per-student calibration set accumulated under UN-inflated
    sigma -- the same apples-to-oranges hazard the typicality guard exists
    for. fidelity_conformal_pvalue must be None whenever sigma was actually
    inflated, and must NOT be suppressed in "off" or "shadow" (shadow never
    multiplies sigma, so its fidelity path is untouched by this guard).
    """
    state = _state_with_baseline()
    rng = np.random.default_rng(99)
    vec = np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)
    feature_dict = {code: float(v) for code, v in zip(ALL_FEATURE_CODES, vec)}
    # A calibration set that overlaps the un-inflated fidelity's range, so
    # conformal_pvalue actually returns something other than a degenerate
    # 0.5-empty-set default under "off" -- otherwise this test could pass
    # for the wrong reason (an empty/no-op calibration set rather than a
    # genuine suppression).
    authentic_fidelities = [0.45, 0.5, 0.55, 0.6, 0.65]

    def _run(mode):
        return score(
            state,
            vec,
            feature_dict,
            submission_id="s1",
            manifest=_manifest(0.95),
            scoring_config=ScoringConfig(
                topic_variance_inflation=mode,
                amplitude_scoring_enabled=True,
                authentic_fidelities=authentic_fidelities,
            ),
        )

    off = _run("off")
    on = _run("on")
    shadow = _run("shadow")

    assert off.authorship.quantum_fidelity > 0.0
    assert off.authorship.fidelity_conformal_pvalue is not None

    assert on.topic_inflation_applied is True
    assert on.authorship.fidelity_conformal_pvalue is None

    # Shadow never multiplies sigma, so its fidelity path is untouched by
    # this guard -- it must match "off" exactly (shadow stays inert).
    assert shadow.topic_inflation_applied is False
    assert shadow.authorship.fidelity_conformal_pvalue == off.authorship.fidelity_conformal_pvalue


def test_degraded_topic_resolution_yields_no_inflation_end_to_end():
    """
    A degraded resolve_topic() result must not inflate sigma even though its
    baseline_distance (0.5) is the maximum reachable value and would
    otherwise trigger the strongest possible correction.
    """
    state = _state_with_baseline()
    rng = np.random.default_rng(99)
    vec = np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)
    degraded_manifest = {
        "topic": {"baseline_distance": 0.5, "novelty": "medium", "degraded": True}
    }
    healthy_manifest = {
        "topic": {"baseline_distance": 0.5, "novelty": "high", "degraded": False}
    }

    off = _score_with(state, vec, degraded_manifest, "off")
    degraded_on = _score_with(state, vec, degraded_manifest, "on")
    healthy_on = _score_with(state, vec, healthy_manifest, "on")

    assert degraded_on.topic_inflation_applied is False
    assert degraded_on.topic_mean_inflation is None
    assert degraded_on.authorship.deviation_score == off.authorship.deviation_score
    assert degraded_on.recommendation.action == off.recommendation.action

    # Sanity: the SAME baseline_distance, without the degraded marker, does
    # inflate -- proves the guard is keyed on "degraded", not silently
    # neutered by baseline_distance == 0.5 for some other reason.
    assert healthy_on.topic_inflation_applied is True
    assert healthy_on.authorship.deviation_score < off.authorship.deviation_score


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
    # NOTE: this fixture's baseline is i.i.d. around a constant mean, so
    # state.trajectory.direction lands "lateral" (alignment ~0.002) and
    # adjustment_factor is 1.0 -- multiplying by it is a no-op here. That
    # made this test pass even when the shadow preview forgot to apply
    # adj_factor at all; see test_shadow_score_equals_the_on_mode_score_for_a_growth_trajectory
    # below for the general (non-lateral) case.
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


def _state_with_growth_baseline(seed=11, n=5, base=0.20, step=0.18, noise=0.005):
    """
    A StudentState whose baseline samples drift monotonically (rather than
    the i.i.d.-around-a-mean fixture above), so state.trajectory.vector is
    not None and a submission that continues the trend clears
    TRAJECTORY_GROWTH_THRESHOLD instead of landing in the lateral band.

    Only the first half of the feature dimensions trend upward across
    samples; the second half stays flat. Trajectory vectors are built from
    per-sample UNIT-normalised vectors (state.py:_compute_trajectory), so a
    uniform across-the-board increase would cancel out under normalisation
    -- the asymmetry between the two halves is what gives the trend an
    actual direction to detect.
    """
    rng = np.random.default_rng(seed)
    state = StudentState(student_id="topic-test-growth")
    half = FEATURE_DIM // 2
    for i in range(n):
        vec = np.full(FEATURE_DIM, base)
        vec[:half] += i * step
        vec = np.clip(vec + rng.normal(0.0, noise, size=FEATURE_DIM), 0.0, 1.0)
        state.add_sample(
            BaselineSample(
                text=f"growth baseline {i}",
                vector=vec,
                provenance="proctored",
                auth_weight=1.0,
                assignment=f"a{i}",
            )
        )
    return state


def test_shadow_score_equals_the_on_mode_score_for_a_growth_trajectory():
    """
    Regression test for a shadow preview that silently dropped
    D_adjusted's trajectory adjustment_factor. deviation_score_inflated
    must mirror D_adjusted -- not D_raw -- for every trajectory direction,
    not just the lateral one (adj_factor == 1.0) that the sibling test
    above happens to exercise.
    """
    state = _state_with_growth_baseline()

    # Continue the baseline's trend: first half elevated, second half low.
    # This is not a random submission -- it is deliberately shaped to align
    # with the baseline's drift direction so trajectory.direction lands
    # "growth" rather than "lateral" or "insufficient_data".
    rng = np.random.default_rng(99)
    half = FEATURE_DIM // 2
    vec = np.full(FEATURE_DIM, 0.02)
    vec[:half] = 1.0
    vec = np.clip(vec + rng.normal(0.0, 0.005, size=FEATURE_DIM), 0.0, 1.0)

    shadow = _score_with(state, vec, _manifest(0.95), "shadow")
    on = _score_with(state, vec, _manifest(0.95), "on")

    # Prove the fixture is exercising the case it claims -- if this fixture
    # ever drifts back into "lateral" (or fails to accumulate enough
    # samples for a trajectory at all), adj_factor would silently become
    # 1.0 again and the equality assertion below would stop being a
    # meaningful test of the trajectory-adjustment coupling.
    assert shadow.trajectory.direction == "growth"
    assert on.trajectory.direction == "growth"

    # Shadow must predict exactly what enabling the flag would do -- for
    # this non-lateral trajectory, that means deviation_score_inflated must
    # already be scaled by the SAME adj_factor (0.75 for growth) that
    # D_adjusted applies on the "on" path.
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
