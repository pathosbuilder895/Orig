"""
validation/power.py — statistical floors and ceilings for gate verdicts.

Every reported validation number is a statistical quantity with a known
floor/ceiling given N. A gate that "passes" because its criterion is
arithmetically unreachable at the current corpus size is UNINFORMATIVE,
not passing — these helpers let gate code tell the difference and print
the limitation instead of the flattering number.

Conformal p-values (original/quantum/typicality.py) are ranks over N
leave-one-out distances: p ∈ {1/(N+1), ..., 1}. Nothing can produce a
p below 1/(N+1), so an action band at threshold t is reachable only when
1/(N+1) <= t.
"""
from __future__ import annotations

import math


def conformal_p_floor(n: int) -> float:
    """Smallest conformal p-value reachable with n calibration samples."""
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    return 1.0 / (n + 1)


def band_reachable(n: int, threshold: float) -> bool:
    """Can a conformal p-value computed from n samples ever be <= threshold?"""
    return conformal_p_floor(n) <= threshold


def min_docs_for_band(threshold: float) -> int:
    """Smallest n for which band_reachable(n, threshold) holds."""
    if threshold <= 0:
        raise ValueError(f"threshold must be positive, got {threshold}")
    return math.ceil(1.0 / threshold) - 1


def rule_of_three_upper(n: int) -> float:
    """
    95% upper confidence bound on a true rate when 0 events were observed
    in n trials (the rule of three). An observed 0/n flagged rate can never
    demonstrate an FPR below this.
    """
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    return 3.0 / n


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """
    Wilson score interval for a binomial proportion (default 95%).

    Preferred over the normal approximation because it stays inside [0, 1]
    and behaves at the extremes — both of which matter at the corpus sizes
    this project actually has (n = 22 held-out essays for G3).

    The closed form is analytically within [0, 1] but not numerically: at
    successes=0 the lower bound evaluates to ≈ -3.1e-17 (verified), so the
    result is clamped. Without the clamp a caller checking `lo >= 0` — or
    formatting the bound for a report — sees a negative probability.
    """
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    if not 0 <= successes <= n:
        raise ValueError(f"successes must be in [0, {n}], got {successes}")
    p = successes / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    lo = max(0.0, (center - margin) / denom)
    hi = min(1.0, (center + margin) / denom)
    return (lo, hi)


def bar_decidable(successes: int, n: int, bar: float, z: float = 1.96) -> str:
    """
    Can this many trials decide whether the true rate clears `bar`?

    Returns "above" (whole CI above the bar), "below" (whole CI below), or
    "undecided" (CI straddles it — the observation is compatible with both
    sides, so neither a pass nor a fail is evidence).

    This is the sampling-uncertainty analogue of band_reachable(): G1 cannot
    flag because of an arithmetic floor; G3 cannot demonstrate a pass at
    n=22 because the interval is wider than the distance to the bar.
    """
    lo, hi = wilson_interval(successes, n, z)
    if lo > bar:
        return "above"
    if hi < bar:
        return "below"
    return "undecided"
