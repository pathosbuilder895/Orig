"""Pure-numpy metrics for the short-baseline operating-point harness.

No I/O, no original.* imports — unit-testable in CI without any corpus.
Deviation convention: LOWER = more same-author-like, so an impostor is
"caught" when its score is ABOVE the honest-quantile threshold.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CatchResult:
    threshold: float
    catch_rate: float
    false_flag_rate: float
    n_honest: int
    n_impostor: int


def auc(honest: np.ndarray, impostor: np.ndarray) -> float:
    """P(random impostor scores above random honest); ties count 1/2."""
    honest = np.asarray(honest, dtype=float)
    impostor = np.asarray(impostor, dtype=float)
    if honest.size == 0 or impostor.size == 0:
        raise ValueError("auc needs non-empty honest and impostor arrays")
    wins = (impostor[:, None] > honest[None, :]).sum()
    ties = (impostor[:, None] == honest[None, :]).sum()
    return float((wins + 0.5 * ties) / (impostor.size * honest.size))


def catch_at_budget(
    honest: np.ndarray, impostor: np.ndarray, budget: float = 0.05
) -> CatchResult:
    """Threshold = (1-budget) quantile of honest; catch = frac impostors above."""
    honest = np.asarray(honest, dtype=float)
    impostor = np.asarray(impostor, dtype=float)
    if honest.size == 0 or impostor.size == 0:
        raise ValueError("catch_at_budget needs non-empty honest and impostor arrays")
    thr = float(np.quantile(honest, 1.0 - budget, method="higher"))
    return CatchResult(
        threshold=thr,
        catch_rate=float((impostor > thr).mean()),
        false_flag_rate=float((honest > thr).mean()),
        n_honest=int(honest.size),
        n_impostor=int(impostor.size),
    )


def bootstrap_ci(
    honest: np.ndarray,
    impostor: np.ndarray,
    metric: str,
    n_boot: int = 1000,
    seed: int = 0,
    budget: float = 0.05,
) -> tuple[float, float]:
    """Percentile-bootstrap 95% CI over resampled honest AND impostor sets."""
    honest = np.asarray(honest, dtype=float)
    impostor = np.asarray(impostor, dtype=float)
    rng = np.random.default_rng(seed)
    vals = np.empty(n_boot)
    for b in range(n_boot):
        h = honest[rng.integers(0, honest.size, honest.size)]
        i = impostor[rng.integers(0, impostor.size, impostor.size)]
        vals[b] = auc(h, i) if metric == "auc" else catch_at_budget(h, i, budget).catch_rate
    return float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))
