"""
features/tier7.py — Tier 7: AI Detection Markers

Seven features targeting the statistical signatures of LLM-generated text.
Function word distributions, lexical diversity patterns, and positional
variance behave differently in AI text vs. human text — even when the
AI is prompted to "write like" a specific person.

No new dependencies beyond a precomputed word-frequency table.
"""

import math
import re
import json
import os
from collections import Counter
from typing import Dict, List

from .tier1 import TextDoc, _tokenize
from ..constants import HEDGE_WORDS, FUNCTION_WORDS

# ── Word frequency table (lazy-loaded) ──────────────────────────────────────

_WORD_FREQS: Dict[str, float] = {}
_FREQ_LOADED = False
_FREQ_FLOOR = -15.0  # log2 frequency floor for unknown words


def _load_word_freqs():
    """Load precomputed word frequency table (log2 frequencies)."""
    global _WORD_FREQS, _FREQ_LOADED
    if _FREQ_LOADED:
        return
    freq_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data", "word_frequencies.json"
    )
    try:
        with open(freq_path, "r") as f:
            raw = json.load(f)
        # Convert raw counts to log2 probabilities
        total = sum(raw.values())
        if total > 0:
            _WORD_FREQS = {w: math.log2(c / total) for w, c in raw.items()}
    except (FileNotFoundError, json.JSONDecodeError):
        pass  # graceful degradation — perplexity_proxy will use fallback
    _FREQ_LOADED = True


# ── Helpers ──────────────────────────────────────────────────────────────────

def _gini_coefficient(values: List[float]) -> float:
    """Compute Gini coefficient for a list of non-negative values."""
    if not values or len(values) < 2:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    total = sum(sorted_vals)
    if total == 0:
        return 0.0
    cumulative = 0.0
    gini_sum = 0.0
    for i, v in enumerate(sorted_vals):
        cumulative += v
        gini_sum += (2 * (i + 1) - n - 1) * v
    return gini_sum / (n * total)


# ── Tier 7 feature extractors ───────────────────────────────────────────────

def burstiness(doc: TextDoc) -> float:
    """
    Variance-to-mean ratio of sentence lengths (index of dispersion).

    Human writing is bursty (short punchy sentences mixed with long complex ones);
    LLM text tends toward uniform sentence length.
    High = bursty (human-like). Low = uniform (LLM-like).
    """
    if len(doc.sentences) < 3:
        return 1.0  # neutral for very short texts

    lengths = [len(_tokenize(s)) for s in doc.sentences]
    mean = sum(lengths) / len(lengths)
    if mean == 0:
        return 0.0
    variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)
    return variance / mean


def perplexity_proxy(doc: TextDoc) -> float:
    """
    Average negative log-frequency of word choices.

    Uses a precomputed word frequency table. Low value = very predictable
    word choices (more LLM-like). High value = surprising word choices
    (more human-like).

    Returns the mean negative log2 probability (higher = more surprising).
    """
    _load_word_freqs()
    if not doc.lower_words:
        return 0.0

    if not _WORD_FREQS:
        # Fallback: use hapax-based estimate when no frequency table available
        freq = Counter(doc.lower_words)
        total = len(doc.lower_words)
        log_probs = [math.log2(freq[w] / total) for w in doc.lower_words]
        return -sum(log_probs) / len(log_probs)

    log_probs = []
    for w in doc.lower_words:
        log_p = _WORD_FREQS.get(w, _FREQ_FLOOR)
        log_probs.append(log_p)

    return -sum(log_probs) / len(log_probs)


def repetition_gap_entropy(doc: TextDoc) -> float:
    """
    Entropy of gap distances between repeated content words.

    For repeated content words, measure the distances (in words) between
    successive occurrences, then compute the entropy of those gaps.

    Humans repeat words in clustered, topic-driven bursts (lower entropy).
    LLMs space repetitions more uniformly (higher entropy).
    """
    if not doc.lower_words or len(doc.lower_words) < 20:
        return 0.0

    # Build position lists for repeated content words
    positions: Dict[str, List[int]] = {}
    for i, w in enumerate(doc.lower_words):
        if len(w) >= 4 and w not in FUNCTION_WORDS:
            positions.setdefault(w, []).append(i)

    # Compute gaps for words that appear 2+ times
    all_gaps: List[int] = []
    for word, pos_list in positions.items():
        if len(pos_list) >= 2:
            for i in range(1, len(pos_list)):
                all_gaps.append(pos_list[i] - pos_list[i - 1])

    if not all_gaps:
        return 0.0

    # Bin gaps and compute entropy
    gap_counter = Counter(all_gaps)
    total = len(all_gaps)
    entropy = 0.0
    for count in gap_counter.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


def function_word_profile(doc: TextDoc) -> Dict[str, int]:
    """
    Return the top-30 function word frequency profile for comparison.

    This is NOT a scalar feature — it's a profile stored alongside
    the feature vector for divergence computation at scoring time.
    """
    fw_counts = Counter()
    for w in doc.lower_words:
        if w in FUNCTION_WORDS:
            fw_counts[w] += 1
    return dict(fw_counts.most_common(30))


def transition_predictability(doc: TextDoc) -> float:
    """
    How predictable paragraph-to-paragraph topic shifts are.

    Measured by mean cosine similarity of adjacent paragraph bag-of-words vectors.
    LLMs produce more uniform transitions (higher similarity).
    Humans are more variable (lower similarity).
    """
    paras = doc.paragraphs
    if len(paras) < 2:
        return 0.5  # neutral for single-paragraph texts

    # Build bag-of-words vectors per paragraph (content words only)
    def _bow(sentences: List[str]) -> Counter:
        words = Counter()
        for sent in sentences:
            for w in _tokenize(sent):
                w_lower = w.lower()
                if len(w_lower) >= 3 and w_lower not in FUNCTION_WORDS:
                    words[w_lower] += 1
        return words

    bows = [_bow(p) for p in paras]

    similarities = []
    for i in range(1, len(bows)):
        a, b = bows[i - 1], bows[i]
        if not a or not b:
            continue
        # Cosine similarity
        shared_keys = set(a.keys()) & set(b.keys())
        dot = sum(a[k] * b[k] for k in shared_keys)
        norm_a = math.sqrt(sum(v * v for v in a.values()))
        norm_b = math.sqrt(sum(v * v for v in b.values()))
        if norm_a > 0 and norm_b > 0:
            similarities.append(dot / (norm_a * norm_b))

    if not similarities:
        return 0.5
    return sum(similarities) / len(similarities)


def vocabulary_introduction_rate(doc: TextDoc) -> float:
    """
    Rate at which new unique words appear through the text.

    Divide text into 10 equal segments. Compute cumulative unique word count
    at each boundary. The AUC (normalized) measures how front-loaded vocabulary
    introduction is.

    Humans front-load vocabulary (higher AUC); LLMs introduce new words more
    uniformly through the text (lower AUC).
    """
    words = doc.lower_words
    if len(words) < 20:
        return 0.5  # insufficient text

    n_segments = 10
    segment_size = max(1, len(words) // n_segments)

    seen = set()
    cumulative_unique = []
    for seg_idx in range(n_segments):
        start = seg_idx * segment_size
        end = min(start + segment_size, len(words)) if seg_idx < n_segments - 1 else len(words)
        for w in words[start:end]:
            seen.add(w)
        cumulative_unique.append(len(seen))

    # Normalize: total unique = cumulative_unique[-1]
    total_unique = cumulative_unique[-1]
    if total_unique == 0:
        return 0.5

    # AUC of the normalized cumulative curve
    # Perfect front-loading: first segment has all unique words → AUC = 1.0
    # Uniform introduction: linear curve → AUC ≈ 0.55
    normalized = [c / total_unique for c in cumulative_unique]
    auc = sum(normalized) / n_segments
    return auc


def filler_hedge_cluster_rate(doc: TextDoc) -> float:
    """
    Whether hedging language clusters in specific locations (human) or
    distributes uniformly (LLM).

    Measured as Gini coefficient of hedge word positions (as fraction of
    document length).

    High Gini = clustered hedging (human-like).
    Low Gini = uniform hedging (LLM-like).
    """
    if not doc.lower_words or len(doc.lower_words) < 20:
        return 0.0

    total_words = len(doc.lower_words)
    hedge_positions: List[float] = []
    for i, w in enumerate(doc.lower_words):
        if w in HEDGE_WORDS:
            hedge_positions.append(i / total_words)

    if len(hedge_positions) < 3:
        return 0.0  # too few hedges to measure clustering

    # Compute gaps between consecutive hedge positions
    hedge_positions.sort()
    gaps = [hedge_positions[i] - hedge_positions[i - 1]
            for i in range(1, len(hedge_positions))]

    return _gini_coefficient(gaps)


# ── Public extraction function ───────────────────────────────────────────────

def extract_tier7(doc: TextDoc) -> Dict[str, float]:
    return {
        "burstiness":                   burstiness(doc),
        "perplexity_proxy":             perplexity_proxy(doc),
        "repetition_gap_entropy":       repetition_gap_entropy(doc),
        "transition_predictability":    transition_predictability(doc),
        "vocabulary_introduction_rate": vocabulary_introduction_rate(doc),
        "filler_hedge_cluster_rate":    filler_hedge_cluster_rate(doc),
    }


def extract_tier7_profiles(doc: TextDoc) -> Dict[str, object]:
    """Extract comparison profiles (stored alongside feature_vector)."""
    return {
        "_function_word_profile": function_word_profile(doc),
    }
