"""Character labels for extracted text.

A .docx or .pdf goes through ``original.upload_utils.extract_text_from_bytes``
before Original sees it, so the true part of each character has to be found
again in the extracted string. This module does that by matching, never by
guessing:

1. The main flow (every body paragraph, in order, with its per-character
   kinds) is aligned to the extracted text word by word
   (``difflib.SequenceMatcher``); words that differ slightly (a superscript
   note number run into a word, a ligature) are aligned character by
   character inside that gap.
2. What is left over is searched for the floating parts the source put
   outside the flow: each page's running head or page number, and each
   footnote. Exact matches first (whitespace ignored), then long fuzzy
   blocks for a footnote split across pages.
3. Anything still unmatched is labelled ``unattributed`` and counted, and
   every source character that was never found is counted as lost in
   extraction, by kind.

Whitespace is never scored: metrics count non-whitespace characters only.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

SEP = "sep"  # whitespace between paragraphs
UNATTRIBUTED = "unattributed"
_TOKEN = re.compile(r"\S+")
_MAX_GAP_CHARS = 4000
_MIN_FUZZY = 6


def rle(labels: list[str]) -> list[list]:
    out: list[list] = []
    for k in labels:
        if out and out[-1][0] == k:
            out[-1][1] += 1
        else:
            out.append([k, 1])
    return out


def unrle(runs: list[list]) -> list[str]:
    out: list[str] = []
    for k, n in runs:
        out.extend([k] * n)
    return out


def nonws_counts(text: str, labels: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for ch, k in zip(text, labels, strict=True):
        if not ch.isspace():
            out[k] = out.get(k, 0) + 1
    return out


def _tokens(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _TOKEN.finditer(text)]


def _char_align(src: str, a_pos: list[int], ext: str, b_pos: list[int]):
    """Pairs (src offset, ext offset) for characters matched inside a gap."""
    a = "".join(src[i] for i in a_pos)
    b = "".join(ext[j] for j in b_pos)
    if not a or not b or len(a) > _MAX_GAP_CHARS or len(b) > _MAX_GAP_CHARS:
        return []
    sm = SequenceMatcher(None, a, b, autojunk=False)
    pairs = []
    for blk in sm.get_matching_blocks():
        for t in range(blk.size):
            pairs.append((a_pos[blk.a + t], b_pos[blk.b + t]))
    return pairs


def _nonws_positions(text: str, spans: list[tuple[int, int]]) -> list[int]:
    return [i for s, e in spans for i in range(s, e)]


def align(
    ext: str,
    flow: list[tuple[str, list[str]]],
    floating: list[tuple[str, str]],
) -> dict:
    """Label ``ext`` from the source parts.

    ``flow``: (paragraph text, kind of each character), in document order.
    ``floating``: (text, kind) of parts placed outside the flow (one running
    head per page, each footnote). Returns ``labels`` (one kind per character
    of ``ext``), ``source`` and ``lost`` (non-whitespace characters per kind
    in the source, and how many of them were never found) and
    ``unattributed`` (non-whitespace characters of ``ext`` matched to
    nothing)."""
    src = "\n".join(t for t, _ in flow)
    src_kind: list[str] = []
    for n, (_text, kinds) in enumerate(flow):
        if n:
            src_kind.append(SEP)
        src_kind.extend(kinds)
    assert len(src_kind) == len(src)

    labels: list[str | None] = [None] * len(ext)
    src_hit = [False] * len(src)

    st, et = _tokens(src), _tokens(ext)
    sm = SequenceMatcher(None, [src[s:e] for s, e in st], [ext[s:e] for s, e in et], autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for (sa, sb), (ea, _eb) in zip(st[i1:i2], et[j1:j2], strict=True):
                for d in range(sb - sa):
                    labels[ea + d] = src_kind[sa + d]
                    src_hit[sa + d] = True
        elif tag == "replace":
            pairs = _char_align(
                src, _nonws_positions(src, st[i1:i2]), ext, _nonws_positions(ext, et[j1:j2])
            )
            for si, ej in pairs:
                labels[ej] = src_kind[si]
                src_hit[si] = True

    # Floating parts, searched in what the flow left over.
    float_hit: list[list[bool]] = []
    left = [j for j, ch in enumerate(ext) if not ch.isspace() and labels[j] is None]
    left_str = "".join(ext[j] for j in left)
    taken = [False] * len(left)
    order = sorted(range(len(floating)), key=lambda n: -len(floating[n][0]))
    hits: dict[int, list[bool]] = {}
    for n in order:
        text, kind = floating[n]
        f = "".join(text.split())
        hit = [False] * len(f)
        hits[n] = hit
        if not f:
            continue
        start = 0
        while True:
            k = left_str.find(f, start)
            if k < 0:
                break
            if not any(taken[k : k + len(f)]):
                for d in range(len(f)):
                    taken[k + d] = True
                    labels[left[k + d]] = kind
                    hit[d] = True
                break
            start = k + 1
        if not all(hit) and kind == "footnote" and len(f) >= 2 * _MIN_FUZZY:
            free = "".join(c if not taken[i] else "\0" for i, c in enumerate(left_str))
            fsm = SequenceMatcher(None, f, free, autojunk=False)
            for blk in fsm.get_matching_blocks():
                if blk.size >= _MIN_FUZZY:
                    for d in range(blk.size):
                        if not hit[blk.a + d] and not taken[blk.b + d]:
                            taken[blk.b + d] = True
                            labels[left[blk.b + d]] = kind
                            hit[blk.a + d] = True
    float_hit = [hits[n] for n in range(len(floating))]

    unattributed = 0
    out: list[str] = []
    for ch, k in zip(ext, labels, strict=True):
        if k is None:
            if ch.isspace():
                k = SEP
            else:
                k = UNATTRIBUTED
                unattributed += 1
        out.append(k)

    source: dict[str, int] = {}
    lost: dict[str, int] = {}
    for ch, k, hit in zip(src, src_kind, src_hit, strict=True):
        if ch.isspace():
            continue
        source[k] = source.get(k, 0) + 1
        if not hit:
            lost[k] = lost.get(k, 0) + 1
    for (text, kind), hit in zip(floating, float_hit, strict=True):
        n = len("".join(text.split()))
        source[kind] = source.get(kind, 0) + n
        missed = n - sum(hit)
        if missed:
            lost[kind] = lost.get(kind, 0) + missed
    return {"labels": out, "source": source, "lost": lost, "unattributed": unattributed}
