"""
features/tier16.py — Tier 16: Citation Fingerprint

Eight features derived from *how* a student uses citations — arguably the most
unconscious dimension of academic writing.  Students do not think about whether
they always use "argues" vs. rotating verbs, or whether they habitually block-
quote vs. paraphrase.  These habits are deeply stable and extremely hard to
replicate when ghostwriting.

Why this matters
----------------
AI ghostwriters replicate vocabulary range and argument structure (Tiers 1-9)
but have no access to the student's citation personality:
  - They use a small, predictable set of signal verbs (low entropy)
  - They have no "source loyalty" — no go-to authors the student has read
    all semester
  - They default to end-of-sentence citation placement (assertive style)
  - They avoid ibid. (no footnote habit)
  - They rarely block-quote (no feel for the student's quote-density habit)

Features
--------
signal_verb_entropy         Diversity of signal verbs used (bits).
                            AI ≈ 0.5–1.0 bits; humans typically 1.5–3.5 bits.
signal_verb_assertiveness   Mean assertiveness of signal verbs [0, 1].
                            Assertive writers ("demonstrates", "proves") → high.
                            Hedgers ("suggests", "implies") → low.
source_loyalty_index        Repeat-author fraction.  Students who return to the
                            same 3–4 authors score high (0.6+); AI spreads thin.
block_quote_rate            Block-quote words per 1000 prose words.
                            Habitual: some students never block-quote; others do
                            it in every paper.
citation_density_cv         Coefficient of variation of citations per paragraph.
                            High CV = clustered (heavy intro, sparse body).
ibid_usage_rate             ibid. + op. cit. / total citations.
                            Footnote-style students develop strong habits.
citation_position_pref      Mean relative position of citation within sentence.
                            0 = always at start (authority-led),
                            1 = always at end (assertive / post-argument).
paraphrase_density          Paraphrase-attribution phrases per 100 prose words.
                            High = student integrates sources by summary rather
                            than direct quote.

All outputs are in [0, 1] (normalisation via NORM_BOUNDS in constants.py).
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Dict

from .preprocess import CitationData


# ══════════════════════════════════════════════════════════════════════════════
# Feature extractors
# ══════════════════════════════════════════════════════════════════════════════

def signal_verb_entropy(cd: CitationData) -> float:
    """
    Shannon entropy (bits) of the signal verb distribution.

    No signal verbs → 0.0 (neutral — treated as missing data).
    One verb used exclusively → 0.0 bits.
    Eight verbs used equally → 3.0 bits.
    """
    counts = cd.signal_verb_counts
    total = sum(counts.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy


def signal_verb_assertiveness(cd: CitationData) -> float:
    """
    Mean assertiveness score of all signal verb occurrences.

    Returns 0.5 when no signal verbs are found (neutral).
    """
    scores = cd.signal_verb_assertiveness_scores
    if not scores:
        return 0.5
    return sum(scores) / len(scores)


def source_loyalty_index(cd: CitationData) -> float:
    """
    Fraction of citation events that cite a repeat author.

    E.g.: [Calvin, Calvin, Barth, Calvin, Wright, Barth]
    → 4 repeat events out of 6 total = loyalty 0.667

    Returns 0.5 when fewer than 3 citations (insufficient data).
    """
    authors = cd.cited_authors
    if len(authors) < 3:
        return 0.5
    counts = Counter(authors)
    # "Repeat" means cited more than once
    repeat_events = sum(c - 1 for c in counts.values() if c > 1)
    return repeat_events / len(authors)


def block_quote_rate(cd: CitationData) -> float:
    """
    Block-quote words per 1000 prose words.

    Returns 0.0 when prose is empty.
    """
    if cd.prose_word_count < 1:
        return 0.0
    return (cd.block_quote_word_count / cd.prose_word_count) * 1000


def citation_density_cv(cd: CitationData) -> float:
    """
    Coefficient of variation (std / mean) of citations-per-paragraph.

    High CV → citation-heavy intro/conclusion with dry body (common pattern).
    Low CV → uniform citation distribution throughout.
    Returns 0.0 when fewer than 2 paragraphs or no citations at all.
    """
    counts = cd.citations_per_paragraph
    if len(counts) < 2:
        return 0.0
    n = len(counts)
    mean = sum(counts) / n
    if mean < 1e-9:
        return 0.0  # no citations at all
    variance = sum((c - mean) ** 2 for c in counts) / n
    std = variance ** 0.5
    return std / mean


def ibid_usage_rate(cd: CitationData) -> float:
    """
    ibid. / op. cit. count relative to total citation count.

    Total citations = parenthetical + footnote markers.
    Returns 0.0 when no citations found.
    """
    total = cd.paren_citation_count + cd.footnote_marker_count
    if total == 0:
        return 0.0
    return min(cd.ibid_count / total, 1.0)


def citation_position_pref(cd: CitationData) -> float:
    """
    Mean relative position of citation markers within their sentence.

    0.0 = always at sentence start (authority-led: "Calvin argues that...")
    1.0 = always at sentence end (assertive: "...in the text (Calvin 2020).")
    0.5 = midpoint or mixed (returned when no position data).
    """
    positions = cd.citation_positions
    if not positions:
        return 0.5
    return sum(positions) / len(positions)


def paraphrase_density(cd: CitationData) -> float:
    """
    Paraphrase-attribution markers per 100 prose words.

    High = student integrates sources via summary ("According to Calvin, ...")
    Low = student prefers direct quotation or implicit citation.
    Returns 0.0 when prose is empty.
    """
    if cd.prose_word_count < 1:
        return 0.0
    return (cd.paraphrase_marker_count / cd.prose_word_count) * 100


# ══════════════════════════════════════════════════════════════════════════════
# Public extractor
# ══════════════════════════════════════════════════════════════════════════════

def extract_tier16(cd: CitationData) -> Dict[str, float]:
    """
    Compute all 8 Tier 16 citation fingerprint features from a CitationData.

    Returns raw values in their natural units; normalisation to [0, 1] is
    applied by pipeline.py via NORM_BOUNDS.
    """
    return {
        "signal_verb_entropy":       signal_verb_entropy(cd),
        "signal_verb_assertiveness": signal_verb_assertiveness(cd),
        "source_loyalty_index":      source_loyalty_index(cd),
        "block_quote_rate":          block_quote_rate(cd),
        "citation_density_cv":       citation_density_cv(cd),
        "ibid_usage_rate":           ibid_usage_rate(cd),
        "citation_position_pref":    citation_position_pref(cd),
        "paraphrase_density":        paraphrase_density(cd),
    }
