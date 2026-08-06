"""validation/verify/feature_cache.py -- persistent feature-vector cache.

FeatureCache itself is pure (no multiprocessing, no model dependency) and
fully covered here. extract_many's cache-hit path is covered without
invoking the real feature pipeline or a process pool, by pre-populating the
cache so every requested text is already a hit -- exercising the real
extraction path (subprocess-spawned feature_vector calls) is a slow,
model-dependent smoke test left to manual runs, the same way this repo
treats other heavyweight corpus/model pipelines (e.g. gutenberg_corpus.py's
network fetches)."""

from __future__ import annotations

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from validation.verify.feature_cache import FeatureCache, extract_many


def test_cache_miss_then_hit(tmp_path):
    cache = FeatureCache(tmp_path / "cache.npz")
    assert cache.get("hello") is None
    vector = np.linspace(0.0, 1.0, FEATURE_DIM)
    cache.put("hello", vector)
    np.testing.assert_array_equal(cache.get("hello"), vector)


def test_put_rejects_wrong_shape(tmp_path):
    cache = FeatureCache(tmp_path / "cache.npz")
    with pytest.raises(ValueError, match="invalid feature vector shape"):
        cache.put("hello", np.zeros(FEATURE_DIM - 1))


def test_save_and_reload_round_trips(tmp_path):
    path = tmp_path / "cache.npz"
    cache = FeatureCache(path)
    v1 = np.linspace(0.0, 1.0, FEATURE_DIM)
    v2 = np.linspace(1.0, 0.0, FEATURE_DIM)
    cache.put("first text", v1)
    cache.put("second text", v2)
    cache.save()

    reloaded = FeatureCache(path)
    np.testing.assert_allclose(reloaded.get("first text"), v1)
    np.testing.assert_allclose(reloaded.get("second text"), v2)
    assert reloaded.get("unseen text") is None


def test_different_texts_get_different_keys(tmp_path):
    cache = FeatureCache(tmp_path / "cache.npz")
    v = np.linspace(0.0, 1.0, FEATURE_DIM)
    cache.put("text A", v)
    assert cache.get("text B") is None  # no accidental collision/prefix match


def test_incompatible_feature_dim_raises(tmp_path):
    import json

    path = tmp_path / "cache.npz"
    np.savez_compressed(
        path,
        metadata=json.dumps({"schema": "original.feature_cache.v1", "feature_dim": 1}),
        keys=np.asarray([]),
        vectors=np.empty((0, 1)),
    )
    with pytest.raises(ValueError, match="FEATURE_DIM"):
        FeatureCache(path)


def test_extract_many_dedupes_and_uses_cache_hits(tmp_path):
    """Every requested text is pre-cached, so extract_many must return
    results purely from cache hits -- no real extraction, no process pool
    spawned -- while still deduplicating repeated texts."""
    cache = FeatureCache(tmp_path / "cache.npz")
    va = np.linspace(0.0, 1.0, FEATURE_DIM)
    vb = np.linspace(1.0, 0.0, FEATURE_DIM)
    cache.put("alpha", va)
    cache.put("beta", vb)

    result = extract_many(["alpha", "beta", "alpha", "beta", "alpha"], cache=cache)

    assert set(result) == {"alpha", "beta"}
    np.testing.assert_allclose(result["alpha"], va)
    np.testing.assert_allclose(result["beta"], vb)


def test_extract_many_empty_input():
    cache = FeatureCache.__new__(FeatureCache)
    cache.values = {}
    cache.path = None
    assert extract_many([], cache=cache) == {}
