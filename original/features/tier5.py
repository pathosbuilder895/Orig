"""
features/tier5.py — Tier 5: POS & Shallow Syntax

Seven features capturing grammatical rhythm independent of vocabulary.
When an editor swaps content words but leaves sentence structure intact,
POS patterns persist.

Requires spaCy with en_core_web_sm model.
"""

import logging
import math
from collections import Counter
from typing import Dict, List, Optional

from .tier1 import TextDoc

log = logging.getLogger(__name__)

# ── Lazy-loaded spaCy model ─────────────────────────────────────────────────

_nlp = None
_spacy_warning_logged = False


def _get_nlp():
    """Load spaCy model on first use (singleton)."""
    global _nlp, _spacy_warning_logged
    if _nlp is None:
        try:
            import spacy
            _nlp = spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])
        except (ImportError, OSError):
            _nlp = "unavailable"
            if not _spacy_warning_logged:
                log.warning(
                    "spaCy model unavailable — Tier 5 POS features will return neutral defaults. "
                    "Run: python -m spacy download en_core_web_sm"
                )
                _spacy_warning_logged = True
    return _nlp


def is_spacy_available() -> bool:
    """Return True if spaCy loaded successfully, False otherwise."""
    return _get_nlp() != "unavailable"


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


def _get_pos_tags(doc: TextDoc) -> Optional[List[str]]:
    """Return list of POS tags for all tokens, or None if spaCy unavailable."""
    nlp = _get_nlp()
    if nlp == "unavailable":
        return None
    spacy_doc = nlp(doc.clean)
    return [token.pos_ for token in spacy_doc if not token.is_space]


def _get_dep_depths(doc: TextDoc) -> Optional[List[int]]:
    """Return max dependency tree depth for each sentence."""
    nlp = _get_nlp()
    if nlp == "unavailable":
        return None

    spacy_doc = nlp(doc.clean)
    depths = []

    for sent in spacy_doc.sents:
        def _depth(token, seen=None):
            if seen is None:
                seen = set()
            if token.i in seen:
                return 0
            seen.add(token.i)
            children_depths = [_depth(child, seen) for child in token.children
                               if child.i not in seen]
            return 1 + max(children_depths) if children_depths else 1

        root = [t for t in sent if t.head == t]
        if root:
            depths.append(_depth(root[0]))
        else:
            depths.append(1)

    return depths


# ── Tier 5 feature extractors ───────────────────────────────────────────────

def pos_bigram_entropy(doc: TextDoc) -> float:
    """Shannon entropy of POS tag bigram distribution."""
    tags = _get_pos_tags(doc)
    if not tags or len(tags) < 2:
        return 0.0
    bigrams = Counter()
    for i in range(len(tags) - 1):
        bigrams[(tags[i], tags[i + 1])] += 1
    return _shannon_entropy(bigrams)


def pos_trigram_entropy(doc: TextDoc) -> float:
    """Shannon entropy of POS tag trigram distribution."""
    tags = _get_pos_tags(doc)
    if not tags or len(tags) < 3:
        return 0.0
    trigrams = Counter()
    for i in range(len(tags) - 2):
        trigrams[(tags[i], tags[i + 1], tags[i + 2])] += 1
    return _shannon_entropy(trigrams)


def noun_verb_ratio(doc: TextDoc) -> float:
    """NOUN / VERB count — captures nominal vs. verbal writing style."""
    tags = _get_pos_tags(doc)
    if not tags:
        return 1.0  # neutral default
    nouns = sum(1 for t in tags if t in ("NOUN", "PROPN"))
    verbs = sum(1 for t in tags if t in ("VERB", "AUX"))
    if verbs == 0:
        return 3.0  # cap for heavily nominal text
    return min(nouns / verbs, 5.0)


def adjective_rate(doc: TextDoc) -> float:
    """ADJ tags per 100 words — measures descriptive density."""
    tags = _get_pos_tags(doc)
    if not tags:
        return 0.0
    adj_count = sum(1 for t in tags if t == "ADJ")
    return adj_count / len(tags) * 100


def adverb_rate(doc: TextDoc) -> float:
    """ADV tags per 100 words — measures qualification tendency."""
    tags = _get_pos_tags(doc)
    if not tags:
        return 0.0
    adv_count = sum(1 for t in tags if t == "ADV")
    return adv_count / len(tags) * 100


def subordination_ratio(doc: TextDoc) -> float:
    """
    Subordinating conjunctions (SCONJ) per sentence.
    Measures syntactic complexity.
    """
    tags = _get_pos_tags(doc)
    if not tags or not doc.sentence_count:
        return 0.0
    sconj_count = sum(1 for t in tags if t == "SCONJ")
    return sconj_count / doc.sentence_count


def clause_depth_mean(doc: TextDoc) -> float:
    """
    Average max depth of dependency parse tree per sentence.
    Captures syntactic embedding habits.
    """
    depths = _get_dep_depths(doc)
    if not depths:
        return 3.0  # neutral fallback
    return sum(depths) / len(depths)


# ── Public extraction function ───────────────────────────────────────────────

def extract_tier5(doc: TextDoc) -> Dict[str, float]:
    return {
        "pos_bigram_entropy":   pos_bigram_entropy(doc),
        "pos_trigram_entropy":  pos_trigram_entropy(doc),
        "noun_verb_ratio":      noun_verb_ratio(doc),
        "adjective_rate":       adjective_rate(doc),
        "adverb_rate":          adverb_rate(doc),
        "subordination_ratio":  subordination_ratio(doc),
        "clause_depth_mean":    clause_depth_mean(doc),
    }
