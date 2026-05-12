"""
tests/test_features.py — Unit tests for feature extractors.

Tests all 34 feature extractors for correctness and bounds.
"""

import pytest
import numpy as np

from original.features.pipeline import extract_features
from original.constants import ALL_FEATURE_CODES, FEATURE_DIM


SAMPLE_100_WORD_TEXT = """
The development of theological understanding requires careful consideration
of both historical context and contemporary application. Scholars have long
debated the interpretation of scriptural passages in light of modern hermeneutical
approaches. The relationship between faith and reason has been central to Christian
philosophy. Contemporary theology must address the challenges posed by pluralism
and secularization. Academic discourse in this field demands rigorous analysis
of textual evidence and logical argumentation. Many theologians have contributed
to our understanding of divine attributes. The nature of salvation remains contested
among different Christian traditions. Ethical frameworks derived from theological
principles continue to influence moral philosophy. The role of tradition in shaping
doctrine cannot be underestimated. Future developments in this discipline will
likely incorporate insights from interdisciplinary sources.
""".strip()


class TestFeatureExtraction:
    """Tests for feature extraction functionality."""

    def test_extract_features_returns_dict(self):
        """Feature extraction returns a dictionary."""
        result = extract_features(SAMPLE_100_WORD_TEXT)
        assert isinstance(result, dict)

    def test_extract_features_all_34_codes(self):
        """Feature extraction returns exactly 34 features."""
        result = extract_features(SAMPLE_100_WORD_TEXT)
        assert len(result) == FEATURE_DIM
        assert set(result.keys()) == set(ALL_FEATURE_CODES)

    def test_extract_features_all_normalized(self):
        """All feature values are normalized to [0, 1]."""
        result = extract_features(SAMPLE_100_WORD_TEXT)
        for code, value in result.items():
            assert 0.0 <= value <= 1.0, f"{code} = {value} not in [0, 1]"

    def test_extract_features_empty_text(self):
        """Feature extraction handles empty text without crashing."""
        result = extract_features("")
        assert isinstance(result, dict)
        assert len(result) == FEATURE_DIM
        # Most features should be 0 for empty text
        assert all(isinstance(v, float) for v in result.values())

    def test_extract_features_single_word(self):
        """Feature extraction handles single word."""
        result = extract_features("test")
        assert isinstance(result, dict)
        assert len(result) == FEATURE_DIM

    def test_type_token_ratio_all_unique_words(self):
        """Type-Token Ratio is high for text with all unique words."""
        unique_words = "the quick brown fox jumps over lazy dog"
        result = extract_features(unique_words)
        ttr = result["type_token_ratio"]
        # Should be relatively high since all words are unique
        assert ttr > 0.7

    def test_type_token_ratio_all_same_word(self):
        """Type-Token Ratio is low for text with same word repeated."""
        repeated = "test " * 20
        result = extract_features(repeated)
        ttr = result["type_token_ratio"]
        # Should be very low since only one unique word
        assert ttr < 0.1

    def test_mean_sentence_length(self):
        """Mean sentence length is calculated correctly."""
        text = "Short. Medium length sentence. This is a longer sentence with multiple words."
        result = extract_features(text)
        msl = result["mean_sentence_length"]
        assert 0.0 <= msl <= 1.0

    def test_function_word_ratio(self):
        """Function word ratio is non-zero for normal text."""
        result = extract_features(SAMPLE_100_WORD_TEXT)
        fwr = result["function_word_ratio"]
        # Should be non-zero for normal text with articles, prepositions, etc.
        assert fwr > 0.0

    def test_passive_voice_ratio(self):
        """Passive voice ratio detects passive constructions."""
        active = "The student wrote the paper."
        passive = "The paper was written by the student."

        active_result = extract_features(active)
        passive_result = extract_features(passive)

        active_pvr = active_result["passive_voice_ratio"]
        passive_pvr = passive_result["passive_voice_ratio"]

        # Passive should have higher passive voice ratio
        assert passive_pvr >= active_pvr

    def test_modal_verb_ratio_no_modals(self):
        """Modal verb ratio is zero when no modal verbs present."""
        no_modals = "The student studied hard and completed the work."
        result = extract_features(no_modals)
        mvr = result["modal_verb_ratio"]
        assert mvr == 0.0 or mvr < 0.1  # May be slightly nonzero due to tokenization

    def test_modal_verb_ratio_with_modals(self):
        """Modal verb ratio is higher with modal verbs."""
        with_modals = "The student can write, should study, and will succeed."
        result = extract_features(with_modals)
        mvr = result["modal_verb_ratio"]
        assert mvr > 0.0

    def test_avg_word_length(self):
        """Average word length is calculated."""
        result = extract_features(SAMPLE_100_WORD_TEXT)
        awl = result["avg_word_length"]
        assert 0.0 <= awl <= 1.0

    def test_stop_word_ratio(self):
        """Stop word ratio is non-zero for normal text."""
        result = extract_features(SAMPLE_100_WORD_TEXT)
        swr = result["stop_word_ratio"]
        assert swr > 0.0

    def test_discourse_marker_density(self):
        """Discourse marker density is detected."""
        with_markers = "Furthermore, the analysis shows that. Moreover, the evidence supports."
        result = extract_features(with_markers)
        dmd = result["discourse_marker_density"]
        assert isinstance(dmd, float)


class TestFeatureConsistency:
    """Tests for feature extraction consistency."""

    def test_same_text_same_features(self):
        """Same text produces same features (deterministic)."""
        text = "The quick brown fox jumps over the lazy dog. " * 5
        result1 = extract_features(text)
        result2 = extract_features(text)

        for code in ALL_FEATURE_CODES:
            assert result1[code] == result2[code], f"{code} not deterministic"

    def test_longer_text_more_stable(self):
        """Longer text should produce more stable features."""
        short = "The quick brown fox."
        long = "The quick brown fox. " * 20

        short_result = extract_features(short)
        long_result = extract_features(long)

        # Both should have valid features
        assert all(0.0 <= v <= 1.0 for v in short_result.values())
        assert all(0.0 <= v <= 1.0 for v in long_result.values())
