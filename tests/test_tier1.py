"""
tests/test_tier1.py — branch coverage for `original/features/tier1.py`
(Tier 1 — Surface Stylometrics) and its `TextDoc` container.

Covers:
  - `TextDoc.sent_words`: never exercised by any higher-level pipeline path
    (only `.sentences` / `.tokens` are consumed downstream) — unit-tested
    directly.

The `_split_paragraphs` empty-sentence-list arm (`if sents:` false branch)
is marked `# pragma: no branch` in the source with a rigorous unreachability
justification — see the comment there — rather than tested here, since no
non-empty, already-stripped paragraph can produce an empty sentence list.
"""

from __future__ import annotations

from original.features.tier1 import TextDoc


def test_sent_words_returns_one_token_list_per_sentence():
    doc = TextDoc("First sentence here. Second sentence follows now.")
    result = doc.sent_words()
    assert result == [
        ["First", "sentence", "here"],
        ["Second", "sentence", "follows", "now"],
    ]


def test_sent_words_empty_text_returns_empty_list():
    doc = TextDoc("")
    assert doc.sent_words() == []
