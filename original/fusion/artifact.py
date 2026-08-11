"""Load and validate the committed fused-score weights.

Deliberately JSON, not joblib: inference is a dot product, so there is no
reason to carry a pickled sklearn estimator and the version-drift failure
mode that has already made the AI-likelihood detector inert.

Every validation failure logs one WARNING and returns None. A partially
trusted model is worse than no model — the caller treats None exactly like
the flag being off.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .channels import CHANNEL_NAMES

log = logging.getLogger(__name__)

DEFAULT_ARTIFACT_PATH = Path(__file__).parent.parent / "data" / "fused_score_v1.json"
EXPECTED_SCHEMA_VERSION = 1
_REFERENCE_TOLERANCE = 1e-9


@dataclass(frozen=True)
class FusedArtifact:
    channel_order: tuple[str, ...]
    mu: np.ndarray
    sd: np.ndarray
    weights: np.ndarray
    intercept: float
    threshold_fa5: float
    threshold_fa1: float
    model_version: str
    trained_on: str

    def log_odds(self, values: np.ndarray) -> float:
        """Standardize then apply the linear model. Higher = more impostor-like."""
        standardized = (np.asarray(values, dtype=np.float64) - self.mu) / self.sd
        return float(np.dot(standardized, self.weights) + self.intercept)

    def band(self, log_odds: float) -> str:
        if log_odds >= self.threshold_fa1:
            return "divergent"
        if log_odds >= self.threshold_fa5:
            return "inconclusive"
        return "consistent"


_UNLOADED, _READY, _FAILED = 0, 1, 2
_state = _UNLOADED
_artifact: FusedArtifact | None = None
_lock = threading.Lock()


def _artifact_path() -> Path:
    override = os.environ.get("FUSED_SCORE_MODEL_PATH", "").strip()
    return Path(override) if override else DEFAULT_ARTIFACT_PATH


def reset_for_tests() -> None:
    global _state, _artifact
    with _lock:
        _state, _artifact = _UNLOADED, None


def _fail(reason: str) -> None:
    global _state, _artifact
    log.warning("Fused score disabled: %s (path=%s)", reason, _artifact_path())
    _state, _artifact = _FAILED, None


def _parse(payload: dict) -> FusedArtifact | None:
    if payload.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        _fail("artifact schema mismatch")
        return None

    channel_order = tuple(payload.get("channel_order") or ())
    if not channel_order or any(name not in CHANNEL_NAMES for name in channel_order):
        _fail("unknown channel in channel_order")
        return None

    mu = np.asarray(payload.get("mu", []), dtype=np.float64)
    sd = np.asarray(payload.get("sd", []), dtype=np.float64)
    weights = np.asarray(payload.get("weights", []), dtype=np.float64)
    if not (mu.shape == sd.shape == weights.shape == (len(channel_order),)):
        _fail("mu/sd/weights length does not match channel_order")
        return None
    if not np.all(sd > 0):
        _fail("non-positive standardizer scale")
        return None
    if not (np.all(np.isfinite(mu)) and np.all(np.isfinite(weights))):
        _fail("non-finite value in mu or weights")
        return None

    threshold_fa5 = float(payload.get("threshold_fa5", 0.0))
    threshold_fa1 = float(payload.get("threshold_fa1", 0.0))
    if not threshold_fa5 < threshold_fa1:
        _fail("thresholds are not monotone (fa5 must be below fa1)")
        return None

    intercept = float(payload.get("intercept", 0.0))
    if not np.isfinite(intercept):
        _fail("non-finite intercept")
        return None

    provenance = payload.get("provenance") or {}
    candidate = FusedArtifact(
        channel_order=channel_order,
        mu=mu,
        sd=sd,
        weights=weights,
        intercept=intercept,
        threshold_fa5=threshold_fa5,
        threshold_fa1=threshold_fa1,
        model_version=f"v{EXPECTED_SCHEMA_VERSION}",
        trained_on=str(provenance.get("dataset", "unknown")),
    )

    reference_inputs = np.asarray(payload.get("reference_inputs", []), dtype=np.float64)
    expected = np.asarray(payload.get("reference_outputs", []), dtype=np.float64)
    if reference_inputs.ndim != 2 or reference_inputs.shape[0] != expected.shape[0]:
        _fail("reference inputs/outputs are missing or misshapen")
        return None
    got = np.asarray([candidate.log_odds(row) for row in reference_inputs])
    # Inverted form (NaN-safe): a plain `diff > tolerance` gate is defeated by
    # NaN, since every comparison against NaN is False. Asserting the
    # in-tolerance condition and negating it instead means any NaN element
    # makes `np.all(...)` False, so `not np.all(...)` is True and we fail
    # closed, exactly as a genuine drift would.
    if not np.all(np.abs(got - expected) <= _REFERENCE_TOLERANCE):
        _fail("reference prediction drift")
        return None
    return candidate


def _load() -> None:
    global _state, _artifact
    try:
        path = _artifact_path()
        if not path.exists():
            _fail("artifact not found")
            return
        parsed = _parse(json.loads(path.read_text()))
        if parsed is None:
            return
        _artifact, _state = parsed, _READY
    except Exception as exc:  # noqa: BLE001
        _fail(f"{type(exc).__name__}: {exc}")


def load_artifact() -> FusedArtifact | None:
    """The validated artifact, or None. Result is cached after the first call."""
    if _state == _READY:
        return _artifact
    if _state == _FAILED:
        return None
    with _lock:
        if _state == _UNLOADED:
            _load()
    return _artifact
