"""Uploads keep a paper's page structure (step 2 of the document-parts plan).

``original.upload_utils.extract_text_from_bytes`` is the one extractor every
upload route uses. It stores a page break as ``matter.PAGE_BREAK`` (a form
feed on its own line, where a blank line stood before), and with
``MATTER_SPLITTER_ENABLED`` on it also restructures a PDF's pages (running
heads and page numbers out, wrapped lines joined, footnotes moved under the
paragraph they interrupted).

The guarantee that matters: a page break is never measured. A paper with page
breaks gives exactly the feature vector, evidence view and score of the same
paper with blank lines, switch off or on, and the extractor with the switch
off returns exactly the old text once its page breaks are dropped.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import numpy as np
import pytest

from original import evidence as ev
from original import upload_utils as uu
from original.features import matter
from original.features import preprocess as pp
from original.features.matter import PAGE_BREAK, without_page_breaks
from original.features.pipeline import feature_vector

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "validation" / "diagnostics" / "document_parts_v2" / "samples"
CORPUS = ROOT / "validation" / "public_authors" / "corpus"


def _old_docx(raw: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(raw))
    return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _old_pdf(raw: bytes) -> str:
    from pypdf import PdfReader

    return "\n\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)


def _docx(build) -> bytes:
    from docx import Document

    doc = Document()
    build(doc)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ── .docx page breaks ────────────────────────────────────────────────────────


def test_docx_page_breaks_of_every_kind_become_form_feeds():
    from docx.enum.section import WD_SECTION
    from docx.enum.text import WD_BREAK

    def build(doc):
        doc.add_paragraph("Title Page Line")
        brk = doc.add_paragraph()  # Ctrl+Enter: a paragraph holding only a break
        brk.add_run().add_break(WD_BREAK.PAGE)
        doc.add_paragraph("Abstract")
        doc.add_paragraph("The abstract text.")
        after = doc.add_paragraph("Ends its page.")
        after.add_run().add_break(WD_BREAK.PAGE)  # a break after the text
        doc.add_paragraph("Body paragraph one.")
        doc.add_paragraph("Body paragraph two.")
        doc.add_section(WD_SECTION.NEW_PAGE)  # a section break starting a new page
        doc.add_paragraph("Next section.")
        doc.add_section(WD_SECTION.CONTINUOUS)  # no new page
        doc.add_paragraph("Same page.")
        styled = doc.add_paragraph("References")
        styled.paragraph_format.page_break_before = True
        doc.add_paragraph("Smith, J. (2020). A book. Press.")

    raw = _docx(build)
    text = uu.extract_text_from_bytes(raw, "paper.docx")
    assert text == (
        "Title Page Line" + PAGE_BREAK + "Abstract\n\nThe abstract text.\n\nEnds its page."
        + PAGE_BREAK + "Body paragraph one.\n\nBody paragraph two." + PAGE_BREAK
        + "Next section.\n\nSame page." + PAGE_BREAK + "References\n\n"
        "Smith, J. (2020). A book. Press."
    )  # fmt: skip
    assert without_page_breaks(text) == _old_docx(raw)


def test_a_style_that_starts_a_new_page_is_read():
    def build(doc):
        doc.styles["Heading 1"].paragraph_format.page_break_before = True
        doc.add_paragraph("First page prose.")
        doc.add_paragraph("Works Cited", style="Heading 1")
        doc.add_paragraph("Smith, Jo. A Book. Press, 2020.")

    text = uu.extract_text_from_bytes(_docx(build), "p.docx")
    assert text == "First page prose." + PAGE_BREAK + "Works Cited\n\nSmith, Jo. A Book. Press, 2020."


def test_a_break_before_the_first_words_breaks_nothing():
    from docx.enum.text import WD_BREAK

    def build(doc):
        doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        doc.add_paragraph("Only text.")

    assert uu.extract_text_from_bytes(_docx(build), "p.docx") == "Only text."


@pytest.mark.parametrize("path", sorted(SAMPLES.glob("*.docx")) + sorted(SAMPLES.glob("*.pdf")))
def test_switch_off_extraction_is_the_old_text_once_page_breaks_are_dropped(path):
    raw = path.read_bytes()
    text = uu.extract_text_from_bytes(raw, path.name, structure=False)
    old = _old_docx(raw) if path.suffix == ".docx" else _old_pdf(raw)
    assert "\f" in text
    assert without_page_breaks(text) == old


# ── .pdf restructuring (switch on) ───────────────────────────────────────────

P1 = "Ana Ruiz\nProfessor Lee\nENGL 101\n12 May 2026\nRuiz 1"
P2 = (
    "Ruiz 2\n"
    "The first paragraph of the paper runs across the whole line and keeps going \n"
    "until it ends here.1\n"
    "A second paragraph begins and it is long enough to fill the line of the \n"
    "page and then it carries on past the foot of the page into the next one, \n"
    "1 Ana Ruiz, A Book of Notes (Boston: Press, 2001), 12.\n"
)
P3 = (
    "Ruiz 3\n"
    "where it finishes its sentence.2 4. A numbered point that is prose.\n"
    "2 Ibid., 14.\n"
)
P4 = "Ruiz 4\nWorks Cited\nRuiz, Ana. A Book of Notes. Boston: Press, 2001. https://\nexample.org/x."


def test_pdf_pages_are_restructured_with_the_switch_on():
    text = uu._structure_pdf([P1, P2, P3, P4])
    assert "Ruiz 2" not in text and "Ruiz 3" not in text  # running head gone
    assert not re.search(r"^\d+$", text, re.M)  # page numbers gone
    paras = [p for p in re.split(r"\n[\f\n]*\n", text) if p.strip()]
    assert (
        "A second paragraph begins and it is long enough to fill the line of the page "
        "and then it carries on past the foot of the page into the next one, where it "
        "finishes its sentence.2 4. A numbered point that is prose."
    ) in paras  # joined across lines and across the page break
    # The footnotes moved under the paragraph they interrupted, as one block
    # just before a page break, one note per line.
    assert "1 Ana Ruiz, A Book of Notes (Boston: Press, 2001), 12.\n2 Ibid., 14." + PAGE_BREAK in text
    assert "Works Cited\n\nRuiz, Ana. A Book of Notes. Boston: Press, 2001. https://example.org/x." in (
        text.replace(PAGE_BREAK, "\n\n")
    )
    # The heading block's short lines are not joined to each other.
    assert text.startswith("Ana Ruiz\n\nProfessor Lee\n\nENGL 101\n\n12 May 2026")


def test_the_switch_decides_whether_a_pdf_is_restructured(monkeypatch):
    raw = (SAMPLES / "mla.pdf").read_bytes()
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "0")
    plain = uu.extract_text_from_bytes(raw, "mla.pdf")
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    shaped = uu.extract_text_from_bytes(raw, "mla.pdf")
    assert without_page_breaks(plain) == _old_pdf(raw)
    assert shaped != plain and shaped == uu.extract_text_from_bytes(raw, "x.pdf", structure=True)


def test_a_keywords_line_is_not_joined_to_the_next_pages_title():
    long_kw = "Keywords: " + ", ".join(["civil rulers"] * 7)
    page2 = "Abstract\n" + ("word " * 16 + "\n") * 3 + long_kw
    text = uu._structure_pdf(["Title", page2, "A Title on Page Three\nProse starts here."])
    assert long_kw + PAGE_BREAK + "A Title on Page Three" in text


def test_a_numbered_paragraph_is_not_a_footnote():
    page = (
        "Some prose that runs on and on to fill a line of the page, with a marker.1\n"
        "1. And this is the writer's own numbered paragraph, long enough that it cannot be "
        + "a note at all, " * 12
        + "so it ends.\n"
    )
    text = uu._structure_pdf([page, "More prose."])
    assert "1. And this is the writer's own numbered paragraph" in text
    assert "\n\n1. And this" in text  # a paragraph of its own, not a notes block


# ── A page break is never measured ───────────────────────────────────────────


def _paper() -> str:
    parts = sorted(CORPUS.glob("mill/*part_0*.txt"))[0].read_text(encoding="utf-8")
    paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", parts) if p.strip()]
    return "\n\n".join(p for p in paras if len(p.split()) > 20)[:9000]


@pytest.mark.parametrize("switch", ["0", "1"])
def test_a_paper_with_page_breaks_measures_exactly_as_without(switch, monkeypatch):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", switch)
    ev.engine_view.cache_clear()
    plain = _paper()
    paged = plain.replace("\n\n", PAGE_BREAK)
    assert paged.count("\f") > 3
    assert pp.preprocess(paged)[0] == pp.preprocess(plain)[0]
    a, b = np.asarray(feature_vector(plain)), np.asarray(feature_vector(paged))
    assert np.array_equal(a, b)
    va, vb = ev.engine_view(plain), ev.engine_view(paged)
    assert va is not None and vb is not None
    assert va.prose.text == vb.prose.text
    assert all(paged[o] != "\f" for o in vb.prose.origin if o >= 0)
    ev.engine_view.cache_clear()


def test_page_breaks_do_not_reach_the_raw_text_experts():
    from original.fusion import channels
    from original.paper_profile import paper_profile
    from original.style_authorship import content_reduced_signature

    plain = _paper()
    paged = plain.replace("\n\n", PAGE_BREAK)
    assert paper_profile(paged) == paper_profile(plain)
    # The experts drop the page break at their entry; what they then compute
    # is a pure function of the text.
    assert channels.compressed_size(without_page_breaks(paged).encode()) == (
        channels.compressed_size(plain.encode())
    )
    assert np.array_equal(
        content_reduced_signature(without_page_breaks(paged)), content_reduced_signature(plain)
    )


def test_without_page_breaks_only_drops_a_form_feed_alone_on_its_line():
    assert without_page_breaks("a\n\f\nb") == "a\n\nb"
    assert without_page_breaks("a\n\f\n\n\f\nb") == "a\n\n\n\nb"  # an empty page
    assert without_page_breaks("a\fb\n\fc") == "a\fb\n\fc"  # any other form feed stays
    assert without_page_breaks("no breaks") == "no breaks"


def test_a_scored_paper_with_page_breaks_scores_exactly_as_without(live_client, store_reset):
    plain = _paper()
    paged = plain.replace("\n\n", PAGE_BREAK)
    texts = [
        sorted(CORPUS.glob("mill/*part_0*.txt"))[i].read_text(encoding="utf-8")[:6000]
        for i in (1, 2, 3)
    ]
    out = []
    for sid, sub, past in (("demo:pb_plain", plain, texts), ("demo:pb_paged", paged, texts)):
        for i, t in enumerate(past):
            body = t if sid == "demo:pb_plain" else t.replace("\n\n", PAGE_BREAK)
            r = live_client.post(
                f"/students/{sid}/baseline",
                json={"text": body, "provenance": "verified", "submitted_at": f"2026-01-0{i + 1}"},
            )
            assert r.status_code == 200, r.text[:300]
        r = live_client.post(f"/students/{sid}/score", json={"text": sub, "submission_id": "s"})
        assert r.status_code == 200, r.text[:300]
        out.append(r.json())
    a, b = out
    assert a["authorship"] == b["authorship"]
    assert a["recommendation"] == b["recommendation"]


# ── One extractor ────────────────────────────────────────────────────────────


def test_the_upload_routes_have_no_extractor_of_their_own():
    for name in ("students.py", "students_baseline.py"):
        src = (ROOT / "original" / "routers" / name).read_text(encoding="utf-8")
        assert "extract_text_from_bytes" in src
        assert "PdfReader" not in src and "Document(" not in src, name


def test_the_upload_route_keeps_page_breaks(live_client, store_reset):
    from docx.enum.text import WD_BREAK

    def build(doc):
        doc.add_paragraph("Title")
        doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        doc.add_paragraph("Body.")

    r = live_client.post(
        "/students/up-structure/upload",
        files={"file": ("paper.docx", io.BytesIO(_docx(build)), "application/octet-stream")},
    )
    assert r.status_code == 200
    assert r.json()["text"] == "Title" + PAGE_BREAK + "Body."
    assert r.json()["word_count"] == 2


def test_matter_reads_a_page_break_in_any_stored_form():
    # "\f" on its own line (an upload) and "\fFirst" (pdftotext's form) both
    # mark the page; the line ranges still cover the text exactly.
    for text in ("Title\n\f\nBody text here.", "Title\n\fBody text here."):
        d = matter._doc(text)
        assert d.has_breaks and any(d.brk)
        assert d.spans[-1][1] == len(text)
        assert "".join(text[a:b] for a, b, _ in d.spans) == text
