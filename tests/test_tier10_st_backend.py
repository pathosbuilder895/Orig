"""
tests/test_tier10_st_backend.py — sentence-transformers backend coverage for tier10.

`original/features/tier10.py`'s `_get_st_model()` prefers the sentence-transformers
("all-MiniLM-L6-v2") backend when importable, falling back to TF-IDF otherwise.
In this repo's test env that ST import path is normally never exercised (either
because sentence-transformers/torch isn't installed, or — as of this session —
it may actually BE installed for real, which would pull in the real network-
fetched model and make tests slow/non-deterministic). Either way we don't want
the real model: this test stubs a fake `sentence_transformers` module into
`sys.modules` so the ST branch runs deterministically regardless of what's
really installed.

Pairs with `validation/test_tier10_optional.py`, which covers the TF-IDF
fallback path (the "backend unavailable" branch) as a lightweight smoke test.
"""

from __future__ import annotations

import logging
import sys
import types
from typing import Any

import numpy as np
import pytest

from original.features import tier10
from original.features.tier1 import TextDoc

EMBED_DIM = 384


class _FakeSentenceTransformer:
    """Deterministic stand-in for sentence_transformers.SentenceTransformer."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def encode(self, sentences: list[str], normalize_embeddings: bool = True) -> np.ndarray:
        # Deterministic, sentence-content-derived embedding: seed a per-sentence
        # RNG from a hash of the sentence text so identical inputs always yield
        # identical output (determinism check) while different sentences yield
        # different (but still fixed) vectors.
        vectors = np.zeros((len(sentences), EMBED_DIM), dtype=np.float32)
        for i, s in enumerate(sentences):
            rng = np.random.default_rng(abs(hash(s)) % (2**32))
            v = rng.standard_normal(EMBED_DIM).astype(np.float32)
            if normalize_embeddings:
                norm = np.linalg.norm(v)
                if norm > 0:
                    v = v / norm
            vectors[i] = v
        return vectors


def _install_fake_sentence_transformers(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = _FakeSentenceTransformer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    # Reset tier10's module-level backend cache so the stub actually gets
    # exercised instead of a cached None/model from a previous test/run.
    monkeypatch.setattr(tier10, "_st_model", None)
    monkeypatch.setattr(tier10, "_st_failed", False)


def _long_prose() -> str:
    return "This is a sentence with more than ten characters. " * 8


@pytest.fixture(autouse=True)
def _reset_tier10_backend_cache():
    """Ensure every test in this module starts from a clean backend cache and
    leaves a clean cache behind, so ordering relative to other tier10 tests
    (e.g. validation/test_tier10_optional.py) can't leak state either way."""
    yield
    tier10._st_model = None
    tier10._st_failed = False


def test_get_st_model_uses_stub_backend_and_logs_choice(monkeypatch, caplog):
    _install_fake_sentence_transformers(monkeypatch)

    with caplog.at_level(logging.INFO, logger="original.features.tier10"):
        model = tier10._get_st_model()

    assert isinstance(model, _FakeSentenceTransformer)
    assert model.model_name == "all-MiniLM-L6-v2"
    assert any(
        "using sentence-transformers backend" in rec.message for rec in caplog.records
    ), "expected the ST backend-choice log line to fire"

    # Cached on the second call — no re-instantiation, same object returned.
    model2 = tier10._get_st_model()
    assert model2 is model


def test_extract_tier10_standalone_bounded_and_deterministic_with_st_backend(monkeypatch):
    _install_fake_sentence_transformers(monkeypatch)

    doc = TextDoc(_long_prose())
    r1 = tier10.extract_tier10_standalone(doc)
    r2 = tier10.extract_tier10_standalone(doc)

    assert "semantic_field_dispersion" in r1
    v1 = r1["semantic_field_dispersion"]
    v2 = r2["semantic_field_dispersion"]
    assert isinstance(v1, float)
    assert 0.0 <= v1 <= 1.0
    assert v1 == v2  # deterministic across repeated calls on the same input


def test_extract_tier10_profile_uses_st_embeddings(monkeypatch):
    _install_fake_sentence_transformers(monkeypatch)

    doc = TextDoc(_long_prose())
    profile = tier10.extract_tier10_profile(doc)

    assert "_semantic_embeddings" in profile
    embs = profile["_semantic_embeddings"]
    assert isinstance(embs, np.ndarray)
    assert embs.ndim == 2
    assert embs.shape[1] == EMBED_DIM

    # Deterministic across calls.
    profile2 = tier10.extract_tier10_profile(doc)
    np.testing.assert_array_equal(embs, profile2["_semantic_embeddings"])


def test_compute_tier10_comparison_bounded_and_deterministic_with_st_backend(monkeypatch):
    _install_fake_sentence_transformers(monkeypatch)

    base_doc = TextDoc("Baseline paragraph one is here. Baseline paragraph two follows. " * 3)
    sub_doc = TextDoc("Submission paragraph one appears. Submission paragraph two appears. " * 3)

    base_profile = tier10.extract_tier10_profile(base_doc)
    sub_profile = tier10.extract_tier10_profile(sub_doc)

    baseline_profiles = {
        "_semantic_embeddings_list": [base_profile["_semantic_embeddings"]],
    }

    c1 = tier10.compute_tier10_comparison(sub_profile, baseline_profiles)
    c2 = tier10.compute_tier10_comparison(sub_profile, baseline_profiles)

    assert "semantic_centroid_proximity" in c1
    score1 = c1["semantic_centroid_proximity"]
    score2 = c2["semantic_centroid_proximity"]
    assert isinstance(score1, float)
    assert 0.0 <= score1 <= 1.0
    assert score1 == score2  # deterministic across repeated calls


def test_st_backend_falls_back_cleanly_when_encode_raises(monkeypatch):
    """If the ST backend errors at encode time, _encode_sentences should fall
    back to the TF-IDF path rather than propagating the exception."""

    class _RaisingSentenceTransformer:
        def __init__(self, model_name: str) -> None:
            pass

        def encode(self, sentences, normalize_embeddings=True):
            raise RuntimeError("simulated ST encode failure")

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = _RaisingSentenceTransformer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.setattr(tier10, "_st_model", None)
    monkeypatch.setattr(tier10, "_st_failed", False)

    doc = TextDoc(_long_prose())
    result = tier10.extract_tier10_standalone(doc)

    assert "semantic_field_dispersion" in result
    assert 0.0 <= result["semantic_field_dispersion"] <= 1.0


# ── `_get_st_model` failure arms ─────────────────────────────────────────────


def test_get_st_model_caches_failure_and_short_circuits(monkeypatch):
    """Once `_st_failed` is set, subsequent calls must return None immediately
    without re-attempting the (expensive) import/instantiation — branch:
    `if _st_failed: return None`."""
    monkeypatch.setattr(tier10, "_st_model", None)
    monkeypatch.setattr(tier10, "_st_failed", True)

    calls = {"n": 0}

    def _boom(model_name):
        calls["n"] += 1
        raise RuntimeError("should never be called — failure is cached")

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = _boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    result = tier10._get_st_model()

    assert result is None
    assert calls["n"] == 0


def test_get_st_model_handles_load_failure_and_caches_it(monkeypatch, caplog):
    """A genuine import/load failure (package missing, or the model download
    unreachable) must be caught, logged, and remembered in `_st_failed` so it
    isn't retried on every call."""
    monkeypatch.setattr(tier10, "_st_model", None)
    monkeypatch.setattr(tier10, "_st_failed", False)
    # Setting sys.modules[name] = None is the standard idiom for forcing
    # `import name` to raise ImportError without needing the real package
    # to actually be absent.
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    with caplog.at_level(logging.INFO, logger="original.features.tier10"):
        result = tier10._get_st_model()

    assert result is None
    assert tier10._st_failed is True
    assert any(
        "sentence-transformers unavailable" in rec.message for rec in caplog.records
    ), "expected the ST backend-unavailable log line to fire"

    # Second call short-circuits via the cached-failure branch above.
    result2 = tier10._get_st_model()
    assert result2 is None


# ── `_tfidf_encode` arms (unit-tested directly) ──────────────────────────────


def test_tfidf_encode_returns_none_for_fewer_than_two_sentences():
    assert tier10._tfidf_encode([]) is None
    assert tier10._tfidf_encode(["only one sentence here"]) is None


def test_tfidf_encode_with_provided_vocab_uses_transform_not_fit():
    """When a fitted vocabulary is supplied, `_tfidf_encode` must call
    `.transform()` on it rather than fitting a new vocabulary — this is the
    shared-feature-space path `compute_tier10_comparison` relies on."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    fitted = TfidfVectorizer(
        min_df=1, max_features=300, sublinear_tf=True, strip_accents="unicode"
    )
    fitted.fit(["The quick brown fox jumps.", "Over the lazy dog again."])

    result = tier10._tfidf_encode(
        ["A new sentence entirely different.", "Another new sentence here too."],
        vocab=fitted,
    )

    assert result is not None
    assert result.shape[0] == 2
    assert result.shape[1] == len(fitted.vocabulary_)


def test_tfidf_encode_returns_none_when_vectorizer_raises():
    """Symbol-only sentences leave scikit-learn with an empty vocabulary,
    which raises ValueError inside the try block — must degrade to None."""
    result = tier10._tfidf_encode(["!!!", "???"])
    assert result is None


# ── `_encode_sentences` model-absent arm ─────────────────────────────────────


def test_encode_sentences_uses_tfidf_when_model_is_none(monkeypatch):
    """When `_get_st_model()` returns None (no ST backend at all, as opposed
    to it raising at encode time), `_encode_sentences` must skip straight to
    the TF-IDF path — branch: `if model is not None` false arm."""
    monkeypatch.setattr(tier10, "_get_st_model", lambda: None)

    doc = TextDoc(_long_prose())
    result = tier10._encode_sentences(doc)

    assert result is not None
    assert result.ndim == 2


def test_tfidf_fallback_produces_real_non_neutral_dispersion(monkeypatch):
    """CLAUDE.md pins this: the TF-IDF fallback is a genuine implementation,
    not a placeholder — it must produce a real, non-neutral dispersion value
    when the ST backend is simply absent (not merely too-few-sentences)."""
    monkeypatch.setattr(tier10, "_get_st_model", lambda: None)

    text = (
        "The cat sat on the warm mat by the window. "
        "The cat chased a small mouse across the yard. "
        "A dog barked loudly at the passing mail truck. "
        "Sunlight filtered through the tall green trees. "
        "The old library smelled of dust and ancient paper. "
    )
    doc = TextDoc(text)
    result = tier10.extract_tier10_standalone(doc)

    dispersion = result["semantic_field_dispersion"]
    assert dispersion != 0.5, "0.5 must only fire on too-few-usable-sentences, not a missing backend"
    assert 0.0 <= dispersion <= 1.0


# ── `extract_tier10_profile` too-short arm ───────────────────────────────────


def test_extract_tier10_profile_returns_zero_array_when_too_short():
    doc = TextDoc("Hi.")
    profile = tier10.extract_tier10_profile(doc)

    embs = profile["_semantic_embeddings"]
    assert isinstance(embs, np.ndarray)
    assert embs.shape == (1, 384)
    assert np.all(embs == 0.0)


# ── `compute_tier10_comparison` remaining arms ───────────────────────────────


def test_compute_tier10_comparison_clears_mismatched_dimensions_and_rebuilds():
    """Pre-computed embeddings whose vector widths disagree (e.g. two TF-IDF
    encodings fit on different independent vocabularies) must be discarded so
    the function falls through to the shared-vocabulary TF-IDF rebuild path,
    rather than comparing incompatible vector spaces."""
    rng = np.random.default_rng(0)
    sub_profile = {
        "_semantic_embeddings": rng.random((2, 50)).astype(np.float32),
        "_sentences": ["Sub sentence one here about foxes.", "Sub sentence two here about dogs."],
    }
    baseline_profiles = {
        "_semantic_embeddings_list": [rng.random((2, 10)).astype(np.float32)],
        "_sentences_list": [
            ["Base sentence one here about cats.", "Base sentence two here about birds."]
        ],
    }

    result = tier10.compute_tier10_comparison(sub_profile, baseline_profiles)

    assert "semantic_centroid_proximity" in result
    assert 0.0 <= result["semantic_centroid_proximity"] <= 1.0


def test_compute_tier10_comparison_returns_neutral_when_rebuild_has_too_few_sentences():
    """The TF-IDF rebuild path itself requires >= 2 sentences per group; a
    single-sentence submission or baseline group must degrade to the neutral
    fallback rather than raise."""
    sub_profile = {"_sentences": ["Only one sentence."]}
    baseline_profiles = {"_sentences_list": [["Only one baseline sentence."]]}

    result = tier10.compute_tier10_comparison(sub_profile, baseline_profiles)

    assert result == {"semantic_centroid_proximity": 0.5}


def test_compute_tier10_comparison_returns_neutral_when_vectorizer_fit_raises():
    """A shared-vocabulary fit across symbol-only sentences leaves scikit-learn
    with an empty vocabulary, raising inside the rebuild `try` block — must
    degrade to the neutral fallback rather than propagate."""
    sub_profile = {"_sentences": ["!!!", "???"]}
    baseline_profiles = {"_sentences_list": [["@@@", "###"]]}

    result = tier10.compute_tier10_comparison(sub_profile, baseline_profiles)

    assert result == {"semantic_centroid_proximity": 0.5}
