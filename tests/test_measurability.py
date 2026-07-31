"""
tests/test_measurability.py — the measurability registry is the single
source of truth for which feature columns can carry corpus-sweep evidence.
"""
from __future__ import annotations

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
