"""Research implementation of Ross-style Dirichlet-multinomial drift.

This module is validation-only.  It models function-word count vectors with
either constant concentration parameters or log-linear concentrations over
time.  It does not participate in production scoring.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import random
import re

import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln

from original.constants import FUNCTION_WORDS


DEFAULT_VOCABULARY = tuple(sorted(FUNCTION_WORDS))


@dataclass
class DirichletMultinomialComparison:
    selected_model: str
    constant_log_likelihood: float
    drift_log_likelihood: float
    constant_bic: float
    drift_bic: float
    bic_improvement: float
    converged_constant: bool
    converged_drift: bool
    n_documents: int
    n_categories: int
    permutation_false_selection_rate: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def count_function_words(
    text: str,
    vocabulary: tuple[str, ...] = DEFAULT_VOCABULARY,
) -> np.ndarray:
    """Count frozen function-word categories plus an ``other`` category."""
    tokens = re.findall(r"\b[a-z]+(?:'[a-z]+)?\b", text.lower())
    lookup = {word: index for index, word in enumerate(vocabulary)}
    counts = np.zeros(len(vocabulary) + 1, dtype=np.int64)
    for token in tokens:
        counts[lookup.get(token, len(vocabulary))] += 1
    return counts


def _dm_log_likelihood(counts: np.ndarray, alpha: np.ndarray) -> float:
    totals = counts.sum(axis=1)
    concentration = alpha.sum(axis=1)
    value = gammaln(concentration) - gammaln(totals + concentration)
    value += np.sum(gammaln(counts + alpha) - gammaln(alpha), axis=1)
    # The multinomial coefficient is constant across the compared models and
    # omitted, matching the paper's optimization expression.
    return float(np.sum(value))


def _initial_log_alpha(counts: np.ndarray) -> np.ndarray:
    proportions = (counts + 0.5) / (counts.sum(axis=1, keepdims=True) + 0.5 * counts.shape[1])
    mean = proportions.mean(axis=0)
    return np.log(np.maximum(mean * 30.0, 1e-4))


def _fit(counts: np.ndarray, times: np.ndarray, drift: bool) -> tuple[float, bool, int]:
    n, categories = counts.shape
    initial = _initial_log_alpha(counts)
    if drift:
        x0 = np.concatenate([initial, np.zeros(categories)])

        def objective(params: np.ndarray) -> float:
            intercept, slope = params[:categories], params[categories:]
            eta = intercept[None, :] + times[:, None] * slope[None, :]
            alpha = np.exp(np.clip(eta, -12.0, 12.0))
            # Weak slope penalty prevents tiny corpora from winning through an
            # implausibly flexible trajectory.
            return -_dm_log_likelihood(counts, alpha) + 0.5 * float(slope @ slope)

        parameter_count = 2 * categories
    else:
        x0 = initial

        def objective(params: np.ndarray) -> float:
            alpha = np.broadcast_to(
                np.exp(np.clip(params, -12.0, 12.0))[None, :], (n, categories)
            )
            return -_dm_log_likelihood(counts, alpha)

        parameter_count = categories

    result = minimize(objective, x0, method="L-BFGS-B", options={"maxiter": 500})
    return -float(result.fun), bool(result.success), parameter_count


def compare_constant_and_drift(
    counts: np.ndarray,
    times: np.ndarray | None = None,
) -> DirichletMultinomialComparison:
    counts = np.asarray(counts, dtype=np.float64)
    if counts.ndim != 2 or counts.shape[0] < 4 or counts.shape[1] < 2:
        raise ValueError("counts must be a documents×categories matrix with at least 4 documents")
    if np.any(counts < 0) or np.any(counts.sum(axis=1) <= 0):
        raise ValueError("each document must contain non-negative counts and at least one token")
    n = counts.shape[0]
    if times is None:
        times = np.linspace(0.0, 1.0, n)
    else:
        times = np.asarray(times, dtype=np.float64)
        if times.shape != (n,):
            raise ValueError("times must have one value per document")
        span = float(times.max() - times.min())
        times = (times - times.min()) / span if span > 0 else np.zeros(n)

    ll0, ok0, k0 = _fit(counts, times, False)
    ll1, ok1, k1 = _fit(counts, times, True)
    bic0 = -2.0 * ll0 + k0 * math.log(n)
    bic1 = -2.0 * ll1 + k1 * math.log(n)
    improvement = bic0 - bic1
    selected = "gradual_drift" if ok1 and improvement > 0 else "constant"
    return DirichletMultinomialComparison(
        selected_model=selected,
        constant_log_likelihood=ll0,
        drift_log_likelihood=ll1,
        constant_bic=bic0,
        drift_bic=bic1,
        bic_improvement=improvement,
        converged_constant=ok0,
        converged_drift=ok1,
        n_documents=n,
        n_categories=counts.shape[1],
    )


def permutation_false_selection_rate(
    counts: np.ndarray,
    *,
    repeats: int = 100,
    seed: int = 20260804,
) -> float:
    """Ross-style chronology permutation estimate for false drift selection."""
    matrix = np.asarray(counts)
    rng = random.Random(seed)
    selected = 0
    indices = list(range(matrix.shape[0]))
    for _ in range(repeats):
        rng.shuffle(indices)
        comparison = compare_constant_and_drift(matrix[indices])
        selected += comparison.selected_model == "gradual_drift"
    return selected / repeats
