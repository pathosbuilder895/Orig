"""Front and back matter: the parts of a paper that are not running prose
(``MATTER_SPLITTER_ENABLED``; off by default).

What it finds
-------------
``find_matter(text)`` returns character ranges of whole lines in the stored
text, each with a kind. ``find_parts(text)`` returns the same ranges plus the
``possible`` parts: shapes that look like a part but did not pass its checks.
Those are measured as prose (when unsure, measure as prose) and are listed so a
teacher can see them and decide.

Page breaks: an uploaded .docx or .pdf carries them as ``PAGE_BREAK``
(``upload_utils``); pasted text has none. A form feed is never measured
(``features.preprocess`` drops it), but it is the strongest evidence of where a
title page ends and a list of sources starts.

Verified parts (set aside whatever their size):

``title_page``
    Everything before the first page break, when that page is short (under
    ``TITLE_PAGE_MAX_WORDS``), holds no sentence-like paragraph (an "Author
    Note" and its paragraph excepted) and carries a title-page signal (a date
    or term, a course code, a teacher's title, an institution, "Running
    head:", "Submitted to", "In partial fulfillment", "by", ...).
``abstract``
    An "Abstract" heading (plain or decorated, or "Abstract:" opening its
    paragraph) in the first 25% of the words, with its paragraph(s) up to a
    clear end within ``ABSTRACT_MAX_WORDS`` words: the next heading, a page
    break, or a "Keywords:" line (set aside too). With no clear end it is
    only ``possible``.
``back_matter``
    A list of sources (Works Cited, References, Reference List, Literature
    Cited, Bibliography, Annotated Bibliography, numbered Notes) from its
    heading to the end of the paper, or to an "Appendix" heading, after which
    the paper is measured again. The heading is read tolerantly ("Works
    Cited:", centred, "Works Cited Page", "## References", "7. References",
    "**Works Cited**"; not for "Notes"). It is trusted at or after 40% of the
    paper's words, or earlier when a page break stands right before it or
    the rest of the paper is overwhelmingly entries; and only when at least
    half of the entries after it start like an entry and carry a year, a URL
    or DOI, or "n.d.". Entries are counted whole: a line that does not start
    like an entry after a line that does not end one is the same entry
    wrapped (a PDF's hard-wrapped lines count once). A list with no heading
    is set aside only when the paper's final block is at least
    ``UNHEADED_MIN_ENTRIES`` entries, every one entry-shaped and short, in
    alphabetical order, after half the paper; a weaker final list is
    ``possible``.
``notes``
    Endnotes under a plain "Notes"/"Endnotes" heading (late in the paper or
    after a page break) when every line is a note numbered 1, 2, 3, ... and at
    least two, and at least half, carry a citation shape (a year in brackets,
    a full note citation, "Ibid."): the short notes among them ("4. Edwards,
    Strong Rod, 72.") go with them. And, in a paper with page breaks, a block
    of footnotes at the foot of a page: lines from the next note number in
    the paper to the page break, each number continuing the count and printed
    as a marker in the prose above.

Low-confidence parts (soft; capped, see below):

``front_matter``
    The heading block at the top (name, teacher, course, date, title, an
    APA title page in pasted text), only when it carries a date or term, a
    course code, a teacher's title or another title-page signal; otherwise
    only a lone title line. It stops at the first line that reads as a
    sentence (an "Author Note" paragraph excepted).
``heading``
    A short title-like line standing on its own between paragraphs.
``page_header``
    A running head or page number line ("Grant 2", "Page 3", "4"), or, in a
    paper with page breaks, a first or last line of a page that repeats
    (digits ignored) on most pages.
``footnote``
    A numbered note line with a citation shape ("1. Augustine, Confessions
    (Oxford: ..., 1991), 230." or "2. Ibid., 232."). Only a page may follow
    the citation, and a numbered biblical book ("1 Peter 2:9 ...") is never a
    note number, so a numbered paragraph that cites a book and goes on stays
    prose.

Not detected, so measured as prose: a cover letter to the teacher, and notes
that carry no year outside a verified notes block. Rules for both kept
setting real student writing aside (letter assignments, a sermon's closing
prayer, numbered points citing scripture), so they wait for a teacher's own
"set this part aside" control.

Rules when unsure
-----------------
Anything not clearly matter stays prose. If the soft parts together take more
than 15% of the words outside the verified parts, that is logged; above 30%
none of them is set aside (the paper is unusual; keeping the prose is the
safe failure), they are listed as ``possible``, and a warning is logged. A
list of sources longer than 20% of the paper is still set aside (it passed
the entry check) but logged.

``features.preprocess`` measures only the text outside the set-aside ranges
when the switch is on, and ``evidence.engine_view`` uses the same ranges, so
quoted evidence always comes from what was measured.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: How an uploaded paper's page break is stored (``upload_utils``): a form
#: feed on a line of its own, where a blank line ``"\n\n"`` stood before.
PAGE_BREAK = "\n\f\n"
#: The form feed of a stored page break. ``features.preprocess`` drops it
#: before anything is measured (and ``evidence.engine_view`` mirrors that), so
#: a paper with page breaks measures exactly as the same paper without them.
LONE_FORM_FEED = re.compile(r"(?<=\n)\f(?=\n)")


def without_page_breaks(text: str) -> str:
    """``text`` as it was stored before page breaks were kept."""
    return LONE_FORM_FEED.sub("", text) if "\f" in text else text


#: Setting aside more than this share of the body's words as low-confidence
#: parts is logged.
LOG_SOFT_SHARE = 0.15
#: Above this share the low-confidence parts are kept as prose (and logged).
MAX_SOFT_SHARE = 0.30
#: A list of sources longer than this share of the paper is logged.
LOG_BACK_SHARE = 0.20
#: A first page longer than this is not a title page.
TITLE_PAGE_MAX_WORDS = 120
#: An abstract must reach a clear end within this many words.
ABSTRACT_MAX_WORDS = 350
#: An abstract heading must sit in this first share of the paper's words.
ABSTRACT_WITHIN = 0.25
#: A footnote longer than this is read as prose.
NOTE_MAX_WORDS = 100
#: A list of sources with no heading needs at least this many entries.
UNHEADED_MIN_ENTRIES = 5

_LIST_HEADING = re.compile(
    r"^[ \t]*(?:bibliography|references?|works?\s+cited(?:\s+page)?|works?\s+consulted"
    r"|works?\s+referenced|sources?\s+(?:cited|consulted)|selected\s+bibliography"
    r"|annotated\s+bibliography|further\s+reading|reference\s+list|literature\s+cited"
    r"|references\s+cited|(?:end)?notes)[ \t]*:?[ \t]*$",
    re.IGNORECASE,
)
_NOTES_HEADING = re.compile(r"^[ \t]*(?:end)?notes[ \t]*:?[ \t]*$", re.IGNORECASE)
_APPENDIX_HEADING = re.compile(
    r"^(?:appendix(?:[ \t]+(?:[A-Z]|[IVX]{1,4}|\d{1,2}))?(?:[ \t]*[.:–-][ \t]*\S.{0,80})?"
    r"|appendices)$",
    re.IGNORECASE,
)
_ENTRY_START = re.compile(
    r"^[ \t]*(?:"
    r"[A-Z][A-Za-z'’\-]+(?:\s[A-Z][A-Za-z'’\-]+){0,2},\s+\S"  # Surname, First
    r"|[A-Z][A-Za-z'’\-]+\.\s+[A-Z]"  # Augustine. Confessions.
    # A body as author: "Center for Historical Reading. Guide ..."
    r"|[A-Z][A-Za-z'\u2019\-]+(?:\s(?:[A-Z][A-Za-z'\u2019\-]+|of|for|and|the|on|in|at)){1,5}"
    r"(?<!\sof)(?<!\sfor)(?<!\sand)(?<!\sthe)(?<!\son)(?<!\sin)(?<!\sat)\.\s+[\"\u201cA-Z(]"
    r"|\d{1,3}\.\s+[A-Z]"  # 1. A numbered note
    r"|[\"“][A-Z]"  # "Title." (no author)
    r")"
)
# Where an entry may end: a full stop (or one inside closing quotes or
# brackets), or a URL / DOI.
_ENTRY_END = re.compile(r"[.!?][\"'”’)\]]*$|(?:https?://|doi:|www\.)\S+$", re.I)
_URL = re.compile(r"(?:https?://|\bdoi:|\bwww\.)\S+", re.IGNORECASE)
_ND = re.compile(r"\(?\bn\.\s?d\.", re.IGNORECASE)
# Decoration around a heading: a markdown "#" run, a number or Roman numeral
# ("7.", "IV)"), and emphasis ("**", "__", "*", "_") on either side.
_HEADING_DECOR = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*)?(?:(?:\d{1,2}|[IVXLC]{1,6})[.)][ \t]+)?[*_]{0,2}[ \t]*"
)
_HEADING_TAIL = re.compile(r"[ \t]*[*_]{0,2}[ \t]*(:?)[ \t]*$")
_NUMBERED = re.compile(r"^[ \t]*\d{1,3}\.?\s+\S")
_NOTE_NUMBER = re.compile(r"^[ \t]*(\d{1,3})\.?\s+\S")
#: A footnote's first line: its number, then a capital, a quote or a bracket.
NOTE_START = re.compile(r"^\s*(\d{1,3})\.?\s+([A-Z\"“‘'_(\[])")
_YEAR = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")
_MONTHS = (
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
)  # fmt: skip
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
# Title-page lines a heading block can carry beyond a date, a course code or
# a teacher's title. Each is matched on a whole short line.
_TITLE_PAGE_SIGNAL = re.compile(
    r"^\s*(?:running\s+head\s*:"
    r"|author(?:'s)?\s+note\s*$"
    r"|(?:a\s+)?(?:paper|thesis|essay|dissertation|project)?\s*(?:submitted|presented)\s+to\b"
    r"|in\s+partial\s+fulfil{1,2}ment\b"
    r"|by\s*$"
    r"|(?:spring|summer|fall|autumn|winter)\s+(?:term\s+|semester\s+|quarter\s+)?\d{4}\s*$"
    r"|(?:january|february|march|april|may|june|july|august|september|october|november"
    r"|december)\s+\d{4}\s*$"
    r"|\d{1,2}[/.-]\d{1,2}[/.-](?:\d{4}|\d{2})\s*$"
    r"|\d{4}-\d{2}-\d{2}\s*$"
    r"|.*\b(?:university|college|seminary|institute|academy|school\s+of|department\s+of)\b"
    r")",
    re.IGNORECASE,
)
_AUTHOR_NOTE = re.compile(r"^\s*author(?:'s)?\s+note\s*$", re.IGNORECASE)
_ABSTRACT_INLINE = re.compile(r"^\s*(?:[*_]{1,2})?abstract(?:[*_]{1,2})?\s*:\s*\S", re.I)
_KEYWORDS = re.compile(
    r"^\s*(?:[*_]{1,2})?(?:key\s*words|index\s+terms)(?:[*_]{1,2})?\s*[:.]", re.IGNORECASE
)
_PAGE_LINE = re.compile(r"^\s*(?:[A-Z][a-z]+\s+)?(?:page\s+)?\d{1,3}\s*$", re.IGNORECASE)
# A numbered note line: "1. Augustine, Confessions (Oxford: ..., 1991), 230."
# or "2. Ibid., 232.". Only a page reference may follow the citation, so a
# numbered paragraph that goes on after a citation stays prose, and a numbered
# biblical book ("1 Peter 2:9 ...", "2 Corinthians") is never a note number.
_BIBLE_NUMBERED_BOOKS = (
    r"(?:samuel|sam|kings|kgs|chronicles|chron|chr|corinthians|cor|thessalonians|thess"
    r"|timothy|tim|peter|pet|john|jn|maccabees|macc|esdras|esd)\b"
)
_FOOTNOTE_LINE = re.compile(
    r"^\s*\d{1,3}\.?\s+(?!(?i:" + _BIBLE_NUMBERED_BOOKS + r"))"
    r"(?:Ibid\b[^\n]{0,40}"
    r"|[A-Z][^\n]{0,250}?\([^()]*:[^()]*(?:1[5-9]\d\d|20\d\d)[^()]*\)"
    r"(?:,?\s*(?:pp?\.\s*)?\d[\d\-–, ]*)?)\.?\s*$"
)
# A year inside brackets with a comma before it in the note: "(2019): 119",
# "(New Haven: Yale, 2003)".
_NOTE_CITE = re.compile(r",[^()]*\([^()]*\b(?:1[5-9]\d\d|20\d\d)\b[^()]*\)")
_SECTION_NAMES = frozenset(
    {
        "abstract", "introduction", "method", "methods", "methodology", "participants",
        "results", "discussion", "conclusion", "conclusions", "background",
        "literature review", "analysis", "summary",
    }
)  # fmt: skip
_SMALL_WORDS = frozenset(
    {"a", "an", "the", "of", "in", "on", "and", "or", "for", "to", "with", "at", "by", "from"}
    | {"as", "vs"}
)
_SENTENCE_END = (".", "?", "!", '"', "”", ")", "'", "’")
_DIGITS = re.compile(r"\d+")

SOFT_KINDS = frozenset({"front_matter", "heading", "page_header", "footnote"})
HARD_KINDS = frozenset({"title_page", "abstract", "notes"})


@dataclass(frozen=True)
class MatterRange:
    start: int  # stored-text offset of the line's first character
    end: int  # offset just past the line's newline (or the end of the text)
    kind: str


@dataclass(frozen=True)
class Parts:
    """What ``find_parts`` found: the ranges set aside (``find_matter``) and
    the ``possible`` parts, measured as prose."""

    set_aside: list[MatterRange]
    possible: list[MatterRange]


def _words(s: str) -> int:
    return len(s.split())


def _title_like(line: str) -> bool:
    words = re.findall(r"[A-Za-z][\w'’\-]*", line)
    return bool(words) and all(w[0].isupper() or w.lower() in _SMALL_WORDS for w in words)


def _heading_like(line: str) -> bool:
    """A short line that reads as a heading: a section name, or up to 10
    title-case words (up to 14 when the line has a subtitle colon, as a
    paper's title often does)."""
    s = line.strip()
    if not s or s.endswith((*_SENTENCE_END, ";", ",", ":")):
        return False
    limit = 14 if ": " in s else 10
    if _words(s) > limit:
        return False
    return s.lower() in _SECTION_NAMES or _title_like(s)


def _undecorated(line: str) -> str:
    """The heading's own words without markdown, numbering or emphasis."""
    core = _HEADING_DECOR.sub("", line, count=1)
    return _HEADING_TAIL.sub(r"\1", core)


def _is_list_heading(line: str) -> bool:
    """A list-of-sources heading, plain or decorated. A decorated "Notes" is
    not one: notes need their own numbered-line check, and prose under a
    "## Notes" stays prose."""
    if _LIST_HEADING.match(line):
        return True
    core = _undecorated(line)
    return bool(_LIST_HEADING.match(core)) and not _NOTES_HEADING.match(core)


def _is_appendix_heading(line: str) -> bool:
    core = _undecorated(line).strip().rstrip(":").strip()
    return bool(core) and _words(core) <= 12 and bool(_APPENDIX_HEADING.match(core))


def _signal(line: str) -> bool:
    s = line.strip()
    return bool(_DATE.search(s) or _HEADER_SIGNAL.match(s) or _TITLE_PAGE_SIGNAL.match(s))


def _lines(text: str) -> list[tuple[int, int, str]]:
    """(start, end including newline, line text without newline). A form feed
    is a line boundary only together with a newline: ``"\\f"`` on its own line,
    or opening a line ("\\fFirst words", as pdftotext writes a page)."""
    out: list[tuple[int, int, str]] = []
    pos = 0
    carry = ""
    for chunk in text.splitlines(keepends=True):
        if chunk.endswith("\f") and not chunk.endswith(("\n\f", "\r\f")):
            carry += chunk  # rejoin what splitlines cut at a form feed
            continue
        chunk = carry + chunk
        carry = ""
        out.append((pos, pos + len(chunk), chunk.rstrip("\r\n")))
        pos += len(chunk)
    if carry:
        out.append((pos, pos + len(carry), carry))
    return out


def _entries(lines: list[str], idx: list[int]) -> list[list[str]]:
    """Group the non-blank lines ``idx`` into entries. A line continues the
    entry above it when nothing blank separates them and the line above does
    not end an entry, or when it is only a URL or DOI."""
    groups: list[list[str]] = []
    last = -2
    for j in idx:
        s = lines[j].strip()
        if groups and (_URL.fullmatch(s) or (j == last + 1 and _continues(groups[-1][-1], s))):
            groups[-1].append(s)
        else:
            groups.append([s])
        last = j
    return groups


def _continues(prev: str, line: str) -> bool:
    """Is ``line`` the wrapped rest of the entry ending ``prev``? Not when
    ``prev`` ends an entry, and never for a numbered or quoted start, which
    always opens an entry of its own."""
    if _ENTRY_END.search(prev.strip()):
        return False
    return not re.match(r"[ \t]*(?:\d{1,3}\.?\s|[\"\u201c])", line)


def _dated(entry: str) -> bool:
    return bool(_YEAR.search(entry) or _URL.search(entry) or _ND.search(entry))


def _entry_shaped(group: list[str]) -> bool:
    return bool(_ENTRY_START.match(group[0])) and _dated(" ".join(group))


def _strict_entry(group: list[str]) -> bool:
    """An entry for the unheaded rule: entry-shaped, short, and at least two
    full stops (author. title. publisher), not a sentence of prose."""
    text = " ".join(group)
    return _entry_shaped(group) and _words(text) <= 70 and text.count(". ") + 1 >= 2


def _sort_key(group: list[str]) -> str:
    s = group[0].lstrip(" \t\"“'").lower()
    return re.sub(r"^(?:the|a|an)\s+", "", s)


@dataclass
class _Doc:
    text: str
    spans: list[tuple[int, int, str]]
    lines: list[str]  # line text, form feeds removed
    brk: list[bool]  # a page break between the previous non-blank line and this one
    filled: list[int]
    wpos: list[int]  # words before each line
    total: int
    has_breaks: bool


def _doc(text: str) -> _Doc:
    spans = _lines(text)
    lines = [s.replace("\f", "") for _, _, s in spans]
    brk, pending = [], False
    for _, _, raw in spans:
        if "\f" in raw:
            pending = True
        if raw.replace("\f", "").strip():
            brk.append(pending)
            pending = False
        else:
            brk.append(False)
    wpos, n = [], 0
    for line in lines:
        wpos.append(n)
        n += _words(line)
    wpos.append(n)
    filled = [i for i, line in enumerate(lines) if line.strip()]
    first = filled[0] if filled else 0
    if filled:
        brk[first] = False  # a page break before the first words breaks nothing
    return _Doc(text, spans, lines, brk, filled, wpos, n, "\f" in text)


def _back_matter(d: _Doc) -> tuple[tuple[int, int] | None, list[tuple[int, int]]]:
    """((first line, end line) of a verified list of sources, or None), and
    the candidates that did not pass (possible)."""
    lines, filled, n = d.lines, d.filled, len(d.lines)
    possible: list[tuple[int, int]] = []
    for k, i in enumerate(filled):
        if not _is_list_heading(lines[i]):
            continue
        end = next(
            (j for j in filled[k + 1 :] if _is_appendix_heading(lines[j])),
            n,
        )
        # Decoration is read only on the heading being judged. The lines after
        # it are counted as #354 counts them, so a later decorated heading can
        # never leave the count and let its list vouch for prose above it.
        rest_idx = [j for j in filled[k + 1 :] if j < end and not _LIST_HEADING.match(lines[j])]
        if not rest_idx:
            continue
        rest = [lines[j] for j in rest_idx]
        if _NOTES_HEADING.match(lines[i]):
            numbered = sum(1 for r in rest if _NUMBERED.match(r))
            if numbered / len(rest) < 0.5:
                continue
        groups = _entries(lines, rest_idx)
        shaped = sum(1 for g in groups if _entry_shaped(g))
        share = shaped / len(groups)
        late = d.wpos[i] >= 0.4 * d.total
        early = d.brk[i] or (share >= 0.8 and len(groups) >= 3)
        if shaped and share >= 0.5 and (late or early):
            return (i, end), possible
        if shaped:
            possible.append((i, end))
    return None, possible


def _unheaded_list(d: _Doc) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    """A list of sources with no heading: the paper's final entries. Returns
    (verified range, possible range)."""
    lines, filled = d.lines, d.filled
    if len(filled) < 4:
        return None, None
    groups_idx: list[list[int]] = []
    last = -2
    for j in filled:
        s = lines[j].strip()
        cont = groups_idx and (
            (j == last + 1 and _continues(lines[groups_idx[-1][-1]], s)) or _URL.fullmatch(s)
        )
        if cont:
            groups_idx[-1].append(j)
        else:
            groups_idx.append([j])
        last = j
    run: list[list[int]] = []
    for g in reversed(groups_idx):
        if not _strict_entry([lines[j].strip() for j in g]):
            break
        run.insert(0, g)
    if len(run) == len(groups_idx) or len(run) < 3:
        return None, None  # all entries (nothing to set aside from) or no list
    start, end = run[0][0], run[-1][-1] + 1
    keys = [_sort_key([lines[j] for j in g]) for g in run]
    ordered = sum(1 for a, b in zip(keys, keys[1:], strict=False) if a <= b)
    sorted_ok = ordered >= 0.8 * (len(keys) - 1)
    late = d.wpos[start] >= 0.5 * d.total
    if len(run) >= UNHEADED_MIN_ENTRIES and sorted_ok and late:
        return (start, end), None
    return None, (start, end)


def _paragraphs(d: _Doc, lo: int, hi: int) -> list[list[int]]:
    """Non-blank line runs (blank line or page break between) in [lo, hi)."""
    out: list[list[int]] = []
    for i in range(lo, hi):
        if not d.lines[i].strip():
            continue
        if out and out[-1][-1] == i - 1 and not d.brk[i]:
            out[-1].append(i)
        else:
            out.append([i])
    return out


def _sentence_like(text: str) -> bool:
    s = text.strip()
    ends = len(re.findall(r"[a-z0-9,)][.?!](?:\s|$)", s))
    return _words(s) >= 15 and (ends >= 2 or s.endswith((".", "?", "!")))


def _title_page(d: _Doc) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    """The first page, when the paper has a page break and that page reads
    as a title page. (verified range, possible range)."""
    if not d.has_breaks or not d.filled:
        return None, None
    first_break = next((i for i in d.filled if d.brk[i]), None)
    if first_break is None:
        return None, None
    page = [i for i in d.filled if i < first_break]
    words = sum(_words(d.lines[i]) for i in page)
    if not page or words >= TITLE_PAGE_MAX_WORDS * 2:
        return None, None
    excused: set[int] = set()
    for k, i in enumerate(page):
        if _AUTHOR_NOTE.match(d.lines[i]):
            excused.update(page[k + 1 :])  # the note runs to the page's end
            break
    counted = [i for i in page if i not in excused]
    sentences = any(
        _sentence_like(" ".join(d.lines[j] for j in par))
        for par in _paragraphs(d, page[0], first_break)
        if not any(j in excused for j in par)
    )
    counted_words = sum(_words(d.lines[i]) for i in counted)
    rng = (page[0], page[-1] + 1)
    if sentences or counted_words >= TITLE_PAGE_MAX_WORDS:
        return None, (rng if not sentences else None)
    if any(_signal(d.lines[i]) for i in page):
        return rng, None
    return None, rng


def _front_matter(lines: list[str], stop: int) -> list[int]:
    run: list[int] = []
    filled = [i for i in range(stop) if lines[i].strip()]
    note_words = -1  # >= 0 inside an "Author Note" paragraph
    for pos, i in enumerate(filled):
        s = lines[i].strip()
        sig = _signal(s)
        nxt = lines[filled[pos + 1]].strip() if pos + 1 < len(filled) else ""
        if note_words >= 0:
            if (_title_like(s) and _words(s) <= 10) or note_words + _words(s) > 150:
                note_words = -1  # the note ended: judge this line as usual
            else:
                note_words += _words(s)
                run.append(i)
                if not nxt:
                    break
                continue
        ends = s.endswith((*_SENTENCE_END, ";", ",", ":"))
        # A short date line may end with a full stop; a dated sentence may not.
        if _words(s) > 14 or (ends and (not sig or _words(s) > 6)):
            break
        if not sig and not _title_like(s):
            break
        if not nxt or (nxt[:1].islower() and not _signal(nxt)):
            break
        run.append(i)
        if _AUTHOR_NOTE.match(s):
            note_words = 0
    if any(_signal(lines[i]) for i in run):
        return run
    return run[:1] if run and _heading_like(lines[run[0]]) else []


def _abstract(d: _Doc, taken: set[int]) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    """(verified range, possible range) of an abstract."""
    lines = d.lines
    for k, i in enumerate(d.filled):
        if d.wpos[i] > ABSTRACT_WITHIN * d.total:
            break
        if i in taken:
            continue
        core = _undecorated(lines[i]).strip().rstrip(":").strip().lower()
        inline = bool(_ABSTRACT_INLINE.match(lines[i]))
        if core != "abstract" and not inline:
            continue
        words = _words(lines[i]) if inline else 0
        last = i
        clear = False
        for j in d.filled[k + 1 :]:
            s = lines[j].strip()
            if _KEYWORDS.match(s) and not d.brk[j]:
                last, clear = j, words > 0
                break
            if j in taken or d.brk[j] or _is_list_heading(s) or _heading_like(s):
                clear = words > 0
                break
            words += _words(s)
            if words > ABSTRACT_MAX_WORDS:
                break
            last = j
        else:
            clear = False  # the paper ended inside it: it is the paper
        rng = (i, last + 1)
        if words < 30 or d.wpos[last + 1] > 0.4 * d.total:
            return None, (rng if words else None)
        if clear:
            return rng, None
        return None, rng
    return None, None


def has_note_marker(number: int, text: str) -> bool:
    """A note number printed right after a word or punctuation (a superscript
    run into the text), e.g. "him?6 We", "xi.2 3."."""
    pat = r"(?<=[A-Za-z.,;:!?\"'”’)\]_])" + str(number) + r"(?!\d)"
    return re.search(pat, text) is not None


def _note_strong(line: str) -> bool:
    return bool(_FOOTNOTE_LINE.match(line) or _NOTE_CITE.search(line))


def _notes_section(d: _Doc, stop: int, taken: set[int]) -> tuple[list[int], list[tuple]]:
    """Endnotes under a plain Notes heading: (lines, possible ranges)."""
    lines = d.lines
    possible: list[tuple] = []
    for k, i in enumerate(d.filled):
        if i >= stop or i in taken or not _NOTES_HEADING.match(lines[i]):
            continue
        if d.wpos[i] < 0.4 * d.total and not d.brk[i]:
            continue
        section: list[int] = []
        for j in d.filled[k + 1 :]:
            if j >= stop or j in taken or _is_list_heading(lines[j]):
                break
            if _is_appendix_heading(lines[j]):
                break
            section.append(j)
        if len(section) < 2:
            continue
        nums = [_NOTE_NUMBER.match(lines[j]) for j in section]
        consecutive = all(m and int(m.group(1)) == n for n, m in enumerate(nums, 1))
        strong = sum(1 for j in section if _note_strong(lines[j]))
        rng = (i, section[-1] + 1)
        if consecutive and strong >= 2 and 2 * strong >= len(section):
            return [i, *section], possible
        if consecutive and strong:
            possible.append(rng)
    return [], possible


def _page_bottom_notes(d: _Doc, stop: int, taken: set[int]) -> list[int]:
    """Footnote blocks at the foot of a page (a paper with page breaks)."""
    if not d.has_breaks:
        return []
    pages: list[list[int]] = [[]]
    for i in d.filled:
        if i >= stop:
            break
        if d.brk[i] and pages[-1]:
            pages.append([])
        pages[-1].append(i)
    out: list[int] = []
    expected = 1
    for page in pages:
        foot = [i for i in page if i not in taken]
        while foot and _PAGE_LINE.match(d.lines[foot[-1]]):
            foot.pop()  # a page number under the notes (raw PDF text)
        for s_pos, s in enumerate(foot):
            m = NOTE_START.match(d.lines[s])
            if not m or int(m.group(1)) != expected:
                continue
            before = d.text[: d.spans[s][0]]
            if not has_note_marker(expected, before):
                continue
            if s_pos == 0:
                continue  # a footnote block sits under some of the page's prose
            k, run, ok, note_words = expected - 1, [], True, 0
            for j in foot[s_pos:]:
                mm = NOTE_START.match(d.lines[j])
                if mm and int(mm.group(1)) == k + 1 and has_note_marker(k + 1, before):
                    k, note_words = k + 1, 0
                elif not run:
                    ok = False
                    break
                note_words += _words(d.lines[j])
                if note_words > NOTE_MAX_WORDS:
                    ok = False  # a paragraph of prose, not a note
                    break
                run.append(j)
            if ok:
                out.extend(run)
                expected = k + 1
                break
    return out


def _repeating_page_lines(d: _Doc, stop: int) -> set[int]:
    """First or last line of a page that repeats, digits ignored, on most
    pages (a running head or page number in text extracted from a PDF)."""
    if not d.has_breaks:
        return set()
    pages: list[list[int]] = [[]]
    for i in d.filled:
        if i >= stop:
            break
        if d.brk[i] and pages[-1]:
            pages.append([])
        pages[-1].append(i)
    if len(pages) < 2:
        return set()

    def key(i: int) -> str:
        return " ".join(_DIGITS.sub("#", d.lines[i]).lower().split())

    edges = [(p[0], p[-1]) for p in pages if p]
    counts = Counter(key(i) for pair in edges for i in set(pair))
    out = set()
    for pair in edges:
        for i in set(pair):
            k = key(i)
            if _words(k) <= 12 and counts[k] >= 2 and 2 * counts[k] > len(pages):
                out.add(i)
    return out


def _is_heading(lines: list[str], i: int, after_part: bool = False) -> bool:
    s = lines[i]
    if not s.strip() or s.startswith(("    ", "\t")) or not _heading_like(s):
        return False
    prev = lines[i - 1].strip() if i > 0 else ""
    nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
    if not nxt:
        nxt2 = next((ln.strip() for ln in lines[i + 2 :] if ln.strip()), "")
        return not prev and bool(nxt2)  # a paragraph follows somewhere
    starts = nxt[:1].isupper() or nxt[:1].isdigit() or nxt[:1] in "\"“‘'_("
    boundary = not prev or prev.endswith(_SENTENCE_END) or after_part
    return boundary and starts and bool(prev or i == 0)


def _block(spans: list[tuple[int, int, str]], lo: int, hi: int, kind: str) -> MatterRange:
    return MatterRange(spans[lo][0], spans[hi - 1][1], kind)


def find_parts(text: str) -> Parts:
    """Set-aside and possible parts of ``text`` (see module notes)."""
    d = _doc(text)
    lines, spans, n = d.lines, d.spans, len(d.lines)
    if not d.filled:
        return Parts([], [])
    possible: list[tuple[int, int, str]] = []

    back, back_possible = _back_matter(d)
    possible += [(a, b, "back_matter") for a, b in back_possible]
    if back is None:
        back, maybe = _unheaded_list(d)
        if maybe:
            possible.append((*maybe, "back_matter"))
    stop = back[0] if back else n
    tail = range(back[1], n) if back else range(0)  # an appendix after the list

    hard: dict[int, str] = {}
    title, maybe = _title_page(d)
    if maybe:
        possible.append((*maybe, "title_page"))
    if title and title[1] <= stop:
        for i in range(*title):
            hard[i] = "title_page"
    abstract, maybe = _abstract(d, set(hard))
    if maybe:
        possible.append((*maybe, "abstract"))
    if abstract and abstract[1] <= stop:
        for i in range(*abstract):
            hard[i] = "abstract"
    notes, maybe_notes = _notes_section(d, stop, set(hard))
    possible += [(a, b, "notes") for a, b in maybe_notes]
    for i in notes:
        hard[i] = "notes"
    for i in _page_bottom_notes(d, stop, set(hard)):
        hard[i] = "notes"

    kinds: dict[int, str] = {}
    if "title_page" not in hard.values():
        for i in _front_matter(lines, stop):
            if i not in hard:
                kinds[i] = "front_matter"
    repeating = _repeating_page_lines(d, stop)
    for i in [*range(stop), *tail]:
        if i in kinds or i in hard or not lines[i].strip():
            continue
        if i in repeating or _PAGE_LINE.match(lines[i]):
            kinds[i] = "page_header"
        elif _FOOTNOTE_LINE.match(lines[i]):
            kinds[i] = "footnote"
        elif _is_heading(lines, i, after_part=(i - 1) in hard):
            kinds[i] = "heading"

    body_lines = [i for i in [*range(stop), *tail] if i not in hard]
    body_words = sum(_words(lines[i]) for i in body_lines) or 1
    soft_words = sum(_words(lines[i]) for i in kinds)
    if LOG_SOFT_SHARE < soft_words / body_words <= MAX_SOFT_SHARE:
        log.info(
            "matter: setting aside %d of %d body words as headings/heading block/page "
            "lines/footnotes (over %.0f%%)",
            soft_words,
            body_words,
            LOG_SOFT_SHARE * 100,
        )
    elif soft_words / body_words > MAX_SOFT_SHARE:
        log.warning(
            "matter: headings/heading block/page lines/footnotes would set aside %d of %d "
            "words (over %.0f%%); keeping them as prose",
            soft_words,
            body_words,
            MAX_SOFT_SHARE * 100,
        )
        possible += [(i, i + 1, k) for i, k in sorted(kinds.items())]
        kinds = {}

    out: list[MatterRange] = []
    for i in sorted(kinds):
        out.append(MatterRange(spans[i][0], spans[i][1], kinds[i]))
    # Verified parts: one range per run of consecutive lines of a kind
    # (blank lines inside a run belong to it).
    order = sorted(hard)
    k = 0
    while k < len(order):
        lo = order[k]
        hi = lo + 1
        while (
            k + 1 < len(order)
            and hard[order[k + 1]] == hard[lo]
            and all(not lines[j].strip() for j in range(hi, order[k + 1]))
        ):
            k += 1
            hi = order[k] + 1
        out.append(_block(spans, lo, hi, hard[lo]))
        k += 1
    if back is not None:
        total = d.total or 1
        back_words = d.wpos[back[1]] - d.wpos[back[0]]
        if back_words / total > LOG_BACK_SHARE:
            log.info(
                "matter: list of sources is %d of %d words (over %.0f%%)",
                back_words,
                total,
                LOG_BACK_SHARE * 100,
            )
        end = len(text) if back[1] >= n else spans[back[1]][0]
        out.append(MatterRange(spans[back[0]][0], end, "back_matter"))
    out.sort(key=lambda r: r.start)
    # A possible part is listed unless it is already set aside: it touches a
    # verified part, or every line of it is set aside as a soft part.
    hard_spans = [(r.start, r.end) for r in out if r.kind not in SOFT_KINDS]
    maybe_out = []
    for a, b, kind in possible:
        r = _block(spans, a, b, kind)
        if any(s < r.end and r.start < e for s, e in hard_spans):
            continue
        if all(i in kinds or not lines[i].strip() for i in range(a, b)):
            continue
        maybe_out.append(r)
    return Parts(out, sorted(set(maybe_out), key=lambda r: (r.start, r.end)))


def find_matter(text: str) -> list[MatterRange]:
    """Line ranges of front and back matter in ``text`` (see module notes)."""
    return find_parts(text).set_aside


def kept_ranges(text: str) -> list[tuple[int, int]]:
    """Stored-text ranges outside the matter, in order (the measured body)."""
    out, pos = [], 0
    for r in find_matter(text):
        if r.start > pos:
            out.append((pos, r.start))
        pos = max(pos, r.end)
    if pos < len(text):
        out.append((pos, len(text)))
    return out
