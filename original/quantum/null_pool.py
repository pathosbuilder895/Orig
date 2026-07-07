"""
null_pool.py — production impostor pool for the explicit null model.

The verify benchmarks (validation/benchmarks/2026-07-01/*nullmodel*) showed
that ranking by the relative llr_deviation_score instead of the absolute
deviation_score lifts seminary median per-author AUC 0.8125 → 1.0 (pooled
0.8925 → 0.9325) and cuts Brier 0.51 → 0.17. The scoring hook has existed
since the rank-and-null work (scoring.py:_llr_deviation, gated by
NULL_MODEL=impostor + an impostor_stats argument) — but only the validation
harness ever supplied impostor_stats. This module builds the same pool from
the live store so the API path can too.

The cohort is the claimed student's OWN TENANT: every other student in the
same school with authenticated baseline samples. That mirrors what the
benchmark measured (other seminary authors as the impostor pool) and is
genre-matched by construction — a seminary's essays are compared against
seminary essays, not Gutenberg prose. Cross-tenant vectors are never pooled
(same isolation rule as every other tenant-scoped read).

Cold-start guards: with too few other students the diagonal Gaussian is
meaningless, so we return None and llr_deviation_score simply stays None —
identical to the flag-off response shape. No score is ever blocked or
degraded by an absent pool.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from ..principal import tenant_of
from .state import StudentState

# Below these floors a per-feature mean/std over the pool is noise, not a
# null hypothesis. 3 students / 5 vectors matches the spirit of the
# "escalate suppressed under 5 baselines" policy: weak evidence widens
# nothing, it just abstains.
MIN_IMPOSTOR_STUDENTS = 3
MIN_IMPOSTOR_VECTORS = 5

# Same floor StudentState.baseline_std and _llr_deviation use.
SIGMA_FLOOR = 0.005


def fit_impostor_gaussian(vectors: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """
    Fit a per-feature diagonal Gaussian (mu, sigma) from a pool of
    impostor baseline vectors.

    Args:
        vectors: feature vectors, each shape (FEATURE_DIM,), drawn from
            authors OTHER than the one being verified.

    Returns:
        (mu, sigma), each shape (FEATURE_DIM,). sigma is floored at 0.005
        so a feature that is constant across the whole pool doesn't produce
        a divide-by-near-zero z-score.
    """
    if not vectors:
        raise ValueError("fit_impostor_gaussian: need at least 1 impostor vector")
    stacked = np.stack(vectors).astype(np.float64)  # (N, D)
    mu = stacked.mean(axis=0)
    sigma = stacked.std(axis=0)
    sigma = np.maximum(sigma, SIGMA_FLOOR)
    return mu, sigma


def build_impostor_stats(
    claimed_student_id: str,
    states: Iterable[StudentState],
) -> tuple[np.ndarray, np.ndarray] | None:
    """
    Pool authenticated baseline vectors from every SAME-TENANT student other
    than the claimed one and fit the impostor Gaussian.

    Args:
        claimed_student_id: the student being verified — always excluded.
        states: candidate StudentStates (typically the whole store; tenant
            filtering happens here so callers can't get it wrong).

    Returns:
        (mu_null, sigma_null) each shape (FEATURE_DIM,), or None when the
        cohort is below MIN_IMPOSTOR_STUDENTS / MIN_IMPOSTOR_VECTORS.
    """
    claimed_tenant = tenant_of(claimed_student_id)

    vectors: list[np.ndarray] = []
    contributing_students = 0
    for state in states:
        if state.student_id == claimed_student_id:
            continue
        if tenant_of(state.student_id) != claimed_tenant:
            continue
        auth = [s.vector for s in state.samples if s.auth_weight > 0]
        if not auth:
            continue
        contributing_students += 1
        vectors.extend(auth)

    if contributing_students < MIN_IMPOSTOR_STUDENTS or len(vectors) < MIN_IMPOSTOR_VECTORS:
        return None
    return fit_impostor_gaussian(vectors)
