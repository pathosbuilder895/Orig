"""
Tier 10 optional dependency — smoke tests.

This file lives under `validation/` (not `tests/`) so it can be run without
`tests/conftest.py` and without importing the full FastAPI/SQLAlchemy app stack
(useful in minimal environments). Full integration tests remain in `tests/`.

Run: pytest validation/test_tier10_optional.py -q
"""

import numpy as np

from original.features.tier1 import TextDoc
from original.features.tier10 import (
    compute_tier10_comparison,
    extract_tier10_profile,
    extract_tier10_standalone,
)
from original.features.pipeline import compute_full_features


def _long_prose() -> str:
    return "This is a sentence with more than ten characters. " * 8


def test_tier10_standalone_never_raises() -> None:
    d = TextDoc(_long_prose())
    r = extract_tier10_standalone(d)
    assert "semantic_field_dispersion" in r
    v = r["semantic_field_dispersion"]
    assert isinstance(v, float)
    assert 0.0 <= v <= 1.0


def test_tier10_profile_and_comparison_never_raise() -> None:
    d = TextDoc(_long_prose())
    p = extract_tier10_profile(d)
    assert "_semantic_embeddings" in p
    emb = p["_semantic_embeddings"]
    assert isinstance(emb, np.ndarray)
    c = compute_tier10_comparison(p, {"_semantic_embeddings_list": []})
    assert c == {"semantic_centroid_proximity": 0.5}


def test_compute_full_features_with_baseline() -> None:
    base = "Baseline paragraph one. Baseline paragraph two. " * 3
    sub = "Submission paragraph one. Submission paragraph two. " * 3
    feats = compute_full_features(sub, [base])
    assert "semantic_field_dispersion" in feats
    assert "semantic_centroid_proximity" in feats
    assert 0.0 <= feats["semantic_field_dispersion"] <= 1.0
    assert 0.0 <= feats["semantic_centroid_proximity"] <= 1.0
