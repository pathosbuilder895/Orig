"""
context/blend.py — Phase 7: Sliding-window blend detection.

Splits a submission into overlapping token windows, scores each window
against the student's quantum state, and looks for **mid-document
fingerprint shifts** — the signature of:

    - Collaborative authorship (different people wrote different sections)
    - AI-generated insertions (a polished paragraph in otherwise rough prose)
    - Heavy advisor editing (a "rewrite this paragraph" pass)

A single global divergence score (Phase 1) misses all of these — the AI
section averages out with the student section, yielding a "looks fine"
verdict. By scoring chunks separately, the variance across windows
becomes the diagnostic signal.

Output
======
``BlendResult`` carries:

    blend_index    — std(window_scores) / 0.15, clipped to [0, 1].
                     0.0 = fully uniform, 1.0 = maximally heterogeneous.
                     0.15 is the empirical noise floor for same-author
                     drift across small chunks of an unedited submission.
    shift_positions — token offsets where a Pettitt change-point fired
                     (typically 0 or 1 for a single mid-document shift).
    per_section    — one ``WindowScore`` per overlapping window.

Implementation choices
======================
- Reuses ``_tokenize`` from ``tier1`` so window boundaries match other
  feature extractors.
- Per-window comparison features use the parent submission's matched
  cluster (Phase 4) — so a window's char-trigram divergence is computed
  against the same context-similar baseline as the rest of the document,
  not a different cluster per window. Keeps blend scores comparable.
- Pettitt change-point test: rank-based, O(n log n), no extra deps.
  Only one shift is reported per call (the strongest); recursive
  segmentation across multiple shifts is a follow-up.
- Hard-depends on PR 3 (Phases 4+5): the orchestrator must have already
  built a manifest + cluster for the submission. ``detect_blend`` runs the
  same orchestrator internally so callers can hit the endpoint with just
  text + state.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..constants import ALL_FEATURE_CODES
from ..features.pipeline import compute_full_features, feature_vector
from ..features.tier1 import _tokenize
from ..quantum.scoring import score as quantum_score
from .pipeline import run_adaptive_pipeline

log = logging.getLogger(__name__)


# ── Tunable knobs ────────────────────────────────────────────────────────────

# std(window_scores) at which the blend index saturates to 1.0. Empirically
# the noise floor for same-author drift across 300-token windows of an
# unedited submission sits around 0.05–0.08; doubling that to 0.15 gives a
# generous "this is clearly heterogeneous" boundary.
BLEND_INDEX_NOISE_FLOOR: float = 0.15

# Threshold above which `blend_detected` flips to True. Conservative — we
# want false-positive blend alerts to be rare, since they prompt a manual
# review.
BLEND_DETECT_THRESHOLD: float = 0.5

# blend_index threshold above which we bother locating a shift point at
# all. Below this, the windows are uniform enough that any "argmax of U_t"
# would be reporting noise as signal.
SHIFT_LOCATION_MIN_BLEND_INDEX: float = 0.30

# Pettitt p-value threshold — used only as ADDITIONAL confidence info on a
# located shift (NOT as a hard gate). Pettitt's asymptotic distribution is
# heavily under-powered for small n (≤ ~16 windows), so gating shift
# detection on p < α would silently miss obvious mid-document blends in
# typical 1k-3k token submissions. Instead, we use blend_index magnitude as
# the gate and report the Pettitt argmax as the most-likely location.
PETTITT_ALPHA: float = 0.05

# Window-token reliability floor (per the architectural spec). Below this,
# T7 distributional features become unstable, so we report each window's
# confidence as "low" regardless of other signals.
WINDOW_RELIABILITY_THRESHOLD: int = 500

# Minimum windows needed before any shift-location estimate is reliable.
# Fewer than 4 → silently skip shift detection rather than fire on noise.
MIN_WINDOWS_FOR_SHIFT_DETECTION: int = 4


# ══════════════════════════════════════════════════════════════════════════════
# Data classes
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class WindowScore:
    """One overlapping window's deviation score against the student's state."""
    start: int            # token offset (inclusive)
    end: int              # token offset (exclusive)
    score: float          # authorship deviation_score in [0, 1]
    confidence: str       # "low" (window < 500 tokens) | "medium"


@dataclass
class BlendResult:
    """
    Aggregated blend-detection result for a single submission.

    ``per_section`` is the raw window timeline; ``blend_index`` and
    ``shift_positions`` are the diagnostic summary.
    """
    blend_detected: bool
    blend_index: float                          # 0.0 uniform → 1.0 maximally blended
    shift_positions: List[int]                  # token offsets of detected transitions
    per_section: List[WindowScore]
    n_tokens: int = 0                           # total token count (audit field)
    fallback_reason: Optional[str] = None       # populated when graceful degradation kicked in

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ══════════════════════════════════════════════════════════════════════════════
# Pettitt change-point detection
# ══════════════════════════════════════════════════════════════════════════════

def _pettitt_change_point(x: np.ndarray) -> Tuple[Optional[int], float]:
    """
    Pettitt's non-parametric rank-based change-point statistic.

    For a sequence x_1, …, x_n, computes U_t = 2·rank_cumsum_t − t·(n+1)
    (an algebraic equivalent of the classical Mann-Whitney U expressed via
    ranks); the t maximising |U_t| is the most likely change-point.

    Returns
    -------
    (location, p_value)
        ``location`` is the argmax index in the input's index space, or
        ``None`` if the input is too short for shift detection.
        ``p_value`` is the asymptotic Pettitt approximation — informative
        only; callers SHOULD NOT use it as a hard gate for small n
        (n ≤ ~16) because the formula is structurally under-powered there.
        See ``SHIFT_LOCATION_MIN_BLEND_INDEX`` for the recommended gating
        approach.
    """
    n = len(x)
    if n < MIN_WINDOWS_FOR_SHIFT_DETECTION:
        return None, 1.0

    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(n, dtype=np.float64)
    ranks[order] = np.arange(1, n + 1)

    # U_t = 2·sum(ranks[:t+1]) − (t+1)·(n+1).
    cum = np.cumsum(ranks)
    t_index = np.arange(1, n + 1, dtype=np.float64)
    U = 2.0 * cum - t_index * (n + 1)

    # Last index is degenerate (no "after" segment) — exclude.
    U_interior = U[:-1]
    K = float(np.max(np.abs(U_interior)))
    p = 2.0 * float(np.exp(-6.0 * K * K / (n ** 3 + n ** 2)))
    p = min(1.0, max(0.0, p))

    return int(np.argmax(np.abs(U_interior))), p


# ══════════════════════════════════════════════════════════════════════════════
# Window enumeration
# ══════════════════════════════════════════════════════════════════════════════

def _window_offsets(
    n_tokens: int, window_tokens: int, overlap: float,
) -> List[Tuple[int, int]]:
    """
    Compute the (start, end) token-offset pairs for the sliding windows.

    Step size is ``window_tokens · (1 − overlap)``, clamped to ≥ 1. The last
    window is always anchored at ``n_tokens − window_tokens`` so the tail is
    covered when the step does not divide the corpus evenly.
    """
    if n_tokens < window_tokens:
        # Too short to slide — return a single window covering the whole text.
        return [(0, n_tokens)]

    step = max(1, int(round(window_tokens * (1.0 - overlap))))
    offsets: List[Tuple[int, int]] = []
    start = 0
    while start + window_tokens <= n_tokens:
        offsets.append((start, start + window_tokens))
        start += step

    # Anchor the tail: if the last window doesn't reach the end, append one.
    if offsets and offsets[-1][1] < n_tokens:
        offsets.append((n_tokens - window_tokens, n_tokens))

    return offsets


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def detect_blend(
    text: str,
    state: "object",
    window_tokens: int = 300,
    overlap: float = 0.5,
    submission_id: str = "blend",
) -> BlendResult:
    """
    Slide overlapping windows over ``text`` and score each against ``state``.

    Parameters
    ----------
    text : str
        Submission text to inspect.
    state : StudentState
        Student baseline state (must contain at least one authenticated
        sample, like the regular score endpoint).
    window_tokens : int
        Token budget per window. Default 300 — small enough to localise a
        mid-document shift, large enough that T1/T6 character-level features
        stabilise.
    overlap : float
        Fraction of overlap between consecutive windows in [0, 1). 0.5 means
        each window shares half its tokens with its neighbours, halving the
        effective resolution.
    submission_id : str
        Audit identity for the cluster-matching call.

    Returns
    -------
    BlendResult
        ``per_section`` is empty + ``fallback_reason`` is set when the input
        is too short or the state has no usable samples.
    """
    if not (0.0 <= overlap < 1.0):
        raise ValueError(f"overlap must be in [0, 1); got {overlap}")
    if window_tokens < 50:
        raise ValueError(f"window_tokens must be ≥ 50; got {window_tokens}")

    tokens = _tokenize(text)
    n_tokens = len(tokens)

    # ── Edge cases — fall through with a meaningful fallback_reason ──────────
    if n_tokens < window_tokens:
        return BlendResult(
            blend_detected=False, blend_index=0.0, shift_positions=[],
            per_section=[], n_tokens=n_tokens,
            fallback_reason="text_too_short",
        )

    samples = getattr(state, "samples", None) or []
    if not samples:
        return BlendResult(
            blend_detected=False, blend_index=0.0, shift_positions=[],
            per_section=[], n_tokens=n_tokens,
            fallback_reason="no_baseline_samples",
        )

    # ── Resolve the matched cluster ONCE for the whole submission ────────────
    # All windows share the same cluster so per-window comparison features
    # are commensurable. We also reuse the orchestrator's resolver outputs
    # for free — but discard the manifest here; blend reports its own shape.
    cluster_indices: List[int] = []
    baseline_texts = [s.text for s in samples if (s.auth_weight or 0) > 0]
    try:
        adaptive = run_adaptive_pipeline(
            text=text, state=state, submission_id=submission_id,
            keystroke_data=None,
            enable_manifest=True, enable_adaptive_weights=True,
        )
        cluster_indices = list(adaptive.cluster_indices or [])
    except Exception as e:
        # Cluster matching failure → blend still works against full baseline.
        log.warning("blend: cluster matching failed (%s) — using full baseline", e)
        cluster_indices = []

    # ── Build the window timeline ────────────────────────────────────────────
    offsets = _window_offsets(n_tokens, window_tokens, overlap)

    # Confidence label is uniform across windows (depends only on size).
    confidence_label = "low" if window_tokens < WINDOW_RELIABILITY_THRESHOLD else "medium"

    # ── Score each window ────────────────────────────────────────────────────
    per_section: List[WindowScore] = []
    for (start, end) in offsets:
        window_text = " ".join(tokens[start:end])
        try:
            if cluster_indices:
                feat_dict = compute_full_features(
                    window_text, baseline_texts,
                    baseline_indices=cluster_indices,
                )
                vec = np.array([feat_dict[c] for c in ALL_FEATURE_CODES],
                                dtype=np.float64)
            else:
                # No cluster → fall back to the legacy path. Comparison
                # features will be against the full baseline corpus; not
                # ideal but better than skipping the window.
                feat_dict = compute_full_features(window_text, baseline_texts)
                vec = np.array([feat_dict[c] for c in ALL_FEATURE_CODES],
                                dtype=np.float64)
            layer7 = quantum_score(state=state, submission_vector=vec,
                                    feature_dict=feat_dict,
                                    submission_id=f"{submission_id}_w{start}")
            window_score = float(layer7.authorship.deviation_score)
        except Exception as e:
            # Per-window failure → mark with NaN and move on; the aggregator
            # filters NaNs out so one bad window doesn't kill the whole blend.
            log.warning("blend: window [%d, %d) scoring failed: %s", start, end, e)
            window_score = float("nan")

        per_section.append(WindowScore(
            start=start, end=end, score=window_score,
            confidence=confidence_label,
        ))

    # ── Aggregate: blend_index, shift detection ──────────────────────────────
    valid_scores = np.array(
        [w.score for w in per_section if not np.isnan(w.score)],
        dtype=np.float64,
    )

    if len(valid_scores) < 2:
        return BlendResult(
            blend_detected=False, blend_index=0.0, shift_positions=[],
            per_section=per_section, n_tokens=n_tokens,
            fallback_reason="insufficient_valid_windows",
        )

    std_score = float(np.std(valid_scores))
    blend_index = float(np.clip(std_score / BLEND_INDEX_NOISE_FLOOR, 0.0, 1.0))

    shift_positions: List[int] = []
    # Locate the most-likely shift only when blend_index suggests there's
    # actually a regime change to find. This avoids reporting the argmax
    # of pure noise on uniform documents.
    if (blend_index >= SHIFT_LOCATION_MIN_BLEND_INDEX
            and len(valid_scores) >= MIN_WINDOWS_FOR_SHIFT_DETECTION):
        change_idx, _p_value = _pettitt_change_point(valid_scores)
        if change_idx is not None:
            # Map back to a token offset: the END of the window AT the
            # change point is the boundary between the two regimes.
            # change_idx indexes into valid_scores (after NaN filtering);
            # remap to per_section index space.
            valid_indices = [i for i, w in enumerate(per_section)
                             if not np.isnan(w.score)]
            if change_idx < len(valid_indices):
                section_idx = valid_indices[change_idx]
                shift_positions.append(per_section[section_idx].end)

    blend_detected = (
        blend_index >= BLEND_DETECT_THRESHOLD
        or len(shift_positions) > 0
    )

    return BlendResult(
        blend_detected=blend_detected,
        blend_index=round(blend_index, 4),
        shift_positions=shift_positions,
        per_section=per_section,
        n_tokens=n_tokens,
        fallback_reason=None,
    )


__all__ = [
    "WindowScore", "BlendResult", "detect_blend",
    "BLEND_INDEX_NOISE_FLOOR", "BLEND_DETECT_THRESHOLD",
    "SHIFT_LOCATION_MIN_BLEND_INDEX",
    "PETTITT_ALPHA", "WINDOW_RELIABILITY_THRESHOLD",
]
