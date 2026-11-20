"""Uploads keep page markers; a PDF is reflowed only when measured.

``original.upload_utils.extract_text_from_bytes`` is the one extractor every
upload route uses. It stores exactly the text it returned before, plus a page
marker (``matter.PAGE_MARK``, U+001F, alone on a line) where the file breaks a
page. With ``MATTER_SPLITTER_ENABLED`` on, a PDF's measured body is reflowed
(``features.pdf_reflow``); the stored text never depends on the switch.

The guarantees: a page marker is never measured and never part of a duplicate
hash, so an upload measures and hashes exactly as it did before markers were
kept; a form feed a teacher pasted is measured exactly as before.
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
from original.features.matter import PAGE_BREAK, PAGE_MARK, PDF_PAGE_BREAK, without_page_breaks
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
    text = uu.extract_text_from_bytes(raw, path.name)
    old = _old_docx(raw) if path.suffix == ".docx" else _old_pdf(raw)
    assert PAGE_MARK in text and "\f" not in text
    assert without_page_breaks(text) == old


# ── .pdf: stored as read, reflowed only when measured with the switch on ────

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
PDF_TEXT = PDF_PAGE_BREAK.join([P1, P2, P3, P4])


def test_a_pdf_is_reflowed_when_measured_with_the_switch_on(monkeypatch):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    ev.engine_view.cache_clear()
    body = pp._body(PDF_TEXT)
    assert "Ruiz 2" not in body and "Ruiz 3" not in body  # running heads set aside
    assert "Ana Ruiz, A Book" not in body and "Ibid" not in body  # footnotes set aside
    assert "Works Cited" not in body and "Professor Lee" not in body
    assert PAGE_MARK not in body
    paras = [p.strip() for p in body.split("\n\n") if p.strip()]
    assert paras == [
        "The first paragraph of the paper runs across the whole line and keeps going "
        "until it ends here.1",
        "A second paragraph begins and it is long enough to fill the line of the page "
        "and then it carries on past the foot of the page into the next one, where it "
        "finishes its sentence.2 4. A numbered point that is prose.",
    ]  # joined across lines and across the page break, a blank line between
    view = ev.engine_view(PDF_TEXT)  # the evidence view makes the same edits
    assert view is not None and view.prose.text == pp.preprocess(PDF_TEXT)[0]
    ev.engine_view.cache_clear()


def test_with_the_switch_off_a_pdf_measures_as_it_was_read(monkeypatch):
    monkeypatch.delenv("MATTER_SPLITTER_ENABLED", raising=False)
    assert pp._body(PDF_TEXT) == pp._strip_backmatter(without_page_breaks(PDF_TEXT))


def test_stored_pdf_text_does_not_depend_on_the_switch(monkeypatch):
    raw = (SAMPLES / "mla.pdf").read_bytes()
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "0")
    plain = uu.extract_text_from_bytes(raw, "mla.pdf")
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    assert uu.extract_text_from_bytes(raw, "mla.pdf") == plain
    assert without_page_breaks(plain) == _old_pdf(raw)


def test_a_keywords_line_is_not_joined_to_the_next_pages_title():
    from original.features import pdf_reflow

    long_kw = "Keywords: " + ", ".join(["civil rulers"] * 7)
    page2 = "Abstract\n" + ("word " * 16 + "\n") * 3 + long_kw
    text = PDF_PAGE_BREAK.join(["Title", page2, "A Title on Page Three\nProse starts here."])
    out = without_page_breaks(pdf_reflow.apply_ops(text, pdf_reflow.reflow_ops(text)))
    assert long_kw + "\n\nA Title on Page Three" in out


def test_a_pdf_stored_before_page_markers_is_measured_without_reflow(monkeypatch):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    old = "\n\n".join([P1, P2, P3, P4])  # no markers: no reflow, rules on the text alone
    assert "keeps going \nuntil" in pp._body(old)


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
    assert paged.count(PAGE_MARK) > 3
    assert pp.preprocess(paged)[0] == pp.preprocess(plain)[0]
    a, b = np.asarray(feature_vector(plain)), np.asarray(feature_vector(paged))
    assert np.array_equal(a, b)
    va, vb = ev.engine_view(plain), ev.engine_view(paged)
    assert va is not None and vb is not None
    assert va.prose.text == vb.prose.text
    assert all(paged[o] != PAGE_MARK for o in vb.prose.origin if o >= 0)
    ev.engine_view.cache_clear()


def test_a_pdf_upload_with_the_switch_off_measures_exactly_as_before(monkeypatch):
    monkeypatch.delenv("MATTER_SPLITTER_ENABLED", raising=False)
    plain = _paper()
    paged = plain.replace("\n\n", PDF_PAGE_BREAK)
    assert np.array_equal(
        np.asarray(feature_vector(plain)), np.asarray(feature_vector(paged))
    )


PASTE = (
    "Grace is not earned. It is given freely, and the giver asks nothing in return. "
    "Yet many readers resist this."
)
QUOTE = (
    "    For the law was given through Moses, but grace and truth\n"
    "    came through the one who was sent, and of his fullness\n"
    "    we have all received, grace upon grace, without measure."
)


@pytest.mark.parametrize("switch", ["0", "1"])
def test_a_pasted_form_feed_is_measured_exactly_as_before(switch, monkeypatch):
    """A form feed a teacher pasted (or a pdftotext .txt carries) is not a
    page marker: nothing drops it, so the body is the one the measurement
    had before page markers existed (switch off: everything before the first
    back-matter heading; on: the matter ranges, joined), byte for byte."""
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", switch)
    for text in (
        f"{PASTE} {PASTE}\n\f\n{QUOTE}\n\n{PASTE}",
        f"{PASTE}\n\fNext page starts here. {PASTE}",
        uu.extract_text_from_bytes(f"{PASTE}\n\f\n{PASTE}".encode(), "notes.txt"),
    ):
        assert "\f" in text
        if switch == "0":
            want = text[: len(pp._strip_backmatter(text))]
        else:
            want = "".join(text[a:b] for a, b in matter.kept_ranges(text))
        assert pp._body(text) == want
        assert "\f" in pp.preprocess(text)[0] or "\f" not in want


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


def test_without_page_breaks_only_drops_a_page_marker_alone_on_its_line():
    m = PAGE_MARK
    assert without_page_breaks(f"a\n{m}\nb") == "a\n\nb"
    assert without_page_breaks(f"a\n{m}{m}\nb") == "a\n\nb"  # a PDF page
    assert without_page_breaks(f"a\n{m}\n\n{m}\nb") == "a\n\n\n\nb"  # an empty page
    assert without_page_breaks(f"a{m}b") == f"a{m}b"  # not alone on its line
    assert without_page_breaks("a\n\f\nb") == "a\n\f\nb"  # a pasted form feed stays
    assert without_page_breaks("no breaks") == "no breaks"


def test_the_page_marker_is_whitespace_and_not_a_line_boundary():
    """So every word count, strip and line split in the app is unchanged."""
    m = PAGE_MARK
    assert m.isspace() and f"a\n{m}\nb".split() == ["a", "b"]
    assert f"a\n{m}\nb".splitlines() == ["a", m, "b"]
    assert re.fullmatch(r"\s", m)


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


def test_matter_reads_only_the_page_marker_as_a_page_break():
    for text in ("Title" + PAGE_BREAK + "Body text here.", "Title" + PDF_PAGE_BREAK + "Body."):
        d = matter._doc(text)
        assert d.has_breaks and any(d.brk)
        assert "".join(text[a:b] for a, b, _ in d.spans) == text
    for pasted in ("Title\n\f\nBody text here.", "Title\n\fBody text here."):
        d = matter._doc(pasted)
        assert not d.has_breaks and not any(d.brk)


# ── Duplicate checks ignore page markers ─────────────────────────────────────


@pytest.mark.parametrize("path", sorted(SAMPLES.glob("*.docx")) + sorted(SAMPLES.glob("*.pdf")))
def test_an_uploads_duplicate_hash_is_the_hash_it_had_before(path):
    import hashlib

    raw = path.read_bytes()
    old = _old_docx(raw) if path.suffix == ".docx" else _old_pdf(raw)
    text = uu.extract_text_from_bytes(raw, path.name)
    assert text != old
    assert uu.text_digest(text) == hashlib.sha256(old.encode()).hexdigest()


def test_pasted_and_txt_hashes_are_unchanged():
    import hashlib

    for text in (PASTE, f"{PASTE}\n\f\n{PASTE}"):
        assert uu.text_digest(text) == hashlib.sha256(text.encode()).hexdigest()


def test_a_file_stored_before_page_markers_is_a_duplicate_after(live_client, store_reset):
    from docx.enum.text import WD_BREAK

    paras = [_paper()[:1500], _paper()[1500:3000]]

    def build(doc):
        doc.add_paragraph(paras[0])
        doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        doc.add_paragraph(paras[1])

    raw = _docx(build)
    sid = "demo:dedup_upload"
    before = _old_docx(raw)  # what the extractor stored before this change
    r = live_client.post(
        f"/students/{sid}/baseline",
        json={"text": before, "provenance": "verified", "submitted_at": "2026-01-01"},
    )
    assert r.status_code == 200, r.text[:300]
    r = live_client.post(
        f"/students/{sid}/baseline/upload-batch",
        files=[("files", ("paper.docx", io.BytesIO(raw), "application/octet-stream"))],
        data={"provenance": "verified"},
    )
    assert r.status_code == 200, r.text[:300]
    assert r.json()["skipped_duplicates"] == 1 and r.json()["imported"] == 0


def test_the_batch_route_reports_the_librarys_own_error(live_client, store_reset):
    r = live_client.post(
        "/students/demo:batch_err/baseline/upload-batch",
        files=[("files", ("broken.docx", io.BytesIO(b"not a zip"), "application/msword"))],
        data={"provenance": "verified"},
    )
    (err,) = r.json()["errors"]
    assert err.startswith("broken.docx: extraction error ")
    assert "DOCX extraction failed" not in err  # the wording before the shared extractor
