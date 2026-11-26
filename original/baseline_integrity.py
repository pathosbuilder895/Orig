"""baseline_integrity.py — report-only baseline health diagnostic (T-70).

Summarizes how trustworthy a student's authenticated baseline is: how many
approved samples it holds, the provenance mix of every contributing sample,
the calendar span they were collected over, whether any single sample looks like a stylistic
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


# How a sample got into the baseline (``original/approved_papers.sample_sources``)
# for every sample that counts: rule B, 2026-11, which leaves out only a
# student's own self-upload ("student_upload"). A trusted provenance, a shared
# past paper a teacher approved and a take-home sitting a teacher approved
# count, and so does a provenance outside AUTH_WEIGHTS ("unknown"): the API
# refuses those, so such a sample was written by the server or a script
# (legacy names such as "instructor_verified"), never uploaded by a student.
APPROVED_SOURCES = frozenset({"staff_or_supervised", "shared_paper", "take_home", "unknown"})


def count_approved(samples, sources=None) -> int:
    """Approved past papers among the contributing ``samples`` (rule B).

    ``sources`` is one entry per sample from
    ``original/approved_papers.sample_sources``. Without it (no records were
    read, or the read failed) an ``unverified`` sample cannot be shown to be a
    teacher-approved one, so none counts: the count can come out smaller than
    rule B's, never larger. A sample with no weight does not count either way."""
    if sources is None:
        return sum(
            1
            for s in samples
            if (getattr(s, "auth_weight", 0) or 0) > 0
            and getattr(s, "provenance", None) != "unverified"
        )
    return sum(
        1
        for s, src in zip(samples, sources, strict=True)
        if (getattr(s, "auth_weight", 0) or 0) > 0 and src in APPROVED_SOURCES
    )


@dataclass(frozen=True)
class BaselineIntegrity:
    """Report-only summary of a student's authenticated baseline health."""

    # Approved samples (rule B, ``count_approved``): trusted provenance, or a
    # shared paper / take-home sitting a teacher approved.
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
    sources: list[str] | None = None,
) -> BaselineIntegrity | None:
    """Build a :class:`BaselineIntegrity` summary for ``state``.

    ``sources`` says how each sample got in (``count_approved``); the live
    score route always passes it. Without it no ``unverified`` sample counts.

    Returns ``None`` when ``state`` has zero samples at all (nothing has
    ever been submitted), or when anything inside the computation raises —
    this function is designed to be safe to call unconditionally.
    """
    try:
        return _build(state, impostor_stats, sources)
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
    sources: list[str] | None = None,
) -> BaselineIntegrity | None:
    if state is None or not state.samples:
        return None

    contributing = [s for s in state.samples if s.auth_weight > 0]
    # Readiness counts approved samples only (rule B): a student's own
    # self-upload carries weight but no teacher or proctor stands behind it,
    # and Bluebook treats anything short of "ready" as too thin to read. A
    # shared paper or take-home sitting a teacher approved does count.
    n_baselines = count_approved(state.samples, sources)

    if not contributing:
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
        notes.append(f"baseline thinner than N={MIN_BASELINES} approved samples")
    if loo_outlier_samples:
        notes.append("one sample stylistically unlike the others")
    if sigma_inflation is not None and sigma_inflation > _SIGMA_INFLATION_NOTE_THRESHOLD:
        notes.append("baseline spread wider than the peer population")
    return notes
