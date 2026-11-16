"""Per-writer line: judge a paper against the writer's own spread."""
from __future__ import annotations

import math

import numpy as np

from original.constants import (
    WRITER_LINE_MIN_PAPERS,
    WRITER_LINE_STD_FLOOR,
    WRITER_LINE_Z_THRESHOLDS,
)


def writer_z(rms_z: float, loo: list[float]) -> float | None:
    """Z of rms_z against the writer's leave-one-out mean and floored std."""
    if len(loo) < WRITER_LINE_MIN_PAPERS:
        return None
    arr = np.asarray(loo, dtype=float)
    if not math.isfinite(rms_z) or not np.all(np.isfinite(arr)):
        return None
    spread = max(float(np.std(arr)), WRITER_LINE_STD_FLOOR)
    return (rms_z - float(np.mean(arr))) / spread


def writer_line_action(z, thresholds=WRITER_LINE_Z_THRESHOLDS):
    """Map a writer z to an action tier; None abstains."""
    if z is None or not math.isfinite(z):
        return None
    for name, (lo, hi) in thresholds.items():
        if lo <= z < hi:
            return name
    return list(thresholds)[-1]
