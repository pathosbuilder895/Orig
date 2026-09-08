# Consent Records and Retention Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record who authorized processing (institution-level) and who was given notice (student-level), and compute — but never enforce — the retention schedule that `docs/data_inventory.md` already specifies.

**Architecture:** Two new tables behind the existing repository abstraction (SQLite via `original/store.py`, Postgres via SQLAlchemy models + Alembic), a pure-function retention calculator in a new `original/retention.py`, and a shadow-only sweeper started from the API lifespan exactly as `original/backup.py` is. Nothing in this plan deletes anything.

**Tech Stack:** Python 3.11, FastAPI, SQLite (`sqlite3` stdlib) + SQLAlchemy/Alembic for Postgres, pytest.

## Global Constraints

- Branch: `claude/consent-retention-model`, already created off updated `main`.
- Python is **always** `/Users/andrew/Desktop/Original/.venv/bin/python`. The relative `.venv/bin/python` in CLAUDE.md **does not exist in this git worktree**.
- Full suite takes ~11 minutes and outruns a 600s tool timeout. During implementation run **targeted test files only**; run the full suite once at the end.
- Spec is `docs/superpowers/specs/2026-08-17-consent-retention-design.md`. Read §2.2 before Task 4.
- **No enforcement code.** Nothing in this plan may call `store.delete_student()` from a sweep. Not behind a flag, not commented out.
- **The undated rule is load-bearing**: a student with no derivable activity date is NEVER eligible for deletion. See Task 4.
- Timestamps use the store's newer idiom: `datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")`. `UTC` and `datetime` are already imported in `original/store.py:18`.
- `disclosure_acknowledgments` has **no `declined` column**. Do not add one.
- New env flags default OFF; flag-off behaviour must be byte-identical.
- Commit style: `Add ...` / `Fix ...`, one focused commit per task, ending with:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `original/store.py` | SQLite DDL + accessors for both tables; extend `delete_student`, `student_data_inventory` | 1, 2, 7 |
| `original/db/models/live.py` | SQLAlchemy models for both tables (Postgres) | 3 |
| `alembic/versions/<rev>_consent_retention.py` | Postgres migration | 3 |
| `original/repository.py` | `Repository` Protocol + `SqliteRepository` delegation | 3 |
| `original/postgres_repository.py` | Postgres implementations | 3 |
| `original/retention.py` | **New.** Pure retention computation + undated rule | 4 |
| `original/retention_sweep.py` | **New.** asyncio sweep loop (report-only) | 5 |
| `original/api.py` | Lifespan wiring for the sweep | 5 |
| `original/routers/governance.py` | **New.** Authorization + disclosure + candidates endpoints | 6 |
| `tests/test_governance_store.py` | **New.** Store-level tests for both tables | 1, 2 |
| `tests/test_retention.py` | **New.** Retention arithmetic + undated rule | 4, 5 |
| `tests/test_governance_api.py` | **New.** Endpoint tests | 6 |
| `docs/data_inventory.md`, `CLAUDE.md` | Documentation corrections | 7 |

---

### Task 1: `tenant_authorizations` table and store accessors

**Files:**
- Modify: `original/store.py` (DDL near line 370 with the other tenant tables; accessors near `put_correction` ~line 1711)
- Test: `tests/test_governance_store.py` (create)

**Interfaces:**
- Consumes: nothing (first task)
- Produces:
  - `store.put_tenant_authorization(tenant_id: str, document_type: str, document_version: str, executed_at: str, *, officer_name: str = "", officer_title: str = "", recorded_by: str = "", notes: str = "") -> str` (returns the new row id)
  - `store.list_tenant_authorizations(tenant_id: str) -> list[dict]` (newest `executed_at` first)
  - `store.current_tenant_authorization(tenant_id: str) -> dict | None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_governance_store.py`:

```python
"""tests/test_governance_store.py — institutional authorization + student notice records."""

from __future__ import annotations

import pytest

import original.store as store


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Throwaway SQLite file for one test (mirrors conftest's store_reset)."""
    monkeypatch.setattr(store, "_DB_PATH", tmp_path / "gov.db")
    store._init_db()
    return store


def test_put_and_list_tenant_authorization(db):
    row_id = db.put_tenant_authorization(
        "seminary-a",
        "dpa",
        "dpa_template.md@2026-07-07",
        "2026-07-07T00:00:00Z",
        officer_name="A. Registrar",
        officer_title="Registrar",
        recorded_by="op-1",
    )
    assert row_id

    rows = db.list_tenant_authorizations("seminary-a")
    assert len(rows) == 1
    assert rows[0]["document_type"] == "dpa"
    assert rows[0]["officer_name"] == "A. Registrar"
    assert rows[0]["executed_at"] == "2026-07-07T00:00:00Z"
    # executed_at and recorded_at are distinct facts, both populated.
    assert rows[0]["recorded_at"]


def test_current_authorization_is_latest_executed_not_latest_inserted(db):
    # Insert the NEWER agreement FIRST, so insertion order and executed_at
    # order disagree. "Current" must follow executed_at.
    db.put_tenant_authorization("t1", "dpa", "v2", "2026-08-01T00:00:00Z")
    db.put_tenant_authorization("t1", "dpa", "v1", "2025-01-01T00:00:00Z")

    current = db.current_tenant_authorization("t1")
    assert current is not None
    assert current["document_version"] == "v2"


def test_current_authorization_none_when_absent(db):
    assert db.current_tenant_authorization("never-heard-of-it") is None


def test_authorizations_are_tenant_scoped(db):
    db.put_tenant_authorization("t1", "dpa", "v1", "2026-01-01T00:00:00Z")
    db.put_tenant_authorization("t2", "dpa", "v1", "2026-01-01T00:00:00Z")
    assert len(db.list_tenant_authorizations("t1")) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_governance_store.py -v`
Expected: FAIL — `AttributeError: module 'original.store' has no attribute 'put_tenant_authorization'`

- [ ] **Step 3: Add the DDL**

In `original/store.py`, in `_init_db()`, immediately after the `tenants` table block (~line 370–387), add:

```python
    # Institutional authorization to process student work. Under FERPA's
    # school-official exception the INSTITUTION is the authorizing party --
    # not the student -- so this table, not a student consent flag, is the
    # record of the legal basis. Rows describe an out-of-band legal event
    # (someone signed a DPA) entered by an operator; executed_at and
    # recorded_at are deliberately separate facts. Multiple rows per tenant
    # are expected: agreements get renewed and the history is the point.
    # "Current" is computed as MAX(executed_at) at read time -- no is_current
    # column, which would drift.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tenant_authorizations (
            id               TEXT PRIMARY KEY,
            tenant_id        TEXT NOT NULL,
            document_type    TEXT NOT NULL,
            document_version TEXT NOT NULL,
            executed_at      TEXT NOT NULL,
            officer_name     TEXT NOT NULL DEFAULT '',
            officer_title    TEXT NOT NULL DEFAULT '',
            recorded_by      TEXT NOT NULL DEFAULT '',
            recorded_at      TEXT NOT NULL,
            notes            TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_tenant_auth
            ON tenant_authorizations(tenant_id, executed_at)
    """)
```

- [ ] **Step 4: Add `import uuid` to store.py**

`original/store.py` line ~17, alphabetical among the stdlib imports (after `import sys`):

```python
import uuid
```

- [ ] **Step 5: Add the accessors**

In `original/store.py`, after `put_correction`'s block (~line 1790, before the next section comment):

```python
# ── Governance: institutional authorization ──────────────────────────────────


def put_tenant_authorization(
    tenant_id: str,
    document_type: str,
    document_version: str,
    executed_at: str,
    *,
    officer_name: str = "",
    officer_title: str = "",
    recorded_by: str = "",
    notes: str = "",
) -> str:
    """Record that an institution executed an authorizing agreement.

    ``executed_at`` is when the institution signed (an out-of-band fact the
    caller supplies); ``recorded_at`` is when we were told. Returns the row id.
    """
    row_id = uuid.uuid4().hex
    recorded_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO tenant_authorizations "
            "(id, tenant_id, document_type, document_version, executed_at, "
            " officer_name, officer_title, recorded_by, recorded_at, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row_id,
                tenant_id,
                document_type,
                document_version,
                executed_at,
                officer_name,
                officer_title,
                recorded_by,
                recorded_at,
                notes,
            ),
        )
    return row_id


def list_tenant_authorizations(tenant_id: str) -> list[dict]:
    """All authorizations for a tenant, newest ``executed_at`` first."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id, tenant_id, document_type, document_version, executed_at, "
            "       officer_name, officer_title, recorded_by, recorded_at, notes "
            "FROM tenant_authorizations WHERE tenant_id = ? "
            "ORDER BY executed_at DESC",
            (tenant_id,),
        ).fetchall()
    cols = (
        "id", "tenant_id", "document_type", "document_version", "executed_at",
        "officer_name", "officer_title", "recorded_by", "recorded_at", "notes",
    )
    return [dict(zip(cols, r, strict=True)) for r in rows]


def current_tenant_authorization(tenant_id: str) -> dict | None:
    """The authorization with the greatest ``executed_at``, or None."""
    rows = list_tenant_authorizations(tenant_id)
    return rows[0] if rows else None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_governance_store.py -v`
Expected: PASS — 4 passed

- [ ] **Step 7: Commit**

```bash
git add original/store.py tests/test_governance_store.py
git commit -m "Add tenant_authorizations table recording the institutional legal basis

Under FERPA's school-official exception the institution is the authorizing
party, so this -- not a student consent flag -- is the record of why we may
process a tenant's student work. executed_at (signature) and recorded_at
(data entry) are kept as separate facts, and current authorization is
computed as MAX(executed_at) rather than stored in a drifting is_current
column.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: `disclosure_acknowledgments` table and store accessors

**Files:**
- Modify: `original/store.py` (DDL after the Task 1 block; accessors after Task 1's accessors)
- Test: `tests/test_governance_store.py` (append)

**Interfaces:**
- Consumes: Task 1's DDL location and `import uuid`
- Produces:
  - `store.put_disclosure_ack(student_id: str, tenant_id: str, disclosure_version: str, *, context: str = "manual", acknowledged_at: str | None = None) -> str`
  - `store.list_disclosure_acks(student_id: str) -> list[dict]` (newest first)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_governance_store.py`:

```python
def test_put_and_list_disclosure_ack(db):
    ack_id = db.put_disclosure_ack(
        "stu-abc", "seminary-a", "STUDENT_DISCLOSURE.md@2026-07-07",
        context="bluebook_briefing",
    )
    assert ack_id

    rows = db.list_disclosure_acks("stu-abc")
    assert len(rows) == 1
    assert rows[0]["disclosure_version"] == "STUDENT_DISCLOSURE.md@2026-07-07"
    assert rows[0]["context"] == "bluebook_briefing"
    assert rows[0]["acknowledged_at"]


def test_reack_same_version_is_idempotent_and_keeps_first_timestamp(db):
    db.put_disclosure_ack(
        "stu-abc", "t1", "v1", acknowledged_at="2026-01-01T00:00:00Z"
    )
    db.put_disclosure_ack(
        "stu-abc", "t1", "v1", acknowledged_at="2026-06-01T00:00:00Z"
    )

    rows = db.list_disclosure_acks("stu-abc")
    assert len(rows) == 1, "same (student, version) must not duplicate"
    # First notice is the one with evidentiary value.
    assert rows[0]["acknowledged_at"] == "2026-01-01T00:00:00Z"


def test_different_versions_are_separate_rows(db):
    db.put_disclosure_ack("stu-abc", "t1", "v1")
    db.put_disclosure_ack("stu-abc", "t1", "v2")
    assert len(db.list_disclosure_acks("stu-abc")) == 2


def test_disclosure_table_has_no_declined_column(db):
    """Notice, not consent. A declined column would invite enforcement on a
    basis that does not hold under the school-official exception."""
    with store._get_conn() as conn:
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(disclosure_acknowledgments)"
        ).fetchall()}
    assert "declined" not in cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_governance_store.py -v -k disclosure`
Expected: FAIL — `AttributeError: module 'original.store' has no attribute 'put_disclosure_ack'`

- [ ] **Step 3: Add the DDL**

In `original/store.py` `_init_db()`, directly after the Task 1 `tenant_authorizations` block:

```python
    # Evidentiary record that a student was SHOWN the disclosure -- proof of
    # notice, not a permission gate. There is deliberately no `declined`
    # column: under the school-official exception the student is not the
    # consenting party, and a decline field would invite a later contributor
    # to build enforcement on a basis that does not hold. student_id is the
    # existing opaque tenant-scoped code, so this table adds no new PII.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS disclosure_acknowledgments (
            id                 TEXT PRIMARY KEY,
            student_id         TEXT NOT NULL,
            tenant_id          TEXT NOT NULL,
            disclosure_version TEXT NOT NULL,
            acknowledged_at    TEXT NOT NULL,
            context            TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_disclosure_student
            ON disclosure_acknowledgments(student_id, acknowledged_at)
    """)
    # Enforces one row per (student, version) in the schema rather than by
    # write-path convention -- see put_disclosure_ack's ON CONFLICT clause.
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_disclosure_unique
            ON disclosure_acknowledgments(student_id, disclosure_version)
    """)
```

- [ ] **Step 4: Add the accessors**

In `original/store.py`, after Task 1's `current_tenant_authorization`:

```python
# ── Governance: student notice ───────────────────────────────────────────────


def put_disclosure_ack(
    student_id: str,
    tenant_id: str,
    disclosure_version: str,
    *,
    context: str = "manual",
    acknowledged_at: str | None = None,
) -> str:
    """Record that a student was shown a disclosure version.

    Idempotent on (student_id, disclosure_version): re-acknowledging the same
    version leaves the ORIGINAL acknowledged_at intact, because the first
    notice is the one with evidentiary value.
    """
    row_id = uuid.uuid4().hex
    ts = acknowledged_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO disclosure_acknowledgments "
            "(id, student_id, tenant_id, disclosure_version, acknowledged_at, context) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(student_id, disclosure_version) DO NOTHING",
            (row_id, student_id, tenant_id, disclosure_version, ts, context),
        )
    return row_id


def list_disclosure_acks(student_id: str) -> list[dict]:
    """All disclosure acknowledgments for a student, newest first."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id, student_id, tenant_id, disclosure_version, "
            "       acknowledged_at, context "
            "FROM disclosure_acknowledgments WHERE student_id = ? "
            "ORDER BY acknowledged_at DESC",
            (student_id,),
        ).fetchall()
    cols = (
        "id", "student_id", "tenant_id", "disclosure_version",
        "acknowledged_at", "context",
    )
    return [dict(zip(cols, r, strict=True)) for r in rows]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_governance_store.py -v`
Expected: PASS — 8 passed

- [ ] **Step 6: Commit**

```bash
git add original/store.py tests/test_governance_store.py
git commit -m "Add disclosure_acknowledgments table recording student notice

Evidentiary proof that a student was shown a disclosure version, not a
permission gate -- there is deliberately no declined column, asserted by a
test, because under the school-official exception the student is not the
consenting party and a decline field would invite enforcement on a basis
that does not hold. Idempotent on (student, version) via a UNIQUE index,
keeping the first acknowledged_at since that is the notice that counts.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Repository wiring (Protocol, SQLite delegation, Postgres models + migration)

**Files:**
- Modify: `original/repository.py` (`Repository` Protocol ~line 46; `SqliteRepository` ~line 313)
- Modify: `original/db/models/live.py` (after `AuditLogEntry`, ~line 577)
- Modify: `original/postgres_repository.py` (near `log_audit` ~line 1858)
- Create: `alembic/versions/<rev>_consent_retention.py`
- Test: `tests/test_repository_contract.py` (append)

**Interfaces:**
- Consumes: all five store functions from Tasks 1–2
- Produces: the same five names as `Repository` methods —
  `put_tenant_authorization`, `list_tenant_authorizations`, `current_tenant_authorization`, `put_disclosure_ack`, `list_disclosure_acks`

- [ ] **Step 1: Write the failing contract test**

Append to `tests/test_repository_contract.py` (it already parametrizes SQLite and Postgres; follow the file's existing `repo` fixture name — read the top of the file first and match it):

```python
def test_tenant_authorization_roundtrip(repo):
    repo.put_tenant_authorization(
        "t1", "dpa", "v1", "2026-01-01T00:00:00Z", officer_name="R. Officer"
    )
    rows = repo.list_tenant_authorizations("t1")
    assert len(rows) == 1
    assert rows[0]["officer_name"] == "R. Officer"
    assert repo.current_tenant_authorization("t1")["document_version"] == "v1"


def test_disclosure_ack_roundtrip_and_idempotence(repo):
    repo.put_disclosure_ack("stu-1", "t1", "v1", context="manual")
    repo.put_disclosure_ack("stu-1", "t1", "v1", context="manual")
    rows = repo.list_disclosure_acks("stu-1")
    assert len(rows) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_repository_contract.py -v -k "authorization or disclosure"`
Expected: FAIL — `AttributeError: 'SqliteRepository' object has no attribute 'put_tenant_authorization'`
(Postgres-parametrized cases self-skip locally without `DATABASE_URL`; that is expected — see Step 8.)

- [ ] **Step 3: Add to the `Repository` Protocol**

In `original/repository.py`, inside `class Repository(Protocol)`, after the audit-log methods:

```python
    # ── Governance: authorization + notice ───────────────────────────────
    def put_tenant_authorization(
        self,
        tenant_id: str,
        document_type: str,
        document_version: str,
        executed_at: str,
        *,
        officer_name: str = "",
        officer_title: str = "",
        recorded_by: str = "",
        notes: str = "",
    ) -> str: ...
    def list_tenant_authorizations(self, tenant_id: str) -> list[dict]: ...
    def current_tenant_authorization(self, tenant_id: str) -> dict | None: ...
    def put_disclosure_ack(
        self,
        student_id: str,
        tenant_id: str,
        disclosure_version: str,
        *,
        context: str = "manual",
        acknowledged_at: str | None = None,
    ) -> str: ...
    def list_disclosure_acks(self, student_id: str) -> list[dict]: ...
```

- [ ] **Step 4: Add the `SqliteRepository` delegations**

In `original/repository.py`, inside `class SqliteRepository`, matching the file's existing delegation style:

```python
    # ── Governance: authorization + notice ───────────────────────────────
    def put_tenant_authorization(
        self, tenant_id, document_type, document_version, executed_at,
        *, officer_name="", officer_title="", recorded_by="", notes="",
    ) -> str:
        return store.put_tenant_authorization(
            tenant_id, document_type, document_version, executed_at,
            officer_name=officer_name, officer_title=officer_title,
            recorded_by=recorded_by, notes=notes,
        )

    def list_tenant_authorizations(self, tenant_id) -> list[dict]:
        return store.list_tenant_authorizations(tenant_id)

    def current_tenant_authorization(self, tenant_id) -> dict | None:
        return store.current_tenant_authorization(tenant_id)

    def put_disclosure_ack(
        self, student_id, tenant_id, disclosure_version,
        *, context="manual", acknowledged_at=None,
    ) -> str:
        return store.put_disclosure_ack(
            student_id, tenant_id, disclosure_version,
            context=context, acknowledged_at=acknowledged_at,
        )

    def list_disclosure_acks(self, student_id) -> list[dict]:
        return store.list_disclosure_acks(student_id)
```

- [ ] **Step 5: Register the writes with `ShadowRepository`**

In `original/repository.py`, add `"put_tenant_authorization"` and `"put_disclosure_ack"` to the `_WRITE_METHODS` set so shadow mode mirrors them. Find that set (it is used by `ShadowRepository.__getattr__`) and add both names.

- [ ] **Step 6: Add SQLAlchemy models**

In `original/db/models/live.py`, after `class AuditLogEntry(LiveBase)`:

```python
class TenantAuthorization(LiveBase):
    """Institutional authorization to process student work (see
    docs/superpowers/specs/2026-08-17-consent-retention-design.md §1.1)."""

    __tablename__ = "tenant_authorizations"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    document_type = Column(String, nullable=False)
    document_version = Column(String, nullable=False)
    executed_at = Column(DateTime(timezone=True), nullable=False)
    officer_name = Column(String, nullable=False, default="")
    officer_title = Column(String, nullable=False, default="")
    recorded_by = Column(String, nullable=False, default="")
    recorded_at = Column(DateTime(timezone=True), nullable=False)
    notes = Column(Text, nullable=False, default="")


class DisclosureAcknowledgment(LiveBase):
    """Evidentiary proof of notice. No `declined` column, by design (§1.2)."""

    __tablename__ = "disclosure_acknowledgments"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "disclosure_version", name="uq_disclosure_student_version"
        ),
    )

    id = Column(String, primary_key=True)
    student_id = Column(String, nullable=False, index=True)
    tenant_id = Column(String, nullable=False)
    disclosure_version = Column(String, nullable=False)
    acknowledged_at = Column(DateTime(timezone=True), nullable=False)
    context = Column(String, nullable=False)
```

Check the imports at the top of `live.py` — add `UniqueConstraint` (and `Text` if absent) to the existing `from sqlalchemy import ...` line.

- [ ] **Step 7: Generate and edit the Alembic migration**

Run:
```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m alembic revision -m "consent_retention"
```
Fill the generated file's `upgrade()` with `op.create_table` calls matching the two models above (including the unique constraint and both indexes), and `downgrade()` with the two `op.drop_table` calls. Follow `alembic/versions/9f2c7a1b4d63_fused_scores.py` as the format reference.

- [ ] **Step 8: Implement the Postgres repository methods**

In `original/postgres_repository.py`, near `log_audit` (~line 1858), add the five methods using the `session_scope()` idiom that `log_audit` uses. `put_disclosure_ack` must use a PostgreSQL upsert so idempotence matches SQLite:

```python
from sqlalchemy.dialects.postgresql import insert as pg_insert
```
```python
    def put_disclosure_ack(
        self, student_id, tenant_id, disclosure_version,
        *, context="manual", acknowledged_at=None,
    ) -> str:
        row_id = uuid.uuid4().hex
        ts = _parse_iso(acknowledged_at) if acknowledged_at else datetime.now(UTC)
        with session_scope() as session:
            stmt = pg_insert(DisclosureAcknowledgment).values(
                id=row_id, student_id=student_id, tenant_id=tenant_id,
                disclosure_version=disclosure_version,
                acknowledged_at=ts, context=context,
            ).on_conflict_do_nothing(
                index_elements=["student_id", "disclosure_version"]
            )
            session.execute(stmt)
        return row_id
```

Return dicts with the **same keys and ISO-string timestamps** as the SQLite path — the contract test compares them directly. Add a `_parse_iso` helper if the module lacks one.

- [ ] **Step 9: Run the contract tests**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_repository_contract.py -v -k "authorization or disclosure"`
Expected: PASS for SQLite; Postgres cases SKIP locally. If a local Postgres is available, set `DATABASE_URL` and re-run to exercise both.

- [ ] **Step 10: Commit**

```bash
git add original/repository.py original/db/models/live.py original/postgres_repository.py alembic/versions tests/test_repository_contract.py
git commit -m "Wire the governance tables through the repository abstraction

Adds both tables to the Repository Protocol, the SQLite delegation, the
SQLAlchemy models, an Alembic migration, and the Postgres implementations.
The Postgres put_disclosure_ack uses ON CONFLICT DO NOTHING so idempotence
matches SQLite rather than diverging by backend, and both writes are
registered in _WRITE_METHODS so shadow mode mirrors them.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: `original/retention.py` — computation and the undated rule

**Files:**
- Create: `original/retention.py`
- Test: `tests/test_retention.py` (create)

**Interfaces:**
- Consumes: `Repository` (for manifests/fidelity timestamps), `StudentState`
- Produces:
  - `RETENTION_DAYS: dict[str, int]` — category → days
  - `last_activity(repo, student_id: str) -> str | None` — ISO string, or **None when undated**
  - `RetentionReport` dataclass with fields `eligible: dict[str, int]`, `undated: int`, `period_days: int`, `scanned: int`
  - `compute_retention_report(repo, now: datetime, tenant_id: str | None = None) -> RetentionReport`

- [ ] **Step 1: Write the failing test**

Create `tests/test_retention.py`:

```python
"""tests/test_retention.py — retention arithmetic, and the undated rule.

The undated rule (spec §2.2) is the load-bearing one: student_profiles has no
timestamp column and BaselineSample.submitted_at defaults to "", so a naive
missing-as-epoch implementation deletes the OLDEST, least-recoverable records
first, silently. Undated students must never be eligible.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from original import retention
from original.constants import FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState


NOW = datetime(2026, 8, 17, tzinfo=UTC)


def _sample(submitted_at: str) -> BaselineSample:
    return BaselineSample(
        features=np.full(FEATURE_DIM, 0.5),
        submitted_at=submitted_at,
    )


class _FakeRepo:
    """Minimal repo stand-in: only what retention reads."""

    def __init__(self, states: dict[str, StudentState]):
        self._states = states
        self.manifest_dates: dict[str, str] = {}
        self.fidelity_dates: dict[str, str] = {}
        self.name_dates: dict[str, str] = {}

    def all_states(self):
        return list(self._states.values())

    def get(self, student_id):
        return self._states.get(student_id)

    def last_manifest_at(self, student_id):
        return self.manifest_dates.get(student_id)

    def last_fidelity_at(self, student_id):
        return self.fidelity_dates.get(student_id)

    def display_name_updated_at(self, student_id):
        return self.name_dates.get(student_id)


def _state(student_id: str, samples: list[BaselineSample]) -> StudentState:
    st = StudentState(student_id=student_id)
    for s in samples:
        st.add_baseline_sample(s)
    return st


def test_undated_student_is_never_eligible():
    st = _state("stu-undated", [_sample("")])
    repo = _FakeRepo({"stu-undated": st})

    assert retention.last_activity(repo, "stu-undated") is None

    report = retention.compute_retention_report(repo, NOW)
    assert report.undated == 1
    assert sum(report.eligible.values()) == 0, (
        "an undated student must never appear as eligible for deletion"
    )


def test_student_older_than_one_year_is_eligible():
    old = (NOW - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
    st = _state("stu-old", [_sample(old)])
    repo = _FakeRepo({"stu-old": st})

    report = retention.compute_retention_report(repo, NOW)
    assert report.eligible["pii"] == 1
    assert report.undated == 0


def test_boundary_exactly_365_days_is_not_yet_eligible():
    edge = (NOW - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    st = _state("stu-edge", [_sample(edge)])
    repo = _FakeRepo({"stu-edge": st})

    report = retention.compute_retention_report(repo, NOW)
    assert report.eligible["pii"] == 0, "retention elapses AFTER the period, not at it"


def test_last_activity_takes_max_across_sources():
    older = (NOW - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
    newer = (NOW - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    st = _state("stu-mixed", [_sample(older)])
    repo = _FakeRepo({"stu-mixed": st})
    repo.manifest_dates["stu-mixed"] = newer

    assert retention.last_activity(repo, "stu-mixed") == newer
    report = retention.compute_retention_report(repo, NOW)
    assert report.eligible["pii"] == 0


def test_future_dated_activity_is_treated_as_recent_not_stale():
    future = (NOW + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    st = _state("stu-future", [_sample(future)])
    repo = _FakeRepo({"stu-future": st})

    report = retention.compute_retention_report(repo, NOW)
    assert report.eligible["pii"] == 0
    assert report.undated == 0


def test_report_states_the_period_it_used():
    repo = _FakeRepo({})
    report = retention.compute_retention_report(repo, NOW)
    assert report.period_days == 365
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_retention.py -v`
Expected: FAIL — `ImportError: cannot import name 'retention' from 'original'`

- [ ] **Step 3: Implement `original/retention.py`**

```python
"""
Retention computation — report-only.

docs/data_inventory.md §1 states retention periods for every data category and
§10.1 writes out the deletion order, then marks the whole section "Planned --
not implemented (no retention scheduler runs)". This module implements the
COMPUTATION half of that: it decides who is past retention. It deliberately
contains no deletion code at all -- see the spec's §3 for why enforcement is a
separate, separately-reviewed change.

THE UNDATED RULE (spec §2.2)
    student_profiles is `(student_id TEXT PRIMARY KEY, data TEXT NOT NULL)` --
    no timestamp column -- and BaselineSample.submitted_at defaults to "". A
    student can therefore have NO derivable activity date. Coercing that to
    epoch would make the oldest, most-established, least-recoverable records
    the FIRST to be deleted, silently. Such students are reported as `undated`
    and are never eligible. tests/test_retention.py asserts this directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

# Periods transcribed from docs/data_inventory.md §1. This module implements
# the written schedule; it does not invent one.
RETENTION_DAYS: dict[str, int] = {
    "pii": 365,
    "submissions": 365,
    "baselines": 365,
    "results": 365,
    "audit": 730,
}

DEFAULT_PERIOD_DAYS = 365


@dataclass
class RetentionReport:
    """What a sweep found. Counts only -- no student ids, ever."""

    eligible: dict[str, int] = field(default_factory=dict)
    undated: int = 0
    scanned: int = 0
    period_days: int = DEFAULT_PERIOD_DAYS


def _parse(ts: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating the store's trailing Z."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _maybe(repo, method: str, student_id: str) -> str | None:
    """Call an optional repo accessor; absent accessors contribute nothing."""
    fn = getattr(repo, method, None)
    if fn is None:
        return None
    try:
        return fn(student_id)
    except Exception:
        log.exception("retention: %s failed for a student", method)
        return None


def last_activity(repo, student_id: str) -> str | None:
    """Latest activity timestamp for a student, or None when UNDATED.

    None means "no date is derivable", which is NOT the same as "old". Callers
    must treat None as never-eligible.
    """
    candidates: list[str] = []

    state = repo.get(student_id)
    if state is not None:
        for sample in getattr(state, "baseline_samples", []) or []:
            ts = getattr(sample, "submitted_at", "")
            if ts:
                candidates.append(ts)

    for method in ("last_manifest_at", "last_fidelity_at", "display_name_updated_at"):
        ts = _maybe(repo, method, student_id)
        if ts:
            candidates.append(ts)

    parsed = [(p, raw) for raw in candidates if (p := _parse(raw)) is not None]
    if not parsed:
        return None
    return max(parsed, key=lambda pair: pair[0])[1]


def compute_retention_report(
    repo, now: datetime, tenant_id: str | None = None
) -> RetentionReport:
    """Count students past retention, per category. Deletes nothing."""
    report = RetentionReport(
        eligible=dict.fromkeys(RETENTION_DAYS, 0),
        period_days=DEFAULT_PERIOD_DAYS,
    )

    for state in repo.all_states():
        student_id = state.student_id
        if tenant_id is not None and not str(student_id).startswith(f"{tenant_id}:"):
            continue
        report.scanned += 1

        raw = last_activity(repo, student_id)
        if raw is None:
            report.undated += 1
            continue

        seen = _parse(raw)
        if seen is None:
            report.undated += 1
            continue

        for category, days in RETENTION_DAYS.items():
            if category == "audit":
                continue  # audit rows are not per-student; see the sweep
            if now - seen > timedelta(days=days):
                report.eligible[category] += 1

    return report
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_retention.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Verify no deletion code exists in the module**

Run: `grep -n "delete" original/retention.py`
Expected: no output. If anything matches, remove it — the Global Constraints forbid it.

- [ ] **Step 6: Commit**

```bash
git add original/retention.py tests/test_retention.py
git commit -m "Add report-only retention computation with the undated rule

Implements the retention schedule data_inventory.md §1 already specifies, as
pure functions with no deletion code anywhere in the module.

The load-bearing rule is that a student with no derivable activity date is
UNDATED and never eligible. student_profiles has no timestamp column and
BaselineSample.submitted_at defaults to \"\", so a missing-as-epoch
implementation would delete the oldest and least recoverable records first,
silently. A test asserts undated students never appear as eligible.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Shadow-only sweep loop and lifespan wiring

**Files:**
- Create: `original/retention_sweep.py`
- Modify: `original/api.py` (lifespan, ~line 152–176)
- Test: `tests/test_retention.py` (append)

**Interfaces:**
- Consumes: `retention.compute_retention_report`, `RetentionReport`
- Produces: `retention_sweep.sweep_once(repo, now) -> RetentionReport`, `retention_sweep.sweep_loop(repo, interval_hours: float)`, `retention_sweep.enabled() -> bool`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_retention.py`:

```python
def test_sweep_disabled_by_default(monkeypatch):
    from original import retention_sweep

    monkeypatch.delenv("RETENTION_SWEEP_ENABLED", raising=False)
    assert retention_sweep.enabled() is False


def test_sweep_enabled_by_flag(monkeypatch):
    from original import retention_sweep

    monkeypatch.setenv("RETENTION_SWEEP_ENABLED", "1")
    assert retention_sweep.enabled() is True


def test_sweep_once_logs_and_deletes_nothing(caplog, monkeypatch):
    from original import retention_sweep

    old = (NOW - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
    st = _state("t1:stu-old", [_sample(old)])
    repo = _FakeRepo({"t1:stu-old": st})

    with caplog.at_level("INFO"):
        report = retention_sweep.sweep_once(repo, NOW)

    assert report.eligible["pii"] == 1
    assert "retention_sweep" in caplog.text
    assert "period_days=365" in caplog.text
    # The repo stand-in has no delete method at all; if the sweep tried to
    # delete, it would AttributeError. Assert the intent explicitly too.
    assert not hasattr(repo, "delete_student")


def test_sweep_module_contains_no_deletion_call():
    """Enforcement is a separate, separately-reviewed change (spec §3)."""
    from pathlib import Path

    src = Path("original/retention_sweep.py").read_text()
    assert "delete_student" not in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_retention.py -v -k sweep`
Expected: FAIL — `ImportError: cannot import name 'retention_sweep'`

- [ ] **Step 3: Implement `original/retention_sweep.py`**

```python
"""
Retention sweep — SHADOW ONLY.

Computes the retention report on a timer and logs it. It does not delete, and
the code to delete from a sweep does not exist in this module -- not behind a
flag, not commented out. A flag that cannot be flipped is safer than one that
can be flipped by mistake; enforcement should be a separate change reviewed
against real soak data (spec §3).

The number to watch in a soak is `undated`. A meaningful undated population
means date coverage is too poor to enforce against at all, whatever the
eligible counts say.

Configuration (env):
    RETENTION_SWEEP_ENABLED         "1" turns the sweep on. Default off.
    RETENTION_SWEEP_INTERVAL_HOURS  cadence (default 24).
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime

from .retention import RetentionReport, compute_retention_report

log = logging.getLogger(__name__)


def enabled() -> bool:
    return os.environ.get("RETENTION_SWEEP_ENABLED", "0") == "1"


def interval_hours() -> float:
    try:
        return float(os.environ.get("RETENTION_SWEEP_INTERVAL_HOURS", "24") or 24)
    except ValueError:
        return 24.0


def sweep_once(repo, now: datetime | None = None) -> RetentionReport:
    """Compute and log one report. Returns it for tests. Deletes nothing."""
    report = compute_retention_report(repo, now or datetime.now(UTC))
    log.info(
        "retention_sweep scanned=%d eligible_pii=%d eligible_submissions=%d "
        "eligible_baselines=%d eligible_results=%d undated=%d period_days=%d "
        "mode=report_only",
        report.scanned,
        report.eligible.get("pii", 0),
        report.eligible.get("submissions", 0),
        report.eligible.get("baselines", 0),
        report.eligible.get("results", 0),
        report.undated,
        report.period_days,
    )
    return report


async def sweep_loop(repo, hours: float) -> None:
    """Run sweep_once forever on a timer. Cancelled by the API lifespan."""
    while True:
        try:
            sweep_once(repo)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("retention sweep failed; will retry next interval")
        await asyncio.sleep(hours * 3600)
```

- [ ] **Step 4: Wire into the lifespan**

In `original/api.py`, inside `lifespan`, immediately after the backup-scheduler block and **before** `yield`:

```python
    # Retention sweep — report-only (original/retention_sweep.py). Computes
    # who is past the retention schedule and logs counts; deletes nothing.
    # Off by default: flag-off does not create the task or import the module.
    _retention_task = None
    if retention_sweep_mod.enabled():
        _hours = retention_sweep_mod.interval_hours()
        _retention_task = asyncio.create_task(
            retention_sweep_mod.sweep_loop(_repo(), _hours)
        )
        _log.info("Retention sweep: every %.1f h (report-only, deletes nothing).", _hours)
```

And after `yield`, alongside the backup-task cancel:

```python
    if _retention_task is not None:
        _retention_task.cancel()
```

Add the import near the existing `backup_mod` import at the top of `api.py`:

```python
from . import retention_sweep as retention_sweep_mod
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_retention.py -v`
Expected: PASS — 10 passed

- [ ] **Step 6: Verify flag-off starts the app unchanged**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_imports_api_coverage.py -q`
Expected: PASS — the app still imports and starts with the flag unset.

- [ ] **Step 7: Commit**

```bash
git add original/retention_sweep.py original/api.py tests/test_retention.py
git commit -m "Add shadow-only retention sweep on the API lifespan timer

Mirrors backup.py's in-app scheduler idiom, so no Celery or Redis is needed.
The sweep computes the retention report and logs counts; it deletes nothing,
and the code to delete from a sweep does not exist in the module -- asserted
by a test that greps the source. A flag that cannot be flipped is safer than
one that can be flipped by mistake.

undated is the number to watch in a soak: a meaningful undated population
means date coverage is too poor to enforce against at all.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: API endpoints

**Files:**
- Create: `original/routers/governance.py`
- Modify: `original/api.py` (router registration — find the existing `include_router` block)
- Test: `tests/test_governance_api.py` (create)

**Interfaces:**
- Consumes: repository methods from Task 3, `retention.compute_retention_report`
- Produces: five HTTP endpoints (table below)

| Endpoint | Method | Auth |
|---|---|---|
| `/admin/tenants/{tenant_id}/authorization` | POST | `_require_staff` |
| `/admin/tenants/{tenant_id}/authorization` | GET | `_require_staff` |
| `/students/{student_id}/disclosure-ack` | POST | `_require_staff` |
| `/students/{student_id}/disclosure-ack` | GET | `_require_staff` |
| `/admin/retention/candidates` | GET | `_require_staff` + `_require_guard` |

- [ ] **Step 1: Write the failing test**

Create `tests/test_governance_api.py`:

```python
"""tests/test_governance_api.py — governance endpoints."""

from __future__ import annotations

import pytest


def test_record_and_read_tenant_authorization(live_client, store_reset):
    r = live_client.post(
        "/admin/tenants/demo/authorization",
        json={
            "document_type": "dpa",
            "document_version": "dpa_template.md@2026-07-07",
            "executed_at": "2026-07-07T00:00:00Z",
            "officer_name": "A. Registrar",
            "officer_title": "Registrar",
        },
        headers={"x-demo-role": "admin"},
    )
    assert r.status_code == 200, r.text

    g = live_client.get(
        "/admin/tenants/demo/authorization", headers={"x-demo-role": "admin"}
    )
    assert g.status_code == 200
    body = g.json()
    assert body["current"]["document_version"] == "dpa_template.md@2026-07-07"
    assert len(body["history"]) == 1


def test_disclosure_ack_roundtrip(live_client, store_reset):
    r = live_client.post(
        "/students/demo:stu-1/disclosure-ack",
        json={
            "disclosure_version": "STUDENT_DISCLOSURE.md@2026-07-07",
            "context": "manual",
        },
        headers={"x-demo-role": "professor"},
    )
    assert r.status_code == 200, r.text

    g = live_client.get(
        "/students/demo:stu-1/disclosure-ack", headers={"x-demo-role": "professor"}
    )
    assert g.status_code == 200
    assert len(g.json()["acknowledgments"]) == 1


def test_retention_candidates_reports_undated(live_client, store_reset):
    r = live_client.get(
        "/admin/retention/candidates", headers={"x-demo-role": "admin"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "undated" in body
    assert "eligible" in body
    assert body["period_days"] == 365
    assert body["mode"] == "report_only"


def test_retention_candidates_requires_guard_when_guarded(
    live_client, store_reset, monkeypatch
):
    """It enumerates who is closest to deletion -- exactly the reconnaissance
    an attacker wants -- so it sits behind the destructive guard."""
    import original.routers._shared as shared

    monkeypatch.setattr(shared, "_GUARD_DESTRUCTIVE", True, raising=False)
    r = live_client.get(
        "/admin/retention/candidates", headers={"x-demo-role": "admin"}
    )
    assert r.status_code in (401, 403)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_governance_api.py -v`
Expected: FAIL — 404 on every endpoint

- [ ] **Step 3: Implement the router**

Create `original/routers/governance.py`, following `original/routers/tenants.py`'s structure:

```python
"""
Governance endpoints — institutional authorization, student notice, and the
report-only retention candidate list.

See docs/superpowers/specs/2026-08-17-consent-retention-design.md.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from .. import retention
from ._shared import _repo, _require_guard, _require_staff

router = APIRouter()


class AuthorizationIn(BaseModel):
    document_type: str = Field(..., description="'dpa' | 'school_official_designation'")
    document_version: str
    executed_at: str = Field(..., description="ISO-8601; when the institution signed")
    officer_name: str = ""
    officer_title: str = ""
    notes: str = ""


class DisclosureAckIn(BaseModel):
    disclosure_version: str
    context: str = "manual"


@router.post("/admin/tenants/{tenant_id}/authorization", operation_id="record_authorization")
async def record_authorization(tenant_id: str, body: AuthorizationIn, request: Request):
    p = _require_staff(request)
    row_id = _repo().put_tenant_authorization(
        tenant_id,
        body.document_type,
        body.document_version,
        body.executed_at,
        officer_name=body.officer_name,
        officer_title=body.officer_title,
        recorded_by=getattr(p, "user_id", ""),
        notes=body.notes,
    )
    _repo().log_audit(
        action="authorization_recorded",
        tenant_id=tenant_id,
        actor=getattr(p, "user_id", ""),
        result="ok",
        details={"document_type": body.document_type,
                 "document_version": body.document_version},
    )
    return {"id": row_id}


@router.get("/admin/tenants/{tenant_id}/authorization", operation_id="get_authorization")
async def get_authorization(tenant_id: str, request: Request):
    _require_staff(request)
    repo = _repo()
    return {
        "current": repo.current_tenant_authorization(tenant_id),
        "history": repo.list_tenant_authorizations(tenant_id),
    }


@router.post("/students/{student_id}/disclosure-ack", operation_id="record_disclosure_ack")
async def record_disclosure_ack(student_id: str, body: DisclosureAckIn, request: Request):
    _require_staff(request)
    tenant_id = student_id.split(":", 1)[0] if ":" in student_id else ""
    row_id = _repo().put_disclosure_ack(
        student_id, tenant_id, body.disclosure_version, context=body.context
    )
    return {"id": row_id}


@router.get("/students/{student_id}/disclosure-ack", operation_id="list_disclosure_acks")
async def list_disclosure_acks(student_id: str, request: Request):
    _require_staff(request)
    return {"acknowledgments": _repo().list_disclosure_acks(student_id)}


@router.get("/admin/retention/candidates", operation_id="retention_candidates")
async def retention_candidates(request: Request):
    """Report-only. Deletes nothing.

    Guarded despite being read-only: it enumerates which students are closest
    to deletion, which is exactly the reconnaissance an attacker would want.
    """
    _require_staff(request)
    _require_guard(request)
    report = retention.compute_retention_report(_repo(), datetime.now(UTC))
    return {
        "eligible": report.eligible,
        "undated": report.undated,
        "scanned": report.scanned,
        "period_days": report.period_days,
        "mode": "report_only",
    }
```

- [ ] **Step 4: Register the router**

In `original/api.py`, find the existing `app.include_router(...)` block and add, matching the surrounding style:

```python
from .routers import governance as governance_router
...
app.include_router(governance_router.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_governance_api.py -v`
Expected: PASS — 4 passed

- [ ] **Step 6: Check OpenAPI stability**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_openapi_stability.py -q`
Expected: PASS. If it fails because it pins a route inventory, update that fixture to include the five new `operation_id`s — that is the intended maintenance, not a workaround.

- [ ] **Step 7: Commit**

```bash
git add original/routers/governance.py original/api.py tests/test_governance_api.py
git commit -m "Add governance endpoints for authorization, notice, and retention

Records DPA execution per tenant, disclosure notice per student, and exposes
the report-only retention candidate list. The candidates endpoint is
read-only but sits behind GUARD_DESTRUCTIVE anyway: it enumerates which
students are closest to deletion, which is exactly the reconnaissance an
attacker would want.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Deletion completeness and documentation

**Files:**
- Modify: `original/store.py` (`delete_student` ~line 1634; `student_data_inventory` ~line 3000)
- Modify: `docs/data_inventory.md` (§1 table note, §10.1)
- Modify: `CLAUDE.md` (env flag table)
- Test: `tests/test_governance_store.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 1–6
- Produces: no new API

- [ ] **Step 1: Write the failing test**

Append to `tests/test_governance_store.py`:

```python
def test_delete_student_purges_disclosure_acks(db):
    import numpy as np
    from original.constants import FEATURE_DIM
    from original.quantum.state import BaselineSample, StudentState

    st = StudentState(student_id="t1:stu-1")
    st.add_baseline_sample(
        BaselineSample(features=np.full(FEATURE_DIM, 0.5), submitted_at="2026-01-01T00:00:00Z")
    )
    db.put(st)
    db.put_disclosure_ack("t1:stu-1", "t1", "v1")
    assert len(db.list_disclosure_acks("t1:stu-1")) == 1

    db.delete_student("t1:stu-1")
    assert db.list_disclosure_acks("t1:stu-1") == []


def test_data_inventory_reports_disclosure_acks(db):
    import numpy as np
    from original.constants import FEATURE_DIM
    from original.quantum.state import BaselineSample, StudentState

    st = StudentState(student_id="t1:stu-2")
    st.add_baseline_sample(
        BaselineSample(features=np.full(FEATURE_DIM, 0.5), submitted_at="2026-01-01T00:00:00Z")
    )
    db.put(st)
    db.put_disclosure_ack("t1:stu-2", "t1", "v1")

    inv = db.student_data_inventory("t1:stu-2")
    assert inv is not None
    assert inv["disclosure_acknowledgments"] == 1
```

Note: `tenant_authorizations` is intentionally NOT purged by `delete_student` — it is a record about the institution, not the student, and deleting it would destroy the audit trail for every other student in that tenant.

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_governance_store.py -v -k "delete or inventory"`
Expected: FAIL — acks survive deletion; `KeyError: 'disclosure_acknowledgments'`

- [ ] **Step 3: Extend `delete_student`**

In `original/store.py`'s `delete_student`, alongside the other per-student DELETE statements:

```python
            conn.execute(
                "DELETE FROM disclosure_acknowledgments WHERE student_id = ?",
                (student_id,),
            )
```

Update the function's docstring list to include `disclosure_acknowledgments`, and add a line noting that `tenant_authorizations` is deliberately retained (institution-scoped, not student data).

- [ ] **Step 4: Extend `student_data_inventory`**

In `original/store.py`'s `student_data_inventory`, alongside the other counts:

```python
            disclosure_count = conn.execute(
                "SELECT COUNT(*) FROM disclosure_acknowledgments WHERE student_id = ?",
                (student_id,),
            ).fetchone()[0]
```

Add `"disclosure_acknowledgments": disclosure_count` to the returned dict.

- [ ] **Step 5: Run tests to verify they pass**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_governance_store.py -v`
Expected: PASS — 10 passed

- [ ] **Step 6: Update `docs/data_inventory.md`**

In §10.1, replace the `> **Planned — not implemented in the pilot stack (no retention scheduler runs).**` blockquote with:

```markdown
> **Computed and reported — NOT enforcing (2026-08-17).** A report-only sweep
> (`original/retention_sweep.py`, `RETENTION_SWEEP_ENABLED=1`, default off)
> computes who is past each retention period and logs counts; an admin can
> read the same report at `GET /admin/retention/candidates`. **Nothing is
> deleted automatically** — the code to delete from a sweep does not exist,
> deliberately. Retention periods below remain policy targets that no code
> enforces; today deletion still happens only via the manual path in §10.2.
>
> **Known coverage gap:** `student_profiles` has no timestamp column and
> `BaselineSample.submitted_at` defaults to empty, so some students have no
> derivable activity date. These are reported as `undated` and are never
> treated as eligible. A large `undated` count means the date coverage is too
> poor to enforce retention against at all — that number, not the eligible
> counts, is what decides whether enforcement is ever safe to build.
```

In §1, append to the header row note: retention periods are now *computed and reported* but still not *enforced*.

Add a short subsection documenting `tenant_authorizations` and `disclosure_acknowledgments` as data categories, noting that the former is institution-scoped (survives student deletion) and the latter is purged with the student.

- [ ] **Step 7: Update `CLAUDE.md`**

Add two rows to the env flag table, matching the existing style:

```markdown
| `RETENTION_SWEEP_ENABLED` | `0` | Report-only retention sweep (`original/retention_sweep.py`). Computes who is past the `data_inventory.md` §1 retention periods and logs one INFO `retention_sweep …` line per cycle; also readable at `GET /admin/retention/candidates`. **Deletes nothing** — the code to delete from a sweep does not exist, not even behind a disabled flag, so enforcement cannot be turned on by accident. The number that matters in a soak is `undated`: `student_profiles` has no timestamp column and `BaselineSample.submitted_at` defaults to `""`, so students with no derivable date are reported separately and are **never** eligible. A large `undated` count means date coverage is too poor to enforce against at all, whatever the eligible counts say. |
| `RETENTION_SWEEP_INTERVAL_HOURS` | `24` | Sweep cadence when the above is on. |
```

- [ ] **Step 8: Run the full suite once**

Run in background (it takes ~11 min and will outrun the tool timeout):
```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py --cov=original --cov-fail-under=78 -q
```
Expected: 0 failed. Coverage should rise slightly (new code is well covered).

- [ ] **Step 9: Commit**

```bash
git add original/store.py docs/data_inventory.md CLAUDE.md tests/test_governance_store.py
git commit -m "Purge disclosure acks on student deletion and correct the retention docs

delete_student now removes disclosure_acknowledgments and
student_data_inventory reports them, so FERPA deletion and access requests
stay complete. tenant_authorizations is deliberately NOT purged: it is a
record about the institution, and deleting it would destroy the audit trail
for every other student in that tenant.

data_inventory.md §10.1 stops saying \"Planned -- not implemented\" and now
says computed-but-not-enforcing, including the undated coverage gap. The gap
between policy and reality should be visible in the document rather than
resolved by optimistic wording.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §1.1 `tenant_authorizations` | 1 |
| §1.2 `disclosure_acknowledgments` (incl. UNIQUE, no `declined`) | 2 |
| §2.1 last-activity derivation | 4 |
| §2.2 undated rule | 4 (test-asserted) |
| §2.3 categories and periods | 4 |
| §3 sweeper, flags, no enforcement flag | 5 |
| §4 API + CLI surface | 6, 7 |
| §5 documentation | 7 |
| §6 test plan | distributed; every row covered |
| §7 scope boundary (no Bluebook frontend) | respected — no `.jsx` or bundle work anywhere |

**Gap found and closed during review:** §4 lists extending `original.cli.delete_student`. The CLI calls `store.delete_student()`, which Task 7 Step 3 extends, so the CLI inherits the fix without its own change — noted here so a reader does not think it was dropped. Postgres `delete_student` also needs the same DELETE; **added to Task 3 Step 8's scope** (implement the five methods *and* extend the Postgres `delete_student` to purge `disclosure_acknowledgments`).

**Type consistency:** `RetentionReport` fields (`eligible`, `undated`, `scanned`, `period_days`) are used identically in Tasks 4, 5, and 6. Store function signatures in Task 1/2 match the Protocol in Task 3 and the router calls in Task 6.

**Known limitation:** Postgres paths are unverifiable locally without a `DATABASE_URL` — those contract cases will SKIP. CI runs them against a Postgres 16 service container, so the PR's own CI run is the real test of Task 3, exactly as it was for the lockout fix.
