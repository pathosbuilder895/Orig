"""
tests/test_measurability.py — the measurability registry is the single
source of truth for which feature columns can carry corpus-sweep evidence.
"""
from __future__ import annotations

import numpy as np
import pytest

from original.constants import (
    ALL_FEATURE_CODES,
    COMPARISON_CODES,
    MUSICAL_COMPARISON_CODES,
    TIER1_CODES,
    TIER16_CODES,
    TIER17_CODES,
    TIER18_CODES,
)
from validation.measurability import (
    MeasurabilityError,
    MeasurabilityStatus,
    assert_aggregatable,
    disabled_feature_indices,
    measurable_codes,
    measurable_indices,
    status,
    structurally_excluded_codes,
)


class TestStatus:
    def test_every_feature_code_has_a_status(self):
        for code in ALL_FEATURE_CODES:
            assert isinstance(status(code), MeasurabilityStatus)

    def test_unknown_code_raises(self):
        with pytest.raises(KeyError):
            status("not_a_feature")

    def test_comparison_codes_are_scoring_only(self):
        for code in list(COMPARISON_CODES) + list(MUSICAL_COMPARISON_CODES):
            assert status(code) is MeasurabilityStatus.SCORING_ONLY

    def test_catastrophe_index_is_structurally_blank(self):
        assert status("catastrophe_index") is MeasurabilityStatus.STRUCTURALLY_BLANK

    def test_disabled_groups_tracked_live_from_constants(self):
        # tier 17 (behavioral) and tier 18 (uniformity) are in
        # DISABLED_FEATURE_GROUPS today; DISABLED must outrank every
        # other status for those codes.
        for code in TIER17_CODES + TIER18_CODES:
            assert status(code) is MeasurabilityStatus.DISABLED

    def test_tier16_corpus_limited_on_non_academic_corpora(self):
        for code in TIER16_CODES:
            assert status(code, corpus="plato") is MeasurabilityStatus.CORPUS_LIMITED
            assert status(code, corpus="public_authors") is MeasurabilityStatus.CORPUS_LIMITED
            # seminary essays DO contain citation behavior
            assert status(code, corpus="seminary") is MeasurabilityStatus.MEASURABLE
            assert status(code) is MeasurabilityStatus.MEASURABLE

    def test_surface_stylometrics_measurable(self):
        for code in TIER1_CODES:
            assert status(code) is MeasurabilityStatus.MEASURABLE


class TestDerivedSets:
    def test_measurable_codes_excludes_all_non_measurable(self):
        codes = set(measurable_codes())
        assert codes.isdisjoint(structurally_excluded_codes())

    def test_measurable_indices_parallel_to_all_feature_codes(self):
        idx = measurable_indices()
        assert [ALL_FEATURE_CODES[i] for i in idx] == measurable_codes()

    def test_corpus_argument_shrinks_the_measurable_set(self):
        assert set(measurable_codes("plato")) == set(measurable_codes()) - set(TIER16_CODES)

    def test_disabled_indices_cover_tier17_and_18(self):
        codes = {ALL_FEATURE_CODES[i] for i in disabled_feature_indices()}
        assert codes == set(TIER17_CODES) | set(TIER18_CODES)


class TestAssertAggregatable:
    def test_accepts_measurable(self):
        assert_aggregatable(TIER1_CODES)  # no raise

    def test_refuses_scoring_only_and_names_offenders(self):
        with pytest.raises(MeasurabilityError) as exc:
            assert_aggregatable(TIER1_CODES + list(COMPARISON_CODES))
        for code in COMPARISON_CODES:
            assert code in str(exc.value)
        assert "scoring_only" in str(exc.value)

    def test_refuses_corpus_limited_on_named_corpus(self):
        with pytest.raises(MeasurabilityError):
            assert_aggregatable(TIER16_CODES, corpus="plato")


def _fixture_author_texts() -> dict[str, str]:
    """
    Two deliberately style-distinct ~500-word texts (2 windows each at
    length=250). Constant columns are judged on POOLED variance across all
    4 windows, so cross-author style differences are what matters.
    """
    plain = (
        "Go go go. I go. You go. He go. She go. We go. They go. "
        "Run run run. I run. You run. He run. She run. We run. They run. "
        "Walk walk walk. I walk. You walk. He walk. She walk. We walk. They walk. "
        "Stop stop. I stop. You stop. He stop. She stop. We stop. They stop. "
        "Go stop go. Run walk run. Stop go stop. "
        "I am. You are. He is. She is. We are. They are. "
        "One two three. A B C. X Y Z. "
        "No no no. Yes yes yes. Maybe maybe. "
        "I do I do. You do you do. He do he do. "
        "Bad bad bad. Good good. Good bad. Bad good. "
    )
    ornate = (
        "Whosoever contemplates the manifold operations of providence whilst "
        "observing, as it were, the intricate concatenation of causes and "
        "consequences that governs our mortal estate must thereby confess, "
        "with no inconsiderable astonishment, that the arrangement of human "
        "affairs surpasses our impoverished understanding; for what philosopher, "
        "however sagacious and circumspect, has ever successfully circumscribed "
        "the boundless reach of cosmic determinism? "
        "The phenomenological manifestations of such extraordinarily verisimilitudinous "
        "systems, notwithstanding their deceptive superficial appearance of rigid "
        "computational determinism, were demonstrably possessed of a profoundly "
        "subtle epistemological complexity that belied all simplistic categorization. "
        "Erstwhile antiquated methodologies, characterized perpetually by their "
        "reductive tendencies and foundational ontological presuppositions, have "
        "consistently and demonstrably failed to encompass the multifarious dimensions "
        "inherent within such intricate natural phenomena under examination. "
        "Furthermore and moreover, one must necessarily acknowledge the considerable "
        "limitations that remain perpetually inherent in our circumscribed parochial "
        "understanding of universal principles; indeed, the tortuous circumlocutory "
        "nature of contemporary philosophical discourse tends characteristically toward "
        "deliberate obfuscation rather than genuine illumination. "
    )
    return {"plain": plain * 10, "ornate": ornate * 7}


class TestRegistryMatchesPipelineReality:
    """The declared statuses must agree with what extraction actually does."""

    @classmethod
    def setup_class(cls):
        from validation.stability.stability import compute_feature_matrix

        matrices = compute_feature_matrix(_fixture_author_texts(), length=250)
        cls.pooled = np.vstack([m for m in matrices.values() if m.shape[0] > 0])

    def test_every_structurally_excluded_code_is_constant_in_extraction(self):
        variances = self.pooled.var(axis=0)
        broken = [
            code
            for i, code in enumerate(ALL_FEATURE_CODES)
            if code in structurally_excluded_codes() and variances[i] > 1e-12
        ]
        # If this fires, a declared-blank feature started varying — the
        # registry is stale and MUST be updated (good news, not noise).
        assert broken == [], f"declared-blank features now vary: {broken}"

    def test_surface_stylometrics_actually_vary(self):
        variances = self.pooled.var(axis=0)
        constant_t1 = [
            code
            for i, code in enumerate(ALL_FEATURE_CODES)
            if code in TIER1_CODES and variances[i] <= 1e-12
        ]
        assert constant_t1 == [], f"tier-1 features constant on distinct styles: {constant_t1}"

    def test_most_measurable_features_vary_on_distinct_styles(self):
        variances = self.pooled.var(axis=0)
        measurable = set(measurable_codes())
        varying = sum(
            1
            for i, code in enumerate(ALL_FEATURE_CODES)
            if code in measurable and variances[i] > 1e-12
        )
        # Not all measurable codes fire on a 500-word citation-free fixture
        # (e.g. chiasmus, block quotes) — 60% is the canary floor, not a claim.
        assert varying >= 0.6 * len(measurable)
