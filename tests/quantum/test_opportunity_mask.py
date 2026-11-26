"""Tests for OPPORTUNITY_MASK: do not score what the paper gave no chance to occur.

The fault being repaired: a share such as ``that_which_ratio`` returns a
placeholder when the new paper has no eligible construction at all, and
``score()`` compared that placeholder with the student's real past values as
if the student had changed. The mask marks those measurements "not measured"
for this paper and leaves them out of the comparison and out of the count the
distance is averaged over.

Three properties are asserted before anything about whether it helps:

  1. off is byte-identical, whatever mask the caller passes;
  2. shadow is byte-identical to off except for the added report-only fields;
  3. the shadow preview equals exactly what "on" produces.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from original.constants import ALL_FEATURE_CODES, FEATURE_DIM, TIER17_CODES, TIER18_CODES
from original.features.baseline_scope import NOT_COMPUTED_FOR_BASELINES_MASK
from original.quantum.scoring import (
    _DEVIATION_TANH_DIVISOR,
    _TIER_WEIGHT_VECTOR,
    ScoringConfig,
    _parse_opportunity_mask_mode,
    _rms_z_from_z,
    score,
)
from original.quantum.state import BaselineSample, StudentState

_IDX = {code: i for i, code in enumerate(ALL_FEATURE_CODES)}
_THAT = _IDX["that_which_ratio"]
_POLY = _IDX["polysyndeton_ratio"]

# Fields the mask is allowed to add on top of an "off" response.
_REPORT_FIELDS = {
    "opportunity_mask_applied",
    "opportunity_mode",
    "unmeasured_features",
    "opportunity_deviation_preview",
}

_PLACEHOLDER_IDX = [
    i for i, c in enumerate(ALL_FEATURE_CODES) if c in set(TIER17_CODES) | set(TIER18_CODES)
]


def _vector(rng):
    v = np.clip(rng.normal(0.5, 0.05, size=FEATURE_DIM), 0.0, 1.0)
    v[_PLACEHOLDER_IDX] = 0.5  # disabled groups, as in the default pilot config
    return v


def _state(seed=3, n=5, student_id="t1:opp") -> StudentState:
    """A student who strongly prefers "that" (0.9) in every past paper."""
    rng = np.random.default_rng(seed)
    state = StudentState(student_id=student_id)
    for i in range(n):
        v = _vector(rng)
        v[_THAT] = 0.9 + 0.01 * i
        v[_POLY] = 0.2 + 0.01 * i
        state.add_sample(
            BaselineSample(
                text=f"baseline {i}",
                vector=v,
                provenance="proctored",
                auth_weight=1.0,
                assignment=f"a{i}",
            )
        )
    return state


def _submission(state, seed=99):
    """Close to the student everywhere, except two placeholder values."""
    rng = np.random.default_rng(seed)
    sub = state.baseline_mean + rng.normal(0.0, 0.01, size=FEATURE_DIM)
    sub = np.clip(sub, 0.0, 1.0)
    sub[_THAT] = 0.5  # the extractor's "nothing to measure" value
    sub[_POLY] = 0.5
    return sub


def _mask(*idx):
    m = np.zeros(FEATURE_DIM, dtype=bool)
    m[list(idx)] = True
    return m


def _fd(sub):
    return {c: float(sub[i]) for i, c in enumerate(ALL_FEATURE_CODES)}


def _score(state, sub, mode="off", mask=None, **kw):
    cfg = kw.pop("config", None) or ScoringConfig(opportunity_mask=mode)
    return score(state, sub, _fd(sub), scoring_config=cfg, unmeasured_mask=mask, **kw)


def _strip(result):
    d = dataclasses.asdict(result)
    for f in _REPORT_FIELDS:
        d.pop(f)
    return d


def _same(a, b):
    np.testing.assert_equal(a, b)


# ── 1. off is byte-identical ─────────────────────────────────────────────────


def test_off_ignores_the_mask_entirely():
    state = _state()
    sub = _submission(state)
    _same(
        dataclasses.asdict(_score(state, sub)),
        dataclasses.asdict(_score(state, sub, mask=_mask(_THAT, _POLY))),
    )


def test_default_config_is_off():
    assert ScoringConfig().opportunity_mask == "off"
    r = _score(_state(), _submission(_state()))
    assert r.opportunity_mask_applied is False
    assert r.opportunity_mode is None
    assert r.unmeasured_features is None
    assert r.opportunity_deviation_preview is None


@pytest.mark.parametrize(
    "raw,expected",
    [("0", "off"), ("", "off"), ("1", "on"), ("on", "on"), ("Shadow", "shadow"), ("yes", "off")],
)
def test_mode_parsing_fails_closed(raw, expected):
    assert _parse_opportunity_mask_mode(raw) == expected


def test_from_env_reads_the_flag(monkeypatch):
    monkeypatch.setenv("OPPORTUNITY_MASK", "shadow")
    assert ScoringConfig.from_env().opportunity_mask == "shadow"
    monkeypatch.delenv("OPPORTUNITY_MASK")
    assert ScoringConfig.from_env().opportunity_mask == "off"


# ── 2. shadow is inert ───────────────────────────────────────────────────────


def test_shadow_changes_nothing_but_the_report_fields():
    state = _state()
    sub = _submission(state)
    off = _score(state, sub)
    shadow = _score(state, sub, "shadow", _mask(_THAT, _POLY))
    _same(_strip(off), _strip(shadow))
    assert shadow.opportunity_mask_applied is False
    assert shadow.opportunity_mode == "shadow"
    assert shadow.unmeasured_features == ["that_which_ratio", "polysyndeton_ratio"]
    assert shadow.opportunity_deviation_preview is not None


def test_shadow_keeps_the_typicality_band():
    state = _state(n=6)
    sub = _submission(state)
    cfg_off = ScoringConfig(typicality_scoring_enabled=True)
    cfg_shadow = dataclasses.replace(cfg_off, opportunity_mask="shadow")
    off = _score(state, sub, config=cfg_off)
    shadow = _score(state, sub, mask=_mask(_THAT), config=cfg_shadow)
    assert off.typicality_band is not None
    assert shadow.typicality_band == off.typicality_band
    assert shadow.typicality_p_far == off.typicality_p_far


# ── 3. on: the repair itself ─────────────────────────────────────────────────


def test_on_stops_scoring_the_placeholder():
    state = _state()
    sub = _submission(state)
    off = _score(state, sub)
    on = _score(state, sub, "on", _mask(_THAT, _POLY))
    assert on.opportunity_mask_applied is True
    assert on.opportunity_mode == "on"
    assert on.opportunity_deviation_preview is None
    # The placeholders were the paper's only real differences.
    assert on.authorship.deviation_score < off.authorship.deviation_score
    listed = {f.code for f in on.interference.destructive_features}
    listed |= {f.code for f in on.interference.constructive_features}
    assert "that_which_ratio" not in listed
    assert "polysyndeton_ratio" not in listed
    assert "that_which_ratio" in {f.code for f in off.interference.destructive_features}


def test_on_averages_over_measured_features_only():
    state = _state()
    sub = _submission(state)
    on = _score(state, sub, "on", _mask(_THAT, _POLY))
    active = state.active_feature_mask & ~_mask(_THAT, _POLY)
    z = (sub - state.baseline_mean) / state.baseline_std
    expected = _rms_z_from_z(z, _TIER_WEIGHT_VECTOR, active, int(active.sum()))
    assert on.catastrophic_drift_rms_z == pytest.approx(expected, rel=1e-12)
    assert on.authorship.deviation_score == pytest.approx(
        float(np.tanh(expected / _DEVIATION_TANH_DIVISOR)) * on.trajectory.adjustment_factor,
        rel=1e-12,
    )


def test_on_reports_the_feature_dict_unchanged():
    state = _state()
    sub = _submission(state)
    on = _score(state, sub, "on", _mask(_THAT))
    assert on.feature_vector["that_which_ratio"] == 0.5


def test_a_real_measurement_is_still_scored():
    """Masking is per paper: the same feature counts when it was measured."""
    state = _state()
    sub = _submission(state)
    off = _score(state, sub)
    on = _score(state, sub, "on", _mask(_POLY))  # that_which was measured
    assert "that_which_ratio" in {f.code for f in on.interference.destructive_features}
    assert on.authorship.deviation_score > 0.0
    assert on.unmeasured_features == ["polysyndeton_ratio"]
    assert on.authorship.deviation_score != off.authorship.deviation_score


# ── abstention: nothing to mask means exactly off ────────────────────────────


@pytest.mark.parametrize("mode", ["on", "shadow"])
@pytest.mark.parametrize(
    "mask",
    [
        None,
        np.zeros(FEATURE_DIM, dtype=bool),
        np.ones(FEATURE_DIM - 1, dtype=bool),  # wrong shape: ignored
    ],
)
def test_no_usable_mask_is_exactly_off(mode, mask):
    state = _state()
    sub = _submission(state)
    r = _score(state, sub, mode, mask)
    _same(dataclasses.asdict(_score(state, sub)), dataclasses.asdict(r))
    assert r.opportunity_mode is None


@pytest.mark.parametrize("mode", ["on", "shadow"])
def test_mask_on_features_already_left_out_is_exactly_off(mode):
    """Disabled groups and comparison measurements are not compared anyway."""
    state = _state()
    sub = _submission(state)
    mask = np.zeros(FEATURE_DIM, dtype=bool)
    mask[_PLACEHOLDER_IDX] = True
    mask |= NOT_COMPUTED_FOR_BASELINES_MASK
    assert not (mask & state.active_feature_mask).any()
    _same(
        dataclasses.asdict(_score(state, sub)),
        dataclasses.asdict(_score(state, sub, mode, mask)),
    )


def test_on_withholds_the_typicality_band_when_it_masked_something():
    """loo_distances are computed over the full feature set; a distance over
    fewer features is not comparable, so withhold instead of reporting it."""
    state = _state(n=6)
    sub = _submission(state)
    cfg = ScoringConfig(typicality_scoring_enabled=True, opportunity_mask="on")
    assert _score(state, sub, mask=_mask(_THAT), config=cfg).typicality_band is None
    assert _score(state, sub, mask=None, config=cfg).typicality_band is not None


def test_on_withholds_the_conformal_pvalue_when_it_masked_something():
    state = _state(n=6)
    sub = _submission(state)
    cfg = ScoringConfig(
        amplitude_scoring_enabled=True,
        authentic_fidelities=[0.5, 0.6, 0.7, 0.8, 0.9],
        opportunity_mask="on",
    )
    assert (
        _score(state, sub, mask=None, config=cfg).authorship.fidelity_conformal_pvalue is not None
    )
    masked = _score(state, sub, mask=_mask(_THAT), config=cfg)
    assert masked.authorship.fidelity_conformal_pvalue is None


def test_everything_unmeasured_scores_zero_distance():
    state = _state()
    sub = _submission(state)
    on = _score(state, sub, "on", np.ones(FEATURE_DIM, dtype=bool))
    assert on.catastrophic_drift_rms_z == 0.0
    assert on.authorship.deviation_score == 0.0


# ── shadow preview equals "on" ───────────────────────────────────────────────


_TOPIC_MANIFEST = {"topic": {"baseline_distance": 0.45}}


def _genre_prior():
    rng = np.random.default_rng(13)
    return {
        "mean": np.clip(rng.normal(0.5, 0.05, size=FEATURE_DIM), 0.0, 1.0),
        "std": np.abs(rng.normal(0.08, 0.02, size=FEATURE_DIM)) + 0.01,
        "n_samples": 12,
        "n_students": 4,
    }


def _impostor_stats():
    rng = np.random.default_rng(5)
    mu = np.clip(rng.normal(0.5, 0.05, size=FEATURE_DIM), 0.0, 1.0)
    sigma = np.abs(rng.normal(0.08, 0.03, size=FEATURE_DIM)) + 0.01
    return mu, sigma


def _adaptive_weights():
    rng = np.random.default_rng(8)
    return _TIER_WEIGHT_VECTOR * rng.uniform(0.6, 1.4, size=FEATURE_DIM)


@pytest.mark.parametrize(
    "extra,kwargs",
    [
        ({}, {}),
        ({}, {"adaptive_weights": "adaptive"}),
        ({"length_adaptive_weights": True}, {"n_tokens": 350}),
        ({"characteristic_weights": "on"}, {"impostor_stats": "pool"}),
        (
            {"characteristic_weights": "on", "length_adaptive_weights": True},
            {"impostor_stats": "pool", "adaptive_weights": "adaptive", "n_tokens": 350},
        ),
        ({"null_model": "impostor"}, {"impostor_stats": "pool"}),
        ({"identity_axis_enabled": True}, {}),
        ({"characteristic_weights": "shadow"}, {"impostor_stats": "pool"}),
        ({"characteristic_weights": "on"}, {}),  # no pool: the factor abstains
        ({"topic_variance_inflation": "on"}, {"manifest": _TOPIC_MANIFEST}),
        ({"topic_variance_inflation": "shadow"}, {"manifest": _TOPIC_MANIFEST}),
        (
            {"bayesian_prior_enabled": True, "genre_stats": "prior"},
            {},
        ),
    ],
)
@pytest.mark.parametrize("n", [5, 9])
def test_shadow_preview_equals_on(extra, kwargs, n):
    state = _state(n=n)
    sub = _submission(state)
    kw = dict(kwargs)
    extra = dict(extra)
    if extra.get("genre_stats") == "prior":
        extra["genre_stats"] = _genre_prior()
        state.samples[-1].genre = "scholarly_essay"
    if kw.get("adaptive_weights") == "adaptive":
        kw["adaptive_weights"] = _adaptive_weights()
    if kw.get("impostor_stats") == "pool":
        kw["impostor_stats"] = _impostor_stats()
    mask = _mask(_THAT, _POLY)
    shadow = _score(
        state, sub, mask=mask, config=ScoringConfig(opportunity_mask="shadow", **extra), **kw
    )
    on = _score(state, sub, mask=mask, config=ScoringConfig(opportunity_mask="on", **extra), **kw)
    assert shadow.opportunity_deviation_preview == pytest.approx(
        on.authorship.deviation_score, rel=1e-12, abs=1e-15
    )


def test_shadow_preview_follows_the_trajectory_adjustment(monkeypatch):
    """'on' changes the vector the trajectory alignment is read from, so the
    preview has to recompute the adjustment instead of borrowing the live one.

    The growth threshold is placed between the two alignments, so the live
    (unmasked) score is 'lateral' and the masked one is 'growth': a preview
    that reused the live factor would be wrong by exactly 0.75.
    """
    import original.quantum.scoring as scoring

    rng = np.random.default_rng(21)
    state = StudentState(student_id="t1:opp-traj")
    drift = rng.normal(0.0, 1.0, size=FEATURE_DIM)
    drift[_PLACEHOLDER_IDX] = 0.0
    drift /= np.linalg.norm(drift)
    for i in range(8):
        v = np.clip(_vector(rng) + 0.04 * i * drift, 0.0, 1.0)
        v[_THAT] = 0.9 + 0.03 * (i % 3)
        state.add_sample(
            BaselineSample(
                text=f"b{i}", vector=v, provenance="proctored", auth_weight=1.0, assignment=f"a{i}"
            )
        )
    assert state.trajectory.vector is not None
    sub = np.clip(state.baseline_mean + 0.2 * drift, 0.0, 1.0)
    sub[_THAT] = 0.0
    mask = _mask(_THAT)

    def _alignment(vec):
        vec = np.where(NOT_COMPUTED_FOR_BASELINES_MASK, state.baseline_mean, vec)
        return float(np.dot(vec / np.linalg.norm(vec), state.trajectory.vector))

    live = _alignment(sub)
    masked = _alignment(np.where(mask, state.baseline_mean, sub))
    assert live != masked
    lo, hi = sorted((live, masked))
    monkeypatch.setattr(scoring, "TRAJECTORY_GROWTH_THRESHOLD", (lo + hi) / 2)
    monkeypatch.setattr(scoring, "TRAJECTORY_REGRESSIVE_THRESHOLD", -1.0)

    off = _score(state, sub)
    shadow = _score(state, sub, "shadow", mask)
    on = _score(state, sub, "on", mask)
    assert on.trajectory.adjustment_factor != off.trajectory.adjustment_factor
    assert shadow.trajectory.adjustment_factor == off.trajectory.adjustment_factor
    assert shadow.opportunity_deviation_preview == pytest.approx(
        on.authorship.deviation_score, rel=1e-12, abs=1e-15
    )


def test_shadow_preview_equals_on_under_topic_inflation_really_inflated():
    """Guard the topic arms above against a manifest that inflates nothing."""
    state = _state()
    sub = _submission(state)
    on = _score(
        state,
        sub,
        mask=_mask(_THAT),
        config=ScoringConfig(opportunity_mask="on", topic_variance_inflation="on"),
        manifest=_TOPIC_MANIFEST,
    )
    assert on.topic_inflation_applied is True


def test_shadow_preview_equals_on_at_catastrophic_drift():
    state = _state()
    rng = np.random.default_rng(4)
    sub = np.clip(state.baseline_mean + rng.choice([-0.45, 0.45], size=FEATURE_DIM), 0.0, 1.0)
    sub[_THAT] = 0.5
    mask = _mask(_THAT)
    shadow = _score(state, sub, "shadow", mask)
    on = _score(state, sub, "on", mask)
    assert on.catastrophic_drift is True
    assert shadow.opportunity_deviation_preview == pytest.approx(
        on.authorship.deviation_score, rel=1e-12, abs=1e-15
    )


# ── a muted feature must be score-neutral ────────────────────────────────────


@pytest.mark.parametrize("mode", ["on", "shadow"])
def test_masking_a_zero_weight_feature_is_exactly_off(mode):
    """The manifest mutes a feature by giving it weight 0.0, but it is still
    counted in n_active. Dropping it would shrink the denominator alone and
    raise rms_z, so the mask must leave it alone."""
    state = _state()
    sub = _submission(state)
    weights = _TIER_WEIGHT_VECTOR.copy()
    weights[[_THAT, _POLY]] = 0.0
    off = score(state, sub, _fd(sub), adaptive_weights=weights)
    masked = score(
        state,
        sub,
        _fd(sub),
        adaptive_weights=weights,
        scoring_config=ScoringConfig(opportunity_mask=mode),
        unmeasured_mask=_mask(_THAT, _POLY),
    )
    _same(dataclasses.asdict(off), dataclasses.asdict(masked))


def test_on_masks_only_the_features_that_carry_weight():
    state = _state()
    sub = _submission(state)
    weights = _TIER_WEIGHT_VECTOR.copy()
    weights[_POLY] = 0.0
    on = score(
        state,
        sub,
        _fd(sub),
        adaptive_weights=weights,
        scoring_config=ScoringConfig(opportunity_mask="on"),
        unmeasured_mask=_mask(_THAT, _POLY),
    )
    assert on.unmeasured_features == ["that_which_ratio"]
    off = score(state, sub, _fd(sub), adaptive_weights=weights)
    assert on.catastrophic_drift_rms_z < off.catastrophic_drift_rms_z


def test_shadow_preview_equals_on_without_a_trajectory():
    """Two past papers: no trend to adjust for, so the factor is 1.0 in both."""
    rng = np.random.default_rng(31)
    state = StudentState(student_id="t1:opp-two")
    for i, that in enumerate((0.80, 0.95)):  # spread wide enough to stay active
        v = _vector(rng)
        v[_THAT] = that
        state.add_sample(
            BaselineSample(
                text=f"b{i}", vector=v, provenance="proctored", auth_weight=1.0, assignment=f"a{i}"
            )
        )
    assert state.trajectory.vector is None
    sub = _submission(state)
    mask = _mask(_THAT)
    shadow = _score(state, sub, "shadow", mask)
    on = _score(state, sub, "on", mask)
    assert shadow.opportunity_deviation_preview == pytest.approx(
        on.authorship.deviation_score, rel=1e-12, abs=1e-15
    )
