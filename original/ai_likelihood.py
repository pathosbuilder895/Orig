"""
ai_likelihood.py — corpus-level AI-likelihood detector (second scoring mode).

Loads the committed classifier artifact (original/data/ai_detector_v1.joblib,
trained by scripts/train_ai_detector.py on the AuTexTification 2023 English
subtask-1 train split) and scores the SAME 103-dim feature vector the
per-student Born-rule path already computes. This answers a different
question than the identity verification: not "does this match student X's
baseline?" but "does this look like AI-generated text at all?"

Design contract (see MODEL_CARD.md):
  - Gated by AI_LIKELIHOOD_ENABLED at the API layer; this module is never
    imported on the flag-off path, and its output is attach-only — it never
    touches the deviation score or recommended action.
  - Fail closed: any load or predict problem logs ONE warning and returns
    None forever after. A missing/stale artifact can never 500 a request.
  - The load-time reference-vector smoke check doubles as the sklearn
    version gate: if a different sklearn minor version deserializes the
    model into something that predicts differently (> 0.02 drift on the 8
    stored reference vectors), the detector disables itself rather than
    serve silently-changed probabilities.
  - The 13 non-text placeholder dims (Tier 17 keystroke + musical-comparison
    + comparison features) are forced to 0.5 before predicting, because
    that is exactly what they were during training (feature_vector() on
    plain text) — a corpus-level detector must also stay independent of any
    per-student comparison data that may be present at scoring time.
"""

from __future__ import annotations

import logging
import os
import threading
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np

from .constants import (
    ALL_FEATURE_CODES,
    COMPARISON_CODES,
    FEATURE_DIM,
    FEATURE_NAMES,
    MUSICAL_COMPARISON_CODES,
    TIER17_CODES,
)

log = logging.getLogger(__name__)

DEFAULT_ARTIFACT_PATH = Path(__file__).parent / "data" / "ai_detector_v1.joblib"
EXPECTED_SCHEMA_VERSION = 1
REFERENCE_DRIFT_TOLERANCE = 0.02

# Indices forced to 0.5 at predict time — must mirror the training-time
# placeholders in features/pipeline.py (Tier 17 when no keystroke data;
# comparison features always, until scoring time).
_MASKED_CODES = list(TIER17_CODES) + list(MUSICAL_COMPARISON_CODES) + list(COMPARISON_CODES)
_MASKED_IDX = np.array([ALL_FEATURE_CODES.index(c) for c in _MASKED_CODES], dtype=np.intp)

# Only features a professor can be handed as an explanation appear as
# indicators — the plain-language AI-signal vocabulary the narrative
# layer already knows how to talk about.
_INDICATOR_WHITELIST = [
    "perplexity_proxy",
    "burstiness",
    "sentence_length_variance",
    "transition_predictability",
    "metric_flatness_score",
    "stop_word_ratio",
    "function_word_ratio",
]
_INDICATOR_IDX = [(c, ALL_FEATURE_CODES.index(c)) for c in _INDICATOR_WHITELIST
                  if c in ALL_FEATURE_CODES]

MAX_INDICATORS = 3
INDICATOR_Z_FLOOR = 2.0


@dataclass
class AiIndicator:
    """One professor-explainable feature driving the AI-likelihood signal."""
    code: str
    label: str        # plain-English feature name
    z: float          # z-score vs the training-corpus human centroid
    direction: str    # "higher" | "lower" than typical human writing


@dataclass
class AiLikelihoodResult:
    """Corpus-level AI-likelihood for one submission. Report-only signal."""
    probability: float                 # calibrated p(AI-generated) ∈ [0, 1]
    band: str                          # "low" | "elevated" | "strong"
    model_version: str                 # e.g. "v1"
    trained_on: str                    # dataset identifier from the artifact
    top_indicators: List[AiIndicator] = field(default_factory=list)


# ── Lazy singleton with fail-closed tri-state ─────────────────────────────────

_UNLOADED, _READY, _FAILED = 0, 1, 2
_state = _UNLOADED
_artifact: Optional[dict] = None
_lock = threading.Lock()


def _artifact_path() -> Path:
    override = os.environ.get("AI_LIKELIHOOD_MODEL_PATH", "").strip()
    return Path(override) if override else DEFAULT_ARTIFACT_PATH


def _fail(reason: str) -> None:
    """Disable the detector for the life of the process. Logs exactly once."""
    global _state, _artifact
    log.warning("AI-likelihood detector disabled: %s "
                "(scoring continues without it; retrain or fix the artifact "
                "at %s to re-enable)", reason, _artifact_path())
    _state = _FAILED
    _artifact = None


def _load_artifact() -> None:
    """Load + validate the artifact. Sets _READY or _FAILED. Never raises."""
    global _state, _artifact
    path = _artifact_path()
    try:
        if not path.exists():
            _fail(f"artifact not found at {path}")
            return
        import joblib
        with warnings.catch_warnings():
            # A model pickled under a different sklearn version may silently
            # deserialize into something that predicts differently. Escalate
            # the warning to an error and let the reference check below be
            # the authoritative gate for versions that don't warn.
            try:
                from sklearn.exceptions import InconsistentVersionWarning
                warnings.simplefilter("error", InconsistentVersionWarning)
            except ImportError:
                pass
            art = joblib.load(path)

        if not isinstance(art, dict):
            _fail("artifact is not the expected dict schema")
            return
        if art.get("schema_version") != EXPECTED_SCHEMA_VERSION:
            _fail(f"artifact schema_version {art.get('schema_version')!r} "
                  f"!= expected {EXPECTED_SCHEMA_VERSION}")
            return
        if art.get("feature_codes") != list(ALL_FEATURE_CODES):
            _fail("artifact feature_codes do not match ALL_FEATURE_CODES — "
                  "the feature pipeline changed since training; retrain")
            return

        ref_X = np.asarray(art["reference_vectors"], dtype=np.float64)
        ref_p = np.asarray(art["reference_probs"], dtype=np.float64)
        got = art["model"].predict_proba(ref_X)[:, 1]
        drift = float(np.max(np.abs(got - ref_p)))
        if drift > REFERENCE_DRIFT_TOLERANCE:
            _fail(f"reference-vector predictions drifted by {drift:.4f} "
                  f"(> {REFERENCE_DRIFT_TOLERANCE}) — likely an sklearn "
                  f"version skew; retrain the artifact on this environment")
            return

        _artifact = art
        _state = _READY
        prov = art.get("provenance", {})
        log.info("AI-likelihood detector ready: %s trained %s (sklearn %s)",
                 art.get("model_name", "?"), prov.get("trained_at", "?"),
                 prov.get("sklearn_version", "?"))
    except Exception as exc:  # noqa: BLE001 — fail closed on anything
        _fail(f"{type(exc).__name__}: {exc}")


def _ensure_loaded() -> bool:
    global _state
    if _state == _READY:
        return True
    if _state == _FAILED:
        return False
    with _lock:
        if _state == _UNLOADED:
            _load_artifact()
    return _state == _READY


def warm() -> bool:
    """Best-effort eager load (called from the API lifespan when the flag is on)."""
    return _ensure_loaded()


def reset_for_tests() -> None:
    """Reset the singleton so tests can exercise load paths independently."""
    global _state, _artifact
    with _lock:
        _state = _UNLOADED
        _artifact = None


# ── Prediction ────────────────────────────────────────────────────────────────

def _band(probability: float, thresholds: dict) -> str:
    if probability >= thresholds["strong"]:
        return "strong"
    if probability >= thresholds["elevated"]:
        return "elevated"
    return "low"


def _indicators(vec: np.ndarray, art: dict) -> List[AiIndicator]:
    centroid = np.asarray(art["human_centroid"], dtype=np.float64)
    # Floor the std at 0.02 (features are normalized to [0,1]): a feature that
    # was near-constant in the training humans would otherwise produce absurd
    # z-scores (hundreds of thousands) for any ordinary deviation.
    std = np.maximum(np.asarray(art["human_std"], dtype=np.float64), 0.02)
    scored = []
    for code, idx in _INDICATOR_IDX:
        z = float((vec[idx] - centroid[idx]) / std[idx])
        if abs(z) >= INDICATOR_Z_FLOOR:
            scored.append(AiIndicator(
                code=code,
                label=FEATURE_NAMES.get(code, code.replace("_", " ")),
                z=round(z, 2),
                direction="higher" if z > 0 else "lower",
            ))
    scored.sort(key=lambda ind: -abs(ind.z))
    return scored[:MAX_INDICATORS]


def predict_ai_likelihood(vec: np.ndarray) -> Optional[AiLikelihoodResult]:
    """
    Score one submission's 103-dim feature vector. Returns None whenever the
    detector cannot produce a trustworthy answer — callers treat None as
    "signal unavailable", never as an error.
    """
    try:
        if not _ensure_loaded():
            return None
        art = _artifact
        assert art is not None

        v = np.asarray(vec, dtype=np.float64).reshape(-1).copy()
        if v.shape[0] != FEATURE_DIM:
            return None
        v[_MASKED_IDX] = 0.5   # present the exact training-time distribution

        probability = float(art["model"].predict_proba(v.reshape(1, -1))[0, 1])
        prov = art.get("provenance", {})
        return AiLikelihoodResult(
            probability=round(probability, 4),
            band=_band(probability, art["thresholds"]),
            model_version=f"v{art['schema_version']}",
            trained_on=prov.get("dataset", {}).get("name", "unknown"),
            top_indicators=_indicators(v, art),
        )
    except Exception as exc:  # noqa: BLE001 — never let this 500 a request
        log.warning("AI-likelihood prediction failed (%s: %s) — returning None",
                    type(exc).__name__, exc)
        return None
