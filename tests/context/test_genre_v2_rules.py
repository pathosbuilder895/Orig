"""
tests/context/test_genre_v2_rules.py — the abstaining genre resolver.

Task 2 of docs/superpowers/plans/2026-08-08-genre-resolution-v2.md.
"""

from __future__ import annotations

from collections import Counter

from original.constants import GENRE_UNKNOWN
from original.context import genre_v2
from original.features.preprocess import CitationData


class TestAbstention:
    def test_the_rule_tree_abstains_on_empty_text_directly(self):
        """`_resolve_by_rules` has its own empty-text guard, independent of
        the one in `resolve`/`predict` — exercised here by calling it
        directly rather than through `resolve`."""
        out = genre_v2._resolve_by_rules("")
        assert out["primary"] == GENRE_UNKNOWN
        assert out["confidence"] == 0.0

    def test_the_rule_tree_abstains_on_ordinary_prose(self):
        """The Stage 1 contract, asserted against the rule tree directly.
        v1 returns "correspondence" for this at a hardcoded 0.5 confidence;
        correspondence is rule 8's terminal else, not a positive class.

        `resolve` no longer abstains here — Stage 2's model classifies it —
        so the rule-level property is tested where it still lives."""
        text = (
            "The argument proceeds by considering the nature of the good, and "
            "whether it can be known apart from its particular instances. "
            "Those who deny this must account for the evident agreement of "
            "ordinary language on the matter, which is not easily set aside. "
        ) * 6
        out = genre_v2._resolve_by_rules(text)
        assert out["primary"] == GENRE_UNKNOWN
        assert out["confidence"] == 0.0

    def test_the_model_claims_a_real_class_where_the_rules_gave_up(self):
        """Stage 2's whole purpose: the rules abstain on ordinary expository
        prose, the model recognises it."""
        text = (
            "The argument proceeds by considering the nature of the good, and "
            "whether it can be known apart from its particular instances. "
            "Those who deny this must account for the evident agreement of "
            "ordinary language on the matter, which is not easily set aside. "
        ) * 6
        assert genre_v2._resolve_by_rules(text)["primary"] == GENRE_UNKNOWN
        out = genre_v2.resolve(text)
        assert out["primary"] != GENRE_UNKNOWN
        assert out["confidence"] >= genre_v2._confidence_min()

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

    def test_the_rule_tree_short_circuits_on_markup_directly(self):
        """`_resolve_by_rules` runs the markup check itself, ahead of the
        signal-verb/citation branches below it — exercised directly rather
        than through `resolve`, which never reaches the rule tree at all."""
        text = "# Heading\n- first point\n- second point\n- third point\n1. step one\n"
        out = genre_v2._resolve_by_rules(text)
        assert out["primary"] == "structured_template"
        assert out["confidence"] == genre_v2.MARKUP_CONFIDENCE


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


class TestRuleArmsFireOnEngineeredSignals:
    """v1 was measured to starve four of these branches entirely (signal-verb
    count and imperative density sit at a median of 0 on every real corpus,
    academic and oratory alike), so the corpora this suite otherwise draws on
    never drive them. Each test supplies an explicit ``citation_data`` —
    exercising the "caller already computed it" branch of `_resolve_by_rules`
    (`citation_data is not None`, skipping `preprocess`) as a side effect —
    so citation/signal-verb counts are pinned exactly rather than hoped for
    from prose, while sentence length and pronoun choice in the text control
    the remaining thresholds."""

    def test_academic_exegesis_arm(self):
        text = (
            "This extended expository sentence intentionally contains more "
            "than twenty separate tokens so that the mean sentence length "
            "threshold for the academic rule is comfortably exceeded. "
        ) * 8
        citation_data = CitationData(
            paren_citation_count=20, signal_verb_counts=Counter({"argues": 3})
        )
        out = genre_v2._resolve_by_rules(text, citation_data=citation_data)
        assert out == {
            "primary": "academic_exegesis",
            "confidence": genre_v2.RULE_CONFIDENCE,
            "secondary": None,
        }

    def test_scholarly_essay_arm(self):
        """Citation density clears the scholarly floor (half the academic
        one) but the sentences are short, so the academic arm's msl leg
        fails and the elif falls through to scholarly_essay instead."""
        text = "This shorter sentence works fine. " * 20
        citation_data = CitationData(
            paren_citation_count=2, signal_verb_counts=Counter({"claims": 3})
        )
        out = genre_v2._resolve_by_rules(text, citation_data=citation_data)
        assert out == {
            "primary": "scholarly_essay",
            "confidence": genre_v2.RULE_CONFIDENCE,
            "secondary": None,
        }

    def test_sermon_arm(self):
        """High imperative density plus a first-person-dominant pronoun mix
        and no citations at all."""
        text = (
            "Consider these things. Examine your own heart daily. "
            "I say to you, repent now. I beg. "
        ) * 12
        out = genre_v2._resolve_by_rules(text, citation_data=CitationData())
        assert out == {
            "primary": "sermon",
            "confidence": genre_v2.RULE_CONFIDENCE,
            "secondary": None,
        }

    def test_creative_fiction_arm(self):
        """Dialogue-bearing narrative with no first-person pronouns (so the
        personal_essay arm above it in the elif chain does not claim it
        first) and no citation or signal-verb activity at all."""
        text = (
            'He said, "they shall go at once," and turned away. '
            "She looked back once more at the door. "
        ) * 15
        out = genre_v2._resolve_by_rules(text, citation_data=CitationData())
        assert out == {
            "primary": "creative_fiction",
            "confidence": genre_v2.RULE_CONFIDENCE,
            "secondary": None,
        }


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
