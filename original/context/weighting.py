"""
context/weighting.py — Phase 5: Adaptive Weight Modification.

Translates a `ContextManifest`'s directives into a per-feature weight vector
that the quantum scoring kernel can drop in for `_TIER_WEIGHT_VECTOR`.

Operations applied per-feature-code:
    amplify:   weight  = base × AMPLIFY_FACTOR     (1.15)
    attenuate: weight  = base × ATTENUATE_FACTOR   (0.6)
    mute:      weight  = 0.0
    (neutral): weight  = base                       (no-op)

Anchor tiers (from `manifest.anchor_tiers`) are amplified — confirming
"these tiers are reliable identity signals in this context, weight them more."
Mute > attenuate > amplify is enforced upstream in `manifest._derive_directives`,
so the per-code lookup here is unambiguous.

When both feature flags are off (the default), nothing in this module runs —
`score()` keeps using its static `_TIER_WEIGHT_VECTOR`.
"""

from __future__ import annotations

from typing import Dict, Sequence

import numpy as np

from ..constants import (
    ALL_FEATURE_CODES,
    FEATURE_TIER,
    TIER_WEIGHTS,
)


# ── Tunable factors (exposed at module top so tests can monkeypatch) ─────────

# Amplification multiplier for anchor-tier feature codes — bumped up from
# baseline so context-confirmed identity tiers exert more pressure on the
# divergence score. Conservative 15 % matches the spec.
AMPLIFY_FACTOR: float = 1.15

# Attenuation multiplier for codes flagged as contextually unreliable
# (tool-cleaned text → T11/T14; high topic novelty → T10/T15). 0.6 means
# noise is ~halved without throwing the signal away entirely.
ATTENUATE_FACTOR: float = 0.6


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def build_adaptive_weight_vector(
    manifest: "object",                        # ContextManifest, kept duck-typed to avoid import cycle
    base_tier_weights: Dict[int, float] = TIER_WEIGHTS,
    feature_codes: Sequence[str] = ALL_FEATURE_CODES,
) -> np.ndarray:
    """
    Build a per-feature-code weight vector from a ContextManifest.

    Parameters
    ----------
    manifest : ContextManifest
        Source of `weight_modifications` (mute/attenuate/amplify code lists)
        and `anchor_tiers`. Tier-level anchor information is expanded to
        per-feature codes via `FEATURE_TIER`.
    base_tier_weights : Dict[int, float]
        Mapping of tier index → static base weight. Defaults to the project
        `TIER_WEIGHTS` so callers normally don't override.
    feature_codes : Sequence[str]
        Ordered list of feature codes (matches `submission_vector` order).
        Defaults to `ALL_FEATURE_CODES`.

    Returns
    -------
    np.ndarray, shape (len(feature_codes),), dtype float64
        The vector to pass as `score(adaptive_weights=...)`.

    Behavioural guarantees
    ----------------------
    - Empty manifest (no anchors set, no muting, no attenuation) returns a
      vector that's element-wise equal to the static base-weights vector
      built the same way `scoring.py` builds `_TIER_WEIGHT_VECTOR`.
    - Mute is a hard zero; nothing else can override it.
    - A code that is BOTH attenuated AND in an anchor tier ends up
      attenuated — manifest derivation enforces mute > attenuate > amplify
      precedence; weighting just reads the resulting code lists.
    - Codes whose tier is missing from `base_tier_weights` default to 1.0
      (matches scoring.py's `.get(tier, 1.0)` fallback).
    """
    # Resolve directive code lists. Use `getattr` so this function tolerates
    # being passed a plain dict (e.g. manifest.to_dict()) in addition to a
    # ContextManifest dataclass instance — useful in audit/replay paths.
    if isinstance(manifest, dict):
        weight_mods = manifest.get("weight_modifications", {}) or {}
        anchor_tiers = manifest.get("anchor_tiers", []) or []
    else:
        weight_mods = getattr(manifest, "weight_modifications", {}) or {}
        anchor_tiers = getattr(manifest, "anchor_tiers", []) or []

    mute_codes      = set(weight_mods.get("mute_codes", []))
    attenuate_codes = set(weight_mods.get("attenuate_codes", []))
    amplify_codes   = set(weight_mods.get("amplify_codes", []))
    anchor_tier_set = set(anchor_tiers)

    # Anchor tiers expand to per-code amplification — every code whose tier
    # is in anchor_tier_set is treated as if it were in `amplify_codes`.
    # Mute and attenuate still take precedence (enforced below).
    n = len(feature_codes)
    out = np.empty(n, dtype=np.float64)

    for i, code in enumerate(feature_codes):
        tier = FEATURE_TIER.get(code)
        base = base_tier_weights.get(tier, 1.0) if tier is not None else 1.0

        if code in mute_codes:
            out[i] = 0.0
            continue

        # Attenuate beats amplify. A code that's both attenuated AND in an
        # anchor tier should still be attenuated — the resolver flagged it
        # as noisy in this context, that signal takes priority.
        if code in attenuate_codes:
            out[i] = base * ATTENUATE_FACTOR
            continue

        if code in amplify_codes or (tier is not None and tier in anchor_tier_set):
            out[i] = base * AMPLIFY_FACTOR
            continue

        out[i] = base

    return out


__all__ = ["build_adaptive_weight_vector", "AMPLIFY_FACTOR", "ATTENUATE_FACTOR"]
