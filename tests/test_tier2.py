"""
tests/test_tier2.py — branch coverage for `original/features/tier2.py`
(Tier 2 — Discourse Analysis).

Covers:
  - `_find_discourse_markers`: the multi-word marker arm (`" " in marker`)
    — the existing suite's texts only ever trigger single-word markers.
  - `additive_ratio` / `adversative_ratio` / `causal_ratio` / `temporal_ratio`:
    thin wrappers around `_marker_category_ratios` that `extract_tier2`
    never calls directly (it reads the ratios dict inline) — unit-tested
    directly, one text with one marker per category.
  - `thematic_progression_score` / `lexical_chain_density`: the
    empty-content-word-chain arm (`not cw_prev or not cw_curr` /
    `not a or not b`) when an adjacent sentence has zero content words.
  - `paragraph_topic_position`: a paragraph with >= 2 sentences where one
    sentence tokenizes to nothing (`if not toks:` arm).
  - `sentence_opener_variety`: a sentence with no leading word character at
    all, so `re.match(r"\\b(\\w+)", sent)` fails (`if not first:` arm).

The `if not paras:` early-return arms in `paragraph_topic_position` and
`avg_paragraph_length`, and the `if union > 0:` loop-back arm in
`lexical_chain_density`, are marked `# pragma: no cover` / `# pragma: no
branch` in the source with rigorous unreachability justifications — see the
comments there.
"""

from __future__ import annotations

from original.features.tier1 import TextDoc
from original.features.tier2 import (
    additive_ratio,
    adversative_ratio,
    avg_paragraph_length,
    causal_ratio,
    lexical_chain_density,
    paragraph_topic_position,
    sentence_opener_variety,
    temporal_ratio,
    thematic_progression_score,
)

# One marker per category, including one multi-word marker ("on the other
# hand") to exercise the `" " in marker` branch of `_find_discourse_markers`.
_ALL_CATEGORIES_TEXT = (
    "Furthermore, the argument is compelling. "
    "On the other hand, some critics disagree. "
    "Therefore, we must weigh both views. "
    "Finally, the conclusion follows."
)


def test_additive_ratio_direct_call():
    doc = TextDoc(_ALL_CATEGORIES_TEXT)
    assert additive_ratio(doc) == 0.25


def test_adversative_ratio_direct_call_covers_multiword_marker():
    doc = TextDoc(_ALL_CATEGORIES_TEXT)
    assert adversative_ratio(doc) == 0.25


def test_causal_ratio_direct_call():
    doc = TextDoc(_ALL_CATEGORIES_TEXT)
    assert causal_ratio(doc) == 0.25


def test_temporal_ratio_direct_call():
    doc = TextDoc(_ALL_CATEGORIES_TEXT)
    assert temporal_ratio(doc) == 0.25


# ── empty content-word chain (thematic_progression_score / lexical_chain) ──

# "(!!!" is a real split-off sentence (a valid lookahead/lookbehind boundary
# on both sides) that tokenizes to zero words, so its content-word set is
# empty while the preceding sentence's is not.
_EMPTY_CHAIN_TEXT = "Theology requires careful analysis and study. (!!!"


def test_thematic_progression_score_empty_chain_returns_neutral():
    doc = TextDoc(_EMPTY_CHAIN_TEXT)
    assert len(doc.sentences) == 2
    assert thematic_progression_score(doc) == 0.5


def test_lexical_chain_density_empty_chain_returns_zero():
    doc = TextDoc(_EMPTY_CHAIN_TEXT)
    assert lexical_chain_density(doc) == 0.0


# ── paragraph_topic_position: a sentence with zero tokens mid-paragraph ────


def test_paragraph_topic_position_handles_tokless_sentence():
    text = "First sentence ends here. (!!! Second real sentence follows."
    doc = TextDoc(text)
    assert len(doc.paragraphs) == 1
    assert len(doc.paragraphs[0]) == 3  # 3 sentences, so len(para) >= 2
    # Must not raise (ZeroDivisionError from len(cw)/len(toks)) and must
    # produce a valid fraction.
    result = paragraph_topic_position(doc)
    assert 0.0 <= result <= 1.0


def test_avg_paragraph_length_single_paragraph_document():
    text = "First sentence ends here. (!!! Second real sentence follows."
    doc = TextDoc(text)
    assert avg_paragraph_length(doc) == 3.0


# ── sentence_opener_variety: sentence with no leading word character ───────


def test_sentence_opener_variety_no_leading_word_char_is_other():
    doc = TextDoc("!!!")
    assert doc.sentences == ["!!!"]
    # A single "other"-class sentence has zero entropy.
    assert sentence_opener_variety(doc) == 0.0
