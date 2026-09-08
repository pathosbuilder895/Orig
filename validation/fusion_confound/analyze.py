"""Regress fused signals on baseline volume while controlling peer count.

This module is intentionally read-only and accepts already-aggregated
database rows so the shadow-soak report can use it without exposing
identifiers.
"""
from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
from scipy import stats


def _fit(y: np.ndarray, baseline: np.ndarray, references: np.ndarray) -> dict:
    # The shipped fused artifact requires exactly eight references
    # (fusion/peers.py: N_REFERENCES = 8), so real successful rows commonly
    # have zero variance in this control. A constant control is already
    # absorbed by the intercept; retaining it anyway makes the design matrix
    # rank-deficient and the reported standard error meaningless.
    controls_references = bool(np.ptp(references) > 0)
    columns = [np.ones(len(y)), baseline]
    if controls_references:
        columns.append(references)
    design = np.column_stack(columns)
    beta, _, rank, _ = np.linalg.lstsq(design, y, rcond=None)
    residual = y - design @ beta
    dof = len(y) - rank
    if dof > 0:
        variance = float(residual @ residual) / dof
        covariance = variance * np.linalg.pinv(design.T @ design)
        standard_error = math.sqrt(max(0.0, float(covariance[1, 1])))
        # t, not a flat 1.96 z-critical value — this regression runs on
        # pilot-scale n, where the t/z gap is not negligible.
        critical = float(stats.t.ppf(0.975, dof))
        low = float(beta[1] - critical * standard_error)
        high = float(beta[1] + critical * standard_error)
    else:
        standard_error = low = high = None
    total = float(((y - y.mean()) ** 2).sum())
    return {
        "n": len(y),
        "controls_reference_profiles": controls_references,
        "baseline_slope": float(beta[1]),
        "reference_profiles_coefficient": (
            float(beta[2]) if controls_references else None
        ),
        "baseline_slope_standard_error": standard_error,
        "baseline_slope_ci95": [low, high],
        "implied_shift_3_to_30": float(beta[1] * 27),
        "r_squared": (
            1.0 - float(residual @ residual) / total if total > 0 else None
        ),
    }


def analyze_rows(rows: Iterable[dict], *, threshold_fa5: float | None = None,
                  threshold_fa1: float | None = None) -> dict:
    """Return aggregate C1 results; identifiers are neither read nor returned.

    Each row is expected to carry ``channels`` (a dict with a
    ``"compression"`` key), ``fused_log_odds``, ``baseline_samples``, and
    ``reference_profiles`` — the same shape the ``fused_scores`` table's
    columns produce (see ``original/store.py``'s ``put_fused_score``).
    """
    usable = []
    abstain_reasons: dict[str, int] = {}
    band_counts: dict[str, int] = {}
    for row in rows:
        band = str(row.get("band") or "unknown")
        band_counts[band] = band_counts.get(band, 0) + 1
        channels = row.get("channels") or {}
        compression = channels.get("compression")
        if (
            compression is None
            or row.get("fused_log_odds") is None
            or row.get("baseline_samples") is None
            or row.get("reference_profiles") is None
        ):
            reason = row.get("abstain_reason") or "missing_confound_fields"
            abstain_reasons[reason] = abstain_reasons.get(reason, 0) + 1
            continue
        usable.append(
            (
                float(compression),
                float(row["fused_log_odds"]),
                float(row["baseline_samples"]),
                float(row["reference_profiles"]),
            )
        )
    if len(usable) < 4:
        return {
            "verdict": "uninformative",
            "reason": "need at least four complete rows",
            "n_usable": len(usable),
            "band_counts": band_counts,
            "abstain_reasons": abstain_reasons,
        }
    values = np.asarray(usable)
    compression = _fit(values[:, 0], values[:, 2], values[:, 3])
    fused = _fit(values[:, 1], values[:, 2], values[:, 3])
    result = {
        "verdict": "measured",
        "n_usable": len(usable),
        "band_counts": band_counts,
        "abstain_reasons": abstain_reasons,
        "compression_channel": compression,
        "fused_log_odds": fused,
        "normalization_candidates": [
            "cap concatenated baseline text at a fixed byte budget",
            "mean the per-baseline-document compression distances",
            "add baseline_samples as a fusion input and refit",
        ],
        "warning": (
            "Every candidate invalidates the shipped thresholds and requires "
            "a train_fused_score.py refit plus a new artifact."
        ),
    }
    if threshold_fa5 is not None and threshold_fa1 is not None:
        gap = float(threshold_fa1) - float(threshold_fa5)
        result["thresholds"] = {
            "fa5": float(threshold_fa5),
            "fa1": float(threshold_fa1),
            "gap": gap,
        }
        if gap:
            result["fused_log_odds"]["shift_3_to_30_as_fraction_of_gap"] = (
                fused["implied_shift_3_to_30"] / gap
            )
    return result
