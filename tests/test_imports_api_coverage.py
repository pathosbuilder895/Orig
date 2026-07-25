"""
tests/test_imports_api_coverage.py — the roster-import surfaces.

POST /import/courses/{id}/turnitin-csv is how a pilot school seeds its roster,
so the parsing rules ARE the contract: which header spellings are accepted,
how a student id is derived when the export omits one, which rows are counted
as matched vs created, and which are reported back as unmatched. A silent
change to any of those produces a wrong roster with a 200 response.

The Canvas routes are deliberately 501 (WS-7 step 5) — they previously
returned placeholder JSON with 200, which reads as success to any client that
doesn't inspect the body. That regression is worth a permanent test.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import run

app = run.load_legacy_demo_app()
client = TestClient(app)


def _post_csv(body: str | bytes, course: str = "c1"):
    raw = body.encode("utf-8") if isinstance(body, str) else body
    return client.post(
        f"/import/courses/{course}/turnitin-csv",
        files={"file": ("roster.csv", raw, "text/csv")},
    )


def _uid(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


# ── Happy path + idempotency ─────────────────────────────────────────────────


def test_import_creates_students_and_reports_counts():
    """New ids are counted as created (not matched) and are really persisted."""
    sid = _uid("tii")
    csv = f"Last Name,First Name,Student ID\nSmith,Ada,{sid}\n"

    body = _post_csv(csv).json()
    assert body["total_rows"] == 1
    assert body["created_students"] == 1
    assert body["matched_students"] == 0
    assert body["unmatched_rows"] == 0
    assert body["errors"] == []

    # The stub really exists in the store afterwards.
    assert client.get(f"/students/{sid}").status_code == 200


def test_reimporting_the_same_roster_matches_instead_of_duplicating():
    """A second import of the same export must not double-create students.

    Catches a regression where `_repo().get()` stops being consulted and every
    re-import silently resets existing baselines via get_or_create().
    """
    sid = _uid("tirepeat")
    csv = f"Last Name,First Name,Student ID\nBrown,Bo,{sid}\n"

    first = _post_csv(csv).json()
    second = _post_csv(csv).json()

    assert first["created_students"] == 1 and first["matched_students"] == 0
    assert second["created_students"] == 0 and second["matched_students"] == 1


def test_flagged_submissions_counts_every_identified_row():
    """Each identifiable row yields one submission stub, across both students."""
    a, b = _uid("tia"), _uid("tib")
    csv = f"Last Name,First Name,Student ID\nA,Al,{a}\nB,Bea,{b}\n"

    body = _post_csv(csv).json()
    assert body["total_rows"] == 2
    assert body["flagged_submissions"] == 2


# ── Header normalisation + column aliases ────────────────────────────────────


def test_headers_are_matched_case_insensitively_and_trimmed():
    """Turnitin exports vary in header case/padding; normalisation is required.

    Catches removal of the `k.strip().lower()` header normalisation, which
    would make every row unidentifiable and return unmatched_rows == N.
    """
    sid = _uid("ticase")
    csv = f"  LAST NAME , First Name ,  Student ID \nDoe,Jane,{sid}\n"

    body = _post_csv(csv).json()
    assert body["unmatched_rows"] == 0
    assert body["created_students"] == 1
    assert client.get(f"/students/{sid}").status_code == 200


def test_studentid_alias_without_space_is_accepted():
    """'StudentID' (no space) is one of the documented export variants."""
    sid = _uid("tialias")
    csv = f"Surname,FirstName,StudentID\nKim,Sam,{sid}\n"

    body = _post_csv(csv).json()
    assert body["created_students"] == 1
    assert client.get(f"/students/{sid}").status_code == 200


def test_student_id_is_derived_from_the_name_when_the_export_omits_one():
    """No ID column → id is 'first_last' lowercased with spaces underscored.

    This derivation is what links a later submission to the imported row, so
    the exact shape matters.
    """
    tag = uuid.uuid4().hex[:8]
    csv = f"Last Name,First Name\nVanDyke{tag},Mary Jo\n"

    body = _post_csv(csv).json()
    assert body["created_students"] == 1
    assert client.get(f"/students/mary_jo_vandyke{tag}").status_code == 200


# ── Error / edge rows ────────────────────────────────────────────────────────


def test_row_without_any_identity_is_reported_not_silently_dropped():
    """A blank identity row increments unmatched_rows and names its row number.

    The professor-facing importer shows `errors` verbatim, so losing the row
    index would make a bad export impossible to fix.
    """
    sid = _uid("timix")
    csv = f"Last Name,First Name,Student ID\n,,\nOk,Ollie,{sid}\n"

    body = _post_csv(csv).json()
    assert body["total_rows"] == 2
    assert body["unmatched_rows"] == 1
    assert body["created_students"] == 1
    assert len(body["errors"]) == 1
    assert "Row 1" in body["errors"][0]


def test_header_only_csv_is_rejected_422():
    """A header row with no data rows is a user error, not an empty success."""
    r = _post_csv("Last Name,First Name,Student ID\n")
    assert r.status_code == 422, r.text
    assert "empty" in r.json()["detail"].lower()


def test_completely_empty_file_is_rejected_422():
    r = _post_csv(b"")
    assert r.status_code == 422, r.text


def test_utf8_bom_export_is_decoded_without_corrupting_the_first_header():
    """Excel-saved exports start with a UTF-8 BOM.

    Decoding with plain 'utf-8' would leave '\\ufeffLast Name' as the first
    header key, so the surname column would never match and every row would
    come back unmatched. utf-8-sig is required.
    """
    sid = _uid("tibom")
    csv = f"Last Name,First Name,Student ID\nBom,Bea,{sid}\n"

    body = _post_csv(b"\xef\xbb\xbf" + csv.encode("utf-8")).json()
    assert body["unmatched_rows"] == 0
    assert body["created_students"] == 1


# ── Canvas: honest 501s ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    ["list-canvas-submissions", "import-baseline"],
)
def test_canvas_baseline_routes_return_501_not_a_fake_200(path):
    """These must stay 501. They once returned placeholder JSON with 200, which
    professor.html's `r.ok` check read as a successful import."""
    r = client.post(f"/canvas/baseline/some_student/{path}", json={})
    assert r.status_code == 501, r.text
    assert "not available" in r.json()["detail"]
