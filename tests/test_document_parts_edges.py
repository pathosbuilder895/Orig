"""Edge shapes of the document-parts code that the sample papers do not reach:
``features/matter.py`` (a paper that is nothing but its parts, a page break
with nothing after it, a Notes section, a note that runs on too long),
``features/pdf_reflow.py`` (lines a reflow must leave alone),
``paper_profile.py`` (an unheaded list, a numbered appendix, author-year
citations), ``upload_utils.py`` (Word's rendered page breaks, an empty
document) and ``features/part_overrides.py`` (a choice that no longer fits).
"""

from __future__ import annotations

import io

import numpy as np
import pytest

from original import paper_profile as pp
from original import upload_utils as uu
from original.constants import FEATURE_DIM
from original.features import feature_flags as ff
from original.features import part_overrides as po
from original.features import pdf_reflow
from original.features.matter import PAGE_BREAK, PAGE_MARK, find_parts
from original.quantum.state import BaselineSample

ENTRIES = [
    "Adams, John. A Book About Rivers. Penguin, 2001.",
    "Baker, Sue. Another Book. Norton, 2010.",
    "Clark, Tim. Water and Towns. Vintage, 2015.",
    "Davis, Ann. Town Life. Knopf, 2018.",
    "Evans, Bo. The Long River. Scribner, 2019.",
]
SENTENCE = "The river runs past the town and the people who live there know it well. "
PROSE = SENTENCE * 20


def _kinds(text: str) -> tuple[list[str], list[str]]:
    parts = find_parts(text)
    return [r.kind for r in parts.set_aside], [r.kind for r in parts.possible]


def _part(text: str, kind: str):
    (r,) = [r for r in find_parts(text).set_aside if r.kind == kind]
    return text[r.start : r.end]


# ── features/matter.py ───────────────────────────────────────────────────────


def test_a_paper_that_is_only_a_list_is_not_set_aside_from_itself():
    """An unheaded list needs prose before it: entries alone are the paper."""
    assert _kinds("\n\n".join(ENTRIES)) == ([], [])


def test_a_list_of_sources_at_the_very_top_leaves_no_heading_block():
    text = "Works Cited\n\n" + "\n\n".join(ENTRIES)
    assert _kinds(text) == (["back_matter"], [])


def test_a_page_break_with_nothing_after_it_makes_no_title_page():
    text = "My Title\n\n" + SENTENCE * 5 + PAGE_BREAK
    set_aside, possible = _kinds(text)
    assert "title_page" not in set_aside and "title_page" not in possible


def test_a_long_first_page_is_not_a_title_page_even_a_possible_one():
    text = "Name\n\n" + SENTENCE * 30 + PAGE_BREAK + "More prose follows on the next page of it."
    set_aside, possible = _kinds(text)
    assert "title_page" not in set_aside and "title_page" not in possible


def test_a_possible_title_page_already_set_aside_as_a_heading_is_not_listed_twice():
    """A lone title on its own page has no title-page signal (only possible),
    but the line is set aside as the heading block, so it is not offered."""
    text = "My River Paper" + PAGE_BREAK + PROSE
    assert _kinds(text) == (["front_matter"], [])


def test_an_author_note_running_up_to_the_list_of_sources_ends_the_heading_block():
    text = (
        "Jane Doe\nProfessor Smith\nENGL 101\nMay 3, 2024\nAuthor Note\n"
        "I thank my teacher for help with this paper and my family for their patience."
        "\n\nWorks Cited\n\n" + "\n\n".join(ENTRIES)
    )
    parts = find_parts(text)
    assert [r.kind for r in parts.set_aside] == ["back_matter"]
    # The heading block would be every word the rules keep: kept as prose and
    # offered line by line, the note's paragraph included.
    offered = [text[r.start : r.end].strip() for r in parts.possible]
    assert offered[0] == "Jane Doe" and offered[-1].startswith("I thank my teacher")
    assert {r.kind for r in parts.possible} == {"front_matter"}


def test_an_abstract_that_runs_to_the_end_of_the_paper_is_only_possible():
    text = "Abstract\n\n" + "This study looks at how rivers shape towns and people. " * 6
    set_aside, possible = _kinds(text)
    assert "abstract" not in set_aside and possible == ["abstract"]


NOTES = (
    "Notes\n\n1. Augustine, Confessions (Oxford: Oxford University Press, 1991), 230."
    "\n\n2. Ibid., 232.\n\n3. Augustine, Confessions, 240."
)


def test_a_notes_section_is_set_aside_whole():
    text = PROSE + "\n\n" + NOTES
    assert _kinds(text) == (["notes"], [])
    assert _part(text, "notes").strip() == NOTES


def test_an_appendix_ends_a_notes_section_and_is_measured():
    text = PROSE + "\n\n" + NOTES + "\n\nAppendix A\n\nThe survey asked ten questions."
    assert _part(text, "notes").strip() == NOTES
    assert all("survey" not in text[r.start : r.end] for r in find_parts(text).set_aside)


def test_a_note_at_a_pages_foot_that_runs_past_the_limit_is_prose():
    wrapped = "\n".join(["and this note keeps going on about the book in some detail " * 2] * 5)
    page = (
        "Augustine says the heart is restless.1 Then the paper goes on with its own reading. " * 3
        + "\n1. Augustine, Confessions (Oxford: Oxford University Press, 1991), 230.\n"
        + wrapped
    )
    text = page + PAGE_BREAK + PROSE
    parts = find_parts(text)
    # Not a footnote block: only the citation line itself reads as a
    # footnote; the paragraph under it stays measured and is not offered.
    assert [text[r.start : r.end].strip() for r in parts.set_aside] == [
        "1. Augustine, Confessions (Oxford: Oxford University Press, 1991), 230."
    ]
    assert parts.possible == []


# ── features/pdf_reflow.py ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "between",
    ["\n\n", "\n" + PAGE_MARK * 2 + "\n" + PAGE_MARK * 2 + "\n"],
    ids=["blank line", "an empty page"],
)
def test_lines_already_apart_are_not_reflowed(between):
    body = "the first line of a page that wraps" + between + "on to the next one here."
    assert pdf_reflow.reflow_ops(body) == []


# ── paper_profile.py ─────────────────────────────────────────────────────────


def test_an_unheaded_list_has_no_list_name_and_keeps_its_first_entry():
    text = PROSE + "\n\n" + "\n\n".join(ENTRIES)
    assert "back_matter" in _kinds(text)[0]
    profile = pp.paper_profile(text)
    assert profile["sources"]["list_heading"] is None
    assert profile["sources"]["count"] == len(ENTRIES)


def test_a_page_number_after_an_unheaded_list_is_not_an_appendix():
    text = PROSE + "\n\n" + "\n\n".join(ENTRIES) + "\n\n12"
    kinds = [p["kind"] for p in pp.paper_parts(text)]
    assert "back_matter" in kinds and "appendix" not in kinds


def test_author_year_citations_without_a_comma_read_as_chicago_author_date():
    body = (
        "Sleep shapes memory (Walker 2017). Others agree (Stickgold 2013). "
        "The effect is large (Diekelmann and Born 2010). "
    ) * 3
    style = pp.paper_profile(PROSE + body)["citation_style"]
    assert style["guess"] == "Chicago author-date"
    assert "author and the year" in " ".join(style["signs"])


def test_a_part_with_no_visible_line_shows_an_empty_first_line():
    from original.features.matter import MatterRange, Parts

    text = "Prose here.\n\n" + PAGE_MARK + "\n\nMore prose."
    blank = MatterRange(len("Prose here."), len("Prose here.\n\n" + PAGE_MARK + "\n"), "heading")
    (part,) = pp.paper_parts(text, Parts([blank], []))
    assert part["first_line"] == "" and part["words"] == 0


def test_a_chosen_range_of_only_page_markers_is_not_listed(monkeypatch):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    monkeypatch.setenv("PAPER_PROFILE_ENABLED", "1")
    text = "Prose here.\n" + PAGE_MARK + "\nMore prose here."
    mark = (len("Prose here.\n"), len("Prose here.\n" + PAGE_MARK + "\n"))
    chosen = po.chosen(text, po.PartOverride(exclude=(mark,)))
    assert all(p["kind"] != "chosen" for p in pp.paper_parts(chosen))


# ── upload_utils.py ──────────────────────────────────────────────────────────


def _docx(build) -> bytes:
    from docx import Document

    doc = Document()
    build(doc)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_words_rendering_of_a_page_break_before_a_paragraph_is_a_page_break():
    """Word records where it last broke a page (``w:lastRenderedPageBreak``)
    in a paragraph that starts a new page; after the text it is not a break."""
    from docx.oxml import OxmlElement

    def build(doc):
        doc.add_paragraph("First page prose.")
        p = doc.add_paragraph()
        run = p.add_run()
        run._r.append(OxmlElement("w:lastRenderedPageBreak"))
        run.add_text("Second page prose.")
        tail = doc.add_paragraph("Still the second page.")
        tail.runs[0]._r.append(OxmlElement("w:lastRenderedPageBreak"))

    text = uu.extract_text_from_bytes(_docx(build), "p.docx")
    assert text == (
        "First page prose." + PAGE_BREAK + "Second page prose.\n\nStill the second page."
    )


def test_a_docx_with_no_words_is_empty():
    def build(doc):
        doc.add_paragraph("")
        doc.add_paragraph("   ")

    assert uu.extract_text_from_bytes(_docx(build), "p.docx") == ""


# ── features/part_overrides.py ───────────────────────────────────────────────

MLA_LIKE = "Jane Doe\n\nTitle\n\n" + PROSE + "\n\n" + SENTENCE * 10


def _paper(doc) -> BaselineSample:
    return BaselineSample(
        text=MLA_LIKE,
        vector=np.full(FEATURE_DIM, 0.5),
        provenance="verified",
        auth_weight=1.0,
        extra_vectors={"matter": np.full(FEATURE_DIM, 0.25)},
        part_overrides=doc,
    )


def _choice() -> po.PartOverride:
    start = MLA_LIKE.rindex("\n\n") + 2  # the last paragraph
    return po.validate(MLA_LIKE, [[start, len(MLA_LIKE)]], None)


def test_a_choice_for_another_text_is_never_served(monkeypatch):
    """The paper's text changed after the choice was made: its measurement
    with the choice is not served; the rules' own is."""
    from original import measurement

    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    monkeypatch.setenv("PAPER_PROFILE_ENABLED", "1")
    doc = po.to_stored(_choice(), MLA_LIKE, {"matter": np.full(FEATURE_DIM, 0.75)})
    paper = _paper(doc)
    assert np.allclose(measurement.vector_for(paper, "matter"), 0.75)
    paper.text = MLA_LIKE + " An added sentence."
    assert po.choice_vector(paper, "matter") is None
    assert np.allclose(measurement.vector_for(paper, "matter"), 0.25)


def test_measuring_a_stored_choice_needs_a_valid_choice_and_the_splitter():
    calls: list[str] = []

    def extract(text):
        calls.append(ff.current_measurement())
        return np.full(FEATURE_DIM, 0.75)

    good = _paper(po.to_stored(_choice(), MLA_LIKE))
    assert po.measure_stored_choice(good, "fs2", extract) is None
    assert po.measure_stored_choice(_paper(None), "matter", extract) is None
    assert calls == []
    assert np.allclose(po.measure_stored_choice(good, "matter", extract), 0.75)
    assert calls == ["matter"]
