"""
tests/test_public_authors_attribution.py — pure-function tests for the
impostor-calibrated attribution rule in validation/public_authors/run.py.

Why calibration is needed: deviation_score is z-normalized against each
candidate's OWN baseline_std (original/quantum/scoring.py:599), so the
raw deviations an essay earns against different candidate profiles sit
on incomparable scales. The candidate with the loosest baseline becomes
an argmin black hole that absorbs everyone else's essays. These tests
pin the calibration rule that fixes it: z = (dev - ref_mean) / ref_std
per candidate, where the reference distribution comes from scoring OTHER
authors' baseline documents against that candidate.

Pure math only — no HTTP, no corpus, no TestClient.
"""

from __future__ import annotations

import math

from validation.public_authors.run import calibrated_attribution, rank_of


class TestCalibratedAttribution:
    def test_black_hole_candidate_loses_after_calibration(self):
        """A candidate that scores EVERYONE low (loose baseline → low
        ref_mean) wins raw argmin, but calibration hands the essay to the
        true author, whose raw deviation is far below what impostors
        typically score against that author."""
        deviations = {"loose": 0.30, "true": 0.50, "other": 0.90}
        ref_stats = {
            # Impostors against "loose" average 0.32 — a 0.30 is ordinary.
            "loose": (0.32, 0.05),
            # Impostors against "true" average 0.95 — a 0.50 is 4.5σ low.
            "true": (0.95, 0.10),
            "other": (0.92, 0.10),
        }
        raw_argmin = min(deviations, key=deviations.get)
        assert raw_argmin == "loose"  # the defect this fix removes
        predicted, calibrated = calibrated_attribution(deviations, ref_stats)
        assert predicted == "true"
        assert calibrated["true"] < calibrated["loose"]

    def test_ref_std_floor_prevents_division_by_zero(self):
        """A degenerate zero-variance reference set must not divide by
        zero — ref_std is floored at 1e-6."""
        deviations = {"a": 0.5, "b": 0.6}
        ref_stats = {"a": (0.4, 0.0), "b": (0.9, 0.1)}
        predicted, calibrated = calibrated_attribution(deviations, ref_stats)
        for z in calibrated.values():
            assert math.isfinite(z)
        # (0.5 - 0.4) / 1e-6 = 1e5 for "a"; (0.6 - 0.9) / 0.1 = -3 for "b".
        assert predicted == "b"

    def test_rank_of_true_computed_from_calibrated_not_raw(self):
        """The reported rank must come from the calibrated scores: the
        true author ranks 2nd raw (behind the black hole) but 1st
        calibrated."""
        deviations = {"loose": 0.30, "true": 0.50, "other": 0.90}
        ref_stats = {
            "loose": (0.32, 0.05),
            "true": (0.95, 0.10),
            "other": (0.92, 0.10),
        }
        _, calibrated = calibrated_attribution(deviations, ref_stats)
        assert rank_of(deviations, "true") == 2
        assert rank_of(calibrated, "true") == 1

    def test_rank_of_returns_zero_for_absent_author(self):
        assert rank_of({"a": 0.1, "b": 0.2}, "missing") == 0
