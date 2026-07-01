"""
ablation.py — per-tier knock-out to measure each tier's contribution.

For each of Original's 17 tiers (plus tier 0 = comparison features), we:

  1. Re-run scoring on the same corpus with that tier's feature positions
     ZEROED in both the baseline vectors AND the submission vectors. The
     positions are set to the NORM_BOUNDS midpoint (0.5 after normalisation)
     so they contribute neutrally rather than as an outlier.

  2. Recompute AUC + Brier on the ablated outputs.

  3. Report ΔAUC and ΔBrier vs the baseline (no-ablation) run.

Tiers with the largest ΔAUC are the ones that drive Original's accuracy.
Tiers with a NEGATIVE ΔAUC (the ablation IMPROVED the score) are
suspicious — those are the candidates the doc/calibration audit
mentioned (degenerate Tier 3 features, etc.).

This module ONLY touches the feature vector passed into ``score()``. It
does not touch ``score()`` itself, the density matrix logic, the
threshold mapping, or the tier weights. Original's math runs unchanged
on the ablated input.

NOTE on cost: this is the most expensive part of the benchmark. One
baseline run + 18 ablation runs = 19× the cost of a single calibration
run. The wide-benchmark orchestrator therefore samples down to ≤500
essays per ablation pass by default; full ablation on 5000 essays takes
hours.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import numpy as np

from original.constants import ALL_FEATURE_CODES, FEATURE_TIER

from .metrics import arrays_from_results, brier_score


# Position indices for each tier in the FEATURE_DIM=103 vector.
# Built once at import time so the ablation loop is cheap.
TIER_POSITIONS: Dict[int, np.ndarray] = {}
for _pos, _code in enumerate(ALL_FEATURE_CODES):
    _tier = FEATURE_TIER.get(_code, 0)   # comparison features → tier 0
    TIER_POSITIONS.setdefault(_tier, []).append(_pos)
TIER_POSITIONS = {t: np.array(ps, dtype=np.int64) for t, ps in TIER_POSITIONS.items()}

# Authoritative tier list — tiers 0–17, skipping any that have no features.
TIERS: List[int] = sorted(TIER_POSITIONS.keys())


@dataclass(frozen=True)
class TierAblationResult:
    """Result of knocking one tier out and re-scoring."""
    tier: int
    n_features_zeroed: int
    baseline_auc: float
    ablated_auc: float
    delta_auc: float          # baseline_auc − ablated_auc; positive = tier matters
    baseline_brier: float
    ablated_brier: float
    delta_brier: float        # ablated_brier − baseline_brier; positive = tier matters
    notes: str = ""


def per_tier_ablation(
    run_calibration_fn: Callable[..., object],
    run_calibration_kwargs: dict,
    *,
    neutral_value: float = 0.5,
) -> List[TierAblationResult]:
    """
    Run the calibration once with all features active, then once per tier
    with that tier's features ZEROED to ``neutral_value``. Report ΔAUC
    and ΔBrier per tier.

    Args:
        run_calibration_fn: callable that returns a CalibrationReport (with
            ``.results`` and ``.auc``). Typically
            ``validation.calibration.run_calibration``.
        run_calibration_kwargs: kwargs passed to the runner each time.
        neutral_value: value to write into the zeroed positions. 0.5 is
            the midpoint of the normalised feature range used everywhere
            else in the codebase (e.g. baseline padding for legacy
            74-feature profiles, Tier 17 default when keystroke data is
            absent).

    Returns:
        A list of TierAblationResult, one per tier, sorted by tier number.
        Tier 0 (comparison features) is included so the operator can see
        how much the *cross-baseline* comparison contributes.
    """
    # 1. Baseline run (no ablation).
    baseline_report = run_calibration_fn(**run_calibration_kwargs)
    y_true, y_prob = arrays_from_results(baseline_report.results)
    baseline_auc = float(baseline_report.auc)
    baseline_brier = brier_score(y_true, y_prob)

    out: List[TierAblationResult] = []

    # 2. One run per tier.
    for tier in TIERS:
        positions = TIER_POSITIONS[tier]

        # Patch the feature vector path: ScoringResult objects carry the
        # already-scored deviation, so we can't post-hoc ablate. Instead we
        # re-run calibration with an ABLATION_POSITIONS context that the
        # runner respects (added in this PR). For backward compatibility
        # we wrap the runner in a closure that monkey-patches
        # `_run_with_ablation` if exposed, else falls back to a manual
        # re-extraction.
        report = _run_with_position_ablation(
            run_calibration_fn,
            run_calibration_kwargs,
            ablation_positions=positions,
            neutral_value=neutral_value,
        )
        y_true_a, y_prob_a = arrays_from_results(report.results)
        ablated_auc = float(report.auc)
        ablated_brier = brier_score(y_true_a, y_prob_a)

        out.append(TierAblationResult(
            tier=tier,
            n_features_zeroed=int(positions.size),
            baseline_auc=round(baseline_auc, 4),
            ablated_auc=round(ablated_auc, 4),
            delta_auc=round(baseline_auc - ablated_auc, 4),
            baseline_brier=round(baseline_brier, 4),
            ablated_brier=round(ablated_brier, 4),
            delta_brier=round(ablated_brier - baseline_brier, 4),
        ))

    out.sort(key=lambda r: r.tier)
    return out


# ── Internal: how to run calibration with a position mask ─────────────────────
#
# We avoid touching validation/calibration.py for this PR by patching the
# feature_vector + compute_full_features calls via module-level shims while
# the ablation run is active. Once this is merged we can give run_calibration
# a first-class `ablation_positions` kwarg.

def _run_with_position_ablation(
    run_calibration_fn,
    run_calibration_kwargs,
    *,
    ablation_positions: np.ndarray,
    neutral_value: float,
):
    """Temporarily patch the feature extraction so ablation_positions are forced to neutral_value."""
    import validation.calibration as cal_mod
    from original.features.pipeline import feature_vector as _orig_feature_vector
    from original.features.pipeline import compute_full_features as _orig_compute_full

    # Save originals so we can restore.
    _saved_fv = cal_mod.feature_vector
    _saved_full = cal_mod.compute_full_features

    def patched_feature_vector(text, *args, **kwargs):
        v = _orig_feature_vector(text, *args, **kwargs)
        v = np.array(v, dtype=np.float64)
        v[ablation_positions] = neutral_value
        return v

    def patched_compute_full(text, baseline_texts, *args, **kwargs):
        d = _orig_compute_full(text, baseline_texts, *args, **kwargs)
        # The submission vector built in run_calibration is `[features[c] for c in ALL_FEATURE_CODES]`,
        # so we just overwrite the ablated codes with neutral.
        for pos in ablation_positions.tolist():
            d[ALL_FEATURE_CODES[pos]] = neutral_value
        return d

    cal_mod.feature_vector = patched_feature_vector
    cal_mod.compute_full_features = patched_compute_full
    try:
        return run_calibration_fn(**run_calibration_kwargs)
    finally:
        cal_mod.feature_vector = _saved_fv
        cal_mod.compute_full_features = _saved_full
