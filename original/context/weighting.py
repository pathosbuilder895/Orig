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

from collections.abc import Sequence

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

# ── Genre-mismatch attenuation (2026-08 cross-genre study) ───────────────────
#
# validation/genre_crossgenre_2026-08/ found the static per-tier weight
# vector fails at recognizing a student's own writing when their submission's
# genre isn't one their baseline has ever covered: topic/genre-sensitive
# tiers inflate the deviation score enough to look like a different author
# (mean raw-score AUC 0.39, worse than chance, on a held-out-genre test).
#
# Tiers 2 and 3 are ALREADY down-weighted in the static TIER_WEIGHTS for
# exactly this reason ("topic-sensitive features shift with topic even
# within same-author writing" / "more topic-sensitive" — see constants.py).
# The study's tier-ablation (validation/genre_crossgenre_2026-08/tier_probe.py)
# found removing tiers 3, 9, and 10 from a genre-invariance weighting
# NEUTRAL-TO-POSITIVE for cross-genre recognition — i.e. on that corpus they
# were noise, not signal, specifically under a genre mismatch. This extends
# the SAME existing "topic-sensitive → attenuate" reasoning to tiers 9
# (argument topology — already commented "partially topic-sensitive" in
# TIER_WEIGHTS) and 10 (semantic gravity wells), and reuses the existing
# ATTENUATE_FACTOR rather than inventing a new magnitude.
#
# Deliberately NOT a full per-feature reweighting: a companion multi-author
# test (validation/public_authors/, 10 authors) found the study's full
# per-feature "DNA" vector does NOT generalize as a blanket replacement —
# it actively hurts same-genre discrimination, because the same
# topic-sensitive features carry genuine between-author signal when genre
# IS covered. Gating this attenuation behind `genre_covered=False` (only
# applied when the submission's genre is genuinely new to this student) is
# what keeps it safe: it never fires for the common case.
#
# ⚠️ STILL NOT AUTHORISED, but the reason changed on 2026-08-08. Two blockers
# stood here; one is resolved and one is not.
#
# RESOLVED — the classifier no longer mislabels silently. v1 sorted 86% of all
# prose into rule 8's terminal `else` ("correspondence"), so
# `genre_covered_by_baseline` returned True nearly always and this attenuation
# fired only on classifier noise. GENRE_RESOLVER_V2 abstains instead of
# guessing, and `genre_covered_by_baseline` now attenuates only on a CONFIDENT
# mismatch — `unknown` on either side means do nothing. So the gate fires
# rarely and for a real reason rather than never and for a fake one. Note the
# consequence: a working classifier does not make this attenuation fire MORE.
# On the committed corpora v2 still abstains on 23% of documents, and a high
# firing rate would be grounds for suspicion, not celebration.
#
# ALSO RESOLVED — gate G8 now passes: minimum per-class precision 1.000 over
# 36 claimed documents on the author-disjoint hold-out, abstention 33.3%, and
# an author-shuffled control at 0.353 against 0.333 chance, so the classifier
# reads genre rather than authors.
#
# NOT RESOLVED — the tier set below. Tiers 2/3/9/10 have never been validated
# on independent data, and no work so far has attempted it: the genre effort
# fixed the GATE this attenuation hangs off, not the attenuation itself.
# `lexical_chain_density` is a tier-2 feature near the top of the DNA
# invariance table, so attenuating tier 2 wholesale discards one of the most
# topic-invariant signals available — that objection is untouched by anything
# above.
#
# Enabling GENRE_INVARIANT_WEIGHTS_ENABLED therefore requires a separate
# validation of THIS tier set. See
# docs/superpowers/specs/2026-08-08-genre-resolution-design.md.
GENRE_MISMATCH_ATTENUATE_TIERS: frozenset[int] = frozenset({2, 3, 9, 10})


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════


def build_adaptive_weight_vector(
    manifest: object,  # ContextManifest, duck-typed to avoid import cycle
    base_tier_weights: dict[int, float] = TIER_WEIGHTS,
    feature_codes: Sequence[str] = ALL_FEATURE_CODES,
    genre_covered: bool = True,
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
    genre_covered : bool
        From `baseline_match.genre_covered_by_baseline()`, gated by the
        caller behind GENRE_INVARIANT_WEIGHTS_ENABLED. Default True is a
        no-op (matches every call site that doesn't pass it). False applies
        an extra ATTENUATE_FACTOR multiply to GENRE_MISMATCH_ATTENUATE_TIERS
        — see that constant's comment for what motivated this and its
        validation status.

    Returns
    -------
    np.ndarray, shape (len(feature_codes),), dtype float64
        The vector to pass as `score(adaptive_weights=...)`.

    Behavioural guarantees
    ----------------------
    - Empty manifest (no anchors set, no muting, no attenuation) and
      genre_covered=True (the default) returns a vector that's element-wise
      equal to the static base-weights vector built the same way
      `scoring.py` builds `_TIER_WEIGHT_VECTOR`.
    - Mute is a hard zero; nothing else can override it, including the
      genre-mismatch attenuation.
    - A code that is BOTH attenuated AND in an anchor tier ends up
      attenuated — manifest derivation enforces mute > attenuate > amplify
      precedence; weighting just reads the resulting code lists. The
      genre-mismatch attenuation stacks multiplicatively on top of whatever
      that precedence already produced (except mute, which it can't touch).
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

    mute_codes = set(weight_mods.get("mute_codes", []))
    attenuate_codes = set(weight_mods.get("attenuate_codes", []))
    amplify_codes = set(weight_mods.get("amplify_codes", []))
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

    if not genre_covered:
        for i, code in enumerate(feature_codes):
            if code in mute_codes:
                continue  # mute is a hard zero, the genre attenuation can't override it
            tier = FEATURE_TIER.get(code)
            if tier in GENRE_MISMATCH_ATTENUATE_TIERS:
                out[i] *= ATTENUATE_FACTOR

    return out


__all__ = [
    "build_adaptive_weight_vector",
    "AMPLIFY_FACTOR",
    "ATTENUATE_FACTOR",
    "GENRE_MISMATCH_ATTENUATE_TIERS",
]
