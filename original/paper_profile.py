"""Teacher-only descriptive facts about a paper's apparatus (``paper_profile``).

What this is
------------
A paper has parts that are not the writer's running prose: a heading block
(name, teacher, course, date, title), section headings, in-text citations,
footnote markers, quotations and a list of sources. This module *describes*
those parts in plain numbers for the teacher (how many sources, a best guess
at the citation style, how many in-text citations, how many headings, ...).

What this is not
----------------
* It measures nothing the engine uses. ``features.preprocess``, the feature
  vector, every score and every stored value are unchanged: this module only
  reads the stored text and the preprocess module's existing patterns, and
  nothing in the scoring path imports it.
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

#: A line that names a list of sources, read tolerantly (centred with spaces,
#: a trailing colon, "Works Cited Page"). Only trusted when what follows it
#: looks like a list of sources (see ``_source_list``).
_LIST_HEADING = re.compile(
    r"^[ \t]*(?:bibliography|references?|works?\s+cited(?:\s+page)?|works?\s+consulted"
    r"|sources?\s+(?:cited|consulted)|selected\s+bibliography|annotated\s+bibliography"
    r"|(?:end)?notes)[ \t]*:?[ \t]*$",
    re.IGNORECASE,
)
_LIST_NAMES = {
    "bibliography": "Bibliography",
    "reference": "References",
    "references": "References",
    "notes": "Notes",
    "endnotes": "Endnotes",
}
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

#: A heading-block line: a date, a course code or a teacher's title.
_DATE = re.compile(
    r"\b(?:\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4}"
    r"|(?:january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)
_HEADER_SIGNAL = re.compile(
    r"^\s*(?:prof(?:essor)?\.?\s|dr\.\s|mr\.\s|mrs\.\s|ms\.\s|rev\.\s|instructor\b"
    r"|[A-Z]{2,5}\s?-?\d{3,4}[A-Z]?\b)",
)
_PAGE_LINE = re.compile(r"^\s*(?:[A-Z][a-z]+\s+)?(?:page\s+)?\d{1,3}\s*$", re.IGNORECASE)
_SECTION_NAMES = frozenset(
    {
        "abstract", "introduction", "method", "methods", "methodology", "participants",
        "results", "discussion", "conclusion", "conclusions", "background",
        "literature review", "analysis", "summary",
    }
)  # fmt: skip
_SMALL_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "in",
        "on",
        "and",
        "or",
        "for",
        "to",
        "with",
        "at",
        "by",
        "from",
        "as",
        "vs",
    }
)
_SENTENCE_END = (".", "?", "!", '"', "\u201d", ")", "'", "\u2019")

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


def _title_like(line: str) -> bool:
    words = re.findall(r"[A-Za-z][\w'\u2019\-]*", line)
    return bool(words) and all(w[0].isupper() or w.lower() in _SMALL_WORDS for w in words)


def _heading_like(line: str) -> bool:
    s = line.strip()
    if not s or _words(s) > 10 or s.endswith((*_SENTENCE_END, ";", ",", ":")):
        return False
    return s.lower() in _SECTION_NAMES or _title_like(s)


# ── Parts of the paper ───────────────────────────────────────────────────────


def _source_list(lines: list[str]) -> tuple[int | None, str | None]:
    """(index of the heading line, its name) of a list of sources, or (None, None).

    Trusted only when the heading sits after the first 40% of the paper's lines
    and most lines after it start like an entry, so a sentence that begins
    "References to God..." or a one-word paragraph "Notes" mid-paper is not a
    list. The last such heading wins (a notes list followed by a bibliography
    is still one apparatus, counted from the first trusted heading)."""
    filled = [i for i, line in enumerate(lines) if line.strip()]
    for k, i in enumerate(filled):
        if not _LIST_HEADING.match(lines[i]) or k < 0.4 * len(filled):
            continue
        rest = [lines[j] for j in filled[k + 1 :] if not _LIST_HEADING.match(lines[j])]
        if not rest:
            continue
        starts = sum(1 for r in rest if _ENTRY_START.match(r) and _YEAR.search(r))
        if starts and starts / len(rest) >= 0.5:
            name = re.sub(r"\s+", " ", lines[i].strip().rstrip(":").strip())
            return i, _LIST_NAMES.get(name.lower(), name.title())
    return None, None


def _entries(lines: list[str]) -> list[str]:
    """Entries of a list of sources: an entry starts on a line that begins like
    one; any other line continues the entry before it (a wrapped PDF line)."""
    out: list[str] = []
    for line in lines:
        s = line.strip()
        if not s or _LIST_HEADING.match(s):
            continue
        if _ENTRY_START.match(s) or not out:
            out.append(s)
        else:
            out[-1] += " " + s
    return out


def _front_matter(lines: list[str], stop: int) -> list[int]:
    """Indices of the heading block at the top: short lines with no sentence
    ending (name, teacher, course, date, title) before the first line of prose.

    Counted only when the block carries a date, a course code or a teacher's
    title; otherwise only a lone title-like first line counts. A short line
    whose next line starts in lower case is the first line of a wrapped
    paragraph, so the block stops there."""
    run: list[int] = []
    filled = [i for i in range(stop) if lines[i].strip()]
    for pos, i in enumerate(filled):
        s = lines[i].strip()
        signal = bool(_DATE.search(s) or _HEADER_SIGNAL.match(s))
        nxt = lines[filled[pos + 1]].strip() if pos + 1 < len(filled) else ""
        if _words(s) > 14 or (s.endswith((*_SENTENCE_END, ";", ",", ":")) and not signal):
            break
        if not signal and not _title_like(s):
            break  # a line of ordinary prose (lower-case words), e.g. a wrapped first line
        if nxt[:1].islower():
            break
        run.append(i)
    if any(_DATE.search(lines[i]) or _HEADER_SIGNAL.match(lines[i].strip()) for i in run):
        return run
    return run[:1] if run and _heading_like(lines[run[0]]) else []


def _headings(lines: list[str], start: int, stop: int) -> int:
    """Section headings in the body: a short title-like line that stands on its
    own (blank lines around it, or, in hard-wrapped text, after a finished
    sentence and before a capital)."""
    count = 0
    for i in range(start, stop):
        s = lines[i]
        if not s.strip() or s.startswith(("    ", "\t")) or _PAGE_LINE.match(s):
            continue
        if not _heading_like(s):
            continue
        prev = lines[i - 1].strip() if i > 0 else ""
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if (not prev and not nxt) or (
            (not prev or prev.endswith(_SENTENCE_END)) and nxt[:1].isupper()
        ):
            count += 1
    return count


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
    elif list_name == "References":
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


_NOTE_LINE = re.compile(r"^[ \t]*\d{1,3}\.?\s+[A-Z][^\n]*?(?:\(\s*[^()]*:\s*[^()]*\d{4}\)|Ibid)")


def paper_profile(text: str) -> dict[str, Any]:
    """Plain descriptive facts about one paper's headings, citations, quotations
    and list of sources. Deterministic; reads ``text`` only."""
    text = without_page_breaks(text or "")  # an upload's page breaks, as before
    lines = text.split("\n")
    list_at, list_name = _source_list(lines)
    body_stop = list_at if list_at is not None else len(lines)
    body_lines = lines[:body_stop]
    body = "\n".join(body_lines)
    entries = _entries(lines[list_at + 1 :]) if list_at is not None else []

    front = _front_matter(lines, body_stop)
    first_body = (front[-1] + 1) if front else 0
    headings = _headings(lines, first_body, body_stop)
    note_lines = sum(1 for line in body_lines if _NOTE_LINE.match(line))
    # The running text: no heading block and no footnote text, so a note's
    # "(Oxford: Oxford University Press, 1991)" is not an in-text citation.
    skip = set(front)
    running = "\n".join(
        line for i, line in enumerate(body_lines) if i not in skip and not _NOTE_LINE.match(line)
    )

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

    return {
        "words": _words(text),
        "front_matter_words": sum(_words(lines[i]) for i in front),
        "headings": headings,
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


def build_paper_profiles(text: str, baselines: Sequence[tuple[str, str]]) -> dict[str, Any]:
    """This paper's profile beside each past paper's, for the staff pages."""
    return {
        "note": PROFILE_NOTE,
        "this_paper": paper_profile(text),
        "past_papers": [{"paper": label, **paper_profile(t)} for label, t in baselines],
    }
