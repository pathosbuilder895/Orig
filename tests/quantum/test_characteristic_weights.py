"""Tests for characteristic per-student feature weighting (CHARACTERISTIC_WEIGHTS).

The mechanism weights each feature by how *characteristic* it is for the
individual student: features where the peer population is spread out
(sigma_null large) but the student is internally consistent (baseline_std
small) carry identity; the reverse carries noise.

Two properties are load-bearing and are asserted first here, before anything
about whether the mechanism helps:

  1. Sigma(w^2) preservation — the factor RE-DISTRIBUTES weight, it does not
     inflate or deflate the tanh-calibrated rms_z on average. The naive
     "mean factor = 1.0" normalisation was tried for LENGTH_WEIGHT_SCHEDULE
     and FAILED (see the block comment in original/constants.py).
  2. Shadow inertness — "shadow" output is byte-identical to "off" except for
     the added report-only preview fields.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from original.constants import ALL_FEATURE_CODES, FEATURE_DIM, TIER17_CODES, TIER18_CODES
from original.quantum.null_pool import build_impostor_stats
from original.quantum.scoring import (
    _CHARACTERISTIC_SIGMA_FLOOR,
    _TIER_WEIGHT_VECTOR,
    ScoringConfig,
    _characteristic_weight_factor,
    _rms_z_from_z,
    score,
)
from original.quantum.state import BaselineSample, StudentState

# Fields the shadow preview is allowed to add on top of an "off" response.
_PREVIEW_FIELDS = {
    "characteristic_weighting_applied",
    "characteristic_mode",
    "characteristic_factor_dispersion",
    "characteristic_rms_z_preview",
    "characteristic_deviation_preview",
}


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _state_with_baseline(seed=11, n=5, student_id="char-test") -> StudentState:
    rng = np.random.default_rng(seed)
    state = StudentState(student_id=student_id)
    for i in range(n):
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


def _char_factor(state, impostor_stats, weight_vec, active=None):
    """Call the helper the way score() does — with the state's REAL active
    mask, not an assumed all-ones one."""
    return _characteristic_weight_factor(
        state,
        impostor_stats,
        weight_vec,
        state.active_feature_mask if active is None else active,
    )


# ── Realistic active mask ────────────────────────────────────────────────────
#
# _state_with_baseline above gives every one of the 109 features genuine
# variance, so its active mask is all-True and any invariant stated "over the
# active set" is indistinguishable from the same invariant stated over all
# FEATURE_DIM features. That is not the production shape. In the default
# pilot config Tier 17 (behavioral) and Tier 18 (uniformity) are in
# DISABLED_FEATURE_GROUPS, so every baseline vector carries exactly 0.5 in
# those 12 slots, and a handful of features are never observed at all —
# active_feature_mask drops both classes. Those slots carry the two HIGHEST
# tier weights, and their sigma_null/baseline_std ratio is pinned by
# construction (a constant peer pool floors sigma_null at
# null_pool.SIGMA_FLOOR), so they land deterministically on the clip floor.
# Normalising Σ(w²) over all features therefore released their weight to the
# live features and inflated rms_z ~8%.
_DEAD_CODES = ("chiasmus_rate", "structural_centrist_penalty", "hendiadys_rate")
_PLACEHOLDER_IDX = [
    i for i, c in enumerate(ALL_FEATURE_CODES) if c in set(TIER17_CODES) | set(TIER18_CODES)
]
_DEAD_IDX = [i for i, c in enumerate(ALL_FEATURE_CODES) if c in _DEAD_CODES]


def _realistic_vector(rng):
    v = np.clip(rng.normal(0.5, 0.05, size=FEATURE_DIM), 0.0, 1.0)
    v[_PLACEHOLDER_IDX] = 0.5  # disabled groups -> exact neutral placeholder
    v[_DEAD_IDX] = 0.0  # never observed in any baseline doc
    return v


def _realistic_state(seed=11, n=5, student_id="t1:char-real") -> StudentState:
    rng = np.random.default_rng(seed)
    state = StudentState(student_id=student_id)
    for i in range(n):
        state.add_sample(
            BaselineSample(
                text=f"baseline {i}",
                vector=_realistic_vector(rng),
                provenance="proctored",
                auth_weight=1.0,
                assignment=f"a{i}",
            )
        )
    return state


def _realistic_pool(n_peers=4, n_each=3):
    """A peer pool built through the PRODUCTION builder, so the disabled
    tiers get null_pool.SIGMA_FLOOR rather than a hand-chosen sigma."""
    peers = [
        _realistic_state(seed=100 + k, n=n_each, student_id=f"t1:peer{k}") for k in range(n_peers)
    ]
    stats = build_impostor_stats("t1:char-real", peers)
    assert stats is not None
    return stats


def _impostor_stats(seed=7):
    """A peer pool whose per-feature spread VARIES across features — a flat
    sigma_null would make every ratio proportional to 1/baseline_std, which
    still produces a non-trivial factor but hides ordering bugs."""
    rng = np.random.default_rng(seed)
    mu_null = np.full(FEATURE_DIM, 0.5)
    sigma_null = rng.uniform(0.03, 0.20, size=FEATURE_DIM)
    return mu_null, sigma_null


def _score_with(state, vector, mode, impostor_stats=None, **cfg):
    return score(
        state,
        vector,
        {code: float(v) for code, v in zip(ALL_FEATURE_CODES, vector, strict=False)},
        submission_id="s1",
        impostor_stats=impostor_stats,
        scoring_config=ScoringConfig(characteristic_weights=mode, **cfg),
    )


def _submission(seed=99):
    rng = np.random.default_rng(seed)
    return np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)


# ── 1. Sigma(w^2) invariant ──────────────────────────────────────────────────


def test_sum_of_squares_is_preserved_for_the_tier_weight_vector():
    state = _state_with_baseline()
    factor = _char_factor(state, _impostor_stats(), _TIER_WEIGHT_VECTOR)
    assert factor is not None
    w = _TIER_WEIGHT_VECTOR
    assert float(np.sum((w * factor) ** 2)) == pytest.approx(float(np.sum(w**2)), rel=1e-12)


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_sum_of_squares_is_preserved_for_arbitrary_weight_vectors(seed):
    """The rescale is relative to whichever vector was SELECTED (static tier
    weights or a Phase-5 adaptive vector), so it must hold for both."""
    rng = np.random.default_rng(seed)
    state = _state_with_baseline(seed=seed + 30)
    w = rng.uniform(0.2, 2.0, size=FEATURE_DIM)
    factor = _char_factor(state, _impostor_stats(seed=seed + 60), w)
    assert factor is not None
    assert float(np.sum((w * factor) ** 2)) == pytest.approx(float(np.sum(w**2)), rel=1e-12)


def test_factor_is_non_trivial_so_the_invariant_is_not_vacuous():
    """A factor that is identically 1.0 would satisfy the invariant trivially.
    Assert the mechanism actually redistributes: some features up, some down."""
    state = _state_with_baseline()
    factor = _char_factor(state, _impostor_stats(), _TIER_WEIGHT_VECTOR)
    assert factor is not None
    assert factor.shape == (FEATURE_DIM,)
    assert float(factor.max()) > 1.0
    assert float(factor.min()) < 1.0


# ── 1b. Sigma(w^2) invariant under a REALISTIC active mask ───────────────────
#
# These are the tests the two above cannot be: with an all-True mask the
# active-set invariant and the all-features invariant are literally the same
# assertion. Each of these FAILS against a helper that normalises over all
# FEATURE_DIM features (measured on this fixture: active Sigma(w^2) +16%,
# rms_z x1.077, deviation +0.033 at rms_z=1.0).


def test_the_realistic_fixture_actually_has_an_incomplete_active_mask():
    """Guard the guard: if this fixture ever goes all-active, the three tests
    below silently stop testing anything."""
    state = _realistic_state()
    active = state.active_feature_mask
    n_active = int(active.sum())
    assert n_active < FEATURE_DIM
    # The disabled tiers are the systematic part, and they are the ones that
    # carry the highest tier weights.
    assert not active[_PLACEHOLDER_IDX].any()
    assert not active[_DEAD_IDX].any()
    # Enough of the vector must survive for the test to be about a real score.
    assert n_active > FEATURE_DIM * 0.8


def test_sum_of_squares_is_preserved_over_the_active_set():
    """Sigma(w^2) must be invariant over the feature set rms_z actually sums
    over. _rms_z_from_z zeroes inactive features and divides by n_active, so
    weight released from an inactive feature is weight invented from nothing."""
    state = _realistic_state()
    active = state.active_feature_mask
    w = _TIER_WEIGHT_VECTOR
    factor = _char_factor(state, _realistic_pool(), w)
    assert factor is not None
    before = float(np.sum((w**2)[active]))
    after = float(np.sum(((w * factor) ** 2)[active]))
    assert after == pytest.approx(before, rel=1e-12)


def test_rms_z_is_unchanged_on_average_under_a_realistic_active_mask():
    """The stated PURPOSE of the Sigma(w^2) rescale: redistribute weight
    without inflating or deflating the tanh-calibrated rms_z on average. A
    uniform z-vector is exactly the 'on average' case."""
    state = _realistic_state()
    active = state.active_feature_mask
    n_active = int(active.sum())
    w = _TIER_WEIGHT_VECTOR
    factor = _char_factor(state, _realistic_pool(), w)
    assert factor is not None
    z = np.ones(FEATURE_DIM)
    assert _rms_z_from_z(z, w * factor, active, n_active) == pytest.approx(
        _rms_z_from_z(z, w, active, n_active), rel=1e-12
    )


def test_inactive_features_are_pinned_at_exactly_one():
    """Two consequences: Sigma(w^2) is preserved over the FULL vector as well
    as the active set, and dead features contribute exactly nothing to
    characteristic_factor_dispersion instead of sitting at the clip bound."""
    state = _realistic_state()
    active = state.active_feature_mask
    w = _TIER_WEIGHT_VECTOR
    factor = _char_factor(state, _realistic_pool(), w)
    assert factor is not None
    assert np.all(factor[~active] == 1.0)
    assert float(np.sum((w * factor) ** 2)) == pytest.approx(float(np.sum(w**2)), rel=1e-12)
    # Still non-trivial where it counts, so the invariant is not vacuous.
    assert float(factor[active].max()) > 1.0
    assert float(factor[active].min()) < 1.0


def test_abstains_when_the_active_mask_selects_nothing():
    state = _realistic_state()
    nothing = np.zeros(FEATURE_DIM, dtype=bool)
    assert _char_factor(state, _realistic_pool(), _TIER_WEIGHT_VECTOR, active=nothing) is None


def test_dispersion_is_reported_over_active_features_only():
    """characteristic_factor_dispersion is the entire basis of the
    anti-inert-flag argument and of the prescribed shadow soak, so it must
    describe features that can actually move a score."""
    state = _realistic_state()
    active = state.active_feature_mask
    out = _score_with(state, _submission(), "shadow", impostor_stats=_realistic_pool())
    factor = _char_factor(state, _realistic_pool(), _TIER_WEIGHT_VECTOR)
    assert factor is not None
    assert out.characteristic_factor_dispersion == pytest.approx(
        float(np.mean(np.abs(factor[active] - 1.0)))
    )
    # Distinct from the all-features average, which the pinned 1.0s dilute.
    assert out.characteristic_factor_dispersion != pytest.approx(
        float(np.mean(np.abs(factor - 1.0)))
    )
    assert out.characteristic_factor_dispersion > 0.0


# ── 2. Abstention ────────────────────────────────────────────────────────────


def test_abstains_without_impostor_stats():
    assert _char_factor(_state_with_baseline(), None, _TIER_WEIGHT_VECTOR) is None


def test_abstains_on_a_thin_baseline():
    """With < 2 contributing samples baseline_std is the flat 0.15 uncertainty
    prior, not a measurement of the student — the ratio is meaningless."""
    thin = _state_with_baseline(n=1)
    assert _char_factor(thin, _impostor_stats(), _TIER_WEIGHT_VECTOR) is None


def test_abstains_on_malformed_or_non_finite_impostor_sigma():
    state = _state_with_baseline()
    mu_null = np.full(FEATURE_DIM, 0.5)
    bad_shape = (mu_null, np.full(FEATURE_DIM - 3, 0.1))
    assert _char_factor(state, bad_shape, _TIER_WEIGHT_VECTOR) is None

    nan_sigma = np.full(FEATURE_DIM, 0.1)
    nan_sigma[4] = np.nan
    assert _char_factor(state, (mu_null, nan_sigma), _TIER_WEIGHT_VECTOR) is None


def test_abstains_on_a_degenerate_weight_vector():
    """A zero weight vector makes the rescale factor undefined (0/0)."""
    state = _state_with_baseline()
    zeros = np.zeros(FEATURE_DIM)
    assert _char_factor(state, _impostor_stats(), zeros) is None


def test_on_mode_with_no_impostor_stats_is_exactly_off():
    """Abstention must be identity, not merely 'close to' identity."""
    state = _state_with_baseline()
    vec = _submission()
    off = _score_with(state, vec, "off")
    on = _score_with(state, vec, "on")
    assert on.authorship.deviation_score == off.authorship.deviation_score
    assert on.recommendation.action == off.recommendation.action
    assert on.characteristic_weighting_applied is False
    assert on.characteristic_mode is None


def test_sigma_floor_matches_the_existing_convention():
    """SIGMA_FLOOR = 0.005 in null_pool, and state.baseline_std's own hard
    minimum. Do not introduce a third convention."""
    from original.quantum.null_pool import SIGMA_FLOOR

    assert _CHARACTERISTIC_SIGMA_FLOOR == SIGMA_FLOOR == 0.005


# ── 3. Flag parsing ──────────────────────────────────────────────────────────


def test_default_config_is_off():
    assert ScoringConfig().characteristic_weights == "off"


@pytest.mark.parametrize(
    "env_value,expected",
    [
        ("0", "off"),
        ("1", "on"),
        ("on", "on"),
        ("shadow", "shadow"),
        ("off", "off"),
        ("", "off"),
        ("nonsense", "off"),
        ("SHADOW", "shadow"),
        ("  On  ", "on"),
        ("2", "off"),
        ("true", "off"),
    ],
)
def test_from_env_parses_mode(monkeypatch, env_value, expected):
    monkeypatch.setenv("CHARACTERISTIC_WEIGHTS", env_value)
    assert ScoringConfig.from_env().characteristic_weights == expected


def test_from_env_defaults_off_when_unset(monkeypatch):
    monkeypatch.delenv("CHARACTERISTIC_WEIGHTS", raising=False)
    assert ScoringConfig.from_env().characteristic_weights == "off"


# ── 4. Shadow inertness ──────────────────────────────────────────────────────


def _asdict_without_preview(result):
    d = dataclasses.asdict(result)
    for key in _PREVIEW_FIELDS:
        d.pop(key, None)
    return d


def test_shadow_is_byte_identical_to_off_except_the_preview_fields():
    state = _state_with_baseline()
    vec = _submission()
    stats = _impostor_stats()

    off = _score_with(state, vec, "off", impostor_stats=stats)
    shadow = _score_with(state, vec, "shadow", impostor_stats=stats)

    assert _asdict_without_preview(shadow) == _asdict_without_preview(off)
    # ...and the preview is actually populated, so the comparison above is
    # not passing because shadow did nothing at all.
    assert shadow.characteristic_mode == "shadow"
    assert shadow.characteristic_weighting_applied is False
    assert shadow.characteristic_rms_z_preview is not None
    assert shadow.characteristic_deviation_preview is not None
    assert off.characteristic_mode is None
    assert off.characteristic_rms_z_preview is None


def test_shadow_does_not_touch_the_llr_route():
    """weight_vec feeds _llr_deviation too; shadow must leave it alone."""
    state = _state_with_baseline()
    vec = _submission()
    stats = _impostor_stats()
    off = _score_with(state, vec, "off", impostor_stats=stats, null_model="impostor")
    shadow = _score_with(state, vec, "shadow", impostor_stats=stats, null_model="impostor")
    assert off.authorship.llr_deviation_score is not None
    assert shadow.authorship.llr_deviation_score == off.authorship.llr_deviation_score


def test_shadow_does_not_touch_amplitude_scoring():
    state = _state_with_baseline()
    vec = _submission()
    stats = _impostor_stats()
    off = _score_with(state, vec, "off", impostor_stats=stats, amplitude_scoring_enabled=True)
    shadow = _score_with(state, vec, "shadow", impostor_stats=stats, amplitude_scoring_enabled=True)
    assert off.authorship.quantum_fidelity > 0.0
    assert shadow.authorship.quantum_fidelity == off.authorship.quantum_fidelity


def test_shadow_preview_equals_the_on_mode_score():
    """The preview must be what "on" would actually have produced — including
    the trajectory adjustment — or shadow is previewing the wrong number."""
    state = _state_with_baseline()
    vec = _submission()
    stats = _impostor_stats()

    shadow = _score_with(state, vec, "shadow", impostor_stats=stats)
    on = _score_with(state, vec, "on", impostor_stats=stats)

    assert shadow.characteristic_deviation_preview == pytest.approx(
        on.authorship.deviation_score, abs=1e-12
    )
    assert shadow.characteristic_rms_z_preview == pytest.approx(
        on.catastrophic_drift_rms_z, abs=1e-12
    )


def test_shadow_preview_equals_on_mode_under_length_adaptive_weights():
    """Order is select -> characteristic -> length. If the preview applied
    the factor after the length schedule (or skipped it), this diverges."""
    state = _state_with_baseline()
    vec = _submission()
    stats = _impostor_stats()

    kwargs = dict(impostor_stats=stats, length_adaptive_weights=True)
    shadow = _score_with(state, vec, "shadow", **kwargs)
    on = _score_with(state, vec, "on", **kwargs)
    assert shadow.characteristic_deviation_preview == pytest.approx(
        on.authorship.deviation_score, abs=1e-12
    )


def test_shadow_preview_equals_on_mode_under_adaptive_weights():
    """The factor rescales relative to the SELECTED vector, so a Phase-5
    adaptive vector must round-trip identically."""
    rng = np.random.default_rng(5)
    adaptive = rng.uniform(0.4, 1.8, size=FEATURE_DIM)
    state = _state_with_baseline()
    vec = _submission()
    stats = _impostor_stats()
    fd = {code: float(v) for code, v in zip(ALL_FEATURE_CODES, vec, strict=False)}

    def _run(mode):
        return score(
            state,
            vec,
            fd,
            submission_id="s1",
            adaptive_weights=adaptive,
            impostor_stats=stats,
            scoring_config=ScoringConfig(characteristic_weights=mode),
        )

    assert _run("shadow").characteristic_deviation_preview == pytest.approx(
        _run("on").authorship.deviation_score, abs=1e-12
    )


def test_shadow_leaves_typicality_untouched():
    """Shadow never modifies weight_vec, so rms_z stays comparable to
    loo_distances — and typicality_band feeds _recommend() under
    IDENTITY_AXIS, so withholding it in shadow would let shadow change an
    action."""
    state = _state_with_baseline()
    vec = _submission()
    stats = _impostor_stats()
    off = _score_with(state, vec, "off", impostor_stats=stats, typicality_scoring_enabled=True)
    shadow = _score_with(
        state, vec, "shadow", impostor_stats=stats, typicality_scoring_enabled=True
    )
    assert shadow.typicality_band == off.typicality_band
    assert shadow.typicality_n == off.typicality_n


# ── 5. "on" mode ─────────────────────────────────────────────────────────────


def test_on_mode_changes_the_score_and_records_the_audit_trail():
    state = _state_with_baseline()
    vec = _submission()
    stats = _impostor_stats()

    off = _score_with(state, vec, "off", impostor_stats=stats)
    on = _score_with(state, vec, "on", impostor_stats=stats)

    assert on.authorship.deviation_score != off.authorship.deviation_score
    assert on.characteristic_weighting_applied is True
    assert on.characteristic_mode == "on"
    assert on.characteristic_factor_dispersion is not None
    assert on.characteristic_factor_dispersion > 0.0
    # "on" produces the score itself, so there is nothing left to preview.
    assert on.characteristic_rms_z_preview is None
    assert on.characteristic_deviation_preview is None


def test_typicality_is_withheld_when_on():
    """state.loo_distances is computed under the UNweighted reference, so a
    reweighted rms_z cannot be compared against it — withhold the band rather
    than report a wrong one (the established precedent for adaptive weights
    and sigma inflation)."""
    state = _state_with_baseline()
    vec = _submission()
    stats = _impostor_stats()

    off = _score_with(state, vec, "off", impostor_stats=stats, typicality_scoring_enabled=True)
    on = _score_with(state, vec, "on", impostor_stats=stats, typicality_scoring_enabled=True)
    assert off.typicality_n > 0  # the guard is doing work, not masking an empty path
    assert on.typicality_band is None
    assert on.typicality_p_far is None
    assert on.typicality_n == 0


def test_dispersion_is_reported_in_shadow_too():
    """Instrumentation: 'how far from 1.0 is this factor actually getting?'
    must be answerable from a shadow soak, or the flag repeats the
    GENRE_INVARIANT_WEIGHTS_ENABLED failure of shipping an inert mechanism."""
    state = _state_with_baseline()
    vec = _submission()
    stats = _impostor_stats()
    shadow = _score_with(state, vec, "shadow", impostor_stats=stats)
    on = _score_with(state, vec, "on", impostor_stats=stats)
    assert shadow.characteristic_factor_dispersion == pytest.approx(
        on.characteristic_factor_dispersion, abs=1e-12
    )
    assert shadow.characteristic_factor_dispersion > 0.0
