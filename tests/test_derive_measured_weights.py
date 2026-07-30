"""tests/test_derive_measured_weights.py — author-level split + shrinkage-
regularized Fisher-ratio weight derivation (Phase 3)."""

from __future__ import annotations

from scripts.derive_measured_weights import shrink_within_author_variance, split_authors


class TestSplitAuthors:
    def test_split_is_deterministic_for_a_fixed_seed(self):
        authors = [f"author_{i}" for i in range(20)]
        a1, b1 = split_authors(authors, derivation_fraction=0.7, seed=1729)
        a2, b2 = split_authors(authors, derivation_fraction=0.7, seed=1729)
        assert a1 == a2
        assert b1 == b2

    def test_split_is_disjoint_and_covers_all_authors(self):
        authors = [f"author_{i}" for i in range(20)]
        derivation, gate = split_authors(authors, derivation_fraction=0.7, seed=1729)
        assert derivation.isdisjoint(gate)
        assert derivation | gate == set(authors)

    def test_split_fraction_is_approximately_respected(self):
        authors = [f"author_{i}" for i in range(100)]
        derivation, gate = split_authors(authors, derivation_fraction=0.7, seed=1729)
        assert 65 <= len(derivation) <= 75


class TestShrinkWithinAuthorVariance:
    def test_shrinkage_pulls_variance_toward_pooled_estimate(self):
        import numpy as np

        # One author with tiny within-author variance (an artifact of N=4
        # samples), pooled variance across all authors much larger.
        per_author_var = {"a": np.array([0.001, 0.001]), "b": np.array([0.5, 0.5])}
        shrunk = shrink_within_author_variance(per_author_var)
        assert shrunk["a"][0] > 0.001  # pulled up toward the pooled estimate
        assert shrunk["a"][0] < 0.5    # but not all the way

    def test_shrinkage_is_a_no_op_when_only_one_author(self):
        import numpy as np

        per_author_var = {"a": np.array([0.1, 0.2])}
        shrunk = shrink_within_author_variance(per_author_var)
        assert np.allclose(shrunk["a"], per_author_var["a"])
