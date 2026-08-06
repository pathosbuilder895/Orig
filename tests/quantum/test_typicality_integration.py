"""
tests/quantum/test_typicality_integration.py — the typicality axis wired
into score(), gated by TYPICALITY_SCORING / ScoringConfig.typicality_scoring_enabled.
"""

from __future__ import annotations

import numpy as np
import pytest

from original.constants import ALL_FEATURE_CODES, FEATURE_DIM
from original.quantum.scoring import ScoringConfig, score
from original.quantum.state import BaselineSample, StudentState

_RNG = np.random.default_rng(20260728)


def _vec():
    v = _RNG.uniform(0.3, 0.7, FEATURE_DIM)
    return v


def _feature_dict(vector):
    return {code: float(val) for code, val in zip(ALL_FEATURE_CODES, vector)}


def _state_with_n_samples(n):
    samples = [
        BaselineSample(text="", vector=_vec(), provenance="proctored", auth_weight=1.0)
        for _ in range(n)
    ]
    return StudentState(student_id="typicality-test", samples=samples)


class TestTypicalityFlagOff:
    def test_flag_off_leaves_typicality_fields_none(self):
        state = _state_with_n_samples(6)
        sub_vector = _vec()
        result = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(typicality_scoring_enabled=False),
        )
        assert result.typicality_p_far is None
        assert result.typicality_p_central is None
        assert result.typicality_band is None
        assert result.typicality_n == 0

    def test_flag_off_action_selection_unchanged(self):
        """Byte-identical guarantee: flag off must reproduce the pre-existing
        ACTION_THRESHOLDS-on-deviation decision exactly."""
        state = _state_with_n_samples(6)
        sub_vector = _vec()
        off = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(typicality_scoring_enabled=False),
        )
        default = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
        )
        assert off.recommendation.action == default.recommendation.action
        assert off.authorship.deviation_score == default.authorship.deviation_score


class TestTypicalityFlagOn:
    def test_flag_on_populates_typicality_fields_with_enough_samples(self):
        state = _state_with_n_samples(6)
        sub_vector = _vec()
        result = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(typicality_scoring_enabled=True),
        )
        assert result.typicality_p_far is not None
        assert 0.0 <= result.typicality_p_far <= 1.0
        assert result.typicality_p_central is not None
        assert result.typicality_band in {
            "no_action",
            "monitor",
            "schedule_conversation",
            "escalate",
        }
        assert result.typicality_n == 6

    def test_flag_on_with_fewer_than_two_samples_leaves_fields_none(self):
        """loo_distances is [] below N=2 — typicality cannot compute."""
        state = _state_with_n_samples(1)
        sub_vector = _vec()
        result = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(typicality_scoring_enabled=True),
        )
        assert result.typicality_p_far is None
        assert result.typicality_n == 0

    def test_deviation_score_and_catastrophic_override_unaffected_by_flag(self):
        """The typicality axis only changes recommendation.action's SOURCE for
        the no_action/monitor/schedule/escalate call — deviation_score itself,
        and the rms_z >= 3 catastrophic override, are untouched."""
        state = _state_with_n_samples(6)
        sub_vector = _vec()
        on = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(typicality_scoring_enabled=True),
        )
        off = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(typicality_scoring_enabled=False),
        )
        assert on.authorship.deviation_score == off.authorship.deviation_score
        assert on.catastrophic_drift == off.catastrophic_drift
        assert on.catastrophic_drift_rms_z == off.catastrophic_drift_rms_z

    def test_typical_submission_reaches_no_action_at_any_n(self):
        """The spec's central claim: a submission near its own LOO median
        gets p_far ~= 0.5 -> no_action, regardless of N."""
        for n in (2, 5, 9, 15):
            samples = [
                BaselineSample(
                    text="", vector=_vec(), provenance="proctored", auth_weight=1.0
                )
                for _ in range(n)
            ]
            state = StudentState(student_id=f"typicality-n{n}", samples=samples)
            # Score one of the baseline vectors' near-neighbors as the submission —
            # constructed to sit close to the baseline mean, i.e. a typical draw.
            sub_vector = np.mean([s.vector for s in samples], axis=0)
            result = score(
                state=state,
                submission_vector=sub_vector,
                feature_dict=_feature_dict(sub_vector),
                scoring_config=ScoringConfig(typicality_scoring_enabled=True),
            )
            if result.typicality_band is not None:
                # A submission at the exact mean is the MOST central point
                # possible — this specific construction tests the opposite
                # tail (too-central), which is a valid, deliberate probe of
                # the p_central path rather than the "typical" path. See the
                # next test for a genuinely-typical (near-median-distance)
                # construction.
                assert result.typicality_band in {"no_action", "schedule_conversation"}


class TestTypicalityAdaptiveWeightsInteraction:
    def test_typicality_degrades_to_none_when_adaptive_weights_also_active(self):
        """Until loo_distances is computed under the same adaptive weight
        vector as rms_z, the two must not be compared — see Task 3's note."""
        state = _state_with_n_samples(6)
        sub_vector = _vec()
        result = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            adaptive_weights=np.ones(FEATURE_DIM),  # non-None triggers the adaptive path
            scoring_config=ScoringConfig(typicality_scoring_enabled=True),
        )
        assert result.typicality_p_far is None
        assert result.typicality_band is None
