"""
tests/context/test_genre_v2_rules.py — the abstaining genre resolver.

Task 2 of docs/superpowers/plans/2026-08-08-genre-resolution-v2.md.
"""
from __future__ import annotations

from original.constants import GENRE_UNKNOWN
from original.context import genre_v2


class TestAbstention:
    def test_ordinary_prose_abstains_rather_than_claiming_correspondence(self):
        """The whole point. v1 returns "correspondence" for this at a
        hardcoded 0.5 confidence; correspondence is rule 8's terminal else,
        not a positive class."""
        text = (
            "The argument proceeds by considering the nature of the good, and "
            "whether it can be known apart from its particular instances. "
            "Those who deny this must account for the evident agreement of "
            "ordinary language on the matter, which is not easily set aside. "
        ) * 6
        out = genre_v2.resolve(text)
        assert out["primary"] == GENRE_UNKNOWN
        assert out["confidence"] == 0.0

    def test_empty_text_abstains(self):
        out = genre_v2.resolve("")
        assert out["primary"] == GENRE_UNKNOWN
        assert out["confidence"] == 0.0

    def test_whitespace_only_abstains(self):
        assert genre_v2.resolve("   \n\t  ")["primary"] == GENRE_UNKNOWN

    def test_never_returns_correspondence_or_blog_post(self):
        """v2 has no corpus evidence for either, so it never claims them —
        they stay in GENRE_LABELS only for stored-value compatibility."""
        for text in ["", "short.", "The matter is settled. " * 40, "I think so. " * 40]:
            assert genre_v2.resolve(text)["primary"] not in ("correspondence", "blog_post")


class TestStructuredTemplate:
    def test_markup_is_recognised_at_full_confidence(self):
        text = "# Heading\n- first point\n- second point\n- third point\n1. step one\n"
        out = genre_v2.resolve(text)
        assert out["primary"] == "structured_template"
        assert out["confidence"] == genre_v2.MARKUP_CONFIDENCE

    def test_prose_with_one_stray_dash_is_not_structured(self):
        text = "This is ordinary prose about a subject. " * 20 + "\n- one bullet\n"
        assert genre_v2.resolve(text)["primary"] != "structured_template"


class TestCurlyQuoteFix:
    def test_typographic_quotes_are_recognised_as_dialogue(self):
        """v1's regex matched straight quotes only, so Gutenberg-sourced
        prose could never reach the creative_fiction branch — measured
        2026-08-08: Douglass 0% straight / 64% curly, Federalist 0% / 36%."""
        straight = 'He said, "we shall go at once," and turned away. ' * 12
        curly = "He said, “we shall go at once,” and turned away. " * 12
        assert genre_v2.dialogue_present(straight) is True
        assert genre_v2.dialogue_present(curly) is True

    def test_single_typographic_quotes_count_too(self):
        assert genre_v2.dialogue_present("She whispered ‘not yet’ and left.") is True

    def test_no_quotes_is_not_dialogue(self):
        assert genre_v2.dialogue_present("Plain prose without any quotation.") is False

    def test_empty_text_is_not_dialogue(self):
        assert genre_v2.dialogue_present("") is False


class TestContract:
    def test_returns_the_v1_key_shape(self):
        out = genre_v2.resolve("some text here")
        assert set(out) == {"primary", "confidence", "secondary"}

    def test_confidence_is_always_in_the_unit_interval(self):
        for text in ["", "# h\n- a\n- b\n", "Prose. " * 50, "He said, “no.” " * 20]:
            confidence = genre_v2.resolve(text)["confidence"]
            assert 0.0 <= confidence <= 1.0

    def test_every_emitted_label_is_a_known_label(self):
        from original.constants import GENRE_LABELS

        for text in ["", "# h\n- a\n- b\n", "Prose. " * 50, "He said, “no.” " * 20]:
            assert genre_v2.resolve(text)["primary"] in GENRE_LABELS
