"""Teacher-only descriptive facts about a paper's apparatus (``paper_profile``).

What this is
------------
A paper has parts that are not the writer's running prose: a title page or a
heading block (name, teacher, course, date, title), an abstract, section
headings, in-text citations, footnote markers, quotations, notes and a list
of sources. This module *describes* those parts in plain numbers for the
teacher (how many sources, a best guess at the citation style, how many
in-text citations, how many headings, ...).

Where each part is comes from ``features.matter.find_parts``, the same rules
that decide what is measured with the splitter on, so the description and the
measurement can never disagree about where the list of sources starts. With
the splitter on (``MATTER_SPLITTER_ENABLED``), ``parts`` also lists every part
with what happened to it: set aside or measured, by the rules or by the
teacher's own choice (``features.part_overrides``), its word count, its first
line (short) and its character range. A part the rules were unsure of is
``possible``: measured as prose and shown, so the teacher can decide.

What this is not
----------------
* It measures nothing the engine uses. ``features.preprocess``, the feature
  vector, every score and every stored value are unchanged: this module only
  reads the stored text, and nothing in the scoring path imports it.
* It is never shown to students. ``voice.STAFF_ONLY_KEYS`` names it, and the
  student projections drop it (``voice.drop_staff_only``).
* It is a description, not a check. The citation style is a best guess from
  the formatting, worded as one.
* Off unless ``PAPER_PROFILE_ENABLED`` is switched on (default off).

Every rule here is a plain pattern over lines of the stored text, so it is
deterministic and needs no language model. When a rule is unsure it reports
less (for example "no list of sources found"), never more.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from typing import Any

from .features import feature_flags as _ff
from .features import matter as _matter
from .features import part_overrides as _overrides
from .features import preprocess as _pp
from .features.matter import without_page_breaks

#: Values that switch PAPER_PROFILE_ENABLED on. Anything else (unset, "0", a typo)
#: leaves it off: a new staff field appears only when someone turns it on.
_ON_VALUES = frozenset({"1", "on", "true", "yes"})


def paper_profile_enabled() -> bool:
    """The paper profile on staff score responses: off unless PAPER_PROFILE_ENABLED=1."""
    return os.environ.get("PAPER_PROFILE_ENABLED", "0").strip().lower() in _ON_VALUES


PROFILE_NOTE = (
    "Descriptive only: what the paper's headings, citations, quotations and list of "
    "sources look like. None of it is part of the comparison or any score, and "
    "students never see it."
)
STYLE_CAVEAT = "A best guess from the formatting, not a check of the citations."

# ── Line patterns ────────────────────────────────────────────────────────────
# Where each part of the paper is comes from ``features.matter.find_parts``,
# the same rules that decide what is measured; the patterns below only name
# and describe what those rules found.

#: Names of a list of sources, for its label ("References", "Works Cited").
_LIST_NAMES = {
    "bibliography": "Bibliography",
    "selected bibliography": "Bibliography",
    "annotated bibliography": "Annotated Bibliography",
    "reference": "References",
    "references": "References",
    "reference list": "Reference List",
    "works cited": "Works Cited",
    "work cited": "Works Cited",
    "works cited page": "Works Cited",
    "works consulted": "Works Consulted",
    "sources cited": "Sources Cited",
    "sources consulted": "Sources Consulted",
    "literature cited": "Literature Cited",
    "notes": "Notes",
    "endnotes": "Endnotes",
}
#: Decoration around a heading: "## ", "**", "7. ", a trailing colon.
_HEADING_DECOR = re.compile(r"^[\s#*_]*(?:\d{1,2}\.?\s+)?|[\s*_:]*$")
#: The start of one entry in a list of sources.
_ENTRY_START = re.compile(
    r"^[ \t]*(?:"
    # Surname, First / Surname, F.
    r"[A-Z][A-Za-z'\u2019\-]+(?:\s[A-Z][A-Za-z'\u2019\-]+){0,2},\s+\S"
    r"|[A-Z][A-Za-z'\u2019\-]+\.\s+[A-Z]"  # Augustine. Confessions.
    r"|\d{1,3}\.\s+[A-Z]"  # 1. A numbered note
    r"|[\"\u201c][A-Z]"  # "Title." (no author)
    r")"
)
#: An appendix after the list of sources (measured again by the rules).
_APPENDIX = re.compile(r"^[\s#*_]*(?:appendix|appendices)\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")
_APA_ENTRY = re.compile(
    r"^[^()]{1,200}?\(\s*(?:1[5-9]\d\d|20\d\d)[a-z]?(?:,\s*[A-Za-z]+(?:\s\d{1,2})?)?\s*\)\."
)
_MLA_ENTRY = re.compile(r"^[A-Z][A-Za-z'\u2019\-]+,\s+[A-Z][a-z]+[^.]*\.\s.+(?:1[5-9]\d\d|20\d\d)")
_CHICAGO_PUB = re.compile(r"[A-Z][A-Za-z .]+:\s*[A-Z][^,()]{1,80},\s*(?:1[5-9]\d\d|20\d\d)")
_URL = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(?:com|org|edu|gov|net)\b", re.IGNORECASE)
_DOI = re.compile(r"\bdoi\b|doi\.org", re.IGNORECASE)
_JOURNAL = re.compile(
    r"\bvol\.|\bno\.\s*\d|\d+\s*\(\d+\)|\bjournal\b|\breview\b|\bquarterly\b|\bpp\.\s*\d",
    re.IGNORECASE,
)
_BOOK = re.compile(
    r"\bpress\b|\bpublish|\bbooks\b|\btranslated by\b|\btrans\.|\bedited by\b|\beds?\.|\beditor\b",
    re.IGNORECASE,
)

# ── In-text citation patterns ────────────────────────────────────────────────

#: A footnote marker: a number set right after a word or after a word's closing
#: punctuation ("know."1, "extension.2"), never a decimal such as ".31".
_FOOTNOTE_MARK = re.compile(
    r"(?:(?<=[a-z])|(?<=[a-z][.,;:!?\"\u201d\u2019)])|(?<=[a-z][.,;:!?][\"\u201d\u2019)]))"
    r"\^?\d{1,3}(?=[\s,.;:]|$)",
    re.MULTILINE,
)
_PAREN = re.compile(r"\(([^()\n]{1,160})\)")
_NAME = r"[A-Z][A-Za-z'\u2019\-]+"
_AUTHOR_YEAR = re.compile(
    rf"(?:{_NAME}|[A-Z]{{2,}})(?:\s+(?:and|&)\s+{_NAME}|\s+et\s+al\.?)?,?\s+(?:1[5-9]\d\d|20\d\d)[a-z]?\b"
)
_AUTHOR_YEAR_COMMA = re.compile(
    rf"(?:{_NAME}|[A-Z]{{2,}})(?:\s+(?:and|&)\s+{_NAME}|\s+et\s+al\.?)?,\s+(?:1[5-9]\d\d|20\d\d)[a-z]?\b"
)
_AUTHOR_PAGE = re.compile(
    rf"^{_NAME}(?:\s+(?:and|&)\s+{_NAME}|\s+et\s+al\.?)?\s+\d{{1,4}}(?:\s*[-\u2013]\s*\d{{1,4}})?$"
)
_PAGE_ONLY = re.compile(r"^(?:pp?\.\s*)?\d{1,4}(?:\s*[-\u2013]\s*\d{1,4})?$")


def _words(s: str) -> int:
    return len(s.split())


# ── Parts of the paper (features.matter.find_parts) ──────────────────────────

#: Plain names of the parts ``find_parts`` reports.
PART_LABELS = {
    "title_page": "Title page",
    "abstract": "Abstract",
    "back_matter": "List of sources",
    "notes": "Notes",
    "appendix": "Appendix",
    "front_matter": "Heading block",
    "heading": "Section headings",
    "page_header": "Running heads and page numbers",
    "footnote": "Footnotes",
    "chosen": "A part you chose",
}
#: Low-confidence kinds, each listed once with all its lines together.
_GROUPED = ("front_matter", "heading", "page_header", "footnote")
#: Longest first line shown for a part.
FIRST_LINE_CHARS = 60


def _first_line(text: str, start: int, end: int) -> str:
    for line in text[start:end].split("\n"):
        s = " ".join(line.split())  # a page marker is whitespace, so it goes too
        if len(s) > FIRST_LINE_CHARS:
            return s[: FIRST_LINE_CHARS - 1].rstrip() + "\u2026"
        if s:
            return s
    return ""


def _list_name(text: str, start: int, end: int) -> str | None:
    """The heading of a list of sources ("Works Cited"), or None when the list
    starts straight with an entry (an unheaded list)."""
    first = _first_line(text, start, end)
    if not first or _ENTRY_START.match(first) or _words(first) > 5:
        return None
    name = " ".join(_HEADING_DECOR.sub("", first).split())
    return _LIST_NAMES.get(name.lower(), name.title()) if name else None


def _span(ranges: Sequence[tuple[int, int]], within: Sequence[tuple[int, int]]) -> int:
    """Characters of ``ranges`` inside ``within`` (both sorted and merged)."""
    return sum(max(0, min(b, d) - max(a, c)) for a, b in ranges for c, d in within)


def _part(text: str, kind: str, ranges: list[tuple[int, int]], status: str, possible: bool):
    label = PART_LABELS.get(kind, kind.replace("_", " ").capitalize())
    if kind == "back_matter":
        named = _list_name(text, *ranges[0])
        label = named if named and named not in ("Notes", "Endnotes") else label
    return {
        "kind": kind,
        "label": label,
        "possible": possible,
        "rules_status": status,
        "status": status,
        "by": "rules",
        "words": sum(_words(text[a:b]) for a, b in ranges),
        "lines": sum(1 for a, b in ranges for ln in text[a:b].split("\n") if ln.strip()),
        "first_line": _first_line(text, *ranges[0]),
        "start": ranges[0][0],
        "end": ranges[-1][1],
        "ranges": [[a, b] for a, b in ranges],
    }


def _apply_choice(text: str, out: list[dict[str, Any]], found, choice) -> None:
    """Mark each part with what happens to it under the teacher's ``choice``:
    ``status`` is what happens to most of its text once the choice is applied,
    and ``by`` is "teacher" when the choice changed any of it. A range set
    aside that none of the parts covers is listed as a part of its own."""
    rules_aside = _overrides.union_ranges((r.start, r.end) for r in found.set_aside)
    aside = _overrides.minus_ranges(
        _overrides.union_ranges([*rules_aside, *choice.exclude]), choice.include
    )
    rules_kept = _overrides.minus_ranges([(0, len(text))], rules_aside)
    for part in out:
        ranges = [(a, b) for a, b in part["ranges"]]
        size = sum(b - a for a, b in ranges)
        part["status"] = "set_aside" if 2 * _span(ranges, aside) >= size else "measured"
        changed = _span(ranges, _overrides.minus_ranges(choice.exclude, rules_aside)) or _span(
            ranges, _overrides.minus_ranges(choice.include, rules_kept)
        )
        part["by"] = "teacher" if changed else "rules"
    for a, b in choice.exclude:
        if not text[a:b].split():  # only whitespace or page markers: nothing to show
            continue
        if not any(_span([(a, b)], p["ranges"]) for p in out):
            extra = _part(text, "chosen", [(a, b)], "measured", False)
            extra["status"], extra["by"] = "set_aside", "teacher"
            out.append(extra)


def paper_parts(text: str, parts: _matter.Parts | None = None) -> list[dict[str, Any]]:
    """Each part of the paper the rules found, in order, with what happens to it:
    ``status`` "set_aside" or "measured", ``by`` "rules" or "teacher" (a
    teacher's choice in force for this text, ``features.part_overrides``),
    ``possible`` for a shape the rules were unsure of (measured, so the teacher
    can decide). Word counts, the part's first line and its character ranges."""
    text = text or ""
    found = parts if parts is not None else _matter.find_parts(text)
    out: list[dict[str, Any]] = []
    grouped: dict[str, list[tuple[int, int]]] = {}
    for r in found.set_aside:
        if r.kind in _GROUPED:
            grouped.setdefault(r.kind, []).append((r.start, r.end))
        else:
            out.append(_part(text, r.kind, [(r.start, r.end)], "set_aside", False))
    for kind, ranges in grouped.items():
        out.append(_part(text, kind, ranges, "set_aside", False))
    for r in found.possible:
        out.append(_part(text, r.kind, [(r.start, r.end)], "measured", True))
    # An appendix after the list of sources: measured again by the rules.
    for r in found.set_aside:
        if r.kind == "back_matter" and r.end < len(text) and text[r.end :].strip():
            if _APPENDIX.match(_first_line(text, r.end, len(text))):
                out.append(_part(text, "appendix", [(r.end, len(text))], "measured", False))
    choice = _overrides.for_text(text)
    if choice is not None:
        _apply_choice(text, out, found, choice)
    out.sort(key=lambda p: (p["start"], p["end"]))
    return out


def _in_text(body: str) -> dict[str, int]:
    """Parenthetical citations in the body, by shape. Each pair of brackets
    counts once (``(Walker, 2017; Stickgold, 2013)`` is one place, two works)."""
    counts = {"author_year": 0, "author_year_comma": 0, "author_page": 0, "page_only": 0}
    for m in _PAREN.finditer(body):
        inner = m.group(1).strip()
        if _AUTHOR_YEAR.search(inner):
            counts["author_year"] += 1
            if _AUTHOR_YEAR_COMMA.search(inner):
                counts["author_year_comma"] += 1
        elif _AUTHOR_PAGE.match(inner):
            counts["author_page"] += 1
        elif _PAGE_ONLY.match(inner):
            counts["page_only"] += 1
    return counts


def _kind(entry: str) -> str:
    if _DOI.search(entry) or _JOURNAL.search(entry):
        return "journal or periodical"
    if _URL.search(entry):
        return "web page"
    if _BOOK.search(entry) or _CHICAGO_PUB.search(entry):
        return "book"
    return "other"


_STYLE_WORDS = {
    "MLA": "MLA",
    "APA": "APA",
    "Chicago notes": "Chicago (footnotes or endnotes)",
    "Chicago author-date": "Chicago (author-date)",
}


def _style(
    list_name: str | None,
    entries: Sequence[str],
    cites: dict[str, int],
    footnotes: int,
    note_lines: int,
) -> dict[str, Any]:
    """A best guess at the citation style, with the plain signs it rests on."""
    score = dict.fromkeys(_STYLE_WORDS, 0.0)
    signs: dict[str, list[str]] = {k: [] for k in _STYLE_WORDS}

    def add(style: str, points: float, sign: str) -> None:
        score[style] += points
        signs[style].append(sign)

    if list_name == "Works Cited":
        add("MLA", 2, "the list of sources is headed \u201cWorks Cited\u201d")
    elif list_name in ("References", "Reference List"):
        add("APA", 1.5, "the list of sources is headed \u201cReferences\u201d")
    elif list_name == "Bibliography":
        add("Chicago notes", 1, "the list of sources is headed \u201cBibliography\u201d")
    n = len(entries)
    if n:
        apa = sum(1 for e in entries if _APA_ENTRY.match(e))
        mla = sum(1 for e in entries if _MLA_ENTRY.match(e) and not _APA_ENTRY.match(e))
        chi = sum(1 for e in entries if _CHICAGO_PUB.search(e))
        if apa / n >= 0.5:
            add("APA", 2, "entries put the year in brackets after the authors")
        if chi / n >= 0.5:
            add("Chicago notes", 1, "entries give the city and publisher before the year")
            add("Chicago author-date", 0.5, "entries give the city and publisher")
        if mla / n >= 0.5 and chi / n < 0.5:
            add("MLA", 1, "entries start with the author's full name and end with the year")
    if cites["author_page"] + cites["page_only"] >= 2:
        add("MLA", 2, "in-text citations give the author and a page number")
    if cites["author_year_comma"] >= 2:
        add("APA", 2, "in-text citations give the author and the year, with a comma")
    elif cites["author_year"] - cites["author_year_comma"] >= 2:
        add("Chicago author-date", 2, "in-text citations give the author and the year")
    if footnotes >= 2:
        add("Chicago notes", 2, "the text uses numbered footnote markers")
    if note_lines >= 2:
        add("Chicago notes", 1, "numbered notes appear in the text")

    ranked = sorted(score.items(), key=lambda kv: (-kv[1], list(_STYLE_WORDS).index(kv[0])))
    (best, top), (_, second) = ranked[0], ranked[1]
    if top == 0:
        return {
            "guess": None,
            "words": "No citations found to guess a style from.",
            "signs": [],
            "caveat": STYLE_CAVEAT,
        }
    if top < 2 or top - second < 1:
        return {
            "guess": "unclear",
            "words": "Best guess: unclear. The citations do not clearly follow one style.",
            "signs": signs[best],
            "caveat": STYLE_CAVEAT,
        }
    return {
        "guess": best,
        "words": f"Best guess: {_STYLE_WORDS[best]} style.",
        "signs": signs[best],
        "caveat": STYLE_CAVEAT,
    }


def _outside(text: str, cut: Sequence[tuple[int, int]]) -> str:
    """``text`` without the ``cut`` ranges (sorted, as find_parts gives them)."""
    out, pos = [], 0
    for a, b in sorted(cut):
        if a > pos:
            out.append(text[pos:a])
        pos = max(pos, b)
    out.append(text[pos:])
    return without_page_breaks("".join(out))


def paper_profile(text: str) -> dict[str, Any]:
    """Plain descriptive facts about one paper's headings, citations, quotations
    and list of sources, read from where ``features.matter`` finds each part.
    Deterministic; reads ``text`` only. With the splitter on
    (MATTER_SPLITTER_ENABLED) it also lists the parts (``parts``): what was set
    aside and what was measured, so a teacher can check it."""
    raw = text or ""
    found = _matter.find_parts(raw)
    by_kind: dict[str, list[tuple[int, int]]] = {}
    for r in found.set_aside:
        by_kind.setdefault(r.kind, []).append((r.start, r.end))
    sources = by_kind.get("back_matter", [])
    list_name = _list_name(raw, *sources[0]) if sources else None
    entries: list[str] = []
    for a, b in sources:
        lines = [ln.strip() for ln in raw[a:b].split("\n") if ln.strip()]
        if lines and list_name is not None:
            lines = lines[1:]  # the heading
        for s in lines:
            if _ENTRY_START.match(s) or not entries:
                entries.append(s)
            else:
                entries[-1] += " " + s  # a wrapped line of the entry before
    notes = by_kind.get("footnote", []) + by_kind.get("notes", [])
    note_lines = sum(
        1 for a, b in notes for ln in raw[a:b].split("\n") if re.match(r"^\s*\d{1,3}\.?\s", ln)
    )
    front = by_kind.get("title_page", []) + by_kind.get("front_matter", [])

    # The body: everything but the list of sources and the notes. The running
    # text: the body without anything else set aside either (the heading block,
    # headings, page lines), so a note's "(Oxford: ..., 1991)" is not an
    # in-text citation.
    body = _outside(raw, sources + by_kind.get("notes", []))
    running = _outside(raw, [(r.start, r.end) for r in found.set_aside])

    data = _pp._extract_citation_data(body)
    cites = _in_text(running)
    footnotes = len(_FOOTNOTE_MARK.findall(running))
    in_text = cites["author_year"] + cites["author_page"] + cites["page_only"]
    body_words = _words(running)

    years = sorted(int(m.group(1)) for e in entries for m in [_YEAR.search(e)] if m)
    kinds: dict[str, int] = {}
    for e in entries:
        k = _kind(e)
        kinds[k] = kinds.get(k, 0) + 1

    profile = {
        "words": _words(raw),
        "front_matter_words": sum(_words(raw[a:b]) for a, b in front),
        "headings": len(by_kind.get("heading", [])),
        "sources": {
            "count": len(entries),
            "list_heading": list_name,
            "earliest_year": years[0] if years else None,
            "latest_year": years[-1] if years else None,
            "kinds": dict(sorted(kinds.items())),
        },
        "in_text_citations": {
            "count": in_text,
            "per_100_words": round(in_text / body_words * 100, 2) if body_words else 0.0,
        },
        "footnote_markers": footnotes,
        "quotes": {
            "short_quotes": data.short_quote_count,
            "block_quote_words": data.block_quote_word_count,
        },
        "citation_style": _style(list_name, entries, cites, footnotes, note_lines),
    }
    if _ff.matter_splitter_enabled():
        profile["parts"] = paper_parts(raw, found)
        # The teacher's choice in force for this paper, as the next request
        # would send it (the parts' buttons change it one part at a time).
        choice = _overrides.for_text(raw)
        profile["choice"] = (
            choice.to_doc() if choice is not None else {"exclude_ranges": [], "include_ranges": []}
        )
    return profile


def build_paper_profiles(text: str, baselines: Sequence[tuple[str, str]]) -> dict[str, Any]:
    """This paper's profile beside each past paper's, for the staff pages."""
    return {
        "note": PROFILE_NOTE,
        "this_paper": paper_profile(text),
        "past_papers": [{"paper": label, **paper_profile(t)} for label, t in baselines],
    }
