"""
tests/context/test_genre_signals.py — the ten genre signals.

Task 9 of docs/superpowers/plans/2026-08-08-genre-resolution-v2.md.
"""

from __future__ import annotations

import math

from original.context import genre_v2


class TestSignalContract:
    def test_signal_order_is_a_fixed_ten(self):
        """The artifact pins this order; a silent reorder would feed the
        model shuffled columns."""
        assert genre_v2.SIGNAL_ORDER == (
            "raw_mean_sentence_length",
            "sentence_length_dispersion",
            "raw_first_person_ratio",
            "second_person_ratio",
            "dialogue_density",
            "citation_density",
            "raw_imperative_density",
            "signal_verb_rate",
            "question_rate",
            "mean_word_length",
        )

    def test_extract_returns_every_signal_finite(self):
        out = genre_v2.extract_signals("A sentence. Another sentence here. " * 20)
        assert set(out) == set(genre_v2.SIGNAL_ORDER)
        assert all(math.isfinite(v) for v in out.values())

    def test_empty_text_is_all_zeros_not_a_crash(self):
        out = genre_v2.extract_signals("")
        assert set(out) == set(genre_v2.SIGNAL_ORDER)
        assert all(v == 0.0 for v in out.values())

    def test_signals_are_not_pipeline_features(self):
        """ALL_FEATURE_CODES ordering is frozen. Genre signals are computed
        locally and must never leak into the feature vector."""
        from original.constants import ALL_FEATURE_CODES

        assert not (set(genre_v2.SIGNAL_ORDER) & set(ALL_FEATURE_CODES))


class TestSignalsDiscriminate:
    def test_dialogue_density_separates_narrative_from_exposition(self):
        narrative = 'He said, "we go now." She replied, "not yet." ' * 15
        exposition = "The argument depends upon the premise stated above. " * 15
        assert (
            genre_v2.extract_signals(narrative)["dialogue_density"]
            > genre_v2.extract_signals(exposition)["dialogue_density"]
        )

    def test_second_person_separates_address_from_description(self):
        address = "You must consider your own heart before you judge. " * 15
        description = "The heart of the matter is seldom considered at all. " * 15
        assert (
            genre_v2.extract_signals(address)["second_person_ratio"]
            > genre_v2.extract_signals(description)["second_person_ratio"]
        )

    def test_question_rate_separates_interrogative_prose(self):
        asking = "Why should it be so? Who can say? What follows from this? " * 12
        telling = "It is so. Nobody disputes it. Much follows from this. " * 12
        assert (
            genre_v2.extract_signals(asking)["question_rate"]
            > genre_v2.extract_signals(telling)["question_rate"]
        )

    def test_sentence_length_dispersion_is_zero_for_uniform_prose(self):
        uniform = "One two three four five. " * 20
        out = genre_v2.extract_signals(uniform)
        assert out["sentence_length_dispersion"] < 1.0

    def test_dispersion_rises_with_mixed_sentence_lengths(self):
        uniform = "One two three four five. " * 20
        mixed = ("Short. " + "A considerably longer sentence with many more words in it. ") * 10
        assert (
            genre_v2.extract_signals(mixed)["sentence_length_dispersion"]
            > genre_v2.extract_signals(uniform)["sentence_length_dispersion"]
        )
