"""Regress fused signals on baseline volume while controlling peer count."""
from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np


def _fit(y: np.ndarray, baseline: np.ndarray, references: np.ndarray) -> dict:
    design = np.column_stack([np.ones(len(y)), baseline, references])
    beta, _, rank, _ = np.linalg.lstsq(design, y, rcond=None)
    predicted = design @ beta
    residual = y - predicted
    dof = len(y) - rank
    if dof > 0:
        variance = float(residual @ residual) / dof
        covariance = variance * np.linalg.pinv(design.T @ design)
        standard_error = math.sqrt(max(0.0, float(covariance[1, 1])))
        # 1.96 is deliberately reported as an approximate large-sample CI;
        # pilot n is displayed so a reviewer can reject an underpowered read.
        low = float(beta[1] - 1.96 * standard_error)
        high = float(beta[1] + 1.96 * standard_error)
    else:
        standard_error = low = high = None
    return {
        "n": len(y),
        "baseline_slope": float(beta[1]),
        "reference_profiles_coefficient": float(beta[2]),
        "baseline_slope_standard_error": standard_error,
        "baseline_slope_ci95_approx": [low, high],
        "implied_shift_3_to_30": float(beta[1] * 27),
        "r_squared": (
            1.0 - float(residual @ residual) / float(((y - y.mean()) ** 2).sum())
            if float(((y - y.mean()) ** 2).sum()) > 0
            else None
        ),
    }


def analyze_rows(rows: Iterable[dict]) -> dict:
    usable = []
    abstain_reasons: dict[str, int] = {}
    for row in rows:
        channels = row.get("channels") or {}
        compression = channels.get("compression")
        if (
            compression is None
            or row.get("fused_score") is None
            or row.get("baseline_samples") is None
            or row.get("reference_profiles") is None
        ):
            reason = row.get("abstain_reason") or "missing_confound_fields"
            abstain_reasons[reason] = abstain_reasons.get(reason, 0) + 1
            continue
        usable.append(
            (
                float(compression),
                float(row["fused_score"]),
                float(row["baseline_samples"]),
                float(row["reference_profiles"]),
            )
        )
    if len(usable) < 4:
        return {
            "verdict": "uninformative",
            "reason": "need at least four complete rows",
            "n_usable": len(usable),
            "abstain_reasons": abstain_reasons,
        }
    values = np.asarray(usable)
    compression = _fit(values[:, 0], values[:, 2], values[:, 3])
    fused = _fit(values[:, 1], values[:, 2], values[:, 3])
    return {
        "verdict": "measured",
        "n_usable": len(usable),
        "abstain_reasons": abstain_reasons,
        "compression_channel": compression,
        "fused_score": fused,
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
