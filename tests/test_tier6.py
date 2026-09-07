"""
tests/test_tier6.py — branch coverage for `original/features/tier6.py`
(Tier 6 — Idiosyncratic & Error Patterns).

Covers:
  - `citation_style_consistency`: one synthetic text per style arm —
    footnote-only, parenthetical-only, no-citations, and mixed (>= 2
    styles, which is the only arm that actually reaches the Shannon-entropy
    computation; the single-style and no-citation arms both short-circuit
    at `len(format_counts) <= 1`).
  - `abbreviation_tendency`: the `abbrev_count > 0` arm (`abbrev_used +=`)
    — the existing suite's texts never contain a theological abbreviation.

The dead `return 0.0` fallback at the end of `list_marker_preference` is
marked `# pragma: no cover` in the source with a rigorous unreachability
justification (max_count is always found in the loop) rather than tested
here.
"""

from __future__ import annotations

from original.features.tier1 import TextDoc
from original.features.tier6 import abbreviation_tendency, citation_style_consistency


def test_citation_style_consistency_footnote_only_is_fully_consistent():
    doc = TextDoc("1. Smith, T., A History of Doctrine, 2020.")
    assert citation_style_consistency(doc) == 0.0


def test_citation_style_consistency_parenthetical_only_is_fully_consistent():
    doc = TextDoc("The doctrine developed over time (Smith, 2020).")
    assert citation_style_consistency(doc) == 0.0


def test_citation_style_consistency_no_citations_is_fully_consistent():
    doc = TextDoc("There are no citations in this simple sentence at all.")
    assert citation_style_consistency(doc) == 0.0


def test_citation_style_consistency_mixed_styles_has_positive_entropy():
    # apa_parenthetical "(Smith, 2020)" + apa_narrative "Smith (2020)" —
    # two distinct formats, so format_counts has > 1 key and the
    # Shannon-entropy computation actually runs.
    doc = TextDoc(
        "According to recent scholarship (Smith, 2020), the argument holds. "
        "Smith (2020) further explains the nuance."
    )
    result = citation_style_consistency(doc)
    assert result > 0.0


def test_abbreviation_tendency_counts_abbreviation_usage():
    doc = TextDoc("The professor referenced cf. the appendix for confirmation of the claim.")
    result = abbreviation_tendency(doc)
    assert result > 0.0
