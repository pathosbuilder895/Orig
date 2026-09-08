"""
tests/test_preprocess.py — branch coverage for
`original/features/preprocess.py`.

Covers:
  - `_strip_backmatter` (via `preprocess()`): a "Bibliography" heading line
    strips everything from that line to EOF.
  - `_extract_citation_data`: the accented-surname arm where the outer
    `_PAREN_CITATION` regex matches (it accepts `[A-ZÁÉÍÓÚ]`) but the
    inner ASCII-only `surname = re.match(r"[A-Z]...")` does not, so
    `cited_authors` stays empty for that match.
  - `_extract_citation_data` / `_clean_prose` (via `preprocess()`): both
    arms of the double-quote block loop — a long quote (> 40 words, whose
    word count is added to `block_quote_word_count` and is stripped from
    prose) and a short-but-long quote (<= 40 words despite >= 200 chars,
    counted in `short_quote_count` and left in prose) — plus an indented
    block (added to `block_quote_word_count`).
"""

from __future__ import annotations

from original.features.preprocess import _extract_citation_data, preprocess


def test_preprocess_strips_bibliography_heading_and_everything_after():
    body = (
        "Intro paragraph about theology.\n\n"
        "More discussion follows here in depth.\n\n"
        "Bibliography\n"
        "Smith, J. (2020). A Book. Publisher.\n"
        "Jones, A. (2019). Another Book. Publisher."
    )
    prose, _ = preprocess(body)
    assert "Bibliography" not in prose
    assert "Smith" not in prose
    assert prose == "Intro paragraph about theology.\n\nMore discussion follows here in depth."


def test_extract_citation_data_accented_surname_is_not_captured():
    # _PAREN_CITATION accepts [A-ZÁÉÍÓÚ] at the start, but the surname
    # extraction regex is ASCII-only ([A-Z]), so this citation matches the
    # outer pattern yet contributes nothing to cited_authors.
    text = "This claim is well supported (Álvarez, 2020) in the literature."
    cd = _extract_citation_data(text)
    assert cd.paren_citation_count == 1
    assert cd.cited_authors == []


def test_preprocess_double_quote_and_indent_blocks_both_arms():
    long_quote_words = " ".join(["word"] * 45)  # 45 words -> > 40 arm
    short_but_wide_quote = " ".join(["extraordinarily"] * 15)  # 15 words, >=200 chars -> <= 40 arm
    body = (
        "Intro sentence before quotes.\n\n"
        f'She wrote: "{long_quote_words}" which is a long block quote.\n\n'
        f'Then noted: "{short_but_wide_quote}" as a short high-char-count quote.\n\n'
        "    This indented line is a block quote for testing purposes here.\n"
        "    It continues onto a second indented line as well.\n\n"
        "Conclusion sentence after the blocks."
    )

    cd = _extract_citation_data(body)
    # Long quote (45 words) -> block_quote_word_count; short-but-wide quote
    # (15 words) -> short_quote_count; indented block also adds to
    # block_quote_word_count.
    assert cd.short_quote_count == 1
    assert cd.block_quote_word_count > 45  # long quote + indented block words

    prose, _ = preprocess(body)
    # The long (> 40 word) quote is stripped from prose...
    assert long_quote_words not in prose
    # ...but the short-but-wide (<= 40 word) quote is left intact.
    assert short_but_wide_quote in prose
    # The indented block is removed entirely.
    assert "indented line" not in prose
