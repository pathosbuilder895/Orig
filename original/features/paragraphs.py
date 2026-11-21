"""Read a Word-style paste's line breaks as paragraph breaks (the ``para``
measurement, ``PARAGRAPH_BREAKS_ENABLED``; off by default).

Why
---
The extractors find paragraphs at blank lines (``tier1._split_paragraphs``,
``tension_arc._split_paragraphs``, ``preprocess``'s per-paragraph citation
counts). A paper pasted from Google Docs, or read from a .docx, has a blank
line between paragraphs; the same paper pasted from Word has one newline.
Without a blank line the whole paper is one paragraph, which moves
``avg_paragraph_length``, ``paragraph_topic_position``,
``transition_predictability`` and ``metric_flatness_score`` on every paper
(and ``catastrophe_index`` and ``error_topology_consistency`` on some). On the
document_parts_v2 dev split (published prose, not student writing, n = 6) the
single-newline paste read 0.022 to 0.063 higher than the blank-line paste.

The rule (``paragraph_ops``)
----------------------------
Applied to the measured body only (``preprocess._body``, after the page
markers are dropped; ``evidence.engine_view`` makes the same edit). A body is
treated as a Word-style paste when all of these hold:

* it has no blank line at all (a line holding only spaces or tabs counts as
  blank), so a body that marks any paragraph with a blank line is untouched;
* at least ``MIN_PARAGRAPH_LINES`` of its lines are paragraph-length: at least
  ``MIN_LINE_WORDS`` words and ending a sentence (a full stop, question or
  exclamation mark, ellipsis, or a colon introducing a quotation; then any
  dash, closing quote or bracket, and a note number such as ``2``, ``(138)``
  or ``[12]``);
* those lines hold at least ``MIN_WORD_SHARE`` of the body's words.

Then every line break between two lines with words on them becomes a blank
line, which is exactly the blank-line paste of the same text. Anything else is
measured unchanged: poetry, lists and short lines (no paragraph-length
lines), a paragraph hard-wrapped at a fixed width (its lines rarely reach 25
words and end a sentence), a single paragraph, and every .docx and PDF upload
(a .docx has blank lines; a PDF's page breaks become blank lines once its
markers are dropped, and its hard-wrapped lines are short).

Not validated on student writing; see
``validation/diagnostics/document_parts_v2/README.md`` ("Paragraph breaks").
"""

from __future__ import annotations

import re

#: A paragraph-length line has at least this many words ...
MIN_LINE_WORDS = 25
#: ... and the paragraph-length lines hold at least this share of the words.
MIN_WORD_SHARE = 0.75
#: At least this many paragraph-length lines (one line is one paragraph anyway).
MIN_PARAGRAPH_LINES = 2

# The same paragraph boundary tier1._split_paragraphs uses (\n\s*\n), so a blank
# line made of a CR or a non-breaking space counts as blank here too.
_BLANK_LINE = re.compile(r"\n\s*\n")
# A sentence end (or a colon introducing a quotation, which pdf_reflow also
# reads as one), then any dash, closing quote or bracket, then an optional
# note number: "2", "(138)" or "[12]". Built with chr() to keep the source ASCII.
_ENDS = ".?!" + chr(0x2026) + ":"  # full stop, ? !, ellipsis, colon
_AFTER = chr(0x2013) + chr(0x2014) + '"' + "'" + chr(0x201D) + chr(0x2019) + ")]"
_SENT_END = re.compile(
    "[" + re.escape(_ENDS) + "][" + re.escape(_AFTER) + "]*"
    r"(?:\d{1,3}|\(\d{1,3}\)|\[\d{1,3}\])?$"
)


def _paragraph_length(line: str) -> bool:
    s = line.strip()
    return len(s.split()) >= MIN_LINE_WORDS and _SENT_END.search(s) is not None


def is_word_paste(body: str) -> bool:
    """Does ``body`` read as paragraphs separated by single line breaks?"""
    if "\n" not in body or _BLANK_LINE.search(body):
        return False
    lines = [line for line in body.split("\n") if line.split()]
    total = sum(len(line.split()) for line in lines)
    long_lines = [line for line in lines if _paragraph_length(line)]
    if len(long_lines) < MIN_PARAGRAPH_LINES or not total:
        return False
    return sum(len(line.split()) for line in long_lines) >= MIN_WORD_SHARE * total


def paragraph_ops(body: str) -> list[tuple[int, int, str]]:
    """Edits (start, end, "\\n\\n") that turn each line break of a Word-style
    paste into a paragraph break, in order and not overlapping; [] for any
    other body. The same shape as ``pdf_reflow.reflow_ops``."""
    if not is_word_paste(body):
        return []
    ops: list[tuple[int, int, str]] = []
    pos = 0
    chunks = body.split("\n")
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        pos += len(prev)
        if prev.split() and nxt.split():
            ops.append((pos, pos + 1, "\n\n"))
        pos += 1
    return ops
