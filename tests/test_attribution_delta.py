"""
tests/test_attribution_delta.py — distance-based attribution engines.

The raw argmin of per-author z-scores let the author with the loosest
baseline absorb 11 of 12 misattributions (Instrument Report). These
engines normalize at POOL level, so per-author variance scales cannot
create a black hole — the scale-invariance tests below pin exactly that
property.
"""
from __future__ import annotations

import numpy as np
import pytest

from validation.attribution.delta import cosine_delta_attribution


def _matrices():
    rng = np.random.default_rng(1729)
    # Three authors with distinct 6-dim signatures, 5 baseline docs each.
    centers = {
        "alpha": np.array([0.2, 0.8, 0.4, 0.6, 0.3, 0.7]),
        "beta": np.array([0.7, 0.2, 0.6, 0.3, 0.8, 0.2]),
        "gamma": np.array([0.5, 0.5, 0.9, 0.1, 0.5, 0.5]),
    }
    return {
        a: c + rng.normal(0, 0.02, size=(5, 6)) for a, c in centers.items()
    }, centers


class TestCosineDelta:
    def test_recovers_true_author(self):
        matrices, centers = _matrices()
        for author, center in centers.items():
            test_vec = center + 0.01
            predicted, dists = cosine_delta_attribution(
                matrices, test_vec, feature_indices=list(range(6))
            )
            assert predicted == author
            assert set(dists) == set(centers)

    def test_loose_baseline_cannot_become_a_black_hole(self):
        # Inflate ONE author's within-baseline spread 50x. Under the old
        # own-z argmin this makes them absorb everything; pool-level
        # normalization must not care about within-author spread.
        matrices, centers = _matrices()
        rng = np.random.default_rng(7)
        matrices["gamma"] = centers["gamma"] + rng.normal(0, 1.0, size=(5, 6))
        test_vec = centers["alpha"] + 0.01
        predicted, _ = cosine_delta_attribution(
            matrices, test_vec, feature_indices=list(range(6))
        )
        assert predicted == "alpha"

    def test_restricts_to_given_feature_indices(self):
        matrices, centers = _matrices()
        # Make dims 3..5 pure noise for the test vector; dims 0..2 decide.
        test_vec = np.concatenate([centers["beta"][:3], np.array([9.0, 9.0, 9.0])])
        predicted, _ = cosine_delta_attribution(
            matrices, test_vec, feature_indices=[0, 1, 2]
        )
        assert predicted == "beta"

    def test_empty_author_matrix_is_skipped(self):
        matrices, centers = _matrices()
        matrices["empty"] = np.zeros((0, 6))
        predicted, dists = cosine_delta_attribution(
            matrices, centers["alpha"], feature_indices=list(range(6))
        )
        assert "empty" not in dists and predicted == "alpha"

    def test_fewer_than_two_authors_raises(self):
        matrices, centers = _matrices()
        with pytest.raises(ValueError):
            cosine_delta_attribution(
                {"alpha": matrices["alpha"]}, centers["alpha"], list(range(6))
            )

    def test_empty_feature_indices_raises(self):
        # No feature columns selected must fail loudly instead of returning
        # the alphabetically-first author on an all-1.0 distance dict.
        matrices, centers = _matrices()
        with pytest.raises(ValueError):
            cosine_delta_attribution(matrices, centers["alpha"], feature_indices=[])

    def test_non_finite_test_vector_raises(self):
        matrices, centers = _matrices()
        test_vec = centers["alpha"].copy()
        test_vec[2] = np.nan
        with pytest.raises(ValueError):
            cosine_delta_attribution(
                matrices, test_vec, feature_indices=list(range(6))
            )

    def test_non_finite_baseline_row_raises_and_names_author(self):
        matrices, centers = _matrices()
        matrices["gamma"] = matrices["gamma"].copy()
        matrices["gamma"][1, 3] = np.inf
        with pytest.raises(ValueError, match="gamma"):
            cosine_delta_attribution(
                matrices, centers["alpha"], feature_indices=list(range(6))
            )

    def test_non_finite_in_unselected_column_does_not_raise(self):
        # A NaN in a column nobody selected must not block a valid
        # attribution — validation is restricted to the selected columns.
        matrices, centers = _matrices()
        matrices["gamma"] = matrices["gamma"].copy()
        matrices["gamma"][1, 5] = np.nan  # column 5 excluded below
        test_vec = np.concatenate([centers["beta"][:5], np.array([9.0])])
        predicted, dists = cosine_delta_attribution(
            matrices, test_vec, feature_indices=[0, 1, 2, 3, 4]
        )
        assert predicted == "beta"
        assert set(dists) == set(centers)

    def test_single_row_baseline_matrix_attributes_correctly(self):
        matrices, centers = _matrices()
        matrices["alpha"] = centers["alpha"].reshape(1, -1)
        matrices["beta"] = centers["beta"].reshape(1, -1)
        matrices["gamma"] = centers["gamma"].reshape(1, -1)
        test_vec = centers["beta"] + 0.01
        predicted, dists = cosine_delta_attribution(
            matrices, test_vec, feature_indices=list(range(6))
        )
        assert predicted == "beta"
        assert set(dists) == set(centers)
