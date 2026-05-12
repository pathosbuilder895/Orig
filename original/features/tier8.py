"""
features/tier8.py — Prosodic Rhythm (Stress Entropy).

Maps syllables to binary stress values using a phonological heuristic
(vowel-cluster counting, penultimate-stress rule) and computes Shannon
entropy of stress n-gram distributions.

Mathematics
───────────
Stress sequence S = [s₁, s₂, …, sₙ]  where sᵢ ∈ {0, 1}

Shannon entropy of k-length n-grams:
    H(S,k) = -Σᵢ P(sᵢ) log₂ P(sᵢ)

Normalised to [0, 1] by dividing by k (max entropy for binary k-gram = k bits).

Features
────────
stress_entropy_unigram  — H(S, k=1)
stress_entropy_bigram   — H(S, k=2)
clausulae_consistency   — 1 - normalised_std(sentence_final_stress)
breath_group_variance   — CV(sentence_stress_lengths) / 2
"""

import math
import re
from collections import Counter
from typing import Dict, List

import numpy as np

from .tier1 import TextDoc, _tokenize


# ── Syllable stress heuristic ─────────────────────────────────────────────────

def _word_to_stress(word: str) -> List[int]:
    """
    Map a single word to a binary stress sequence using a phonological heuristic.

    Rules (English approximation):
      - Find vowel groups (V+) as proxy syllables.
      - Monosyllabic: stress = [1].
      - Polysyllabic: primary stress on penultimate syllable.
        This captures the most common English stress pattern (e.g. *DAta*, *proGRESS*).
      - All remaining syllables are unstressed (0).
    """
    groups = re.findall(r'[aeiouAEIOU]+', word)
    n = max(1, len(groups))
    stress = [0] * n
    if n == 1:
        stress[0] = 1
    else:
        stress[-2] = 1   # penultimate stress
    return stress


# ── Entropy helpers ───────────────────────────────────────────────────────────

def _stress_entropy(seq: List[int], k: int = 1) -> float:
    """
    Shannon entropy H(S,k) of k-length stress n-grams, normalised to [0, 1].

    H = -Σ P(s_i) log₂ P(s_i)
    Normalised: H_norm = H / k  (max binary k-gram entropy = k bits)

    Returns 0.5 if sequence is too short to form any n-gram.
    """
    ngrams = [tuple(seq[i : i + k]) for i in range(len(seq) - k + 1)]
    if not ngrams:
        return 0.5
    counts = Counter(ngrams)
    total = sum(counts.values())
    H = -sum((c / total) * math.log2(c / total) for c in counts.values())
    return float(np.clip(H / k, 0.0, 1.0))


# ── Main extractor ────────────────────────────────────────────────────────────

def extract_tier8(doc: TextDoc) -> Dict[str, float]:
    """
    Extract 4 prosodic rhythm features from a TextDoc.

    All returned values are already in [0, 1] — NORM_BOUNDS is (0, 1) for all,
    so _normalise() is a no-op clip.
    """
    all_stress: List[int] = []
    sentence_final_stress: List[int] = []
    sentence_stress_lengths: List[int] = []

    # doc.sentences is a List[str]; _tokenize() gives word-token strings.
    for sent_text in doc.sentences:
        sent_stress: List[int] = []
        for tok in _tokenize(sent_text):
            if tok.isalpha():
                sent_stress.extend(_word_to_stress(tok.lower()))

        all_stress.extend(sent_stress)

        if sent_stress:
            # Clausulae: stress value of the final syllable of the sentence
            sentence_final_stress.append(sent_stress[-1])

        # Breath group = number of stress units in this sentence
        sentence_stress_lengths.append(len(sent_stress))

    # ── Feature 1: Unigram stress entropy H(S, k=1) ───────────────────────────
    # Measures how evenly stressed vs. unstressed syllables are distributed.
    # High entropy (≈ 1.0) → balanced stress; Low (≈ 0.0) → monotone pattern.
    stress_entropy_unigram = _stress_entropy(all_stress, k=1)

    # ── Feature 2: Bigram stress entropy H(S, k=2) ────────────────────────────
    # Captures transition patterns (01, 10, 00, 11).
    # High entropy → varied rhythmic transitions; Low → repetitive metre.
    stress_entropy_bigram = _stress_entropy(all_stress, k=2)

    # ── Feature 3: Clausulae consistency ─────────────────────────────────────
    # A writer's habitual sentence-ending stress pattern (classical clausula).
    # std of binary values ∈ [0, 0.5]; invert so high = more consistent cadence.
    if len(sentence_final_stress) >= 2:
        clausulae_var = float(np.std(sentence_final_stress))
        clausulae_consistency = 1.0 - float(np.clip(clausulae_var / 0.5, 0.0, 1.0))
    else:
        clausulae_consistency = 0.5   # insufficient data

    # ── Feature 4: Breath-group length variance ───────────────────────────────
    # Coefficient of variation of stress-unit counts per sentence.
    # High CV → irregular phrasing (human); Low CV → metronomic (AI).
    valid_lengths = [l for l in sentence_stress_lengths if l > 0]
    if len(valid_lengths) >= 2:
        mu = float(np.mean(valid_lengths))
        cv = float(np.std(valid_lengths)) / (mu + 1e-9)
        # CV for academic prose typically 0.2–1.0; cap at 2.0 for normalisation
        breath_group_variance = float(np.clip(cv / 2.0, 0.0, 1.0))
    else:
        breath_group_variance = 0.5   # insufficient data

    return {
        "stress_entropy_unigram": stress_entropy_unigram,
        "stress_entropy_bigram":  stress_entropy_bigram,
        "clausulae_consistency":  clausulae_consistency,
        "breath_group_variance":  breath_group_variance,
    }
