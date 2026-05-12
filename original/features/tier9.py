"""
features/tier9.py — Cognitive Sequencing (Argument Topology).

Tracks the sequence of rhetorical moves (Q=Question, C=Claim, E=Evidence,
K=Concession, R=Resolution, N=Neutral) and computes:

  1. structural_centrist_penalty (standalone): bigram-diversity of the move
     sequence vs. a low-diversity AI-canonical Q→C→E pattern. Low diversity
     = high penalty (AI-like).

  2. argument_sequence_likelihood (comparison): mean log-likelihood of the
     submission's move sequence under the Markov transition matrix M learned
     from the student's baseline texts.

     L = (1/T) Σₜ log P(mₜ | mₜ₋₁)

     Mapped to [0,1]: score = clip(1 + L/3, 0, 1)
       (L ∈ (−∞, 0]; L≈0 → score≈1.0; L=−3 → score=0.0)

Note: uses plain-string sentence list from TextDoc (doc.sentences); no spaCy
required for this tier.
"""

import math
from typing import Dict, List

import numpy as np

from .tier1 import TextDoc
from ..constants import DISCOURSE_MARKERS

# ── Rhetorical move labels ────────────────────────────────────────────────────

_MOVE_LABELS = ["Q", "C", "E", "K", "R", "N"]
_MOVE_IDX    = {m: i for i, m in enumerate(_MOVE_LABELS)}

# Evidence cue phrases
_EVIDENCE_CUES = {
    "according to", "studies show", "research shows", "data suggests",
    "the text states", "as cited", "for example", "for instance",
    "as shown", "evidence shows", "the passage", "scripture states",
    "as written", "as recorded", "ibid", "et al", "cf.",
}

# Resolution cue words (causal + temporal conclusion markers)
_RESOLUTION_CUES = {
    "therefore", "thus", "hence", "consequently", "in conclusion",
    "to summarize", "finally", "in summary", "it follows", "accordingly",
    "as a result", "for this reason",
}

# Claim cue phrases
_CLAIM_CUES = {
    "i argue", "i contend", "one can conclude", "this shows",
    "this demonstrates", "this means", "this implies", "this proves",
    "the argument is", "it is argued",
}


def _tag_move(sentence: str) -> str:
    """
    Classify a sentence string into one of six rhetorical move types using
    keyword heuristics.  Priority: Q > K > R > E > C > N.
    """
    text_lower = sentence.lower().strip()
    stripped   = sentence.strip()

    # Q — Question: ends with '?'
    if stripped.endswith("?"):
        return "Q"

    # K — Concession: adversative discourse marker
    for marker, kind in DISCOURSE_MARKERS.items():
        if kind == "adversative" and marker in text_lower:
            return "K"

    # R — Resolution: causal/conclusion markers
    for cue in _RESOLUTION_CUES:
        if cue in text_lower:
            return "R"

    # E — Evidence: citation/example cues
    for cue in _EVIDENCE_CUES:
        if cue in text_lower:
            return "E"

    # C — Claim: explicit claim language
    for cue in _CLAIM_CUES:
        if cue in text_lower:
            return "C"

    # N — Neutral (background, elaboration)
    return "N"


def _build_move_sequence(doc: TextDoc) -> List[str]:
    """Return the rhetorical move label for each sentence in the document."""
    return [_tag_move(s) for s in doc.sentences]


# ── Standalone feature ────────────────────────────────────────────────────────

def extract_tier9_standalone(doc: TextDoc) -> Dict[str, float]:
    """
    structural_centrist_penalty: how much the submission's move sequence
    resembles the repetitive, low-diversity AI pattern (Q→C→E cycles).

    Metric: 1 − (unique_bigrams / total_bigrams)
      Low diversity (few unique transitions) → high penalty → score near 1.0
      High diversity (many unique transitions) → low penalty → score near 0.0
    """
    moves = _build_move_sequence(doc)
    if len(moves) < 3:
        return {"structural_centrist_penalty": 0.5}

    bigrams = list(zip(moves, moves[1:]))
    unique_ratio = len(set(bigrams)) / max(len(bigrams), 1)
    # Low unique_ratio (repetitive Q→C→E) → high centrist_penalty
    centrist_penalty = float(np.clip(1.0 - unique_ratio, 0.0, 1.0))
    return {"structural_centrist_penalty": centrist_penalty}


# ── Profile extraction (for comparison at scoring time) ──────────────────────

def extract_tier9_profile(doc: TextDoc) -> Dict[str, object]:
    """Extract the raw move sequence to store as a baseline profile."""
    return {"_argument_sequence_profile": _build_move_sequence(doc)}


# ── Comparison feature ────────────────────────────────────────────────────────

def compute_tier9_comparison(
    sub_profile: Dict[str, object],
    baseline_profiles: Dict[str, object],
) -> Dict[str, float]:
    """
    argument_sequence_likelihood: mean log-likelihood of the submission's
    move sequence under the Markov transition matrix learned from baseline.

    M[i][j] = P(move_j | move_i) — estimated from baseline bigram counts
               with Laplace (add-0.1) smoothing.

    L = (1/T) Σₜ log P(mₜ | mₜ₋₁)   — mean log-prob (∈ (−∞, 0])
    score = clip(1 + L / 3, 0, 1)     — 0→1 scaling (L=0 → 1.0; L=−3 → 0.0)
    """
    # Build transition matrix from all baseline move sequences
    M = np.full((6, 6), 0.1, dtype=np.float64)   # Laplace smoothing
    for seq in baseline_profiles.get("_argument_sequence_profiles", []):
        for a, b in zip(seq, seq[1:]):
            M[_MOVE_IDX.get(a, 5)][_MOVE_IDX.get(b, 5)] += 1.0
    # Row-normalise → probability distribution
    row_sums = M.sum(axis=1, keepdims=True)
    M = M / row_sums

    sub_seq = sub_profile.get("_argument_sequence_profile", [])
    if len(sub_seq) < 2:
        return {"argument_sequence_likelihood": 0.5}

    # Mean log-probability of the submission's transition sequence
    log_probs = [
        math.log(float(M[_MOVE_IDX.get(a, 5)][_MOVE_IDX.get(b, 5)]) + 1e-9)
        for a, b in zip(sub_seq, sub_seq[1:])
    ]
    mean_ll = float(np.mean(log_probs))   # ∈ (−∞, 0]

    # Map to [0,1]: score ≈ 1.0 when L≈0 (highly likely), ≈ 0 when L≤−3
    score = float(np.clip(1.0 + mean_ll / 3.0, 0.0, 1.0))
    return {"argument_sequence_likelihood": score}
