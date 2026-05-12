"""
context/pipeline.py — Phase 5: Adaptive scoring orchestrator.

Single integration point for `api.py`. Wires:

    Stage 2 resolvers ──→ Stage 3 manifest ──→ Stage 4 baseline match ──→
    Stage 5 weight vector ──→ Stage 6 feature extraction (with cluster filter)

and returns an `AdaptivePipelineResult` containing the per-feature dict,
the (FEATURE_DIM,) submission vector, the manifest, and the adaptive
weight vector — ready to drop into `quantum_score(...)`.

Two env-flag gates:

    CONTEXT_MANIFEST_ENABLED=1   build the manifest, attach for audit
    ADAPTIVE_WEIGHTS_ENABLED=1   ALSO build matching cluster + adaptive
                                 weight vector and feed them into scoring

Both default OFF. With both off this module short-circuits to plain
`extract_features` + `feature_vector` — byte-identical Phase 1 behaviour.
ADAPTIVE_WEIGHTS_ENABLED implies CONTEXT_MANIFEST_ENABLED (you can't have
adaptive weights without a manifest); the orchestrator handles that
implicitly so callers only need to flip the one flag.

Graceful degradation: any exception inside an enabled stage logs a warning
and the result falls back to the next-most-conservative behaviour rather
than failing the request.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from ..constants import ALL_FEATURE_CODES
from ..features.pipeline import compute_full_features, extract_features, feature_vector
from .baseline_match import match_baseline_cluster, ensure_sample_context_metadata
from .manifest import build_manifest, ContextManifest
from .resolvers import run_resolvers
from .weighting import build_adaptive_weight_vector

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Result dataclass
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class AdaptivePipelineResult:
    """Bundle returned by `run_adaptive_pipeline()` for the caller."""

    feat_dict: Dict[str, float]
    vector: np.ndarray                       # shape (FEATURE_DIM,)
    manifest: Optional[ContextManifest] = None
    adaptive_weights: Optional[np.ndarray] = None
    fallback_reason: Optional[str] = None    # populated when graceful degradation kicked in
    cluster_indices: List[int] = field(default_factory=list)
    anchor_only: bool = False


# ══════════════════════════════════════════════════════════════════════════════
# Public orchestrator
# ══════════════════════════════════════════════════════════════════════════════

def run_adaptive_pipeline(
    text: str,
    state: "object",
    submission_id: str,
    keystroke_data: Optional[Dict] = None,
    enable_manifest: bool = False,
    enable_adaptive_weights: bool = False,
) -> AdaptivePipelineResult:
    """
    Run feature extraction with optional adaptive context layer.

    Parameters
    ----------
    text : str
        Submission text.
    state : StudentState
        Student baseline state — provides the sample corpus for resolvers
        (topic centroid) and Phase 4 baseline matching.
    submission_id : str
        Used for manifest audit identity.
    keystroke_data : Optional[Dict]
        Bbook stylemetry (Tier 17 + composition_mode resolver).
    enable_manifest : bool
        Mirrors the `CONTEXT_MANIFEST_ENABLED` env flag — when True, runs
        resolvers and builds a `ContextManifest`. When False, the manifest
        and adaptive_weights stages are both skipped (Phase 1 short-circuit).
    enable_adaptive_weights : bool
        Mirrors `ADAPTIVE_WEIGHTS_ENABLED`. When True, ALSO runs the
        baseline-match + weight-vector stages and feeds the matched cluster
        indices into `compute_full_features`. Implies `enable_manifest`.

    Returns
    -------
    AdaptivePipelineResult
        - `feat_dict`, `vector`: drop into `quantum_score()`.
        - `manifest`: attach to `Layer7Output.context_manifest` and audit log.
        - `adaptive_weights`: pass as `score(adaptive_weights=...)`.
        - `fallback_reason`: set to a short string when an enabled stage
          degraded back to a more conservative behaviour.
    """
    # `adaptive` implies `manifest` — collapse here so call sites only flip
    # the one flag they care about.
    want_manifest = enable_manifest or enable_adaptive_weights

    # ── Phase-1 short-circuit ─────────────────────────────────────────────────
    if not want_manifest:
        # Identical to the legacy api.py flow at lines 248–255.
        feat_dict = extract_features(text, keystroke_data=keystroke_data)
        vec = feature_vector(text, keystroke_data=keystroke_data)
        return AdaptivePipelineResult(
            feat_dict=feat_dict,
            vector=vec,
            manifest=None,
            adaptive_weights=None,
            fallback_reason=None,
            cluster_indices=[],
            anchor_only=False,
        )

    # ── Stage 2: resolvers ────────────────────────────────────────────────────
    baseline_texts: List[str] = []
    samples = getattr(state, "samples", None) or []
    baseline_texts = [s.text for s in samples if (s.auth_weight or 0) > 0]

    try:
        resolver_outputs = run_resolvers(
            text,
            baseline_texts,
            keystroke_data=keystroke_data,
        )
    except Exception as e:
        log.warning("resolvers failed for %s: %s — falling back to Phase 1",
                    submission_id, e)
        feat_dict = extract_features(text, keystroke_data=keystroke_data)
        vec = feature_vector(text, keystroke_data=keystroke_data)
        return AdaptivePipelineResult(
            feat_dict=feat_dict, vector=vec,
            manifest=None, adaptive_weights=None,
            fallback_reason="resolver_exception",
        )

    # ── Stage 3: manifest ─────────────────────────────────────────────────────
    manifest = build_manifest(submission_id, resolver_outputs)

    # ── Manifest-only mode: collect manifest, weights still static ────────────
    if not enable_adaptive_weights:
        feat_dict = extract_features(text, keystroke_data=keystroke_data)
        vec = feature_vector(text, keystroke_data=keystroke_data)
        return AdaptivePipelineResult(
            feat_dict=feat_dict,
            vector=vec,
            manifest=manifest,
            adaptive_weights=None,        # ← NOT used when only manifest flag is on
            fallback_reason=None,
        )

    # ── Stage 4: baseline matching ────────────────────────────────────────────
    try:
        ensure_sample_context_metadata(state)
        cluster_indices, anchor_only = match_baseline_cluster(
            manifest, state, submission_text=text,
        )
        # Mutate manifest to record what we picked — this is the key audit
        # field for "why was this score the way it was".
        manifest.baseline_match = {
            "cluster_indices": list(cluster_indices),
            "n_samples":       len(cluster_indices),
            "anchor_only":     anchor_only,
        }
    except Exception as e:
        log.warning("baseline matching failed for %s: %s — anchor-only fallback",
                    submission_id, e)
        cluster_indices, anchor_only = [], True
        manifest.baseline_match = {
            "cluster_indices": [],
            "n_samples":       0,
            "anchor_only":     True,
            "error":           str(e),
        }

    # ── Stage 5: adaptive weight vector ───────────────────────────────────────
    try:
        adaptive_weights = build_adaptive_weight_vector(manifest)
    except Exception as e:
        log.warning("weight-vector build failed for %s: %s — using static weights",
                    submission_id, e)
        adaptive_weights = None

    # ── Stage 6: feature extraction with cluster filter ───────────────────────
    # When `anchor_only=True`, pass an empty list to compute_full_features
    # so comparison features stay at the 0.5 placeholder (their natural
    # "no signal" state); the weight vector will mute them via the
    # `length_regime`/anchor logic upstream.
    try:
        if anchor_only:
            feat_dict = compute_full_features(
                text, baseline_texts,
                keystroke_data=keystroke_data,
                baseline_indices=[],
            )
        else:
            feat_dict = compute_full_features(
                text, baseline_texts,
                keystroke_data=keystroke_data,
                baseline_indices=cluster_indices,
            )
    except Exception as e:
        log.warning("compute_full_features failed for %s: %s — using extract_features",
                    submission_id, e)
        feat_dict = extract_features(text, keystroke_data=keystroke_data)

    vec = np.array([feat_dict[c] for c in ALL_FEATURE_CODES], dtype=np.float64)

    return AdaptivePipelineResult(
        feat_dict=feat_dict,
        vector=vec,
        manifest=manifest,
        adaptive_weights=adaptive_weights,
        fallback_reason=None,
        cluster_indices=list(cluster_indices),
        anchor_only=anchor_only,
    )


__all__ = ["run_adaptive_pipeline", "AdaptivePipelineResult"]
