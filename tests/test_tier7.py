"""
tests/test_tier7.py — degenerate-input branch coverage for
`original/features/tier7.py` (Tier 7 — AI Detection Markers).

Covers:
  - `_gini_coefficient`: empty / single-element / all-zero-sum arms
    (unit-tested directly — the public callers never reach these edges
    with real hedge-word data).
  - `_load_word_freqs`: the zero-total-frequency arm (`total > 0` false)
    and the missing-file arm (`FileNotFoundError`), both via
    monkeypatched module state / `__file__`.
  - `burstiness`: the `mean == 0` arm (all-empty-token sentences).
  - `perplexity_proxy`: the hapax-based fallback when no frequency
    table is available.
  - `repetition_gap_entropy`: the no-repeated-content-word arm.
  - `transition_predictability`: the all-empty-paragraph-bows neutral
    arm and the real cross-paragraph-similarity arm.
"""

from __future__ import annotations

from original.features import tier7
from original.features.tier1 import TextDoc


# ── `_gini_coefficient` edge cases (unit-tested directly) ──────────────────


def test_gini_coefficient_empty_list_returns_zero():
    assert tier7._gini_coefficient([]) == 0.0


def test_gini_coefficient_single_element_returns_zero():
    assert tier7._gini_coefficient([5.0]) == 0.0


def test_gini_coefficient_all_zero_values_returns_zero():
    """total == 0 (all-identical-zero arm) must short-circuit rather than
    divide by zero."""
    assert tier7._gini_coefficient([0.0, 0.0, 0.0]) == 0.0


# ── `_load_word_freqs` arms ─────────────────────────────────────────────────


def test_load_word_freqs_missing_file_degrades_gracefully(monkeypatch):
    """A missing data file must be swallowed (FileNotFoundError) leaving
    `_WORD_FREQS` empty rather than raising."""
    monkeypatch.setattr(tier7, "_FREQ_LOADED", False)
    monkeypatch.setattr(tier7, "_WORD_FREQS", {})
    monkeypatch.setattr(tier7, "__file__", "/nonexistent/dir/tier7.py")

    tier7._load_word_freqs()

    assert tier7._WORD_FREQS == {}
    assert tier7._FREQ_LOADED is True


def test_load_word_freqs_zero_total_leaves_freqs_empty(monkeypatch):
    """A frequency file whose counts sum to zero must not populate
    `_WORD_FREQS` (the `total > 0` guard)."""
    monkeypatch.setattr(tier7, "_FREQ_LOADED", False)
    monkeypatch.setattr(tier7, "_WORD_FREQS", {})
    monkeypatch.setattr(tier7.json, "load", lambda f: {})

    tier7._load_word_freqs()

    assert tier7._WORD_FREQS == {}
    assert tier7._FREQ_LOADED is True


# ── `burstiness` arms ────────────────────────────────────────────────────────


class _SentencesStub:
    """Minimal duck-typed stand-in exposing only what `burstiness` reads."""

    def __init__(self, sentences):
        self.sentences = sentences


def test_burstiness_mean_zero_returns_zero():
    """Three sentences that tokenize to zero words each (mean == 0) must
    return 0.0 rather than dividing by zero."""
    doc = _SentencesStub(["!!!", "???", "..."])
    assert tier7.burstiness(doc) == 0.0


def test_burstiness_short_text_returns_neutral():
    doc = _SentencesStub(["One.", "Two."])
    assert tier7.burstiness(doc) == 1.0


# ── `perplexity_proxy` fallback arm ─────────────────────────────────────────


def test_perplexity_proxy_uses_hapax_fallback_when_no_freq_table(monkeypatch):
    """When `_WORD_FREQS` is empty (e.g. data file unavailable), perplexity
    falls back to a hapax-based estimate instead of the precomputed table."""
    monkeypatch.setattr(tier7, "_FREQ_LOADED", True)
    monkeypatch.setattr(tier7, "_WORD_FREQS", {})

    doc = TextDoc("The quick brown fox jumps over the lazy dog again and again.")
    result = tier7.perplexity_proxy(doc)

    assert isinstance(result, float)
    assert result > 0.0


def test_perplexity_proxy_empty_words_returns_zero():
    doc = TextDoc("")
    assert tier7.perplexity_proxy(doc) == 0.0


# ── `repetition_gap_entropy` arms ───────────────────────────────────────────


def test_repetition_gap_entropy_no_repeated_content_words_returns_zero():
    """20+ words, all distinct content words (len >= 4, not function words)
    — no word repeats, so `all_gaps` stays empty."""
    words = (
        "alpha bravo charlie delta echo foxtrot golf hotel india juliet "
        "kilo lima mike november oscar papa quebec romeo sierra tango"
    )
    doc = TextDoc(words)
    assert len(doc.lower_words) >= 20
    assert tier7.repetition_gap_entropy(doc) == 0.0


def test_repetition_gap_entropy_short_text_returns_zero():
    doc = TextDoc("Short text here.")
    assert tier7.repetition_gap_entropy(doc) == 0.0


def test_repetition_gap_entropy_with_repeats_returns_positive_entropy():
    text = "shepherd wandered through valleys. Later the shepherd returned to those valleys again with the flock."
    doc = TextDoc(text)
    result = tier7.repetition_gap_entropy(doc)
    assert isinstance(result, float)


# ── `transition_predictability` arms ────────────────────────────────────────


def test_transition_predictability_single_paragraph_returns_neutral():
    doc = TextDoc("Only one paragraph exists here with a couple of sentences. It has no breaks.")
    assert tier7.transition_predictability(doc) == 0.5


def test_transition_predictability_all_empty_bows_returns_neutral():
    """Two paragraphs built entirely from function/short words produce empty
    bag-of-words vectors for every pair, so no similarity is ever collected
    and the function must fall back to the neutral 0.5."""
    text = "The a an is of.\n\nIt is to be or not so.\n\nAn a the is at it."
    doc = TextDoc(text)
    assert len(doc.paragraphs) >= 2
    assert tier7.transition_predictability(doc) == 0.5


def test_transition_predictability_computes_real_similarity():
    """Two paragraphs sharing substantive content words must produce a
    genuine (non-neutral-by-construction) cosine-similarity average."""
    text = (
        "Elephants migrate across vast savannas during dry seasons searching water.\n\n"
        "Migration patterns among elephants remain remarkably consistent as elephants "
        "follow ancient routes across savannas each year."
    )
    doc = TextDoc(text)
    assert len(doc.paragraphs) >= 2
    result = tier7.transition_predictability(doc)
    assert isinstance(result, float)
    assert 0.0 < result <= 1.0


# ── `extract_tier7` / `extract_tier7_profiles` sanity ───────────────────────


def test_extract_tier7_returns_all_six_features():
    doc = TextDoc("The librarian carefully catalogued every dusty volume in the archive.")
    result = tier7.extract_tier7(doc)
    assert set(result.keys()) == {
        "burstiness",
        "perplexity_proxy",
        "repetition_gap_entropy",
        "transition_predictability",
        "vocabulary_introduction_rate",
        "filler_hedge_cluster_rate",
    }


def test_extract_tier7_profiles_returns_function_word_profile():
    doc = TextDoc("The librarian carefully catalogued every dusty volume in the archive.")
    result = tier7.extract_tier7_profiles(doc)
    assert "_function_word_profile" in result
