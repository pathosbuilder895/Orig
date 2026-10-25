"""Located evidence passages and the optional preliminary score (ADR-013).

Why this exists
---------------
Original turns each paper into whole-paper measurements, so a score response
carries no text positions and ADR-012 removed the design's highlighted
quotes. Some measurements, though, are plain counts of things that sit at a
place in the text: commas, semicolons, transition words, hedges, questions,
contractions. For those, this module finds every place the measurement
counted, in the paper's stored text, and quotes the sentence around it.

Honesty rules this module keeps
-------------------------------
* **Same counting as the engine.** The engine measures the text *after*
  ``features.preprocess`` (back matter, citations and block quotes removed)
  and, for word-level habits, after ``TextDoc`` collapses whitespace. This
  module rebuilds exactly those strings while remembering where every
  character came from in the stored text, then runs each measurement's own
  counting rule over them. The rebuilt strings are checked against the real
  ``preprocess``/``TextDoc`` output, and the number of located places is
  checked against the measurement's own value. Any mismatch fails closed:
  the habit is shown as numbers only for that paper, never with guessed
  quotes.
* **Verbatim quotes only.** Every quoted passage is ``text[start:end]`` of the
  stored text at the recorded offsets. Nothing is paraphrased or generated.
  A sentence longer than ``MAX_QUOTE_CHARS`` is cut to a window that is
  still a verbatim slice, and ``clipped_start``/``clipped_end`` say so.
* **The engine's own ranking.** The habits explained are the engine's
  ``destructive_features`` in the engine's order (``quantum/scoring.py``
  ``_decompose``). No new ranking is invented here.
* **Deterministic.** No sets are iterated for output order, no randomness;
  the same texts and the same score give the same evidence.
* Habits whose value is a statistic over the whole paper (entropy, variance
  of embeddings, rhythm, divergence and so on) have no place in the text.
  They are listed with their numbers and ``locatable: false``.

Nothing here changes a score or the recommended action.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .constants import (
    ASSERTION_WORDS,
    AUTHORITY_MARKERS,
    CLAIM_MARKERS,
    DISCOURSE_MARKERS,
    FEATURE_NAMES,
    FIRST_PERSON,
    HEDGE_WORDS,
    MODAL_VERBS,
    PASSIVE_PATTERNS,
    PERSONAL_PRONOUNS,
    TRANSITION_PHRASES,
)
from .features import preprocess as _pp
from .features import tier1, tier2, tier3, tier4, tier6
from .features.tier1 import TextDoc, _tokenize

#: The one label every preliminary score carries (ADR-013). Wording rules:
#: no detection, misconduct or authorship-verification words, no accuracy claim.
PRELIMINARY_LABEL = "Preliminary · unvalidated · not a judgment"
PRELIMINARY_NOTE = (
    "From Original's own comparison math only: how far this paper sits from the "
    "writer's past papers on a 0 to 1 scale (higher is further). It is not "
    "validated on real student writing and is a reason to read closely, not a finding."
)
INCONCLUSIVE_WORDS = "Not enough writing on file to compare yet."
#: Plain words for the engine's existing action bands (constants.ACTION_THRESHOLDS).
BAND_WORDS = {
    "no_action": "Within the writer's usual range",
    "monitor": "A little outside the usual range",
    "schedule_conversation": "Outside the usual range",
    "escalate": "Far outside the usual range",
}
NUMBERS_ONLY_NOTE = (
    "Measured over the whole paper; this habit has no single place in the text, "
    "so it is shown as numbers only."
)
NOT_LOCATED_NOTE = (
    "The places counted could not be matched exactly to the stored text of this "
    "paper, so no passages are shown for it (numbers only)."
)


def evidence_enabled() -> bool:
    """EVIDENCE_PASSAGES_ENABLED=1 adds located evidence to staff score responses."""
    return os.environ.get("EVIDENCE_PASSAGES_ENABLED", "0").strip() == "1"


def preliminary_enabled() -> bool:
    """PRELIMINARY_SCORE_ENABLED=1 adds the preliminary score to staff score responses."""
    return os.environ.get("PRELIMINARY_SCORE_ENABLED", "0").strip() == "1"


MAX_EXAMPLES = 3
MAX_QUOTE_CHARS = 360
DEFAULT_TOP_N = 5

_FEATURE_DATA = Path(__file__).resolve().parents[1] / "demo" / "original" / "js" / "feature-data.js"
_FEATURE_ROW = re.compile(r"\['([a-z0-9_]+)','((?:[^'\\]|\\.)*)','((?:[^'\\]|\\.)*)'\]")


@lru_cache(maxsize=1)
def _descriptions() -> dict[str, tuple[str, str]]:
    """Plain-English names and descriptions from the live suite's one source
    (``demo/original/js/feature-data.js``), so the report and the pages agree."""
    try:
        source = _FEATURE_DATA.read_text(encoding="utf-8")
    except OSError:
        return {}
    return {
        code: (name.replace("\\'", "'"), desc.replace("\\'", "'"))
        for code, name, desc in _FEATURE_ROW.findall(source)
    }


def describe(code: str) -> tuple[str, str]:
    name, desc = _descriptions().get(code, (FEATURE_NAMES.get(code, code), ""))
    return name, desc


# ── Engine strings with a map back to the stored text ────────────────────────


@dataclass(frozen=True)
class Mapped:
    """A string plus, for every character, its offset in the stored text."""

    text: str
    origin: tuple[int, ...]

    def span(self, a: int, b: int) -> tuple[int, int]:
        """Stored-text span covering engine characters ``[a, b)``.

        A space the engine put in place of a removed block has origin -1 and
        is skipped; every located span has at least one real character."""
        real = [o for o in self.origin[a:b] if o >= 0]
        return real[0], real[-1] + 1


def _msub(
    m: Mapped, pattern: re.Pattern, repl: Callable[[re.Match], tuple[str, Sequence[int]]]
) -> Mapped:
    out: list[str] = []
    origin: list[int] = []
    last = 0
    for match in pattern.finditer(m.text):
        out.append(m.text[last : match.start()])
        origin.extend(m.origin[last : match.start()])
        new_text, new_origin = repl(match)
        out.append(new_text)
        origin.extend(new_origin)
        last = match.end()
    out.append(m.text[last:])
    origin.extend(m.origin[last:])
    return Mapped("".join(out), tuple(origin))


def _strip(m: Mapped) -> Mapped:
    lead = len(m.text) - len(m.text.lstrip())
    end = len(m.text.rstrip())
    return Mapped(m.text[lead:end], m.origin[lead:end])


def _collapse(m: Mapped, pattern: re.Pattern) -> Mapped:
    return _msub(m, pattern, lambda mt: (" ", (m.origin[mt.start()],)))


def _drop(m: Mapped, pattern: re.Pattern) -> Mapped:
    return _msub(m, pattern, lambda mt: ("", ()))


@dataclass(frozen=True)
class EngineView:
    """The two strings the engine measures, mapped back to the stored text."""

    original: str
    prose: Mapped  # what features.preprocess returns (TextDoc.raw)
    clean: Mapped  # TextDoc.clean
    doc: TextDoc


@lru_cache(maxsize=64)
def engine_view(text: str) -> EngineView | None:
    """Rebuild the engine's measured strings with offsets, or None if the
    rebuild does not match the engine byte for byte (fail closed)."""
    body_end = len(_pp._strip_backmatter(text))
    m = Mapped(text[:body_end], tuple(range(body_end)))
    if not _pp._indent_is_paragraph_style(m.text):  # every paragraph indented: nothing stripped
        m = _msub(m, _pp._INDENT_BLOCK, lambda mt: (" ", (-1,)))  # removed: no origin

    def _quote(match: re.Match):
        if len(match.group(0).split()) > 40:
            return " ", (-1,)
        return match.group(0), m_q.origin[match.start() : match.end()]

    m_q = m
    m = _msub(m_q, _pp._DOUBLE_QUOTE_BLOCK, _quote)
    m = _drop(m, _pp._PAREN_CITATION)
    m = _drop(m, _pp._SCRIPTURE_PAREN)
    m = _drop(m, _pp._FOOTNOTE_SUPERSCRIPT)
    m = _collapse(m, re.compile(r" {2,}"))
    m_p = m
    m = _msub(
        m_p, re.compile(r"\s+([.,;:!?])"), lambda mt: (mt.group(1), (m_p.origin[mt.start(1)],))
    )
    prose = _strip(m)
    expected_prose, _ = _pp.preprocess(text)
    if prose.text != expected_prose:
        return None
    doc = TextDoc(expected_prose)
    c = _collapse(prose, re.compile(r"\s+"))
    c = _collapse(c, re.compile(r"\n{3,}"))
    clean = _strip(c)
    if clean.text != doc.clean:  # pragma: no cover - TextDoc._clean is exactly the two subs above
        return None
    return EngineView(text, prose, clean, doc)


# ── Counting rules, mirrored from the feature extractors ─────────────────────
# Each returns (string level, list of [a, b) spans in that level's string).


def _str_count(text: str, needle: str) -> list[tuple[int, int]]:
    """Spans of ``str.count`` (non-overlapping, left to right)."""
    spans, i = [], text.find(needle)
    while i != -1:
        spans.append((i, i + len(needle)))
        i = text.find(needle, i + len(needle))
    return spans


def _phrase_spans(lower: str, phrases: Iterable[str]) -> list[tuple[int, int]]:
    """Spans of tier3._count_phrases / tier2.transition_density."""
    spans: list[tuple[int, int]] = []
    for phrase in sorted(phrases):
        if " " in phrase:
            spans += _str_count(lower, phrase)
        else:
            spans += [mt.span() for mt in re.finditer(r"\b" + re.escape(phrase) + r"\b", lower)]
    return sorted(spans)


def _token_spans(clean: str, vocabulary: set[str]) -> list[tuple[int, int]]:
    return [
        mt.span()
        for mt in re.finditer(r"\b\w+(?:'\w+)?\b", clean)
        if mt.group(0).isalpha() and mt.group(0).lower() in vocabulary
    ]


def _first_marker_spans(lower: str, category: str | None) -> list[tuple[int, int]]:
    """tier2._find_discourse_markers counts each different marker once."""
    spans = []
    for marker, cat in DISCOURSE_MARKERS.items():
        if category is not None and cat != category:
            continue
        if " " in marker:
            i = lower.find(marker)
            if i != -1:
                spans.append((i, i + len(marker)))
        else:
            mt = re.search(r"\b" + re.escape(marker) + r"\b", lower)
            if mt:
                spans.append(mt.span())
    return sorted(spans)


_INITIAL_CONJ = {"and", "but", "so", "or", "yet", "for", "nor"}


def _sentence_spans(view: EngineView) -> list[tuple[int, int]] | None:
    """Clean-string spans of the engine's own sentences (tier1._split_sentences)."""
    spans, cursor = [], 0
    for sentence in view.doc.sentences:
        i = view.clean.text.find(sentence, cursor)
        if i == -1:
            return None
        spans.append((i, i + len(sentence)))
        cursor = i + len(sentence)
    return spans


def _sentences_where(pred: Callable[[str], bool]):
    def locate(view: EngineView):
        spans = _sentence_spans(view) or []
        return "clean", [(a, b) for a, b in spans if pred(view.clean.text[a:b])]

    return locate


def _lower(view: EngineView) -> str | None:
    lower = view.clean.text.lower()
    return lower if len(lower) == len(view.clean.text) else None


def _phrases(vocabulary):
    def locate(view: EngineView):
        lower = _lower(view)
        return ("clean", _phrase_spans(lower, vocabulary)) if lower is not None else ("clean", None)

    return locate


def _markers(category):
    def locate(view: EngineView):
        lower = _lower(view)
        return (
            ("clean", _first_marker_spans(lower, category))
            if lower is not None
            else ("clean", None)
        )

    return locate


def _tokens(vocabulary):
    return lambda view: ("clean", _token_spans(view.clean.text, vocabulary))


def _chars(*needles):
    return lambda view: (
        "prose",
        sorted(s for n in needles for s in _str_count(view.prose.text, n)),
    )


def _quote_marks(view: EngineView):
    spans = [mt.span() for mt in re.finditer(r'(?<!\w)"(?=\w)', view.prose.text)]
    return "prose", sorted(spans + _str_count(view.prose.text, "\u201c"))


def _contractions(view: EngineView):
    pattern = re.compile(r"\b\w+'(?:t|s|re|ve|ll|d|m|nt)\b", re.IGNORECASE)
    return "prose", [mt.span() for mt in pattern.finditer(view.prose.text)]


def _passive(view: EngineView):
    spans = [
        mt.span()
        for pattern in PASSIVE_PATTERNS
        for mt in re.finditer(pattern, view.clean.text, re.IGNORECASE)
    ]
    return "clean", sorted(spans)


def _passive_share(n, doc):
    return min(n, doc.sentence_count) / doc.sentence_count if doc.sentence_count else 0.0


def _first_word(sentence: str) -> str:
    mt = re.match(r"\b(\w+)", sentence.lstrip())
    return mt.group(1).lower() if mt else ""


def _per100(n, doc):
    return n / doc.word_count * 100 if doc.word_count else 0.0


def _per_word(n, doc):
    return n / doc.word_count if doc.word_count else 0.0


def _per_sentence(n, doc):
    return n / doc.sentence_count if doc.sentence_count else 0.0


def _marker_share(n, doc):
    total = len(tier2._find_discourse_markers(doc.clean))
    return n / total if total else 0.0


def _first_person_share(n, doc):
    total = sum(1 for w in doc.lower_words if w in PERSONAL_PRONOUNS)
    return n / total if total else 0.0


@dataclass(frozen=True)
class Locatable:
    code: str
    what: str  # what one located place is, in plain words
    unit: str  # unit of the plain value
    locate: Callable[[EngineView], tuple[str, list[tuple[int, int]] | None]] | None
    formula: Callable[[int, TextDoc], float] | None  # rebuilds the value from the count
    value: Callable[[TextDoc], float]  # the extractor's own function
    sentence_length: str | None = None  # "mean" | "spread" for the two length habits


def _ratio(category):
    return lambda doc: tier2._marker_category_ratios(doc)[category]


#: Habits whose every counted occurrence maps to a place in the text, in the
#: engine's feature order (constants.ALL_FEATURE_CODES). See ADR-013.
LOCATABLE: dict[str, Locatable] = {
    spec.code: spec
    for spec in (
        Locatable(
            "mean_sentence_length",
            "sentence",
            "words per sentence",
            None,
            None,
            tier1.mean_sentence_length,
            sentence_length="mean",
        ),
        Locatable(
            "sentence_length_variance",
            "sentence",
            "variance of sentence length (words²)",
            None,
            None,
            tier1.sentence_length_variance,
            sentence_length="spread",
        ),
        Locatable(
            "passive_voice_ratio",
            "match of Original's passive pattern (is/was/been … + -ed/-en word)",
            "share of sentences (capped at one per sentence)",
            _passive,
            _passive_share,
            tier1.passive_voice_ratio,
        ),
        Locatable(
            "modal_verb_ratio",
            "modal verb (can, could, should, must, …)",
            "share of words",
            _tokens(MODAL_VERBS),
            _per_word,
            tier1.modal_verb_ratio,
        ),
        Locatable(
            "discourse_marker_density",
            "linking word or phrase (first use of each)",
            "per 100 words",
            _markers(None),
            _per100,
            tier2.discourse_marker_density,
        ),
        Locatable(
            "additive_ratio",
            "adding-on link (also, furthermore, …; first use of each)",
            "share of linking words",
            _markers("additive"),
            _marker_share,
            _ratio("additive"),
        ),
        Locatable(
            "adversative_ratio",
            "contrasting link (but, however, …; first use of each)",
            "share of linking words",
            _markers("adversative"),
            _marker_share,
            _ratio("adversative"),
        ),
        Locatable(
            "causal_ratio",
            "cause-and-effect link (because, therefore, …; first use of each)",
            "share of linking words",
            _markers("causal"),
            _marker_share,
            _ratio("causal"),
        ),
        Locatable(
            "temporal_ratio",
            "sequencing link (first, then, finally, …; first use of each)",
            "share of linking words",
            _markers("temporal"),
            _marker_share,
            _ratio("temporal"),
        ),
        Locatable(
            "transition_density",
            "transition word or phrase",
            "per 100 words",
            _phrases(TRANSITION_PHRASES),
            _per100,
            tier2.transition_density,
        ),
        Locatable(
            "hedging_density",
            "softening word (perhaps, might, seems, …)",
            "per 100 words",
            _phrases(HEDGE_WORDS),
            _per100,
            tier3.hedging_density,
        ),
        Locatable(
            "assertion_density",
            "confident-statement word (clearly, certainly, must, …)",
            "per 100 words",
            _phrases(ASSERTION_WORDS),
            _per100,
            tier3.assertion_density,
        ),
        Locatable(
            "claim_density",
            "claim or conclusion marker (therefore, this shows, …)",
            "per 100 words",
            _phrases(CLAIM_MARKERS),
            _per100,
            tier3.claim_density,
        ),
        Locatable(
            "question_ratio",
            "question",
            "share of sentences",
            _sentences_where(lambda s: s.strip().endswith("?")),
            _per_sentence,
            tier3.question_ratio,
        ),
        Locatable(
            "first_person_ratio",
            "first-person word (I, me, we, our, …)",
            "share of personal pronouns",
            _tokens(FIRST_PERSON),
            _first_person_share,
            tier3.first_person_ratio,
        ),
        Locatable(
            "appeal_to_authority_density",
            "source or authority phrase (according to, argues, …)",
            "per 100 words",
            _phrases(set(AUTHORITY_MARKERS)),
            _per100,
            tier3.appeal_to_authority_density,
        ),
        Locatable("comma_rate", "comma", "per 100 words", _chars(","), _per100, tier4.comma_rate),
        Locatable(
            "semicolon_colon_rate",
            "semicolon or colon",
            "per 100 words",
            _chars(";", ":"),
            _per100,
            tier4.semicolon_colon_rate,
        ),
        Locatable(
            "parenthetical_rate",
            "opening parenthesis",
            "per 100 words",
            _chars("("),
            _per100,
            tier4.parenthetical_rate,
        ),
        Locatable(
            "dash_rate",
            "dash (—, – or --)",
            "per 100 words",
            _chars("\u2014", "\u2013", "--"),
            _per100,
            tier4.dash_rate,
        ),
        Locatable(
            "quote_rate",
            "opening quotation mark",
            "per 100 words",
            _quote_marks,
            _per100,
            tier4.quote_rate,
        ),
        Locatable(
            "contraction_rate",
            "contraction (don't, it's, …)",
            "per 100 words",
            _contractions,
            _per100,
            tier6.contraction_rate,
        ),
        Locatable(
            "sentence_initial_conjunction_rate",
            "sentence starting with And, But, So, Or, Yet, For or Nor",
            "share of sentences",
            _sentences_where(lambda s: _first_word(s) in _INITIAL_CONJ),
            _per_sentence,
            tier6.sentence_initial_conjunction_rate,
        ),
    )
}


# ── Located places ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Place:
    start: int  # stored-text offsets of the counted thing
    end: int
    sentence_start: int  # stored-text offsets of the quoted passage
    sentence_end: int
    clipped_start: bool
    clipped_end: bool
    words: int | None = None  # engine word count, for the sentence-length habits
    crosses_set_aside: bool = False  # the counted span runs over text the engine set aside


@dataclass(frozen=True)
class PaperReading:
    """One paper's located places and plain value for one habit."""

    value: float
    places: tuple[Place, ...] | None  # None = could not be located exactly


def _passage(
    text: str, sentences: list[tuple[int, int]], start: int, end: int
) -> tuple[int, int, bool, bool]:
    """The quoted window: the sentence holding ``start``, or a verbatim window
    of at most about ``MAX_QUOTE_CHARS`` inside it, cut at spaces."""
    s0, s1 = start, end
    for a, b in sentences:
        if a <= start < b:
            s0, s1 = a, max(b, end)
            break
    if s1 - s0 <= MAX_QUOTE_CHARS:
        return s0, s1, False, False
    if end - start >= MAX_QUOTE_CHARS:  # the counted span is itself long (a whole sentence)
        w0, w1 = start, start + MAX_QUOTE_CHARS
    else:
        w0 = max(s0, start - (MAX_QUOTE_CHARS - (end - start)) // 2)
        w1 = max(end, min(s1, w0 + MAX_QUOTE_CHARS))
    # Move inward to a space so no word is cut (still a verbatim slice).
    if w0 > s0:
        k = text.find(" ", w0, min(start, w1))
        w0 = k + 1 if k != -1 else w0
    if w1 < s1:
        k = text.rfind(" ", min(end, w1 - 1) if end < w1 else w0 + 1, w1)
        w1 = k if k > w0 else w1
    return w0, w1, w0 > s0, w1 < s1


def _original_sentences(view: EngineView) -> list[tuple[int, int]] | None:
    spans = _sentence_spans(view)
    if spans is None:
        return None
    return [view.clean.span(a, b) for a, b in spans]


def read_paper(text: str, code: str) -> PaperReading | None:
    """Locate one habit in one paper. None when the habit is not locatable."""
    spec = LOCATABLE.get(code)
    if spec is None:
        return None
    view = engine_view(text)
    if view is None:
        prose, _ = _pp.preprocess(text)
        return PaperReading(spec.value(TextDoc(prose)), None)
    value = spec.value(view.doc)
    sentences = _original_sentences(view)
    if sentences is None:
        return PaperReading(value, None)
    if spec.sentence_length is not None:
        lengths = [len(_tokenize(s)) for s in view.doc.sentences]
        places = tuple(
            Place(
                a,
                b,
                *_passage(view.original, sentences, a, b),
                words=n,
                crosses_set_aside=_crosses_set_aside(view, a, b),
            )
            for (a, b), n in zip(sentences, lengths, strict=True)
        )
        return PaperReading(value, places)
    level, spans = spec.locate(view)
    if spans is None:
        return PaperReading(value, None)
    if abs(spec.formula(len(spans), view.doc) - value) > 1e-9:
        return PaperReading(value, None)  # fail closed: counts disagree
    mapped = view.prose if level == "prose" else view.clean
    places = []
    for a, b in spans:
        start, end = mapped.span(a, b)
        places.append(
            Place(
                start,
                end,
                *_passage(view.original, sentences, start, end),
                crosses_set_aside=_crosses_set_aside(view, start, end),
            )
        )
    return PaperReading(value, tuple(places))


@lru_cache(maxsize=64)
def _kept_cached(text: str) -> bytes:
    view = engine_view(text)
    kept = bytearray(len(text))
    for o in view.prose.origin:
        if o >= 0:
            kept[o] = 1
    return bytes(kept)


def _kept(view: EngineView) -> bytes:
    """1 for every stored-text character the engine measured."""
    return _kept_cached(view.original)


def _crosses_set_aside(view: EngineView, start: int, end: int) -> bool:
    kept = _kept(view)
    return any(not kept[i] and not view.original[i].isspace() for i in range(start, end))


def measured_coverage(text: str, *, max_ranges: int = 5, preview_chars: int = 80) -> dict[str, Any]:
    """How much of the stored text the engine actually measured.

    Back matter, citations and long quotations are set aside before any
    habit is measured (``features.preprocess``). This lists the set-aside
    stretches (stored-text offsets, a verbatim preview of each) so a reader
    can see what the numbers were taken from.
    """
    view = engine_view(text)
    stored_words = sum(1 for t in _tokenize(text) if t.isalpha())  # the engine's word count rule
    if view is None:
        prose, _ = _pp.preprocess(text)
        return {
            "stored_words": stored_words,
            "measured_words": TextDoc(prose).word_count,
            "set_aside": None,
            "set_aside_count": None,
        }
    kept = _kept(view)
    ranges: list[tuple[int, int]] = []
    i = 0
    while i < len(text):
        if kept[i] or text[i].isspace():
            i += 1
            continue
        j = i
        while j < len(text) and (not kept[j] or text[j].isspace()):
            j += 1
        while j > i and text[j - 1].isspace():
            j -= 1
        ranges.append((i, j))
        i = j
    return {
        "stored_words": stored_words,
        "measured_words": view.doc.word_count,
        "set_aside_count": len(ranges),
        "set_aside": [
            {
                "start": a,
                "end": b,
                "words": len(text[a:b].split()),
                "preview_end": min(b, a + preview_chars),
                "preview": text[a : min(b, a + preview_chars)],
            }
            for a, b in ranges[:max_ranges]
        ],
    }


# ── Evidence objects ─────────────────────────────────────────────────────────


def _quote(text: str, place: Place, paper: str) -> dict[str, Any]:
    """``passage == text[passage_start:passage_end]`` and ``match ==
    text[match_start:match_end]`` (the counted part inside the passage);
    ``start``/``end`` is the whole counted span."""
    m0 = max(place.start, place.sentence_start)
    m1 = min(place.end, place.sentence_end)
    out = {
        "paper": paper,
        "start": place.start,
        "end": place.end,
        "match_start": m0,
        "match_end": m1,
        "match": text[m0:m1],
        "passage_start": place.sentence_start,
        "passage_end": place.sentence_end,
        "passage": text[place.sentence_start : place.sentence_end],
        "clipped_start": place.clipped_start,
        "clipped_end": place.clipped_end,
        "crosses_set_aside": place.crosses_set_aside,
    }
    if place.words is not None:
        out["words"] = place.words
    return out


def _pick(places: Sequence[Place], limit: int) -> list[Place]:
    """First places in document order, one per passage (deterministic)."""
    seen, picked = set(), []
    for place in places:
        key = (place.sentence_start, place.sentence_end)
        if key in seen:
            continue
        seen.add(key)
        picked.append(place)
        if len(picked) == limit:
            break
    return picked


def _length_pick(places: Sequence[Place], mode: str, direction: str, limit: int) -> list[Place]:
    longest = sorted(places, key=lambda p: (-(p.words or 0), p.start))
    shortest = sorted(places, key=lambda p: ((p.words or 0), p.start))
    if mode == "mean":
        return list((longest if direction == "higher" else shortest)[:limit])
    picked: list[Place] = []
    for place in [x for pair in zip(longest, shortest, strict=False) for x in pair]:
        if place not in picked:
            picked.append(place)
        if len(picked) == limit:
            break
    return picked


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 4)


def build_feature_evidence(
    feature: dict[str, Any],
    submission_text: str,
    baselines: Sequence[tuple[str, str]],
    *,
    rank: int,
    max_examples: int = MAX_EXAMPLES,
) -> dict[str, Any]:
    """Evidence for one of the engine's differing habits.

    ``feature`` is one ``destructive_features`` item (code, submission_value,
    baseline_value, delta). ``baselines`` is ``[(label, text), ...]`` in a
    fixed order.
    """
    code = feature["code"]
    name, description = describe(code)
    delta = float(feature.get("delta", 0.0) or 0.0)
    direction = "higher" if delta > 0 else "lower" if delta < 0 else "same"
    out: dict[str, Any] = {
        "rank": rank,
        "code": code,
        "name": name,
        "description": description,
        "direction": direction,
        "engine_scale": {
            "this_paper": _round(feature.get("submission_value")),
            "past_papers_average": _round(feature.get("baseline_value")),
            "note": "Original's 0 to 1 scale for this habit, as used in the score.",
        },
        "locatable": code in LOCATABLE,
    }
    spec = LOCATABLE.get(code)
    if spec is None:
        out["note"] = NUMBERS_ONLY_NOTE
        return out
    this = read_paper(submission_text, code)
    past = [(label, text, read_paper(text, code)) for label, text in baselines]
    past_values = [r.value for _, _, r in past]
    out["plain"] = {
        "unit": spec.unit,
        "this_paper": _round(this.value),
        "past_papers": [{"paper": label, "value": _round(r.value)} for label, _, r in past],
        "past_range": [_round(min(past_values)), _round(max(past_values))] if past_values else None,
    }
    out["what_is_marked"] = spec.what
    if this.places is None or any(r.places is None for _, _, r in past):
        out["locatable"] = False
        out["note"] = NOT_LOCATED_NOTE
        return out

    def chosen(places):
        if spec.sentence_length:
            return _length_pick(places, spec.sentence_length, direction, max_examples)
        return _pick(places, max_examples)

    out["this_paper"] = {
        "count": len(this.places),
        "examples": [_quote(submission_text, p, "this paper") for p in chosen(this.places)],
    }
    # Past papers: take examples round-robin across papers in their fixed order.
    per_paper = [(label, text, chosen(r.places)) for label, text, r in past]
    examples: list[dict[str, Any]] = []
    depth = 0
    while len(examples) < max_examples and any(depth < len(c) for _, _, c in per_paper):
        for label, text, picks in per_paper:
            if depth < len(picks) and len(examples) < max_examples:
                examples.append(_quote(text, picks[depth], label))
        depth += 1
    out["past_papers"] = {
        "count": sum(len(r.places) for _, _, r in past),
        "per_paper": [{"paper": label, "count": len(r.places)} for label, _, r in past],
        "examples": examples,
    }
    if not spec.sentence_length:
        if not this.places:
            out["note"] = f"No {spec.what} appears in this paper."
        elif not out["past_papers"]["count"]:
            out["note"] = f"No {spec.what} appears in the past papers."
    return out


def build_evidence(
    destructive_features: Sequence[dict[str, Any]],
    submission_text: str,
    baselines: Sequence[tuple[str, str]],
    *,
    top_n: int = DEFAULT_TOP_N,
    max_examples: int = MAX_EXAMPLES,
) -> dict[str, Any]:
    """Evidence for the engine's top differing habits, in the engine's order."""
    features = [
        build_feature_evidence(f, submission_text, baselines, rank=i + 1, max_examples=max_examples)
        for i, f in enumerate(list(destructive_features)[:top_n])
    ]
    return {
        "measured": {
            "this_paper": measured_coverage(submission_text),
            "past_papers": [
                {"paper": label, **measured_coverage(text)} for label, text in baselines
            ],
        },
        "ordering": "Original's own order of the habits furthest from the writer's "
        "usual range (destructive_features).",
        "quotes_are_verbatim": True,
        "features": features,
        "locatable_codes": list(LOCATABLE),
    }


def countable_overview(
    submission_text: str, baselines: Sequence[tuple[str, str]]
) -> list[dict[str, Any]]:
    """Every locatable habit's plain value, this paper vs each past paper.

    Fixed feature order, not a ranking. Numbers only; no quotes.
    """
    rows = []
    views = [engine_view(submission_text)] + [engine_view(t) for _, t in baselines]
    docs = [
        v.doc if v is not None else TextDoc(_pp.preprocess(t)[0])
        for v, t in zip(views, [submission_text] + [t for _, t in baselines], strict=True)
    ]
    for code, spec in LOCATABLE.items():
        this_value = spec.value(docs[0])
        past = [spec.value(d) for d in docs[1:]]
        lo, hi = (min(past), max(past)) if past else (None, None)
        rows.append(
            {
                "code": code,
                "name": describe(code)[0],
                "unit": spec.unit,
                "this_paper": _round(this_value),
                "past_range": [_round(lo), _round(hi)] if past else None,
                "outside_past_range": bool(past) and not (lo - 1e-12 <= this_value <= hi + 1e-12),
            }
        )
    return rows


def preliminary_score(
    deviation: float | None, action: str | None, *, inconclusive: bool
) -> dict[str, Any]:
    """The optional preliminary score: Original's deviation and action band.

    Derived only from numbers the engine already returned; never shown to
    students (callers gate it). A thin baseline gives no number.
    """
    if inconclusive or deviation is None or action not in BAND_WORDS:
        return {
            "label": PRELIMINARY_LABEL,
            "score": None,
            "band": None,
            "band_words": INCONCLUSIVE_WORDS,
            "note": PRELIMINARY_NOTE,
        }
    return {
        "label": PRELIMINARY_LABEL,
        "score": round(float(deviation), 2),
        "band": action,
        "band_words": BAND_WORDS[action],
        "note": PRELIMINARY_NOTE,
    }


# ── Staff report rendering (markdown + HTML, two columns) ────────────────────


def _dir_words(direction: str) -> str:
    return {
        "higher": "higher than the past-paper average",
        "lower": "lower than the past-paper average",
    }.get(direction, "same as the past-paper average")


def _fmt(value) -> str:
    return "–" if value is None else f"{value:.3g}"


def _md_quote(q: dict[str, Any]) -> str:
    """Passage with the counted part in bold; the text itself is untouched."""
    a = q["match_start"] - q["passage_start"]
    b = q["match_end"] - q["passage_start"]
    p = q["passage"]
    whole = a == 0 and b == len(p)
    body = p if ("words" in q or whole) else f"{p[:a]}**{p[a:b]}**{p[b:]}"
    body = " ".join(body.split()).replace("|", "\\|")
    lead = "… " if q["clipped_start"] else ""
    tail = " …" if q["clipped_end"] else ""
    extra = f" ({q['words']} words)" if "words" in q else ""
    if q.get("crosses_set_aside"):
        extra += " (as Original read it, this runs across text it set aside)"
    return f"{lead}“{body}”{tail}{extra} — *{q['paper']}*, chars {q['start']}–{q['end']}"


def render_markdown(
    submission_id: str,
    evidence: dict[str, Any],
    preliminary: dict[str, Any] | None,
    overview: list[dict[str, Any]] | None = None,
) -> str:
    lines = [
        f"# Evidence for {submission_id} (staff only; never shown to students)",
        "",
        "Original in testing: not validated on real student writing. These passages show where "
        "countable habits appear; they are a reason to read closely, not a finding.",
        "",
    ]
    if preliminary is not None:
        score = "–" if preliminary["score"] is None else f"{preliminary['score']:.2f}"
        lines += [
            f"**{preliminary['label']}**: {score} · {preliminary['band_words']}",
            "",
            f"> {preliminary['note']}",
            "",
        ]
    measured = evidence.get("measured")
    if measured:

        def _cov(label, c):
            return f"{label}: {c['measured_words']} of {c['stored_words']} words measured"

        tp = measured["this_paper"]
        lines += [
            "## What Original measured",
            "",
            "Back matter, citations and long quotations are set aside before measuring.",
            "",
            "- " + _cov("This paper", tp),
        ]
        lines += ["- " + _cov(p["paper"], p) for p in measured["past_papers"]]
        for r in tp.get("set_aside") or []:
            preview = " ".join(r["preview"].split()).replace("|", "\\|")
            lines.append(
                f"  - set aside in this paper: chars {r['start']}–{r['end']}"
                f" ({r['words']} words): “{preview}”"
                + (" …" if r["preview_end"] < r["end"] else "")
            )
        if tp["stored_words"] and tp["measured_words"] < 0.8 * tp["stored_words"]:
            lines.append(
                "- **Note:** less than 80% of this paper's words were measured; "
                "read the numbers below with that in mind."
            )
        lines.append("")
    lines += [
        f"Order: {evidence['ordering']} Quotes are verbatim slices of the stored text at the "
        "character offsets shown; bold marks what was counted.",
        "",
    ]
    if not evidence["features"]:
        lines += ["The score listed no habits outside the writer's usual range.", ""]
    for f in evidence["features"]:
        lines += [f"## {f['rank']}. {f['name']} ({_dir_words(f['direction'])})", ""]
        if f["description"]:
            lines += [f["description"], ""]
        eng = f["engine_scale"]
        lines.append(
            f"- Original's 0–1 scale: this paper {_fmt(eng['this_paper'])}"
            f" · past-paper average {_fmt(eng['past_papers_average'])}"
        )
        if "plain" in f:
            pl = f["plain"]
            per = ", ".join(f"{p['paper']} {_fmt(p['value'])}" for p in pl["past_papers"])
            rng = pl["past_range"]
            lines.append(
                f"- In plain units ({pl['unit']}): this paper {_fmt(pl['this_paper'])} "
                f"· past papers "
                f"{_fmt(rng[0]) if rng else '–'}–{_fmt(rng[1]) if rng else '–'} ({per})"
            )
        if not f["locatable"]:
            lines += [f"- Numbers only: {f['note']}", ""]
            continue
        tp, pp = f["this_paper"], f["past_papers"]
        if "count" in tp and "words" not in (tp["examples"][0] if tp["examples"] else {}):
            lines.append(
                f"- Marked: {f['what_is_marked']}. Found {tp['count']} in this paper; "
                + ", ".join(f"{p['count']} in {p['paper']}" for p in pp["per_paper"])
                + "."
            )
        if f.get("note"):
            lines.append(f"- {f['note']}")
        lines += ["", "| This paper | Past papers |", "|---|---|"]
        rows = max(len(tp["examples"]), len(pp["examples"]), 1)
        for i in range(rows):
            left = (
                _md_quote(tp["examples"][i])
                if i < len(tp["examples"])
                else ("*(none in this paper)*" if i == 0 else "")
            )
            right = (
                _md_quote(pp["examples"][i])
                if i < len(pp["examples"])
                else ("*(none in the past papers)*" if i == 0 else "")
            )
            lines.append(f"| {left} | {right} |")
        lines.append("")
    if overview:
        lines += [
            "## Every countable habit (fixed order, not a ranking; numbers only)",
            "",
            "| habit | unit | this paper | past papers (min–max) | outside past range |",
            "|---|---|---:|---:|---|",
        ]
        for row in overview:
            rng = row["past_range"]
            lines.append(
                f"| {row['name']} | {row['unit']} | {_fmt(row['this_paper'])} | "
                f"{(_fmt(rng[0]) + '–' + _fmt(rng[1])) if rng else '–'}"
                f" | {'yes' if row['outside_past_range'] else ''} |"
            )
        lines.append("")
    return "\n".join(lines)


def _html_quote(q: dict[str, Any]) -> str:
    import html

    a = q["match_start"] - q["passage_start"]
    b = q["match_end"] - q["passage_start"]
    p = q["passage"]
    if "words" in q or (a == 0 and b == len(p)):
        inner = html.escape(p)
        extra = f" <small>({q['words']} words)</small>" if "words" in q else ""
    else:
        inner = f"{html.escape(p[:a])}<mark>{html.escape(p[a:b])}</mark>{html.escape(p[b:])}"
        extra = ""
    lead = "… " if q["clipped_start"] else ""
    tail = " …" if q["clipped_end"] else ""
    return (
        f"<blockquote>{lead}{inner}{tail}{extra}<br><small>{html.escape(q['paper'])}, "
        f"chars {q['start']}–{q['end']}</small></blockquote>"
    )


def render_html(
    submission_id: str, evidence: dict[str, Any], preliminary: dict[str, Any] | None
) -> str:
    import html

    parts = [
        "<!doctype html><meta charset='utf-8'><title>Evidence</title>",
        "<style>body{font:15px/1.5 Georgia,serif;max-width:1100px;margin:2em auto;padding:0 1em}"
        ".cols{display:grid;grid-template-columns:1fr 1fr;gap:1.5em}mark{background:#ffe9a8}"
        "blockquote{margin:.5em 0;padding:.4em .8em;border-left:3px solid #c9b37e}"
        ".note{color:#555}</style>",
        f"<h1>Evidence for {html.escape(submission_id)}</h1>",
        "<p class='note'>Staff only; never shown to students. Original in testing: "
        "not validated on real "
        "student writing. Quotes are verbatim slices of the stored text.</p>",
    ]
    if preliminary is not None:
        score = "–" if preliminary["score"] is None else f"{preliminary['score']:.2f}"
        parts.append(
            f"<p><strong>{html.escape(preliminary['label'])}</strong>: {score} · "
            f"{html.escape(preliminary['band_words'])}"
            f"<br><span class='note'>{html.escape(preliminary['note'])}</span></p>"
        )
    measured = evidence.get("measured")
    if measured:
        tp = measured["this_paper"]
        parts.append(
            f"<p class='note'>Measured: this paper {tp['measured_words']}"
            f" of {tp['stored_words']} words; "
            + "; ".join(
                f"{html.escape(p['paper'])} {p['measured_words']} of {p['stored_words']}"
                for p in measured["past_papers"]
            )
            + ".</p>"
        )
    for f in evidence["features"]:
        parts.append(
            f"<h2>{f['rank']}. {html.escape(f['name'])} ({_dir_words(f['direction'])})</h2>"
        )
        if f["description"]:
            parts.append(f"<p>{html.escape(f['description'])}</p>")
        eng = f["engine_scale"]
        parts.append(
            f"<p class='note'>0–1 scale: this paper {_fmt(eng['this_paper'])} · past-paper average "
            f"{_fmt(eng['past_papers_average'])}</p>"
        )
        if not f["locatable"]:
            parts.append(f"<p class='note'>Numbers only. {html.escape(f['note'])}</p>")
            continue
        left = (
            "".join(_html_quote(q) for q in f["this_paper"]["examples"])
            or "<p class='note'>None in this paper.</p>"
        )
        right = (
            "".join(_html_quote(q) for q in f["past_papers"]["examples"])
            or "<p class='note'>None in the past papers.</p>"
        )
        parts.append(
            f"<div class='cols'><div><h3>This paper</h3>{left}</div>"
            f"<div><h3>Past papers</h3>{right}</div></div>"
        )
    return "\n".join(parts) + "\n"
