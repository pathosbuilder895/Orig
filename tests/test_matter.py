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
    "cover_letter_md": (0, 1, 0, 0, "## References"),
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
    sentence, outside any list of sources."""
    head = re.search(
        r"^\s*(?:#+\s*)?(?:works cited:?|references|bibliography)\s*$", text, re.I | re.M
    )
    body = text[: head.start()] if head and head.start() > len(text) * 0.4 else text
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


# ── ADR-015: decorated source headings; letters and year-less notes stay prose ─

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


LETTER = (
    "Dear Professor Hartley,\n\nPlease find my paper attached for the assignment.\n\n"
    "Sincerely,\nJordan Reyes\n"
)


def _kinds(text):
    return [p.kind for p in matter.find_matter(text)]


def test_letter_fragments_stay_prose():
    body = "\n\n".join([PROSE] * 6)
    no_closing = "Dear Professor Hartley,\n\n" + body
    assert _all_kept(no_closing)
    middle = "\n\n".join([PROSE] * 3) + "\n\n" + LETTER + "\n" + "\n\n".join([PROSE] * 3)
    assert _all_kept(middle)  # a letter quoted mid-paper stays prose
    late_start = PROSE * 2 + "\n" + LETTER + "\n" + body  # a long line comes before it
    assert _all_kept(late_start)
    not_last = body + "\n\n" + LETTER + "\n" + PROSE  # prose follows the signature
    assert _all_kept(not_last)
    alone = LETTER  # nothing after it: no paper to set it aside from
    assert _all_kept(alone)


# ── Prose the splitter must keep (score-integrity review of #354) ─────────────


def _all_kept(text):
    """Every line of the letter, salutation to signature, is measured."""
    kept = _kept(text)
    return all(
        ln.strip() in kept
        for ln in text.splitlines()
        if re.match(r"\s*(dear|to whom|sincerely|thank you|best|yours)\b", ln, re.I)
    )


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


# ── New rules keep prose (score-integrity review of the gap PR) ──────────────


def test_numbered_points_and_prose_after_notes_stay_prose():
    body = "\n\n".join([PROSE] * 12)
    notes = "\n".join(f"{i}. See Berlin 10{i} for the point." for i in range(1, 9))
    after = "\n".join([PROSE * 12] * 2)  # prose after the notes, unnumbered
    text = f"{body}\n\nNotes\n\n{notes}\n{after}\n"
    assert PROSE.strip() in _kept(text[text.index("Notes") :])
    assert "back_matter" not in _kinds(text)
    observations = "\n".join(
        f"{i}. The writer keeps returning to the same image because the argument "
        "has not been settled for them yet, and the return is the point."
        for i in range(1, 6)
    )
    for heading in ("Notes", "## Notes", "**Notes**"):
        essay = f"{body}\n\n{heading}\n\n{observations}\n"
        assert "back_matter" not in _kinds(essay), heading


def test_letter_shaped_student_writing_stays_prose():
    body = "\n\n".join([PROSE] * 6)
    sermon = f"{body}\n\nDear friends,\n\n{PROSE * 3}\n\nThank you.\n"
    assert _all_kept(sermon)
    assignment = (
        "Dear Senator Alvarez,\n\nI am writing to urge you to support the bill on rural "
        "clinics, which would bring care to my town.\n\nSincerely,\nJordan Reyes\n\n"
        f"Reflection\n\n{body}\n"
    )
    assert _all_kept(assignment)
    title = f"Dear John: Letters Home from the Front\n\n{PROSE * 2}\n\nBest wishes\n\n{body}\n"
    assert "Best wishes" in _kept(title) and PROSE.strip() in _kept(title)  # the title is a title
    long_note = (
        "Dear Professor Hartley,\n\n"
        + ("I attach my paper. " + PROSE * 4) * 4
        + "\n\nSincerely,\nJo\n"
    )
    assert _all_kept(long_note + "\n" + body * 6)


# ── Second review: strict by design ──────────────────────────────────────────


def test_prose_after_notes_and_a_short_list_is_measured():
    body = "\n\n".join([PROSE] * 10)
    mine = "Writing this reflection I noticed how my sources pulled me in two directions."
    reflection = "\n\n".join([mine + " " + PROSE * 3] * 3)
    text = (
        f"{body}\n\nNotes\n\n1. See Berlin 131.\n2. Ibid., 44.\n\nWorks Cited\n\n"
        f"Berlin, Isaiah. Four Essays on Liberty. Oxford UP, 1969.\n"
        f"Gray, John. Mill on Liberty. Routledge, 1996.\n\nReflection\n\n{reflection}\n"
    )
    assert mine in _kept(text)
    further = f"{body}\n\nNotes\n\n1. See p. 4.\n\nFurther Reading\n\n{reflection}\n"
    assert mine in _kept(further)


def test_numbered_points_with_numbers_in_them_are_not_notes():
    body = "\n\n".join([PROSE] * 10)
    for points in (
        "1. In 1963 the march on Washington drew a huge crowd\n"
        "2. King added 4 lines on the day\n3. The movement had grown since the 1950s",
        "1. The essay writes for 2 audiences at once\n2. The second part is step 3",
        "1. See how the writer turns the scene around at the end\n"
        "2. Notice the opening and the close",
    ):
        assert "back_matter" not in _kinds(f"{body}\n\nNotes\n\n{points}\n"), points


@pytest.mark.parametrize(
    "salutation",
    ["Dear Reader,", "Dear God,", "Dear Lord,", "Dear Diary,", "Dear Mom,", "Dear Theophilus,",
     "Dear Future Self,", "Dear friends,", "Dear Senator Alvarez,"],
)  # fmt: skip
def test_letters_to_anyone_stay_prose(salutation):
    body = "\n\n".join([PROSE] * 6)
    note = f"{salutation}\n\nPlease find my paper attached for the class.\n\nSincerely,\nAva\n"
    assert _all_kept(note + "\n" + body)
    assert _all_kept(body + "\n\n" + note)


def test_a_note_about_the_paper_stays_prose_too():
    body = "\n\n".join([PROSE] * 6)
    in_title = (
        "Letters Project\n\nDear Professor Hartley,\n\nYou will be fine.\n\nThank you,\nAva\n"
    )
    assert _all_kept(in_title + "\n" + body)
    class_word = (
        "Dear Professor Kim,\n\nI am a student in your civics class and the project our class "
        "did taught me a lot.\n\nSincerely,\nJordan Reyes\n"
    )
    assert _all_kept(class_word + "\n" + body)
    long_salutation = (
        "Dear Professor Hartley and the Members of the Committee,\n\nMy paper is attached.\n\n"
        "Sincerely,\nAva\n"
    )
    assert _all_kept(long_salutation + "\n" + body)


def test_an_epigraph_above_a_letter_stays_prose():
    epigraph = (
        "Because I could not stop for Death -\nHe kindly stopped for me -\n"
        "The Carriage held but just Ourselves -\nAnd Immortality.\n\n"
    )
    letter = "Dear Professor Hartley,\n\nHere is my essay, attached.\n\nSincerely,\nAva\n\n"
    text = epigraph + letter + "\n\n".join([PROSE] * 6)
    assert "He kindly stopped for me" in _kept(text)


def test_cover_letters_and_notes_without_years_are_measured_until_a_teacher_control():
    """The trade-off, stated: rules that guessed at cover letters and at notes
    without years kept setting a student's own writing aside, so neither is
    detected. Both stay prose until a teacher can mark a part herself."""
    body = "\n\n".join([PROSE] * 8)
    assert _kinds(LETTER + "\n" + body) == []
    assert _kinds(body + "\n\n" + LETTER) == []
    notes = "1. See Berlin 131 on the two concepts.\n2. Gray argues the opposite, 44.\n3. Ibid."
    assert "back_matter" not in _kinds(f"{body}\n\nNotes\n\n{notes}\n")


@pytest.mark.parametrize("heading", ["## Notes", "**Notes**", "3. Notes"])
def test_a_decorated_notes_heading_is_not_trusted(heading):
    """Decoration is read for lists of sources only: prose under a "## Notes"
    stays prose, whatever follows."""
    body = "\n\n".join([PROSE] * 6)
    mine = "A translator's note in my own words that the reader should keep."
    text = f"{body}\n\n{heading}\n\n{mine}\n\n## References\n\n{BIB_LINES}\n"
    assert mine in _kept(text)
    assert "Abel, A." not in _kept(text)  # the decorated list after it is still found


def test_a_later_decorated_list_cannot_vouch_for_prose_above_it():
    body = "\n\n".join([PROSE] * 6)
    mine = "Writing this reflection I noticed how my sources pulled me apart."
    entries = "\n".join(BIB_LINES.splitlines()[:2])
    text = f"{body}\n\nFurther Reading\n\n{mine}\n\n{mine}\n\n## References\n\n{entries}\n"
    assert mine in _kept(text)


# ── Step 3 of the document-parts plan: page breaks, title pages, abstracts,
#    more list headings, appendices, unheaded lists and notes ────────────────

FF = matter.PAGE_BREAK
PARA = (
    "The writer returns to the question of authority in every section of the "
    "paper, and each return adds a small qualification to the claim before it. "
)


def _body(n: int = 8) -> str:
    return "\n\n".join([PARA * 2] * n)


def _aside(text):
    return "".join(text[r.start : r.end] for r in matter.find_matter(text))


def _possible(text):
    return [(r.kind, text[r.start : r.end].strip()) for r in matter.find_parts(text).possible]


APA_TITLE = (
    "A Strong Rod Broken: Rulers and Grief\n\nHannah Price\n\n"
    "Department of Homiletics, Westfield College\n\nHOMI 520: Preaching\n\n"
    "Dr. Peter Vance\n\nMarch 14, 2026"
)


def test_the_first_page_of_an_upload_is_a_title_page():
    text = APA_TITLE + FF + _body()
    parts = matter.find_matter(text)
    assert parts[0].kind == "title_page"
    assert text[parts[0].start : parts[0].end].strip().endswith("March 14, 2026")
    assert PARA.strip() in _kept(text)


def test_a_professional_title_page_with_its_author_note_is_a_title_page():
    page = (
        "Running head: A STRONG ROD BROKEN\n\nA Strong Rod Broken\n\nHannah Price\n\n"
        "Westfield College\n\nAuthor Note\n\nHannah Price is an undergraduate student in the "
        "Department of Homiletics. Correspondence concerning this paper should be addressed "
        "to Hannah Price. Email: hp@example.edu"
    )
    text = page + FF + _body()
    assert [r.kind for r in matter.find_matter(text)][:1] == ["title_page"]
    assert "Correspondence concerning" in _aside(text)


def test_a_first_page_of_prose_or_without_a_signal_is_not_a_title_page():
    prose_first = PARA * 2 + FF + _body()
    assert "title_page" not in _kinds(prose_first)
    poem = "Because I could not stop for Death\n\nHe kindly stopped for me\n\nThe Carriage held"
    text = poem + FF + _body()
    assert "title_page" not in _kinds(text)
    assert "He kindly stopped for me" in _kept(text)
    assert ("title_page", poem) in _possible(text)  # listed for the teacher, measured


@pytest.mark.parametrize(
    "line",
    ["Running head: THE STRONG ROD", "A Paper Submitted to Dr. Peter Vance",
     "In Partial Fulfilment of the Requirements", "Presented to the Faculty", "Spring 2026",
     "05/02/2026", "Northfield Theological Seminary", "by"],
)  # fmt: skip
def test_title_page_signals_in_pasted_text(line):
    text = f"A Strong Rod Broken\n{line}\nHannah Price\n\n{_body()}"
    assert _kinds(text).count("front_matter") == 3, line
    assert PARA.strip() in _kept(text)


def test_a_pasted_author_note_paragraph_goes_with_its_title_page_but_prose_stops_it():
    text = (
        "Running head: A STRONG ROD\nA Strong Rod Broken\nHannah Price\nAuthor Note\n"
        "Hannah Price is a student. Correspondence should be addressed to her.\n"
        "Abstract\n" + ("This paper studies a funeral sermon and its account of rule. " * 6)
        + "\nKeywords: sermon, rulers\n" + _body()
    )
    aside = _aside(text)
    assert "Correspondence should be addressed" in aside
    assert "This paper studies a funeral sermon" in aside  # the abstract
    assert PARA.strip() in _kept(text)


ABSTRACT = "This paper studies a funeral sermon and the account of public authority it gives. " * 5


@pytest.mark.parametrize("head", ["Abstract", "**Abstract**", "## Abstract", "ABSTRACT"])
def test_an_abstract_and_its_keywords_are_set_aside(head):
    text = f"A Title Of The Paper\n\n{head}\n\n{ABSTRACT}\n\nKeywords: sermon, rulers\n\n{_body()}"
    parts = [r for r in matter.find_matter(text) if r.kind == "abstract"]
    assert len(parts) == 1
    block = text[parts[0].start : parts[0].end]
    assert head in block and "funeral sermon" in block and "Keywords: sermon" in block
    assert PARA.strip() in _kept(text)


def test_an_abstract_ends_at_a_heading_or_a_page_break():
    for after in ("\n\nIntroduction\n\n", FF):
        text = f"Abstract\n\n{ABSTRACT}{after}{_body()}"
        assert "funeral sermon" in _aside(text), repr(after)
        assert PARA.strip() in _kept(text)
    inline = f"Abstract: {ABSTRACT}\n\nIntroduction\n\n{_body()}"
    assert "funeral sermon" in _aside(inline)


def test_an_abstract_with_no_clear_end_is_only_possible():
    """No heading, page break or keywords line after the abstract: the rule
    cannot tell where the abstract stops, so it is measured and listed."""
    text = f"Abstract\n\n{ABSTRACT}\n\n{_body(14)}"
    assert "abstract" not in _kinds(text)
    assert ABSTRACT.strip()[:40] in _kept(text)
    assert any(kind == "abstract" for kind, _ in _possible(text))


def test_the_word_abstract_in_prose_is_never_an_abstract():
    for opening in (
        "Abstract as this distinction may sound, it decides the whole argument.",
        "The abstract nature of the question is what makes it hard to answer.",
        "In the abstract, everyone agrees; in practice nobody does.",
    ):
        text = f"{opening} {PARA}\n\n{_body()}"
        assert "abstract" not in _kinds(text), opening
        assert opening in _kept(text)


ENTRIES = "\n\n".join(
    f"{name}, A. (19{i}). A long title of one more book on the subject. Press."
    for i, name in enumerate(["Abel", "Baker", "Cole", "Dunn", "Eliot", "Frye"], 70)
)


@pytest.mark.parametrize(
    "heading", ["Reference List", "Literature Cited", "Annotated Bibliography", "References Cited"]
)
def test_more_list_headings(heading):
    text = f"{_body()}\n\n{heading}\n\n{ENTRIES}\n"
    assert _kinds(text)[-1:] == ["back_matter"]
    assert "Abel, A." not in _kept(text)


def test_a_short_paper_with_a_long_list_is_measured_by_words_not_lines():
    short = "\n\n".join([PARA * 3] * 3)  # about 200 words in 3 lines
    many = "\n".join(
        f"{n}, Jo. A Title of a Book on the Subject. Press, 19{i:02d}."
        for i, n in enumerate(["Abel", "Baker", "Cole", "Dunn", "Eliot", "Frye", "Gray",
                               "Hart", "Ives", "Jones", "Keller", "Lowe"])
    )  # fmt: skip
    text = f"{short}\n\nWorks Cited\n\n{many}\n"
    assert _kinds(text) == ["back_matter"]
    assert PARA.strip() in _kept(text)


def test_an_early_list_after_a_page_break_is_trusted_but_not_before_prose():
    text = PARA * 3 + FF + "References" + FF.replace("\f", "") + ENTRIES
    assert "back_matter" in _kinds(text)
    later = f"{PARA}\n\nReferences\n\n{ENTRIES}\n\n{_body(6)}"
    assert "back_matter" not in _kinds(later)  # the paper goes on after the list
    assert PARA.strip() in _kept(later)


def test_entries_without_a_year_count_with_a_url_or_nd():
    undated = "\n\n".join(
        [
            "Center for Reading. Guide to Primary Sources. https://example.org/guide.",
            "Writing Center. Writing About Texts. (n.d.). Westfield College.",
            "Library Guide. Citing Classical Texts. www.example.edu/classical",
        ]
    )
    text = f"{_body()}\n\nBibliography\n\n{undated}\n"
    assert _kinds(text) == ["back_matter"]


def test_wrapped_entries_count_once():
    """A PDF wraps an entry over two lines; the second line does not start
    like an entry, so line by line the list fails. Counted whole it passes."""
    wrapped = "\n".join(
        [
            'Hollis, Margaret A. "Reading Historical Sources in the Undergraduate',
            "Classroom.\" Journal of Humanities Pedagogy 14, no. 2 (2019): 115-132.",
            "Pelikan, Jaroslav. The Emergence of the Catholic Tradition (100-600). Chicago:",
            "University of Chicago Press, 1971.",
            "Stout, Harry S. The New England Soul: Preaching and Religious Culture in",
            "Colonial New England. New York: Oxford University Press, 1986.",
        ]
    )
    text = f"{_body()}\nBibliography\n{wrapped}\n"
    assert _kinds(text)[-1:] == ["back_matter"]


def test_a_list_ends_at_an_appendix_and_the_appendix_is_measured():
    mine = "In the appendix I set out the interview questions in my own words, as asked."
    text = f"{_body()}\n\nReferences\n\n{ENTRIES}\n\nAppendix A: Interview Questions\n\n{mine}\n"
    back = [r for r in matter.find_matter(text) if r.kind == "back_matter"]
    assert len(back) == 1 and "Abel, A." in text[back[0].start : back[0].end]
    assert mine in _kept(text)
    assert "Appendix A" not in text[back[0].start : back[0].end]


def test_a_mid_paper_references_sentence_and_a_lone_heading_stay_prose():
    mid = "References to Augustine in this paper follow the Chadwick translation throughout."
    text = f"{_body(4)}\n\n{mid}\n\n{_body(4)}"
    assert mid in _kept(text) and "back_matter" not in _kinds(text)


def test_an_unheaded_list_at_the_end_is_set_aside():
    text = f"{_body()}\n\n{ENTRIES}\n"
    assert _kinds(text)[-1:] == ["back_matter"]
    assert "Abel, A." not in _kept(text) and PARA.strip() in _kept(text)


def test_a_weak_unheaded_list_is_only_possible():
    three = "\n\n".join(ENTRIES.split("\n\n")[:3])
    text = f"{_body()}\n\n{three}\n"
    assert "back_matter" not in _kinds(text)
    assert "Abel, A." in _kept(text)
    assert any(kind == "back_matter" for kind, _ in _possible(text))


def test_a_short_paper_whose_last_paragraph_is_prose_keeps_it():
    last = (
        "Rawls, writing in 1971, gave the argument its modern form. Gray, in 1996, "
        "defended it again. Both, I think, missed what the sermon saw."
    )
    text = "\n\n".join([PARA * 2] * 3) + "\n\n" + last + "\n"
    assert matter.find_matter(text) == []
    assert last in _kept(text)


def test_a_sermons_closing_prayer_and_a_letter_assignment_stay_prose():
    prayer = "Let us pray.\nO Lord, keep us faithful.\nTeach us to number our days.\nAmen."
    sermon = f"{_body()}\n\n{prayer}\n"
    assert all(line in _kept(sermon) for line in prayer.splitlines())
    letter = (
        "Dear Thomas,\n\n" + _body(4) + "\n\nWith affection,\nHannah\n"
    )  # a letter-to-a-friend assignment
    assert "Dear Thomas," in _kept(letter) and "With affection," in _kept(letter)
    paged = letter.replace("\n\nWith affection", FF + "With affection")
    assert "With affection," in _kept(paged)


NOTES = (
    "1. Jonathan Edwards, Sermons and Discourses (New Haven: Yale University Press, 2003), 216.\n\n"
    "2. Ibid., 179.\n\n"
    "3. George M. Marsden, Jonathan Edwards: A Life (New Haven: Yale University Press, 2003), 78.\n\n"
    "4. Edwards, Strong Rod, 72.\n\n"
    '5. Tunde Adeyemi, "Primary Texts," Teaching Philosophy Today 8, no. 1 (2021): 57.\n\n'
    "6. Marsden, Jonathan Edwards, 136."
)


def test_endnotes_with_their_short_notes_are_set_aside():
    text = f"{_body()}\n\nNotes\n\n{NOTES}\n\nBibliography\n\n{ENTRIES}\n"
    aside = _aside(text)
    assert "4. Edwards, Strong Rod, 72." in aside and "6. Marsden" in aside
    assert PARA.strip() in _kept(text)


def test_numbered_points_under_notes_are_still_prose():
    points = "\n\n".join(
        f"{i}. The writer keeps returning to image {i} because the argument is unsettled."
        for i in range(1, 5)
    )
    text = f"{_body()}\n\nNotes\n\n{points}\n"
    assert "1. The writer keeps returning" in _kept(text)


def test_footnotes_at_a_pages_foot_are_set_aside():
    page1 = "The sentence is famous because it is honest.1 It names a problem.2 " + PARA
    notes1 = "1 Augustine, Confessions, trans. Chadwick (Oxford: OUP, 1991), 230.\n2 Ibid., 232."
    page2 = "Time, he concludes, is a distension of the mind.3 " + PARA
    notes2 = "3 Marsden, Jonathan Edwards, 63."
    text = f"{page1}\n\n{notes1}{FF}{page2}\n\n{notes2}{FF}Bibliography\n\n{ENTRIES}\n"
    aside = _aside(text)
    assert "1 Augustine" in aside and "2 Ibid." in aside and "3 Marsden" in aside
    assert "The sentence is famous" in _kept(text) and "Time, he concludes" in _kept(text)


def test_a_numbered_line_without_its_marker_is_not_a_footnote():
    page1 = "A page of prose with no note markers at all. " + PARA
    text = f"{page1}\n\n1 Peter writes to the scattered churches.{FF}{PARA}\n"
    assert "1 Peter writes" in _kept(text)


def test_parts_are_consistent_with_kept_ranges():
    text = APA_TITLE + FF + f"Abstract\n\n{ABSTRACT}\n\nKeywords: a, b" + FF + _body()
    text += FF + f"References\n\n{ENTRIES}\n\nAppendix A\n\n{PARA}\n"
    parts = matter.find_matter(text)
    kinds = [p.kind for p in parts]
    assert kinds[:2] == ["title_page", "abstract"] and "back_matter" in kinds
    covered = sorted([(p.start, p.end) for p in parts] + matter.kept_ranges(text))
    pos = 0
    for a, b in covered:
        assert a == pos
        pos = b
    assert pos == len(text)


def test_verses_and_numbered_points_at_a_pages_foot_stay_prose():
    """Score-integrity witness: Romans 8:1 and 8:2 are verses, not note
    markers, and the student's own numbered points ending a page are not
    footnotes (no citation shape). Before the fix all 52 words were set aside."""
    p = (
        "Paul writes in Romans 8:1 that there is no condemnation, and in 8:2 he explains why "
        "the law of the Spirit sets us free. This paper argues that the passage has three "
        "practical consequences for pastoral care today, which I set out below. "
    )
    p2 = (
        "The second section turns to the wider argument of the letter and how the church "
        "received it over the centuries, with attention to the way the claims were preached. "
    ) * 3
    items = [
        "1. The believer is no longer under the sentence of the law, so pastoral care begins "
        "from assurance.",
        "2. The Spirit, not willpower, is the agent of change, so counsel should point there first.",
        "3. Suffering is not a sign of rejection, and the pastor can say so plainly to the grieving.",
    ]
    text = p * 2 + "\n\n" + "\n\n".join(items) + FF + p2 + "\n\n" + p2
    assert matter.find_matter(text) == []
    assert len(pp._body(text).split()) == len(text.split())


@pytest.mark.parametrize(
    "prose, number",
    [("Romans 8:1 says", 1), ("in 8:2 he", 2), ("verse 3:16-17 reads", 17), ("pages 12-14.", 12),
     ("see pp.12-14", 12), ("chapter 1: the start", 1)],
)  # fmt: skip
def test_a_verse_or_a_range_is_never_a_note_marker(prose, number):
    assert not matter.has_note_marker(number, prose)


@pytest.mark.parametrize("prose, number", [("him?6 We", 6), ("xi.2 3.", 2), ("rod_.5", 5), ("why.3 The", 3)])
def test_a_superscript_note_number_is_a_marker(prose, number):
    assert matter.has_note_marker(number, prose)


def test_page_bottom_footnotes_count_toward_the_soft_cap(caplog):
    """Footnotes at a page's foot are a soft part: a page that is mostly
    numbered, cited lines under very little prose is kept as prose."""
    page = "Short prose.1 More.2 And.3"
    notes = "\n".join(
        f"{i} Augustine, Confessions, trans. Chadwick (Oxford: OUP, 1991), {200 + i}."
        for i in (1, 2, 3)
    )
    text = f"{page}\n\n{notes}{FF}{PARA}\n"
    with caplog.at_level(logging.WARNING, logger="original.features.matter"):
        assert "footnote" not in _kinds(text)
    assert "keeping them as prose" in caplog.text
    assert any(kind == "footnote" for kind, _ in _possible(text))


def test_dotted_references_and_unmarked_points_are_not_footnotes():
    """Second score-integrity witness: dotted references ("Romans 8.1",
    "Institutes 3.2.7") are not note markers, an author-date bracket is not a
    note citation, and the student's three numbered points ending a page stay
    prose (61 of 441 words were set aside before the fix)."""
    p = (
        "Calvin reads Romans 8.1 as the hinge of the letter, and his exposition in the "
        "Institutes 3.2.7 develops it at length for the church. This paper argues that the "
        "reading has three practical consequences for pastoral care, which I set out below. "
    ) * 3
    items = [
        "1. Assurance comes first, as Webster argues (2003), so pastoral care begins from the "
        "gift and not the demand.",
        "2. The Spirit, not willpower, is the agent of change, as Barth insists (1956), so "
        "counsel should point there first.",
        "3. Suffering is not a sign of rejection, as Calvin says (1559), and the pastor can say "
        "so plainly to the grieving.",
    ]
    p2 = (
        "The second section turns to the wider argument of the letter and how the church "
        "received it over the centuries, with attention to the way the claims were preached. "
    ) * 4
    for brk in (FF, matter.PDF_PAGE_BREAK):
        text = p + "\n\n" + "\n\n".join(items) + brk + p2 + "\n\n" + p2
        assert matter.find_matter(text) == []
        assert len(pp._body(text).split()) == len(text.split())
        assert any(kind == "footnote" for kind, _ in _possible(text))  # listed, measured


@pytest.mark.parametrize(
    "prose, number",
    [("Romans 8.1 as", 1), ("Institutes 3.2.7 develops", 7), ("Institutes 3.2.7", 2),
     ("Isaiah 53.5 says", 5), ("in v.3 he", 3), ("in vv.4-5", 4), ("section 2.1 shows", 1)],
)  # fmt: skip
def test_a_dotted_reference_is_never_a_note_marker(prose, number):
    assert not matter.has_note_marker(number, prose)


def test_a_marker_on_an_earlier_page_does_not_vouch_for_a_block():
    page1 = "The sentence is famous because it is honest.1 " + PARA
    page2 = PARA + "\n\n1 Marsden, Jonathan Edwards, 63."
    text = f"{page1}{FF}{page2}{FF}{PARA}\n"
    assert "1 Marsden" in _kept(text)
    same_page = f"{page1}\n\n1 Marsden, Jonathan Edwards, 63.{FF}{PARA}\n"
    assert "1 Marsden" not in _kept(same_page)  # the marker above it, on its page
