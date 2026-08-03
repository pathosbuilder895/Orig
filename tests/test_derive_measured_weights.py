"""tests/test_derive_measured_weights.py — author-level split + honest,
degeneracy-guarded Fisher-ratio weight derivation (Phase 3, hardened).

Covers the reviewer-identified gaps in the first cut of
scripts/derive_measured_weights.py:
  1. structurally-unmeasurable features (tier-0 comparison, disabled feature
     groups) and empirically-constant columns must be excluded from the
     Fisher computation, not silently scored as F=0.
  2. within-author variance must be FLOORED at a low percentile, not
     "shrunk" toward a pooled mean that leaves the aggregate mean
     bit-identical (the original shrink_within_author_variance was inert
     for how its output was actually consumed).
  3. per-tier aggregation must use the MEDIAN across a tier's measurable
     features, not the mean, so one outlier feature can't set the tier.
  4. an author with < 2 windows must be dropped (with a loud warning), not
     silently contribute a zero within-author variance via ddof=0.
"""

from __future__ import annotations

import numpy as np
import pytest

from original.constants import (
    ALL_FEATURE_CODES,
    COMPARISON_CODES,
    DISABLED_FEATURE_GROUPS,
    FEATURE_DIM,
    FEATURE_GROUPS,
    FEATURE_TIER,
    TIER_WEIGHTS,
)
from scripts.derive_measured_weights import (
    compute_tier_weights_from_matrices,
    drop_short_authors,
    floor_within_variance,
    median_per_tier,
    print_tier_weights_diff,
    split_authors,
    structurally_excluded_codes,
    zero_variance_feature_indices,
)


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


class TestStructurallyExcludedCodes:
    def test_all_comparison_codes_are_excluded(self):
        excluded = structurally_excluded_codes()
        assert set(COMPARISON_CODES) <= excluded

    def test_every_currently_disabled_group_is_fully_excluded(self):
        excluded = structurally_excluded_codes()
        for group in DISABLED_FEATURE_GROUPS:
            assert set(FEATURE_GROUPS[group]) <= excluded

    def test_a_normal_enabled_feature_is_not_excluded(self):
        # type_token_ratio (tier 1) requires no baseline and is not in any
        # disabled group — must remain eligible for measurement.
        assert "type_token_ratio" not in structurally_excluded_codes()


class TestZeroVarianceFeatureIndices:
    def test_flags_a_column_constant_across_every_author_and_window(self):
        matrices = {
            "a": np.array([[1.0, 2.0, 5.0], [1.0, 2.0, 6.0]]),
            "b": np.array([[1.0, 3.0, 7.0], [1.0, 3.0, 8.0]]),
        }
        # column 0 is 1.0 everywhere -> zero pooled variance
        # column 1 differs BETWEEN authors (2 vs 3) -> nonzero pooled variance
        # column 2 varies throughout -> nonzero pooled variance
        assert zero_variance_feature_indices(matrices) == {0}

    def test_empty_matrices_yields_no_flagged_columns(self):
        assert zero_variance_feature_indices({}) == set()


class TestFloorWithinVariance:
    def test_near_zero_entry_is_raised_toward_the_floor(self):
        within = np.array([1e-8, 0.01, 0.02, 0.5, 1.0])
        floored = floor_within_variance(within, floor_percentile=10.0)
        assert floored[0] > within[0]
        assert floored[0] >= np.percentile(within[within > 0], 10.0)

    def test_values_already_above_the_floor_are_unchanged(self):
        within = np.array([1e-8, 0.01, 0.02, 0.5, 1.0])
        floored = floor_within_variance(within, floor_percentile=10.0)
        assert floored[-1] == within[-1]

    def test_all_zero_input_is_returned_unchanged_not_a_crash(self):
        within = np.zeros(4)
        floored = floor_within_variance(within, floor_percentile=10.0)
        assert np.array_equal(floored, within)

    def test_binding_floor_prevents_a_near_degenerate_denominator_from_dominating(self):
        # theological_register_score-style case: one feature's within-author
        # variance is ~3.5e-5 (an artifact of a tiny sample), the rest are
        # normal. Unmitigated, that feature's Fisher ratio explodes and would
        # dominate its tier's median/mean; floored, it must not.
        within_raw = np.array([3.5e-5, 0.01, 0.02, 0.05, 0.1])
        between = np.full(5, 0.01)
        raw_fisher = between / (within_raw + 1e-9)
        floored = floor_within_variance(within_raw, floor_percentile=10.0)
        floored_fisher = between / (floored + 1e-9)

        # unmitigated: dominates its tier by 2+ orders of magnitude
        assert raw_fisher[0] > 100 * np.median(raw_fisher[1:])
        # floored: back in the same order of magnitude as its peers
        assert floored_fisher[0] < 10 * np.median(floored_fisher[1:])


class TestDropShortAuthors:
    def test_drops_authors_below_the_window_floor(self):
        matrices = {
            "zero": np.zeros((0, 3)),
            "one": np.ones((1, 3)),
            "enough": np.ones((3, 3)),
        }
        kept = drop_short_authors(matrices, min_windows=2)
        assert set(kept) == {"enough"}

    def test_warns_loudly_on_every_dropped_author(self, capsys):
        matrices = {"zero": np.zeros((0, 3)), "one": np.ones((1, 3)), "enough": np.ones((3, 3))}
        drop_short_authors(matrices, min_windows=2)
        captured = capsys.readouterr()
        assert "zero" in captured.err
        assert "one" in captured.err


class TestMedianPerTier:
    def test_uses_median_not_mean_so_one_outlier_cannot_set_the_tier(self):
        per_tier_values = {3: [0.83, 0.90, 50.0]}  # one wild outlier, as observed for real T3
        result = median_per_tier(per_tier_values)
        assert result[3] == pytest.approx(0.90)
        assert result[3] < 17.0  # nowhere near the mean (~17.24)

    def test_drops_tiers_with_no_surviving_values(self):
        assert median_per_tier({5: []}) == {}


class TestComputeTierWeightsFromMatrices:
    @staticmethod
    def _base_matrices(n_authors=4, n_windows=6, seed=0):
        rng = np.random.default_rng(seed)
        matrices = {}
        for i in range(n_authors):
            mean = rng.uniform(0.3, 0.7, size=FEATURE_DIM)
            matrices[f"author_{i}"] = mean + rng.normal(0, 0.05, size=(n_windows, FEATURE_DIM))
        return matrices

    def test_comparison_and_disabled_group_tiers_are_kept_at_current_value(self):
        matrices = self._base_matrices()
        weights, diagnostics = compute_tier_weights_from_matrices(matrices)
        assert weights[0] == TIER_WEIGHTS[0]
        assert weights[17] == TIER_WEIGHTS[17]
        assert weights[18] == TIER_WEIGHTS[18]
        assert {0, 17, 18} <= set(diagnostics["kept_tiers"])

    def test_kept_tier_reason_is_recorded_for_every_member_feature(self):
        matrices = self._base_matrices()
        _, diagnostics = compute_tier_weights_from_matrices(matrices)
        for code in COMPARISON_CODES:
            assert code in diagnostics["excluded_features"]

    def test_constant_column_is_excluded_and_its_tier_still_measured(self):
        matrices = self._base_matrices()
        # Force one real, currently-enabled tier-1 feature constant across
        # every window of every author.
        code = next(c for c in ALL_FEATURE_CODES if FEATURE_TIER[c] == 1)
        idx = ALL_FEATURE_CODES.index(code)
        for m in matrices.values():
            m[:, idx] = 0.42
        weights, diagnostics = compute_tier_weights_from_matrices(matrices)
        assert code in diagnostics["excluded_features"]
        assert 1 not in diagnostics["kept_tiers"]  # tier 1 has other measurable features
        assert 1 in weights

    def test_author_with_one_window_is_dropped_not_silently_zeroed(self):
        matrices = self._base_matrices(n_authors=4, n_windows=6)
        rng = np.random.default_rng(99)
        matrices["short"] = rng.normal(0.5, 0.05, size=(1, FEATURE_DIM))
        _, diagnostics = compute_tier_weights_from_matrices(matrices)
        assert "short" in diagnostics["dropped_authors"]
        assert "short" not in diagnostics["window_counts_used"]

    def test_raises_when_fewer_than_two_authors_survive_the_window_floor(self):
        matrices = {"only_one": np.random.default_rng(0).normal(0.5, 0.05, size=(6, FEATURE_DIM))}
        with pytest.raises(RuntimeError):
            compute_tier_weights_from_matrices(matrices)

    def test_sigma_w_squared_is_preserved_over_the_measured_subset_only(self):
        matrices = self._base_matrices()
        weights, diagnostics = compute_tier_weights_from_matrices(matrices)
        measured_tiers = set(TIER_WEIGHTS) - set(diagnostics["kept_tiers"])
        current_sq_sum = sum(TIER_WEIGHTS[t] ** 2 for t in measured_tiers)
        new_sq_sum = sum(weights[t] ** 2 for t in measured_tiers)
        assert new_sq_sum == pytest.approx(current_sq_sum, rel=1e-6)


class TestSingleSurvivorAnnotation:
    """
    Tiers 9 and 10 each have exactly 2 member codes today, and one of each
    pair (argument_sequence_likelihood, semantic_centroid_proximity) is a
    comparison-shaped feature that's constant through this pipeline — so
    both tiers routinely end up with exactly ONE surviving measured
    feature. A "median" of one value is a single-feature bet, not tier-
    level evidence, and must be flagged as such rather than presented
    identically to a tier with many surviving features agreeing.
    """

    @staticmethod
    def _matrices_with_single_survivor_tiers(n_authors=4, n_windows=6, seed=0):
        rng = np.random.default_rng(seed)
        matrices = {}
        for i in range(n_authors):
            mean = rng.uniform(0.3, 0.7, size=FEATURE_DIM)
            matrices[f"author_{i}"] = mean + rng.normal(0, 0.05, size=(n_windows, FEATURE_DIM))
        # Force the "comparison-shaped" half of tiers 9 and 10 constant, as
        # they are for real (see stderr of a real run) — leaving exactly
        # one surviving feature in each tier.
        for code in ("argument_sequence_likelihood", "semantic_centroid_proximity"):
            idx = ALL_FEATURE_CODES.index(code)
            for m in matrices.values():
                m[:, idx] = 0.5
        return matrices

    def test_diagnostics_expose_surviving_feature_counts_per_tier(self):
        matrices = self._matrices_with_single_survivor_tiers()
        _, diagnostics = compute_tier_weights_from_matrices(matrices)
        assert diagnostics["tier_feature_counts"][9] == 1
        assert diagnostics["tier_feature_counts"][10] == 1
        # A tier with several surviving features is not flagged as a single-survivor.
        assert diagnostics["tier_feature_counts"].get(1, 0) > 1

    def test_single_survivor_tiers_are_named_in_diagnostics(self):
        matrices = self._matrices_with_single_survivor_tiers()
        _, diagnostics = compute_tier_weights_from_matrices(matrices)
        assert diagnostics["single_survivor_tiers"][9] == "structural_centrist_penalty"
        assert diagnostics["single_survivor_tiers"][10] == "semantic_field_dispersion"
        assert 1 not in diagnostics["single_survivor_tiers"]

    def test_printed_block_annotates_single_survivor_tiers_as_weak_evidence(self, capsys):
        matrices = self._matrices_with_single_survivor_tiers()
        weights, diagnostics = compute_tier_weights_from_matrices(matrices)
        print_tier_weights_diff(weights, diagnostics)
        captured = capsys.readouterr()
        assert "single surviving feature: structural_centrist_penalty" in captured.out
        assert "single surviving feature: semantic_field_dispersion" in captured.out
        assert "weak evidence" in captured.out


class TestVerboseFlag:
    @staticmethod
    def _base_matrices(n_authors=4, n_windows=6, seed=0):
        rng = np.random.default_rng(seed)
        matrices = {}
        for i in range(n_authors):
            mean = rng.uniform(0.3, 0.7, size=FEATURE_DIM)
            matrices[f"author_{i}"] = mean + rng.normal(0, 0.05, size=(n_windows, FEATURE_DIM))
        return matrices

    def test_verbose_false_emits_nothing_on_stdout_or_stderr(self, capsys):
        matrices = self._base_matrices()
        compute_tier_weights_from_matrices(matrices, verbose=False)
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_verbose_true_default_still_emits_progress(self, capsys):
        matrices = self._base_matrices()
        compute_tier_weights_from_matrices(matrices)
        captured = capsys.readouterr()
        assert captured.err != ""

    def test_drop_short_authors_verbose_false_is_silent(self, capsys):
        matrices = {"zero": np.zeros((0, 3)), "enough": np.ones((3, 3))}
        drop_short_authors(matrices, min_windows=2, verbose=False)
        captured = capsys.readouterr()
        assert captured.err == ""
