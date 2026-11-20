"""
upload_utils.py: the one text extractor for uploaded papers (PDF, DOCX, TXT).

Canonical home of the extractor; lives at the package root so every caller can
import it without the v1 package chain: the live app's upload routes
(``routers/students.py``, ``routers/students_baseline.py``,
``routers/past_papers.py``), ``canvas/live_import.py``, and the dormant v1 app
through the re-export shim at ``api/v1/upload_utils.py``.

Page structure
--------------
A page break is stored as ``features.matter.PAGE_BREAK`` (``"\\n\\f\\n"``) in
place of the blank line ``"\\n\\n"`` that used to stand there, so the splitter
(``features/matter.py``) can see where a title page ends and where a list of
sources starts. Before anything is measured, ``features.preprocess`` drops a
form feed that stands alone between two newlines, so a paper extracted here
measures byte for byte what it measured before page breaks were kept
(``tests/test_upload_structure.py``).

``.docx``
    Paragraph text exactly as before (python-docx ``Paragraph.text``, blank
    paragraphs dropped, a blank line between paragraphs). A page break is
    emitted where the file has one: ``w:br w:type="page"``, a paragraph set to
    start on a new page (``w:pageBreakBefore``, direct or from its style), a
    ``w:lastRenderedPageBreak`` before a paragraph's first text, and a section
    break that starts a new page. Headers, footers and footnotes stay out, as
    before: they are not the student's prose in the body.
``.pdf``
    Switch off (the default): the pages as pypdf reads them, joined by a page
    break. Switch on (``MATTER_SPLITTER_ENABLED``): the pages are also
    restructured (``_structure_pdf``): a first or last line that repeats on
    most pages (running head, page number; digits ignored) is removed, lines
    hard-wrapped inside a paragraph are joined again, paragraphs are separated
    by a blank line, and a block of numbered footnotes at a page's foot is
    moved below the paragraph it interrupted, as its own block just before
    the page break, so the splitter can set it aside. The restructuring
    changes the text, so it would change measurements with the switch off;
    that is why it runs only with the switch on.
``.txt``
    Decoded as UTF-8, unchanged. Pasted text never comes through here.

All extractors return a plain unicode string or raise ``ValueError`` with a
human-readable reason (``ExtractorUnavailableError``, a subclass, when the library
is not installed) so callers can attach it to per-file error reports.
"""

from __future__ import annotations

import io
import re
from collections import Counter

from .features import feature_flags as _ff
from .features.matter import NOTE_MAX_WORDS, NOTE_START, PAGE_BREAK, has_note_marker

ACCEPTED = ".txt, .pdf, .docx"


class ExtractorUnavailableError(ValueError):
    """The library that reads this file type is not installed."""

    def __init__(self, package: str, pip_spec: str):
        self.package = package
        super().__init__(f"{package} is not installed; run: pip install {pip_spec}")


def extract_text_from_bytes(raw: bytes, filename: str, *, structure: bool | None = None) -> str:
    """
    Extract plain text from raw file bytes.

    Args:
        raw:       Raw bytes of the uploaded file.
        filename:  Original filename, used to determine the format by extension.
        structure: Restructure a PDF's pages (module notes). None (the default)
                   follows ``MATTER_SPLITTER_ENABLED``.

    Returns:
        Extracted plain text string (may be empty for blank PDFs).

    Raises:
        ValueError: If the file type is unsupported or extraction fails.
    """
    name_lower = filename.lower()

    if name_lower.endswith(".txt"):
        return raw.decode("utf-8", errors="replace")

    if name_lower.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ExtractorUnavailableError("pypdf", "pypdf>=4.0,<5.0") from None
        try:
            reader = PdfReader(io.BytesIO(raw))
            pages = [page.extract_text() or "" for page in reader.pages]
        except Exception as exc:
            raise ValueError(f"PDF extraction failed: {exc}") from exc
        if structure is None:
            structure = _ff.matter_splitter_enabled()
        return _structure_pdf(pages) if structure else PAGE_BREAK.join(pages)

    if name_lower.endswith(".docx"):
        try:
            from docx import Document
        except ImportError:
            raise ExtractorUnavailableError("python-docx", "python-docx>=1.1,<2.0") from None
        try:
            return _docx_text(Document(io.BytesIO(raw)))
        except Exception as exc:
            raise ValueError(f"DOCX extraction failed: {exc}") from exc

    ext = filename.rsplit(".", 1)[-1] if "." in filename else "unknown"
    raise ValueError(f"Unsupported file type '.{ext}'. Accepted formats: {ACCEPTED}")


def word_count(text: str) -> int:
    """Return word count for text."""
    return len(text.split())


# ── .docx ────────────────────────────────────────────────────────────────────

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NO_PAGE = frozenset({"continuous", "nextColumn"})
_OFF = frozenset({"0", "false", "off"})


def _w(tag: str) -> str:
    return f"{{{_W_NS}}}{tag}"


def _style_breaks_before(style) -> bool:
    seen = 0
    while style is not None and seen < 20:  # a base-style loop cannot hang us
        value = style.paragraph_format.page_break_before
        if value is not None:
            return bool(value)
        style, seen = style.base_style, seen + 1
    return False


def _paragraph_breaks(paragraph) -> tuple[bool, bool]:
    """(page break before the paragraph's text, page break after it)."""
    direct = paragraph.paragraph_format.page_break_before
    before = bool(direct) if direct is not None else _style_breaks_before(paragraph.style)
    after = False
    seen_text = False
    for el in paragraph._p.iter():
        if el.tag == _w("t"):
            seen_text = seen_text or bool((el.text or "").strip())
        elif el.tag == _w("br") and el.get(_w("type")) == "page":
            if seen_text:
                after = True
            else:
                before = True
        elif el.tag == _w("lastRenderedPageBreak") and not seen_text:
            before = True
    return before, after


def _section_types(body) -> list[str]:
    """Each section's start type, in document order (the body's last)."""
    out = []
    for sect in body.iter(_w("sectPr")):
        kind = sect.find(_w("type"))
        out.append(kind.get(_w("val")) if kind is not None else "nextPage")
    return out


def _docx_text(doc) -> str:
    """Paragraph text as before, with ``PAGE_BREAK`` where a page breaks."""
    sections = _section_types(doc.element.body)
    n_section = 0
    parts: list[tuple[str, bool]] = []
    pending = False
    for p in doc.paragraphs:
        before, after = _paragraph_breaks(p)
        ppr = p._p.pPr
        if ppr is not None and ppr.find(_w("sectPr")) is not None:
            n_section += 1
            nxt = sections[n_section] if n_section < len(sections) else "continuous"
            after = after or nxt not in _NO_PAGE
        pending = pending or before
        if p.text.strip():
            parts.append((p.text, pending and bool(parts)))
            pending = False
        pending = pending or after
    if not parts:
        return ""
    out = [parts[0][0]]
    for text, brk in parts[1:]:
        out.append(PAGE_BREAK if brk else "\n\n")
        out.append(text)
    return "".join(out)


# ── .pdf (switch on) ─────────────────────────────────────────────────────────

_DIGITS = re.compile(r"\d+")
# A sentence end, with any closing quote or bracket and a note number after it.
_SENT_END = re.compile(r"[.?!][\"'\u201d\u2019)\]]*\d{0,3}$|:$")


def _edge_key(line: str) -> str:
    return " ".join(_DIGITS.sub("#", line).lower().split())


def _drop_repeating_edges(pages: list[list[str]]) -> None:
    """Remove a first or last line that repeats (digits ignored) on most pages:
    the running head and the page number. Two passes, for a head and a number
    printed on separate lines."""
    n = sum(1 for lines in pages if any(s.strip() for s in lines))
    if n < 2:
        return
    for _ in range(2):
        for pick in (0, -1):
            edge: list[int | None] = []
            for lines in pages:
                idx = [i for i, s in enumerate(lines) if s.strip()]
                edge.append(idx[pick] if idx else None)
            keys = [
                _edge_key(lines[i]) if i is not None else None
                for lines, i in zip(pages, edge, strict=True)
            ]
            counts = Counter(k for k in keys if k and len(k.split()) <= 12)
            for lines, i, k in zip(pages, edge, keys, strict=True):
                if i is not None and k in counts and counts[k] >= 2 and 2 * counts[k] > n:
                    del lines[i]  # removed, not blanked: a blank line ends a paragraph


def _split_notes(lines: list[str], expected: int, before: str) -> tuple[list[str], list[str]]:
    """(body lines, footnote lines) for one page. A footnote block is a run of
    lines at the foot of the page that starts with the next note number in the
    paper, where every numbered line continues the count and each number is
    printed as a marker in the prose above it; anything else stays body."""
    body_text = before
    for s in range(len(lines)):
        if s:
            body_text += "\n" + lines[s - 1]
        m = NOTE_START.match(lines[s])
        if not s or not m or int(m.group(1)) != expected:
            continue  # a footnote block sits under some of the page's prose
        if not has_note_marker(expected, body_text):
            continue
        notes: list[list[str]] = []
        k = expected - 1
        ok = True
        for line in lines[s:]:
            if not line.strip():
                continue
            mm = NOTE_START.match(line)
            if mm and int(mm.group(1)) == k + 1 and has_note_marker(k + 1, body_text):
                k += 1
                notes.append([line])
            elif sum(len(x.split()) for x in notes[-1]) + len(line.split()) <= NOTE_MAX_WORDS:
                notes[-1].append(line)
            else:
                ok = False  # a paragraph of prose, not a note
                break
        if ok:
            joined = []
            for note in notes:
                text = note[0]
                for nxt in note[1:]:
                    text = _join(text, nxt)
                joined.append(text.strip())
            return lines[:s], joined
    return lines, []


def _join(a: str, b: str) -> str:
    """Join a wrapped line: no space after a hyphen at the line end
    ("1743-" + "1758") or inside a URL broken at a slash."""
    s = a.rstrip()
    if a == s and ((s.endswith("-") and not s.endswith(" -")) or (s.endswith("/") and "://" in s)):
        return s + b.strip()
    return s + " " + b.strip()


def _wraps(prev: str, nxt: str, measure: float, across: bool = False) -> bool:
    """Is ``nxt`` the same paragraph as ``prev``, hard-wrapped? Only when it
    is safe: a mid-sentence break before a lower-case word, or a line that
    fills the measure and does not end a sentence (or ends one, but carries
    the trailing space a soft wrap leaves). Across a page break a full line
    alone is not enough (a "Keywords:" line above the next page's title is
    full and ends without a full stop): it needs the trailing space too."""
    s, n = prev.rstrip(), nxt.strip()
    if not s or not n:
        return False
    ends = _SENT_END.search(s) is not None
    full = len(s) >= 0.8 * measure
    soft = prev != s  # the trailing space of a soft wrap
    if n[0].islower() and not ends and len(s) >= 0.5 * measure:
        return True
    if s.endswith("-") and (full or n[0].islower() or n[0].isdigit()):
        return True
    if across:
        return full and soft
    return full and (not ends or soft)


def _structure_pdf(pages: list[str]) -> str:
    plines = [(p or "").split("\n") for p in pages]
    _drop_repeating_edges(plines)
    expected, seen = 1, ""
    bodies, notes = [], []
    for lines in plines:
        body, foot = _split_notes(lines, expected, seen)
        expected += len(foot)
        seen += "\n" + "\n".join(body)
        bodies.append(body)
        notes.append(foot)
    lengths = sorted(len(s.rstrip()) for b in bodies for s in b if len(s.strip()) > 20)
    measure = lengths[int(0.9 * (len(lengths) - 1))] if lengths else 80.0

    items: list[tuple[str, object]] = []
    para: list[str] = []
    deferred: list[list[str]] = []

    def flush() -> None:
        if para:
            text = para[0]
            for line in para[1:]:
                text = _join(text, line)
            items.append(("p", text.strip()))
            para.clear()
        for foot in deferred:
            if foot:
                items.append(("notes", foot))
            items.append(("break", None))
        deferred.clear()

    for p, body in enumerate(bodies):
        for line in body:
            if not line.strip():
                flush()
            elif para and _wraps(para[-1], line, measure):
                para.append(line)
            else:
                flush()
                para.append(line)
        last = p == len(bodies) - 1
        nxt = next((s for b in bodies[p + 1 :] for s in b if s.strip()), None)
        if last or nxt is None:
            deferred.append(notes[p])
            if last:
                flush()
                if items and items[-1][0] == "break":
                    items.pop()
        elif para and _wraps(para[-1], nxt, measure, across=True):
            deferred.append(notes[p])  # the paragraph goes on: notes after it
        else:
            deferred.append(notes[p])
            flush()

    # A page that held only the tail of a paragraph keeps only its notes:
    # they join the notes block before them, under the same prose.
    merged: list[tuple[str, object]] = []
    for item in items:
        if (
            item[0] == "notes"
            and len(merged) >= 2
            and merged[-1][0] == "break"
            and merged[-2][0] == "notes"
        ):
            merged.pop()
            merged[-1] = ("notes", [*merged[-1][1], *item[1]])
        else:
            merged.append(item)
    out: list[str] = []
    brk = False
    for kind, value in merged:
        if kind == "break":
            brk = bool(out)
            continue
        if out:
            out.append(PAGE_BREAK if brk else "\n\n")
        out.append("\n".join(value) if kind == "notes" else value)
        brk = False
    return "".join(out)
