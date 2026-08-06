"""
tests/quantum/test_typicality.py — pure conformal typicality math.

Mirrors tests/quantum/test_conformal.py's style: deterministic example-based
tests with inline algebra justifying the expected numeric value, no fixtures.
"""

from __future__ import annotations

from original.quantum.typicality import band_from_p, p_central, p_far


class TestPFar:
    def test_typical_sample_gives_p_far_near_half(self):
        """r_sub at the exact median of 9 LOO distances → p_far = 6/10 = 0.6."""
        loo = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
        # r_sub = 5.0 has 5 values >= 5.0: {5.0, 6.0, 7.0, 8.0, 9.0}, so (1+5)/10 = 6/10
        assert p_far(5.0, loo) == 6 / 10

    def test_extreme_far_sample_gives_minimum_p_far(self):
        """r_sub larger than every LOO distance → p_far = 1/(N+1), the floor."""
        loo = [1.0, 2.0, 3.0]
        assert p_far(100.0, loo) == 1 / 4

    def test_extreme_central_sample_gives_maximum_p_far(self):
        """r_sub smaller than every LOO distance → p_far = (N+1)/(N+1) = 1.0."""
        loo = [1.0, 2.0, 3.0]
        assert p_far(0.0, loo) == 1.0

    def test_empty_loo_distances_raises(self):
        import pytest

        with pytest.raises(ValueError):
            p_far(1.0, [])


class TestPCentral:
    def test_typical_sample_gives_p_central_near_half(self):
        loo = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
        # r_sub = 5.0 has 5 values <= 5.0: {1.0, 2.0, 3.0, 4.0, 5.0}, so (1+5)/10 = 6/10
        assert p_central(5.0, loo) == 6 / 10

    def test_extreme_central_sample_gives_minimum_p_central(self):
        """r_sub smaller than every LOO distance → p_central = 1/(N+1), the floor."""
        loo = [1.0, 2.0, 3.0]
        assert p_central(0.0, loo) == 1 / 4

    def test_extreme_far_sample_gives_maximum_p_central(self):
        loo = [1.0, 2.0, 3.0]
        assert p_central(100.0, loo) == 1.0

    def test_p_far_and_p_central_are_complementary_at_extremes(self):
        """A point that is rank-1-farthest has p_far at the floor and
        p_central at the ceiling, and vice versa for rank-1-closest."""
        loo = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert p_far(100.0, loo) == 1 / 6
        assert p_central(100.0, loo) == 6 / 6
        assert p_far(-100.0, loo) == 6 / 6
        assert p_central(-100.0, loo) == 1 / 6


class TestBandFromP:
    def test_typical_is_no_action(self):
        assert band_from_p(p_far=0.5, p_central=0.5) == "no_action"

    def test_mild_drift_is_monitor(self):
        assert band_from_p(p_far=0.02, p_central=0.5) == "monitor"

    def test_moderate_drift_is_schedule_conversation(self):
        assert band_from_p(p_far=0.008, p_central=0.5) == "schedule_conversation"

    def test_strong_drift_is_escalate(self):
        assert band_from_p(p_far=0.001, p_central=0.5) == "escalate"

    def test_too_central_is_schedule_conversation(self):
        assert band_from_p(p_far=0.5, p_central=0.01) == "schedule_conversation"

    def test_no_action_boundary_is_inclusive_of_far_side(self):
        """p_far exactly at .03 is NOT > .03, so it must not be no_action."""
        assert band_from_p(p_far=0.03, p_central=0.5) != "no_action"

    def test_no_action_boundary_is_inclusive_of_central_side(self):
        assert band_from_p(p_far=0.5, p_central=0.02) != "no_action"
