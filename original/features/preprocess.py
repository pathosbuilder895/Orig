"""
features/preprocess.py — Text preprocessing for stylometric feature extraction.

Performs two tasks before TextDoc is constructed:

1.  **Back-matter stripping** — removes bibliography, references, appendices,
    and endnote sections that contain non-authorial prose (citation lists,
    raw data, tables).  Leaving these in corrupts sentence-length, noun-verb
    ratio, punctuation rates, and type-token ratio.

2.  **In-body citation cleaning** — strips parenthetical citation markers and
    footnote-reference superscripts from prose sentences so surface features
    are not contaminated.  Signal phrases ("As Calvin argues, ...") are KEPT
    because they ARE the student's word choice and contribute to Tier 16.
    Block quotes (>40 words of direct quoted text) are also stripped because
    they are another author's prose, not the student's.

3.  **Citation data extraction** — before stripping, collects structured data
    about how the student uses citations.  This data is consumed by
    ``extract_tier16()`` in tier16.py to build the citation fingerprint.

Returns
-------
prose : str
    Clean body text for all tier 1–15 feature extractors.
citation_data : CitationData
    Structured citation usage data for Tier 16.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ══════════════════════════════════════════════════════════════════════════════
# Back-matter section headings
# ══════════════════════════════════════════════════════════════════════════════

# Regex matches a line that IS ONLY a back-matter heading (case-insensitive).
# Everything from this line to EOF is stripped.
_BACKMATTER_HEADING = re.compile(
    r"^(?:"
    r"bibliography"
    r"|references?"
    r"|works?\s+cited"
    r"|works?\s+referenced"
    r"|selected\s+bibliography"
    r"|annotated\s+bibliography"
    r"|appendix\s*[a-z0-9]*"
    r"|appendices"
    r"|(?:end)?notes?"
    r"|sources?\s+consulted"
    r"|further\s+reading"
    r")\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _strip_backmatter(text: str) -> str:
    """Remove bibliography, references, appendix, and notes sections."""
    m = _BACKMATTER_HEADING.search(text)
    if m:
        text = text[: m.start()].rstrip()
    return text


# ══════════════════════════════════════════════════════════════════════════════
# In-body citation patterns
# ══════════════════════════════════════════════════════════════════════════════

# Parenthetical author-year citations: (Smith, 2020) / (Smith & Jones, 2020, p. 45)
_PAREN_CITATION = re.compile(
    r"\("
    r"(?:[A-ZÁÉÍÓÚ][a-záéíóú\-]{1,25}"
    r"(?:\s+(?:and|&|et\s+al\.?)\s+[A-ZÁÉÍÓÚ][a-záéíóú\-]{1,25})*"
    r",?\s+)"
    r"\d{4}"
    r"(?:,\s*pp?\.\s*\d+(?:[–\-]\d+)?)?"
    r"\)",
    re.UNICODE,
)

# SBL / Turabian inline short-title footnote marker: superscript integers
# attached to end of word/punctuation.
_FOOTNOTE_SUPERSCRIPT = re.compile(
    r"(?<=[a-zA-Z.,;:!?\"\u2019\u201d])\^?\d{1,3}(?=[\s,.]|$)",
    re.MULTILINE,
)

# Scripture references used as inline citations: (Gen 1:1; John 3:16)
_SCRIPTURE_PAREN = re.compile(
    r"\((?:[1-3]\s*)?[A-Z][a-z]+\.?\s+\d+(?::\d+)?(?:[–\-]\d+)?(?:;\s*(?:[1-3]\s*)?[A-Z][a-z]+\.?\s+\d+(?::\d+)?)*\)",
)

# Block quotes: 40+ words in "…" or indented 4 spaces / tab
# Block-quote detector: match "..." spans of 200+ characters (\u224840+ words).
# Uses [^"] to avoid nested quantifiers and catastrophic backtracking on texts
# that have an unmatched opening quote (common in 18th-century prose that uses
# "\u2026" for emphasis rather than block quotation).
_DOUBLE_QUOTE_BLOCK = re.compile(
    r'"[^"]{200,}"',
    re.DOTALL,
)
_INDENT_BLOCK = re.compile(
    r"(?m)^(?:    |\t).+(?:\n(?:    |\t).+)*",
)

# Ibid. / op. cit. / loc. cit.
_IBID_RE = re.compile(r"\bibid(?:\.|,)?\b|\bop\.\s*cit\.\b|\bloc\.\s*cit\.\b", re.IGNORECASE)


# ══════════════════════════════════════════════════════════════════════════════
# Signal verb taxonomy
# ══════════════════════════════════════════════════════════════════════════════

# Maps each signal verb (lowercase) to its assertiveness score [0, 1].
# 0 = maximally hedging/neutral ("hints", "seems")
# 1 = maximally assertive/demonstrative ("proves", "demonstrates")
SIGNAL_VERB_ASSERTIVENESS: Dict[str, float] = {
    # Assertive (0.8 – 1.0)
    "proves":        1.0,
    "demonstrates":  0.95,
    "establishes":   0.90,
    "confirms":      0.88,
    "shows":         0.85,
    "reveals":       0.82,
    "makes clear":   0.80,
    # Moderate (0.5 – 0.79)
    "argues":        0.75,
    "contends":      0.72,
    "maintains":     0.70,
    "insists":       0.68,
    "asserts":       0.65,
    "claims":        0.62,
    "states":        0.60,
    "explains":      0.58,
    "concludes":     0.55,
    "emphasizes":    0.55,
    "emphasises":    0.55,
    "highlights":    0.52,
    "observes":      0.50,
    # Hedging / neutral (0.0 – 0.49)
    "notes":         0.45,
    "writes":        0.45,
    "remarks":       0.42,
    "comments":      0.40,
    "mentions":      0.35,
    "points out":    0.35,
    "acknowledges":  0.30,
    "admits":        0.28,
    "suggests":      0.25,
    "implies":       0.20,
    "hints":         0.10,
    "seems to":      0.08,
}

# Regex to capture "Author <verb>" signal phrases (the verb comes after the name).
# We capture just the verb part.
_SIGNAL_PHRASE_RE = re.compile(
    r"\b[A-Z][a-zé\-]+\s+(?:and\s+[A-Z][a-zé\-]+\s+)?"
    r"("
    + "|".join(re.escape(v) for v in sorted(SIGNAL_VERB_ASSERTIVENESS, key=len, reverse=True))
    + r")\b",
)

# Paraphrase markers: attribution without a quote following
_PARAPHRASE_MARKERS = re.compile(
    r"\b(?:according\s+to|in\s+(?:the\s+view|words?)\s+of|following\s+[A-Z]|"
    r"as\s+[A-Z][a-z]+\s+(?:has\s+)?(?:noted?|observed?|argued?|written?|shown?|put\s+it))"
    r"\b",
    re.IGNORECASE,
)


# ══════════════════════════════════════════════════════════════════════════════
# CitationData — structured output for Tier 16
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CitationData:
    """
    Structured citation usage extracted before prose stripping.

    All counts are raw; normalisation happens in tier16.py.
    """
    # Signal verbs: {verb: count}
    signal_verb_counts: Counter = field(default_factory=Counter)
    # Assertiveness scores of all signal verbs found (list for mean/distribution)
    signal_verb_assertiveness_scores: List[float] = field(default_factory=list)

    # Author names extracted from parenthetical citations
    cited_authors: List[str] = field(default_factory=list)

    # Total parenthetical + scripture citation count
    paren_citation_count: int = 0
    # Footnote marker count (superscripts)
    footnote_marker_count: int = 0
    # ibid / op. cit. count
    ibid_count: int = 0

    # Block quote word count (direct quote > 40 words)
    block_quote_word_count: int = 0
    # Non-block direct quote count (short in-line quotes)
    short_quote_count: int = 0

    # Per-paragraph citation counts (for CV calculation)
    citations_per_paragraph: List[int] = field(default_factory=list)

    # Citation position encoding: list of values in {0:"end", 0.5:"mid", 1:"start"}
    citation_positions: List[float] = field(default_factory=list)

    # Paraphrase marker count
    paraphrase_marker_count: int = 0

    # Total prose word count (for rate normalisation)
    prose_word_count: int = 0


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def preprocess(text: str) -> Tuple[str, CitationData]:
    """
    Prepare text for stylometric feature extraction.

    Steps
    -----
    1. Strip back-matter sections (bibliography, appendices, notes).
    2. Extract citation fingerprint data *before* stripping in-body citations.
    3. Strip parenthetical citations, footnote markers, and block quotes from
       the prose body so they do not contaminate surface feature extractors.
    4. Return clean prose + CitationData.

    Parameters
    ----------
    text : str
        Raw submission or baseline text (may include bibliography etc.)

    Returns
    -------
    prose : str
        Clean body prose for TextDoc / feature extractors.
    citation_data : CitationData
        Structured citation usage data for Tier 16.
    """
    # ── 1. Strip back-matter ──────────────────────────────────────────────────
    body = _strip_backmatter(text)

    # ── 2. Extract citation fingerprint data ──────────────────────────────────
    citation_data = _extract_citation_data(body)

    # ── 3. Strip citations and block quotes from prose ────────────────────────
    prose = _clean_prose(body)

    citation_data.prose_word_count = len(prose.split())
    return prose, citation_data


# ══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _extract_citation_data(body: str) -> CitationData:
    """Extract all citation fingerprint data from the body text."""
    cd = CitationData()

    # ── Signal verbs ──────────────────────────────────────────────────────────
    for m in _SIGNAL_PHRASE_RE.finditer(body):
        verb = m.group(1).lower()
        cd.signal_verb_counts[verb] += 1
        score = SIGNAL_VERB_ASSERTIVENESS.get(verb, 0.5)
        cd.signal_verb_assertiveness_scores.append(score)

    # ── Parenthetical citations ───────────────────────────────────────────────
    paren_matches = list(_PAREN_CITATION.finditer(body))
    scripture_matches = list(_SCRIPTURE_PAREN.finditer(body))
    cd.paren_citation_count = len(paren_matches) + len(scripture_matches)

    # Extract author names (first token in each match)
    for m in paren_matches:
        # First word inside the parenthesis = first author surname
        inner = m.group(0)[1:-1].strip()
        surname = re.match(r"[A-Z][a-záéíóú\-]+", inner)
        if surname:
            cd.cited_authors.append(surname.group(0))

    # ── Footnote markers ──────────────────────────────────────────────────────
    cd.footnote_marker_count = len(_FOOTNOTE_SUPERSCRIPT.findall(body))

    # ── Ibid ──────────────────────────────────────────────────────────────────
    cd.ibid_count = len(_IBID_RE.findall(body))

    # ── Block quotes ──────────────────────────────────────────────────────────
    for m in _DOUBLE_QUOTE_BLOCK.finditer(body):
        wc = len(m.group(0).split())
        if wc > 40:
            cd.block_quote_word_count += wc
        else:
            cd.short_quote_count += 1
    for m in _INDENT_BLOCK.finditer(body):
        cd.block_quote_word_count += len(m.group(0).split())

    # ── Per-paragraph citation density ────────────────────────────────────────
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    all_citation_re = re.compile(
        _PAREN_CITATION.pattern + r"|" + _SCRIPTURE_PAREN.pattern
        + r"|" + _FOOTNOTE_SUPERSCRIPT.pattern
        + r"|" + _IBID_RE.pattern,
        re.IGNORECASE | re.UNICODE,
    )
    for para in paragraphs:
        count = len(all_citation_re.findall(para))
        cd.citations_per_paragraph.append(count)

    # ── Citation position within sentence ────────────────────────────────────
    # Rough sentence split; for each citation, determine whether it appears
    # near the start, middle, or end of the sentence it falls in.
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z\"\'])", body)
    for sent in sentences:
        # Find all citation positions in this sentence
        sent_len = len(sent)
        if sent_len < 10:
            continue
        for cit_re in (_PAREN_CITATION, _SCRIPTURE_PAREN, _FOOTNOTE_SUPERSCRIPT):
            for m in cit_re.finditer(sent):
                rel_pos = m.start() / sent_len  # 0=start, 1=end
                # Remap: 0=start (authority-led), 1=end (assertive)
                cd.citation_positions.append(rel_pos)

    # ── Paraphrase markers ────────────────────────────────────────────────────
    cd.paraphrase_marker_count = len(_PARAPHRASE_MARKERS.findall(body))

    return cd


def _clean_prose(body: str) -> str:
    """
    Remove citation markers and block quotes from body prose.

    Keeps signal phrases intact. Strips:
    - Parenthetical citations
    - Scripture parenthetical references
    - Footnote superscript markers
    - Block quotes (indented or > 40 words in quotes)
    """
    # Remove block quotes (indented) first so we don't process their content
    prose = _INDENT_BLOCK.sub(" ", body)

    # Remove long quoted blocks
    def _maybe_strip_quote(m: re.Match) -> str:
        wc = len(m.group(0).split())
        return " " if wc > 40 else m.group(0)

    prose = _DOUBLE_QUOTE_BLOCK.sub(_maybe_strip_quote, prose)

    # Strip parenthetical citations and scripture refs
    prose = _PAREN_CITATION.sub("", prose)
    prose = _SCRIPTURE_PAREN.sub("", prose)

    # Strip footnote superscript markers
    prose = _FOOTNOTE_SUPERSCRIPT.sub("", prose)

    # Collapse multiple spaces / clean up punctuation gaps
    prose = re.sub(r" {2,}", " ", prose)
    prose = re.sub(r"\s+([.,;:!?])", r"\1", prose)
    prose = prose.strip()

    return prose
