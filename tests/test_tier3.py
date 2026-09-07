"""
tests/test_tier3.py — branch coverage for `original/features/tier3.py`
(Tier 3 — Rhetorical Fingerprint + Theological Register).

Covers:
  - `source_integration_style`: the `(idx + 1) not in citation_indices`
    false arm — reached when two consecutive sentences are both citation
    sentences, so the "next sentence provides commentary" check is skipped
    for the first of the pair.
  - `theological_register_score`: the `CONFESSIONAL_MARKERS` hit arm
    (`hits += 1`) — the existing suite's texts only ever exercise the
    single-word `THEOLOGICAL_TERMS` count, never a confessional phrase.
"""

from __future__ import annotations

from original.features.tier1 import TextDoc
from original.features.tier3 import source_integration_style, theological_register_score


def test_source_integration_style_consecutive_citation_sentences():
    # Both sentences are citation sentences (AUTHORITY_MARKERS "according
    # to"), so for idx=0 the next sentence (idx=1) is *also* a citation
    # sentence — the `(idx + 1) not in citation_indices` check must be
    # False, skipping the commentary check for that pair.
    text = (
        "According to Calvin, the doctrine is clear. "
        "According to Luther, the doctrine is affirmed."
    )
    doc = TextDoc(text)
    assert len(doc.sentences) == 2
    # Neither citation sentence is followed by non-citation commentary, so
    # comment_count stays 0 for both citation indices.
    assert source_integration_style(doc) == 0.0


def test_source_integration_style_short_commentary_does_not_count():
    # Citation sentence followed by a genuine non-citation sentence whose
    # commentary word count (> 3 chars, non-stop) is < 4 — the
    # `len(cw) >= 4` check must be False, so comment_count is not
    # incremented for this citation.
    text = "According to Calvin, the doctrine is clear. It is true."
    doc = TextDoc(text)
    assert len(doc.sentences) == 2
    assert source_integration_style(doc) == 0.0


def test_theological_register_score_counts_confessional_marker_phrase():
    # "inerrancy" is a literal entry in CONFESSIONAL_MARKERS, distinct from
    # the single-word THEOLOGICAL_TERMS lookup above it.
    text = (
        "This essay affirms the inerrancy of scripture as central to sound "
        "doctrine and theological formation across many chapters of study."
    )
    doc = TextDoc(text)
    result = theological_register_score(doc)
    assert result > 0.0
