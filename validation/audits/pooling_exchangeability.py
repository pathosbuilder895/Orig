"""Is a pooled typicality reference legitimate on this population?

Pooling rms_z across students assumes the standardisation already made
them comparable. If between-student variance dominates within-student
variance, it did not, and a pooled p-value would be systematically wrong
for the students furthest from the pooled centre.
"""

from __future__ import annotations

import numpy as np
from scipy import stats

_MIN_STUDENTS = 3
_MIN_PER_STUDENT = 2
_RATIO_LIMIT = 1.0   # between-student variance must not exceed within
_KS_LIMIT = 0.5      # no student may be this far from the pooled rest


def assess_exchangeability(per_student_distances) -> dict:
    usable = []
    for d in per_student_distances:
        arr = np.asarray(d, dtype=float).ravel()
        arr = arr[np.isfinite(arr)]
        if arr.size >= _MIN_PER_STUDENT:
            usable.append(arr)

    if len(usable) < _MIN_STUDENTS:
        return {
            "between_within_variance_ratio": None,
            "ks_max_pairwise": None,
            "verdict": "insufficient",
            "n_students": len(usable),
        }

    means = np.array([a.mean() for a in usable])
    between = float(means.var(ddof=1))
    within = float(np.mean([a.var(ddof=1) for a in usable if a.size > 1]))
    ratio = between / within if within > 0 else float("inf")

    ks_max = 0.0
    for i, arr in enumerate(usable):
        rest = np.concatenate([a for j, a in enumerate(usable) if j != i])
        ks_max = max(ks_max, float(stats.ks_2samp(arr, rest).statistic))

    verdict = "exchangeable" if (ratio <= _RATIO_LIMIT and ks_max <= _KS_LIMIT) else "heterogeneous"
    return {
        "between_within_variance_ratio": ratio,
        "ks_max_pairwise": ks_max,
        "verdict": verdict,
        "n_students": len(usable),
    }
