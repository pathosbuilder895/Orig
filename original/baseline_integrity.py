"""baseline_integrity.py — report-only baseline health diagnostic (T-70).

Summarizes how trustworthy a student's authenticated baseline is: how many
samples actually contribute, their provenance mix, the calendar span they
were collected over, whether any single sample looks like a stylistic
outlier relative to the rest (leave-one-out), and whether this student's
baseline spread is wider than the peer population's (when an impostor pool
is available).

This module never computes or touches ``deviation_score``,
``quantum_fidelity``, or any recommended action. It is purely descriptive,
for a later task to attach to a response. ``build_baseline_integrity`` is
safe to call unconditionally: any internal failure (malformed sample data,
unexpected shapes, a ``None`` state, garbage ``impostor_stats``, ...)
returns ``None`` rather than raising, mirroring the abstain-to-None
convention used elsewhere (e.g. ``style_authorship``, ``fusion``).
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from .quantum.state import StudentState
from .style_authorship import MIN_BASELINES

log = logging.getLogger(__name__)

# Modified z-score cutoff for flagging a leave-one-out distance as an
# outlier (Iglewicz & Hoaglin's standard recommendation).
LOO_OUTLIER_Z_CUTOFF = 3.5

# Constant used in the modified z-score: 0.6745 * (d - median) / MAD.
_MODIFIED_Z_CONSTANT = 0.6745

# Above this fraction of features where this student's baseline_std exceeds
# the peer pool's sigma_null, the baseline is noted as unusually spread out
# relative to peers. Deliberately a plain majority threshold, not tuned
# against any corpus — this note is descriptive, not a gate.
_SIGMA_INFLATION_NOTE_THRESHOLD = 0.5


@dataclass(frozen=True)
class BaselineIntegrity:
    """Report-only summary of a student's authenticated baseline health."""

    n_baselines: int
    min_required: int
    readiness: str  # "ready" | "thin" | "absent"
    provenance_mix: dict[str, int]
    span_days: int | None
    loo_outlier_samples: list[dict]
    sigma_inflation: float | None
    notes: list[str]


def build_baseline_integrity(
    state: StudentState | None,
    impostor_stats: tuple[np.ndarray, np.ndarray] | None = None,
) -> BaselineIntegrity | None:
    """Build a :class:`BaselineIntegrity` summary for ``state``.

    Returns ``None`` when ``state`` has zero samples at all (nothing has
    ever been submitted), or when anything inside the computation raises —
    this function is designed to be safe to call unconditionally.
    """
    try:
        return _build(state, impostor_stats)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Baseline integrity computation failed (%s: %s); returning None",
            type(exc).__name__,
            exc,
        )
        return None


def _build(
    state: StudentState,
    impostor_stats: tuple[np.ndarray, np.ndarray] | None,
) -> BaselineIntegrity | None:
    if state is None or not state.samples:
        return None

    contributing = [s for s in state.samples if s.auth_weight > 0]
    n_baselines = len(contributing)

    if n_baselines == 0:
        readiness = "absent"
    elif n_baselines < MIN_BASELINES:
        readiness = "thin"
    else:
        readiness = "ready"

    provenance_mix = dict(Counter(s.provenance for s in contributing))
    span_days = _compute_span_days(contributing)
    loo_outlier_samples = _compute_loo_outliers(state.loo_distances)
    sigma_inflation = _compute_sigma_inflation(state.baseline_std, impostor_stats)
    notes = _build_notes(readiness, loo_outlier_samples, sigma_inflation)

    return BaselineIntegrity(
        n_baselines=n_baselines,
        min_required=MIN_BASELINES,
        readiness=readiness,
        provenance_mix=provenance_mix,
        span_days=span_days,
        loo_outlier_samples=loo_outlier_samples,
        sigma_inflation=sigma_inflation,
        notes=notes,
    )


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _compute_span_days(contributing: list) -> int | None:
    dates = [d for s in contributing if (d := _parse_date(s.submitted_at)) is not None]
    if len(dates) < 2:
        return None
    return (max(dates) - min(dates)).days


def _compute_loo_outliers(loo_distances: list[float]) -> list[dict]:
    if len(loo_distances) < 2:
        return []
    distances = np.asarray(loo_distances, dtype=np.float64)
    median = float(np.median(distances))
    mad = float(np.median(np.abs(distances - median)))
    if mad == 0.0:
        # No spread among the distances at all -> nothing is "unlike" the
        # rest; avoid a divide-by-zero rather than manufacturing outliers.
        return []
    modified_z = _MODIFIED_Z_CONSTANT * (distances - median) / mad
    return [
        {"index": index, "z": float(z)}
        for index, z in enumerate(modified_z)
        if z > LOO_OUTLIER_Z_CUTOFF
    ]


def _compute_sigma_inflation(
    baseline_std: np.ndarray,
    impostor_stats: tuple[np.ndarray, np.ndarray] | None,
) -> float | None:
    if impostor_stats is None:
        return None
    _mu_null, sigma_null = impostor_stats
    baseline_std = np.asarray(baseline_std, dtype=np.float64)
    sigma_null = np.asarray(sigma_null, dtype=np.float64)
    if baseline_std.shape != sigma_null.shape:
        raise ValueError("baseline_integrity: baseline_std/sigma_null shape mismatch")
    return float(np.mean(baseline_std > sigma_null))


def _build_notes(
    readiness: str,
    loo_outlier_samples: list[dict],
    sigma_inflation: float | None,
) -> list[str]:
    notes: list[str] = []
    if readiness == "absent":
        notes.append("no authenticated baseline samples")
    elif readiness == "thin":
        notes.append(f"baseline thinner than N={MIN_BASELINES}")
    if loo_outlier_samples:
        notes.append("one sample stylistically unlike the others")
    if sigma_inflation is not None and sigma_inflation > _SIGMA_INFLATION_NOTE_THRESHOLD:
        notes.append("baseline spread wider than the peer population")
    return notes
