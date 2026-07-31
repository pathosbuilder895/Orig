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

import re
from collections import Counter
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


_WORD_RE = re.compile(r"[a-z']+")


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _rel_freqs(tokens: list[str], vocab: list[str]) -> np.ndarray:
    counts = Counter(tokens)
    total = len(tokens) or 1
    return np.array([counts[w] / total for w in vocab], dtype=float)


def mfw_delta_attribution(
    baseline_texts: dict[str, list[str]],
    test_text: str,
    top_n: int = 150,
) -> tuple[str, dict[str, float]]:
    """
    Classic Burrows' Delta: z-score the top_n most-frequent words' relative
    frequencies across the candidate pool; Delta(author) = mean |z_test -
    z_author|. Independent of the feature pipeline by design — the "cheap
    but robust" cross-check engine, computed straight from raw text with no
    dependency on original.* or the 109-feature pipeline.

    Two degenerate-input guards mirror the ones cosine_delta_attribution
    needed (see its docstring/fix history):
    - A candidate with an entirely empty list of baseline texts cannot
      contribute a profile (np.mean of an empty list is NaN), so it is
      dropped before the pool is built — mirroring cosine_delta_attribution's
      skip of empty baseline matrices — and the >=2-candidate floor is
      re-checked against what remains.
    - If the pooled vocabulary comes out empty (every baseline text has no
      [a-z'] word characters at all), every candidate's Delta would be an
      identical 0.0 and min() would silently return the alphabetically-first
      candidate; raise instead of returning that confident-looking but
      arbitrary answer.

    A baseline text (or the test text) that individually tokenizes to
    nothing is NOT an error: _rel_freqs falls back to an all-zero relative-
    frequency vector for it (via `total = len(tokens) or 1`) rather than
    dividing by zero, so a candidate with at least one usable baseline doc,
    or a test document with no recognizable words, still gets a real
    (if less certain) attribution instead of a crash.
    """
    if len(baseline_texts) < 2:
        raise ValueError(
            f"attribution needs >= 2 candidates, got {len(baseline_texts)}"
        )

    non_empty = {a: docs for a, docs in baseline_texts.items() if len(docs) > 0}
    if len(non_empty) < 2:
        raise ValueError(
            f"attribution needs >= 2 candidates with baseline docs, got {len(non_empty)}"
        )

    pooled: Counter = Counter()
    for docs in non_empty.values():
        for doc in docs:
            pooled.update(_tokens(doc))
    vocab = [w for w, _ in pooled.most_common(top_n)]
    if not vocab:
        raise ValueError(
            "attribution cannot proceed: pooled vocabulary is empty (no "
            "word characters found across any baseline text)"
        )

    names = sorted(non_empty)
    profiles = np.vstack([
        np.mean([_rel_freqs(_tokens(d), vocab) for d in non_empty[a]], axis=0)
        for a in names
    ])
    mu = profiles.mean(axis=0)
    sd = np.maximum(profiles.std(axis=0, ddof=0), _SD_FLOOR)
    profiles_z = (profiles - mu) / sd
    test_z = (_rel_freqs(_tokens(test_text), vocab) - mu) / sd

    deltas = {
        a: float(np.mean(np.abs(test_z - profiles_z[i])))
        for i, a in enumerate(names)
    }
    return min(deltas, key=deltas.get), deltas
