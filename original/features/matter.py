"""Front and back matter: the parts of a paper that are not running prose
(``MATTER_SPLITTER_ENABLED``; off by default).

What it finds
-------------
``find_matter(text)`` returns character ranges of whole lines in the stored
text, each with a kind:

``back_matter``
    A list of sources (Works Cited, References, Bibliography, numbered Notes)
    from its heading to the end of the paper. The heading is read tolerantly
    ("Works Cited:", centred, "Works Cited Page") but trusted only after the
    first 40% of the paper and when most lines after it start like entries
    and carry a year. Markdown, numbering and emphasis around the heading are
    ignored ("## References", "7. References", "**Works Cited**").
    "Notes"/"Endnotes" also need numbered lines; notes without years are
    trusted only when every line is a short numbered line pointing somewhere
    (a page, "Ibid.", "See", "Cf."). So a
    one-word paragraph "Notes", or a sentence starting "References to ...",
    no longer cuts off the rest of the paper (it did under the old rule).
``cover_letter``
    A note to the teacher at the very start or the very end of the paper: a
    salutation line of at most six words ending in "," or ":" ("Dear Professor
    Hartley,", "To whom it may concern:"; not "Dear friends," or another
    general audience) and, after it, a closing line ("Sincerely,", "Best
    regards,") followed by at most three short signature lines. All of these
    are required: the letter sits before the paper's first line of prose (the
    short lines above its salutation, a name or an address, go with it) or
    after its last; it says what it accompanies ("paper", "essay",
    "assignment", "attached" and the like), so a letter that is itself the
    assignment stays prose; and it is at most 200 words and 35% of the paper.
    Otherwise it stays prose. It is never compared with the student's past
    papers (there is no record of their letters to compare it with).
``front_matter``
    The heading block at the top (name, teacher, course, date, title), only
    when it carries a date, a course code or a teacher's title; otherwise only
    a lone title line.
``heading``
    A short title-like line standing on its own between paragraphs.
``page_header``
    A running head or page number line ("Grant 2", "Page 3", "4").
``footnote``
    A numbered note line with a citation shape ("1. Augustine, Confessions
    (Oxford: ..., 1991), 230." or "2. Ibid., 232.").

Rules when unsure
-----------------
Anything not clearly matter stays prose. If the headings, heading block, page
lines and footnotes together take more than 15% of the words before the list
of sources, that is logged; above 30% none of them is set aside (the paper is
unusual; keeping the prose is the safe failure) and a warning is logged. A list of sources longer
than 20% of the paper is still set aside (it passed the entry check) but
logged.

``features.preprocess`` measures only the text outside these ranges when the
switch is on, and ``evidence.engine_view`` uses the same ranges, so quoted
evidence always comes from what was measured.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: Setting aside more than this share of the body's words as low-confidence
#: parts is logged.
LOG_SOFT_SHARE = 0.15
#: Above this share the low-confidence parts are kept as prose (and logged).
MAX_SOFT_SHARE = 0.30
#: A list of sources longer than this share of the paper is logged.
LOG_BACK_SHARE = 0.20
#: A "Notes" section without years is trusted only when every line is a short
#: numbered reference line of at most this many words.
NOTE_MAX_WORDS = 40
#: A letter longer than this share of the paper's words is kept as prose.
LETTER_MAX_SHARE = 0.35
#: ... or longer than this many words: a cover note, not an essay.
LETTER_MAX_WORDS = 200
#: Short lines allowed after a letter's closing (name, course, email).
LETTER_SIGNATURE_LINES = 3

_LIST_HEADING = re.compile(
    r"^[ \t]*(?:bibliography|references?|works?\s+cited(?:\s+page)?|works?\s+consulted"
    r"|works?\s+referenced|sources?\s+(?:cited|consulted)|selected\s+bibliography"
    r"|annotated\s+bibliography|further\s+reading|(?:end)?notes)[ \t]*:?[ \t]*$",
    re.IGNORECASE,
)
_NOTES_HEADING = re.compile(r"^[ \t]*(?:end)?notes[ \t]*:?[ \t]*$", re.IGNORECASE)
_ENTRY_START = re.compile(
    r"^[ \t]*(?:"
    r"[A-Z][A-Za-z'\u2019\-]+(?:\s[A-Z][A-Za-z'\u2019\-]+){0,2},\s+\S"  # Surname, First
    r"|[A-Z][A-Za-z'\u2019\-]+\.\s+[A-Z]"  # Augustine. Confessions.
    r"|\d{1,3}\.\s+[A-Z]"  # 1. A numbered note
    r"|[\"\u201c][A-Z]"  # "Title." (no author)
    r")"
)
# Decoration around a heading: a markdown "#" run, a number or Roman numeral
# ("7.", "IV)"), and emphasis ("**", "__", "*", "_") on either side.
_HEADING_DECOR = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*)?(?:(?:\d{1,2}|[IVXLC]{1,6})[.)][ \t]+)?[*_]{0,2}[ \t]*"
)
_HEADING_TAIL = re.compile(r"[ \t]*[*_]{0,2}[ \t]*(:?)[ \t]*$")
_SALUTATION = re.compile(
    r"^[ \t]*(?:dear[ \t]+(?!(?:my[ \t]+)?(?:friends|brothers|sisters|brethren|church"
    r"|congregation|everyone|all|readers|colleagues|family|beloved)\b)\S[^\n,:]{0,50}"
    r"|to[ \t]+whom[ \t]+it[ \t]+may[ \t]+concern)[ \t]*[,:][ \t]*$",
    re.IGNORECASE,
)
# A cover note says what it accompanies.
_SUBMISSION_WORD = re.compile(
    r"\b(?:paper|essay|assignment|draft|submission|submit(?:ted|ting)?|attached|enclosed"
    r"|course|class|thesis|project)\b",
    re.IGNORECASE,
)
# A note line that points somewhere: a page or number after the note number,
# or a reference word.
_NOTE_REFERENCE = re.compile(r"^\s*\d{1,3}\.?\s+(?:.*\d|(?:ibid|see|cf)\b)", re.IGNORECASE)
_CLOSING = re.compile(
    r"^[ \t]*(?:(?:yours[ \t]+)?sincerely(?:[ \t]+yours)?|respectfully(?:[ \t]+yours)?"
    r"|(?:with[ \t]+)?(?:best|kind|warm(?:est)?)[ \t]+(?:regards|wishes)|regards"
    r"|yours[ \t]+(?:truly|faithfully)|(?:with[ \t]+)?(?:many[ \t]+)?thanks|thank[ \t]+you"
    r"|gratefully|cordially|best)[ \t]*[,.!]?[ \t]*$",
    re.IGNORECASE,
)
_NUMBERED = re.compile(r"^[ \t]*\d{1,3}\.?\s+\S")
_YEAR = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")
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
    r"(?:,?\s*(?:pp?\.\s*)?\d[\d\-\u2013, ]*)?)\.?\s*$"
)
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
_SENTENCE_END = (".", "?", "!", '"', "\u201d", ")", "'", "\u2019")

SOFT_KINDS = frozenset({"front_matter", "heading", "page_header", "footnote"})


@dataclass(frozen=True)
class MatterRange:
    start: int  # stored-text offset of the line's first character
    end: int  # offset just past the line's newline (or the end of the text)
    kind: str


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


def _undecorated(line: str) -> str:
    """The heading's own words without markdown, numbering or emphasis."""
    core = _HEADING_DECOR.sub("", line, count=1)
    return _HEADING_TAIL.sub(r"\1", core)


def _is_list_heading(line: str) -> bool:
    return bool(_LIST_HEADING.match(line) or _LIST_HEADING.match(_undecorated(line)))


def _is_notes_heading(line: str) -> bool:
    return bool(_NOTES_HEADING.match(line) or _NOTES_HEADING.match(_undecorated(line)))


def _lines(text: str) -> list[tuple[int, int, str]]:
    """(start, end including newline, line text without newline)."""
    out, pos = [], 0
    for chunk in text.splitlines(keepends=True):
        out.append((pos, pos + len(chunk), chunk.rstrip("\r\n")))
        pos += len(chunk)
    return out


def _back_matter(lines: list[str]) -> int | None:
    """Line index where a verified list of sources starts, or None."""
    filled = [i for i, line in enumerate(lines) if line.strip()]
    total = sum(_words(lines[i]) for i in filled) or 1
    before = 0
    for k, i in enumerate(filled):
        # Position counts words, not lines: a docx paragraph is one long line,
        # so a long list after a few paragraphs sits late in the paper's words
        # even when it starts early in its lines.
        at = before / total
        before += _words(lines[i])
        if not _is_list_heading(lines[i]) or at < 0.4:
            continue
        rest = [lines[j] for j in filled[k + 1 :] if not _is_list_heading(lines[j])]
        if not rest:
            continue
        if _is_notes_heading(lines[i]):
            # The notes run to the next list heading (a bibliography often
            # follows them), not to the end of the paper.
            section = []
            for j in filled[k + 1 :]:
                if _is_list_heading(lines[j]):
                    break
                section.append(lines[j])
            numbered = sum(1 for r in section if _NUMBERED.match(r))
            if not section or numbered / len(section) < 0.5:
                continue
            # Notes rarely carry a year ("1. See Berlin 131 ..."). Without one,
            # trust the section only when every line is a short numbered line
            # that points somewhere, so a student's own numbered points, or
            # prose after the notes, stay prose.
            if all(_NOTE_REFERENCE.match(r) and _words(r) <= NOTE_MAX_WORDS for r in section):
                return i
        starts = sum(1 for r in rest if _ENTRY_START.match(r) and _YEAR.search(r))
        if starts and starts / len(rest) >= 0.5:
            return i
    return None


def _front_matter(lines: list[str], stop: int, start: int = 0) -> list[int]:
    run: list[int] = []
    filled = [i for i in range(start, stop) if lines[i].strip()]
    for pos, i in enumerate(filled):
        s = lines[i].strip()
        signal = bool(_DATE.search(s) or _HEADER_SIGNAL.match(s))
        nxt = lines[filled[pos + 1]].strip() if pos + 1 < len(filled) else ""
        ends = s.endswith((*_SENTENCE_END, ";", ",", ":"))
        # A short date line may end with a full stop; a dated sentence may not.
        if _words(s) > 14 or (ends and (not signal or _words(s) > 6)):
            break
        if not signal and not _title_like(s):
            break
        if nxt[:1].islower() or not nxt:
            break
        run.append(i)
    if any(_DATE.search(lines[i]) or _HEADER_SIGNAL.match(lines[i].strip()) for i in run):
        return run
    return run[:1] if run and _heading_like(lines[run[0]]) else []


def _is_salutation(line: str) -> bool:
    return bool(_SALUTATION.match(line)) and _words(line) <= 6


def _letter_end(lines: list[str], filled: list[int], s: int) -> int | None:
    """Position in ``filled`` of a letter's last line, given its salutation at
    ``filled[s]``: the first closing line after it plus up to
    LETTER_SIGNATURE_LINES short lines straight after it (no blank line
    between) that do not read as prose."""
    for c in range(s + 1, len(filled)):
        if _CLOSING.match(lines[filled[c]]):
            end = c
            for j in range(c + 1, min(c + 1 + LETTER_SIGNATURE_LINES, len(filled))):
                sig = lines[filled[j]].strip()
                adjacent = filled[j] == filled[j - 1] + 1  # a blank line ends the signature
                if not adjacent or _words(sig) > 6 or sig.endswith((".", "?", "!", ";")):
                    break
                end = j
            return end
    return None


def _cover_letter(lines: list[str], stop: int) -> list[int]:
    """Line indices of a letter at the start or end of the paper (see module
    notes), or [] when there is none or it is not clearly one."""
    filled = [i for i in range(stop) if lines[i].strip()]
    total = sum(_words(lines[i]) for i in filled) or 1
    found: list[int] = []
    # At the start: only short lines (a date, an address) before the salutation.
    for s, i in enumerate(filled[:6]):
        if _is_salutation(lines[i]):
            end = _letter_end(lines, filled, s)
            if end is not None and end + 1 < len(filled):
                # The short lines above the salutation (a name, an address, a
                # date) belong to the letter.
                found = filled[: end + 1]
            break
        if _words(lines[i]) > 10:
            break
    # At the end: the salutation after the paper's midpoint and nothing but the
    # signature after the closing.
    if not found:
        for s in range(len(filled) - 1, len(filled) // 2 - 1, -1):
            if _is_salutation(lines[filled[s]]):
                end = _letter_end(lines, filled, s)
                if end == len(filled) - 1:
                    found = filled[s:]
                break
    if not found:
        return []
    if not any(_SUBMISSION_WORD.search(lines[i]) for i in found):
        return []  # a letter that is the student's writing, not a note about it
    words = sum(_words(lines[i]) for i in found)
    if words / total > LETTER_MAX_SHARE or words > LETTER_MAX_WORDS:
        log.info(
            "matter: a letter of %d of %d words is over %.0f%% of the paper or %d words; "
            "kept as prose",
            words,
            total,
            LETTER_MAX_SHARE * 100,
            LETTER_MAX_WORDS,
        )
        return []
    log.info("matter: setting aside a cover letter of %d words", words)
    return found


def _is_heading(lines: list[str], i: int) -> bool:
    s = lines[i]
    if not s.strip() or s.startswith(("    ", "\t")) or not _heading_like(s):
        return False
    prev = lines[i - 1].strip() if i > 0 else ""
    nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
    if not nxt:
        nxt2 = next((ln.strip() for ln in lines[i + 2 :] if ln.strip()), "")
        return not prev and bool(nxt2)  # a paragraph follows somewhere
    return (not prev or prev.endswith(_SENTENCE_END)) and nxt[:1].isupper() and bool(prev or i == 0)


def find_matter(text: str) -> list[MatterRange]:
    """Line ranges of front and back matter in ``text`` (see module notes)."""
    spans = _lines(text)
    lines = [s for _, _, s in spans]
    if not lines:
        return []
    back = _back_matter(lines)
    stop = back if back is not None else len(lines)
    kinds: dict[int, str] = {}
    letter = _cover_letter(lines, stop)
    for i in letter:
        kinds[i] = "cover_letter"
    # A letter at the start is followed by the heading block, if any.
    leading = bool(letter) and letter[0] < stop // 2
    front_start = letter[-1] + 1 if leading else 0
    for i in _front_matter(lines, stop, front_start):
        kinds[i] = "front_matter"
    for i in range(stop):
        if i in kinds or not lines[i].strip():
            continue
        if _PAGE_LINE.match(lines[i]):
            kinds[i] = "page_header"
        elif _FOOTNOTE_LINE.match(lines[i]):
            kinds[i] = "footnote"
        elif _is_heading(lines, i):
            kinds[i] = "heading"

    body_words = sum(_words(lines[i]) for i in range(stop) if i not in letter) or 1
    soft_words = sum(_words(lines[i]) for i, k in kinds.items() if k in SOFT_KINDS)
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
        kinds = {i: k for i, k in kinds.items() if k not in SOFT_KINDS}

    out = [MatterRange(spans[i][0], spans[i][1], kinds[i]) for i in sorted(kinds)]
    if back is not None:
        total = sum(_words(ln) for ln in lines) or 1
        back_words = sum(_words(ln) for ln in lines[back:])
        if back_words / total > LOG_BACK_SHARE:
            log.info(
                "matter: list of sources is %d of %d words (over %.0f%%)",
                back_words,
                total,
                LOG_BACK_SHARE * 100,
            )
        out.append(MatterRange(spans[back][0], len(text), "back_matter"))
    return out


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
