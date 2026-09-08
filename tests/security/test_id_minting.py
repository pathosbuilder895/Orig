"""
tests/security/test_id_minting.py — "make the system create a flat id for me."

docs/testing/04-security-adversarial.md §1.3. The Turnitin CSV importer
(``original/routers/imports.py:import_turnitin_csv``) mints
``student_id = sid or name.lower().replace(" ", "_")`` with no tenant
prefix at all, even when the import is authenticated as a specific
tenant's staff. A tenant-scoped id looks like ``"<tenant>:<local>"``
(``original/principal.py:tenant_of``); a flat id has no ``":"`` and is
exactly the shape ``original.principal.assert_student_access`` treats as
the anonymous demo sandbox — see the "Additive by construction" comment on
the tenant-isolation middleware in ``original/api.py`` and
``tests/test_tenant_isolation.py::test_demo_flat_student_round_trip``. So a
flat id minted from a real tenant's roster import reads back as a legacy/
sandbox id and is anonymously readable, in every environment, forever.

The endpoint's response body carries no ids (just counts), so the created
ids are recovered via ``get_repository().all_states()`` before/after the
import, exactly as the brief instructs.
"""

from __future__ import annotations

import pytest

from original.repository import get_repository

pytestmark = pytest.mark.security

CSV_HEADER = "Last Name,First Name,Student ID,Assignment Title,Date Submitted,Similarity,File Name"
# Row 1 carries an explicit Turnitin "Student ID" column value (still not
# tenant-prefixed by the importer). Row 2 has no id column, forcing the
# name-derived fallback (`name.lower().replace(" ", "_")`).
CSV_BODY = (
    f"{CSV_HEADER}\r\n"
    "Doe,Jane,turnitin-9001,Midterm Essay,2026-09-01,4%,jane_doe.docx\r\n"
    "Roe,Richard,,Midterm Essay,2026-09-01,7%,richard_roe.docx\r\n"
)


@pytest.mark.blocker
def test_turnitin_import_mints_tenant_prefixed_ids(
    pilot_env, two_tenants, store_reset, live_client
):
    """T-04: Turnitin CSV import mints flat ids instead of tenant-prefixed ones.

    Imported as tenant A staff, so every created id should read
    ``"sectesta:..."`` (``original.principal.tenant_of`` == the caller's own
    tenant) the same way ``POST /students/{tenant:id}/baseline`` scopes its
    writes. Instead ``import_turnitin_csv`` never looks at the caller's
    principal at all — it writes exactly the CSV's raw id / lowercased name,
    with no ``_require_staff`` call and no tenant prefix — so both created
    ids come back flat.
    """
    before_ids = {s.student_id for s in get_repository().all_states()}

    r = live_client.post(
        "/import/courses/c1/turnitin-csv",
        files={"file": ("roster.csv", CSV_BODY.encode(), "text/csv")},
        headers=two_tenants["headers_a"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created_students"] == 2, body

    after_ids = {s.student_id for s in get_repository().all_states()}
    created_ids = after_ids - before_ids
    assert len(created_ids) == 2, created_ids

    tenant_a_prefix = f"{two_tenants['tenant_a']}:"
    unprefixed = [sid for sid in created_ids if not sid.startswith(tenant_a_prefix)]
    assert unprefixed == [], f"minted ids are not tenant-prefixed: {unprefixed}"


@pytest.mark.blocker
def test_turnitin_minted_ids_refuse_anonymous_read(
    pilot_env, two_tenants, store_reset, live_client
):
    """T-04: a flat id minted by the Turnitin import is anonymously readable.

    Companion witness to the test above: even without inspecting the id
    shape directly, the *observable* consequence is that ``GET
    /students/{id}`` — gated only by the tenant-isolation middleware's
    ``assert_student_access`` — answers 200 for anyone, no principal
    required, because a flat (unprefixed) id reads as the demo sandbox.
    A tenant-prefixed id would 403 the same request (see
    ``tests/test_tenant_isolation.py::test_demo_cannot_read_pilot_student``).
    """
    before_ids = {s.student_id for s in get_repository().all_states()}

    r = live_client.post(
        "/import/courses/c1/turnitin-csv",
        files={"file": ("roster.csv", CSV_BODY.encode(), "text/csv")},
        headers=two_tenants["headers_a"],
    )
    assert r.status_code == 200, r.text

    after_ids = {s.student_id for s in get_repository().all_states()}
    created_ids = after_ids - before_ids
    assert len(created_ids) == 2, created_ids

    leaked = []
    for sid in sorted(created_ids):
        r = live_client.get(f"/students/{sid}")
        if r.status_code not in (401, 403):
            leaked.append((sid, r.status_code))
    assert leaked == [], f"anonymous caller could read minted ids: {leaked}"


def test_turnitin_import_still_requires_staff(pilot_env, live_client):
    """Sanity/witness: the import route itself is not reachable anonymously.

    Proves the harness would detect a regression here — if the tenant-only
    isolation middleware's staff-only prefix list ever dropped ``/import/``,
    this would start failing (and the two tests above would then be testing
    an already-broken precondition instead of the id-minting gap
    specifically).
    """
    r = live_client.post(
        "/import/courses/c1/turnitin-csv",
        files={"file": ("roster.csv", CSV_BODY.encode(), "text/csv")},
    )
    assert r.status_code in (401, 403), r.text
