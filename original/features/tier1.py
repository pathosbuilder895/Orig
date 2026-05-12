"""
features/tier1.py — Tier 1: Surface Stylometrics

Nine lexical and syntactic features computable with pure Python.
All functions accept a pre-processed TextDoc and return a raw value
in its natural unit. Normalization to [0,1] happens in pipeline.py.
"""

import re
import math
from typing import List, Dict

from ..constants import (
    FUNCTION_WORDS, STOP_WORDS, MODAL_VERBS, PASSIVE_PATTERNS
)


# ── TextDoc: lightweight NLP container ──────────────────────────────────────

class TextDoc:
    """Pre-processed representation of a text sample."""

    def __init__(self, text: str):
        self.raw = text
        self.text = text          # alias — used by tension_arc via pipeline
        self.clean = _clean(text)
        self.sentences: List[str] = _split_sentences(self.clean)
        self.paragraphs: List[List[str]] = _split_paragraphs(text)
        self.tokens: List[str] = _tokenize(self.clean)
        self.words: List[str] = [t for t in self.tokens if t.isalpha()]
        self.lower_words: List[str] = [w.lower() for w in self.words]
        self.word_count: int = len(self.words)
        self.sentence_count: int = len(self.sentences)

    def sent_words(self) -> List[List[str]]:
        """List of word lists, one per sentence."""
        return [_tokenize(s) for s in self.sentences]


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_sentences(text: str) -> List[str]:
    """Regex sentence splitter — handles theological abbreviations."""
    # Protect common abbreviations from being split on
    text = re.sub(r"\b(Dr|Mr|Mrs|Ms|Prof|Rev|Gen|Col|Cor|Eph|Phil|Col|etc|vs|cf|ibid|op)\.", r"\1<DOT>", text)
    text = re.sub(r"\b([A-Z])\.", r"\1<DOT>", text)   # initials
    # Split
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z\"\'(])", text)
    # Restore dots
    sentences = [s.replace("<DOT>", ".") for s in sentences]
    return [s.strip() for s in sentences if s.strip()]


def _split_paragraphs(text: str) -> List[List[str]]:
    """Return paragraphs as lists of sentences."""
    paras = re.split(r"\n\s*\n", text)
    result = []
    for p in paras:
        p = p.strip()
        if p:
            sents = _split_sentences(p)
            if sents:
                result.append(sents)
    return result if result else [[text]]


def _tokenize(text: str) -> List[str]:
    """Simple word-boundary tokenizer that preserves apostrophes."""
    return re.findall(r"\b\w+(?:'\w+)?\b", text)


# ── Tier 1 feature extractors ────────────────────────────────────────────────

def type_token_ratio(doc: TextDoc) -> float:
    """Unique word types / total word tokens."""
    if not doc.lower_words:
        return 0.0
    return len(set(doc.lower_words)) / doc.word_count


def hapax_legomena_rate(doc: TextDoc) -> float:
    """Words appearing exactly once / total word tokens."""
    if not doc.lower_words:
        return 0.0
    freq: Dict[str, int] = {}
    for w in doc.lower_words:
        freq[w] = freq.get(w, 0) + 1
    hapax = sum(1 for v in freq.values() if v == 1)
    return hapax / doc.word_count


def mean_sentence_length(doc: TextDoc) -> float:
    """Mean words per sentence."""
    if not doc.sentences:
        return 0.0
    lengths = [len(_tokenize(s)) for s in doc.sentences]
    return sum(lengths) / len(lengths)


def sentence_length_variance(doc: TextDoc) -> float:
    """Variance of per-sentence word counts."""
    if len(doc.sentences) < 2:
        return 0.0
    lengths = [float(len(_tokenize(s))) for s in doc.sentences]
    mean = sum(lengths) / len(lengths)
    return sum((l - mean) ** 2 for l in lengths) / len(lengths)


def function_word_ratio(doc: TextDoc) -> float:
    """Function words / total words."""
    if not doc.lower_words:
        return 0.0
    fn = sum(1 for w in doc.lower_words if w in FUNCTION_WORDS)
    return fn / doc.word_count


def passive_voice_ratio(doc: TextDoc) -> float:
    """Passive constructions / sentence count (approximated by regex)."""
    if not doc.sentence_count:
        return 0.0
    count = 0
    for pattern in PASSIVE_PATTERNS:
        count += len(re.findall(pattern, doc.clean, re.IGNORECASE))
    # Deduplicate crudely: cap at 1 per sentence
    return min(count, doc.sentence_count) / doc.sentence_count


def modal_verb_ratio(doc: TextDoc) -> float:
    """Modal verb tokens / total word tokens."""
    if not doc.word_count:
        return 0.0
    modals = sum(1 for w in doc.lower_words if w in MODAL_VERBS)
    return modals / doc.word_count


def stop_word_ratio(doc: TextDoc) -> float:
    """Stop words / total word tokens."""
    if not doc.lower_words:
        return 0.0
    stops = sum(1 for w in doc.lower_words if w in STOP_WORDS)
    return stops / doc.word_count


def avg_word_length(doc: TextDoc) -> float:
    """Mean character length of alphabetic word tokens."""
    if not doc.words:
        return 0.0
    return sum(len(w) for w in doc.words) / len(doc.words)


# ── Public extraction function ───────────────────────────────────────────────

def extract_tier1(doc: TextDoc) -> Dict[str, float]:
    return {
        "type_token_ratio":         type_token_ratio(doc),
        "hapax_legomena_rate":      hapax_legomena_rate(doc),
        "mean_sentence_length":     mean_sentence_length(doc),
        "sentence_length_variance": sentence_length_variance(doc),
        "function_word_ratio":      function_word_ratio(doc),
        "passive_voice_ratio":      passive_voice_ratio(doc),
        "modal_verb_ratio":         modal_verb_ratio(doc),
        "stop_word_ratio":          stop_word_ratio(doc),
        "avg_word_length":          avg_word_length(doc),
    }
