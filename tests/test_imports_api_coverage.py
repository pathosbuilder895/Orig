"""
tests/test_imports_api_coverage.py — the roster-import surfaces.

POST /import/courses/{id}/turnitin-csv is how a pilot school seeds its roster,
so the parsing rules ARE the contract: which header spellings are accepted,
how a student id is derived when the export omits one, which rows are counted
as matched vs created, and which are reported back as unmatched. A silent
change to any of those produces a wrong roster with a 200 response.

The route requires a staff principal and tenant-prefixes every created id
with that principal's own tenant (``{tenant}:{derived_id}``) — a flat,
tenant-less id is a demo-sandbox-only convention elsewhere in the app, and
minting one on a real deploy would make that student readable by any staff
account regardless of institution. The tests below use the anonymous demo
principal (tenant "demo"), which is why created ids are checked at
``/students/demo:{sid}``.

The Canvas routes are deliberately 501 (WS-7 step 5) — they previously
returned placeholder JSON with 200, which reads as success to any client that
doesn't inspect the body. That regression is worth a permanent test.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import run
from original import principal as pr

app = run.load_legacy_demo_app()
client = TestClient(app)

# The three Canvas live-import routes (list-canvas-submissions,
# import-baseline, fetch-submission-text) require a real (non-demo) staff
# principal (`_require_non_demo_staff`) since they make an outbound network
# call to a caller-supplied canvas_url/access_token — an SSRF primitive the
# demo sandbox's anonymous-staff convention should never have covered. Tests
# below that exercise those routes' business logic (not the auth gate
# itself) carry this header; the Turnitin CSV route is unaffected and still
# reachable anonymously (see the "Canvas: live-import auth gate" section).
# Role "operator" (a SUPER_ROLES member, see
# original/principal.py:assert_student_access) rather than "professor":
# these tests use the flat, tenant-less student id "some_student", and a
# tenant-scoped "professor" principal would be rejected by the tenant-
# isolation middleware's cross-tenant check before even reaching the route.
CANVAS_STAFF_TOKEN = pr.mint_principal_token("op-canvas-imports", "operator", "canvasimp")
CANVAS_STAFF_HEADERS = {"Authorization": f"Bearer {CANVAS_STAFF_TOKEN}"}


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

    # The stub really exists in the store afterwards, tenant-prefixed with
    # the importing (anonymous demo) principal's own tenant.
    assert client.get(f"/students/demo:{sid}").status_code == 200


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
    assert client.get(f"/students/demo:{sid}").status_code == 200


def test_studentid_alias_without_space_is_accepted():
    """'StudentID' (no space) is one of the documented export variants."""
    sid = _uid("tialias")
    csv = f"Surname,FirstName,StudentID\nKim,Sam,{sid}\n"

    body = _post_csv(csv).json()
    assert body["created_students"] == 1
    assert client.get(f"/students/demo:{sid}").status_code == 200


def test_student_id_is_derived_from_the_name_when_the_export_omits_one():
    """No ID column → id is 'first_last' lowercased with spaces underscored.

    This derivation is what links a later submission to the imported row, so
    the exact shape matters.
    """
    tag = uuid.uuid4().hex[:8]
    csv = f"Last Name,First Name\nVanDyke{tag},Mary Jo\n"

    body = _post_csv(csv).json()
    assert body["created_students"] == 1
    assert client.get(f"/students/demo:mary_jo_vandyke{tag}").status_code == 200


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


def test_decode_failure_is_a_422_not_a_500(monkeypatch):
    """imports.py:[37,38] — `except Exception as exc:` around the CSV
    decode. `raw.decode("utf-8-sig", errors="replace")` never actually
    raises for real byte input (`errors="replace"` absorbs every invalid
    sequence), so this handler is defensive code for a failure the decode
    call itself cannot currently produce. Reach it anyway by making
    `UploadFile.read()` hand back something that isn't bytes at all — the
    handler's real contract ("if extracting CSV text fails for any reason,
    422 rather than 500") shouldn't depend on which failure mode gets
    there."""
    import tempfile

    def _read_returns_a_str(self, size=-1):
        return "not bytes, has no .decode()"

    monkeypatch.setattr(tempfile.SpooledTemporaryFile, "read", _read_returns_a_str)

    r = _post_csv("Last Name,First Name,Student ID\nA,B,c1\n")

    assert r.status_code == 422, r.text
    assert "Could not decode CSV" in r.json()["detail"]


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


# ── Tenant scoping ────────────────────────────────────────────────────────────


def test_unauthenticated_import_is_rejected_on_a_real_deploy(monkeypatch):
    """Off the demo sandbox, an anonymous caller must not be able to mint
    student records at all."""
    import original.api as api_mod

    monkeypatch.setattr(api_mod, "_IS_REAL_DEPLOY", True)
    try:
        sid = _uid("tiauth")
        csv = f"Last Name,First Name,Student ID\nNoAuth,Case,{sid}\n"
        r = _post_csv(csv)
        assert r.status_code in (401, 403), r.text
    finally:
        monkeypatch.setattr(api_mod, "_IS_REAL_DEPLOY", False)


def test_two_institutions_importing_the_same_raw_id_land_in_separate_tenants():
    """A raw Turnitin student id is not globally unique across institutions;
    it must never collide across tenants."""
    from original import principal as pr

    raw_id = _uid("shared")
    csv = f"Last Name,First Name,Student ID\nShared,Id,{raw_id}\n"

    acme_token = pr.mint_principal_token("prof-acme-ti", "professor", "acme")
    beta_token = pr.mint_principal_token("prof-beta-ti", "professor", "beta")

    acme_resp = client.post(
        "/import/courses/c1/turnitin-csv",
        files={"file": ("roster.csv", csv.encode(), "text/csv")},
        headers={"Authorization": f"Bearer {acme_token}"},
    )
    assert acme_resp.status_code == 200, acme_resp.text
    beta_resp = client.post(
        "/import/courses/c1/turnitin-csv",
        files={"file": ("roster.csv", csv.encode(), "text/csv")},
        headers={"Authorization": f"Bearer {beta_token}"},
    )
    assert beta_resp.status_code == 200, beta_resp.text

    # Both imports report "created" — they are two distinct students, not
    # the second one matching the first's record.
    assert acme_resp.json()["created_students"] == 1
    assert beta_resp.json()["created_students"] == 1
    assert client.get(
        f"/students/acme:{raw_id}", headers={"Authorization": f"Bearer {acme_token}"}
    ).status_code == 200
    assert client.get(
        f"/students/beta:{raw_id}", headers={"Authorization": f"Bearer {beta_token}"}
    ).status_code == 200
    # Neither tenant's staff can read the flat, unprefixed id — it was
    # never created.
    assert client.get(
        f"/students/{raw_id}", headers={"Authorization": f"Bearer {acme_token}"}
    ).status_code in (403, 404)


# ── Canvas: live integration fails closed without configuration ─────────────


@pytest.mark.parametrize(
    "path",
    ["list-canvas-submissions", "import-baseline"],
)
def test_canvas_baseline_routes_require_configuration(path):
    """Live Canvas routes must not report placeholder success when unconfigured."""
    r = client.post(
        f"/canvas/baseline/some_student/{path}", json={}, headers=CANVAS_STAFF_HEADERS
    )
    assert r.status_code == 400, r.text
    assert "Canvas base URL and API token" in r.json()["detail"]


# ── Canvas: live-import auth gate (_require_non_demo_staff) ─────────────────


@pytest.mark.parametrize(
    "path",
    ["list-canvas-submissions", "import-baseline", "fetch-submission-text"],
)
def test_canvas_baseline_routes_reject_anonymous_demo_principal(path):
    """The anonymous demo principal (no Authorization header) must not reach
    any of the three Canvas live-import routes -- they spend a caller-supplied
    canvas_url/access_token making a real outbound request, which is an SSRF
    primitive the demo sandbox's normal anonymous-is-staff convention should
    never have covered."""
    r = client.post(f"/canvas/baseline/some_student/{path}", json={})
    assert r.status_code == 401, r.text


@pytest.mark.parametrize(
    "path",
    ["list-canvas-submissions", "import-baseline", "fetch-submission-text"],
)
def test_canvas_baseline_routes_reject_self_assigned_demo_role(path):
    """A caller who self-assigns a staff role via X-Demo-Role (no
    Authorization token) must still be rejected. `_require_staff` alone would
    have let this through, since the demo principal's role is
    self-assignable via that header -- `_require_non_demo_staff` closes it by
    rejecting the demo principal outright, regardless of its assigned role."""
    r = client.post(
        f"/canvas/baseline/some_student/{path}",
        json={},
        headers={"X-Demo-Role": "operator"},
    )
    assert r.status_code == 401, r.text


@pytest.mark.parametrize(
    "path",
    ["list-canvas-submissions", "import-baseline", "fetch-submission-text"],
)
def test_canvas_baseline_routes_accept_real_staff_token(path):
    """A real (non-demo) staff token passes the auth gate. With no further
    body fields supplied, the route's own validation takes over next -- here
    that's the pinned config-absent 400 -- which is itself proof the request
    got past `_require_non_demo_staff` rather than being stopped at 401."""
    r = client.post(
        f"/canvas/baseline/some_student/{path}", json={}, headers=CANVAS_STAFF_HEADERS
    )
    assert r.status_code == 400, r.text
    assert "Canvas base URL and API token" in r.json()["detail"]


def test_turnitin_csv_import_unaffected_still_reachable_anonymously():
    """The Turnitin CSV import route is a different handler in the same file
    that legitimately still uses `_require_staff` (no outbound network call,
    so no SSRF exposure) -- it must remain reachable by the anonymous demo
    principal. A future change to _shared.py that widened or narrowed this
    boundary should fail this test."""
    sid = _uid("tinoauth")
    csv = f"Last Name,First Name,Student ID\nNoAuth,Anon,{sid}\n"
    r = _post_csv(csv)
    assert r.status_code == 200, r.text
    assert r.json()["created_students"] == 1
