"""PDF -> cleaned prose.

Uses poppler's ``pdftotext -bbox-layout`` (word boxes), so the cleaner can use
geometry: the box height of a word tracks its font size, which separates body
text from footnotes, captions, running heads and page numbers without any font
metadata. Everything removed here is *not prose by the task's definition*:
formulas, tables, references, footnotes and block quotations.

Pure functions (``parse_bbox``, ``clean_pages``, ``strip_inline``) take plain
data so they are unit-tested without poppler or a network.
"""
from __future__ import annotations

import html
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------- parsing --
_PAGE = re.compile(r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', re.S)
_BLOCK = re.compile(r"<block [^>]*>(.*?)</block>", re.S)
_LINE = re.compile(r'<line xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</line>', re.S)
_WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', re.S)


@dataclass
class Line:
    text: str
    x0: float
    x1: float
    y0: float
    y1: float
    h: float  # mean word-box height ~ font size
    page: int
    page_h: float
    block: int  # block index within the document


@dataclass
class Page:
    width: float
    height: float
    lines: List[Line] = field(default_factory=list)


def parse_bbox(xml: str) -> List[Page]:
    pages: List[Page] = []
    block_no = 0
    for pi, pm in enumerate(_PAGE.finditer(xml)):
        pw, ph = float(pm.group(1)), float(pm.group(2))
        page = Page(pw, ph)
        for bm in _BLOCK.finditer(pm.group(3)):
            block_no += 1
            for lm in _LINE.finditer(bm.group(1)):
                words = [(float(w.group(4)) - float(w.group(2)), html.unescape(w.group(5)))
                         for w in _WORD.finditer(lm.group(5))]
                if not words:
                    continue
                page.lines.append(Line(
                    text=" ".join(w for _, w in words),
                    x0=float(lm.group(1)), y0=float(lm.group(2)),
                    x1=float(lm.group(3)), y1=float(lm.group(4)),
                    h=sum(h for h, _ in words) / len(words),
                    page=pi, page_h=ph, block=block_no,
                ))
        pages.append(page)
    return pages


# --------------------------------------------------------------- cleaning --
_REF_HEAD = re.compile(
    r"^\s*(\d+\.?\s*)?(references?( cited)?|bibliography|works? cited|literature cited|"
    r"endnotes?|notes|sources|acknowledge?ments?)\s*:?\s*$", re.I)
_MATH_CHARS = re.compile(r"[=<>≤≥≈≠±×÷∑∏∫∂∇√∞∈∉⊂⊆⊃⊇∪∩→←↔⇒⇔∀∃∧∨¬∘⊕⊗ℝℕℤℚℂ^_{}|\\∼≡≪≫〈〉⟨⟩]")
_GREEK = re.compile(r"[Ͱ-Ͽ]")
_CITE_PAREN = re.compile(r"\((?:[^()]{0,80}?\b(?:1[5-9]|20)\d\d[a-z]?(?:[,;:][^()]{0,60})?)\)")
_CITE_BRACKET = re.compile(r"\[\s*\d+(?:\s*[,–\-]\s*\d+)*\s*\]|\[[^\[\]]{0,80}?\b(?:1[5-9]|20)\d\d[a-z]?[^\[\]]{0,40}\]")
_URL = re.compile(r"(https?://|www\.|doi:)\S+", re.I)
_STOP = frozenset("the of and to in a is that for it as with was on be by this are from or an at which not have has".split())
_ALPHA_WORD = re.compile(r"^[A-Za-z][A-Za-z'’\-]*[.,;:!?\"”’)]*$|^[(\"“‘][A-Za-z][A-Za-z'’\-]*[.,;:!?\"”’)]*$")


def alpha_fraction(text: str) -> float:
    toks = text.split()
    if not toks:
        return 0.0
    return sum(1 for t in toks if _ALPHA_WORD.match(t)) / len(toks)


def stopword_fraction(text: str) -> float:
    toks = [t.lower().strip(".,;:!?\"'()") for t in text.split()]
    return sum(1 for t in toks if t in _STOP) / len(toks) if toks else 0.0


def is_english(text: str) -> bool:
    return stopword_fraction(text) >= 0.18


_NOTE_MARK = re.compile(r"(?<=[.,;:!?”’)\"])\d{1,3}(?=\s|$)|(?<=[a-z])\d{1,2}(?=[\s.,;:)])")


def strip_inline(text: str) -> str:
    """Remove inline citations, footnote markers, URLs and formula residue from prose."""
    text = _CITE_PAREN.sub("", text)
    text = _NOTE_MARK.sub("", text)
    text = _CITE_BRACKET.sub("", text)
    text = _URL.sub("", text)
    out = []
    for tok in text.split():
        if _MATH_CHARS.search(tok) or _GREEK.search(tok):
            continue
        if len(tok) == 1 and tok.isalpha() and tok not in "aAI":  # stray variable symbols
            continue
        out.append(tok)
    return re.sub(r"\s+([.,;:!?])", r"\1", " ".join(out))


def _body_height(lines: List[Line]) -> float:
    c: Counter = Counter()
    for ln in lines:  # half-point bins: a mode over 0.1-point bins is split by rounding noise
        c[round(ln.h * 2) / 2] += len(ln.text.split())
    return c.most_common(1)[0][0] if c else 0.0


def _left_margin(lines: List[Line], body_h: float) -> float:
    c: Counter = Counter()
    for ln in lines:
        if abs(ln.h - body_h) <= 0.12 * body_h and len(ln.text.split()) >= 6:
            c[round(ln.x0 / 4)] += 1
    return c.most_common(1)[0][0] * 4 if c else 0.0


def clean_pages(pages: List[Page], min_para_words: int = 12) -> str:
    """Prose of a parsed document: body-size text only, no formulas, tables,
    references, footnotes, headings, captions or block quotations."""
    lines = [ln for p in pages for ln in p.lines]
    if not lines:
        return ""
    body_h = _body_height(lines)
    left = _left_margin(lines, body_h)

    # 1. geometry: keep body-size lines outside the running-head/foot bands
    kept: List[Line] = []
    for ln in lines:
        if ln.h < 0.9 * body_h or ln.h > 1.25 * body_h:      # footnotes, captions, headings
            continue
        if ln.y0 < 0.07 * ln.page_h or ln.y1 > 0.93 * ln.page_h:  # headers, footers, page numbers
            continue
        kept.append(ln)

    # 2. cut at the references / endnotes heading in the back half
    cut = None
    n = len(lines)
    pos = {id(ln): i for i, ln in enumerate(lines)}
    for ln in lines:
        if _REF_HEAD.match(ln.text) and pos[id(ln)] > 0.45 * n:
            cut = pos[id(ln)]
            break
    if cut is not None:
        kept = [ln for ln in kept if pos[id(ln)] < cut]

    # 3. group into blocks; drop indented (block-quote) and symbol-heavy blocks
    blocks: List[List[Line]] = []
    for ln in kept:
        if blocks and blocks[-1][-1].block == ln.block:
            blocks[-1].append(ln)
        else:
            blocks.append([ln])
    paras: List[str] = []
    for blk in blocks:
        if all(l.x0 > left + 1.5 * body_h for l in blk) and len(blk) >= 2:  # block quotation
            continue
        text = ""
        for l in blk:
            t = l.text
            if text.endswith("-") and t[:1].islower():
                text = text[:-1] + t           # de-hyphenate across the line break
            else:
                text = (text + " " + t) if text else t
        if alpha_fraction(text) < 0.78:        # tables, display formulas, citation lists
            continue
        text = strip_inline(text)
        if re.match(r"^(fig(ure)?|table)\b\.?\s*\d", text, re.I):
            continue
        if len(text.split()) < min_para_words:  # headings, labels, orphan lines
            continue
        if text.count("•") >= 2 and text.lstrip().startswith("•"):  # publication / reference lists
            continue
        if stopword_fraction(text) < 0.17:      # another language (bilingual abstracts) or word lists
            continue
        if re.match(r"^[“\"‘].*[”\"’][\s.,;:!?)\d]*$", text) and len(text.split()) > 40:  # quoted passage
            continue
        paras.append(text)
    # a paragraph split only by a page or column break continues the previous one
    merged: List[str] = []
    for t in paras:
        if merged and not re.search(r"[.!?:”\"’)]$", merged[-1]) and t[:1].islower():
            joined = merged[-1] + t if merged[-1].endswith("-") else merged[-1] + " " + t
            merged[-1] = joined
        else:
            merged.append(t)
    return "\n\n".join(merged)


class PdfToolMissing(RuntimeError):
    pass


@dataclass
class Extraction:
    text: str
    raw_words: int        # words poppler found before any cleaning (0 for a scanned PDF)
    raw_stopword: float   # English function-word share of the raw text (language test)


def raw_stats(pages: List[Page]) -> tuple:
    raw = " ".join(ln.text for p in pages for ln in p.lines)
    return len(raw.split()), stopword_fraction(raw)


def pdf_bytes_to_text(pdf: bytes, tmp_dir: Path, name: str = "doc", timeout: int = 120) -> Optional[str]:
    ex = pdf_bytes_to_extraction(pdf, tmp_dir, name, timeout)
    return None if ex is None else ex.text


def pdf_bytes_to_extraction(pdf: bytes, tmp_dir: Path, name: str = "doc", timeout: int = 120) -> Optional["Extraction"]:
    """Run poppler on PDF bytes. None when the bytes are not a readable PDF."""
    if not pdf.startswith(b"%PDF"):
        return None
    exe = shutil.which("pdftotext")
    if not exe:
        raise PdfToolMissing("pdftotext (poppler-utils) is required: apt install poppler-utils")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    p = tmp_dir / f"{name}.pdf"
    p.write_bytes(pdf)
    try:
        r = subprocess.run([exe, "-bbox-layout", "-enc", "UTF-8", str(p), "-"],
                           capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    finally:
        p.unlink(missing_ok=True)
    if r.returncode != 0:
        return None
    pages = parse_bbox(r.stdout.decode("utf-8", "replace"))
    n, stop = raw_stats(pages)
    return Extraction(clean_pages(pages), n, stop)
