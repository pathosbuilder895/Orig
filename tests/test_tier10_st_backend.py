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
