"""
tests/test_tier16.py — degenerate/populated-input branch coverage for
`original/features/tier16.py` (Tier 16 — Citation Fingerprint).

The existing suite only ever exercises `CitationData` in its default
(empty) state, so every extractor's "insufficient data" neutral arm is
covered but the actual computation body — reached only once real signal
verbs / assertiveness scores / per-paragraph citation counts are present
— never runs. These tests supply populated `CitationData` instances to
close that residue.
"""

from __future__ import annotations

from collections import Counter

from original.features.preprocess import CitationData
from original.features.tier16 import (
    citation_density_cv,
    signal_verb_assertiveness,
    signal_verb_entropy,
)


# ── `signal_verb_entropy` ───────────────────────────────────────────────────


def test_signal_verb_entropy_no_verbs_returns_zero():
    cd = CitationData()
    assert signal_verb_entropy(cd) == 0.0


def test_signal_verb_entropy_single_verb_used_exclusively_is_zero_bits():
    cd = CitationData(signal_verb_counts=Counter({"argues": 5}))
    assert signal_verb_entropy(cd) == 0.0


def test_signal_verb_entropy_multiple_verbs_returns_positive_entropy():
    cd = CitationData(
        signal_verb_counts=Counter({"argues": 3, "claims": 2, "suggests": 1, "notes": 1})
    )
    result = signal_verb_entropy(cd)
    assert result > 0.0


# ── `signal_verb_assertiveness` ─────────────────────────────────────────────


def test_signal_verb_assertiveness_no_scores_returns_neutral():
    cd = CitationData()
    assert signal_verb_assertiveness(cd) == 0.5


def test_signal_verb_assertiveness_computes_mean_of_scores():
    cd = CitationData(signal_verb_assertiveness_scores=[0.9, 0.7, 0.5, 0.3])
    result = signal_verb_assertiveness(cd)
    assert result == 0.6


# ── `citation_density_cv` ───────────────────────────────────────────────────


def test_citation_density_cv_fewer_than_two_paragraphs_returns_zero():
    cd = CitationData(citations_per_paragraph=[3])
    assert citation_density_cv(cd) == 0.0


def test_citation_density_cv_zero_mean_returns_zero():
    """>= 2 paragraphs but no citations at all in any of them."""
    cd = CitationData(citations_per_paragraph=[0, 0, 0])
    assert citation_density_cv(cd) == 0.0


def test_citation_density_cv_computes_coefficient_of_variation():
    cd = CitationData(citations_per_paragraph=[1, 3, 5])
    result = citation_density_cv(cd)
    assert result > 0.0


def test_citation_density_cv_uniform_counts_gives_zero_cv():
    """Non-zero mean but zero variance (perfectly uniform distribution)."""
    cd = CitationData(citations_per_paragraph=[2, 2, 2])
    assert citation_density_cv(cd) == 0.0
