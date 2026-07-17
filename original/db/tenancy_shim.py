"""
db/tenancy_shim.py — WS-6 P3 compatibility shim between the SQLite/API-facing
scoped student id and the live schema's composite (tenant_id, student_id) key.

SQLite (store.py) keys student_profiles on a single string: either
"{tenant_id}:{local_id}" (a real, registered tenant) or a colon-less legacy
id (pre-tenancy data, and the flat ids the demo sandbox has historically
used interchangeably with "demo:{id}"). The live schema splits this into a
real composite primary key with an FK to tenants — see StudentProfile's
docstring in db/models/live.py. The Repository Protocol's public signature
is unchanged (every method still takes/returns one scoped-id string); only
PostgresRepository's storage layer sees the split form.

The one subtlety this module exists to get right: "demo:foo" (an explicit,
namespaced id under the real "demo" tenant — see e2e/exam-flow.spec.mjs's
TEST_STUDENT_ID) and a genuinely colon-less flat id "foo" are DIFFERENT
SQLite primary keys and must round-trip to DIFFERENT composite keys too.
Mapping the flat case to tenant_id="demo" would collide the two onto the
same Postgres row — silent cross-contamination, exactly the risk the WS-6
plan calls out. _LEGACY_FLAT_TENANT is therefore a distinct sentinel that
slugify() (student_auth.py) can never produce for a real tenant, since it
only ever emits [a-z0-9-].
"""

from __future__ import annotations

from original.principal import tenant_of

_LEGACY_FLAT_TENANT = "__legacy_flat__"


def split_scoped_id(student_id: str) -> tuple[str, str]:
    """(tenant_id, local_id) for a scoped or legacy-flat student id.

    Mirrors principal.tenant_of()'s exact parsing (split on the FIRST ':'
    only, local id may itself contain colons).
    """
    tenant = tenant_of(student_id)
    if tenant is None:
        return _LEGACY_FLAT_TENANT, student_id
    return tenant, student_id.split(":", 1)[1]


def join_scoped_id(tenant_id: str, local_id: str) -> str:
    """Inverse of split_scoped_id. NOT the inverse of "always prepend
    tenant_id:" — the legacy-flat sentinel must round-trip back to the
    original colon-less id, not to "__legacy_flat__:{local_id}"."""
    if tenant_id == _LEGACY_FLAT_TENANT:
        return local_id
    return f"{tenant_id}:{local_id}"


def resolve_tenant_id(student_id: str) -> str:
    """The composite-key tenant_id a scoped/flat student_id resolves to —
    convenience wrapper for callers that only need the tenant half (e.g. to
    ensure the parent tenants row exists before an insert)."""
    return split_scoped_id(student_id)[0]
