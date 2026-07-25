"""
tests/test_upload_utils_coverage.py — original/upload_utils.py contract.

``extract_text_from_bytes`` is the canonical extractor shared by the Bbook
upload path and the dormant v1 shim. Its documented contract is narrow but
load-bearing for callers that build per-file error reports:

  * dispatch is by *filename extension*, case-insensitively;
  * every failure mode surfaces as ``ValueError`` with a human-readable
    reason — never a raw pypdf/python-docx exception, which callers do not
    catch;
  * a blank PDF is an empty string, not an error.

Each test below names one of those and fails if it regresses.
"""

from __future__ import annotations

import io

import pytest

from original.upload_utils import extract_text_from_bytes, word_count

# ── .txt ──────────────────────────────────────────────────────────────────────


def test_txt_decodes_utf8():
    """A .txt file is decoded as UTF-8 (round-trips non-ASCII prose)."""
    text = "Grace and peace — καὶ εἰρήνη — to the saints."
    assert extract_text_from_bytes(text.encode("utf-8"), "essay.txt") == text


def test_txt_replaces_undecodable_bytes_instead_of_raising():
    """errors='replace': a latin-1 byte must not abort a whole batch import.

    Catches a switch to strict decoding, which would turn one mis-encoded
    student file into a UnicodeDecodeError the callers don't handle.
    """
    out = extract_text_from_bytes(b"caf\xe9 au lait", "note.txt")
    assert "caf" in out and "au lait" in out
    assert "�" in out  # the undecodable byte became U+FFFD, not an exception


# ── extension dispatch ────────────────────────────────────────────────────────


def test_extension_match_is_case_insensitive():
    """`REPORT.TXT` from a Windows upload must dispatch to the txt branch.

    Catches removal of the `filename.lower()` normalisation, which would send
    every uppercase filename to the 'unsupported type' error.
    """
    assert extract_text_from_bytes(b"hello", "REPORT.TXT") == "hello"


def test_unsupported_extension_reports_extension_and_accepted_formats():
    """An unsupported type raises ValueError naming the ext + accepted list.

    The professor-facing batch importer pastes this string straight into its
    per-file error report, so both halves are part of the contract.
    """
    with pytest.raises(ValueError) as exc:
        extract_text_from_bytes(b"data", "notes.rtf")
    msg = str(exc.value)
    assert ".rtf" in msg
    assert ".txt" in msg and ".pdf" in msg and ".docx" in msg


def test_extensionless_filename_reports_unknown():
    """A filename with no dot reports '.unknown' rather than crashing on rsplit."""
    with pytest.raises(ValueError) as exc:
        extract_text_from_bytes(b"data", "README")
    assert "unknown" in str(exc.value)


def test_dotfile_without_real_extension_is_rejected():
    """'.gitignore' has a dot but no supported suffix — still a clean ValueError."""
    with pytest.raises(ValueError):
        extract_text_from_bytes(b"data", ".gitignore")


# ── .docx ─────────────────────────────────────────────────────────────────────


def _docx_bytes(paragraphs: list[str]) -> bytes:
    from docx import Document

    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_docx_round_trip_joins_paragraphs_and_drops_blanks():
    """Paragraphs are joined with a blank line; whitespace-only ones are dropped.

    Catches a regression that emits empty paragraphs (which would inflate the
    word/`\\n\\n` structure the downstream feature pipeline segments on).
    """
    raw = _docx_bytes(["First paragraph.", "   ", "", "Second paragraph."])
    out = extract_text_from_bytes(raw, "paper.docx")
    assert out == "First paragraph.\n\nSecond paragraph."


def test_corrupt_docx_raises_valueerror_not_the_library_exception():
    """A non-docx payload surfaces as ValueError('DOCX extraction failed: ...').

    python-docx raises PackageNotFoundError; callers only catch ValueError, so
    losing this wrapper turns one bad upload into a 500.
    """
    with pytest.raises(ValueError) as exc:
        extract_text_from_bytes(b"this is definitely not a zip archive", "broken.docx")
    assert "DOCX extraction failed" in str(exc.value)


# ── .pdf ──────────────────────────────────────────────────────────────────────


def test_blank_pdf_returns_empty_string_not_an_error():
    """A text-free PDF is an empty string — the docstring's explicit promise.

    The batch importer distinguishes 'no text extracted' (skip with a note)
    from 'extraction failed' (hard error); raising here would collapse the two.
    """
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)

    assert extract_text_from_bytes(buf.getvalue(), "blank.pdf").strip() == ""


def test_corrupt_pdf_raises_valueerror_not_the_library_exception():
    """A non-PDF payload surfaces as ValueError('PDF extraction failed: ...')."""
    with pytest.raises(ValueError) as exc:
        extract_text_from_bytes(b"%NOT-A-PDF% garbage", "broken.pdf")
    assert "PDF extraction failed" in str(exc.value)


# ── word_count ────────────────────────────────────────────────────────────────


def test_word_count_splits_on_arbitrary_whitespace():
    """Counting is whitespace-split, so newlines/tabs/runs collapse."""
    assert word_count("one two\tthree\n\nfour   five") == 5


def test_word_count_of_blank_text_is_zero():
    """Whitespace-only text counts zero — the readiness surfaces divide by this."""
    assert word_count("   \n\t ") == 0
