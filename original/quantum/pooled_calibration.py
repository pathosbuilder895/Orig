"""Population-calibrated typicality reference (Phase 1, opt-in).

Per-student conformal p-values are quantised at 1/(N+1), so with a
realistic pilot N (5-30 submissions) the smallest reachable p-value is
0.032-0.167 while the band thresholds need 0.005-0.03. The typicality
axis is therefore inert at pilot scale — see the reachability table in
docs/superpowers/plans/2026-07-31-pilot-scale-reachability.md.

Pooling every student's same-author LOO distances into one reference
distribution raises N into the hundreds immediately. The pooling is only
legitimate because rms_z is already standardised against each student's
own baseline spread, so a distance of 1.4 means the same thing for a
tight writer and a variable one. That assumption is not taken on faith:
Task 7 checks it empirically before this mode is trusted.
"""

from __future__ import annotations

import numpy as np


def build_pooled_reference(
    per_student_distances: list[np.ndarray],
    min_students: int = 3,
    min_total: int = 30,
) -> np.ndarray | None:
    """Sorted pooled reference, or None when there is too little data.

    Returning None is load-bearing: the caller falls back to per-student
    self-calibration rather than computing a confident-looking p-value
    against a reference too thin to support one.
    """
    contributions = []
    for d in per_student_distances:
        arr = np.asarray(d, dtype=float).ravel()
        arr = arr[np.isfinite(arr)]
        if arr.size:
            contributions.append(arr)

    if len(contributions) < min_students:
        return None

    pooled = np.concatenate(contributions)
    if pooled.size < min_total:
        return None

    return np.sort(pooled)


def pooled_reference_stats(ref: np.ndarray | None) -> dict:
    """Diagnostics for the report — including the p-value floor this
    reference makes reachable, which is the whole point of pooling."""
    if ref is None or len(ref) == 0:
        return {"n": 0, "p_floor": 1.0, "n_students": None}
    n = int(len(ref))
    return {"n": n, "p_floor": 1.0 / (n + 1), "n_students": None}
