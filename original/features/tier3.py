"""
features/tier3.py — Tier 3: Rhetorical Fingerprint + Theological Register

Twelve features capturing the deepest layer of writing identity:
epistemic stance, source integration style, argumentation posture,
and SBTS-specific theological register.
"""

import re
import math
from collections import Counter
from typing import List, Dict, Set

from .tier1 import TextDoc, _tokenize
from ..constants import (
    HEDGE_WORDS, ASSERTION_WORDS, CLAIM_MARKERS, AUTHORITY_MARKERS,
    FUNCTION_WORDS, STOP_WORDS, FIRST_PERSON, PERSONAL_PRONOUNS,
    THEOLOGICAL_TERMS, SCRIPTURE_PATTERNS, CONFESSIONAL_MARKERS,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _per_100(count: float, word_count: int) -> float:
    if not word_count:
        return 0.0
    return count / word_count * 100


def _count_phrases(text: str, phrases: Set[str]) -> int:
    """Count occurrences of a set of phrases/words in lower-cased text."""
    lower = text.lower()
    count = 0
    for phrase in phrases:
        if " " in phrase:
            count += lower.count(phrase)
        else:
            count += len(re.findall(r'\b' + re.escape(phrase) + r'\b', lower))
    return count


# ── Tier 3 extractors ────────────────────────────────────────────────────────

def epistemic_certainty_ratio(doc: TextDoc) -> float:
    """
    Assert markers / (assert + hedge markers).
    Near 1.0 = highly assertive; near 0.0 = heavily hedged.
    """
    hedges = _count_phrases(doc.clean, HEDGE_WORDS)
    asserts = _count_phrases(doc.clean, ASSERTION_WORDS)
    total = hedges + asserts
    if total == 0:
        return 0.5  # neutral baseline
    return asserts / total


def hedging_density(doc: TextDoc) -> float:
    """Hedge markers per 100 words."""
    return _per_100(_count_phrases(doc.clean, HEDGE_WORDS), doc.word_count)


def assertion_density(doc: TextDoc) -> float:
    """Strong assertion markers per 100 words."""
    return _per_100(_count_phrases(doc.clean, ASSERTION_WORDS), doc.word_count)


def source_integration_style(doc: TextDoc) -> float:
    """
    Scale 0 → 1 from cite-and-move (0) to full synthesis (1).

    Heuristic:
    - Detect citation sentences (contain a reference pattern or authority marker)
    - For each citation sentence, check if the NEXT sentence provides
      commentary (≥5 content words, no citation, starts with an evaluative word)
    - cite_with_comment / max(1, citation_count) → normalized
    """
    lower = doc.clean.lower()
    sents = doc.sentences

    # Detect citation sentences
    citation_indices = set()
    for i, sent in enumerate(sents):
        has_ref = any(re.search(p, sent) for p in SCRIPTURE_PATTERNS)
        has_auth = _count_phrases(sent, set(AUTHORITY_MARKERS)) > 0
        if has_ref or has_auth:
            citation_indices.add(i)

    if not citation_indices:
        # No citations detected — check if synthesis language present
        synth_markers = {
            "in other words", "this means", "what paul means",
            "the significance", "this implies", "therefore",
        }
        synth_count = _count_phrases(lower, synth_markers)
        return min(synth_count / max(1, len(sents)) * 3, 1.0)

    comment_count = 0
    for idx in citation_indices:
        if idx + 1 < len(sents):
            next_sent = sents[idx + 1]
            # Commentary: no citation, has evaluative/analytical words
            if (idx + 1) not in citation_indices:
                cw = [w for w in _tokenize(next_sent)
                      if w.lower() not in STOP_WORDS and len(w) > 3]
                if len(cw) >= 4:
                    comment_count += 1

    return comment_count / len(citation_indices)


def counter_argument_ratio(doc: TextDoc) -> float:
    """
    Adversative / concessive sentences / total sentences.
    Signals that the writer acknowledges and addresses objections.
    """
    adversative_openers = {
        "however", "nevertheless", "nonetheless", "yet", "but",
        "although", "even though", "while", "despite", "granted",
        "admittedly", "it might be objected", "one might argue",
        "some would argue", "critics contend", "it could be said",
        "one could argue",
    }
    if not doc.sentence_count:
        return 0.0
    count = 0
    for sent in doc.sentences:
        first_words = " ".join(_tokenize(sent)[:6]).lower()
        # Use word-boundary regex to avoid false positives from substring matches
        # (e.g. "but" inside "about"). Check only the first ~6 tokens.
        if any(re.search(r'\b' + re.escape(op) + r'\b', first_words)
               for op in adversative_openers):
            count += 1
    return count / doc.sentence_count


def claim_density(doc: TextDoc) -> float:
    """Toulmin claim/conclusion markers per 100 words."""
    return _per_100(_count_phrases(doc.clean, CLAIM_MARKERS), doc.word_count)


def question_ratio(doc: TextDoc) -> float:
    """Interrogative sentences / total sentences."""
    if not doc.sentence_count:
        return 0.0
    questions = sum(1 for s in doc.sentences if s.strip().endswith("?"))
    return questions / doc.sentence_count


def imperative_density(doc: TextDoc) -> float:
    """
    Imperative constructions per 100 words.
    Heuristic: sentence starts with a base-form verb (not a pronoun/article).

    Covers both academic imperatives (consider, examine, note) and the
    pastoral/homiletical register common in theological writing (pray, receive,
    confess, serve, give, seek, trust, follow, read, come, go, be).
    """
    if not doc.word_count:
        return 0.0

    # Academic-prose imperatives
    academic_imperatives = {
        "consider", "note", "observe", "recall", "recognize", "acknowledge",
        "see", "compare", "contrast", "examine", "notice", "imagine",
        "suppose", "assume", "grant", "reflect", "think", "understand",
        "distinguish", "recall", "apply", "evaluate", "assess",
    }
    # Pastoral / homiletical imperatives common in theological writing
    pastoral_imperatives = {
        "receive", "pray", "confess", "serve", "give", "seek", "trust",
        "follow", "remember", "read", "listen", "come", "go", "be",
        "love", "forgive", "worship", "ask", "rest", "rejoice",
        "repent", "believe", "obey", "know", "take", "keep", "let",
    }
    imperative_verbs = academic_imperatives | pastoral_imperatives

    count = 0
    for sent in doc.sentences:
        first = re.match(r'(\w+)', sent.lstrip())
        if first and first.group(1).lower() in imperative_verbs:
            count += 1
    return _per_100(count, doc.word_count)


def first_person_ratio(doc: TextDoc) -> float:
    """First-person pronouns / all personal pronouns."""
    all_pron = sum(1 for w in doc.lower_words if w in PERSONAL_PRONOUNS)
    if not all_pron:
        return 0.0
    first = sum(1 for w in doc.lower_words if w in FIRST_PERSON)
    return first / all_pron


def appeal_to_authority_density(doc: TextDoc) -> float:
    """Citation and authority-appeal language per 100 words."""
    return _per_100(_count_phrases(doc.clean, set(AUTHORITY_MARKERS)), doc.word_count)


def conclusion_strategy_score(doc: TextDoc) -> float:
    """
    Scale 0→1: 0 = bare summary, 1 = summary + implication + open question.

    Detects the presence of:
    - Summary markers ("in summary", "in conclusion", "to conclude", "thus", "therefore")
    - Implication markers ("this means", "therefore", "consequently", "implications")
    - Open-ended markers ("further research", "future work", "remains to be seen",
                          "question for", "invites further")
    """
    lower = doc.clean.lower()
    # Only look in the last 20% of text
    cutoff = max(0, int(len(lower) * 0.8))
    conclusion_text = lower[cutoff:]

    summary_markers = {
        "in summary", "in conclusion", "to conclude", "to summarize",
        "thus", "therefore", "in sum", "in short", "briefly",
    }
    implication_markers = {
        "this means", "this implies", "this suggests", "the implication",
        "what this means", "consequently", "it follows", "the significance",
        "for the church", "for theology", "for ministry",
    }
    open_markers = {
        "further research", "future work", "remains to be seen",
        "question for further", "deserves further", "invites further",
        "more work is needed", "not yet resolved", "an open question",
    }

    has_summary = _count_phrases(conclusion_text, summary_markers) > 0
    has_implication = _count_phrases(conclusion_text, implication_markers) > 0
    has_open = _count_phrases(conclusion_text, open_markers) > 0

    return (int(has_summary) + int(has_implication) + int(has_open)) / 3.0


def theological_register_score(doc: TextDoc) -> float:
    """
    Density of SBTS theological vocabulary (domain-specific).
    Normalized by total word count so longer essays don't score artificially higher.
    """
    if not doc.word_count:
        return 0.0
    hits = sum(1 for w in doc.lower_words if w in THEOLOGICAL_TERMS)
    # Also check for multi-word theological phrases (conservative count: each phrase = 1 hit)
    lower = doc.clean.lower()
    for marker in CONFESSIONAL_MARKERS:
        if marker in lower:
            hits += 1

    # Normalize: typical theological essay has ~3-8% theological terms
    # Cap at 0.15 raw rate → maps to 1.0
    raw_rate = hits / doc.word_count
    return min(raw_rate / 0.15, 1.0)


# ── Public extraction function ───────────────────────────────────────────────

def extract_tier3(doc: TextDoc) -> Dict[str, float]:
    return {
        "epistemic_certainty_ratio":  epistemic_certainty_ratio(doc),
        "hedging_density":            hedging_density(doc),
        "assertion_density":          assertion_density(doc),
        "source_integration_style":   source_integration_style(doc),
        "counter_argument_ratio":     counter_argument_ratio(doc),
        "claim_density":              claim_density(doc),
        "question_ratio":             question_ratio(doc),
        "imperative_density":         imperative_density(doc),
        "first_person_ratio":         first_person_ratio(doc),
        "appeal_to_authority_density":appeal_to_authority_density(doc),
        "conclusion_strategy_score":  conclusion_strategy_score(doc),
        "theological_register_score": theological_register_score(doc),
    }
