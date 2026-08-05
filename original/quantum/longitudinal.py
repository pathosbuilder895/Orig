"""Longitudinal stylometric drift analysis.

This module deliberately sits beside, rather than inside, the production
deviation scorer.  Its first contract is observational: explain whether a
submission's distance from the lifetime baseline is compatible with a
chronological trend in authenticated writing.  It never changes a score or
recommended action.

The model is intentionally conservative for short student histories:

* only authenticated, dated, sufficiently long samples are eligible;
* a ridge-shrunk linear trend must beat a constant model in forward-chaining
  prediction before it is selected;
* the disputed submission is never used to fit its own trajectory;
* a one-change-point diagnostic is reported only with a substantially longer
  history and is not treated as evidence of an impostor.

The richer Dirichlet-multinomial count model described by Ross (2020) belongs
in the validation layer until stable function-word count metadata is available
for every baseline.  This feature-vector model provides the safe production
seam and the same constant/drift/change model-selection semantics.
"""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

import numpy as np

from ..constants import ALL_FEATURE_CODES, FEATURE_TIER
from .state import BaselineSample, StudentState

# Prefer comparatively topic-light identity features.  This is deliberately
# local: changing it cannot reorder or resize the canonical feature vector.
_DRIFT_TIERS = frozenset({1, 4, 5, 6, 11})
DRIFT_FEATURE_CODES = tuple(
    code for code in ALL_FEATURE_CODES if FEATURE_TIER.get(code) in _DRIFT_TIERS
)
_DRIFT_INDICES = np.array([ALL_FEATURE_CODES.index(code) for code in DRIFT_FEATURE_CODES])


@dataclass(frozen=True)
class LongitudinalConfig:
    enabled: bool = False
    min_samples_for_trend: int = 6
    min_samples_for_change_point: int = 12
    min_segment_samples: int = 4
    min_words: int = 300
    min_span_days: int = 60
    ridge_strength: float = 4.0
    min_predictive_improvement: float = 0.05
    max_extrapolation_days: int = 365

    @classmethod
    def from_env(cls) -> LongitudinalConfig:
        return cls(
            enabled=os.environ.get("LONGITUDINAL_DRIFT_ENABLED", "0") == "1",
            min_samples_for_trend=int(os.environ.get("LONGITUDINAL_MIN_SAMPLES", "6")),
            min_samples_for_change_point=int(
                os.environ.get("LONGITUDINAL_CHANGEPOINT_MIN_SAMPLES", "12")
            ),
        )


@dataclass
class DriftAnalysis:
    eligible: bool
    reason: str | None
    selected_model: str
    historical_deviation: float | None
    predicted_current_deviation: float | None
    drift_relief: float | None
    trend_confidence: float
    predictive_improvement: float | None
    sample_count: int
    dated_sample_count: int
    span_days: int
    extrapolation_days: int | None
    change_point_index: int | None
    change_point_evidence: float | None
    interpretation: str
    feature_count: int = len(DRIFT_FEATURE_CODES)
    model_version: str = "longitudinal-ridge-v1"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class _TimedSample:
    sample: BaselineSample
    when: datetime
    original_index: int


def _parse_datetime(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _word_count(sample: BaselineSample) -> int:
    stored = getattr(sample, "word_count", None)
    if stored is not None:
        try:
            return max(0, int(stored))
        except (TypeError, ValueError):
            pass
    return len((sample.text or "").split())


def _eligible_samples(
    state: StudentState,
    config: LongitudinalConfig,
    submission_genre: str | None = None,
) -> list[_TimedSample]:
    timed: list[_TimedSample] = []
    for index, sample in enumerate(state.samples):
        if sample.auth_weight <= 0 or _word_count(sample) < config.min_words:
            continue
        # When the probe has a resolved genre, require like-for-like history.
        # Unknown legacy genres abstain rather than silently confounding topic
        # or assignment context with personal evolution.
        if submission_genre is not None and sample.genre != submission_genre:
            continue
        when = _parse_datetime(sample.submitted_at)
        if when is None:
            continue
        timed.append(_TimedSample(sample=sample, when=when, original_index=index))
    # Never mutate state.samples: density-matrix recency semantics depend on its
    # persisted ingestion order.  The original index makes ties deterministic.
    return sorted(timed, key=lambda item: (item.when, item.original_index))


def _rms_deviation(x: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> float:
    z = np.clip((x - mean) / np.maximum(scale, 0.02), -4.0, 4.0)
    return float(np.tanh(np.sqrt(np.mean(z**2)) / 1.5))


def _fit_trend(t: np.ndarray, values: np.ndarray, ridge: float) -> tuple[np.ndarray, np.ndarray]:
    """Return intercept and ridge-shrunk slope for every feature."""
    center = float(t.mean())
    tc = t - center
    denom = float(tc @ tc) + ridge
    slope = (tc[:, None] * values).sum(axis=0) / denom
    intercept = values.mean(axis=0) - slope * center
    return intercept, slope


def _forward_errors(
    t: np.ndarray, values: np.ndarray, config: LongitudinalConfig
) -> tuple[float, float]:
    """Forward-chaining MSE for constant and trend models."""
    constant_errors: list[float] = []
    trend_errors: list[float] = []
    # Four observations gives the first trend fit enough leverage to be useful.
    for end in range(4, len(t)):
        train_t, train_v = t[:end], values[:end]
        target = values[end]
        constant = train_v.mean(axis=0)
        intercept, slope = _fit_trend(train_t, train_v, config.ridge_strength)
        predicted = intercept + slope * t[end]
        constant_errors.append(float(np.mean((target - constant) ** 2)))
        trend_errors.append(float(np.mean((target - predicted) ** 2)))
    if not constant_errors:
        return math.inf, math.inf
    return float(np.mean(constant_errors)), float(np.mean(trend_errors))


def _change_point_diagnostic(
    values: np.ndarray, config: LongitudinalConfig
) -> tuple[int | None, float | None]:
    """BIC-style one-change-point diagnostic on residual feature vectors.

    The returned evidence is the BIC improvement (constant minus segmented),
    so positive values favour a discontinuity.  It is deliberately diagnostic:
    a discontinuity has many causes and is never labelled an impostor here.
    """
    n, d = values.shape
    if n < config.min_samples_for_change_point:
        return None, None
    eps = 1e-12
    overall = values.mean(axis=0)
    rss0 = float(np.sum((values - overall) ** 2)) + eps
    bic0 = n * d * math.log(rss0 / (n * d)) + d * math.log(n)
    best_index: int | None = None
    best_improvement = -math.inf
    for split in range(config.min_segment_samples, n - config.min_segment_samples + 1):
        left, right = values[:split], values[split:]
        rss = float(np.sum((left - left.mean(axis=0)) ** 2))
        rss += float(np.sum((right - right.mean(axis=0)) ** 2)) + eps
        # Two means plus the discrete split location.
        bic = n * d * math.log(rss / (n * d)) + (2 * d + 1) * math.log(n)
        improvement = bic0 - bic
        if improvement > best_improvement:
            best_improvement = improvement
            best_index = split
    if best_improvement <= 0:
        return None, float(best_improvement)
    return best_index, float(best_improvement)


def analyze_longitudinal_drift(
    state: StudentState,
    submission_vector: np.ndarray,
    *,
    submitted_at: str = "",
    submission_genre: str | None = None,
    config: LongitudinalConfig | None = None,
) -> DriftAnalysis | None:
    """Analyze a submission without modifying ``state`` or production scores."""
    cfg = config or LongitudinalConfig()
    if not cfg.enabled:
        return None

    timed = _eligible_samples(state, cfg, submission_genre)
    dated_count = len(timed)
    if dated_count < cfg.min_samples_for_trend:
        return DriftAnalysis(
            eligible=False,
            reason="insufficient_dated_authenticated_samples",
            selected_model="insufficient_history",
            historical_deviation=None,
            predicted_current_deviation=None,
            drift_relief=None,
            trend_confidence=0.0,
            predictive_improvement=None,
            sample_count=state.authenticated_count,
            dated_sample_count=dated_count,
            span_days=0,
            extrapolation_days=None,
            change_point_index=None,
            change_point_evidence=None,
            interpretation="insufficient_history",
        )

    first, last = timed[0].when, timed[-1].when
    span_days = max(0, (last - first).days)
    if span_days < cfg.min_span_days:
        return DriftAnalysis(
            eligible=False,
            reason="insufficient_time_span",
            selected_model="insufficient_history",
            historical_deviation=None,
            predicted_current_deviation=None,
            drift_relief=None,
            trend_confidence=0.0,
            predictive_improvement=None,
            sample_count=state.authenticated_count,
            dated_sample_count=dated_count,
            span_days=span_days,
            extrapolation_days=None,
            change_point_index=None,
            change_point_evidence=None,
            interpretation="insufficient_history",
        )

    values = np.stack([item.sample.vector[_DRIFT_INDICES] for item in timed])
    t = np.array([(item.when - first).days / 365.25 for item in timed], dtype=np.float64)
    target_time = _parse_datetime(submitted_at) or last
    if target_time < first:
        target_time = first
    extrapolation_days = max(0, (target_time - last).days)
    if extrapolation_days > cfg.max_extrapolation_days:
        target_time = last + timedelta(days=cfg.max_extrapolation_days)
        extrapolation_days = cfg.max_extrapolation_days
    target_t = (target_time - first).days / 365.25

    constant_error, trend_error = _forward_errors(t, values, cfg)
    if not math.isfinite(constant_error) or constant_error <= 1e-12:
        improvement = 0.0
    else:
        improvement = (constant_error - trend_error) / constant_error
    selected = "gradual_drift" if improvement >= cfg.min_predictive_improvement else "constant"

    intercept, slope = _fit_trend(t, values, cfg.ridge_strength)
    historical_mean = values.mean(axis=0)
    predicted_mean = (
        intercept + slope * target_t if selected == "gradual_drift" else historical_mean
    )

    fitted = intercept[None, :] + t[:, None] * slope[None, :]
    residuals = values - (fitted if selected == "gradual_drift" else historical_mean)
    predictive_scale = np.maximum(residuals.std(axis=0, ddof=1), 0.02)
    x = np.asarray(submission_vector, dtype=np.float64)[_DRIFT_INDICES]
    historical_deviation = _rms_deviation(x, historical_mean, predictive_scale)
    predicted_deviation = _rms_deviation(x, predicted_mean, predictive_scale)
    relief = historical_deviation - predicted_deviation

    # Confidence couples predictive lift to history depth; a flexible trend
    # cannot become confident solely by fitting six points unusually well.
    depth = min(1.0, (dated_count - cfg.min_samples_for_trend + 1) / 6.0)
    trend_confidence = float(np.clip(max(0.0, improvement) * depth, 0.0, 1.0))
    cp_index, cp_evidence = _change_point_diagnostic(values, cfg)

    if selected == "gradual_drift" and relief >= 0.10 and predicted_deviation < 0.60:
        interpretation = "drift_compatible"
    elif historical_deviation < 0.40 and predicted_deviation < 0.40:
        interpretation = "stable_consistent"
    elif cp_index is not None and cp_evidence is not None and cp_evidence > 10.0:
        interpretation = "unexplained_discontinuity"
    elif predicted_deviation >= 0.60:
        interpretation = "unexplained_change"
    else:
        interpretation = "no_supported_drift"

    return DriftAnalysis(
        eligible=True,
        reason=None,
        selected_model=selected,
        historical_deviation=historical_deviation,
        predicted_current_deviation=predicted_deviation,
        drift_relief=relief,
        trend_confidence=trend_confidence,
        predictive_improvement=float(improvement),
        sample_count=state.authenticated_count,
        dated_sample_count=dated_count,
        span_days=span_days,
        extrapolation_days=extrapolation_days,
        change_point_index=cp_index,
        change_point_evidence=cp_evidence,
        interpretation=interpretation,
    )
