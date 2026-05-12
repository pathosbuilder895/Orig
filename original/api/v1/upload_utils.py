"""
api/v1/upload_utils.py — Shared text extraction utilities.

Extracts plain text from PDF, DOCX, and TXT file bytes.
Used by:
  - POST /students/{id}/baseline/upload-batch  (batch baseline creation)
  - POST /students/{id}/upload                 (legacy demo API)
  - canvas/baseline_import.py                  (Canvas file attachments)

All extractors return a plain unicode string or raise ValueError with a
human-readable reason so callers can attach it to per-file error reports.
"""

from __future__ import annotations

import io
from typing import Optional


def extract_text_from_bytes(raw: bytes, filename: str) -> str:
    """
    Extract plain text from raw file bytes.

    Args:
        raw:      Raw bytes of the uploaded file.
        filename: Original filename — used to determine format by extension.

    Returns:
        Extracted plain text string (may be empty for blank PDFs).

    Raises:
        ValueError: If the file type is unsupported or extraction fails.
    """
    name_lower = filename.lower()

    if name_lower.endswith(".txt"):
        return raw.decode("utf-8", errors="replace")

    if name_lower.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ValueError("pypdf is not installed — run: pip install pypdf>=4.0,<5.0")
        try:
            reader = PdfReader(io.BytesIO(raw))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(pages)
        except Exception as exc:
            raise ValueError(f"PDF extraction failed: {exc}") from exc

    if name_lower.endswith(".docx"):
        try:
            from docx import Document
        except ImportError:
            raise ValueError("python-docx is not installed — run: pip install python-docx>=1.1,<2.0")
        try:
            doc = Document(io.BytesIO(raw))
            return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as exc:
            raise ValueError(f"DOCX extraction failed: {exc}") from exc

    ext = filename.rsplit(".", 1)[-1] if "." in filename else "unknown"
    raise ValueError(
        f"Unsupported file type '.{ext}'. Accepted formats: .txt, .pdf, .docx"
    )


def word_count(text: str) -> int:
    """Return word count for text."""
    return len(text.split())
