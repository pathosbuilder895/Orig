# Rebase `docs/section9-implementation-plans` onto latest `main` (WS-6 P3–P6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `docs/section9-implementation-plans` (currently 6 commits behind `origin/main`, PR #79 showing `CONFLICTING`) fully up to date with `main`'s WS-6 P3–P6 Postgres convergence (PostgresRepository is now a real implementation, not a skeleton; the entire dormant v1 stack is deleted), while porting forward this branch's genuinely-new work — Bluebook exam-day robustness (server-pinned sessions, idempotent sealing) and the corrections-UI design spec — with the new Bluebook-session methods implemented for real against Postgres, not stubbed.

**Architecture:** Not a literal `git rebase -i` replaying ~20 historical commits — main deleted ~2,100 statements of v1 code that many of those commits touch, so commit-by-commit replay would conflict repeatedly on code that no longer exists. Instead: a **transplant** — start a fresh branch from `origin/main`, port forward only the branch's genuinely-unique content (confirmed by content-diffing, not just path-diffing — several apparent differences turned out to be byte-identical files that reached both branches via different history, and two of this branch's recent e2e fixes turn out to be workarounds for a temporary merged state that don't apply to true `main`). Net effect is the same as a rebase (linear history, `main` as base, no merge commit) with each step independently testable.

**Tech Stack:** FastAPI + dual backend (SQLite via `original/store.py`, Postgres via `original/postgres_repository.py` + SQLAlchemy), alembic, pytest, Playwright, esbuild.

## Global Constraints

- All work happens in `/Users/andrew/Desktop/Original`. Python: `.venv/bin/python` only.
- **Do not force-push until the final task, and only after re-fetching to confirm no one else has pushed to `origin/docs/section9-implementation-plans` in the meantime** — this branch has been actively worked by a parallel session twice already this week.
- Full suite must be **0 failed** against BOTH backends before the final push (SQLite default, and Postgres via `DATABASE_URL`) — this is the plan's core "testability & correctness" requirement per the user's explicit ask.
- After any `demo/bluebook/*.jsx` change: `cd demo/bluebook && npm run build` and commit the bundle.
- Leave `demo/app/` (still-undecided) and `demo/prototypes/` (user's own WIP) completely untouched.
- Commit style: `Add ...`/`Fix ...` + `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.

## Reference facts gathered during investigation (do not re-derive — verified 2026-07-22)

- `origin/main` HEAD: `f2d706d`. Single alembic revision, `20128da16c79` (root and head) — **unchanged by P3–P6**. This branch's existing `alembic/versions/7c4d1e88a3b5_bluebook_sessions_and_seal_idempotency.py` (`down_revision="20128da16c79"`) already chains onto the correct head — no revision-chain edit needed, just re-add the file.
- `original/db/models/live.py` on main: **unchanged by P3–P6**, still 16 models, `LIVE_MODELS` still a flat list. Appending `BluebookSession` + `submission_uuid`/`late` on `BluebookSubmission` is a clean, conflict-free addition.
- `PostgresRepository` moved to its own file, `original/postgres_repository.py` (1837 lines, 70 methods, only `db_path()` still `_todo`). `original/repository.py` now re-exports it lazily via `__getattr__` (PEP 562) so plain SQLite runs never import sqlalchemy. `get_repository()` now switches on `REPO_BACKEND=postgres` / `REPO_SHADOW=postgres` env vars via a new `ShadowRepository` class (mirrors writes to a shadow backend, logs divergence, never raises to the caller).
- Method pattern (verified against `put_bluebook_exam`/`get_bluebook_exam`/`list_bluebook_exams`, `original/postgres_repository.py:1409-1465`): `with session_scope() as session:` + try/except (reads → log+return `None`/`[]` on failure, writes → log+re-raise); `pg_insert(Model).values(...).on_conflict_do_update(index_elements=[...], set_=values)` for upserts; `session.get(Model, pk)` for single-row reads (composite PKs: `session.get(Model, (pk1, pk2))`, tuple form, supported in this SQLAlchemy version — verify in Task 2); `select(Model).where(...)` for filtered lists. Tenant-scoped writes call `self._ensure_tenant_exists(session, tenant_id)` first (idempotent placeholder-tenant insert, `postgres_repository.py:89`).
- `original/db/postgres_session.py` was substantially rewritten by P3 (added `init_db()`/`drop_db()`, renamed `_SessionFactory`→`_SessionLocal`, `get_session_factory()` now public). This branch's P2-era copy is fully superseded — adopt main's wholesale, no merge needed.
- `original/db/tenancy.py` (this branch) has **zero call sites anywhere** — dead code, added in P2 ahead of its P3 consumer. Main's `original/db/tenancy_shim.py` (different name, different contract: `split_scoped_id` never returns `None`, returns a `_LEGACY_FLAT_TENANT` sentinel instead) is what `postgres_repository.py` and the migration script actually import. **Delete `original/db/tenancy.py` outright** — nothing references it.
- `scripts/migrate_sqlite_to_pg.py` (P4, main-only, 1209 lines) is **per-table explicit**, not generic over `LIVE_MODELS` — one `_XMigrator` subclass per table, all instantiated into a `MIGRATORS` list (`:1017-1034`). A `bluebook_sessions` table needs a new `_BluebookSessionMigrator` added to that list, or the migration script silently skips the table.
- `ShadowRepository`'s `_WRITE_METHODS` frozenset (`original/repository.py`, ~24 entries) explicitly lists every mutating method it mirrors to the shadow backend. `get_or_create_bluebook_session` (a write) must be added to this set or `REPO_SHADOW` mode silently never mirrors Bluebook sessions.
- `.github/workflows/test.yml`'s `pytest` job now runs a real `postgres:16` service container (`POSTGRES_USER=original`, `POSTGRES_PASSWORD=original`, `POSTGRES_DB=original_test`, port 5432) with `DATABASE_URL=postgresql://original:original@localhost:5432/original_test`. Coverage floor `--cov-fail-under=72`.
- `original/canvas/` is **entirely gone** on main and has zero live import dependents (confirmed via grep on both branches) — safe to delete outright.
- `original/core/config.py` and `original/db/session.py` still exist on main (intentionally kept as documented-dormant v1 remnants per `postgres_session.py`'s docstring) — leave them, not part of this branch's deletion set.
- **Locally available for Postgres testing:** Docker is installed; a `postgres:16-alpine` container named `bbook-postgres` is already running, mapped to host port 5432 (`POSTGRES_USER=postgres`, `POSTGRES_PASSWORD=postgres`, `POSTGRES_DB=bbook`). Reuse it — create a new `original_test` database inside it rather than starting a second container (a second container can't also bind host port 5432).
- `demo/bluebook/NewExam.jsx`'s `canSubmit` gating on main **already matches** this branch's fix (`title.trim() && duration && prompts.some(p => p.trim())`, no course requirement) — no change needed, just confirm on adoption.
- `demo/bluebook/e2e/exam-flow.spec.mjs` on main **already has** `mintProctorAttestation()` + storing it via `bootInExam` (the other session's real fix, already merged into this branch too at `5450b3d`) — the strict `expect(...provenance === 'proctored').toBe(true)` assertion is CORRECT there. This branch's earlier loosened assertion (`['proctored','unverified'].includes(...)`) should be **tightened back** to match, not carried forward loose — the real fix means it should always be `'proctored'` now.
- `demo/bluebook/e2e/professor-journey.spec.mjs` on main **does not have** the verbose `#neCourse` visibility/text assertion block this branch added (the one with the `courseName` `ReferenceError` bug) — main just has a one-line comment and moves on. **Adopt main's simpler version** rather than porting forward a fix for code that shouldn't exist post-reconciliation.
- `original/api.py` and `original/schemas.py` on main have **no** Bluebook-session endpoint, `REPO_BACKEND` read, or `submission_uuid` field — this branch's API/schema work (Task 3 of the earlier exam-robustness plan) is genuinely net-new and must be fully re-applied.

---

### Task 1: Start the transplant branch, confirm clean baseline

**Files:** none (git operations only)

- [ ] **Step 1: Fetch and create the new branch**

```bash
git fetch origin main docs/section9-implementation-plans
git branch transplant-backup-$(date +%Y%m%d) docs/section9-implementation-plans   # safety ref, not pushed
git checkout -b docs/section9-implementation-plans-transplant origin/main
```

- [ ] **Step 2: Verify main's own suite is green before adding anything**

Run: `.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q`
Expected: matches the README's claim (~775 passed, 0 failed) — if not, STOP and report; don't build on a red base.

---

### Task 2: Port the `BluebookSession` model + `submission_uuid`/`late` columns

**Files:**
- Modify: `original/db/models/live.py` (append model to the file, `BluebookSubmission` gets 2 new columns, `LIVE_MODELS` gets one append)
- Create: `alembic/versions/7c4d1e88a3b5_bluebook_sessions_and_seal_idempotency.py` (re-add verbatim from the old branch — already correct, `down_revision="20128da16c79"` matches main's actual head)

**Interfaces:**
- Produces: `BluebookSession` SQLAlchemy model (`exam_id`, `student_key` composite PK; `tenant_id` FK; `started_at`, `deadline_at` `DateTime(timezone=True)`), `BluebookSubmission.submission_uuid: str | None` (unique), `BluebookSubmission.late: int`.

- [ ] **Step 1: Add the columns to `BluebookSubmission`**

In `original/db/models/live.py`, find the `BluebookSubmission` class's `created_at` column and add directly after it:

```python
    # Idempotent sealing (Bluebook exam-day robustness): client seal id --
    # replays with the same uuid return the prior row instead of writing a
    # second one.
    submission_uuid: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    late: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
```

- [ ] **Step 2: Add the `BluebookSession` model**

Directly after the `BluebookSubmission` class (before the next class, likely `BluebookCourse`):

```python
class BluebookSession(LiveBase):
    """One (exam, student) sitting (``bluebook_sessions``): pins the immutable
    server deadline (exam-day robustness). The first insert wins; reopening
    the exam returns the same row, so the clock can never be restarted or
    paused by closing the tab.
    """

    __tablename__ = "bluebook_sessions"

    exam_id: Mapped[str] = mapped_column(Text, primary_key=True)
    student_key: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.tenant_id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

- [ ] **Step 3: Append to `LIVE_MODELS`**

Find `BluebookSubmission,` in the `LIVE_MODELS` list and add `BluebookSession,` directly after it. Update the preceding comment from `#: All 16 live models...` to `#: All 17 live models...`.

- [ ] **Step 4: Re-add the alembic revision file**

Write `alembic/versions/7c4d1e88a3b5_bluebook_sessions_and_seal_idempotency.py` with this exact content:

```python
"""bluebook sessions + seal idempotency

Exam-day robustness: a ``bluebook_sessions`` table pinning one immutable
server deadline per (exam, student) sitting, and ``submission_uuid``/``late``
on ``bluebook_submissions`` so a retried seal replays idempotently instead
of double-writing. Mirrors the SQLite DDL in original/store.py; models in
original/db/models/live.py (``BluebookSession``).

Revision ID: 7c4d1e88a3b5
Revises: 20128da16c79
Create Date: 2026-07-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7c4d1e88a3b5"
down_revision: str | None = "20128da16c79"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bluebook_sessions",
        sa.Column("exam_id", sa.Text(), primary_key=True),
        sa.Column("student_key", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.tenant_id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column("bluebook_submissions", sa.Column("submission_uuid", sa.Text(), nullable=True))
    op.add_column(
        "bluebook_submissions",
        sa.Column("late", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "idx_bluebook_subs_uuid",
        "bluebook_submissions",
        ["submission_uuid"],
        unique=True,
        postgresql_where=sa.text("submission_uuid IS NOT NULL"),
        sqlite_where=sa.text("submission_uuid IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_bluebook_subs_uuid", table_name="bluebook_submissions")
    op.drop_column("bluebook_submissions", "late")
    op.drop_column("bluebook_submissions", "submission_uuid")
    op.drop_table("bluebook_sessions")
```

- [ ] **Step 5: Verify the model + migration are structurally sound**

Run: `.venv/bin/python -c "from original.db.models.live import LIVE_MODELS, BluebookSession; print(len(LIVE_MODELS), BluebookSession.__tablename__)"`
Expected: `17 bluebook_sessions`

Run: `.venv/bin/python -m alembic heads` (from repo root, with `alembic.ini` present)
Expected: `7c4d1e88a3b5 (head)`

- [ ] **Step 6: Commit**

```bash
git add original/db/models/live.py alembic/versions/7c4d1e88a3b5_bluebook_sessions_and_seal_idempotency.py
git commit -m "Add BluebookSession model + submission_uuid/late columns on top of WS-6 P3-P6

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Set up local Postgres test target

**Files:** none (infrastructure only)

- [ ] **Step 1: Create a fresh test database in the already-running container**

```bash
docker exec bbook-postgres psql -U postgres -c "DROP DATABASE IF EXISTS original_test;"
docker exec bbook-postgres psql -U postgres -c "CREATE DATABASE original_test;"
```

- [ ] **Step 2: Export `DATABASE_URL` for this session's verification runs**

```bash
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/original_test"
```

(Use this exact export before every Postgres-targeted test run in later tasks — note the container's actual credentials are `postgres`/`postgres`, not the code's `original`/`original` fallback default; `DATABASE_URL` overrides the default either way so this is fine.)

- [ ] **Step 3: Prove connectivity + schema creation**

```bash
.venv/bin/python -c "
from original.db.postgres_session import get_engine, reset_engine
from original.db.models.live import LiveBase
reset_engine()
LiveBase.metadata.create_all(bind=get_engine())
print('17 tables created:', len(LiveBase.metadata.tables))
"
```

Expected: `17 tables created: 17` (16 from main + `bluebook_sessions`). If this fails on a connection error, confirm `docker ps` still shows `bbook-postgres` running and port 5432 is reachable (`docker port bbook-postgres`).

---

### Task 4: Implement the 3 Bluebook-session methods on `PostgresRepository` for real

**Files:**
- Modify: `original/postgres_repository.py` (add 3 methods to the Bluebook section, add `BluebookSession` to the model imports)
- Modify: `original/repository.py` (Protocol + `SqliteRepository`: re-add the 3-method diff this branch already had; add `get_or_create_bluebook_session` to `_WRITE_METHODS`)
- Test: `tests/test_repository_contract.py` (parametrized `TestBluebook` class — runs against BOTH `sqlite` and `postgres` params)

**Interfaces:**
- Produces: `Repository.get_or_create_bluebook_session(exam_id, student_key, tenant_id, duration_seconds) -> dict`, `Repository.get_bluebook_session(exam_id, student_key) -> dict | None`, `Repository.get_bluebook_submission_by_uuid(submission_uuid) -> dict | None` — real on both backends now, no `_todo` anywhere.

- [ ] **Step 1: Write the failing contract tests**

In `tests/test_repository_contract.py`, inside the existing `TestBluebook` class (or a new `TestBluebookSessions` class in the same file, matching the file's parametrization pattern — check whether main's copy still uses the `repo` fixture parametrized over `BACKENDS`/`["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)]`, and match that exactly):

```python
    def test_session_deadline_is_pinned(self, repo):
        first = repo.get_or_create_bluebook_session("ex-c1", "sem:al", "sem", 1800)
        again = repo.get_or_create_bluebook_session("ex-c1", "sem:al", "sem", 1800)
        assert first["created"] and not again["created"]
        assert again["deadline_at"] == first["deadline_at"]
        assert repo.get_bluebook_session("ex-c1", "sem:al")["deadline_at"] == first["deadline_at"]
        assert repo.get_bluebook_session("ex-c1", "sem:nobody") is None

    def test_submission_uuid_lookup(self, repo):
        repo.put_bluebook_submission(
            {
                "id": "bbsub-uu", "tenant_id": "sem", "exam_id": "ex-c1",
                "student_id": "sem:al", "submission_uuid": "uu-contract-1", "late": 1,
            }
        )
        got = repo.get_bluebook_submission_by_uuid("uu-contract-1")
        assert got["id"] == "bbsub-uu" and got["late"] == 1
        assert repo.get_bluebook_submission_by_uuid("uu-none") is None
```

- [ ] **Step 2: Run to verify it fails on BOTH backends**

Run: `DATABASE_URL="postgresql://postgres:postgres@localhost:5432/original_test" .venv/bin/python -m pytest "tests/test_repository_contract.py::TestBluebook::test_session_deadline_is_pinned" "tests/test_repository_contract.py::TestBluebook::test_submission_uuid_lookup" -v`
Expected: 4 tests (2 tests × 2 backends) — `[sqlite]` variants FAIL with `AttributeError`; `[postgres]` variants FAIL too (either `AttributeError` on `SqliteRepository`'s missing methods, or the postgres param may currently be skipped if `_postgres_available()` hasn't been re-checked — confirm `DATABASE_URL` is exported in this shell before running).

- [ ] **Step 3: Add the 3 methods to `original/repository.py`'s Protocol**

Find `put_bluebook_submission(self, rec: dict) -> None: ...` in the Protocol and add directly after `list_bluebook_submissions`:

```python
    def get_bluebook_submission_by_uuid(self, submission_uuid: str) -> dict | None: ...
    def get_or_create_bluebook_session(
        self, exam_id: str, student_key: str, tenant_id: str, duration_seconds: int
    ) -> dict: ...
    def get_bluebook_session(self, exam_id: str, student_key: str) -> dict | None: ...
```

- [ ] **Step 4: Implement on `SqliteRepository`** (delegates to `store.py`, which already has these — this branch wrote them in the earlier exam-robustness work; if `original/store.py` on this transplant branch is missing them because it came fresh from main, re-add them per Task 5 below FIRST, then this step)

```python
    def get_bluebook_submission_by_uuid(self, submission_uuid: str) -> dict | None:
        return store.get_bluebook_submission_by_uuid(submission_uuid)

    def get_or_create_bluebook_session(
        self, exam_id: str, student_key: str, tenant_id: str, duration_seconds: int
    ) -> dict:
        return store.get_or_create_bluebook_session(exam_id, student_key, tenant_id, duration_seconds)

    def get_bluebook_session(self, exam_id: str, student_key: str) -> dict | None:
        return store.get_bluebook_session(exam_id, student_key)
```

- [ ] **Step 5: Add `get_or_create_bluebook_session` to `_WRITE_METHODS`**

In `original/repository.py`, find the `_WRITE_METHODS = frozenset({...})` set and add `"get_or_create_bluebook_session",` to it (alongside the other `put_*`/`get_or_create` entries — it's a write since it can insert a row).

- [ ] **Step 6: Implement for real on `PostgresRepository`**

In `original/postgres_repository.py`: add `BluebookSession` to the `from .db.models.live import (...)` block (alphabetical, after `BluebookCourse`). Then, in the Bluebook section, directly after `list_bluebook_submissions`:

```python
    def get_bluebook_submission_by_uuid(self, submission_uuid):
        try:
            with session_scope() as session:
                stmt = select(BluebookSubmission).where(
                    BluebookSubmission.submission_uuid == submission_uuid
                )
                row = session.execute(stmt).scalar_one_or_none()
                return self._bluebook_sub_to_dict(row) if row else None
        except Exception:
            log.exception("get_bluebook_submission_by_uuid failed for %s", submission_uuid)
            return None

    @staticmethod
    def _bluebook_session_to_dict(row: BluebookSession, created: bool) -> dict:
        return {
            "exam_id": row.exam_id,
            "student_key": row.student_key,
            "tenant_id": row.tenant_id,
            "started_at": row.started_at.isoformat(),
            "deadline_at": row.deadline_at.isoformat(),
            "created": created,
        }

    def get_or_create_bluebook_session(self, exam_id, student_key, tenant_id, duration_seconds):
        from datetime import timedelta

        try:
            with session_scope() as session:
                self._ensure_tenant_exists(session, tenant_id)
                now = datetime.now(UTC)
                deadline = now + timedelta(seconds=int(duration_seconds))
                stmt = (
                    pg_insert(BluebookSession)
                    .values(
                        exam_id=exam_id,
                        student_key=student_key,
                        tenant_id=tenant_id,
                        started_at=now,
                        deadline_at=deadline,
                    )
                    .on_conflict_do_nothing(index_elements=["exam_id", "student_key"])
                )
                result = session.execute(stmt)
                created = result.rowcount == 1
                row = session.get(BluebookSession, (exam_id, student_key))
                return self._bluebook_session_to_dict(row, created)
        except Exception as e:
            log.error(
                "get_or_create_bluebook_session failed for %s/%s: %s", exam_id, student_key, e
            )
            raise

    def get_bluebook_session(self, exam_id, student_key):
        try:
            with session_scope() as session:
                row = session.get(BluebookSession, (exam_id, student_key))
                if row is None:
                    return None
                return {
                    "exam_id": row.exam_id,
                    "student_key": row.student_key,
                    "tenant_id": row.tenant_id,
                    "started_at": row.started_at.isoformat(),
                    "deadline_at": row.deadline_at.isoformat(),
                }
        except Exception:
            log.exception("get_bluebook_session failed for %s/%s", exam_id, student_key)
            return None
```

**Note on `session.get(Model, (pk1, pk2))` for composite primary keys:** this is the correct SQLAlchemy 1.4+/2.0 API (tuple form). Step 7 proves it works in this codebase's actual SQLAlchemy version — if it raises a `TypeError`, fall back to `session.execute(select(BluebookSession).where(BluebookSession.exam_id == exam_id, BluebookSession.student_key == student_key)).scalar_one_or_none()` instead, in both places this pattern is used above.

- [ ] **Step 7: Run the contract tests against BOTH backends**

Run: `DATABASE_URL="postgresql://postgres:postgres@localhost:5432/original_test" .venv/bin/python -m pytest "tests/test_repository_contract.py::TestBluebook::test_session_deadline_is_pinned" "tests/test_repository_contract.py::TestBluebook::test_submission_uuid_lookup" -v`
Expected: **4 passed** (both tests, both `[sqlite]` and `[postgres]` params). If `[postgres]` params still show as skipped, check `_postgres_available()` in the test file — it checks `DATABASE_URL.startswith("postgresql")` and attempts a real connection; confirm the env var is exported in the exact shell running pytest.

- [ ] **Step 8: Full contract suite on both backends, no regressions**

Run: `DATABASE_URL="postgresql://postgres:postgres@localhost:5432/original_test" .venv/bin/python -m pytest tests/test_repository_contract.py -v`
Expected: every test passes twice (once per backend) — 0 failed.

- [ ] **Step 9: Commit**

```bash
git add original/repository.py original/postgres_repository.py tests/test_repository_contract.py
git commit -m "Implement Bluebook-session Repository methods for real on PostgresRepository

Follows the put_bluebook_exam/get_bluebook_exam pattern (session_scope +
pg_insert...on_conflict + _to_dict helpers). Verified against a real
postgres:16 instance, not just the SQLite contract path.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Re-add the SQLite store layer (`original/store.py`) + its unit tests

**Files:**
- Modify: `original/store.py` (DDL for `bluebook_sessions`, `submission_uuid`/`late` columns on `bluebook_submissions`, 4 new/changed functions)
- Test: `tests/test_store_bluebook.py`

This is a straight re-application of prior work (SQLite side is unaffected by the Postgres convergence, so the content ports forward unchanged) — write it directly rather than TDD-round-tripping again, then verify.

- [ ] **Step 1: Add the DDL** — in the `bluebook_submissions` CREATE TABLE block, add `submission_uuid TEXT` and `late INTEGER DEFAULT 0` to the column list; directly after the table's index statement, add:

```python
    _sub_cols = {r[1] for r in conn.execute("PRAGMA table_info(bluebook_submissions)")}
    if "submission_uuid" not in _sub_cols:
        conn.execute("ALTER TABLE bluebook_submissions ADD COLUMN submission_uuid TEXT")
    if "late" not in _sub_cols:
        conn.execute("ALTER TABLE bluebook_submissions ADD COLUMN late INTEGER DEFAULT 0")
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_bluebook_subs_uuid
            ON bluebook_submissions(submission_uuid)
            WHERE submission_uuid IS NOT NULL
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bluebook_sessions (
            exam_id     TEXT NOT NULL,
            student_key TEXT NOT NULL,
            tenant_id   TEXT NOT NULL,
            started_at  TEXT NOT NULL,
            deadline_at TEXT NOT NULL,
            PRIMARY KEY (exam_id, student_key)
        )
    """)
```

- [ ] **Step 2: Update `put_bluebook_submission`'s INSERT** to include `submission_uuid, late` columns/values (`rec.get("submission_uuid")`, `rec.get("late", 0)`); update `list_bluebook_submissions`'s `cols` string to include `submission_uuid, late`; update `_bluebook_sub_to_dict` to map `row[13]`→`"submission_uuid"`, `row[14] or 0`→`"late"`.

- [ ] **Step 3: Add the 3 new functions** (`get_bluebook_submission_by_uuid`, `get_or_create_bluebook_session`, `get_bluebook_session`) — same implementations as documented in the earlier exam-robustness work (see this repo's git history at commit `228d77f` on the old branch for the exact prior code if a reference is needed, or re-derive from the DDL/dict-mapping pattern above).

- [ ] **Step 4: Re-add `tests/test_store_bluebook.py`'s new test classes** (`TestBluebookSessions`, `TestSubmissionUuid`) — same content as the old branch's commit `228d77f`.

- [ ] **Step 5: Run**

Run: `.venv/bin/python -m pytest tests/test_store_bluebook.py -q`
Expected: all passed, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add original/store.py tests/test_store_bluebook.py
git commit -m "Add bluebook_sessions store layer + submission_uuid/late columns

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Add `_BluebookSessionMigrator` to the SQLite→Postgres migration script

**Files:**
- Modify: `scripts/migrate_sqlite_to_pg.py`
- Test: whatever test file covers this script on main (check `tests/test_migration.py` first — it's main-only per the investigation, read it to find the exact per-table test pattern before writing a new one)

**Interfaces:**
- Consumes: the `_Migrator` base class / per-table subclass shape already established by the other 16 migrators in this file.
- Produces: `_BluebookSessionMigrator`, registered in `MIGRATORS`.

- [ ] **Step 1: Read the existing pattern**

Before writing anything: `grep -n "class _.*Migrator" scripts/migrate_sqlite_to_pg.py` and read ONE existing migrator closely (pick a simple one, e.g. whichever table has the fewest columns) to copy its exact shape — `name`, `model`, `pk`, `read_sqlite()`, `to_model()`, `read_pg()` methods.

- [ ] **Step 2: Write `_BluebookSessionMigrator`** following that exact shape, reading from SQLite's `bluebook_sessions` table (columns: `exam_id, student_key, tenant_id, started_at, deadline_at`) and writing to the `BluebookSession` model, with `pk = ("exam_id", "student_key")` (composite, matching whatever convention the existing migrators use for tables with non-single-column PKs — check if any other migrator already handles a composite PK and mirror it exactly; if none do, this is the first, so be extra careful about the checksum/parity logic honoring both key columns).

- [ ] **Step 3: Register it**

Add `_BluebookSessionMigrator(),` to the `MIGRATORS` list — placed AFTER the tenants migrator (FK dependency) but the exact position otherwise doesn't matter since nothing else depends on `bluebook_sessions`.

- [ ] **Step 4: Test against the real local Postgres**

Run whatever the discovered test file's invocation pattern is (e.g. `DATABASE_URL="postgresql://postgres:postgres@localhost:5432/original_test" .venv/bin/python -m pytest tests/test_migration.py -v`) plus, if the script supports a dry-run/single-table mode, exercise it directly against a small seeded SQLite fixture to confirm row-count + checksum parity for `bluebook_sessions` specifically.

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_sqlite_to_pg.py
git commit -m "Add bluebook_sessions to the SQLite->Postgres migration script

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Re-apply the Bluebook API endpoint + idempotent sealing + late tagging

**Files:**
- Modify: `original/schemas.py` (add `BluebookStartSessionRequest`, `BluebookSessionResponse`, `submission_uuid` field on `BluebookRecordSubmissionRequest`)
- Modify: `original/api.py` (new session endpoint, idempotency + late-tagging in `bluebook_record_submission`, seal-replay guard in `add_baseline`)
- Modify: `original/schemas.py`'s `AddSampleRequest` (add `submission_uuid` field)
- Test: `tests/test_bluebook_api.py`

Since main's `api.py`/`schemas.py` have no trace of this work, re-derive it fresh against main's CURRENT file content rather than attempting a mechanical diff-apply (main's surrounding code has shifted). Use the earlier design (`docs/superpowers/specs/2026-07-22-bluebook-exam-robustness-design.md`, §1–§2) as the source of truth for WHAT to build; write fresh code that fits main's current file shape.

- [ ] **Step 1: Read main's current `add_baseline`, `bluebook_record_submission`, `bluebook_get_exam`** in full first, to find the exact current insertion points (line numbers will have shifted from what any old branch commit recorded).

- [ ] **Step 2: Add the two schema classes + the `submission_uuid` fields** — same shapes as documented in the exam-robustness spec §1 (`BluebookStartSessionRequest`: `student_id: str = ""`, `candidate: str = ""`; `BluebookSessionResponse`: `exam_id`, `started_at`, `deadline_at`, `server_now`, `duration_seconds`), and `submission_uuid: str | None = None` on both `BluebookRecordSubmissionRequest` and `AddSampleRequest`.

- [ ] **Step 3: Add the session endpoint** directly after `bluebook_get_exam`, matching main's current staff/tenant helper names (`_bluebook_tenant`, `_int_or` — confirm these still exist unchanged on main before assuming the signature):

```python
@app.post("/bluebook/exams/{exam_id}/session", response_model=BluebookSessionResponse)
def bluebook_start_session(exam_id: str, body: BluebookStartSessionRequest, request: Request):
    """Begin (or resume) a sitting: the first call pins the server deadline;
    every later call returns the same one, so reopening the tab never
    restarts or pauses the clock."""
    tenant = _bluebook_tenant(request)
    exam = _repo().get_bluebook_exam(exam_id)
    if exam is None or exam.get("tenant_id") not in (tenant, None):
        raise HTTPException(status_code=404, detail="exam not found")
    duration_seconds = max(60, _int_or(exam.get("duration"), 90) * 60)
    student_key = (body.student_id or (body.candidate and f"cand:{body.candidate}") or "")[:128]
    if not student_key.strip():
        raise HTTPException(status_code=422, detail="student_id or candidate is required")
    s = _repo().get_or_create_bluebook_session(exam_id, student_key, tenant, duration_seconds)
    return BluebookSessionResponse(
        exam_id=exam_id,
        started_at=s["started_at"],
        deadline_at=s["deadline_at"],
        server_now=datetime.now(UTC).isoformat(),
        duration_seconds=duration_seconds,
    )
```

(Confirm `datetime`/`UTC`/`timedelta` are imported at module level on main's current `api.py` — add the import if missing.)

- [ ] **Step 4: Add idempotency + late tagging to `bluebook_record_submission`** — at the top of the handler:

```python
    if body.submission_uuid:
        prior = _repo().get_bluebook_submission_by_uuid(body.submission_uuid[:64])
        if prior is not None:
            return {"id": prior["id"], "status": prior["status"],
                    "late": prior.get("late", 0), "duplicate": True}
```

Before the final `put_bluebook_submission` call, add `submission_uuid`/`late` to `rec` and compute lateness via `_repo().get_bluebook_session(...)`, wrapping the write in try/except `sqlite3.IntegrityError` (or, if main's Postgres path is what's active, the equivalent SQLAlchemy `IntegrityError` — check what exception `put_bluebook_submission` actually surfaces on constraint violation for whichever backend is active, and catch appropriately) to handle a racing replay. Change the final return to include `"late": rec["late"]`.

- [ ] **Step 5: Add the seal-replay guard to `add_baseline`** — after `state = _repo().get_or_create(student_id)`:

```python
    if req.submission_uuid:
        import hashlib

        text_hash = hashlib.sha256(req.text.encode()).hexdigest()
        if text_hash in _existing_text_hashes(student_id):
            return {"skipped": True, "reason": "duplicate_text",
                    "student_id": student_id, "sample_index": state.sample_count - 1,
                    "provenance": req.provenance, "authenticated_count": state.authenticated_count,
                    "purity": state.purity}
```

**Check first whether `_existing_text_hashes` still exists on main's `api.py`** (it was a Canvas-import helper this branch preserved standalone during an earlier merge) — if main's P6 v1-deletion removed it (unlikely, since it's Canvas-import-adjacent but not itself v1, but verify), re-add it as a standalone function per the earlier merge commit's reasoning (SHA-256 hash every baseline sample's text for dedup).

- [ ] **Step 6: Re-add `tests/test_bluebook_api.py`'s new test functions** (`test_session_pins_deadline`, `test_session_unknown_exam_404`, `test_session_requires_some_identity`, `test_seal_replay_returns_prior_result`, `test_no_session_means_not_late`, `test_late_after_deadline_grace`, `test_baseline_seal_replay_adds_exactly_one_sample`, `test_baseline_without_uuid_keeps_todays_behavior`) — same content as before, adjusted for whatever fixture/helper names main's current copy of this test file uses (check `_exam_body`/`_submission_body`/`client`/`api_mod` fixtures still match).

- [ ] **Step 7: Run**

Run: `.venv/bin/python -m pytest tests/test_bluebook_api.py -q`
Expected: all passed, 0 failed.

- [ ] **Step 8: Commit**

```bash
git add original/api.py original/schemas.py tests/test_bluebook_api.py
git commit -m "Add exam-session endpoint, idempotent seal replay, and late tagging

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: Fix the now-false PostgresRepository skeleton assertion

**Files:**
- Modify: `tests/test_baseline_requests.py`

**Interfaces:** none — test-only.

- [ ] **Step 1: Read main's current version of this test file's `TestRepositorySeamWidened` (or equivalent) class** — main already rewrote the analogous "is PostgresRepository a skeleton" assertion to reflect reality (per the investigation). Since this branch is building FROM main now (Task 1's fresh branch), this file is already main's correct version by construction — **no action needed** UNLESS this branch's later commits (Tasks 2-7) somehow re-introduce a stale assertion. Grep to confirm:

```bash
grep -n "skeleton\|_todo\|NotImplementedError" tests/test_baseline_requests.py
```

Expected: no hits describing PostgresRepository as incomplete (main's version should already say something like "implements every method except db_path()"). If a stale assertion is somehow present, correct it to match main's actual `PostgresRepository` state (70 real methods, only `db_path()` still `_todo`).

- [ ] **Step 2: Run**

Run: `.venv/bin/python -m pytest tests/test_baseline_requests.py -q`
Expected: all passed.

- [ ] **Step 3: Commit only if Step 1 required a change** (otherwise skip — nothing to commit).

---

### Task 9: Re-apply the Bluebook frontend robustness work

**Files:**
- Modify: `demo/bluebook/Exam.jsx`
- Rebuild: `demo/bluebook/bluebook.bundle.js` + `.map`
- Create: `demo/bluebook/e2e/exam-robustness.spec.mjs`

This is backend-independent (WS-6 P3–P6 never touched Bluebook's frontend), so port forward unchanged — same content as the prior branch's commits `f1bd893` (Exam.jsx) and `4fd1da8` (e2e spec).

- [ ] **Step 1: Confirm main's `Exam.jsx` doesn't already have any of this** (it shouldn't — P3-P6 is backend-only):

```bash
grep -n "bbStartSession\|deadlineRef\|sealRef" demo/bluebook/Exam.jsx
```

Expected: no hits.

- [ ] **Step 2: Re-apply the full `Exam.jsx` changes** — `bbStartSession` helper, `deadlineRef`/`sealRef`/`offline` state, the deadline-driven countdown effect replacing the plain interval, the full `handleSubmit` rewrite (uuid + retry loop + offline park + draft-preserved-on-failure), the offline banner JSX, `role="timer"` on the clock span. Same content as documented in the exam-robustness design spec §1–§4 and this repo's prior commit `f1bd893`.

- [ ] **Step 3: Rebuild the bundle**

```bash
cd demo/bluebook && npm run build
```

- [ ] **Step 4: Re-add `exam-robustness.spec.mjs`** — same content as prior commit `4fd1da8`.

- [ ] **Step 5: Verify against a live server**

Boot a scratch pilot-mode server (see Task 11 for the exact invocation) and run:

```bash
cd demo/bluebook && npx playwright test e2e/exam-robustness.spec.mjs
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add demo/bluebook/Exam.jsx demo/bluebook/bluebook.bundle.js demo/bluebook/bluebook.bundle.js.map demo/bluebook/e2e/exam-robustness.spec.mjs
git commit -m "Add Bluebook exam-day robustness: server deadline, retryable seal, offline banner

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 10: Tighten the exam-flow provenance assertion (do NOT port the loosened version)

**Files:**
- Modify: `demo/bluebook/e2e/exam-flow.spec.mjs`

**Rationale:** main already has the real proctor-attestation fix (`mintProctorAttestation` + storing it in `bootInExam`) — the earlier branch's loosened assertion (`['proctored', 'unverified'].includes(...)`) was a workaround for a temporary state that no longer exists post-transplant. Leave this file as main's, but VERIFY the assertion is the strict one.

- [ ] **Step 1: Confirm**

```bash
grep -n "provenance ===" demo/bluebook/e2e/exam-flow.spec.mjs
```

Expected: `expect(student.samples.some(s => s.provenance === 'proctored')).toBe(true)` (strict, no `.includes`). If main's copy somehow has the loose version, tighten it back to strict — this branch should not carry a masked assertion forward.

- [ ] **Step 2: Run against a live server** (same server as Task 9 Step 5):

```bash
cd demo/bluebook && npx playwright test e2e/exam-flow.spec.mjs
```

Expected: all passed, including the round-trip test with the strict `'proctored'` assertion.

- [ ] **Step 3: No commit needed if Step 1 required no change.**

---

### Task 11: Re-add the corrections-UI design spec (pure doc, no code dependency)

**Files:**
- Create: `docs/superpowers/specs/2026-07-22-bluebook-corrections-ui-design.md`
- Create: `docs/superpowers/specs/2026-07-22-bluebook-exam-robustness-design.md`
- Create: `docs/superpowers/plans/2026-07-16-code-review-fixes.md`, `docs/superpowers/plans/2026-07-22-bluebook-exam-robustness.md` (historical plan docs — port forward as records of prior work, add a one-line addendum noting the PostgresRepository-stub instruction in the exam-robustness plan is superseded now that P3 shipped for real on main)

**Interfaces:** none — documentation only, no code dependency, no conflict risk.

- [ ] **Step 1: Copy each file forward verbatim** from the old branch (`docs/section9-implementation-plans`, pre-transplant) via `git show docs/section9-implementation-plans:<path>` piped to `Write`.

- [ ] **Step 2: Add the superseded-instruction addendum** to `docs/superpowers/plans/2026-07-22-bluebook-exam-robustness.md`, Task 2, right after the plan's `PostgresRepository` stub instruction:

```markdown
> **Superseded 2026-07-22:** by the time this plan's work was reconciled onto
> `main`, WS-6 P3 had shipped a full `PostgresRepository` implementation (no
> more `_todo` stubs anywhere except `db_path()`). The 3 methods below were
> implemented for real, not stubbed — see
> `docs/superpowers/plans/2026-07-22-rebase-onto-main-ws6-p3-p6.md` Task 4.
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/
git commit -m "Re-add sub-project design docs from the pre-transplant branch

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 12: Adopt main's WS-6/README docs, refresh test-count numbers

**Files:**
- `docs/implementation/WS-6-postgres-convergence.md`, `docs/implementation/README.md` — already main's current version by construction (fresh branch from main); no action unless a later task's commit touched them (it shouldn't have).
- `CLAUDE.md`, `README.md` (repo root) — test-count/coverage numbers need a fresh truth-pass given the new totals from Tasks 2-9's additions.

- [ ] **Step 1: Measure current real numbers**

```bash
.venv/bin/python -m pytest tests/ --collect-only -q | tail -1
.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py --collect-only -q | tail -1
DATABASE_URL="postgresql://postgres:postgres@localhost:5432/original_test" \
  .venv/bin/python -m pytest tests/ validation/test_tier10_optional.py --cov=original --cov-report=term-missing -q 2>&1 | tail -5
```

- [ ] **Step 2: Update `CLAUDE.md`/`README.md`'s test-count line** with the measured numbers and today's date, same pattern as the earlier docs/CI truth pass in this repo's history.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "Refresh test-count numbers post-transplant

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 13: Final verification — both backends, full e2e

**Files:** none — verification only.

- [ ] **Step 1: Full suite, SQLite (default)**

Run: `unset DATABASE_URL; .venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q`
Expected: 0 failed.

- [ ] **Step 2: Full suite, Postgres**

Run: `DATABASE_URL="postgresql://postgres:postgres@localhost:5432/original_test" .venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q`
Expected: 0 failed, and this time the `[postgres]`-parametrized contract tests actually RUN (not skip) — confirm by checking the test count is higher than the SQLite-only run, or grep the output for `postgres]` PASSED lines.

- [ ] **Step 3: Full e2e Playwright suite**

Boot a scratch pilot-mode server:

```bash
ORIGINAL_ENV=pilot SECRET_KEY=ci-test-only-secret-do-not-deploy MAINTENANCE_TOKEN=ci-test-only \
  LOGIN_THROTTLE_MAX_ATTEMPTS=500 ORIGINAL_DB=/tmp/transplant-verify.db \
  .venv/bin/python run.py --demo --frontend-dir demo --port 8021 --skip-seed &
# wait for /health, then:
cd demo/bluebook && PLAYWRIGHT_BASE_URL=http://localhost:8021 npx playwright test --grep-invert "@serial-lockout"
# stop the server you started when done
```

Expected: 0 failed.

- [ ] **Step 4: `app/` workspace (WS-8 components — should be untouched, just confirm)**

Run: `cd app && npm test && npm run lint && npm run typecheck`
Expected: all clean.

- [ ] **Step 5: Report the full picture to the user** before proceeding to Task 14 — summarize what changed, confirm both-backend green, and explicitly flag that Task 14 is a force-push and needs a final go-ahead.

---

### Task 14: Push (explicit checkpoint — do not run unattended)

**Files:** none — git operations only.

- [ ] **Step 1: Re-fetch immediately before pushing** to check for new work from the parallel session:

```bash
git fetch origin docs/section9-implementation-plans
git log --oneline origin/docs/section9-implementation-plans -5
```

If this shows commits newer than the ones already reconciled in this plan's Task 1 baseline, STOP and report to the user — do not silently re-reconcile or overwrite.

- [ ] **Step 2: Confirm with the user, then force-push**

This step force-pushes a rewritten history to `origin/docs/section9-implementation-plans`, which will update PR #79. **Get explicit confirmation before running** (per this repo's standing safety rules on force-push):

```bash
git push --force-with-lease origin docs/section9-implementation-plans-transplant:docs/section9-implementation-plans
```

(`--force-with-lease`, not bare `--force` — it aborts instead of overwriting if Step 1's re-fetch was stale by the time this runs.)

- [ ] **Step 3: Verify the PR**

```bash
gh pr view 79 --json mergeable,state
```

Expected: `mergeable: MERGEABLE` (or `UNKNOWN` transiently — re-check after a few seconds), `state: OPEN`.

- [ ] **Step 4: Clean up the safety ref from Task 1** once the user confirms the pushed result looks right:

```bash
git branch -D transplant-backup-<date-from-task-1>
```
