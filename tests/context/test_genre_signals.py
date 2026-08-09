"""
tests/context/test_genre_signals.py — the ten genre signals.

Task 9 of docs/superpowers/plans/2026-08-08-genre-resolution-v2.md.
"""

from __future__ import annotations

import math

from original.context import genre_v2


class TestSignalContract:
    def test_signal_order_is_fixed(self):
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
            "past_tense_ratio",
            "modal_verb_rate",
            "argumentative_connective_rate",
            "narrative_connective_rate",
            "abstract_noun_ratio",
            "proper_noun_rate",
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


class TestArgumentVersusNarrationSignals:
    """The codebook's deciding test between personal_essay and
    scholarly_essay is "is the first person doing argumentative work or
    autobiographical work?" — a distinction first-person RATIO cannot make.
    Measured on the derivation split it separated those classes at only 1.0
    pooled SD (0.413 vs 0.278), which is why they were confused. These six
    signals operationalise the distinction the codebook actually draws."""

    def test_past_tense_marks_narrative(self):
        narrative = "He walked to the river and looked at the water he had crossed. " * 12
        argument = "The claim requires evidence, and the evidence is not available. " * 12
        assert (
            genre_v2.extract_signals(narrative)["past_tense_ratio"]
            > genre_v2.extract_signals(argument)["past_tense_ratio"]
        )

    def test_modal_verbs_mark_argument(self):
        argument = "One must concede the point, and it ought to be granted freely. " * 12
        narrative = "He walked out and closed the door behind him quietly. " * 12
        assert (
            genre_v2.extract_signals(argument)["modal_verb_rate"]
            > genre_v2.extract_signals(narrative)["modal_verb_rate"]
        )

    def test_argumentative_connectives_mark_argument(self):
        argument = "Therefore the case fails. However, moreover, consequently it stands. " * 12
        narrative = "He rose early. He ate. He left the house before dawn. " * 12
        assert (
            genre_v2.extract_signals(argument)["argumentative_connective_rate"]
            > genre_v2.extract_signals(narrative)["argumentative_connective_rate"]
        )

    def test_narrative_connectives_mark_narration(self):
        narrative = "Then he left. Afterwards she followed. Suddenly it began to rain. " * 12
        argument = "The principle holds, and the objection does not defeat it. " * 12
        assert (
            genre_v2.extract_signals(narrative)["narrative_connective_rate"]
            > genre_v2.extract_signals(argument)["narrative_connective_rate"]
        )

    def test_abstract_nouns_mark_exposition(self):
        abstract = "The justification of liberty requires attention to necessity. " * 12
        concrete = "The dog ran past the gate and into the wet field. " * 12
        assert (
            genre_v2.extract_signals(abstract)["abstract_noun_ratio"]
            > genre_v2.extract_signals(concrete)["abstract_noun_ratio"]
        )

    def test_proper_nouns_mark_peopled_narrative(self):
        peopled = "Elizabeth met Darcy near Pemberley, and Jane followed with Bingley soon. " * 12
        abstract = "The argument met the objection near the point, and it followed soon. " * 12
        assert (
            genre_v2.extract_signals(peopled)["proper_noun_rate"]
            > genre_v2.extract_signals(abstract)["proper_noun_rate"]
        )

    def test_all_new_signals_are_in_the_order(self):
        for name in (
            "past_tense_ratio",
            "modal_verb_rate",
            "argumentative_connective_rate",
            "narrative_connective_rate",
            "abstract_noun_ratio",
            "proper_noun_rate",
        ):
            assert name in genre_v2.SIGNAL_ORDER
