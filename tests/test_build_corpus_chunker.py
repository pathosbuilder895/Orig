"""
tests/test_build_corpus_chunker.py — _chunk_text must never return TOC stubs.

Regression for the Gutenberg TOC bug: editions whose table of contents lists
every chapter heading (kempis pg1653, mill pg34901) made the chapter regex
match the TOC lines first, so the first n_chunks "chunks" were 6-41 word
heading stubs instead of chapter bodies.
"""

from __future__ import annotations

from validation.public_authors.build_corpus import _chunk_text

_FILLER_SENTENCE = (
    "The discipline of daily reading shapes the mind toward patience, "
    "and patience in turn shapes the habits of honest work. "
)  # 20 words


def _chapter_body(n_sentences: int = 20) -> str:
    """~400 words of filler prose for one synthetic chapter."""
    return _FILLER_SENTENCE * n_sentences


def _toc_edition(n_chapters: int = 5) -> str:
    """A work whose TOC lists every chapter heading before the real chapters."""
    numerals = ["I", "II", "III", "IV", "V"][:n_chapters]
    toc = "CONTENTS\n\n" + "\n".join(
        f"CHAPTER {r}\n\nOf the short summary line for chapter {r}" for r in numerals
    )
    chapters = "\n\n".join(
        f"CHAPTER {r}\n\n{_chapter_body()}" for r in numerals
    )
    return f"{toc}\n\n\n{chapters}\n"


def test_toc_edition_chunks_are_chapter_bodies_not_stubs():
    chunks = _chunk_text(_toc_edition(), n_chunks=5)
    assert len(chunks) == 5
    for i, chunk in enumerate(chunks, 1):
        words = len(chunk.split())
        assert words >= 300, f"chunk {i} is a {words}-word stub: {chunk[:80]!r}"


def test_no_chapter_headings_falls_back_to_paragraph_split():
    paragraphs = "\n\n".join(_FILLER_SENTENCE * 5 for _ in range(20))  # 20 × ~100 words
    chunks = _chunk_text(paragraphs, n_chunks=4)
    assert len(chunks) == 4
    for i, chunk in enumerate(chunks, 1):
        words = len(chunk.split())
        assert words >= 100, f"chunk {i} is trivial: {words} words"
