"""Per-writer line: judge a paper against the writer's own spread."""
from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable

import numpy as np

from original.constants import (
    WRITER_LINE_MIN_PAPERS,
    WRITER_LINE_STD_FLOOR,
    WRITER_LINE_Z_THRESHOLDS,
)


def writer_z(value: float, reference: list[float]) -> float | None:
    """Z of value against the reference's mean and floored population std."""
    if len(reference) < WRITER_LINE_MIN_PAPERS:
        return None
    arr = np.asarray(reference, dtype=float)
    if not math.isfinite(value) or not np.all(np.isfinite(arr)):
        return None
    spread = max(float(np.std(arr)), WRITER_LINE_STD_FLOOR)
    return (value - float(np.mean(arr))) / spread


def loo_deviation_scores(state, score_fn: Callable, **score_kwargs) -> list[float]:
    """Leave-one-out deviation_score of each contributing baseline paper.

    Paper i is scored by ``score_fn`` against a fresh StudentState built from
    the writer's other contributing papers (same order, same auth weights),
    with the caller's scoring arguments and the writer line forced off.
    ``state`` is not mutated (samples are shallow-copied). Returns [] below
    WRITER_LINE_MIN_PAPERS contributing papers or if any inner score raises
    or is non-finite. Costs one score_fn call per contributing paper.
    """
    from .scoring import ScoringConfig
    from .state import StudentState

    contributing = [s for s in state.samples if s.auth_weight > 0]
    if len(contributing) < WRITER_LINE_MIN_PAPERS:
        return []
    kwargs = dict(score_kwargs)
    config = kwargs.pop("scoring_config", None) or ScoringConfig()
    kwargs["scoring_config"] = dataclasses.replace(config, writer_line="off")
    kwargs.pop("submission_id", None)
    out: list[float] = []
    try:
        from original.constants import ALL_FEATURE_CODES

        for i, held in enumerate(contributing):
            others = [dataclasses.replace(s) for j, s in enumerate(contributing) if j != i]
            inner = StudentState(
                student_id=state.student_id, samples=others, baseline_kappa=state.baseline_kappa
            )
            vec = np.asarray(held.vector, dtype=float)
            fd = {c: float(v) for c, v in zip(ALL_FEATURE_CODES, vec, strict=False)}
            res = score_fn(inner, vec, fd, submission_id=f"loo:{i}", **kwargs)
            d = float(res.authorship.deviation_score)
            if not math.isfinite(d):
                return []
            out.append(d)
    except Exception:
        return []
    return out


def writer_line_action(
    z: float | None, thresholds=WRITER_LINE_Z_THRESHOLDS
) -> str | None:
    """Map a writer z to an action tier; None abstains."""
    if z is None or not math.isfinite(z):
        return None
    names = list(thresholds)
    for name in names:
        lo, hi = thresholds[name]
        if lo <= z < hi:
            return name
    if z < thresholds[names[0]][0]:
        return names[0]
    return names[-1]
