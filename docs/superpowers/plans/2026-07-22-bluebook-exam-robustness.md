# Bluebook Exam-Day Robustness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin exam deadlines server-side, make sealing idempotent and retryable, add offline awareness, and finish the exam page's a11y — per the approved spec `docs/superpowers/specs/2026-07-22-bluebook-exam-robustness-design.md`.

**Architecture:** Hybrid (user-selected): a new `bluebook_sessions` table + one endpoint issue an immutable per-student deadline; drafts stay in localStorage; the client seal flow gains a `submission_uuid`, per-step completion flags, and a bounded retry loop that parks while offline. Server dedupes replays on both write endpoints.

**Tech Stack:** FastAPI + SQLite (`original/store.py` → `Repository` seam), SQLAlchemy `models/live.py` + alembic (schema-of-record), React JSX via esbuild (`demo/bluebook/`, committed bundle), pytest + Playwright.

## Global Constraints

- Work in `/Users/andrew/Desktop/Original`, branch `docs/section9-implementation-plans`. Python: `.venv/bin/python` only.
- Full suite must stay **0 failed** (`.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q`).
- After any `demo/bluebook/*.jsx` change: `cd demo/bluebook && npm run build` and **commit the bundle** (Render has no Node).
- Schema changes land in BOTH `original/store.py` DDL (live SQLite path) and `original/db/models/live.py` + a new alembic revision on top of `20128da16c79` (schema of record).
- Never reject/destroy student work server-side; degrade open on the client.
- Commit style: `Add ...`/`Fix ...` + `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`. Pre-commit hooks must pass unmodified (no `--no-verify`).
- Timestamps are UTC ISO-8601 strings (`datetime.now(UTC).isoformat()`), matching the rest of `store.py`.

---

### Task 1: Store layer — `bluebook_sessions` + `submission_uuid`/`late` columns

**Files:**
- Modify: `original/store.py` (DDL block ~line 300 after `bluebook_courses`; new functions after `list_bluebook_submissions`)
- Test: `tests/test_store_bluebook.py` (append new test classes)

**Interfaces:**
- Produces: `store.get_or_create_bluebook_session(exam_id: str, student_key: str, tenant_id: str, duration_seconds: int) -> dict` returning `{"exam_id", "student_key", "tenant_id", "started_at", "deadline_at", "created": bool}` — same row on every call after the first.
- Produces: `store.get_bluebook_submission_by_uuid(submission_uuid: str) -> dict | None` (same dict shape as `list_bluebook_submissions` rows, plus `submission_uuid` and `late`).
- Produces: `put_bluebook_submission(rec)` now also persists `rec.get("submission_uuid")` and `rec.get("late", 0)`.

- [ ] **Step 1: Write failing tests** — append to `tests/test_store_bluebook.py` (follow the file's existing fixture pattern for a tmp DB; if it uses a `fresh_store` fixture, reuse it):

```python
class TestBluebookSessions:
    def test_first_call_creates_session(self, fresh_store):
        s = store.get_or_create_bluebook_session("ex1", "sem:alice", "sem", 3600)
        assert s["created"] is True
        assert s["exam_id"] == "ex1" and s["tenant_id"] == "sem"
        started = datetime.fromisoformat(s["started_at"])
        deadline = datetime.fromisoformat(s["deadline_at"])
        assert (deadline - started).total_seconds() == 3600

    def test_second_call_returns_same_deadline(self, fresh_store):
        first = store.get_or_create_bluebook_session("ex1", "sem:alice", "sem", 3600)
        again = store.get_or_create_bluebook_session("ex1", "sem:alice", "sem", 3600)
        assert again["created"] is False
        assert again["deadline_at"] == first["deadline_at"]
        assert again["started_at"] == first["started_at"]

    def test_sessions_are_per_student_and_exam(self, fresh_store):
        a = store.get_or_create_bluebook_session("ex1", "sem:alice", "sem", 3600)
        b = store.get_or_create_bluebook_session("ex1", "sem:bob", "sem", 3600)
        c = store.get_or_create_bluebook_session("ex2", "sem:alice", "sem", 3600)
        assert a is not None and b["created"] and c["created"]


class TestSubmissionUuid:
    def _rec(self, uuid_val):
        return {
            "id": "sub-" + uuid_val, "exam_id": "ex1", "tenant_id": "sem",
            "student_id": "sem:alice", "candidate": "Alice", "exam_title": "T",
            "course": "C", "word_count": 10, "time_min": 5, "stylometric": 90,
            "ai_score": None, "status": "SUBMITTED",
            "submission_uuid": uuid_val, "late": 0,
        }

    def test_uuid_roundtrip(self, fresh_store):
        store.put_bluebook_submission(self._rec("u-1"))
        got = store.get_bluebook_submission_by_uuid("u-1")
        assert got is not None and got["submission_id"] == "sub-u-1"
        assert got["late"] == 0

    def test_unknown_uuid_returns_none(self, fresh_store):
        assert store.get_bluebook_submission_by_uuid("nope") is None

    def test_duplicate_uuid_insert_raises(self, fresh_store):
        store.put_bluebook_submission(self._rec("u-2"))
        with pytest.raises(sqlite3.IntegrityError):
            store.put_bluebook_submission(self._rec("u-2") | {"id": "other"})
```

Add needed imports at top if missing: `import sqlite3`, `import pytest`, `from datetime import datetime`.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_store_bluebook.py -q -k "Sessions or Uuid"`
Expected: FAIL / ERROR — `AttributeError: module 'original.store' has no attribute 'get_or_create_bluebook_session'`.

- [ ] **Step 3: Implement.** In `original/store.py`:

(a) In the DDL block, directly after the `bluebook_courses` index statement:

```python
        conn.execute("""
        CREATE TABLE IF NOT EXISTS bluebook_sessions (
            exam_id     TEXT NOT NULL,
            student_key TEXT NOT NULL,
            tenant_id   TEXT NOT NULL,
            started_at  TEXT NOT NULL,
            deadline_at TEXT NOT NULL,
            PRIMARY KEY (exam_id, student_key)
        )""")
```

(b) Immediately after the `bluebook_submissions` CREATE + index, add a guarded column upgrade (SQLite `ADD COLUMN` can't add UNIQUE, so a partial unique index enforces dedup):

```python
        # In-place upgrade for pre-existing DBs (no migration ladder yet —
        # PRAGMA-guarded ALTERs, same pattern the fresh CREATE keeps in sync).
        _cols = {r[1] for r in conn.execute("PRAGMA table_info(bluebook_submissions)")}
        if "submission_uuid" not in _cols:
            conn.execute("ALTER TABLE bluebook_submissions ADD COLUMN submission_uuid TEXT")
        if "late" not in _cols:
            conn.execute("ALTER TABLE bluebook_submissions ADD COLUMN late INTEGER DEFAULT 0")
        conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_bluebook_subs_uuid
            ON bluebook_submissions(submission_uuid)
            WHERE submission_uuid IS NOT NULL
        """)
```

Also add `submission_uuid TEXT` and `late INTEGER DEFAULT 0` lines to the fresh `CREATE TABLE IF NOT EXISTS bluebook_submissions` column list so new DBs match.

(c) Extend `put_bluebook_submission`'s INSERT with the two columns/values (`rec.get("submission_uuid")`, `rec.get("late", 0)`); extend the `cols` string in `list_bluebook_submissions` (and the row→dict mapping if explicit) with `submission_uuid, late`.

(d) New functions after `list_bluebook_submissions`:

```python
def get_bluebook_submission_by_uuid(submission_uuid: str) -> dict | None:
    cols = (
        "submission_id, exam_id, tenant_id, student_id, candidate, exam_title, "
        "course, word_count, time_min, stylometric, ai_score, status, created_at, "
        "submission_uuid, late"
    )
    try:
        with _get_conn() as conn:
            row = conn.execute(
                f"SELECT {cols} FROM bluebook_submissions WHERE submission_uuid = ?",
                (submission_uuid,),
            ).fetchone()
        if row is None:
            return None
        return dict(zip(cols.replace(" ", "").split(","), row))
    except sqlite3.Error:
        log.exception("get_bluebook_submission_by_uuid failed for %s", submission_uuid)
        raise


def get_or_create_bluebook_session(
    exam_id: str, student_key: str, tenant_id: str, duration_seconds: int
) -> dict:
    """Idempotent per-(exam, student) session: the first call pins started_at/
    deadline_at; every later call returns the same row unchanged, so reopening
    the exam can never restart or pause the clock."""
    now = datetime.now(UTC)
    started_at = now.isoformat()
    deadline_at = (now + timedelta(seconds=int(duration_seconds))).isoformat()
    try:
        with _get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO bluebook_sessions
                     (exam_id, student_key, tenant_id, started_at, deadline_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(exam_id, student_key) DO NOTHING""",
                (exam_id, student_key, tenant_id, started_at, deadline_at),
            )
            created = cur.rowcount == 1
            conn.commit()
            row = conn.execute(
                "SELECT exam_id, student_key, tenant_id, started_at, deadline_at "
                "FROM bluebook_sessions WHERE exam_id = ? AND student_key = ?",
                (exam_id, student_key),
            ).fetchone()
        return {
            "exam_id": row[0], "student_key": row[1], "tenant_id": row[2],
            "started_at": row[3], "deadline_at": row[4], "created": created,
        }
    except sqlite3.Error as e:
        log.error("get_or_create_bluebook_session failed for %s/%s: %s", exam_id, student_key, e)
        raise
```

Ensure `from datetime import timedelta` is imported (check the existing datetime import line and extend it).

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_store_bluebook.py -q`
Expected: all PASS (existing + new).

- [ ] **Step 5: Commit** — `git add original/store.py tests/test_store_bluebook.py && git commit -m "Add bluebook_sessions store layer + submission_uuid/late columns ..."` (with co-author line).

---

### Task 2: Repository seam + schema-of-record (live.py model + alembic revision)

> **Superseded 2026-07-22:** by the time this plan's work was reconciled onto
> `main`, WS-6 P3 had shipped a full `PostgresRepository` implementation (no
> more `_todo` stubs anywhere except `db_path()`). The 3 methods below were
> implemented for real, not stubbed — see
> `docs/superpowers/plans/2026-07-22-rebase-onto-main-ws6-p3-p6.md` Task 4.

**Files:**
- Modify: `original/repository.py` (Protocol Bluebook section, `SqliteRepository`, `PostgresRepository` stubs)
- Modify: `original/db/models/live.py` (new `BluebookSession` model; `submission_uuid`/`late` on `BluebookSubmission`; `LIVE_MODELS` append)
- Create: `alembic/versions/<generated>_bluebook_sessions.py`
- Test: `tests/test_repository_contract.py` (TestBluebook section or new `TestBluebookSessions`), `tests/test_db_models.py`

**Interfaces:**
- Produces: `Repository.get_or_create_bluebook_session(exam_id: str, student_key: str, tenant_id: str, duration_seconds: int) -> dict` and `Repository.get_bluebook_submission_by_uuid(submission_uuid: str) -> dict | None` — thin delegates on `SqliteRepository`, `self._todo(...)` on `PostgresRepository` (exact pattern of `submission_student_id`, added 2026-07-17).

- [ ] **Step 1: Failing contract tests** — in `tests/test_repository_contract.py`, next to the existing Bluebook tests:

```python
class TestBluebookSessions:
    def test_session_deadline_is_pinned(self, repo):
        first = repo.get_or_create_bluebook_session("ex-c1", "sem:al", "sem", 1800)
        again = repo.get_or_create_bluebook_session("ex-c1", "sem:al", "sem", 1800)
        assert first["created"] and not again["created"]
        assert again["deadline_at"] == first["deadline_at"]

    def test_submission_uuid_lookup(self, repo):
        repo.put_bluebook_submission({
            "id": "s1", "exam_id": "ex-c1", "tenant_id": "sem",
            "student_id": "sem:al", "submission_uuid": "uu-1", "late": 1,
        })
        got = repo.get_bluebook_submission_by_uuid("uu-1")
        assert got["submission_id"] == "s1" and got["late"] == 1
        assert repo.get_bluebook_submission_by_uuid("uu-none") is None
```

- [ ] **Step 2: Verify failure** — `.venv/bin/python -m pytest "tests/test_repository_contract.py::TestBluebookSessions" -q` → AttributeError on `SqliteRepository`.

- [ ] **Step 3: Implement seam.** In `original/repository.py`, Bluebook section of the Protocol:

```python
    def get_or_create_bluebook_session(
        self, exam_id: str, student_key: str, tenant_id: str, duration_seconds: int
    ) -> dict: ...
    def get_bluebook_submission_by_uuid(self, submission_uuid: str) -> dict | None: ...
```

`SqliteRepository` (delegates) and `PostgresRepository` (`self._todo("get_or_create_bluebook_session")` / `self._todo("get_bluebook_submission_by_uuid")`), placed in each class's Bluebook section.

- [ ] **Step 4: live.py + migration.** In `original/db/models/live.py`, following the file's exact style (look at `BluebookSubmission` for column idioms):

```python
class BluebookSession(LiveBase):
    """Per-(exam, student) sitting: pins the immutable server deadline."""

    __tablename__ = "bluebook_sessions"

    exam_id: Mapped[str] = mapped_column(Text, primary_key=True)
    student_key: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[str] = mapped_column(Text, nullable=False)
    deadline_at: Mapped[str] = mapped_column(Text, nullable=False)
```

(Timestamps as Text mirror the store's ISO strings — same reasoning `SubmissionManifest.created_at` documents.) Add `submission_uuid: Mapped[str | None]` (Text, nullable, unique) and `late: Mapped[int]` (server_default `text("0")`) to `BluebookSubmission`. Append `BluebookSession` to `LIVE_MODELS` and update its "16 live models" comment to 17.

New alembic revision (hand-written, `down_revision = "20128da16c79"`): `op.create_table("bluebook_sessions", ...)` matching the model, `op.add_column("bluebook_submissions", sa.Column("submission_uuid", sa.Text(), nullable=True))`, `op.add_column(... "late", sa.Integer(), server_default="0")`, `op.create_index(... unique=True, postgresql_where=sa.text("submission_uuid IS NOT NULL"), sqlite_where=...)`; symmetric `downgrade()`.

- [ ] **Step 5: Extend `tests/test_db_models.py`** with `BluebookSession` presence (follow the file's existing pattern — likely metadata/table-name assertions; mirror one existing case).

- [ ] **Step 6: Run** — `.venv/bin/python -m pytest tests/test_repository_contract.py tests/test_db_models.py tests/test_baseline_requests.py -q` → 0 failed. (`test_baseline_requests` guards the PG-skeleton invariant — the new `_todo` stubs keep it true.)

- [ ] **Step 7: Commit.**

---

### Task 3: API — session endpoint, idempotent recordSubmission, late tagging

**Files:**
- Modify: `original/schemas.py` (new request/response models; extend `BluebookRecordSubmissionRequest`)
- Modify: `original/api.py` (new endpoint after `bluebook_get_exam`; extend `bluebook_record_submission`)
- Test: `tests/test_bluebook_api.py`

**Interfaces:**
- Consumes: Task 1/2 seam methods.
- Produces: `POST /bluebook/exams/{exam_id}/session` → `{"exam_id", "started_at", "deadline_at", "server_now", "duration_seconds"}`; 404 for unknown exam.
- Produces: `POST /bluebook/submissions` accepting `submission_uuid: str | None`; replay returns the prior `{"id", "status", "late"}` + `"duplicate": true`; fresh inserts include `"late"` computed from the session (grace 300s; no session row → `late: 0`).

- [ ] **Step 1: Failing API tests** — append to `tests/test_bluebook_api.py` (reuse its client/tenant fixtures exactly as the existing exam-create tests do):

```python
class TestExamSessions:
    def test_session_pins_deadline(self, client):
        exam = client.post("/bluebook/exams", json={"title": "T", "duration": 30}).json()
        r1 = client.post(f"/bluebook/exams/{exam['id']}/session",
                         json={"student_id": "demo:al", "candidate": ""})
        assert r1.status_code == 200
        b1 = r1.json()
        assert b1["duration_seconds"] == 1800
        r2 = client.post(f"/bluebook/exams/{exam['id']}/session",
                         json={"student_id": "demo:al", "candidate": ""})
        assert r2.json()["deadline_at"] == b1["deadline_at"]

    def test_session_unknown_exam_404(self, client):
        r = client.post("/bluebook/exams/nope/session", json={"student_id": "x", "candidate": ""})
        assert r.status_code == 404


class TestSealIdempotency:
    def _payload(self, uuid_val, exam_id=None):
        return {"exam_id": exam_id, "student_id": "demo:al", "candidate": "Al",
                "exam_title": "T", "course": "C", "word_count": 5, "time_min": 1,
                "stylometric": 80, "ai_score": None, "status": "SUBMITTED",
                "submission_uuid": uuid_val}

    def test_replay_returns_prior_result(self, client):
        r1 = client.post("/bluebook/submissions", json=self._payload("uu-x")).json()
        r2 = client.post("/bluebook/submissions", json=self._payload("uu-x")).json()
        assert r2["id"] == r1["id"] and r2.get("duplicate") is True
        subs = client.get("/bluebook/submissions").json()["submissions"]
        assert sum(1 for s in subs if s.get("submission_uuid") == "uu-x") == 1

    def test_no_session_means_not_late(self, client):
        r = client.post("/bluebook/submissions", json=self._payload("uu-y")).json()
        assert r["late"] == 0

    def test_late_after_deadline_grace(self, client, monkeypatch):
        exam = client.post("/bluebook/exams", json={"title": "T", "duration": 30}).json()
        client.post(f"/bluebook/exams/{exam['id']}/session",
                    json={"student_id": "demo:al", "candidate": ""})
        import original.api as api_mod
        real_now = api_mod.datetime.now
        # Pretend it's 40 minutes later (past 30min + 5min grace).
        class _Later:
            @staticmethod
            def now(tz=None):
                from datetime import timedelta
                return real_now(tz) + timedelta(minutes=40)
        monkeypatch.setattr(api_mod, "datetime", _Later)
        r = client.post("/bluebook/submissions",
                        json=self._payload("uu-z", exam_id=exam["id"])).json()
        assert r["late"] == 1
```

(If `api.py` imports `datetime` differently, adapt the monkeypatch target to what `grep -n "^from datetime\|^import datetime" original/api.py` shows — patch the symbol the handler actually calls.)

- [ ] **Step 2: Verify failure** — `.venv/bin/python -m pytest tests/test_bluebook_api.py -q -k "Session or Idempo"` → 404-route-missing / KeyError failures.

- [ ] **Step 3: Schemas.** In `original/schemas.py` next to the other Bluebook models:

```python
class BluebookStartSessionRequest(BaseModel):
    """POST /bluebook/exams/{exam_id}/session — begin (or resume) a sitting."""

    student_id: str = Field("", description="Resolved Original student id, when known")
    candidate: str = Field("", description="Candidate email/label fallback for demo sittings")


class BluebookSessionResponse(BaseModel):
    exam_id: str
    started_at: str
    deadline_at: str
    server_now: str
    duration_seconds: int
```

Add to `BluebookRecordSubmissionRequest`:

```python
    submission_uuid: str | None = Field(
        None, description="Client seal id; replays return the prior result instead of re-writing"
    )
```

- [ ] **Step 4: Endpoint** (in `original/api.py`, after `bluebook_get_exam`; same section conventions):

```python
@app.post("/bluebook/exams/{exam_id}/session", response_model=BluebookSessionResponse)
def bluebook_start_session(exam_id: str, body: BluebookStartSessionRequest, request: Request):
    """Begin (or resume) a sitting: the first call pins the server deadline;
    every later call returns the same one, so reopening the tab never
    restarts or pauses the clock."""
    tenant = _bluebook_tenant(request)
    exam = _repo().get_bluebook_exam(exam_id)
    if exam is None or (exam.get("tenant_id") not in (tenant, None)):
        raise HTTPException(status_code=404, detail="exam not found")
    duration_seconds = max(60, _int_or(exam.get("duration"), 90) * 60)
    student_key = (body.student_id or f"cand:{body.candidate}")[:128]
    if not student_key.strip() or student_key == "cand:":
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

- [ ] **Step 5: recordSubmission idempotency + late.** At the top of `bluebook_record_submission`, before building `rec`:

```python
    if body.submission_uuid:
        prior = _repo().get_bluebook_submission_by_uuid(body.submission_uuid[:64])
        if prior is not None:
            return {"id": prior["submission_id"], "status": prior["status"],
                    "late": prior.get("late", 0), "duplicate": True}
```

After building `rec` (before `put_bluebook_submission`):

```python
    rec["submission_uuid"] = (body.submission_uuid or None) and body.submission_uuid[:64]
    rec["late"] = 0
    if rec["exam_id"]:
        student_key = (body.student_id or f"cand:{body.candidate}")[:128]
        sess = None
        try:
            sess = _repo().get_bluebook_session(rec["exam_id"], student_key)
        except AttributeError:
            sess = None
        # No session row (degrade-open start) → no late judgment possible.
        if sess:
            deadline = datetime.fromisoformat(sess["deadline_at"])
            if datetime.now(UTC) > deadline + timedelta(seconds=300):
                rec["late"] = 1
```

This needs a read-only `get_bluebook_session(exam_id, student_key) -> dict | None` — add it in this task to `store.py` (simple SELECT of the same row), the Protocol, `SqliteRepository`, and a `PostgresRepository` `_todo` stub. Return dict shape identical to `get_or_create_bluebook_session` minus `created`. Change the endpoint's final return to `{"id": rec["id"], "status": rec["status"], "late": rec["late"]}`. Guard against `sqlite3.IntegrityError` on the uuid unique index (two racing replays): catch it, re-fetch by uuid, return with `"duplicate": True`.

- [ ] **Step 6: Run** — `.venv/bin/python -m pytest tests/test_bluebook_api.py tests/test_repository_contract.py -q` → 0 failed. (Contract suite gets `get_bluebook_session` coverage: add one line asserting the read-only lookup returns the created row and `None` when absent.)

- [ ] **Step 7: Commit.**

---

### Task 4: Baseline replay guard

**Files:**
- Modify: `original/schemas.py` (`AddSampleRequest`), `original/api.py:add_baseline` (~line 1673)
- Test: `tests/test_bluebook_api.py` or `tests/context/test_admin_endpoints.py` — wherever `add_baseline` already has coverage; follow that file.

**Interfaces:**
- Produces: `AddSampleRequest.submission_uuid: str | None` — when present, `add_baseline` skips ingestion if an identical text (sha256) already exists in the profile, returning `{"skipped": true, "reason": "duplicate_text", "sample_count": <unchanged>}`.

- [ ] **Step 1: Failing test:**

```python
def test_baseline_seal_replay_adds_exactly_one_sample(client):
    body = {"text": "An essay of sufficient length for ingestion." * 20,
            "provenance": "unverified", "submission_uuid": "uu-seal-1"}
    r1 = client.post("/students/demo:replay/baseline", json=body)
    assert r1.status_code == 200
    n1 = r1.json().get("sample_count")
    r2 = client.post("/students/demo:replay/baseline", json=body)
    assert r2.json().get("skipped") is True
    assert r2.json().get("sample_count") == n1
```

(Adjust the success-shape assertions to whatever `add_baseline` actually returns — check its final `return` before writing; `sample_count` is expected there, verify with `grep -n "sample_count" original/api.py | head`.)

- [ ] **Step 2: Verify failure** (second post currently appends: `sample_count` grows).

- [ ] **Step 3: Implement.** `AddSampleRequest` gains `submission_uuid: str | None = Field(None, ...)`. In `add_baseline`, after `state = _repo().get_or_create(student_id)`:

```python
    # Seal-replay guard: a retried Bluebook seal must not double-weight this
    # sitting in the profile. Only active when the client sends its seal id —
    # normal baseline uploads keep today's behavior untouched.
    if req.submission_uuid:
        import hashlib

        text_hash = hashlib.sha256(req.text.encode()).hexdigest()
        if text_hash in _existing_text_hashes(student_id):
            return {"skipped": True, "reason": "duplicate_text",
                    "sample_count": len(state.samples)}
```

(`_existing_text_hashes` already exists in `api.py` — the Canvas-import dedup helper.)

- [ ] **Step 4: Run the file's tests + `tests/test_scoring_flags.py`** (flags-OFF byte-identical guard — this must not disturb scoring) → 0 failed.

- [ ] **Step 5: Commit.**

---

### Task 5: Client — Exam.jsx sessions, retry seal, offline, a11y

**Files:**
- Modify: `demo/bluebook/Exam.jsx` (helpers ~86–180; ExamScreen state ~296–340; countdown ~450–462; handleSubmit ~388–448; status region ~572; timer span ~824–831)
- Rebuild: `demo/bluebook/bluebook.bundle.js` (+ `.map`)

**Interfaces:**
- Consumes: `POST {BB_API_BASE}/bluebook/exams/{id}/session` (Task 3), `submission_uuid` fields (Tasks 3–4).

- [ ] **Step 1: Session helper** — after `bbAuthHeaders()`:

```jsx
// Pin the sitting's deadline server-side. Returns { deadlineMs, offsetMs }
// (offset = serverNow - clientNow, so deadline comparisons use server time),
// or null when the backend is unreachable — the caller then degrades open
// to the local countdown rather than stranding the student.
async function bbStartSession(cfg, studentId) {
  if (!cfg.id) return null;
  try {
    const r = await fetch(`${BB_API_BASE}/bluebook/exams/${encodeURIComponent(cfg.id)}/session`, {
      method: 'POST', headers: bbAuthHeaders(),
      body: JSON.stringify({ student_id: studentId || '', candidate: cfg.candidateEmail || cfg.candidate || '' }),
    });
    if (!r.ok) return null;
    const d = await r.json();
    return {
      deadlineMs: Date.parse(d.deadline_at),
      offsetMs: Date.parse(d.server_now) - Date.now(),
    };
  } catch (e) { return null; }
}
```

- [ ] **Step 2: Deadline-driven countdown.** In `ExamScreen`: add `const deadlineRef = useExRef(null);` and a mount effect:

```jsx
  // Server-pinned deadline (spec §1). timeLeft is DERIVED from the deadline
  // each tick, so refreshes can't pause the clock. Fallback: local countdown.
  useExEffect(() => {
    let cancelled = false;
    (async () => {
      const sid = await bbResolveStudentId(cfg);
      const s = await bbStartSession(cfg, sid);
      if (!cancelled && s && s.deadlineMs) deadlineRef.current = s;
    })();
    return () => { cancelled = true; };
  }, []);
```

Replace the countdown interval body:

```jsx
  useExEffect(() => {
    const id = setInterval(() => {
      const s = deadlineRef.current;
      if (s) {
        const left = Math.max(0, Math.round((s.deadlineMs - (Date.now() + s.offsetMs)) / 1000));
        setTimeLeft(left);
      } else {
        setTimeLeft(t => t > 0 ? t - 1 : 0);   // degrade-open local fallback
      }
    }, 1000);
    return () => clearInterval(id);
  }, []);
```

Remove `timeLeft` from `writeDraftNow()`'s payload and from the `restored` initializer (initialize `timeLeft` to `cfg.duration` unconditionally; the session effect corrects it within a second). Keep `restored.content` handling unchanged.

- [ ] **Step 3: Seal uuid + step flags in the draft.** Extend `writeDraftNow()`'s object with `seal: sealRef.current` where `const sealRef = useExRef((restored && restored.seal) || { uuid: null, aiScore: undefined, baselineData: null });`.

- [ ] **Step 4: Rewrite `handleSubmit`** — replace everything from `setSubmitting(true);` through `onNavigate('submitted');` with:

```jsx
    setSubmitting(true);
    const seal = sealRef.current;
    if (!seal.uuid) {
      seal.uuid = (crypto.randomUUID ? crypto.randomUUID()
        : 'uu-' + Date.now() + '-' + Math.random().toString(16).slice(2));
    }
    writeDraftNow();   // persists content + seal state before any network step

    const waitOnline = () => new Promise((res) => {
      if (navigator.onLine !== false) return res();
      const h = () => { window.removeEventListener('online', h); res(); };
      window.addEventListener('online', h);
    });

    const studentId = await bbResolveStudentId(cfg);
    let result = null;
    let lastError = null;
    const BACKOFF = [2000, 5000, 10000];
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        await waitOnline();
        // 1) Score against the EXISTING baseline (skipped on retry once known).
        if (seal.aiScore === undefined) {
          seal.aiScore = await bbScoreWithOriginal(studentId, content, cfg.title);
          writeDraftNow();
        }
        // 2) Add this proctored sitting (server dedupes by text on replay).
        if (!seal.baselineData) {
          const r = await bbSubmitToOriginal({
            text: content, assignment: cfg.title,
            keystrokeData: buildKeystrokeData(), cfg, studentId,
            submissionUuid: seal.uuid,
          });
          if (!r.ok) throw new Error(r.error || 'baseline write failed');
          seal.baselineData = r; writeDraftNow();
        }
        // 3) Record the sealed submission (server dedupes by submission_uuid).
        const drift = (seal.baselineData.data && seal.baselineData.data.drift
          && seal.baselineData.data.drift.drift_magnitude) || 0;
        const stylometric = Math.max(0, Math.min(100, Math.round((1 - drift) * 100)));
        const status = (drift > 0.5 || (seal.aiScore != null && seal.aiScore < 70))
          ? 'FLAGGED' : 'SUBMITTED';
        const timeMin = Math.max(0, Math.round(((cfg.duration || 0) - timeLeft) / 60));
        await BB_API.recordSubmission({
          exam_id: cfg.id || null,
          student_id: seal.baselineData.studentId || studentId,
          candidate: cfg.candidate, exam_title: cfg.title, course: cfg.course,
          word_count: wordCount(content), time_min: timeMin,
          stylometric, ai_score: seal.aiScore, status,
          submission_uuid: seal.uuid,
        });
        result = { ok: true, studentId: seal.baselineData.studentId || studentId, status };
        break;
      } catch (e) {
        lastError = e;
        setLiveMsg(`Sealing attempt ${attempt + 1} failed — retrying.`);
        if (attempt < 2) await new Promise(res => setTimeout(res, BACKOFF[attempt]));
      }
    }

    if (result && result.ok) {
      try { localStorage.removeItem(draftKey); } catch (e) {}
    } else {
      // Final failure: the draft stays on this device. Never strand the UI.
      setLiveMsg('Sealing failed. Your work is saved on this device — please tell your proctor.');
    }
    window.BB_LAST_SUBMISSION = {
      words: wordCount(content), title: cfg.title, courseTitle: cfg.courseTitle,
      candidate: cfg.candidate, studentId: (result && result.studentId) || studentId,
      ok: !!(result && result.ok),
      error: result && result.ok ? null : String((lastError && lastError.message) || lastError || 'seal failed'),
      aiScore: seal.aiScore, expired: !!opts.expired, draftKey,
    };
    setSubmitting(false);
    onNavigate('submitted');
```

Also thread `submissionUuid` through `bbSubmitToOriginal` — add it to the destructured params and to the fetch body as `submission_uuid: submissionUuid || undefined`.

- [ ] **Step 5: Offline banner + a11y.** Add `const [offline, setOffline] = useExState(navigator.onLine === false);` + listeners effect (`online`/`offline` → setOffline + `setLiveMsg('Connection lost — your writing is safe on this device.' / 'Connection restored.')`). Render, directly under the `role="status"` region:

```jsx
      {offline && (
        <div role="status" style={{
          position: 'fixed', bottom: 0, left: 0, right: 0, zIndex: 100,
          background: BB.parchment, borderTop: '1px solid rgba(201,169,97,0.7)',
          padding: '8px 48px', fontFamily: fontMono, fontSize: 12,
          letterSpacing: '0.08em', color: BB.indigo,
        }}>
          Connection lost — your writing is safe on this device.
          {submitting ? ' Your seal will submit when reconnected.' : ''}
        </div>
      )}
```

On the timer `<span>` (line ~824): add `role="timer"` and `aria-label={'Time remaining ' + fmt(timeLeft)}`. (The textarea already has `aria-label="Your examination answer"` — no change.)

- [ ] **Step 6: Rebuild + verify** — `cd demo/bluebook && npm run build`; then start the demo server per `.claude/launch.json` preview config (never kill an existing one), walk an exam: confirm the countdown continues correctly across a reload, and DevTools-offline at seal time shows the banner + parks, sealing on reconnect.

- [ ] **Step 7: Commit** (JSX + bundle + map together).

---

### Task 6: Playwright e2e — robustness spec

**Files:**
- Create: `demo/bluebook/e2e/exam-robustness.spec.mjs`
- Test command: `cd demo/bluebook && npx playwright test e2e/exam-robustness.spec.mjs`

**Interfaces:** Consumes the running pilot server + fixtures from `e2e/fixtures/api-setup.mjs` (study `professor-journey.spec.mjs`'s setup for tenant/exam provisioning and reuse its helpers verbatim).

- [ ] **Step 1: Write the spec** with three tests (adapt selectors from `professor-journey.spec.mjs`'s student-exam section — it already drives the exam screen):

```js
// 1) Deadline survives reload
test('reload does not reset the exam clock', async ({ page }) => {
  // ...provision exam via api-setup helpers, open exam as student, start sitting
  const t1 = await page.locator('[role="timer"]').textContent();
  await page.waitForTimeout(3000);
  await page.reload();
  const t2 = await page.locator('[role="timer"]').textContent();
  // parse mm:ss → seconds; the clock must have CONTINUED (t2 <= t1 - 2s),
  // not reset to the full duration
  expect(toSeconds(t2)).toBeLessThanOrEqual(toSeconds(t1) - 2);
});

// 2) Seal succeeds after one failed attempt
test('seal retries transient submission failure', async ({ page }) => {
  let failedOnce = false;
  await page.route('**/bluebook/submissions', (route) => {
    if (!failedOnce) { failedOnce = true; return route.abort(); }
    return route.continue();
  });
  // ...write past minWords, click seal, expect the submitted screen
  await expect(page.getByText(/sealed|submitted/i)).toBeVisible({ timeout: 30000 });
});

// 3) Total failure keeps the draft + shows proctor guidance
test('failed seal preserves the draft', async ({ page }) => {
  await page.route('**/students/*/baseline', (route) => route.abort());
  // ...write text, seal, wait for retries to exhaust (~20s)
  const draft = await page.evaluate(() =>
    Object.keys(localStorage).some(k => k.startsWith('bb_draft_')));
  expect(draft).toBe(true);
});
```

Fill the provisioning/drive steps by copying the exact patterns from `professor-journey.spec.mjs` (login, exam create, student launch). Write a small `toSeconds('45:12')` helper in the spec.

- [ ] **Step 2: Run** — start a scratch-DB pilot server exactly like the CI `bundle-e2e` job (`ORIGINAL_ENV=pilot SECRET_KEY=... MAINTENANCE_TOKEN=... LOGIN_THROTTLE_MAX_ATTEMPTS=500 ORIGINAL_DB=<scratch> .venv/bin/python run.py --demo --frontend-dir demo --port 8001 --skip-seed &`), run the spec, stop the server you started. Expected: 3 passed.

- [ ] **Step 3: Commit.**

---

### Task 7: Final verification + docs

- [ ] **Step 1:** `.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q` → **0 failed**.
- [ ] **Step 2:** Full e2e: `cd demo/bluebook && npx playwright test --grep-invert "@serial-lockout"` against a scratch server → 0 failed.
- [ ] **Step 3:** Update the spec doc's status line to `implemented <date>`; note the new endpoint in `docs/ARCHITECTURE.md`'s Bluebook section if it lists endpoints (check first).
- [ ] **Step 4:** Commit; report results + remaining sub-projects (2: corrections UI, 3: keystroke→Tier-17, 4: WS-8 adoption).
