"""
Regression tests for the block-quote stripper in features/preprocess.py.

The old pattern '"[^"]{200,}"' also matched from one short quotation's CLOSING
mark to the next short quotation's OPENING mark, so the student's own prose
between two short quotes more than 200 characters apart was dropped from
measurement. The fixed pattern pairs a real opening mark with its real
closing mark, understands curly quotes, never spans a closing-then-opening
pair, and keeps text it cannot pair (nested or unbalanced quotes).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from original.features import preprocess as pp
from original.features.preprocess import _DOUBLE_QUOTE_BLOCK, preprocess

REPO = Path(__file__).resolve().parents[1]
OLD_PATTERN = re.compile(r'"[^"]{200,}"', re.DOTALL)
OLD_INDENT = re.compile(r"(?m)^(?:    |\t).+(?:\n(?:    |\t).+)*")
WORD = re.compile(r"\b\w+(?:'\w+)?\b")


def _words(text: str) -> int:
    """The engine's word rule (features/tier1): alphabetic tokens."""
    return sum(1 for w in WORD.findall(text) if w.isalpha())


def _measured(text: str) -> int:
    """Words Original measures after preprocess()."""
    return _words(preprocess(text)[0])


def _measured_before_fix(text: str) -> int:
    """Words the pre-fix pipeline measured (old quote and indent patterns)."""
    saved = pp._DOUBLE_QUOTE_BLOCK, pp._INDENT_BLOCK, pp._indent_is_paragraph_style
    pp._DOUBLE_QUOTE_BLOCK, pp._INDENT_BLOCK = OLD_PATTERN, OLD_INDENT
    pp._indent_is_paragraph_style = lambda body: False
    try:
        return _words(preprocess(text)[0])
    finally:
        pp._DOUBLE_QUOTE_BLOCK, pp._INDENT_BLOCK, pp._indent_is_paragraph_style = saved


# A 121-word paragraph in the student's own words with two short quotations
# far apart: the shape that lost almost everything under the old pattern.
DEMO = (
    'He called it "home goodbye" and left. The bus pulled away from the station '
    "before the sun was up, and the town slid past the window: the bakery, the park, "
    "the school where his mother "
    "had taught for thirty years, the river that froze every winter and flooded "
    "every spring. He did not look back at the house, because he knew that if "
    "he did he would ask the driver to stop. Instead he counted the fence posts "
    "until the fields gave way to the highway, and the highway gave way to the "
    "long grey bridge across the bay. Years later his sister would tell him that "
    'their father had stood at the gate all morning, saying only "he will '
    'write."'
)


def test_demo_two_short_quotes_far_apart_keep_all_prose():
    assert _words(DEMO) == 121
    # Before the fix almost the whole paragraph vanished.
    assert _measured_before_fix(DEMO) == 8  # "He called it home goodbye he will write"
    # After the fix every word is measured, quotes included.
    assert _measured(DEMO) == 121
    prose, cd = preprocess(DEMO)
    assert "The bus pulled away from the station" in prose
    assert cd.block_quote_word_count == 0


def _chesterton_fixture() -> str:
    # The 1,441-word slice of Orthodoxy used in the 2026-10-24 evidence run.
    full = (REPO / "validation/public_authors/corpus/chesterton/orthodoxy_part_01.txt").read_text(
        encoding="utf-8"
    )
    return full[3225 : 3225 + 7758]


def test_chesterton_fixture_is_measured_almost_whole():
    text = _chesterton_fixture()
    assert _words(text) == 1444
    before, after = _measured_before_fix(text), _measured(text)
    assert before == 125
    # The slice has short quotations and first-line-indented paragraphs only,
    # so nothing in it is a block quote and every word is measured.
    assert after == 1444


def test_real_long_block_quote_is_still_stripped_straight_and_curly():
    quoted = "Liberty " + " ".join(["consists in doing what one desires"] * 9)
    assert _words(quoted) > 40
    for opener, closer in (('"', '"'), ("\u201c", "\u201d")):
        text = f"Mill writes: {opener}{quoted}.{closer} I disagree with him, for three reasons."
        prose, cd = preprocess(text)
        assert "consists in doing" not in prose
        assert prose.startswith("Mill writes:")
        assert "I disagree with him, for three reasons." in prose
        assert cd.block_quote_word_count == len(f"{opener}{quoted}.{closer}".split())


def test_short_quotes_far_apart_curly_and_straight_mixed_keep_prose():
    middle = " ".join(["the student wrote this middle sentence in her own words."] * 8)
    for a, b in (('"', '"'), ("\u201c", "\u201d")):
        text = f"She called it {a}a gift{b} at first. {middle} Later it was {a}a debt{b} instead."
        assert _measured(text) == _words(text)


@pytest.mark.parametrize(
    "text",
    [
        # unbalanced: an opening mark that never closes
        'He began, "' + "and the rest of this sentence keeps going without a close " * 6 + "end.",
        # nested: a curly quotation inside a straight one
        '"' + "outer words " * 25 + "\u201cinner quote\u201d " + "more outer words " * 10 + 'done."',
        # nested: straight inside curly
        "\u201c" + "outer words " * 25 + '"inner" ' + "more outer words " * 10 + "done.\u201d",
        # a lone closing curly mark, then a long run, then a lone opening one
        "end of a quote\u201d " + "plain prose words here " * 15 + "\u201cstart of another",
    ],
)
def test_nested_or_unbalanced_quotes_fail_safe(text):
    assert _DOUBLE_QUOTE_BLOCK.search(text) is None
    assert _measured(text) == _words(text)


def test_closing_then_opening_pair_is_never_a_match():
    gap = "x" * 300
    text = f'a "short" {gap} "another" b'
    assert _DOUBLE_QUOTE_BLOCK.search(text) is None


def test_inch_marks_and_mid_word_quotes_do_not_open_a_quote():
    text = 'The board was 12" wide' + " and quite long" * 30 + ' then "ok" said he.'
    assert _DOUBLE_QUOTE_BLOCK.search(text) is None


def test_quote_followed_by_punctuation_or_end_closes():
    body = " ".join(["words"] * 45)
    for tail in (".", ",", ";", ")", "", " next"):
        text = f'(He said "{body}"{tail}'
        assert _DOUBLE_QUOTE_BLOCK.search(text) is not None, tail


def test_no_catastrophic_backtracking_on_many_unmatched_quotes():
    import time

    text = ('"' + "a" * 250 + " ") * 400
    start = time.perf_counter()
    _DOUBLE_QUOTE_BLOCK.findall(text)
    assert time.perf_counter() - start < 2.0


# ── Indented block quotes ────────────────────────────────────────────────────


def test_indented_whole_paragraph_block_quote_is_still_stripped():
    text = (
        "My own opening paragraph.\n\n"
        "    Quoted line one of the block quotation\n"
        "    quoted line two of the block quotation\n\n"
        "My own closing paragraph."
    )
    prose, cd = preprocess(text)
    assert "Quoted line" not in prose
    assert "My own opening paragraph." in prose and "My own closing paragraph." in prose
    assert cd.block_quote_word_count == 14


def test_first_line_paragraph_indent_is_kept():
    text = (
        "     The first line of my paragraph is indented\n"
        "the way many hard-wrapped texts are, and it goes on.\n\n"
        "     A second paragraph starts the same\n"
        "way and continues without indentation."
    )
    prose, cd = preprocess(text)
    assert _measured(text) == _words(text)
    assert cd.block_quote_word_count == 0
    assert _measured_before_fix(text) < _words(text)  # the old pattern dropped first lines


def test_tab_indented_one_line_paragraphs_are_kept():
    text = "Title\n\n\tMy first paragraph, typed with a tab.\n\n\tMy second paragraph, also tabbed."
    assert _measured(text) == _words(text)
    assert _measured_before_fix(text) == 1  # only "Title" survived before


def test_every_paragraph_indented_is_paragraph_style_not_quotes():
    text = (
        "    My first paragraph is indented\n    on every line of it.\n\n"
        "    So is my second paragraph,\n    the whole way through."
    )
    assert pp._indent_is_paragraph_style(text)
    assert _measured(text) == _words(text)
    assert preprocess(text)[1].block_quote_word_count == 0


def test_indented_lines_inside_a_paragraph_are_kept():
    text = "He wrote:\n    a line in the flow\n    and another\nthen went on."
    assert _measured(text) == _words(text)
