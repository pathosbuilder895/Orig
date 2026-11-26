"""Reworked word-list habits (``FEATURE_SET=2``; off by default).

Why
---
The first word-list habits (``tier1``/``tier2``/``tier3``/``tier7`` with the
lists in ``constants``) match words with no regard to how they are used:
"May 2026" counted as a hedge and a modal verb, "about grief" and "rather
than" as hedges, "It is clearly wrong" as two confident-statement words, and
"the second chapter", "so long" or "the thing that is wrong" as linking words.
This module counts the same habits with rules a reader would apply. It is used
only when ``features.feature_flags.lexicon_v2()`` is on; otherwise the old
functions run unchanged.

Hedges
------
The list follows Hyland's hedges (Metadiscourse, 2005, appendix), the standard
list for academic writing, with the rules Hyland himself asks for ("every
instance should be studied in its sentential co-text"):

* may / might / could count only as modal verbs (spaCy tag ``MD``), so the
  month "May" never counts; "May I ..." at the start of a sentence asks
  permission and does not count.
* would counts only in "would seem / appear / suggest / ..." (habitual
  "would walk" and requests do not).
* about / around count only before a number ("about forty", "around $40").
* rather does not count in "rather than" or "would rather".
* appear counts only before "to" or "that" (not "appeared on stage");
  tend only before "to".
* think / believe / feel / suspect / guess count only after "I" or "we".
* phrases ("to some extent", "it is possible that", "in my view", ...) match
  whole words, longest first, and a word inside a counted phrase is not
  counted again.

Word classes come from the paper's own spaCy parse (``TextDoc.spacy_doc``,
the shared pipeline Tier 5 already runs), so no other model is loaded. Without
spaCy, a small fallback rule keeps the month out ("May" capitalised inside a
sentence, or next to a number).

Every function returns ``(start, end)`` spans in ``TextDoc.clean``, so the
staff evidence pages can quote exactly what was counted (``evidence.py``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..constants import ASSERTION_WORDS, DISCOURSE_MARKERS, MODAL_VERBS, TRANSITION_PHRASES

Span = tuple[int, int]

# ── Hyland (2005) hedges, as used here ───────────────────────────────────────

HEDGE_PHRASES_V2 = frozenset(
    {
        "to some extent", "to a certain extent", "to a large extent", "to some degree",
        "to a degree", "to a certain degree", "in some ways", "in some sense", "in a sense",
        "in many respects", "in general", "in most cases", "in most instances", "on the whole",
        "in my opinion", "in my view", "in our opinion", "in our view", "in this view",
        "from my perspective", "from our perspective", "from this perspective",
        "to my knowledge", "as far as i know", "as far as i can tell", "more or less",
        "not necessarily", "it is possible that", "it is likely that", "it is unlikely that",
        "it is probable that", "it is conceivable that", "it seems", "it appears",
        "certain amount", "certain extent", "certain level",
    }
)  # fmt: skip
HEDGE_ADVERBS_V2 = frozenset(
    {
        "almost", "apparent", "apparently", "approximately", "arguably", "broadly",
        "conceivably", "doubtful", "essentially", "fairly", "frequently", "generally",
        "largely", "likely", "mainly", "maybe", "mostly", "nearly", "often", "partially",
        "partly", "perhaps", "plausible", "plausibly", "possible", "possibly", "presumably",
        "probable", "probably", "quite", "relatively", "roughly", "seemingly", "sometimes",
        "somewhat", "typical", "typically", "uncertain", "uncertainly", "unclear",
        "unclearly", "unlikely", "usually", "virtually",
    }
)  # fmt: skip
HEDGE_MODALS_V2 = frozenset({"may", "might", "could", "couldn't"})
HEDGE_VERBS_V2 = frozenset(
    {
        "seem", "seems", "seemed", "suggest", "suggests", "suggested", "indicate",
        "indicates", "indicated", "suppose", "supposes", "suspect", "suspects", "assume",
        "assumes", "assumed", "estimate", "estimates", "estimated", "postulate",
        "postulates", "postulated", "doubt",
    }
)  # fmt: skip
_APPEAR = frozenset({"appear", "appears", "appeared"})
_TEND = frozenset({"tend", "tends", "tended"})
_FIRST_PERSON_COGNITION = frozenset(
    {"think", "believe", "feel", "felt", "suspect", "guess", "doubt"}
)
_WOULD_EPISTEMIC = frozenset(
    {"seem", "appear", "suggest", "indicate", "argue", "guess", "think", "imagine", "say", "expect"}
)
_NUMBER_WORDS = frozenset(
    {
        "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        "eleven", "twelve", "fifteen", "twenty", "thirty", "forty", "fifty", "sixty",
        "seventy", "eighty", "ninety", "hundred", "a", "half", "dozen",
    }
)  # fmt: skip
_MONTH_NEIGHBOURS = re.compile(r"\d")
_DETERMINERS = frozenset({"the", "a", "an", "his", "her", "my", "their", "our", "your", "its"})

# Confident-statement words: the old list with whole-word matching. "must" is
# left out: in student prose it is mostly obligation ("we must act"), and
# Hyland lists it as a booster only in its "must be (possibility)" sense.
ASSERTION_WORDS_V2 = frozenset(ASSERTION_WORDS - {"must"})

# Linking words whose other uses are common: counted only where they link.
_LINK_AT_START = frozenset({"first", "second", "third", "next"})
_LINK_AFTER_PAUSE = frozenset({"so", "then"})
_SO_NOT_LINKING = frozenset({"much", "many", "far", "long", "few", "little", "well", "to"})

_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _phrase_pattern(phrase: str) -> re.Pattern:
    words = [re.escape(w) for w in phrase.split()]
    return re.compile(r"(?<![\w'])" + r"\s+".join(words) + r"(?![\w'])", re.IGNORECASE)


_PATTERN_CACHE: dict[str, re.Pattern] = {}


def _pattern(phrase: str) -> re.Pattern:
    p = _PATTERN_CACHE.get(phrase)
    if p is None:
        p = _PATTERN_CACHE[phrase] = _phrase_pattern(phrase)
    return p


def _longest_first(
    text: str, phrases: Iterable[str], keep=lambda text, a, b, phrase: True
) -> list[tuple[int, int, str]]:
    """Whole-word, case-insensitive matches, longest phrase first; a match that
    overlaps one already taken is skipped. ``keep`` can veto a match."""
    taken: list[tuple[int, int, str]] = []
    used = bytearray(len(text))
    for phrase in sorted(phrases, key=lambda p: (-len(p), p)):
        for m in _pattern(phrase).finditer(text):
            a, b = m.span()
            if any(used[a:b]) or not keep(text, a, b, phrase):
                continue
            used[a:b] = b"\x01" * (b - a)
            taken.append((a, b, phrase))
    return sorted(taken)


def _at_sentence_start(text: str, i: int) -> bool:
    j = i - 1
    while j >= 0 and (text[j].isspace() or text[j] in "\"'(\u201c\u2018["):
        j -= 1
    if j < 0:
        return True
    if text[j] in ".!?":
        return True
    if text[j] in "\"'\u201d\u2019)" and j > 0 and text[j - 1] in ".!?":
        return True
    return False


def _after_pause(text: str, i: int) -> bool:
    j = i - 1
    while j >= 0 and text[j].isspace():
        j -= 1
    return j < 0 or text[j] in ",;:\u2014\u2013-" or _at_sentence_start(text, i)


def _next_word(text: str, b: int) -> str:
    m = _WORD.match(text, len(text) - len(text[b:].lstrip()))
    return m.group(0).lower() if m else ""


def _prev_word(text: str, a: int) -> str:
    m = re.search(r"([A-Za-z]+(?:'[A-Za-z]+)?)[^A-Za-z]*$", text[max(0, a - 80) : a])
    return m.group(1).lower() if m else ""


def _next_is_number(text: str, b: int) -> bool:
    rest = text[b:].lstrip()
    if rest[:1].isdigit() or (rest and rest[0] in "$\u00a3\u20ac"):
        return True
    m = _WORD.match(rest)
    if not m:
        return False
    word = m.group(0).lower()
    if word == "a":  # "about a dozen", "around a hundred"
        return _next_word(rest, m.end()) in {"dozen", "hundred", "thousand", "third", "quarter"}
    return word in _NUMBER_WORDS


def _tags(doc) -> dict[int, tuple[str, str]] | None:
    """{character offset in doc.clean: (tag, coarse class)} from the paper's
    own spaCy parse, or None without spaCy."""
    sp = doc.spacy_doc
    if sp is None:
        return None
    return {t.idx: (t.tag_, t.pos_) for t in sp}


def _month_like(text: str, a: int, b: int) -> bool:
    """Fallback without spaCy: "May" as the month."""
    if text[a:b] != "May":
        return False
    before, after = text[max(0, a - 4) : a], text[b : b + 4]
    if _MONTH_NEIGHBOURS.search(before) or _MONTH_NEIGHBOURS.search(after):
        return True
    return not _at_sentence_start(text, a)


# ── Hedges ───────────────────────────────────────────────────────────────────


def hedge_spans(doc) -> list[Span]:
    text = doc.clean
    tags = _tags(doc)
    out = [(a, b) for a, b, _ in _longest_first(text, HEDGE_PHRASES_V2)]
    used = bytearray(len(text))
    for a, b in out:
        used[a:b] = b"\x01" * (b - a)
    for m in _WORD.finditer(text):
        a, b = m.span()
        if any(used[a:b]):
            continue
        if _is_hedge(text, a, b, m.group(0), tags):
            out.append((a, b))
    return sorted(out)


def _is_hedge(text: str, a: int, b: int, word: str, tags) -> bool:
    w = word.lower()
    # A word spaCy split differently has no tag at this offset: treat it as untagged.
    tag = tags.get(a, ("", "")) if tags is not None else None
    if w in HEDGE_MODALS_V2:
        if w == "may" and _at_sentence_start(text, a) and _next_word(text, b) in {"i", "we"}:
            return False  # "May I ask ...": permission
        if tag is not None:
            return tag[0] == "MD"
        return not _month_like(text, a, b)
    if w in {"would", "wouldn't"}:
        return _next_word(text, b) in _WOULD_EPISTEMIC
    if w in {"about", "around"}:
        return _next_is_number(text, b)
    if w == "rather":
        return _next_word(text, b) != "than" and _prev_word(text, a) not in {"would", "i'd", "we'd"}
    if w in HEDGE_ADVERBS_V2:
        return tag is None or tag[1] in {"ADV", "ADJ"}
    if w in _APPEAR:
        return _next_word(text, b) in {"to", "that"}
    if w in _TEND:
        return _next_word(text, b) == "to"
    if w in _FIRST_PERSON_COGNITION and _prev_word(text, a) in {"i", "we"}:
        return True
    if w in HEDGE_VERBS_V2:
        if w == "doubt":
            return _prev_word(text, a) not in {"no", "without", "beyond"}
        return tag is None or tag[1] in {"VERB", "AUX"}
    return False


# ── Confident statements ─────────────────────────────────────────────────────


def assertion_spans(doc) -> list[Span]:
    return [(a, b) for a, b, _ in _longest_first(doc.clean, ASSERTION_WORDS_V2)]


# ── Modal verbs ──────────────────────────────────────────────────────────────


def modal_spans(doc) -> list[Span]:
    """Modal verbs among the paper's words (the old count's ``lower_words``),
    counted only when spaCy tags them as modals; without spaCy, the old count
    less the month "May" and names like "Will" inside a sentence."""
    text = doc.clean
    tags = _tags(doc)
    out = []
    for m in re.finditer(r"\b\w+(?:'\w+)?\b", text):
        word = m.group(0)
        if not word.isalpha() or word.lower() not in MODAL_VERBS:
            continue
        a, b = m.span()
        if _prev_word(text, a) in _DETERMINERS:
            continue  # "the can", "her will": nouns, whatever the tagger says
        if tags is not None:
            if tags.get(a, ("", ""))[0] != "MD":
                continue
        elif word[0].isupper() and not _at_sentence_start(text, a):
            continue  # "Will Smith", "in May"
        elif _month_like(text, a, b):
            continue
        out.append((a, b))
    return out


# ── Linking words ────────────────────────────────────────────────────────────


def _links_here(text: str, a: int, b: int, phrase: str) -> bool:
    p = phrase.lower()
    if p in _LINK_AT_START:
        return _at_sentence_start(text, a)
    if p in _LINK_AFTER_PAUSE:
        if not _after_pause(text, a):
            return False
        return not (p == "so" and _next_word(text, b) in _SO_NOT_LINKING)
    if p == "that is":
        return _after_pause(text, a) or text[b : b + 1] == ","
    return True


def transition_spans(doc) -> list[Span]:
    return [(a, b) for a, b, _ in _longest_first(doc.clean, TRANSITION_PHRASES, _links_here)]


def discourse_markers(text: str) -> list[tuple[str, str]]:
    """(marker, category) for each different marker used as a link at least
    once, in ``DISCOURSE_MARKERS`` order (the old function's shape)."""
    return [(mk, cat) for mk, cat, _ in _first_markers(text)]


def first_marker_spans(text: str, category: str | None) -> list[Span]:
    found = _first_markers(text)
    return sorted(span for _, cat, span in found if category is None or cat == category)


def _first_markers(text: str) -> list[tuple[str, str, Span]]:
    found = []
    for marker, cat in DISCOURSE_MARKERS.items():
        for m in _pattern(marker).finditer(text):
            if _links_here(text, m.start(), m.end(), marker):
                found.append((marker, cat, m.span()))
                break
    return found
