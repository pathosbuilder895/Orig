"""
tests/test_prosodic.py — degenerate-input / optional-dependency branch
coverage for `original/features/prosodic.py` (Tiers 13-15).

Covers:
  - `_get_nlp`'s unavailable arm (mirrors tier5/tier11: OSError degrades
    cleanly, module-level `_spacy_ok`/`_nlp` cache reset via monkeypatch).
  - `_shannon_entropy`'s empty-counter arm (unit-tested directly — every
    caller already guards against it before calling).
  - `_metric_flatness_score`: no-paragraphs arm (stub object — real
    TextDoc.paragraphs is never empty) and the >= 2 densities computation
    body, including the zero-mean (all-monosyllabic, "no stressed
    syllables") sub-arm.
  - `_article_omission_rate`: the spaCy-parse exception arm, which falls
    through into the regex fallback.
  - `_semantic_field_concentration`: the spaCy-unavailable lexical
    fallback arm, and the word-vector cosine-similarity arm (spaCy's
    small model ships no vectors, so this requires a fake vocab).
  - `_chiasmus_rate`: the spaCy-unavailable neutral arm and the
    per-sentence POS-tagging exception arm.
"""

from __future__ import annotations

import sys
import types
from collections import Counter

import numpy as np
import pytest

from original.features import prosodic
from original.features.tier1 import TextDoc


# ── `_get_nlp` unavailable arm ──────────────────────────────────────────────


def test_get_nlp_unavailable_degrades_to_none(monkeypatch):
    """spacy.load raising OSError (missing model) must cache `_spacy_ok =
    False` / `_nlp = None` rather than propagate."""
    monkeypatch.setattr(prosodic, "_spacy_ok", None)
    monkeypatch.setattr(prosodic, "_nlp", None)

    def _raise_load(name, disable=None):
        raise OSError("model 'en_core_web_sm' not found")

    fake_spacy = types.ModuleType("spacy")
    fake_spacy.load = _raise_load
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)

    result = prosodic._get_nlp()

    assert result is None
    assert prosodic._spacy_ok is False


def test_get_nlp_available_caches_model(monkeypatch):
    monkeypatch.setattr(prosodic, "_spacy_ok", None)
    monkeypatch.setattr(prosodic, "_nlp", None)

    result = prosodic._get_nlp()

    assert result is not None
    assert prosodic._spacy_ok is True


# ── `_shannon_entropy` (prosodic's local copy) ──────────────────────────────


def test_shannon_entropy_empty_counter_returns_zero():
    assert prosodic._shannon_entropy(Counter()) == 0.0


def test_shannon_entropy_nonzero_counter_returns_positive():
    assert prosodic._shannon_entropy(Counter({"planus": 3, "trochaic": 1})) > 0.0


# ── `_metric_flatness_score` arms ───────────────────────────────────────────


class _ParagraphsStub:
    """Minimal duck-typed stand-in — real TextDoc.paragraphs can never be
    empty (`_split_paragraphs` always falls back to `[[text]]`), so the
    `not doc.paragraphs` guard is only reachable via a direct stub."""

    def __init__(self, paragraphs):
        self.paragraphs = paragraphs


def test_metric_flatness_score_no_paragraphs_returns_neutral():
    assert prosodic._metric_flatness_score(_ParagraphsStub([])) == 0.5


def test_metric_flatness_score_all_monosyllabic_gives_zero_cv():
    """Every word across >= 2 paragraphs has a single vowel-group (no
    stressed syllables anywhere), so stress density is 0.0 in every
    paragraph and arr.mean() == 0 -- the CV falls to the else-branch 0.0,
    giving maximal (1.0) flatness."""
    text = "Cat sat on mat. Dog ran to bed.\n\nSun set fast. Wind blew hard."
    doc = TextDoc(text)
    assert len(doc.paragraphs) >= 2
    result = prosodic._metric_flatness_score(doc)
    assert result == 1.0


def test_metric_flatness_score_computes_real_cv_across_paragraphs():
    """Paragraphs with differing polysyllabic-word density must exercise
    the full >= 2 densities computation body (arr.mean() > 0 arm)."""
    text = (
        "Theological interpretation demands considerable investigation "
        "of complicated historical documentation.\n\n"
        "Cat sat on mat. Dog ran to bed. Sun set fast."
    )
    doc = TextDoc(text)
    assert len(doc.paragraphs) >= 2
    result = prosodic._metric_flatness_score(doc)
    assert isinstance(result, float)
    assert 0.0 <= result <= 1.0


# ── `_article_omission_rate` exception arm ──────────────────────────────────


class _RaisingNLP:
    """Callable stand-in for a loaded spaCy pipeline that always blows up
    mid-parse — exercises the `except Exception: pass` fallback arms."""

    def __call__(self, text):
        raise RuntimeError("spaCy parse failed")


def test_article_omission_rate_falls_back_to_regex_on_parse_exception(monkeypatch):
    monkeypatch.setattr(prosodic, "_get_nlp", lambda: _RaisingNLP())

    text = "Students often struggle in constant darkness during winter months at seminary."
    doc = TextDoc(text)
    assert doc.word_count >= 10

    result = prosodic._article_omission_rate(doc)
    assert isinstance(result, float)
    assert 0.0 <= result <= 1.0


def test_article_omission_rate_short_text_returns_zero():
    doc = TextDoc("Too short.")
    assert prosodic._article_omission_rate(doc) == 0.0


def test_article_omission_rate_uses_regex_fallback_when_spacy_unavailable(monkeypatch):
    """`if nlp:` False (spaCy unavailable) must skip straight to the regex
    fallback rather than only being reached via a parse exception."""
    monkeypatch.setattr(prosodic, "_get_nlp", lambda: None)

    text = "Students often struggle in constant darkness during winter months at seminary."
    doc = TextDoc(text)
    assert doc.word_count >= 10

    result = prosodic._article_omission_rate(doc)
    assert isinstance(result, float)
    assert 0.0 <= result <= 1.0


# ── `_semantic_field_concentration` arms ────────────────────────────────────


def test_semantic_field_concentration_falls_back_when_spacy_unavailable(monkeypatch):
    monkeypatch.setattr(prosodic, "_get_nlp", lambda: None)
    monkeypatch.setattr(prosodic, "_spacy_ok", False)

    text = "Elephants migrate savannas seasons water routes patterns valleys elephants"
    doc = TextDoc(text)
    result = prosodic._semantic_field_concentration(doc)
    assert isinstance(result, float)
    assert 0.0 <= result <= 1.0


def test_semantic_field_concentration_no_content_words_returns_neutral():
    doc = TextDoc("a an is of to")
    assert prosodic._semantic_field_concentration(doc) == 0.5


class _FakeLexeme:
    def __init__(self, vector):
        self.has_vector = True
        self.vector = vector


# Two orthogonal unit directions (e0, e1 in R^300), each shared by a pair
# of words. Fixed, hardcoded values -- NOT derived from hash(word), which
# is randomized per-process unless PYTHONHASHSEED is pinned and would make
# the expected result unreproducible across runs.
_E0 = np.array([1.0] + [0.0] * 299)
_E1 = np.array([0.0, 1.0] + [0.0] * 298)
_FIXED_VECTORS = {
    "alpha": _E0,
    "beta": _E0,
    "gamma": _E1,
    "delta": _E1,
}


class _FixedVocab:
    """Deterministic fake vocab — real en_core_web_sm ships no word
    vectors (has_vector is always False), so the cosine-similarity branch
    is otherwise unreachable without a stand-in. Unlike a hash-seeded
    random vocab, every word maps to a fixed, known vector so the expected
    output can be derived by hand and checked independently of whatever
    the function under test happens to return."""

    def __getitem__(self, word):
        return _FakeLexeme(_FIXED_VECTORS[word])


class _FakeNLPWithVectors:
    def __init__(self):
        self.vocab = _FixedVocab()


def test_semantic_field_concentration_computes_cosine_similarity_with_vectors(monkeypatch):
    """alpha/beta share direction e0, gamma/delta share direction e1, and
    e0 ⟂ e1. Of the 6 unique pairs among the 4 words, 2 are same-direction
    (cosine sim ~1.0: alpha-beta, gamma-delta) and 4 are orthogonal
    (cosine sim 0.0: every alpha/beta-gamma/delta cross pair). Hand-derived
    expected value:

        mean_sim = (2*1.0 + 4*0.0) / 6 = 1/3
        result   = clip((mean_sim + 1.0) / 2.0, 0.0, 1.0) = (1/3 + 1) / 2 = 2/3

    (The source normalizes each vector by norm + 1e-8 before the dot
    product, so same-direction pairs land at ~0.99999998 rather than
    exactly 1.0 -- off by ~1e-8, well within pytest.approx's tolerance.)
    This is independently derivable from the formula and would catch a
    wrong triu offset (e.g. including the diagonal, which would pull the
    mean toward 1.0) or a wrong normalization/matmul axis, unlike a bare
    0.0 <= result <= 1.0 bounds check that every successful return value
    satisfies by construction."""
    monkeypatch.setattr(prosodic, "_get_nlp", lambda: _FakeNLPWithVectors())
    monkeypatch.setattr(prosodic, "_spacy_ok", True)

    text = "alpha alpha beta beta gamma gamma delta delta"
    doc = TextDoc(text)
    result = prosodic._semantic_field_concentration(doc)
    assert isinstance(result, float)
    assert result == pytest.approx(2.0 / 3.0, abs=1e-6)


# ── `_chiasmus_rate` arms ───────────────────────────────────────────────────


def test_chiasmus_rate_unavailable_spacy_returns_neutral(monkeypatch):
    monkeypatch.setattr(prosodic, "_get_nlp", lambda: None)
    monkeypatch.setattr(prosodic, "_spacy_ok", False)

    doc = TextDoc("One. Two. Three. Four. Five.")
    assert prosodic._chiasmus_rate(doc) == 0.5


def test_chiasmus_rate_short_text_returns_zero(monkeypatch):
    monkeypatch.setattr(prosodic, "_spacy_ok", None)
    monkeypatch.setattr(prosodic, "_nlp", None)

    doc = TextDoc("Only one sentence here.")
    assert prosodic._chiasmus_rate(doc) == 0.0


def test_chiasmus_rate_pos_tagging_exception_is_swallowed(monkeypatch):
    """A spaCy failure mid-sentence (`nlp(text)` raising) inside the nested
    `_pos_tags` helper must be caught and degrade to an empty tag list,
    not propagate out of extraction."""
    monkeypatch.setattr(prosodic, "_get_nlp", lambda: _RaisingNLP())
    monkeypatch.setattr(prosodic, "_spacy_ok", True)

    text = (
        "The first sentence appears here. The second sentence follows it. "
        "The third sentence continues the thought. The fourth sentence ends it."
    )
    doc = TextDoc(text)
    assert len(doc.sentences) >= 4

    result = prosodic._chiasmus_rate(doc)
    assert result == 0.0


# ── `_word_stress` sanity (both real arms, for context alongside the
#    unreachable elif False arm pragma'd in source) ─────────────────────────


def test_word_stress_monosyllabic_word_stresses_first_syllable():
    assert prosodic._word_stress("cat") == [1]


def test_word_stress_polysyllabic_word_stresses_penultimate_syllable():
    result = prosodic._word_stress("elephant")
    assert result[-2] == 1


# ── `extract_prosodic` sanity ────────────────────────────────────────────────


def test_extract_prosodic_returns_all_fifteen_features():
    doc = TextDoc(
        "The old librarian carefully catalogued every dusty volume. "
        "She often wondered about the students who never returned books. "
        "Quietly, the afternoon light moved slowly across the reading room."
    )
    result = prosodic.extract_prosodic(doc)
    assert len(result) == 15
    assert all(isinstance(v, float) for v in result.values())
