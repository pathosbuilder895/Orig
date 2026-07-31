"""
validation/attribution/delta.py — distance-based attribution engines
(Burrows'-Delta family), validation-layer only.

Both engines normalize at CANDIDATE-POOL level: features are z-scored
against the spread of the candidates' centroids/profiles, never against a
single author's own baseline spread. That is the structural difference
from the raw argmin-of-own-z rule the Instrument Report retired — a loose
per-author baseline cannot become an attribution black hole here.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

_SD_FLOOR = 1e-9


def cosine_delta_attribution(
    baseline_matrices: dict[str, np.ndarray],
    test_vector: np.ndarray,
    feature_indices: Sequence[int],
) -> tuple[str, dict[str, float]]:
    """
    Nearest-centroid by cosine distance in pool-z-scored feature space.

    baseline_matrices: {author: (n_docs, FEATURE_DIM)} raw feature rows
      (one row per baseline document, e.g. from feature_vector()).
    test_vector: (FEATURE_DIM,) raw features of the disputed document.
    feature_indices: which columns to use — pass
      validation.measurability.measurable_indices(corpus) so blank columns
      can never contribute.

    Returns (predicted_author, {author: cosine_distance}); lower = closer.
    """
    idx = np.asarray(list(feature_indices), dtype=int)
    if idx.size == 0:
        raise ValueError(
            "attribution cannot proceed with no feature columns selected "
            "(feature_indices is empty)"
        )

    test_vector = np.asarray(test_vector, dtype=float)
    test_selected = test_vector[idx]
    if not np.all(np.isfinite(test_selected)):
        raise ValueError(
            "attribution cannot proceed: test_vector has non-finite values "
            "(NaN/Inf) in the selected feature columns"
        )

    for a, m in baseline_matrices.items():
        if m.shape[0] == 0:
            continue
        if not np.all(np.isfinite(m[:, idx])):
            raise ValueError(
                f"attribution cannot proceed: baseline matrix for author "
                f"{a!r} has non-finite values (NaN/Inf) in the selected "
                f"feature columns"
            )

    centroids = {
        a: m[:, idx].mean(axis=0)
        for a, m in baseline_matrices.items()
        if m.shape[0] > 0
    }
    if len(centroids) < 2:
        raise ValueError(
            f"attribution needs >= 2 candidates with baseline docs, got {len(centroids)}"
        )
    names = sorted(centroids)
    pool = np.vstack([centroids[a] for a in names])
    mu = pool.mean(axis=0)
    sd = np.maximum(pool.std(axis=0, ddof=0), _SD_FLOOR)
    pool_z = (pool - mu) / sd
    test_z = (test_selected - mu) / sd

    distances = {
        a: _cosine_distance(pool_z[i], test_z) for i, a in enumerate(names)
    }
    predicted = min(distances, key=distances.get)
    return predicted, distances


def _cosine_distance(u: np.ndarray, v: np.ndarray) -> float:
    nu, nv = np.linalg.norm(u), np.linalg.norm(v)
    if nu == 0.0 or nv == 0.0:
        return 1.0
    return 1.0 - float(np.dot(u, v) / (nu * nv))
