"""
features/tier4.py — Tier 4: Character & Punctuation Fingerprint

Eight features capturing sub-word and punctuation habits that are
deeply unconscious, highly author-specific, and survive vocabulary
substitution — the primary attack vector for both human editors
and AI paraphrasers.

All pure Python + collections.Counter. No NLP dependencies.
"""

import math
import re
from collections import Counter
from typing import Dict, List

from .tier1 import TextDoc


# ── Helpers ──────────────────────────────────────────────────────────────────

def _char_trigrams(text: str) -> Counter:
    """Build a Counter of all character 3-grams in lower-cased text."""
    lower = text.lower()
    trigrams: Counter = Counter()
    for i in range(len(lower) - 2):
        trigrams[lower[i:i + 3]] += 1
    return trigrams


def _shannon_entropy(counter: Counter) -> float:
    """Shannon entropy in bits from a Counter."""
    total = sum(counter.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in counter.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


def _count_pattern(text: str, pattern: str) -> int:
    """Count regex pattern matches in text."""
    return len(re.findall(pattern, text))


# ── Tier 4 feature extractors ───────────────────────────────────────────────

def char_trigram_entropy(doc: TextDoc) -> float:
    """
    Shannon entropy of the character 3-gram frequency distribution.

    Captures spelling patterns, morphological habits, and whitespace
    preferences at a sub-word level. High entropy = diverse character
    sequences. Extremely stable across topics.
    """
    trigrams = _char_trigrams(doc.clean)
    if not trigrams:
        return 0.0
    return _shannon_entropy(trigrams)


def punctuation_diversity(doc: TextDoc) -> float:
    """
    Shannon entropy of punctuation mark distribution.

    Captures habitual punctuation choices. Some writers never use
    semicolons; others use them constantly.
    """
    punct_chars = re.findall(r'[.,;:!?\u2014\u2013\u201C\u201D\u2018\u2019()/\-\[\]"\'{}]', doc.raw)
    if not punct_chars:
        return 0.0
    counter = Counter(punct_chars)
    return _shannon_entropy(counter)


def comma_rate(doc: TextDoc) -> float:
    """Commas per 100 words. One of the most author-specific habits in English."""
    if not doc.word_count:
        return 0.0
    commas = doc.raw.count(",")
    return commas / doc.word_count * 100


def semicolon_colon_rate(doc: TextDoc) -> float:
    """Semicolons + colons per 100 words. Rare enough to be highly discriminating."""
    if not doc.word_count:
        return 0.0
    count = doc.raw.count(";") + doc.raw.count(":")
    return count / doc.word_count * 100


def parenthetical_rate(doc: TextDoc) -> float:
    """Parentheses pairs per 100 words. Strong stylistic marker."""
    if not doc.word_count:
        return 0.0
    # Count opening parens as proxy for pairs
    count = doc.raw.count("(")
    return count / doc.word_count * 100


def dash_rate(doc: TextDoc) -> float:
    """Em-dashes + en-dashes + hyphens-as-dashes per 100 words."""
    if not doc.word_count:
        return 0.0
    # Em-dash (—), en-dash (–), and double-hyphen (--)
    count = (
        doc.raw.count("\u2014")
        + doc.raw.count("\u2013")
        + doc.raw.count("--")
    )
    return count / doc.word_count * 100


def quote_rate(doc: TextDoc) -> float:
    """Quotation mark pairs per 100 words. Measures direct-quote integration habit."""
    if not doc.word_count:
        return 0.0
    # Count opening quotes (straight + smart)
    count = (
        _count_pattern(doc.raw, r'(?<!\w)"(?=\w)')   # straight opening "
        + doc.raw.count("\u201C")                      # smart opening "
    )
    return count / doc.word_count * 100


def char_trigram_profile(doc: TextDoc) -> Dict[str, int]:
    """
    Return the top-200 character trigram profile for comparison features.

    This is NOT a scalar feature — it's a profile stored alongside the
    feature vector for later divergence computation at scoring time.
    """
    trigrams = _char_trigrams(doc.clean)
    return dict(trigrams.most_common(200))


# ── Public extraction function ───────────────────────────────────────────────

def extract_tier4(doc: TextDoc) -> Dict[str, float]:
    return {
        "char_trigram_entropy":     char_trigram_entropy(doc),
        "punctuation_diversity":    punctuation_diversity(doc),
        "comma_rate":               comma_rate(doc),
        "semicolon_colon_rate":     semicolon_colon_rate(doc),
        "parenthetical_rate":       parenthetical_rate(doc),
        "dash_rate":                dash_rate(doc),
        "quote_rate":               quote_rate(doc),
    }


def extract_tier4_profiles(doc: TextDoc) -> Dict[str, object]:
    """Extract comparison profiles (stored alongside feature_vector)."""
    return {
        "_char_trigram_profile": char_trigram_profile(doc),
    }
