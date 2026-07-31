"""
tests/test_power.py — statistical floors/ceilings for gate informativeness.
The Instrument Report's G1 finding in numbers: with 12 baseline docs the
smallest reachable conformal p is 1/13 ≈ 0.077, while the no-action band
needs <= 0.03 — the gate cannot flag, so 0.0% flagged proves nothing.
"""
from __future__ import annotations

import pytest

from validation.power import (
    band_reachable,
    bar_decidable,
    conformal_p_floor,
    min_docs_for_band,
    rule_of_three_upper,
    wilson_interval,
)


class TestConformalFloor:
    def test_twelve_docs_floor_matches_instrument_report(self):
        assert conformal_p_floor(12) == pytest.approx(1 / 13)

    def test_floor_decreases_with_n(self):
        assert conformal_p_floor(200) < conformal_p_floor(12)

    def test_nonpositive_n_raises(self):
        with pytest.raises(ValueError):
            conformal_p_floor(0)


class TestBandReachable:
    def test_unreachable_at_pilot_scale(self):
        assert band_reachable(12, 0.03) is False

    def test_reachable_at_scale(self):
        assert band_reachable(199, 0.005) is True
        assert band_reachable(33, 0.03) is True

    def test_boundary_is_inclusive(self):
        # floor(33) = 1/34 ≈ 0.0294 <= 0.03 → reachable; floor(32) = 1/33 ≈ 0.0303 → not
        assert band_reachable(33, 0.03) is True
        assert band_reachable(32, 0.03) is False


class TestMinDocsForBand:
    def test_escalation_band_needs_199(self):
        # Instrument Report: "Escalation needs roughly 199 samples"
        # (SCHEDULE_FAR_THRESHOLD = 0.005 → ceil(1/0.005) - 1 = 199)
        assert min_docs_for_band(0.005) == 199

    def test_no_action_band_needs_33(self):
        assert min_docs_for_band(0.03) == 33

    def test_returned_n_is_minimal(self):
        for t in (0.005, 0.02, 0.03, 0.05):
            n = min_docs_for_band(t)
            assert band_reachable(n, t) and not band_reachable(n - 1, t)


class TestRuleOfThree:
    def test_216_samples_bounds_fpr_at_1_4_percent(self):
        # G1's 0/216 flagged: cannot demonstrate FPR below ~1.4%
        assert rule_of_three_upper(216) == pytest.approx(3 / 216)

    def test_nonpositive_n_raises(self):
        with pytest.raises(ValueError):
            rule_of_three_upper(0)


class TestWilsonInterval:
    def test_matches_known_values_for_g3(self):
        lo, hi = wilson_interval(10, 22)  # the measured 0.455
        assert lo == pytest.approx(0.269, abs=0.002)
        assert hi == pytest.approx(0.653, abs=0.002)

    def test_interval_contains_the_point_estimate(self):
        for k, n in [(0, 10), (5, 10), (10, 10), (18, 22)]:
            lo, hi = wilson_interval(k, n)
            assert lo <= k / n <= hi

    def test_interval_narrows_as_n_grows(self):
        narrow = wilson_interval(150, 200)
        wide = wilson_interval(15, 20)
        assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])

    def test_bounds_stay_within_zero_one(self):
        for k, n in [(0, 5), (5, 5)]:
            lo, hi = wilson_interval(k, n)
            assert 0.0 <= lo <= hi <= 1.0

    def test_rejects_impossible_counts(self):
        with pytest.raises(ValueError):
            wilson_interval(11, 10)
        with pytest.raises(ValueError):
            wilson_interval(-1, 10)


class TestBarDecidable:
    def test_g3_observed_failure_is_genuinely_below(self):
        # 10/22 = 0.455, CI upper 0.653 < 0.7 — a real finding
        assert bar_decidable(10, 22, bar=0.7) == "below"

    def test_g3_diagnostic_is_undecided_at_n22(self):
        # 18/22 = 0.818, CI [0.615, 0.927] straddles 0.7 — cannot prove a pass
        assert bar_decidable(18, 22, bar=0.7) == "undecided"

    def test_barely_over_the_bar_is_undecided(self):
        assert bar_decidable(16, 22, bar=0.7) == "undecided"

    def test_large_n_can_decide_above(self):
        assert bar_decidable(230, 306, bar=0.7) == "above"
