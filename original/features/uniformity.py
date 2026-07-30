"""
features/uniformity.py — Tier 18: second-moment uniformity features.

Current tiers are per-document MEANS; generation artifacts (LLM output,
cautious forgeries) often live in the WITHIN-document spread instead —
unusually uniform sentence lengths, function-word timing, punctuation
placement. This module extracts raw (un-normalized) dispersion values;
NORM_BOUNDS-based [0,1] scaling happens in pipeline.py, matching every
other tier's contract (see tier17.py for the precedent).

Ships inside DISABLED_FEATURE_GROUPS by default. See design spec §8 for
the two gates (G2b, G6) required before this group may be enabled.
"""

from __future__ import annotations

import statistics

from .tier1 import TextDoc

_FUNCTION_WORDS = frozenset(
    "the a an of in on at to for with by from as is are was were be been "
    "being have has had do does did this that these those and or but if "
    "not no so than then".split()
)

_PUNCT_CHARS = frozenset(",.;:!?")


def _sentence_word_counts(doc: TextDoc) -> list[int]:
    return [len(s.split()) for s in doc.sentences if s.split()]


def sentence_length_dispersion_ratio(doc: TextDoc) -> float:
    """Within-doc sentence-length CV, as a raw dispersion value (the
    ÷-baseline-typical-CV comparison happens at scoring time via the
    ordinary z-score machinery, not here — see the design spec §8 note
    on feature purity)."""
    counts = _sentence_word_counts(doc)
    if len(counts) < 3:
        return 0.5
    mean = statistics.mean(counts)
    if mean < 1e-9:
        return 0.0
    return statistics.stdev(counts) / mean


def window_feature_variance_ratio(doc: TextDoc) -> float:
    """Variance of sentence length over 3-sentence windows, raw."""
    counts = _sentence_word_counts(doc)
    if len(counts) < 6:
        return 0.5
    window_means = [statistics.mean(counts[i : i + 3]) for i in range(0, len(counts) - 2, 3)]
    if len(window_means) < 2:
        return 0.5
    return statistics.variance(window_means)


def function_word_burstiness_ratio(doc: TextDoc) -> float:
    """Inter-arrival dispersion of function words across the document,
    raw. Low burstiness (evenly spaced) is the uniformity signal."""
    words = doc.text.lower().split()
    positions = [i for i, w in enumerate(words) if w.strip(".,;:!?") in _FUNCTION_WORDS]
    if len(positions) < 5:
        return 0.5
    gaps = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
    mean_gap = statistics.mean(gaps)
    if mean_gap < 1e-9:
        return 0.0
    return statistics.stdev(gaps) / mean_gap


def punctuation_dispersion_ratio(doc: TextDoc) -> float:
    """Per-window punctuation-rate variance, raw."""
    sentences = [s for s in doc.sentences if s.strip()]
    if len(sentences) < 4:
        return 0.5
    rates = []
    for s in sentences:
        n_words = max(1, len(s.split()))
        n_punct = sum(1 for ch in s if ch in _PUNCT_CHARS)
        rates.append(n_punct / n_words)
    if len(rates) < 2:
        return 0.5
    return statistics.variance(rates)


def vocab_introduction_flatness(doc: TextDoc) -> float:
    """
    Fit of the new-type-introduction-rate decay curve. Standalone (no
    baseline needed). A flat (non-decaying) introduction rate across the
    document is atypical of genuine human prose, where new-word
    introduction naturally decays as the document progresses.
    """
    words = [w.strip(".,;:!?\"'()").lower() for w in doc.text.split()]
    words = [w for w in words if w]
    if len(words) < 20:
        return 0.5
    seen: set[str] = set()
    new_type_flags = []
    for w in words:
        new_type_flags.append(0 if w in seen else 1)
        seen.add(w)
    n_buckets = 4
    bucket_size = max(1, len(new_type_flags) // n_buckets)
    bucket_rates = []
    for i in range(0, len(new_type_flags), bucket_size):
        chunk = new_type_flags[i : i + bucket_size]
        bucket_rates.append(statistics.mean(chunk) if chunk else 0.0)
    bucket_rates = bucket_rates[:n_buckets]
    if len(bucket_rates) < 2 or bucket_rates[0] < 1e-9:
        return 0.5
    # Flatness: how close the LAST bucket's rate is to the FIRST bucket's
    # rate. Genuine decay -> low value (last << first). Flat -> high value.
    return min(1.0, bucket_rates[-1] / bucket_rates[0])


def clause_depth_variance_ratio(doc: TextDoc) -> float:
    """
    Per-sentence clause-depth variance, raw, approximated by comma+
    subordinating-conjunction count per sentence (a cheap proxy avoiding a
    full dependency parse, consistent with Tier 1's cheap-feature philosophy).
    """
    subordinators = frozenset(
        "because although though while since unless whereas whenever "
        "wherever if when as after before until".split()
    )
    sentences = [s for s in doc.sentences if s.strip()]
    if len(sentences) < 4:
        return 0.5
    depths = []
    for s in sentences:
        words = s.lower().split()
        depth = s.count(",") + sum(1 for w in words if w.strip(".,;:!?") in subordinators)
        depths.append(depth)
    if len(depths) < 2:
        return 0.5
    return statistics.variance(depths)


def extract_uniformity(doc: TextDoc) -> dict[str, float]:
    """Compute all 6 Tier 18 uniformity features. Raw values; normalisation
    to [0, 1] is applied by pipeline.py via NORM_BOUNDS."""
    return {
        "sentence_length_dispersion_ratio": sentence_length_dispersion_ratio(doc),
        "window_feature_variance_ratio": window_feature_variance_ratio(doc),
        "function_word_burstiness_ratio": function_word_burstiness_ratio(doc),
        "punctuation_dispersion_ratio": punctuation_dispersion_ratio(doc),
        "vocab_introduction_flatness": vocab_introduction_flatness(doc),
        "clause_depth_variance_ratio": clause_depth_variance_ratio(doc),
    }
