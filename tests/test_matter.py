"""features/matter.py and the splitter switch (MATTER_SPLITTER_ENABLED).

Sample papers in tests/fixtures/paper_matter/ cover the shapes the plan named:
an MLA paper pasted from Word, MLA with a centred title and "Works Cited:", an
APA paper with section headings, a Chicago paper extracted from a PDF (running
head, footnotes at the page foot), and three traps: a PDF line-wrap with a
numbered list holding a year, an indented poem with short one-line replies,
and prose that starts lines with "Notes", "References", "Appendix A" and
"Bibliography". The rule that matters most: no prose is lost.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from original import evidence as ev
from original.features import matter
from original.features import preprocess as pp

FIXTURES = Path(__file__).parent / "fixtures" / "paper_matter"
NAMES = sorted(p.stem for p in FIXTURES.glob("*.txt"))


def _text(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text(encoding="utf-8")


def _parts(text: str) -> list[tuple[str, str]]:
    return [(r.kind, text[r.start : r.end].strip()) for r in matter.find_matter(text)]


@pytest.fixture
def splitter_on(monkeypatch):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    ev.engine_view.cache_clear()
    yield
    ev.engine_view.cache_clear()


#: kinds found per fixture: (front_matter lines, headings, page lines, footnotes, back matter)
EXPECTED = {
    "apa": (7, 5, 0, 0, "References"),
    "cover_letter_md": (5, 0, 0, 0, "## References"),
    "chicago_pdf": (4, 0, 1, 3, "Bibliography"),
    "mla_docx": (5, 0, 0, 0, "Works Cited"),
    "mla_variants": (5, 0, 0, 0, "Works Cited:"),
    "pdf_wrap_trap": (5, 0, 1, 0, None),
    "poem_quote": (1, 1, 0, 0, None),
    "tricky_prose": (1, 1, 0, 0, None),
}


@pytest.mark.parametrize("name", NAMES)
def test_fixture_parts(name):
    parts = _parts(_text(name))
    kinds = [k for k, _ in parts]
    front, heads, pages, notes, back = EXPECTED[name]
    assert kinds.count("front_matter") == front
    assert kinds.count("heading") == heads
    assert kinds.count("page_header") == pages
    assert kinds.count("footnote") == notes
    backs = [s for k, s in parts if k == "back_matter"]
    assert [b.splitlines()[0].strip() for b in backs] == ([back] if back else [])


def _prose_paragraphs(text: str) -> list[str]:
    """Lines a reader would call running prose: eight or more words ending a
    sentence, outside any list of sources and any cover letter."""
    head = re.search(
        r"^\s*(?:#+\s*)?(?:works cited:?|references|bibliography)\s*$", text, re.I | re.M
    )
    body = text[: head.start()] if head and head.start() > len(text) * 0.4 else text
    letter = re.search(r"^Dear .*?^Sincerely,$", body, re.M | re.S)
    if letter and letter.start() == 0:
        body = body[letter.end() :]
    return [
        ln.strip()
        for ln in body.splitlines()
        if len(ln.split()) >= 8
        and ln.rstrip().endswith((".", "?", "!", '"', "\u201d"))
        and not re.match(r"^\s*\d{1,3}\.\s", ln)  # footnote/numbered lines checked separately
    ]


@pytest.mark.parametrize("name", NAMES)
def test_no_prose_is_lost(name):
    """Every line of running prose is outside the set-aside ranges."""
    text = _text(name)
    kept = "".join(text[a:b] for a, b in matter.kept_ranges(text))
    for line in _prose_paragraphs(text):
        assert line in kept, f"{name}: lost prose line {line!r}"


def test_traps_keep_their_prose():
    wrap = _text("pdf_wrap_trap")
    kept = "".join(wrap[a:b] for a, b in matter.kept_ranges(wrap))
    for line in ("Henry James", "1. The sentences delay meaning on purpose.", "2. The delay"):
        assert line in kept  # a wrapped line and a numbered list with a year stay prose
    assert "Ruiz 2" not in kept
    tricky = _text("tricky_prose")
    kept = "".join(tricky[a:b] for a, b in matter.kept_ranges(tricky))
    for line in (
        "That was the word",
        "Appendix A of my life",
        "Bibliography is not",
        "References to",
    ):
        assert line in kept  # the old rule cut everything after "Notes"
    poem = _text("poem_quote")
    kept = "".join(poem[a:b] for a, b in matter.kept_ranges(poem))
    for line in ("Yes.", "No.", "Maybe later.", "I took the one less traveled by"):
        assert line in kept


def test_old_rule_lost_the_tricky_prose_and_the_new_one_keeps_it(splitter_on, monkeypatch):
    text = _text("tricky_prose")
    on, _ = pp.preprocess(text)
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "0")
    off, _ = pp.preprocess(text)
    assert "Some days the list was long." not in off
    assert "Some days the list was long." in on
    assert len(on.split()) > 1.5 * len(off.split())


def test_works_cited_with_a_colon_is_set_aside(splitter_on, monkeypatch):
    text = _text("mla_variants")
    on, _ = pp.preprocess(text)
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "0")
    off, _ = pp.preprocess(text)
    assert "Avalon Project" in off and "Avalon Project" not in on
    assert "John Roe" in off and "John Roe" not in on


# ── Guards ───────────────────────────────────────────────────────────────────

PROSE = "This is an ordinary sentence of the paper with several words in it. "


def test_large_low_confidence_share_is_logged_then_refused(caplog):
    # 3 heading-block words of ~14 + 8: logged but kept aside (15-30%).
    some = "Jane Doe\nENGL 1101\n\n" + PROSE + "\n"
    with caplog.at_level(logging.INFO, logger="original.features.matter"):
        assert [r.kind for r in matter.find_matter(some)] == ["front_matter", "front_matter"]
    assert "over 15%" in caplog.text
    caplog.clear()
    # Mostly headings: kept as prose, with a warning.
    heavy = "Jane Doe\nENGL 1101\n17 May 2026\nA Title Here\n\nShort text here now.\n"
    with caplog.at_level(logging.INFO, logger="original.features.matter"):
        assert matter.find_matter(heavy) == []
    assert "keeping them as prose" in caplog.text


def test_long_list_of_sources_is_logged(caplog):
    body = "\n".join([PROSE] * 12)
    sources = "\n".join(
        f"{name}, Ann. A Long Title of One More Book on the Subject. Press, 19{i}."
        for i, name in enumerate(["Abel", "Baker", "Cole", "Dunn", "Eliot", "Frye"], 10)
    )
    text = f"{body}\nWorks Cited\n{sources}\n"
    with caplog.at_level(logging.INFO, logger="original.features.matter"):
        parts = matter.find_matter(text)
    assert [p.kind for p in parts] == ["back_matter"]
    assert parts[0].end == len(text)
    assert "list of sources is" in caplog.text


def test_numbered_notes_are_back_matter_but_a_notes_paragraph_is_not():
    body = "\n\n".join([PROSE] * 4)
    notes = "1. Augustine, Confessions, 1991, 230.\n2. Ricoeur, Time, 1984, 7."
    text = f"{body}\n\nNotes\n{notes}"
    assert [p.kind for p in matter.find_matter(text)] == ["back_matter"]
    prose_notes = (
        f"{body}\n\nNotes\nSmith, John wrote 1991 letters. He said more and more.\nIt ended."
    )
    assert "back_matter" not in [p.kind for p in matter.find_matter(prose_notes)]


def test_unverified_heading_is_kept():
    body = "\n\n".join([PROSE] * 4)
    assert matter.find_matter(f"{body}\n\nReferences") == []  # nothing after it
    text = f"{body}\n\nReferences\nThe end of the essay comes after this heading, oddly."
    assert "back_matter" not in [p.kind for p in matter.find_matter(text)]


def test_edges():
    assert matter.find_matter("") == []
    assert matter.find_matter("\n\n") == []
    assert matter.kept_ranges("") == []
    assert matter.find_matter("Just One Title") == []  # nothing follows it
    assert matter.find_matter(PROSE) == []
    indented = PROSE + "\n\n    An Indented Line\n\n" + PROSE
    assert matter.find_matter(indented) == []
    trailing = PROSE + "\n\nA Heading At The End\n\n"
    assert matter.find_matter(trailing) == []


def test_kept_ranges_cover_everything_else():
    text = _text("chicago_pdf")
    parts = matter.find_matter(text)
    kept = matter.kept_ranges(text)
    covered = sorted([(p.start, p.end) for p in parts] + kept)
    pos = 0
    for a, b in covered:
        assert a == pos
        pos = b
    assert pos == len(text)


# ── Preprocess and evidence use the same ranges ──────────────────────────────


@pytest.mark.parametrize("name", NAMES)
def test_switch_off_is_the_old_body(name, monkeypatch):
    monkeypatch.delenv("MATTER_SPLITTER_ENABLED", raising=False)
    text = _text(name)
    assert pp.body_segments(text) == [(0, len(pp._strip_backmatter(text)))]
    assert pp._body(text) == pp._strip_backmatter(text)


@pytest.mark.parametrize("name", NAMES)
def test_switch_on_uses_the_matter_ranges(name, splitter_on):
    text = _text(name)
    assert pp.body_segments(text) == matter.kept_ranges(text)


@pytest.mark.parametrize("feature_set", ["1", "2"])
@pytest.mark.parametrize("name", NAMES)
def test_evidence_aligns_with_the_splitter_on(name, feature_set, splitter_on, monkeypatch):
    """With the splitter on (and either word-list version) the evidence view
    rebuilds the engine's text byte for byte, every locatable habit's located
    count equals its value, and no quote comes from a set-aside part."""
    monkeypatch.setenv("FEATURE_SET", feature_set)
    text = _text(name)
    view = ev.engine_view(text)
    assert view is not None
    aside = [(r.start, r.end) for r in matter.find_matter(text)]
    for code, spec in ev.LOCATABLE.items():
        reading = ev.read_paper(text, code)
        assert reading is not None
        assert reading.places is not None, f"{name}/{code}: located count disagreed"
        if spec.sentence_length is None:
            assert len(reading.places) == 0 or reading.value != 0.0
        for place in reading.places:
            assert not any(a <= place.start < b for a, b in aside), (name, code)


# ── Gaps closed for ADR-015: decorated headings, notes, cover letters ─────────

BIB_LINES = "\n".join(
    f"{name}, A. (19{i}). A long title of one more book on the subject. Press."
    for i, name in enumerate(["Abel", "Baker", "Cole", "Dunn"], 70)
)


@pytest.mark.parametrize(
    "heading",
    ["## References", "# Works Cited:", "7. References", "IV. Bibliography", "**References**",
     "__Works Cited__", "1) Works Cited", "### **References**"],
)  # fmt: skip
def test_decorated_list_headings_are_read(heading):
    body = "\n\n".join([PROSE] * 6)
    text = f"{body}\n\n{heading}\n\n{BIB_LINES}\n"
    parts = matter.find_matter(text)
    assert [p.kind for p in parts] == ["back_matter"]
    assert text[parts[0].start :].lstrip().startswith(heading)


def test_a_decorated_heading_still_needs_entries_after_it():
    body = "\n\n".join([PROSE] * 6)
    text = f"{body}\n\n## References\n\nThe essay goes on after this heading, which is odd.\n"
    assert "back_matter" not in _kinds(text)  # at most an ordinary section heading


def test_numbered_notes_without_years_are_notes():
    body = "\n\n".join([PROSE] * 6)
    notes = "1. See Berlin 131 on the two concepts.\n2. Gray argues the opposite.\n3. Ibid."
    assert [p.kind for p in matter.find_matter(f"{body}\n\nNotes\n\n{notes}\n")] == ["back_matter"]
    # Notes followed by a bibliography: the notes end at the next heading, so
    # the entries after it do not dilute them, and both are set aside.
    both = f"{body}\n\nNotes\n\n{notes}\n\nWorks Cited\n\n{BIB_LINES}\n"
    parts = matter.find_matter(both)
    assert [p.kind for p in parts] == ["back_matter"]
    assert both[parts[0].start :].startswith("Notes")
    # An empty Notes section is not trusted; the list after it still is.
    empty = f"{body}\n\nNotes\n\nWorks Cited\n\n{BIB_LINES}\n"
    parts = matter.find_matter(empty)
    assert parts[-1].kind == "back_matter"
    assert empty[parts[-1].start :].startswith("Works Cited")
    mixed = "1. See Berlin 131.\nA sentence that is not a note at all, said plainly.\n2. Ibid."
    assert "back_matter" not in _kinds(f"{body}\n\nNotes\n\n{mixed}\n")


LETTER = (
    "Dear Professor Hartley,\n\nPlease find my paper attached for the assignment.\n\n"
    "Sincerely,\nJordan Reyes\n"
)


def _kinds(text):
    return [p.kind for p in matter.find_matter(text)]


def test_a_letter_at_the_start_is_set_aside_and_logged(caplog):
    text = LETTER + "\n" + "\n\n".join([PROSE] * 6)
    with caplog.at_level(logging.INFO, logger="original.features.matter"):
        assert _kinds(text) == ["cover_letter"] * 4
    assert "setting aside a cover letter" in caplog.text
    kept = "".join(text[a:b] for a, b in matter.kept_ranges(text))
    assert "Dear" not in kept and "Jordan" not in kept and PROSE.strip() in kept


def test_a_letter_at_the_end_is_set_aside():
    text = "\n\n".join([PROSE] * 6) + "\n\n" + LETTER
    assert _kinds(text) == ["cover_letter"] * 4


def test_a_letter_needs_its_closing_and_its_place():
    body = "\n\n".join([PROSE] * 6)
    no_closing = "Dear Professor Hartley,\n\n" + body
    assert "cover_letter" not in _kinds(no_closing)
    middle = "\n\n".join([PROSE] * 3) + "\n\n" + LETTER + "\n" + "\n\n".join([PROSE] * 3)
    assert "cover_letter" not in _kinds(middle)  # a letter quoted mid-paper stays prose
    late_start = PROSE * 2 + "\n" + LETTER + "\n" + body  # a long line comes before it
    assert "cover_letter" not in _kinds(late_start)
    not_last = body + "\n\n" + LETTER + "\n" + PROSE  # prose follows the signature
    assert "cover_letter" not in _kinds(not_last)
    alone = LETTER  # nothing after it: no paper to set it aside from
    assert "cover_letter" not in _kinds(alone)


def test_a_signature_stops_at_a_blank_line_and_at_prose():
    text = (
        "Dear Ms. Park,\n\nHere is the essay.\n\nBest regards,\nSam Lee\n"
        "A full sentence that reads like prose follows here.\n\n" + "\n\n".join([PROSE] * 6)
    )
    parts = matter.find_matter(text)
    lines = [text[p.start : p.end].strip() for p in parts if p.kind == "cover_letter"]
    assert lines[-1] == "Sam Lee"


def test_a_long_letter_stays_prose_and_is_logged(caplog):
    long_letter = "Dear Professor Hartley,\n\n" + PROSE * 8 + "\n\nSincerely,\nJordan\n"
    text = long_letter + "\n" + "\n\n".join([PROSE] * 3)
    with caplog.at_level(logging.INFO, logger="original.features.matter"):
        assert "cover_letter" not in _kinds(text)
    assert "kept as prose" in caplog.text


def test_a_letter_is_kept_out_of_the_soft_share_and_survives_its_refusal():
    short_letter = "Dear Ms. Park,\nHere it is.\nThanks,\nSam\n"
    heavy = (
        short_letter
        + "\nJane Doe\nENGL 1101\n17 May 2026\nA Title Here\n\n"
        + "Short text here now and a few more words.\n"
    )
    kinds = _kinds(heavy)
    assert "front_matter" not in kinds  # the heading block was over the soft cap
    assert kinds.count("cover_letter") == 4


# ── Prose the splitter must keep (score-integrity review of #354) ─────────────


def _kept(text):
    return "".join(text[a:b] for a, b in matter.kept_ranges(text))


def test_a_numbered_paragraph_that_goes_on_after_a_citation_is_prose():
    body = "\n\n".join([PROSE] * 4)
    peter = (
        "1 Peter 2:9 calls the church a royal priesthood, a phrase Wright develops "
        "(Surprised by Hope, New York: HarperOne, 2008). The image matters here."
    )
    barth = (
        "1. First, Barth insists that revelation is an event "
        "(Church Dogmatics, Edinburgh: T&T Clark, 1956). He returns to it later."
    )
    for para in (peter, barth):
        text = f"{body}\n\n{para}\n\n{body}"
        assert para in _kept(text)
    # A numbered biblical book is never a note number, even when the line
    # ends on its citation.
    lone = "2 Corinthians 5:17 is quoted (New York: Doubleday, 1999), 12."
    assert matter._FOOTNOTE_LINE.match(lone) is None
    # Real note lines still are notes, with or without a page.
    for note in (
        "1. Augustine, Confessions (Oxford: Oxford University Press, 1991), 230.",
        "2. Ibid., 232.",
        "3. Ricoeur, Time and Narrative (Chicago: University of Chicago Press, 1984).",
    ):
        assert matter._FOOTNOTE_LINE.match(note), note
    assert matter._FOOTNOTE_LINE.match("1. see Augustine (Oxford: OUP, 1991), 230.") is None


def test_a_dated_opening_sentence_is_prose():
    king = "On April 16, 1963, Martin Luther King Jr. wrote from a Birmingham jail."
    text = king + "\n\n" + "\n\n".join([PROSE] * 4)
    assert king in _kept(text)
    assert "front_matter" not in _kinds(text)
    # A short date line with a full stop is still part of a heading block.
    block = "Jane Doe\nProf. Smith\nENGL 1101\n17 May 2026.\n\n" + "\n\n".join([PROSE] * 8)
    assert _kinds(block).count("front_matter") == 4


def test_a_long_list_after_a_few_long_paragraphs_is_found():
    """A docx paper: each paragraph one long line, so the list starts early in
    the paper's lines but late in its words."""
    header = "Jane Doe\nProf. Smith\nENGL 1101\n17 May 2026\nA Title Here\n"
    paras = "\n".join([PROSE * 18] * 3)
    entries = "\n".join(
        f"{name}, Ann. A Long Title of One More Book on the Subject. Press, 19{i}."
        for i, name in enumerate(
            ["Abel", "Baker", "Cole", "Dunn", "Eliot", "Frye", "Gold", "Hale", "Ives",
             "Jones", "Kerr", "Lane", "Moss", "Nash"],
            50,
        )
    )  # fmt: skip
    text = f"{header}{paras}\nWorks Cited\n{entries}\n"
    kinds = _kinds(text)
    assert kinds[-1] == "back_matter"
    assert "Abel, Ann" not in _kept(text)
