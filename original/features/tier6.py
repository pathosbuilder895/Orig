"""
features/tier6.py — Tier 6: Idiosyncratic & Error Patterns

Six features capturing the most person-specific category in the
Writeprints taxonomy. Spelling errors, grammatical habits, and
formatting preferences are largely unconscious and extremely
difficult to fake consistently.

All pure Python + regex. No NLP dependencies.
"""

import re
import math
from collections import Counter
from typing import Dict, List, Set

from .tier1 import TextDoc, _tokenize
from ..constants import STOP_WORDS


# ── Abbreviation dictionary (theological domain) ────────────────────────────
# Maps abbreviation → full form.  Used by abbreviation_tendency.

THEOLOGICAL_ABBREVIATIONS = {
    "nt":  "new testament",
    "ot":  "old testament",
    "lxx": "septuagint",
    "mt":  "masoretic text",
    "bfm": "baptist faith and message",
    "cf":  "compare",
    "e.g": "for example",
    "i.e": "that is",
    "et al": "and others",
    "ibid": "in the same place",
    "op cit": "in the work cited",
    "viz": "namely",
    "esp": "especially",
    "v":   "verse",
    "vv":  "verses",
    "ch":  "chapter",
    "chs": "chapters",
    "gen": "genesis",
    "exod": "exodus",
    "lev": "leviticus",
    "num": "numbers",
    "deut": "deuteronomy",
    "isa": "isaiah",
    "jer": "jeremiah",
    "ezek": "ezekiel",
    "dan": "daniel",
    "hos": "hosea",
    "matt": "matthew",
    "rom": "romans",
    "cor": "corinthians",
    "gal": "galatians",
    "eph": "ephesians",
    "phil": "philippians",
    "col": "colossians",
    "thess": "thessalonians",
    "tim": "timothy",
    "heb": "hebrews",
    "jas": "james",
    "pet": "peter",
    "rev": "revelation",
}


# ── Citation format patterns ────────────────────────────────────────────────

CITATION_PATTERNS = {
    "apa_parenthetical": re.compile(r'\([A-Z][a-z]+,?\s+\d{4}'),          # (Smith, 2020)
    "apa_narrative":     re.compile(r'[A-Z][a-z]+\s+\(\d{4}\)'),          # Smith (2020)
    "turabian_footnote": re.compile(r'\d+\.\s+[A-Z][a-z]+,\s+[A-Z]'),    # 1. Author, T
    "inline_author":     re.compile(r'(?:as\s+)?[A-Z][a-z]+\s+(?:argues|notes|writes|states|contends|observes|claims|suggests|maintains)'),
    "ibid_style":        re.compile(r'\b[Ii]bid\.'),
    "scripture_ref":     re.compile(r'\b[1-3]?\s*[A-Z][a-z]+\s+\d+:\d+'),
}


# ── Tier 6 feature extractors ───────────────────────────────────────────────

def contraction_rate(doc: TextDoc) -> float:
    """
    Contractions per 100 words.

    Contractions (don't, it's, they're, etc.) are a strong register
    marker. Academic writers who use them do so habitually; those who
    avoid them almost never slip.
    """
    if not doc.word_count:
        return 0.0
    # Match tokens containing an apostrophe followed by common contractions
    contraction_pattern = re.compile(
        r"\b\w+'(?:t|s|re|ve|ll|d|m|nt)\b", re.IGNORECASE
    )
    count = len(contraction_pattern.findall(doc.raw))
    return count / doc.word_count * 100


def sentence_initial_conjunction_rate(doc: TextDoc) -> float:
    """
    Sentences starting with And/But/So/Or/Yet/For/Nor per total sentences.

    A strong register marker: formal academic writing avoids this;
    casual writers do it constantly.
    """
    if not doc.sentence_count:
        return 0.0
    initial_conjunctions = {"and", "but", "so", "or", "yet", "for", "nor"}
    count = 0
    for sent in doc.sentences:
        first_match = re.match(r'\b(\w+)', sent.lstrip())
        if first_match and first_match.group(1).lower() in initial_conjunctions:
            count += 1
    return count / doc.sentence_count


def that_which_ratio(doc: TextDoc) -> float:
    """
    Uses of "that" vs. "which" in relative clause contexts.

    Returns that_count / (that_count + which_count).
    Near 1.0 = strongly prefers "that"; near 0.0 = strongly prefers "which".
    0.5 = balanced. This is a deeply habitual preference.
    """
    # Match relative clause patterns (word + that/which)
    lower = doc.clean.lower()
    that_rel = len(re.findall(r'\b\w+\s+that\s+(?:is|are|was|were|has|have|had|the|a|an|\w+s\b)', lower))
    which_rel = len(re.findall(r'\b\w+\s+which\s+', lower))
    total = that_rel + which_rel
    if total == 0:
        return 0.5  # neutral when neither is used
    return that_rel / total


def citation_style_consistency(doc: TextDoc) -> float:
    """
    Entropy of citation format variants used in the text.

    Low entropy = consistent citation habit (single style).
    High entropy = mixed citation formats (or no citations).
    Returns 0.0 when no citations are found (perfectly consistent = no citations).
    """
    format_counts = Counter()
    for fmt_name, pattern in CITATION_PATTERNS.items():
        matches = len(pattern.findall(doc.raw))
        if matches > 0:
            format_counts[fmt_name] = matches

    if len(format_counts) <= 1:
        return 0.0  # single format or none = fully consistent

    # Shannon entropy normalized by log2(num_formats)
    total = sum(format_counts.values())
    entropy = 0.0
    for count in format_counts.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    max_entropy = math.log2(len(format_counts))
    return entropy / max_entropy if max_entropy > 0 else 0.0


def list_marker_preference(doc: TextDoc) -> float:
    """
    Categorical encoding of the author's default list/enumeration style.

    Returns a value encoding the dominant list marker:
      0.0 = no lists detected
      0.2 = numbered (1. 2. 3.)
      0.4 = lettered (a. b. c. or a) b) c))
      0.6 = roman (i. ii. iii.)
      0.8 = bullet (- or *)
      1.0 = inline (first, second, third / firstly, secondly)
    """
    numbered = len(re.findall(r'^\s*\d+[.)]\s', doc.raw, re.MULTILINE))
    lettered = len(re.findall(r'^\s*[a-z][.)]\s', doc.raw, re.MULTILINE))
    roman = len(re.findall(r'^\s*(?:i{1,3}|iv|vi{0,3}|ix|x)[.)]\s', doc.raw, re.MULTILINE))
    bullet = len(re.findall(r'^\s*[-*•]\s', doc.raw, re.MULTILINE))
    inline = len(re.findall(
        r'\b(?:first(?:ly)?|second(?:ly)?|third(?:ly)?|fourth(?:ly)?|finally)\b',
        doc.clean.lower()
    ))

    counts = {
        0.2: numbered,
        0.4: lettered,
        0.6: roman,
        0.8: bullet,
        1.0: inline,
    }

    max_count = max(counts.values())
    if max_count == 0:
        return 0.0

    # Return the encoding of the most common style
    for encoding, count in sorted(counts.items()):
        if count == max_count:
            return encoding
    return 0.0


def abbreviation_tendency(doc: TextDoc) -> float:
    """
    Ratio of abbreviated forms used vs. expanded forms available.

    High = author prefers abbreviations (e.g., "NT" over "New Testament").
    Low = author prefers full forms.

    Normalized against the theological abbreviation dictionary.
    """
    lower = doc.clean.lower()
    abbrev_used = 0
    full_used = 0

    for abbrev, full_form in THEOLOGICAL_ABBREVIATIONS.items():
        # Check for abbreviation (case-insensitive word boundary)
        abbrev_count = len(re.findall(r'\b' + re.escape(abbrev) + r'\b', lower))
        # Check for full form
        full_count = lower.count(full_form)

        if abbrev_count > 0:
            abbrev_used += abbrev_count
        if full_count > 0:
            full_used += full_count

    total = abbrev_used + full_used
    if total == 0:
        return 0.5  # neutral when neither form is detected
    return abbrev_used / total


# ── Public extraction function ───────────────────────────────────────────────

def extract_tier6(doc: TextDoc) -> Dict[str, float]:
    return {
        "contraction_rate":                 contraction_rate(doc),
        "sentence_initial_conjunction_rate": sentence_initial_conjunction_rate(doc),
        "that_which_ratio":                 that_which_ratio(doc),
        "citation_style_consistency":       citation_style_consistency(doc),
        "list_marker_preference":           list_marker_preference(doc),
        "abbreviation_tendency":            abbreviation_tendency(doc),
    }
