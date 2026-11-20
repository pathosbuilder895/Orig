"""
upload_utils.py: the one text extractor for uploaded papers (PDF, DOCX, TXT).

Canonical home of the extractor; lives at the package root so every caller can
import it without the v1 package chain: the live app's upload routes
(``routers/students.py``, ``routers/students_baseline.py``,
``routers/past_papers.py``), ``canvas/live_import.py``, and the dormant v1 app
through the re-export shim at ``api/v1/upload_utils.py``.

Page markers
------------
The text is exactly what this extractor returned before page markers were
kept, plus a page marker (``features.matter.PAGE_MARK``, U+001F, alone on a
line) where the file breaks a page, in the blank line that stood there:

``.docx``
    Paragraph text as before (python-docx ``Paragraph.text``, blank
    paragraphs dropped, a blank line between paragraphs), with
    ``matter.PAGE_BREAK`` where the file breaks a page: ``w:br w:type="page"``,
    a paragraph set to start on a new page (``w:pageBreakBefore``, direct or
    from its style), a ``w:lastRenderedPageBreak`` before a paragraph's first
    text, and a section break that starts a new page. Headers, footers and
    footnotes stay out, as before.
``.pdf``
    The pages as pypdf reads them, joined by ``matter.PDF_PAGE_BREAK`` (two
    marks) where they were joined by a blank line. Nothing else changes:
    running heads, page numbers and footnotes are set aside, and hard-wrapped
    lines reflowed, only when the paper is measured with the splitter on
    (``features.matter``, ``features.pdf_reflow``), so the stored text is the
    same whatever the switch says.
``.txt``
    Decoded as UTF-8, unchanged. Pasted text never comes through here.

A page marker is never measured and never part of a duplicate check: every
measurement (``features.preprocess``), the raw-text experts and every
duplicate hash (``text_digest``) drop it first, so a paper extracted here
measures and hashes byte for byte as it did before markers were kept
(``tests/test_upload_structure.py``). The mark is whitespace to Python, so
word counts are unchanged too.

All extractors return a plain unicode string or raise ``ValueError`` with a
human-readable reason (``ExtractorUnavailableError``, a subclass, when the
library is not installed), chained to the library's own exception, so callers
can attach either to per-file error reports.
"""

from __future__ import annotations

import hashlib
import io

from .features.matter import PAGE_BREAK, PDF_PAGE_BREAK, without_page_breaks

ACCEPTED = ".txt, .pdf, .docx"


class ExtractorUnavailableError(ValueError):
    """The library that reads this file type is not installed."""

    def __init__(self, package: str, pip_spec: str):
        self.package = package
        super().__init__(f"{package} is not installed; run: pip install {pip_spec}")


def extract_text_from_bytes(raw: bytes, filename: str) -> str:
    """
    Extract plain text from raw file bytes.

    Args:
        raw:      Raw bytes of the uploaded file.
        filename: Original filename, used to determine the format by extension.

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
        except ImportError as err:
            raise ExtractorUnavailableError("pypdf", "pypdf>=4.0,<5.0") from err
        try:
            reader = PdfReader(io.BytesIO(raw))
            pages = [page.extract_text() or "" for page in reader.pages]
        except Exception as exc:
            raise ValueError(f"PDF extraction failed: {exc}") from exc
        return PDF_PAGE_BREAK.join(pages)

    if name_lower.endswith(".docx"):
        try:
            from docx import Document
        except ImportError as err:
            raise ExtractorUnavailableError("python-docx", "python-docx>=1.1,<2.0") from err
        try:
            return _docx_text(Document(io.BytesIO(raw)))
        except Exception as exc:
            raise ValueError(f"DOCX extraction failed: {exc}") from exc

    ext = filename.rsplit(".", 1)[-1] if "." in filename else "unknown"
    raise ValueError(f"Unsupported file type '.{ext}'. Accepted formats: {ACCEPTED}")


def word_count(text: str) -> int:
    """Return word count for text."""
    return len(text.split())


def text_digest(text: str) -> str:
    """SHA-256 of a paper's text for duplicate checks, page markers dropped,
    so a file uploaded before markers were kept and the same file uploaded
    after hash alike."""
    return hashlib.sha256(without_page_breaks(text).encode()).hexdigest()


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
