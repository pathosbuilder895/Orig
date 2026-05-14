"""
tests/quantum/test_conformal.py — Unit tests for the conformal prediction module.
"""

from __future__ import annotations

import pytest

from original.quantum.conformal import (
    asymmetric_threshold,
    conformal_pvalue,
    verdict_from_pvalue,
)


# ── conformal_pvalue ──────────────────────────────────────────────────────────

class TestConformalPvalue:
    def test_empty_calibration_returns_half(self):
        """No calibration data → neutral p-value 0.5."""
        assert conformal_pvalue(0.5, []) == 0.5

    def test_all_calibration_above_query_returns_zero(self):
        """All calibration fidelities > query → p-value = 0/(n+1) = 0."""
        cal = [0.8, 0.9, 0.95]
        p = conformal_pvalue(0.1, cal)
        assert p == 0.0  # 0 calibration scores ≤ 0.1

    def test_all_calibration_below_query_returns_near_one(self):
        """All calibration fidelities ≤ query → p-value = n/(n+1)."""
        cal = [0.1, 0.2, 0.3]
        p = conformal_pvalue(0.9, cal)
        expected = 3 / (3 + 1)
        assert abs(p - expected) < 1e-9

    def test_half_below_half_above(self):
        """Exactly half the calibration is ≤ query."""
        cal = [0.2, 0.4, 0.6, 0.8]   # 4 values
        # query = 0.5 → 2 values ≤ 0.5 (0.2, 0.4)
        p = conformal_pvalue(0.5, cal)
        expected = 2 / (4 + 1)
        assert abs(p - expected) < 1e-9

    def test_single_calibration_point(self):
        """Edge case: calibration set of size 1."""
        # query > cal[0] → 1 ≤ query → p = 1/(1+1) = 0.5
        assert abs(conformal_pvalue(0.8, [0.5]) - 0.5) < 1e-9
        # query < cal[0] → 0 ≤ query → p = 0
        assert conformal_pvalue(0.2, [0.5]) == 0.0

    def test_bounded(self):
        """p-value is always in [0, 1]."""
        import random
        rng = random.Random(42)
        for _ in range(50):
            cal = [rng.random() for _ in range(rng.randint(1, 20))]
            query = rng.random()
            p = conformal_pvalue(query, cal)
            assert 0.0 <= p <= 1.0

    def test_monotone_in_fidelity(self):
        """Higher fidelity (more authentic) → higher p-value (less suspicious)."""
        cal = [0.3, 0.5, 0.7, 0.9]
        p_low = conformal_pvalue(0.1, cal)
        p_high = conformal_pvalue(0.95, cal)
        assert p_low <= p_high


# ── verdict_from_pvalue ───────────────────────────────────────────────────────

class TestVerdictFromPvalue:
    def test_high_p_no_action(self):
        assert verdict_from_pvalue(0.5) == "no_action"
        assert verdict_from_pvalue(1.0) == "no_action"
        assert verdict_from_pvalue(0.20) == "no_action"

    def test_low_p_monitor(self):
        assert verdict_from_pvalue(0.15) == "monitor"
        assert verdict_from_pvalue(0.10) == "monitor"

    def test_very_low_p_schedule(self):
        assert verdict_from_pvalue(0.03) == "schedule_conversation"

    def test_extremely_low_p_escalate(self):
        assert verdict_from_pvalue(0.005) == "escalate"
        assert verdict_from_pvalue(0.0) == "escalate"

    def test_custom_thresholds(self):
        # Strict: only escalate at p < 0.001
        assert verdict_from_pvalue(0.005, alpha_escalate=0.001) == "schedule_conversation"
        assert verdict_from_pvalue(0.0005, alpha_escalate=0.001) == "escalate"

    def test_boundary_values(self):
        """Values exactly at thresholds use strict inequality (< not <=)."""
        # p == alpha_monitor (0.20) → no_action (not monitor)
        assert verdict_from_pvalue(0.20) == "no_action"
        # p == alpha_escalate (0.01) → schedule_conversation (not escalate)
        assert verdict_from_pvalue(0.01) == "schedule_conversation"


# ── asymmetric_threshold ──────────────────────────────────────────────────────

class TestAsymmetricThreshold:
    def test_equal_costs_gives_half(self):
        """Equal FP and FN costs → threshold = 0.5."""
        assert abs(asymmetric_threshold(1.0, 1.0) - 0.5) < 1e-9

    def test_high_fn_cost_gives_high_threshold(self):
        """Missing ghostwriting (FN) is much worse → high threshold (escalate more)."""
        alpha = asymmetric_threshold(cost_fp=1.0, cost_fn=9.0)
        assert abs(alpha - 0.1) < 1e-9

    def test_high_fp_cost_gives_low_threshold(self):
        """False accusation (FP) is much worse → low threshold (escalate less)."""
        alpha = asymmetric_threshold(cost_fp=9.0, cost_fn=1.0)
        assert abs(alpha - 0.9) < 1e-9

    def test_zero_both_gives_default(self):
        """Degenerate zero costs → default 0.05."""
        alpha = asymmetric_threshold(0.0, 0.0)
        assert abs(alpha - 0.05) < 1e-9

    def test_bounded(self):
        """Result always in (0, 1)."""
        import random
        rng = random.Random(0)
        for _ in range(20):
            fp = rng.uniform(0.01, 10.0)
            fn = rng.uniform(0.01, 10.0)
            alpha = asymmetric_threshold(fp, fn)
            assert 0.0 < alpha < 1.0
