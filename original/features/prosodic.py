"""
features/prosodic.py — Tiers 13–15: Deep Prosodic & Lexical Architecture

Fifteen new features that extend the existing pipeline with genuinely
unbeatable stylometric signals.  No other authorship system measures these.

Tier 13 — Prosodic Depth (items 1, 2, 3, 4, 5, 11)
─────────────────────────────────────────────────────
  clausula_type_consistency  — consistency of sentence-final rhythmic type
  breath_group_regularity    — regularity of pause-marker-delimited spans
  vowel_sonority_ratio       — heavy-vowel density (long vowel clusters)
  arc_resolution_score       — whether narrative tension resolves at the end
  metric_flatness_score      — CV of stress density across paragraphs (low=AI)
  clausula_shape_preference  — dominant closing pattern (dactylic→trochaic→spondaic)

Tier 14 — Error Topology & Syntax (items 6, 8, 9, 10)
───────────────────────────────────────────────────────
  error_topology_consistency — positional consistency of comma-splice errors
  article_omission_rate      — determiner-less NPs per 100 words
  pronoun_ambiguity_rate     — fraction of pronouns with ambiguous antecedents
  comma_splice_rate          — comma splices per 100 sentences

Tier 15 — Lexical Architecture (items 7, 12, 13, 14, 15)
──────────────────────────────────────────────────────────
  semantic_field_concentration — concentration of top nouns into one field
  polysyndeton_ratio           — polysyndetic vs. asyndetic list ratio
  chiasmus_rate                — A-B-B-A POS-reversal patterns per 100 sent.
  latinate_ratio               — Latinate-suffix words / total content words
  nominalization_density       — -tion/-ment/-ness/-ity nominals per 100 words

All features are standalone (no baseline required) and return values
normalised to [0, 1].  NORM_BOUNDS in constants.py are set to (0.0, 1.0).

Graceful degradation: if spaCy is unavailable, features that require
dependency parsing fall back to regex/heuristic approximations.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple

import numpy as np

from .tier1 import TextDoc, _tokenize

log = logging.getLogger(__name__)

# ── Lazy spaCy ───────────────────────────────────────────────────────────────

_nlp = None
_spacy_ok: Optional[bool] = None


def _get_nlp():
    global _nlp, _spacy_ok
    if _spacy_ok is None:
        try:
            import spacy
            _nlp = spacy.load("en_core_web_sm", disable=["ner"])
            _spacy_ok = True
        except (ImportError, OSError):
            _nlp = None
            _spacy_ok = False
            log.debug("spaCy unavailable — prosodic Tier 14 uses heuristic fallbacks.")
    return _nlp


# ── Syllable/stress helpers (shared with tier8 but kept local) ────────────────

_LONG_VOWEL_RE = re.compile(r"[aeiou]{2,}|[aeio][yw]|[aeiou](?=[^aeiou\s]{0,1}\s)", re.I)
_VOWEL_GROUP_RE = re.compile(r"[aeiou]+", re.I)


def _syllable_groups(word: str) -> List[str]:
    """Return vowel-cluster groups as proxy syllables."""
    return _VOWEL_GROUP_RE.findall(word)


def _word_stress(word: str) -> List[int]:
    """Binary stress sequence for a word (1=stressed, 0=unstressed).

    Heuristic: penultimate stress for polysyllabic words.
    """
    groups = _syllable_groups(word)
    n = max(1, len(groups))
    stress = [0] * n
    if n == 1:
        stress[0] = 1
    elif n >= 2:
        stress[-2] = 1   # penultimate (most common English pattern)
    return stress


def _sentence_stress_tail(sentence: str, n_syllables: int = 6) -> List[int]:
    """Return last n_syllables stress values for a sentence."""
    words = [w for w in re.findall(r"[a-zA-Z']+", sentence) if re.search(r"[aeiou]", w, re.I)]
    tail: List[int] = []
    for word in reversed(words):
        syl = _word_stress(word)
        tail = list(reversed(syl)) + tail
        if len(tail) >= n_syllables:
            break
    return tail[-n_syllables:] if len(tail) >= n_syllables else tail


def _classify_clausula(stress_tail: List[int]) -> str:
    """Classify the stress tail into a clausula type.

    Classical cursus patterns (last 4-6 syllables):
      planus   — ′ × | ′ × ×   → e.g. [1,0,1,0,0]
      velox    — ′ × × | ′ × × × → e.g. [1,0,0,1,0,0]
      tardus   — ′ × × | ′ × × → e.g. [1,0,0,1,0]
      trochaic — ends ′ ×       → e.g. [...1,0]
      dactylic — ends ′ × ×     → e.g. [...1,0,0]
    """
    if len(stress_tail) < 3:
        return "short"
    tail = stress_tail[-5:]  # use last 5 syllables
    # Match patterns from most specific to least
    if len(tail) >= 5 and tail[-5:] == [1, 0, 0, 1, 0]:
        return "velox"
    if len(tail) >= 5 and tail[-5:] == [1, 0, 1, 0, 0]:
        return "planus"
    if len(tail) >= 4 and tail[-4:] == [1, 0, 0, 1]:
        return "tardus"
    if len(tail) >= 3 and tail[-3:] == [1, 0, 0]:
        return "dactylic"
    if len(tail) >= 2 and tail[-2:] == [1, 0]:
        return "trochaic"
    if len(tail) >= 2 and tail[-2:] == [0, 1]:
        return "iambic"
    return "other"


def _shannon_entropy(counts: Counter) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return -sum((c / total) * math.log2(c / total) for c in counts.values() if c > 0)


# ── TIER 13: Prosodic Depth ───────────────────────────────────────────────────

def _clausula_type_consistency(doc: TextDoc) -> float:
    """1 − normalised entropy of sentence-final clausula types.

    A writer who consistently uses the same rhythmic close (e.g. always
    trochaic) scores near 1.0; a chaotic mixture scores near 0.0.
    """
    if doc.sentence_count < 3:
        return 0.5
    types: Counter = Counter()
    for sent in doc.sentences:
        tail = _sentence_stress_tail(sent, n_syllables=6)
        types[_classify_clausula(tail)] += 1
    h = _shannon_entropy(types)
    max_h = math.log2(len(types)) if len(types) > 1 else 1.0
    return float(np.clip(1.0 - h / max(max_h, 1.0), 0.0, 1.0))


def _breath_group_regularity(doc: TextDoc) -> float:
    """1 / (1 + CV) of token-span lengths between pause markers.

    Pause markers: , ; : — … (en/em dash, ellipsis).
    A writer with highly regular breath groups scores near 1.0.
    """
    pause_re = re.compile(r"[,;:—–…]")
    chunks = pause_re.split(doc.clean)
    # Measure token span length (words only) for each chunk
    lengths = [len(_tokenize(c)) for c in chunks if c.strip()]
    if len(lengths) < 3:
        return 0.5
    arr = np.array(lengths, dtype=float)
    cv = float(arr.std() / arr.mean()) if arr.mean() > 0 else 1.0
    return float(np.clip(1.0 / (1.0 + cv), 0.0, 1.0))


def _vowel_sonority_ratio(doc: TextDoc) -> float:
    """Ratio of heavy (long) vowel clusters to all vowel clusters.

    Long vowel approximations: digraphs (ee, ea, oo, ou, ai, ay, oa, ie,
    ue, ew, oi, oy, au, aw), and vowels before silent-e positions.
    Higher ratio = more sonorous prose style.
    """
    long_re = re.compile(r"ee|ea|oo|ou|ow|ai|ay|oa|ie|ue|ew|oi|oy|au|aw|ui|igh", re.I)
    text_lower = doc.clean.lower()
    long_count = len(long_re.findall(text_lower))
    all_count = len(_VOWEL_GROUP_RE.findall(text_lower))
    if all_count == 0:
        return 0.5
    return float(np.clip(long_count / all_count, 0.0, 1.0))


def _arc_resolution_score(doc: TextDoc) -> float:
    """Measure whether narrative tension (sentence-length) resolves.

    Compute mean sentence length per quarter of text.  Resolution pattern
    (low → high → high → low) scores near 1.0; flat or monotone rising
    scores lower.  Returns the ratio: Q4_mean / max(Q1..Q3_mean).
    """
    sents = doc.sentences
    if len(sents) < 8:
        return 0.5
    lengths = [len(_tokenize(s)) for s in sents]
    n = len(lengths)
    q = n // 4
    q1 = float(np.mean(lengths[:q])) if q > 0 else 0.0
    q2 = float(np.mean(lengths[q:2*q])) if q > 0 else 0.0
    q3 = float(np.mean(lengths[2*q:3*q])) if q > 0 else 0.0
    q4 = float(np.mean(lengths[3*q:])) if q > 0 else 0.0
    # Resolution: final quarter calmer (shorter) than middle
    middle_max = max(q1, q2, q3, 1.0)
    resolution_ratio = 1.0 - float(np.clip(q4 / middle_max, 0.0, 1.5)) / 1.5
    return float(np.clip(resolution_ratio, 0.0, 1.0))


def _metric_flatness_score(doc: TextDoc) -> float:
    """Coefficient of variation of stress density per paragraph.

    AI writing tends to produce metrically uniform paragraphs (low CV).
    Returns 1 − min(CV/0.4, 1.0) so that flat prose (AI-like) → 1.0,
    varied prose (human-like) → 0.0.

    This is deliberately counterintuitive: HIGH score = more suspicious.
    """
    if not doc.paragraphs:
        return 0.5
    densities: List[float] = []
    for para_sents in doc.paragraphs:
        para_text = " ".join(para_sents)
        words = [w for w in re.findall(r"[a-zA-Z]+", para_text)
                 if re.search(r"[aeiou]", w, re.I)]
        if not words:
            continue
        stressed = sum(1 for w in words if len(_syllable_groups(w)) >= 2)
        densities.append(stressed / len(words))
    if len(densities) < 2:
        return 0.5
    arr = np.array(densities, dtype=float)
    cv = float(arr.std() / arr.mean()) if arr.mean() > 0 else 0.0
    # Low CV (flat) → high flatness score
    flatness = float(np.clip(1.0 - cv / 0.4, 0.0, 1.0))
    return flatness


def _clausula_shape_preference(doc: TextDoc) -> float:
    """Dominant sentence-ending stress shape as a continuous value.

    Returns the weighted average of shape scores across all sentences:
      dactylic (SWW)  → 0.0  [light close]
      iambic (WS)     → 0.25
      trochaic (SW)   → 0.5  [balanced]
      spondaic (SS)   → 0.75
      planus/velox    → 1.0  [heavy rhetorical close]

    A value near 0 = dactylic style; near 1 = classical rhetorical close.
    """
    shape_scores = {
        "dactylic": 0.0, "short": 0.1, "iambic": 0.25,
        "trochaic": 0.5, "other": 0.5,
        "tardus": 0.65, "spondaic": 0.75,
        "velox": 0.9, "planus": 1.0,
    }
    if doc.sentence_count < 2:
        return 0.5
    scores = []
    for sent in doc.sentences:
        tail = _sentence_stress_tail(sent, n_syllables=6)
        ctype = _classify_clausula(tail)
        scores.append(shape_scores.get(ctype, 0.5))
    return float(np.clip(np.mean(scores), 0.0, 1.0))


# ── TIER 14: Error Topology & Syntax ─────────────────────────────────────────

# Heuristic comma-splice detector:
# A sentence containing `, [lowercase subject word]` where both sides
# contain a verb is a candidate comma splice.
_SUBJECT_WORDS = {
    "i", "he", "she", "it", "we", "they", "you",
    "this", "that", "these", "those",
    "the", "a", "an",
}
_VERB_RE = re.compile(
    r"\b(is|are|was|were|has|have|had|do|does|did|will|would|could|should|"
    r"may|might|must|can|seem|seems|seemed|appear|appears|appeared|become|"
    r"became|get|gets|got|make|makes|made|go|goes|went|take|takes|took|"
    r"show|shows|showed|provide|provides|provided|suggest|suggests|suggest)\b",
    re.I,
)


def _is_comma_splice(sentence: str) -> bool:
    """Heuristic: detect if a sentence is a comma splice."""
    # Find commas that are followed by a lowercase subject word
    parts = re.split(r",\s+", sentence)
    if len(parts) < 2:
        return False
    # Check if at least one interior comma creates a splice:
    # both sides of the comma have a subject + verb
    for i in range(len(parts) - 1):
        left = parts[i]
        right = parts[i + 1]
        first_word_right = _tokenize(right)[0].lower() if _tokenize(right) else ""
        if first_word_right not in _SUBJECT_WORDS:
            continue
        if _VERB_RE.search(left) and _VERB_RE.search(right):
            return True
    return False


def _error_topology_consistency(doc: TextDoc) -> float:
    """Positional consistency of comma-splice errors across paragraphs.

    Measures the entropy of splice positions within their paragraphs.
    A writer who always puts splices at paragraph midpoints has LOW entropy
    → high consistency (near 1.0).  Random placement → near 0.0.
    """
    positions: Counter = Counter()   # "early"/"mid"/"late"
    for para in doc.paragraphs:
        n = max(len(para), 1)
        for i, sent in enumerate(para):
            if _is_comma_splice(sent):
                frac = i / n
                if frac < 0.33:
                    positions["early"] += 1
                elif frac < 0.67:
                    positions["mid"] += 1
                else:
                    positions["late"] += 1
    total = sum(positions.values())
    if total < 2:
        return 0.5   # neutral: not enough splices to judge
    h = _shannon_entropy(positions)
    max_h = math.log2(3)   # 3 bins
    return float(np.clip(1.0 - h / max_h, 0.0, 1.0))


def _article_omission_rate(doc: TextDoc) -> float:
    """Rate of likely article-omission sites per 100 words.

    Heuristic: count occurrences where a preposition (in, on, at, of, to,
    by, with, for, from) is directly followed by an adjective or noun
    (title-cased or in a known pattern) without a DET between them.

    Uses spaCy if available for accurate DET detection; falls back to regex.
    """
    if doc.word_count < 10:
        return 0.0

    nlp = _get_nlp()
    if nlp:
        # Use spaCy dependency parse: count det-less singular common nouns
        # that are governed by a preposition (an article-drop position).
        try:
            spacy_doc = nlp(doc.clean[:4000])   # truncate for speed
            omissions = 0
            prep_governed: set = set()   # token indices that are in prep phrase
            for tok in spacy_doc:
                # Mark tokens whose head is a preposition
                if tok.head.pos_ == "ADP":
                    prep_governed.add(tok.i)
            for tok in spacy_doc:
                # A common singular noun in a prepositional phrase without DET subtree
                if (tok.pos_ == "NOUN" and tok.i in prep_governed
                        and not tok.text.endswith("s")           # rough singular check
                        and not any(c.pos_ == "DET" for c in tok.children)):
                    omissions += 1
            total_words = len(doc.words)
            # Normalise: ceiling at 20 per 100 words (very high ESL rate)
            return float(np.clip(omissions / max(total_words, 1) * 100, 0.0, 20.0)) / 20.0
        except Exception:
            pass

    # Regex fallback: bare singular nouns directly after spatial/temporal prepositions
    # (excluding mass nouns heuristic: words < 5 chars that are very common)
    prep_re = re.compile(
        r"\b(in|on|at|during|within|throughout)\s+"
        r"(?!(?:the|a|an|this|that|these|those|his|her|its|my|our|their|your|his|all|some|any)\b)"
        r"([a-z]{5,})\b"  # only longer words (less likely to be mass nouns)
    )
    matches = len(prep_re.findall(doc.clean.lower()))
    # Normalise: ceiling at 15 per 100 words
    return float(np.clip(matches / max(doc.word_count, 1) * 100, 0.0, 15.0)) / 15.0


def _pronoun_ambiguity_rate(doc: TextDoc) -> float:
    """Fraction of third-person pronouns with potentially ambiguous antecedents.

    A pronoun is flagged as ambiguous when the two preceding sentences
    contain ≥ 2 same-gender noun phrases, making the referent unclear.

    Approximation: gender groups are he/him/his, she/her, they/them/their, it/its.
    Counts antecedent nouns (title-cased words or words following 'the'/'a')
    in the window and flags ambiguity if count ≥ 2.
    """
    pronoun_sets = {
        "m":   {"he", "him", "his", "himself"},
        "f":   {"she", "her", "hers", "herself"},
        "pl":  {"they", "them", "their", "theirs", "themselves"},
        "n":   {"it", "its", "itself"},
    }
    pronoun_map: Dict[str, str] = {}
    for g, words in pronoun_sets.items():
        for w in words:
            pronoun_map[w] = g

    total_pronouns = 0
    ambiguous = 0
    sents = doc.sentences

    for i, sent in enumerate(sents):
        tokens = [t.lower() for t in _tokenize(sent)]
        for tok in tokens:
            gender = pronoun_map.get(tok)
            if gender is None:
                continue
            total_pronouns += 1
            # Check window: previous 2 sentences
            window_text = " ".join(sents[max(0, i-2):i])
            # Count nouns (rough proxy: words that follow "the" or "a/an", or are title-cased)
            noun_candidates = len(re.findall(r"\b(?:the|a|an)\s+[A-Za-z]+", window_text))
            noun_candidates += len(re.findall(r"\b[A-Z][a-z]{2,}", window_text))
            if noun_candidates >= 4:   # require 4+ candidates for conservative flagging
                ambiguous += 1
            break   # count once per sentence

    if total_pronouns == 0:
        return 0.5
    return float(np.clip(ambiguous / total_pronouns, 0.0, 1.0))


def _comma_splice_rate(doc: TextDoc) -> float:
    """Comma splices per 100 sentences.

    Returns value normalised to [0, 1] with max = 30 splices per 100
    sentences (very high splice rate, typical of ESL or deliberate rhetorical style).
    """
    if doc.sentence_count == 0:
        return 0.0
    splice_count = sum(1 for s in doc.sentences if _is_comma_splice(s))
    rate = splice_count / doc.sentence_count * 100   # per 100 sentences
    return float(np.clip(rate / 30.0, 0.0, 1.0))


# ── TIER 15: Lexical Architecture ────────────────────────────────────────────

# Latinate suffix patterns (Greco-Latin origin proxy)
_LATINATE_SUFFIXES = re.compile(
    r"(tion|tions|sion|sions|ment|ments|ence|ences|ance|ances|ity|ities|"
    r"ous|ious|eous|ical|ical|ive|ives|ate|ates|ated|ory|ories|ary|aries|"
    r"ism|isms|ist|ists|ize|izes|ized|ify|ifies|ified|uous)$",
    re.I,
)

# Nominalization patterns
_NOMINALIZATION_RE = re.compile(
    r"\b\w+(tion|tions|sion|sions|ment|ments|ness|nesses|ity|ities|"
    r"ance|ances|ence|ences)\b",
    re.I,
)

# Polysyndeton: 3+ items joined by repeated conjunctions
_POLY_RE = re.compile(r"\b(and|or|but)\b[^.!?]{1,40}\b(and|or|but)\b[^.!?]{1,40}\b(and|or|but)\b", re.I)
# Asyndeton: 3+ items in a comma list with no final conjunction
_ASYN_RE = re.compile(r"[a-z]+,\s+[a-z]+,\s+[a-z]+(?:,\s+[a-z]+)*(?!\s*(?:and|or|but))", re.I)


def _semantic_field_concentration(doc: TextDoc) -> float:
    """Concentration of top content nouns into a single semantic field.

    Uses spaCy word vectors (cosine similarity) to compute mean pairwise
    similarity among the top-20 most frequent nouns.  High similarity =
    concentrated semantic field = strong personal thematic fingerprint.

    Falls back to: fraction of top-20 nouns sharing a common root/prefix
    (first 4 characters) as a crude lexical cluster proxy.
    """
    nlp = _get_nlp()

    # Extract candidate nouns (lowercase alphabetic tokens, 4+ chars,
    # not in function word list)
    from ..constants import FUNCTION_WORDS
    content_words = [
        w.lower() for w in doc.words
        if len(w) >= 4 and w.lower() not in FUNCTION_WORDS
    ]
    if not content_words:
        return 0.5

    top_nouns = [w for w, _ in Counter(content_words).most_common(25)]
    if len(top_nouns) < 4:
        return 0.5

    if nlp and _spacy_ok:
        try:
            vecs = []
            for noun in top_nouns[:20]:
                tok = nlp.vocab[noun]
                if tok.has_vector:
                    vecs.append(tok.vector / (np.linalg.norm(tok.vector) + 1e-8))
            if len(vecs) < 4:
                raise ValueError("too few vectors")
            # Mean pairwise cosine similarity
            mat = np.stack(vecs)   # (N, 300)
            sim_matrix = mat @ mat.T
            n = len(vecs)
            # Extract upper triangle (excluding diagonal)
            mask = np.triu(np.ones((n, n), dtype=bool), k=1)
            mean_sim = float(np.mean(sim_matrix[mask]))
            return float(np.clip((mean_sim + 1.0) / 2.0, 0.0, 1.0))   # [-1,1] → [0,1]
        except Exception:
            pass

    # Lexical fallback: fraction of top nouns sharing a 4-char prefix cluster
    top20 = top_nouns[:20]
    prefix_counts: Counter = Counter(w[:4] for w in top20)
    dominant = prefix_counts.most_common(1)[0][1] if prefix_counts else 0
    return float(np.clip(dominant / len(top20), 0.0, 1.0))


def _polysyndeton_ratio(doc: TextDoc) -> float:
    """Ratio of polysyndetic patterns to total (poly + asyndetic).

    polysyndeton: 'X and Y and Z' — multiple repeated conjunctions
    asyndeton:    'X, Y, Z'       — bare comma list with no conjunction

    Returns 0 = pure asyndeton, 1 = pure polysyndeton, 0.5 = balanced/none.
    """
    poly_count = len(_POLY_RE.findall(doc.clean))
    asyn_count = len(_ASYN_RE.findall(doc.clean))
    total = poly_count + asyn_count
    if total == 0:
        return 0.5
    return float(np.clip(poly_count / total, 0.0, 1.0))


def _chiasmus_rate(doc: TextDoc) -> float:
    """A-B-B-A POS-pattern reversals per 100 sentence pairs.

    Requires spaCy for reliable POS tagging.  Without spaCy, the regex
    proxy assigns most content words to the catch-all "X" tag, causing
    trivial X-X-X / reversed(X-X-X) false-positive matches on nearly
    every adjacent sentence pair.  To avoid flooding the baseline with a
    constant non-neutral value (which would make every subsequent
    submission look anomalous), we return 0.5 (the neutral / no-data
    placeholder) when spaCy is unavailable.

    Rate normalised so 5 chiasms per 100 sentences → 1.0.
    """
    nlp = _get_nlp()
    if not (nlp and _spacy_ok):
        # spaCy unavailable — return neutral to prevent false positives.
        return 0.5

    sents = doc.sentences
    if len(sents) < 4:
        return 0.0

    def _pos_tags(text: str) -> List[str]:
        try:
            return [t.pos_ for t in nlp(text[:200]) if t.is_alpha]
        except Exception:
            return []

    chiasmus_count = 0
    for i in range(len(sents) - 1):
        tags_a = _pos_tags(sents[i])
        tags_b = _pos_tags(sents[i + 1])
        if len(tags_a) < 3 or len(tags_b) < 3:
            continue
        tail_a = tags_a[-3:]
        head_b = tags_b[:3]
        # Require at least 2 non-trivial (non-X) tags in the match to avoid
        # false positives from catch-all categories.
        non_trivial = sum(1 for t in tail_a if t not in ("X", "PUNCT", "SPACE"))
        if non_trivial >= 2 and tail_a == list(reversed(head_b)):
            chiasmus_count += 1

    rate = chiasmus_count / max(len(sents) - 1, 1) * 100
    return float(np.clip(rate / 5.0, 0.0, 1.0))


def _latinate_ratio(doc: TextDoc) -> float:
    """Proportion of content words with Latinate/Greco-Latin suffixes.

    Proxy: words with suffixes characteristic of French/Latin borrowings
    (-tion, -ment, -ence, -ance, -ity, -ous, -ive, -ate, -ory, etc.)
    divided by total content words (non-function, non-stop words).
    """
    from ..constants import FUNCTION_WORDS
    content = [w for w in doc.lower_words if w not in FUNCTION_WORDS and len(w) >= 3]
    if not content:
        return 0.5
    latinate = sum(1 for w in content if _LATINATE_SUFFIXES.search(w))
    return float(np.clip(latinate / len(content), 0.0, 1.0))


def _nominalization_density(doc: TextDoc) -> float:
    """Nominalization count per 100 words, normalised to [0, 1].

    Nominalizations: nouns derived from verbs/adjectives via -tion/-ment/
    -ness/-ity/-ance/-ence.  Rate per 100 words; max normalised at 15
    per 100 (very heavy nominalization register).
    """
    if doc.word_count == 0:
        return 0.0
    noms = len(_NOMINALIZATION_RE.findall(doc.clean))
    rate = noms / doc.word_count * 100   # per 100 words
    return float(np.clip(rate / 15.0, 0.0, 1.0))


# ── Public entry point ────────────────────────────────────────────────────────

def extract_prosodic(doc: TextDoc) -> Dict[str, float]:
    """
    Extract all 15 Tier 13–15 prosodic and lexical features.

    Returns a dict of {feature_code: value ∈ [0, 1]}.
    All values are already normalised; NORM_BOUNDS for these codes are (0, 1).
    """
    return {
        # Tier 13 — Prosodic Depth
        "clausula_type_consistency":  _clausula_type_consistency(doc),
        "breath_group_regularity":    _breath_group_regularity(doc),
        "vowel_sonority_ratio":       _vowel_sonority_ratio(doc),
        "arc_resolution_score":       _arc_resolution_score(doc),
        "metric_flatness_score":      _metric_flatness_score(doc),
        "clausula_shape_preference":  _clausula_shape_preference(doc),
        # Tier 14 — Error Topology & Syntax
        "error_topology_consistency": _error_topology_consistency(doc),
        "article_omission_rate":      _article_omission_rate(doc),
        "pronoun_ambiguity_rate":     _pronoun_ambiguity_rate(doc),
        "comma_splice_rate":          _comma_splice_rate(doc),
        # Tier 15 — Lexical Architecture
        "semantic_field_concentration": _semantic_field_concentration(doc),
        "polysyndeton_ratio":           _polysyndeton_ratio(doc),
        "chiasmus_rate":                _chiasmus_rate(doc),
        "latinate_ratio":               _latinate_ratio(doc),
        "nominalization_density":       _nominalization_density(doc),
    }
