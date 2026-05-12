"""
features/tier2.py — Tier 2: Discourse Analysis

Thirteen features that fingerprint how a writer organises information
on the page — largely genre-invariant, highly individual.

Approach: pure Python + regex. No dependency parser available in
offline deployment, so thematic progression uses sentence-level
subject-word overlap as a proxy for linear vs. constant-theme chaining.
"""

import re
import math
from collections import Counter
from typing import List, Dict, Set

from .tier1 import TextDoc, _tokenize
from ..constants import (
    DISCOURSE_MARKERS, TRANSITION_PHRASES, STOP_WORDS, FUNCTION_WORDS
)

# ── Helpers ──────────────────────────────────────────────────────────────────

def _content_words(sentence: str) -> Set[str]:
    """Lower-cased non-stop alphabetic tokens in a sentence."""
    return {w.lower() for w in re.findall(r'\b[a-zA-Z]{3,}\b', sentence)
            if w.lower() not in STOP_WORDS and not w.lower() in FUNCTION_WORDS}


def _find_discourse_markers(text: str):
    """Return list of (marker, category) found in text (lower-cased)."""
    lower = text.lower()
    found = []
    for marker, cat in DISCOURSE_MARKERS.items():
        # Use word-boundary matching for single words, plain search for phrases
        if " " in marker:
            if marker in lower:
                found.append((marker, cat))
        else:
            if re.search(r'\b' + re.escape(marker) + r'\b', lower):
                found.append((marker, cat))
    return found


# ── Feature extractors ───────────────────────────────────────────────────────

def discourse_marker_density(doc: TextDoc) -> float:
    """Total discourse markers per 100 words."""
    if not doc.word_count:
        return 0.0
    markers = _find_discourse_markers(doc.clean)
    return len(markers) / doc.word_count * 100


def _marker_category_ratios(doc: TextDoc) -> Dict[str, float]:
    """Fraction of all markers belonging to each category."""
    markers = _find_discourse_markers(doc.clean)
    if not markers:
        return {"additive": 0.0, "adversative": 0.0, "causal": 0.0, "temporal": 0.0}
    cats = Counter(cat for _, cat in markers)
    total = len(markers)
    return {
        "additive":    cats.get("additive",    0) / total,
        "adversative": cats.get("adversative", 0) / total,
        "causal":      cats.get("causal",      0) / total,
        "temporal":    cats.get("temporal",    0) / total,
    }


def additive_ratio(doc: TextDoc) -> float:
    return _marker_category_ratios(doc)["additive"]


def adversative_ratio(doc: TextDoc) -> float:
    return _marker_category_ratios(doc)["adversative"]


def causal_ratio(doc: TextDoc) -> float:
    return _marker_category_ratios(doc)["causal"]


def temporal_ratio(doc: TextDoc) -> float:
    return _marker_category_ratios(doc)["temporal"]


def thematic_progression_score(doc: TextDoc) -> float:
    """
    Proxy for linear vs. constant-theme progression.

    For each adjacent sentence pair (A, B):
    - 'linear'  if B's subject area (first third of B's content words)
                overlaps with A's rheme (last third of A's content words)
    - 'constant' if B's subject area overlaps with A's subject area (first third)

    score = linear_count / max(1, pair_count)
    Higher = more linear (new information chaining).
    """
    sents = doc.sentences
    if len(sents) < 2:
        return 0.5  # indeterminate

    linear_count = 0
    constant_count = 0
    pairs = 0

    for i in range(1, len(sents)):
        cw_prev = list(_content_words(sents[i - 1]))
        cw_curr = list(_content_words(sents[i]))
        if not cw_prev or not cw_curr:
            continue

        n_prev = max(1, len(cw_prev))
        n_curr = max(1, len(cw_curr))

        # Rheme = last half of previous sentence's content words
        rheme_prev  = set(cw_prev[n_prev // 2:])
        # Theme = first half of previous sentence's content words
        theme_prev  = set(cw_prev[:max(1, n_prev // 2)])
        # Theme of current sentence
        theme_curr  = set(cw_curr[:max(1, n_curr // 2)])

        if theme_curr & rheme_prev:
            linear_count += 1
        if theme_curr & theme_prev:
            constant_count += 1
        pairs += 1

    if pairs == 0:
        return 0.5
    return linear_count / pairs


def pronoun_reference_density(doc: TextDoc) -> float:
    """Anaphoric pronouns (he/she/it/they/this/that/these/those) per sentence."""
    if not doc.sentence_count:
        return 0.0
    anaphoric = {
        "he", "him", "his", "she", "her", "hers",
        "it", "its", "they", "them", "their",
        "this", "that", "these", "those",
        "such", "the former", "the latter",
    }
    count = sum(1 for w in doc.lower_words if w in anaphoric)
    return count / doc.sentence_count


def lexical_chain_density(doc: TextDoc) -> float:
    """
    Mean Jaccard similarity of content-word sets in adjacent sentences.
    High = student reuses vocabulary across sentence boundaries (cohesion).
    """
    sents = doc.sentences
    if len(sents) < 2:
        return 0.0

    scores = []
    for i in range(1, len(sents)):
        a = _content_words(sents[i - 1])
        b = _content_words(sents[i])
        if not a or not b:
            continue
        intersection = len(a & b)
        union = len(a | b)
        if union > 0:
            scores.append(intersection / union)

    return sum(scores) / len(scores) if scores else 0.0


def paragraph_topic_position(doc: TextDoc) -> float:
    """
    Fraction of paragraphs where the first sentence has the highest
    lexical density (content words / total words) — a proxy for
    fronted topic sentences.
    """
    paras = doc.paragraphs
    if not paras:
        return 0.5

    fronted = 0
    for para in paras:
        if len(para) < 2:
            fronted += 1  # single-sentence paragraph trivially fronted
            continue
        densities = []
        for sent in para:
            toks = _tokenize(sent)
            if not toks:
                densities.append(0.0)
                continue
            cw = [t for t in toks if t.lower() not in STOP_WORDS and t.isalpha()]
            densities.append(len(cw) / len(toks))
        if densities and densities[0] == max(densities):
            fronted += 1

    return fronted / len(paras)


def avg_paragraph_length(doc: TextDoc) -> float:
    """Mean sentences per paragraph."""
    paras = doc.paragraphs
    if not paras:
        return float(doc.sentence_count)
    return sum(len(p) for p in paras) / len(paras)


def sentence_opener_variety(doc: TextDoc) -> float:
    """
    Shannon entropy over the distribution of sentence-opening word classes.
    We approximate word class by pattern:
      - pronoun opener (I, We, He, She, They, It, This, That, These, Those)
      - conjunction opener (Although, While, Despite, Since, When, After, …)
      - adverbial opener (However, Furthermore, Therefore, Moreover, …)
      - nominal opener (The, A, An + noun)
      - verb opener (gerund or verb-first)
      - other

    Normalised by log2(6) so 1.0 = perfectly uniform distribution.
    """
    PRONOUN_OPENERS   = {"i","we","he","she","they","it","this","that","these","those"}
    CONJUNCTION_OPENERS = {"although","while","despite","since","when","after",
                           "before","because","if","unless","until","though","whereas"}
    ADVERBIAL_OPENERS = {"however","furthermore","therefore","moreover","consequently",
                         "thus","hence","additionally","nevertheless","nonetheless",
                         "first","second","third","finally","next","then","initially",
                         "subsequently","ultimately","accordingly","indeed","clearly"}

    classes = []
    for sent in doc.sentences:
        first = re.match(r'\b(\w+)', sent)
        if not first:
            classes.append("other")
            continue
        w = first.group(1).lower()
        if w in PRONOUN_OPENERS:
            classes.append("pronoun")
        elif w in CONJUNCTION_OPENERS:
            classes.append("conjunction")
        elif w in ADVERBIAL_OPENERS:
            classes.append("adverbial")
        elif w in {"the", "a", "an"}:
            classes.append("nominal")
        elif sent.strip()[:1].islower():
            classes.append("continuation")
        else:
            classes.append("other")

    if not classes:
        return 0.0

    counts = Counter(classes)
    n = len(classes)
    entropy = -sum((c / n) * math.log2(c / n) for c in counts.values() if c > 0)
    max_entropy = math.log2(6)  # 6 categories
    return min(entropy / max_entropy, 1.0)


def cohesion_device_ratio(doc: TextDoc) -> float:
    """
    (pronoun_tokens + discourse_marker_tokens + repeated_content_noun_tokens)
    / total word tokens.
    """
    if not doc.word_count:
        return 0.0

    # Pronouns
    all_pronouns = {
        "i","me","my","mine","myself","we","us","our","ours","ourselves",
        "he","him","his","she","her","hers","they","them","their",
        "it","its","this","that","these","those","such","one",
    }
    pron_count = sum(1 for w in doc.lower_words if w in all_pronouns)

    # Discourse markers (token count)
    dm_count = len(_find_discourse_markers(doc.clean))

    # Repeated content nouns: words ≥4 chars, non-stop, appearing ≥2 times
    freq = Counter(doc.lower_words)
    repeated = sum(
        v for w, v in freq.items()
        if len(w) >= 4 and w not in STOP_WORDS and v >= 2
    )

    total_cohesive = pron_count + dm_count + repeated
    return min(total_cohesive / doc.word_count, 1.0)


def transition_density(doc: TextDoc) -> float:
    """Transition phrases per 100 words."""
    if not doc.word_count:
        return 0.0
    lower = doc.clean.lower()
    count = 0
    for phrase in TRANSITION_PHRASES:
        if " " in phrase:
            count += lower.count(phrase)
        else:
            count += len(re.findall(r'\b' + re.escape(phrase) + r'\b', lower))
    return count / doc.word_count * 100


# ── Cache marker ratios to avoid re-computing ────────────────────────────────

_CACHED_RATIOS: Dict[int, Dict[str, float]] = {}


def extract_tier2(doc: TextDoc) -> Dict[str, float]:
    ratios = _marker_category_ratios(doc)
    return {
        "discourse_marker_density":   discourse_marker_density(doc),
        "additive_ratio":             ratios["additive"],
        "adversative_ratio":          ratios["adversative"],
        "causal_ratio":               ratios["causal"],
        "temporal_ratio":             ratios["temporal"],
        "thematic_progression_score": thematic_progression_score(doc),
        "pronoun_reference_density":  pronoun_reference_density(doc),
        "lexical_chain_density":      lexical_chain_density(doc),
        "paragraph_topic_position":   paragraph_topic_position(doc),
        "avg_paragraph_length":       avg_paragraph_length(doc),
        "sentence_opener_variety":    sentence_opener_variety(doc),
        "cohesion_device_ratio":      cohesion_device_ratio(doc),
        "transition_density":         transition_density(doc),
    }
