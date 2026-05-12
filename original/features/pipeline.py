"""
features/pipeline.py — Feature extraction orchestrator.

Runs all twelve tiers and normalises raw values to [0, 1] using
the per-feature bounds in constants.NORM_BOUNDS.

Returns a FeatureVector: an ordered dict of normalised values
keyed by the exact feature codes used in the frontend.

Comparison features (COMPARISON_CODES + MUSICAL_COMPARISON_CODES) are NOT
computed here — they require baseline profiles and are computed at scoring
time.  Default value 0.5 (neutral) is inserted as a placeholder.

Tier 12 (catastrophe_index) is computed via a thin wrapper over
tension_arc.analyze_tension_arc(), imported lazily to keep it optional
during unit tests that don't have the full dependency stack.
"""

import math
from collections import Counter
from typing import Dict, Optional

import numpy as np

from .tier1 import TextDoc, extract_tier1
from .tier2 import extract_tier2
from .tier3 import extract_tier3
from .tier4 import extract_tier4, extract_tier4_profiles
from .tier5 import extract_tier5
from .tier6 import extract_tier6
from .tier7 import extract_tier7, extract_tier7_profiles
from .tier8 import extract_tier8
from .tier9 import extract_tier9_standalone, extract_tier9_profile, compute_tier9_comparison
from .tier10 import extract_tier10_standalone, extract_tier10_profile, compute_tier10_comparison
from .tier11 import extract_tier11_profile, compute_tier11_comparison
from .prosodic import extract_prosodic                          # Tiers 13–15
from .preprocess import preprocess                              # backmatter strip + citation data
from .tier16 import extract_tier16                              # Tier 16 — Citation Fingerprint
from .tier17 import extract_tier17                              # Tier 17 — Behavioral Biometrics
from ..constants import (
    NORM_BOUNDS, ALL_FEATURE_CODES, FEATURE_DIM,
    BASE_FEATURE_CODES, COMPARISON_CODES, MUSICAL_COMPARISON_CODES,
    TIER17_CODES, DISABLED_FEATURE_GROUPS,
)


def _normalise(raw: float, code: str) -> float:
    lo, hi = NORM_BOUNDS[code]
    if hi <= lo:
        return 0.0
    return float(np.clip((raw - lo) / (hi - lo), 0.0, 1.0))


# ── Tier 12: Catastrophe Index wrapper ───────────────────────────────────────

def _extract_catastrophe_index(doc: TextDoc) -> float:
    """
    Compute κ = σ(ρ) · (1 − μ(ρ)) from the Tension Arc module and map to [0,1].

    κ is computed by analyze_tension_arc() which already handles short texts
    gracefully (returns κ=0.0 with arc_flag="insufficient_length").

    Normalisation: κ is bounded in [0, 0.5] for typical prose (σ ≤ 0.5,
    1−μ ≤ 1).  We scale by dividing by 0.3 (empirical 90th-percentile value
    for human writing) and clip to [0,1].

    Falls back to 0.5 (neutral) on any import or computation error so that
    tier8–11 remain testable without the full sentence-transformer stack.
    """
    try:
        from ..tension_arc import analyze_tension_arc
        result = analyze_tension_arc(doc.text, baseline_kappa=None)
        kappa = result.catastrophe_index
        return float(np.clip(kappa / 0.3, 0.0, 1.0))
    except Exception:
        return 0.5


# ── Feature extraction ────────────────────────────────────────────────────────

def extract_features(
    text: str,
    keystroke_data: Optional[Dict] = None,
) -> Dict[str, float]:
    """
    Extract and normalise all base features from raw text.

    Returns a dict {feature_code: normalised_value ∈ [0,1]}.
    Comparison features (COMPARISON_CODES + MUSICAL_COMPARISON_CODES) are set
    to 0.5 (neutral placeholder) and computed at scoring time.

    Args:
        text:           Raw submission text.
        keystroke_data: Optional Bbook stylemetry JSON (keystrokes, pauses,
                        revisions, deletionRate, wordCount, …).  When provided,
                        Tier 17 behavioral biometric features are computed from
                        this data.  When absent, all Tier 17 features default to
                        0.5 (neutral) so they do not influence the density matrix.

    Preprocessing steps (before feature extraction):
    - Strip bibliography, appendix, and notes sections
    - Extract citation fingerprint data (for Tier 16)
    - Strip parenthetical citations, footnote markers, and block quotes from prose
    """
    # ── Preprocessing: strip back-matter + clean citations from prose ─────────
    prose, citation_data = preprocess(text)

    # Build TextDoc from clean prose (not raw text)
    doc = TextDoc(prose)

    raw: Dict[str, float] = {}
    raw.update(extract_tier1(doc))
    raw.update(extract_tier2(doc))
    raw.update(extract_tier3(doc))
    raw.update(extract_tier4(doc))
    raw.update(extract_tier5(doc))
    raw.update(extract_tier6(doc))
    raw.update(extract_tier7(doc))
    raw.update(extract_tier8(doc))                        # Tier 8 — Prosodic Rhythm
    raw.update(extract_tier9_standalone(doc))             # Tier 9 standalone
    raw.update(extract_tier10_standalone(doc))            # Tier 10 standalone
    raw["catastrophe_index"] = _extract_catastrophe_index(doc)  # Tier 12
    raw.update(extract_prosodic(doc))                     # Tiers 13–15 (15 features)
    raw.update(extract_tier16(citation_data))             # Tier 16 — Citation Fingerprint

    # Tier 17 — Behavioral Biometrics (keystroke data from Bbook)
    # Only computed when: (a) keystroke_data is provided AND
    #                     (b) "behavioral" is not in DISABLED_FEATURE_GROUPS.
    # When disabled or absent, features are set to 0.5 (neutral placeholder).
    # The active_feature_mask in state.py will automatically exclude them from
    # the density matrix so they contribute zero noise to the deviation score.
    if keystroke_data and "behavioral" not in DISABLED_FEATURE_GROUPS:
        raw.update(extract_tier17(keystroke_data))
    else:
        for code in TIER17_CODES:
            lo, hi = NORM_BOUNDS[code]
            raw[code] = (lo + hi) / 2   # midpoint → 0.5 after normalisation

    # Normalise base features (Tiers 8–12 standalone already output [0,1];
    # _normalise() is a no-op clip for bounds=(0.0, 1.0))
    result = {code: _normalise(raw[code], code) for code in BASE_FEATURE_CODES}

    # All comparison features: placeholder until scoring time
    for code in MUSICAL_COMPARISON_CODES + list(COMPARISON_CODES):
        result[code] = 0.5

    return result


def extract_profiles(text: str) -> Dict[str, object]:
    """
    Extract comparison profiles from raw text.

    Returns a dict of profiles keyed by underscore-prefixed names:
      _char_trigram_profile:       top-200 char trigram frequencies
      _function_word_profile:      top-30 function word frequencies
      _argument_sequence_profile:  List[str] of rhetorical move labels
      _semantic_embeddings:        np.ndarray (N, 384) sentence embeddings
      _error_profile:              Dict[str, float] error rates per 100 words
    """
    prose, _ = preprocess(text)
    doc = TextDoc(prose)
    profiles: Dict[str, object] = {}
    profiles.update(extract_tier4_profiles(doc))
    profiles.update(extract_tier7_profiles(doc))
    profiles.update(extract_tier9_profile(doc))    # Tier 9 — argument sequence
    profiles.update(extract_tier10_profile(doc))   # Tier 10 — sentence embeddings
    profiles.update(extract_tier11_profile(doc))   # Tier 11 — error profile
    return profiles


def compute_comparison_features(
    submission_profiles: Dict[str, object],
    baseline_profiles: Dict[str, object],
) -> Dict[str, float]:
    """
    Compute all comparison features between submission and baseline.

    Returns raw values for the two existing char/funcword divergence features.
    Musical comparison features (Tiers 9–11) are computed separately in
    compute_full_features() and are already normalised to [0,1].
    """
    result: Dict[str, float] = {}

    # Character trigram profile divergence (KL-divergence, bits)
    sub_trigrams = submission_profiles.get("_char_trigram_profile", {})
    base_trigrams = baseline_profiles.get("_char_trigram_profile", {})
    result["char_trigram_profile_divergence"] = _kl_divergence(sub_trigrams, base_trigrams)

    # Function word profile divergence (KL-divergence, bits)
    sub_fw = submission_profiles.get("_function_word_profile", {})
    base_fw = baseline_profiles.get("_function_word_profile", {})
    result["function_word_profile_divergence"] = _kl_divergence(sub_fw, base_fw)

    return result


def normalise_comparison_features(raw: Dict[str, float]) -> Dict[str, float]:
    """Normalise raw comparison features to [0, 1]."""
    return {code: _normalise(val, code) for code, val in raw.items()}


def _kl_divergence(p_counts: Dict, q_counts: Dict) -> float:
    """
    Compute KL-divergence D_KL(P || Q) from frequency count dicts.

    Uses add-1 (Laplace) smoothing to avoid division by zero.
    Returns divergence in bits (log2).
    """
    if not p_counts or not q_counts:
        return 0.0

    # Build unified vocabulary
    all_keys = set(p_counts.keys()) | set(q_counts.keys())
    if not all_keys:
        return 0.0

    # Smoothed probabilities
    p_total = sum(p_counts.values()) + len(all_keys)
    q_total = sum(q_counts.values()) + len(all_keys)

    kl = 0.0
    for key in all_keys:
        p_prob = (p_counts.get(key, 0) + 1) / p_total
        q_prob = (q_counts.get(key, 0) + 1) / q_total
        if p_prob > 0:
            kl += p_prob * math.log2(p_prob / q_prob)

    return max(kl, 0.0)  # KL should be non-negative


def build_aggregate_baseline_profiles(
    baseline_texts: list[str],
) -> Dict[str, object]:
    """
    Build aggregate comparison profiles from multiple baseline texts.

    Dict-type profiles (char trigram, function word) are merged by summing
    frequency counts.  List/array-type profiles (argument sequences, embeddings,
    error profiles) are collected into lists so that Tier 9/10/11 comparison
    functions can access per-sample structure.
    """
    merged: Dict[str, object] = {
        # Existing dict-merge profiles
        "_char_trigram_profile":     {},
        "_function_word_profile":    {},
        # New list-collect profiles (one entry per baseline sample)
        "_argument_sequence_profiles": [],
        "_semantic_embeddings_list":   [],
        "_error_profiles":             [],
    }

    for text in baseline_texts:
        if not text:
            continue
        profiles = extract_profiles(text)

        # Dict-type: merge by summing counts
        for key in ("_char_trigram_profile", "_function_word_profile"):
            for tok, count in profiles.get(key, {}).items():
                d = merged[key]
                d[tok] = d.get(tok, 0) + count   # type: ignore[index]

        # List-type: append per-sample values
        merged["_argument_sequence_profiles"].append(          # type: ignore[union-attr]
            profiles.get("_argument_sequence_profile", [])
        )
        merged["_semantic_embeddings_list"].append(            # type: ignore[union-attr]
            profiles.get("_semantic_embeddings")
        )
        merged["_error_profiles"].append(                      # type: ignore[union-attr]
            profiles.get("_error_profile", {})
        )

    return merged


def compute_full_features(
    text: str,
    baseline_texts: list[str],
    keystroke_data: Optional[Dict] = None,
    baseline_indices: Optional[list[int]] = None,
) -> Dict[str, float]:
    """
    Extract all features including comparison features.

    This is the end-to-end feature extraction that should be used at
    scoring time when baseline texts are available.

    Args:
        text:             The submission text to extract features from.
        baseline_texts:   List of raw baseline texts for the student.
        keystroke_data:   Optional Bbook stylemetry JSON for Tier 17.
        baseline_indices: Optional list of indices into ``baseline_texts``
                          selecting a contextual cluster (Phase 4 baseline
                          matching). When ``None`` (default), all baseline
                          texts are used — preserves Phase 1 behaviour.
                          When ``[]`` (anchor-only fallback), comparison
                          features are computed against an empty cluster
                          (i.e. comparison features stay at the 0.5 neutral
                          placeholder set by ``extract_features``).

    Returns:
        Complete feature dict with all 103 features normalised to [0,1].
    """
    # Extract base features (comparison features set to 0.5 placeholder)
    features = extract_features(text, keystroke_data=keystroke_data)

    # Phase 4 cluster filter: when an index list is supplied, slice
    # baseline_texts down to the matched cluster. None preserves the legacy
    # path; [] yields anchor-only fallback (no comparison features computed).
    if baseline_indices is not None:
        baseline_texts = [
            baseline_texts[i] for i in baseline_indices
            if 0 <= i < len(baseline_texts)
        ]

    # If we have baseline texts, compute real comparison features
    if baseline_texts:
        sub_profiles = extract_profiles(text)
        base_profiles = build_aggregate_baseline_profiles(baseline_texts)

        # Existing char-trigram and function-word divergence features
        raw_comparison = compute_comparison_features(sub_profiles, base_profiles)
        features.update(normalise_comparison_features(raw_comparison))

        # New musical comparison features (Tiers 9–11) — already normalised to [0,1]
        features.update(compute_tier9_comparison(sub_profiles, base_profiles))
        features.update(compute_tier10_comparison(sub_profiles, base_profiles))
        features.update(compute_tier11_comparison(sub_profiles, base_profiles))

    return features


def feature_vector(
    text: str,
    keystroke_data: Optional[Dict] = None,
) -> np.ndarray:
    """
    Extract features and return as a numpy array of shape (FEATURE_DIM,).
    Order is determined by ALL_FEATURE_CODES.
    """
    feats = extract_features(text, keystroke_data=keystroke_data)
    return np.array([feats[c] for c in ALL_FEATURE_CODES], dtype=np.float64)
