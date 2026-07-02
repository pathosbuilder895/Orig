"""
null_models.py — fit an explicit "not this student" distribution.

The evaluator in binary_auc.py measures how well Original separates
same-author from different-author submissions using ``deviation_score``
(a monotone function of "distance from the CLAIMED author's baseline").
That is an approximation of −log P(ξ | H₁) — it says nothing about what
"different" should look like, so there is no way to guarantee a false-
positive rate at any threshold.

This module fits the missing null hypothesis: an EMPIRICAL IMPOSTOR
COHORT. Pool the baseline feature vectors of every author OTHER than the
one being verified, fit a per-feature diagonal Gaussian (mu_null,
sigma_null), and hand that to ``original.quantum.scoring.score()`` via
its ``impostor_stats`` parameter. ``score()`` then computes
``llr_deviation_score`` — the bounded log-likelihood-ratio proxy defined
in ``_llr_deviation`` there — alongside the existing deviation_score,
without changing it.

Kept deliberately simple: diagonal Gaussian, not a full-covariance or
mixture model. A GMM-UBM upgrade (Reynolds 2000, the classical forensic
speaker-verification technique) is the natural next step if the impostor
Gaussian under-performs — same interface, just a richer p(ξ|H0).
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np


def fit_impostor_gaussian(vectors: List[np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
    """
    Fit a per-feature diagonal Gaussian (mu, sigma) from a pool of
    impostor baseline vectors.

    Args:
        vectors: list of raw (not necessarily unit-normalised) feature
            vectors, each shape (FEATURE_DIM,), drawn from every author
            OTHER than the one being verified.

    Returns:
        (mu, sigma), each shape (FEATURE_DIM,). sigma is floored at
        0.005 — the same floor ``StudentState.baseline_std`` uses — so a
        feature that happens to be constant across the whole impostor
        pool doesn't produce a divide-by-near-zero z-score.
    """
    if not vectors:
        raise ValueError("fit_impostor_gaussian: need at least 1 impostor vector")
    stacked = np.stack(vectors).astype(np.float64)   # (N, D)
    mu = stacked.mean(axis=0)
    sigma = stacked.std(axis=0)
    sigma = np.maximum(sigma, 0.005)
    return mu, sigma
