"""Reflow a PDF's hard-wrapped lines before the matter measurement measures it.

pypdf prints a PDF page as the lines it was set in: every line of a paragraph
ends in a newline and paragraphs are not separated by a blank line. The same
prose pasted, or read from a .docx, is one line per paragraph with a blank
line between paragraphs. The splitter's ranges (``features.matter``) already
take out the running heads, page numbers, footnote blocks and the other
parts; this module joins what is left back into paragraphs, so the measured
prose of a PDF is the prose of the same paper pasted.

It runs only on text that ``upload_utils`` stored from a PDF (it ends with
``matter.PDF_TAG``, one page or many) and only on the measured body, with the splitter
on (``features.preprocess._body``; ``evidence.engine_view`` applies the same
edits to its offset map). Stored text is never changed, and a PDF stored
before page markers were kept is measured as it is (no reflow).

A line break is decided from the two lines around it, deterministically:

* joined with a space when the line above does not end a sentence and the
  line below starts in lower case (and the line above is at least half the
  usual line length), or when the line above fills the line
  (``FULL``) and does not end a sentence, or fills it and ends with the
  trailing space a soft wrap leaves;
* joined with nothing after a hyphen at the end of a full line, or inside a
  URL broken after a slash;
* across a page marker, joined only on the lower-case rule, a hyphen, or a
  full line with the soft-wrap space (a full "Keywords:" line above the next
  page's title stays apart);
* otherwise it becomes a paragraph break (a blank line).
"""

from __future__ import annotations

import re

from .matter import PAGE_MARK

#: A line at least this share of the usual line length fills the line.
FULL = 0.8
# A sentence end, with any closing quote or bracket and a note number after it.
_SENT_END = re.compile(r"[.?!][\"'”’)\]]*\d{0,3}$|:$")


def _measure(lines: list[str]) -> float:
    lengths = sorted(len(s.rstrip()) for s in lines if len(s.strip()) > 20)
    return float(lengths[int(0.9 * (len(lengths) - 1))]) if lengths else 80.0


def _wraps(prev: str, nxt: str, measure: float, across: bool) -> str | None:
    """The joint between two lines: " " or "" (same paragraph) or None."""
    s, n = prev.rstrip(), nxt.strip()
    ends = _SENT_END.search(s) is not None
    full = len(s) >= FULL * measure
    soft = prev != s  # the trailing space of a soft wrap
    tight = prev == s and (
        (s.endswith("-") and not s.endswith(" -")) or (s.endswith("/") and "://" in s)
    )
    if n[0].islower() and not ends and len(s) >= 0.5 * measure:
        return "" if tight else " "
    if s.endswith("-") and (full or n[0].islower() or n[0].isdigit()):
        return "" if tight else " "
    if across:
        return " " if full and soft else None
    if full and (not ends or soft):
        return "" if tight else " "
    return None


def reflow_ops(body: str) -> list[tuple[int, int, str]]:
    """Edits (start, end, replacement) that reflow ``body``, in order and not
    overlapping. Only the whitespace between two lines is ever replaced."""
    spans: list[tuple[int, int, str]] = []  # (start, end of content, content)
    pos = 0
    for chunk in body.split("\n"):
        spans.append((pos, pos + len(chunk), chunk))
        pos += len(chunk) + 1
    content = [i for i, (_, _, c) in enumerate(spans) if c.strip()]
    measure = _measure([spans[i][2] for i in content])
    ops: list[tuple[int, int, str]] = []
    for a, b in zip(content, content[1:], strict=False):
        between = [spans[i][2] for i in range(a + 1, b)]
        marks = sum(1 for c in between if c in (PAGE_MARK, PAGE_MARK * 2))
        if marks > 1:
            continue  # an empty page between them
        across = marks == 1  # a blank line next to a page marker is the page's edge
        if not across and between:
            continue  # a blank line already separates them
        prev, nxt = spans[a][2], spans[b][2]
        joint = _wraps(prev, nxt, measure, across)
        start = spans[a][0] + len(prev.rstrip())
        end = spans[b][0] + (len(nxt) - len(nxt.lstrip()))
        if joint is not None:
            ops.append((start, end, joint))
        elif not across:
            ops.append((start, spans[a][1] + 1, "\n\n"))
    return ops


def apply_ops(text: str, ops: list[tuple[int, int, str]]) -> str:
    out, last = [], 0
    for start, end, repl in ops:
        out.append(text[last:start])
        out.append(repl)
        last = end
    out.append(text[last:])
    return "".join(out)
