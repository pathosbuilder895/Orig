# Professor-Approved Writing Baselines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sealed Bluebook exams enter a student's Original baseline only when a professor approves them (per exam or in bulk, removable), sealing becomes compare-only, and new Postgres workspace rows default to Bluebook only.

**Architecture:** A new router `original/routers/bluebook_baselines.py` approves by calling the existing baseline-write handler internally (so validation, the replay guard, the drift gate and audit stay in one place). It removes via a new `StudentState.remove_sample`. "In baseline" is derived by fingerprint (SHA-256 of the answer text) against the student's samples, with no approval storage. The exam page drops its seal-time baseline write. The professor's reader and exam page gain the controls. One Alembic revision changes the Postgres `products_json` default.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy/Alembic on Postgres 16, SQLite store, React 19 bundled by esbuild, Playwright, node:test.

**Spec:** `docs/superpowers/specs/2026-10-05-baseline-approval-design.md` (approved 2026-10-05).

## Global Constraints

- No typing rhythm or keystroke biometrics; text and coarse session information only.
- No student text leaves the deployment; no student text in audit-log details.
- Report-only, consistency-not-accusation wording: the baseline is the student's own reference writing; a held exam is "held for review", never "suspicious".
- Original stays off unless an operator switches it on; Bluebook-only workspaces see no new controls and every new route answers them 403 `This workspace's plan does not include Original.`
- Python: always `/Users/andrew/Desktop/Original/.venv/bin/python` (and `.../.venv/bin/alembic`); add `--no-cov` to focused pytest runs.
- After editing any `demo/bluebook/*.jsx`: `cd demo/bluebook && npm run build` and commit the rebuilt `*.bundle.*` files in the same commit.
- Postgres for tests: `postgresql://original:original@localhost:55432/original_test` (disposable; container `codex-bluebook-release-postgres`).
- Never kill or restart a server you did not start; start your own on a free port (8764–8790) with a scratch `ORIGINAL_DB`, and stop it afterwards.
- Commit messages: `Add …` / `Fix …` / `Refactor …`, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.
- Diffs touching `original/quantum/` get a `score-integrity-reviewer` pass before commit.

## File map

| File | Responsibility | Task |
|---|---|---|
| `alembic/versions/a7d3c9e1b5f2_bluebook_only_tenant_default.py` (new) | Postgres default `["bluebook"]` for new tenant rows | 1 |
| `original/db/models/live.py:168-174` | model `server_default` matches the migration | 1 |
| `tests/test_tenant_products_default_migration.py` (new) | upgrade/downgrade default check on Postgres | 1 |
| `original/quantum/state.py:165-171` | `StudentState.remove_sample` | 2 |
| `tests/quantum/test_remove_sample.py` (new) | removal equals a rebuild | 2 |
| `original/routers/bluebook_baselines.py` (new) | the four approval routes | 3 |
| `original/api.py:51-65, 594-605` | register the router | 3 |
| `tests/test_bluebook_baselines.py` (new) | route behaviour | 3 |
| `demo/bluebook/Exam.jsx` | compare-only seal | 4 |
| `demo/bluebook/e2e/{exam-flow,exam-robustness,professor-journey,original-switch}.spec.mjs` | specs follow the compare-only seal | 4 |
| `demo/bluebook/components.jsx` | four `BB_API` methods | 5 |
| `demo/bluebook/Teacher.jsx` | reader control, bulk button, `baselineSummary` | 5 |
| `demo/bluebook/unit/baselines.test.mjs` (new) | API client + summary text | 5 |
| `demo/bluebook/e2e/baseline-approval.spec.mjs` (new) | professor approval journey | 5 |
| `docs/BLUEBOOK_LAUNCH_CHECKLIST.md`, `docs/data_inventory.md`, `docs/release/VERIFICATION_AND_BLOCKERS.md`, spec | docs | 1, 6 |

---

### Task 1: Bluebook-only default for new Postgres tenant rows

**Files:**
- Create: `alembic/versions/a7d3c9e1b5f2_bluebook_only_tenant_default.py`
- Modify: `original/db/models/live.py:168-174`
- Modify: `docs/BLUEBOOK_LAUNCH_CHECKLIST.md` (the `Running upgrade … -> f4c9a2d71b30` line)
- Test: `tests/test_tenant_products_default_migration.py`

**Interfaces:**
- Produces: Alembic head `a7d3c9e1b5f2` (down revision `f4c9a2d71b30`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_tenant_products_default_migration.py`:

```python
"""New tenant rows default to Bluebook only (alembic a7d3c9e1b5f2).

Postgres inserts a placeholder tenants row for any write that names an
unregistered tenant (PostgresRepository._ensure_tenant_exists). With the old
default of both products such a workspace held Original without an operator
switching it on.
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from tests.test_migration import _postgres_available

pytestmark = pytest.mark.postgres

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _reset(engine) -> None:
    from original.db.models.live import LiveBase

    LiveBase.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))


@pytest.fixture
def migrated():
    if not _postgres_available():
        pytest.skip("no reachable Postgres — set DATABASE_URL to run the migration test")
    from original.db import postgres_session

    engine = postgres_session.get_engine()
    _reset(engine)
    cfg = Config(os.path.join(_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_ROOT, "alembic"))
    command.upgrade(cfg, "head")
    yield engine, cfg
    _reset(engine)


def _insert_default(conn, tenant_id: str):
    conn.execute(
        sa.text(
            "INSERT INTO tenants (tenant_id, name, environment, created_at) "
            "VALUES (:t, :t, 'pilot', now())"
        ),
        {"t": tenant_id},
    )
    return _products(conn, tenant_id)


def _products(conn, tenant_id: str):
    return conn.execute(
        sa.text("SELECT products_json FROM tenants WHERE tenant_id = :t"), {"t": tenant_id}
    ).scalar_one()


def test_new_rows_default_to_bluebook_only(migrated):
    engine, _cfg = migrated
    with engine.begin() as conn:
        assert _insert_default(conn, "after-upgrade") == ["bluebook"]


def test_downgrade_restores_the_old_default_and_keeps_existing_rows(migrated):
    engine, cfg = migrated
    with engine.begin() as conn:
        _insert_default(conn, "made-under-new-default")
    command.downgrade(cfg, "f4c9a2d71b30")
    with engine.begin() as conn:
        assert _insert_default(conn, "after-downgrade") == ["original", "bluebook"]
        assert _products(conn, "made-under-new-default") == ["bluebook"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `DATABASE_URL=postgresql://original:original@localhost:55432/original_test /Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_tenant_products_default_migration.py -q --no-cov`
Expected: `test_new_rows_default_to_bluebook_only` FAILS (`['original', 'bluebook'] == ['bluebook']`); the downgrade test fails because revision `f4c9a2d71b30` is already head (downgrade leaves the old default, and the first insert also gets both products — either assertion may be the one that fails).

- [ ] **Step 3: Write the migration and update the model**

Create `alembic/versions/a7d3c9e1b5f2_bluebook_only_tenant_default.py`:

```python
"""Bluebook-only default for new tenant rows

Revision ID: a7d3c9e1b5f2
Revises: f4c9a2d71b30
Create Date: 2026-10-05

A tenants row inserted without a products list (the repository's placeholder
row for a write that names an unregistered tenant, for one) used to default to
both products, so a workspace could hold Original without an operator
switching it on. New rows now default to Bluebook only. Existing rows keep
whatever products they hold; the downgrade restores the old default.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "a7d3c9e1b5f2"
down_revision: str | None = "f4c9a2d71b30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("tenants", "products_json", server_default=sa.text("""'["bluebook"]'"""))


def downgrade() -> None:
    op.alter_column(
        "tenants", "products_json", server_default=sa.text("""'["original", "bluebook"]'""")
    )
```

In `original/db/models/live.py`, replace the `products_json` comment and column (currently lines ~168-174):

```python
    # Products this tenant bought: "original" and/or "bluebook". New rows
    # default to Bluebook only (alembic a7d3c9e1b5f2): a placeholder row for a
    # write naming an unregistered tenant must not hold Original unless an
    # operator switches it on. Rows that predate that revision keep their
    # products. Read through principal.tenant_products(); enforced by the
    # product gate in api.py's tenant_isolation middleware.
    products_json: Mapped[list[str]] = mapped_column(
        JSONDoc, nullable=False, server_default=text("""'["bluebook"]'""")
    )
```

In `docs/BLUEBOOK_LAUNCH_CHECKLIST.md`, change `Running upgrade … -> f4c9a2d71b30` to `Running upgrade … -> a7d3c9e1b5f2`.

- [ ] **Step 4: Run the tests to verify they pass, plus the Postgres repository suites**

Run: `DATABASE_URL=postgresql://original:original@localhost:55432/original_test /Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_tenant_products_default_migration.py tests/test_repository_contract.py tests/test_migration.py tests/test_pg_backup_offbox.py -m postgres -q --no-cov`
Expected: all pass, 0 skipped. If a contract test asserts that a Postgres tenant created without products holds both products, change that assertion to `["bluebook"]` for the Postgres backend only, with a one-line comment citing a7d3c9e1b5f2. SQLite keeps both products by design, so never weaken a SQLite assertion.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/a7d3c9e1b5f2_bluebook_only_tenant_default.py original/db/models/live.py tests/test_tenant_products_default_migration.py docs/BLUEBOOK_LAUNCH_CHECKLIST.md tests/test_repository_contract.py
git commit -m "Fix implicit Postgres workspace rows defaulting to Original

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `StudentState.remove_sample`

**Files:**
- Modify: `original/quantum/state.py:165-171` (after `add_sample`)
- Test: `tests/quantum/test_remove_sample.py`

**Interfaces:**
- Produces: `StudentState.remove_sample(self, index: int) -> BaselineSample` — pops `samples[index]`, invalidates `_rho`, `_purity`, `_trajectory`, `_loo_distances`, returns the removed sample. Raises `IndexError` for a bad index.

- [ ] **Step 1: Write the failing test**

Create `tests/quantum/test_remove_sample.py`:

```python
"""StudentState.remove_sample: the professor can take an approved exam back
out of a student's baseline (plan Phase 7). The profile afterwards must be
exactly the one built from the remaining samples."""

from __future__ import annotations

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState


def _samples(n: int) -> list[BaselineSample]:
    rng = np.random.default_rng(7)
    return [
        BaselineSample(
            text=f"sample {i}",
            vector=rng.uniform(0.1, 0.9, FEATURE_DIM),
            provenance="proctored",
            auth_weight=1.0,
        )
        for i in range(n)
    ]


def test_removing_a_sample_matches_a_profile_built_without_it():
    s = _samples(4)
    state = StudentState(student_id="t:a", samples=list(s))
    # Fill every cache first, so a missed invalidation would show.
    _ = (state.density_matrix, state.purity, state.trajectory, state.loo_distances)

    removed = state.remove_sample(1)

    assert removed is s[1]
    fresh = StudentState(student_id="t:a", samples=[s[0], s[2], s[3]])
    np.testing.assert_allclose(state.density_matrix, fresh.density_matrix)
    assert state.purity == pytest.approx(fresh.purity)
    np.testing.assert_allclose(state.baseline_mean, fresh.baseline_mean)
    np.testing.assert_allclose(state.baseline_std, fresh.baseline_std)
    assert state.loo_distances == pytest.approx(fresh.loo_distances)
    assert state.sample_count == 3


def test_removing_a_missing_index_raises():
    state = StudentState(student_id="t:a", samples=_samples(1))
    with pytest.raises(IndexError):
        state.remove_sample(5)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/quantum/test_remove_sample.py -q --no-cov`
Expected: FAIL with `AttributeError: 'StudentState' object has no attribute 'remove_sample'`.

- [ ] **Step 3: Implement**

In `original/quantum/state.py`, directly after `add_sample`:

```python
    def remove_sample(self, index: int) -> BaselineSample:
        """Remove one baseline sample and invalidate the cached state.

        Every derived value (density matrix, purity, trajectory, leave-one-out
        distances) is recomputed from the remaining samples on next access, so
        the result equals a state built from them directly."""
        sample = self.samples.pop(index)
        self._rho = None
        self._purity = None
        self._trajectory = None
        self._loo_distances = None
        return sample
```

- [ ] **Step 4: Run it to verify it passes, plus the quantum suite**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/quantum/ -q --no-cov`
Expected: all pass.

- [ ] **Step 5: Score-integrity review, then commit**

Dispatch the `score-integrity-reviewer` agent on `git diff`. It must confirm the change is additive: no existing path calls `remove_sample`, and flag-off scoring is byte-identical. Resolve any finding, then:

```bash
git add original/quantum/state.py tests/quantum/test_remove_sample.py
git commit -m "Add StudentState.remove_sample for professor-removable baselines

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Approval routes

**Files:**
- Create: `original/routers/bluebook_baselines.py`
- Modify: `original/api.py` (router import list ~line 51-65; `app.router.routes.extend(...)` block ~line 594-605)
- Test: `tests/test_bluebook_baselines.py`

**Interfaces:**
- Consumes: `StudentState.remove_sample(index)` (Task 2); `add_baseline(student_id, req: AddSampleRequest, request)` and `_hashes_from_samples(samples) -> set[str]` from `original/routers/students_baseline.py`; `_can_touch(request, owner)` and `_owned_exam(exam_id, request)` from `original/routers/bluebook.py`; `_repo`, `_require_staff`, `_persist_or_503` from `original/routers/_shared.py`; `principal.tenant_products(tenant_id)`; `analyze_tension_arc`, `update_student_baseline_kappa` from `original/tension_arc.py`; `original.onboarding.set_original(email, enabled)` (tests).
- Produces (HTTP, used by Task 5):
  - `POST /bluebook/submissions/{id}/baseline` → `{"submission_id", "student", "status": "added"|"already_in_baseline"|"held", "detail"}`
  - `DELETE /bluebook/submissions/{id}/baseline` → same shape, `status: "removed"|"not_in_baseline"`
  - `POST /bluebook/exams/{id}/baseline` → `{"added", "already_in_baseline", "held", "nothing_written", "errors", "results": [row…]}`
  - `GET /bluebook/exams/{id}/baseline` → `{"submissions": [{"submission_id", "student", "in_baseline": bool, "has_text": bool}]}`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bluebook_baselines.py`:

```python
"""Professor-approved writing baselines (plan Phase 7,
docs/superpowers/specs/2026-10-05-baseline-approval-design.md)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException

from original import principal as principal_mod
from original.onboarding import set_original
from original.repository import get_repository

PW = "s3cret-passw0rd"
ANSWERS = [
    "Augustine argues that the restless heart finds rest only in God, and he builds the "
    "argument slowly, from memory and desire, through the long middle books of the work, "
    "until the reader sees that the search was the subject all along.",
    "I find the argument persuasive in its account of desire but less so in its account of "
    "memory, which seems to me to carry more of the weight than he admits, and which a modern "
    "reader would want to examine before accepting the conclusion he draws from it.",
]


@pytest.fixture(autouse=True)
def _isolate(store_reset, live_app):
    import original.api as api

    api._login_attempts.clear()
    principal_mod.invalidate_tenant_cache()
    yield
    api._login_attempts.clear()
    principal_mod.invalidate_tenant_cache()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _workspace(client, email="prof@school.edu", original=True):
    r = client.post(
        "/auth/signup",
        json={"email": email, "password": PW, "name": "Prof", "accept_terms": True},
    )
    assert r.status_code == 201, r.text
    prof = r.json()
    if original:
        set_original(email, True)
    course = client.post(
        "/bluebook/courses", json={"name": "Ethics", "code": "ETH"}, headers=_auth(prof["token"])
    ).json()["id"]
    exam = client.post(
        "/bluebook/exams",
        json={"title": "Midterm", "status": "ACTIVE", "prompt": "Discuss.", "course_id": course},
        headers=_auth(prof["token"]),
    ).json()
    return prof, course, exam


def _student(client, prof, course, email):
    row = client.post(
        f"/bluebook/courses/{course}/students",
        json={"students": [{"email": email, "name": email.split("@")[0]}]},
        headers=_auth(prof["token"]),
    ).json()["students"][0]
    token = parse_qs(urlparse(row["invite_path"]).query)["invite"][0]
    r = client.post("/auth/invite/redeem", json={"token": token, "password": PW})
    assert r.status_code == 200, r.text
    return r.json()


def _seal(client, student, exam_id, answers=ANSWERS):
    client.post(f"/bluebook/me/exams/{exam_id}/start", headers=_auth(student["token"]))
    body = {
        "exam_id": exam_id,
        "student_id": student["student_id"],
        "word_count": 120,
        "text": "\n\n".join(f"Question {i + 1}.\n{a}" for i, a in enumerate(answers)),
        "answers": answers,
        "submission_uuid": f"uuid-{student['student_id']}-{exam_id}",
    }
    r = client.post("/bluebook/submissions", json=body, headers=_auth(student["token"]))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _sample_count(student) -> int:
    state = get_repository().get(student["student_id"])
    return 0 if state is None else state.sample_count


def test_add_puts_the_answers_in_the_students_baseline(live_client):
    prof, course, exam = _workspace(live_client)
    stu = _student(live_client, prof, course, "one@school.edu")
    sub = _seal(live_client, stu, exam["id"])

    r = live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "added"
    state = get_repository().get(stu["student_id"])
    assert state.sample_count == 1
    assert state.samples[0].provenance == "proctored"
    assert state.samples[0].text == "\n\n".join(ANSWERS)  # no "Question N." headings
    assert state.samples[0].assignment == "Midterm"
    status = live_client.get(f"/bluebook/exams/{exam['id']}/baseline", headers=_auth(prof["token"]))
    rows = status.json()["submissions"]
    assert [(r["submission_id"], r["in_baseline"], r["has_text"]) for r in rows] == [(sub, True, True)]


def test_adding_twice_is_a_no_op(live_client):
    prof, course, exam = _workspace(live_client)
    stu = _student(live_client, prof, course, "one@school.edu")
    sub = _seal(live_client, stu, exam["id"])
    live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))

    r = live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))

    assert r.json()["status"] == "already_in_baseline"
    assert _sample_count(stu) == 1


def test_remove_then_add_again(live_client):
    prof, course, exam = _workspace(live_client)
    stu = _student(live_client, prof, course, "one@school.edu")
    sub = _seal(live_client, stu, exam["id"])
    live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))

    removed = live_client.delete(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))
    again = live_client.delete(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))
    readded = live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))

    assert removed.json()["status"] == "removed"
    assert again.json()["status"] == "not_in_baseline"
    assert readded.json()["status"] == "added"
    assert _sample_count(stu) == 1


def test_remove_finds_a_sample_the_old_seal_added_with_headings(live_client):
    from original.routers import students_baseline
    from original.schemas import AddSampleRequest

    prof, course, exam = _workspace(live_client)
    stu = _student(live_client, prof, course, "one@school.edu")
    sub = _seal(live_client, stu, exam["id"])
    stored = get_repository().get_bluebook_submission(sub)
    # What the pre-Phase-7 seal sent: the stored text, headings included.
    students_baseline.add_baseline(
        stu["student_id"], AddSampleRequest(text=stored["text"], provenance="unverified"), None
    )
    assert _sample_count(stu) == 1
    status = live_client.get(f"/bluebook/exams/{exam['id']}/baseline", headers=_auth(prof["token"]))
    assert status.json()["submissions"][0]["in_baseline"] is True

    r = live_client.delete(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))

    assert r.json()["status"] == "removed"
    assert _sample_count(stu) == 0


def test_a_sample_held_by_the_drift_gate_is_reported_not_added(live_client, monkeypatch):
    from original.routers import bluebook_baselines

    def held(student_id, req, request):
        raise HTTPException(status_code=202, detail={"status": "pending_review"})

    monkeypatch.setattr(bluebook_baselines, "add_baseline", held)
    prof, course, exam = _workspace(live_client)
    stu = _student(live_client, prof, course, "one@school.edu")
    sub = _seal(live_client, stu, exam["id"])

    r = live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))

    assert r.status_code == 200
    assert r.json()["status"] == "held"
    assert "held for review" in r.json()["detail"]
    assert _sample_count(stu) == 0


def test_bulk_adds_every_sealed_submission(live_client):
    prof, course, exam = _workspace(live_client)
    one = _student(live_client, prof, course, "one@school.edu")
    two = _student(live_client, prof, course, "two@school.edu")
    blank = _student(live_client, prof, course, "blank@school.edu")
    _seal(live_client, one, exam["id"])
    _seal(live_client, two, exam["id"], answers=[ANSWERS[1], ANSWERS[0]])
    _seal(live_client, blank, exam["id"], answers=[""])

    first = live_client.post(f"/bluebook/exams/{exam['id']}/baseline", headers=_auth(prof["token"]))
    second = live_client.post(f"/bluebook/exams/{exam['id']}/baseline", headers=_auth(prof["token"]))

    assert first.status_code == 200, first.text
    body = first.json()
    assert (body["added"], body["already_in_baseline"], body["held"]) == (2, 0, 0)
    assert (body["nothing_written"], body["errors"]) == (1, 0)
    assert len(body["results"]) == 3
    assert second.json()["already_in_baseline"] == 2


def test_empty_submission_is_refused(live_client):
    prof, course, exam = _workspace(live_client)
    stu = _student(live_client, prof, course, "one@school.edu")
    sub = _seal(live_client, stu, exam["id"], answers=[""])

    r = live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))

    assert r.status_code == 422
    assert r.json()["detail"] == "Nothing written to add."


def test_bluebook_only_workspace_is_refused(live_client):
    prof, course, exam = _workspace(live_client, original=False)
    stu = _student(live_client, prof, course, "one@school.edu")
    sub = _seal(live_client, stu, exam["id"])
    h = _auth(prof["token"])

    responses = [
        live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=h),
        live_client.delete(f"/bluebook/submissions/{sub}/baseline", headers=h),
        live_client.post(f"/bluebook/exams/{exam['id']}/baseline", headers=h),
        live_client.get(f"/bluebook/exams/{exam['id']}/baseline", headers=h),
    ]

    assert [r.status_code for r in responses] == [403, 403, 403, 403]
    assert all(r.json()["detail"] == "This workspace's plan does not include Original." for r in responses)


def test_another_workspace_gets_404(live_client):
    prof, course, exam = _workspace(live_client)
    stu = _student(live_client, prof, course, "one@school.edu")
    sub = _seal(live_client, stu, exam["id"])
    other, _c, _e = _workspace(live_client, email="other@school.edu")
    h = _auth(other["token"])

    assert live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=h).status_code == 404
    assert live_client.delete(f"/bluebook/submissions/{sub}/baseline", headers=h).status_code == 404
    assert live_client.post(f"/bluebook/exams/{exam['id']}/baseline", headers=h).status_code == 404
    assert live_client.get(f"/bluebook/exams/{exam['id']}/baseline", headers=h).status_code == 404


def test_a_student_cannot_approve(live_client):
    prof, course, exam = _workspace(live_client)
    stu = _student(live_client, prof, course, "one@school.edu")
    sub = _seal(live_client, stu, exam["id"])

    r = live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=_auth(stu["token"]))

    assert r.status_code == 403
    assert _sample_count(stu) == 0


def test_every_action_is_audited_without_student_text(live_client):
    prof, course, exam = _workspace(live_client)
    stu = _student(live_client, prof, course, "one@school.edu")
    sub = _seal(live_client, stu, exam["id"])
    h = _auth(prof["token"])
    live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=h)
    live_client.delete(f"/bluebook/submissions/{sub}/baseline", headers=h)
    live_client.post(f"/bluebook/exams/{exam['id']}/baseline", headers=h)

    repo = get_repository()
    for action in ("baseline_approve", "baseline_remove", "baseline_approve_bulk"):
        items = repo.list_audit(action=action)["items"]
        assert items, action
        assert "Augustine" not in repr(items)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_bluebook_baselines.py -q --no-cov`
Expected: failures with 404 (routes do not exist) and, for the held test, `ImportError`/`AttributeError` on `original.routers.bluebook_baselines`.

- [ ] **Step 3: Write the router**

Create `original/routers/bluebook_baselines.py`:

```python
"""Professor-approved writing baselines (plan Phase 7).

A sealed Bluebook exam enters a student's Original baseline only when a
professor approves it, one at a time or for a whole examination, and an
approval can be removed. "In baseline" is derived from the baseline itself:
the SHA-256 of the exam's answer text among the student's sample hashes, so
there is no approval table to drift out of step with the profile.

Adding goes through the existing baseline-write handler, so validation, the
seal-replay guard, the drift gate and its audit entry apply unchanged; the
drift gate is never overridden. Design:
docs/superpowers/specs/2026-10-05-baseline-approval-design.md
"""

from __future__ import annotations

import hashlib
import sys

from fastapi import APIRouter, HTTPException, Request

from .. import principal as principal_mod
from ..schemas import AddSampleRequest
from ..tension_arc import analyze_tension_arc, update_student_baseline_kappa
from ._shared import _persist_or_503, _repo, _require_staff
from .bluebook import _can_touch, _owned_exam
from .students_baseline import _hashes_from_samples, add_baseline

router = APIRouter()

NO_ORIGINAL = "This workspace's plan does not include Original."
NOTHING_WRITTEN = "Nothing written to add."
HELD_DETAIL = (
    "Not added: this exam differs strongly from the student's existing samples, "
    "so it was held for review."
)


def _baseline_text(rec: dict) -> str:
    """The student's own words: answers joined by a blank line, without the
    "Question N." headings the stored text carries for multi-question exams."""
    raw = rec.get("answers") or []
    if raw:  # stored answers win, even when all blank: the text has headings
        return "\n\n".join(str(a).strip() for a in raw if str(a or "").strip())
    return (rec.get("text") or "").strip()


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _fingerprints(rec: dict) -> set[str]:
    """Every fingerprint this exam can have in a baseline: the approved form
    (answers, no headings) and, for samples the old seal-time write added,
    the stored text exactly as it was sent (with "Question N." headings)."""
    out = set()
    text = _baseline_text(rec)
    if text:
        out.add(_fingerprint(text))
    if rec.get("text"):
        out.add(_fingerprint(rec["text"]))
    return out


def _require_original(tenant_id: str | None) -> None:
    if "original" not in principal_mod.tenant_products(tenant_id):
        raise HTTPException(status_code=403, detail=NO_ORIGINAL)


def _actor(request: Request) -> str:
    p = getattr(request.state, "principal", None)
    return getattr(p, "user_id", "") or ""


def _owned_submission(submission_id: str, request: Request) -> dict:
    _require_staff(request)
    rec = _repo().get_bluebook_submission(submission_id)
    if rec is None or not _can_touch(request, rec.get("tenant_id")):
        raise HTTPException(status_code=404, detail="submission not found")
    _require_original(rec.get("tenant_id"))
    return rec


def _owned_original_exam(exam_id: str, request: Request) -> dict:
    _require_staff(request)
    exam = _owned_exam(exam_id, request)
    _require_original(exam.get("tenant_id"))
    return exam


def _submitted_at(rec: dict) -> str:
    created = rec.get("created_at")
    value = created.isoformat() if hasattr(created, "isoformat") else str(created or "")
    return value[:10]


def _row(rec: dict, status: str, detail: str = "") -> dict:
    return {
        "submission_id": rec["id"],
        "student": rec.get("student"),
        "status": status,
        "detail": detail,
    }


def _add(rec: dict, request: Request) -> dict:
    text = _baseline_text(rec)
    if not text or not rec.get("student_id"):
        return _row(rec, "nothing_written", NOTHING_WRITTEN)
    req = AddSampleRequest(
        text=text,
        provenance="proctored",
        assignment=rec.get("exam") or "",
        submitted_at=_submitted_at(rec),
        submission_uuid=rec.get("submission_uuid") or rec["id"],
    )
    try:
        out = add_baseline(rec["student_id"], req, request)
    except HTTPException as exc:
        if exc.status_code in (202, 409):  # drift gate: flag for review / rebaseline
            return _row(rec, "held", HELD_DETAIL)
        raise
    return _row(rec, "already_in_baseline" if out.get("skipped") else "added")


def _matching_indices(state, fingerprints: set[str]) -> list[int]:
    """Indices of every sample carrying one of this exam's fingerprints
    (duplicates included), highest first so they can be popped in order."""
    return [
        i
        for i in range(len(state.samples) - 1, -1, -1)
        if _hashes_from_samples([state.samples[i]]) & fingerprints
    ]


def _rebuild_kappa(state) -> None:
    """Recompute the tension-arc κ baseline from the remaining samples with
    the admission rule (authenticated provenance, κ > 0)."""
    log: list[float] = []
    mean = None
    for sample in state.samples:
        if sample.provenance in ("proctored", "verified") and sample.text:
            kappa = analyze_tension_arc(sample.text).catastrophe_index
            if kappa > 0:
                mean = update_student_baseline_kappa(log, kappa)
    state.kappa_log = log
    state.baseline_kappa = mean


@router.post("/bluebook/submissions/{submission_id}/baseline")
def approve_submission_baseline(submission_id: str, request: Request):
    """Add one sealed exam to the student's writing baseline."""
    rec = _owned_submission(submission_id, request)
    result = _add(rec, request)
    if result["status"] == "nothing_written":
        raise HTTPException(status_code=422, detail=NOTHING_WRITTEN)
    _repo().log_audit(
        action="baseline_approve",
        student_id=rec["student_id"],
        tenant_id=rec.get("tenant_id"),
        actor=_actor(request),
        result=result["status"],
        details={"submission_id": rec["id"]},
    )
    return result


@router.delete("/bluebook/submissions/{submission_id}/baseline")
def remove_submission_baseline(submission_id: str, request: Request):
    """Take one exam back out of the student's baseline; the profile is
    recomputed from the remaining samples."""
    rec = _owned_submission(submission_id, request)
    fingerprints = _fingerprints(rec)
    state = _repo().get(rec["student_id"]) if rec.get("student_id") and fingerprints else None
    indices = _matching_indices(state, fingerprints) if state is not None else []
    if not indices:
        return _row(rec, "not_in_baseline")
    for index in indices:
        state.remove_sample(index)
    _rebuild_kappa(state)
    _persist_or_503(state)
    # The fused score keeps a per-student profile of raw baseline text in
    # process (FUSED_SCORE_* flags); drop it, as delete_student does.
    fusion_peers = sys.modules.get("original.fusion.peers")
    if fusion_peers is not None:
        fusion_peers.clear_student(rec["student_id"])
    _repo().log_audit(
        action="baseline_remove",
        student_id=rec["student_id"],
        tenant_id=rec.get("tenant_id"),
        actor=_actor(request),
        result="removed",
        details={
            "submission_id": rec["id"],
            "samples_removed": len(indices),
            "sample_count_after": state.sample_count,
        },
    )
    return _row(rec, "removed")


@router.post("/bluebook/exams/{exam_id}/baseline")
def approve_exam_baselines(exam_id: str, request: Request):
    """Add every sealed submission of an examination to its student's baseline."""
    exam = _owned_original_exam(exam_id, request)
    counts = {"added": 0, "already_in_baseline": 0, "held": 0, "nothing_written": 0, "errors": 0}
    results = []
    for rec in _repo().list_bluebook_submissions_for_exam(exam_id):
        try:
            row = _add(rec, request)
        except HTTPException as exc:
            row = _row(rec, "error", str(exc.detail))
        counts["errors" if row["status"] == "error" else row["status"]] += 1
        results.append(row)
    _repo().log_audit(
        action="baseline_approve_bulk",
        tenant_id=exam.get("tenant_id"),
        actor=_actor(request),
        details={"exam_id": exam_id, **counts},
    )
    return {**counts, "results": results}


@router.get("/bluebook/exams/{exam_id}/baseline")
def exam_baseline_status(exam_id: str, request: Request):
    """Whether each submission of an examination is in its student's baseline."""
    _owned_original_exam(exam_id, request)
    states: dict = {}
    out = []
    for rec in _repo().list_bluebook_submissions_for_exam(exam_id):
        text = _baseline_text(rec)
        sid = rec.get("student_id")
        if sid and sid not in states:
            states[sid] = _repo().get(sid)
        state = states.get(sid) if sid else None
        in_baseline = bool(
            state is not None and _fingerprints(rec) & _hashes_from_samples(state.samples)
        )
        out.append(
            {
                "submission_id": rec["id"],
                "student": rec.get("student"),
                "in_baseline": in_baseline,
                "has_text": bool(text),
            }
        )
    return {"submissions": out}
```

In `original/api.py`, add `bluebook_baselines,` to the `from .routers import (...)` list (alphabetical, after `bluebook_accounts,`), and add `app.router.routes.extend(bluebook_baselines.router.routes)` directly after the `bluebook_accounts` line.

- [ ] **Step 4: Run the tests to verify they pass, plus neighbours**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_bluebook_baselines.py tests/test_bluebook_self_serve.py tests/test_bluebook_crud.py tests/test_openapi_stability.py tests/security/ tests/test_pilot_lockdown.py -q --no-cov`
Expected: all pass. If `test_add_puts_the_answers_in_the_students_baseline` fails because the drift gate holds the very first sample, read `check_drift` in `original/quantum/state.py`. If it holds first samples by design, seal a second, different exam for the student first (approve both), and say so in the report. Do not weaken the assertion.

- [ ] **Step 5: Commit**

```bash
git add original/routers/bluebook_baselines.py original/api.py tests/test_bluebook_baselines.py
git commit -m "Add professor approval routes for writing baselines

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Compare-only seal

**Files:**
- Modify: `demo/bluebook/Exam.jsx` (seal loop: steps 1–3 inside `handleSubmit`; delete `bbSubmitToOriginal`)
- Modify: `demo/bluebook/e2e/exam-flow.spec.mjs:211-268`, `demo/bluebook/e2e/exam-robustness.spec.mjs:141-142`, `demo/bluebook/e2e/professor-journey.spec.mjs:264-265`, `demo/bluebook/e2e/original-switch.spec.mjs:9-17,147`

**Interfaces:**
- Produces: a seal in a workspace holding Original makes no `POST /students/{id}/baseline`; `recordSubmission` sends `stylometric: null`; `status` is `FLAGGED` only when `withOriginal && seal.aiScore != null && seal.aiScore < 70`.

- [ ] **Step 1: Change the specs first, so they state the new behaviour**

In `demo/bluebook/e2e/exam-flow.spec.mjs`, rename the test at line 211 to `'Type past minimum → Seal → Examination Sealed, recorded, and no baseline write'`. Before the seal click (`page.once('dialog', …)` line), add:

```js
    // Compare-only seal (plan Phase 7): sealing never adds a baseline
    // sample; only a professor's approval does.
    const baselineWrites = []
    page.on('request', r => {
      if (r.method() === 'POST' && /\/students\/[^/]+\/baseline$/.test(new URL(r.url()).pathname)) {
        baselineWrites.push(r.url())
      }
    })
```

Replace everything from the comment `// ── API-side verification: the bound student now has a proctored sample` to the end of that test with:

```js
    expect(baselineWrites).toEqual([])
  })
```

In `demo/bluebook/e2e/exam-robustness.spec.mjs`, replace

```js
    // Kill the seal at step 2 (baseline write) on every attempt.
    await studentPage.route('**/students/*/baseline', (route) => route.abort())
```

with

```js
    // Kill the seal's submission record (its only write) on every attempt.
    await studentPage.route('**/bluebook/submissions', (route) =>
      route.request().method() === 'POST' ? route.abort() : route.continue())
```

In `demo/bluebook/e2e/professor-journey.spec.mjs`, replace the two comment lines

```js
    // The proctored-baseline transmission succeeded (recordSubmission only
    // runs when it does — Exam.jsx handleSubmit).
```

with

```js
    // The submission record was written (the sealed screen only says
    // "Delivered" when recordSubmission succeeded — Exam.jsx handleSubmit).
```

In `demo/bluebook/e2e/original-switch.spec.mjs`, change header lines 11-15 to say the seal calls Original's **score** route, which now answers 403, and records the submission as a Bluebook-only workspace does. Change line 147 from `c.path.endsWith('/baseline')` to `c.path.endsWith('/score')`.

- [ ] **Step 2: Change the seal**

In `demo/bluebook/Exam.jsx`, inside `handleSubmit`'s retry loop, replace the block from `// 2) Add this proctored sitting` through the line `const status = withOriginal && (drift > 0.5 || (seal.aiScore != null && seal.aiScore < 70))` / `? 'FLAGGED' : 'SUBMITTED';` with:

```js
        // 2) Record the sealed submission (server dedupes by submission_uuid).
        // Compare-only (plan Phase 7): the seal never adds to the student's
        // baseline; a professor approves which sealed exams become baseline
        // samples. A workspace switched off Original since this sitting began
        // answers the score call with 403, which returns null above, so the
        // exam is recorded exactly like a Bluebook-only one.
        const stylometric = null;
        const status = withOriginal && seal.aiScore != null && seal.aiScore < 70
          ? 'FLAGGED' : 'SUBMITTED';
```

In the `BB_API.recordSubmission({...})` call and the `result = {...}` line just below it, replace `baseline.studentId || studentId` with `studentId` (both places). Delete the now-unused `async function bbSubmitToOriginal(...)` (around line 314) and its leading comment. Leave `bbAuthHeaders` and the proctor-token storage in place; the score call still sends them, harmlessly. Rename the remaining step comment `// 3) Record the sealed submission` if one is left, so the numbering reads 1, 2. Then `grep -n "baselineData\|bbSubmitToOriginal\|drift" demo/bluebook/Exam.jsx`: remove any remaining reference to `seal.baselineData` or the drift variable, but keep `baselineData: null` in the seal-state initialisers (old drafts carry it).

- [ ] **Step 3: Build and run unit tests**

Run: `cd demo/bluebook && npm run build && node --test unit/`
Expected: three ✓ lines; all unit tests pass.

- [ ] **Step 4: Run the affected Playwright specs against your own pilot-mode server**

Start (background, from the worktree root): `ORIGINAL_ENV=pilot SECRET_KEY=ci-test-only-secret-do-not-deploy MAINTENANCE_TOKEN=ci-test-only LOGIN_THROTTLE_MAX_ATTEMPTS=500 ORIGINAL_DB=<scratchpad>/t4.db /Users/andrew/Desktop/Original/.venv/bin/python run.py --demo --frontend-dir demo --port 8771 --skip-seed`, wait for `curl -sf localhost:8771/health`.
Run: `cd demo/bluebook && PLAYWRIGHT_BASE_URL=http://localhost:8771 SECRET_KEY=ci-test-only-secret-do-not-deploy MAINTENANCE_TOKEN=ci-test-only npx playwright test e2e/exam-flow.spec.mjs e2e/exam-robustness.spec.mjs e2e/professor-journey.spec.mjs e2e/original-switch.spec.mjs e2e/self-serve.spec.mjs`
Expected: all pass. Stop the server.

- [ ] **Step 5: Commit**

```bash
git add demo/bluebook/Exam.jsx demo/bluebook/*.bundle.* demo/bluebook/e2e/exam-flow.spec.mjs demo/bluebook/e2e/exam-robustness.spec.mjs demo/bluebook/e2e/professor-journey.spec.mjs demo/bluebook/e2e/original-switch.spec.mjs
git commit -m "Fix sealing adding exams to baselines without professor approval

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Professor controls

**Files:**
- Modify: `demo/bluebook/components.jsx` (after `unreleaseResults`, ~line 464)
- Modify: `demo/bluebook/Teacher.jsx` (`SubmissionReader` ~46-124; `ManageExamScreen` ~201-300)
- Create: `demo/bluebook/unit/baselines.test.mjs`
- Create: `demo/bluebook/e2e/baseline-approval.spec.mjs`

**Interfaces:**
- Consumes: the four routes from Task 3.
- Produces: `BB_API.addToBaseline(id)`, `BB_API.removeFromBaseline(id)`, `BB_API.examBaselineStatus(examId)`, `BB_API.addExamToBaselines(examId)`; `export function baselineSummary(result) -> string` in `Teacher.jsx`.

- [ ] **Step 1: Write the failing unit test**

Create `demo/bluebook/unit/baselines.test.mjs`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

const bundle = async (file) => {
  const built = await build({
    entryPoints: [new URL(file, import.meta.url).pathname],
    bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic', logLevel: 'silent',
  });
  return import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));
};

globalThis.window = { BB_API_BASE: '' };
globalThis.localStorage = { getItem: () => 'test-session', setItem() {}, removeItem() {} };
const { BB_API } = await bundle('../components.jsx');
const { baselineSummary } = await bundle('../Teacher.jsx');

test('baseline API methods call the approval routes', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => { calls.push([init.method, url]); return new Response('{}'); };
  await BB_API.addToBaseline('s 1');
  await BB_API.removeFromBaseline('s 1');
  await BB_API.examBaselineStatus('e/1');
  await BB_API.addExamToBaselines('e/1');
  assert.deepEqual(calls, [
    ['POST', '/bluebook/submissions/s%201/baseline'],
    ['DELETE', '/bluebook/submissions/s%201/baseline'],
    ['GET', '/bluebook/exams/e%2F1/baseline'],
    ['POST', '/bluebook/exams/e%2F1/baseline'],
  ]);
});

test('the bulk summary counts every outcome and names held students', () => {
  assert.equal(
    baselineSummary({ added: 2, already_in_baseline: 1, held: 1, nothing_written: 0, errors: 0,
      results: [{ status: 'held', student: 'Ana' }, { status: 'added', student: 'Ben' }] }),
    '2 added · 1 already in baseline · 1 held for review. Held: Ana.',
  );
  assert.equal(
    baselineSummary({ added: 0, already_in_baseline: 0, held: 0, nothing_written: 1, errors: 1, results: [] }),
    '0 added · 0 already in baseline · 0 held for review · 1 with nothing written · 1 could not be added.',
  );
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd demo/bluebook && node --test unit/baselines.test.mjs`
Expected: FAIL. `BB_API.addToBaseline is not a function` / `baselineSummary is not a function`.

- [ ] **Step 3: Implement**

In `demo/bluebook/components.jsx`, after the `unreleaseResults` line:

```js
  // Professor-approved writing baselines (plan Phase 7).
  addToBaseline(id)      { return this._json('POST',   `/bluebook/submissions/${encodeURIComponent(id)}/baseline`); },
  removeFromBaseline(id) { return this._json('DELETE', `/bluebook/submissions/${encodeURIComponent(id)}/baseline`); },
  examBaselineStatus(id) { return this._json('GET',    `/bluebook/exams/${encodeURIComponent(id)}/baseline`); },
  addExamToBaselines(id) { return this._json('POST',   `/bluebook/exams/${encodeURIComponent(id)}/baseline`); },
```

In `demo/bluebook/Teacher.jsx`, above `export function SubmissionReader`, add (use the hook names the file already uses, e.g. `useState`/`useEffect`; `Btn`, `Notice` and `ErrorText` are already imported there):

```jsx
// Professor-approved writing baselines (plan Phase 7). Only a workspace that
// holds Original sees these controls; a sealed exam enters a student's
// baseline only when a professor adds it here or in bulk.
const BASELINE_MESSAGE = {
  added: name => `Added to ${name}'s baseline.`,
  already_in_baseline: () => 'Already in the baseline.',
  removed: name => `Removed from ${name}'s baseline.`,
  not_in_baseline: () => 'It was not in the baseline.',
};

export function baselineSummary(r) {
  const parts = [
    `${r.added} added`,
    `${r.already_in_baseline} already in baseline`,
    `${r.held} held for review`,
  ];
  if (r.nothing_written) parts.push(`${r.nothing_written} with nothing written`);
  if (r.errors) parts.push(`${r.errors} could not be added`);
  const held = (r.results || []).filter(x => x.status === 'held').map(x => x.student).filter(Boolean);
  return parts.join(' · ') + (held.length ? `. Held: ${held.join(', ')}.` : '.');
}

function BaselineControl({ sub }) {
  const [inBaseline, setInBaseline] = useState(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const name = sub.student || 'the student';

  useEffect(() => {
    let live = true;
    if (!sub.exam_id) return undefined;
    BB_API.examBaselineStatus(sub.exam_id).then(d => {
      if (!live) return;
      const row = (d.submissions || []).find(r => r.submission_id === sub.id);
      setInBaseline(row ? !!row.in_baseline : false);
    }).catch(err => { if (live) setError(err.message || 'Could not load the baseline status.'); });
    return () => { live = false; };
  }, [sub.id, sub.exam_id]);

  async function add() {
    setBusy(true); setError(''); setMessage('');
    try {
      const r = await BB_API.addToBaseline(sub.id);
      if (r.status === 'held') setMessage(r.detail);
      else { setInBaseline(true); setMessage(BASELINE_MESSAGE[r.status](name)); }
    } catch (err) { setError(err.message || 'Could not add to the baseline.'); }
    setBusy(false);
  }

  async function remove() {
    if (!confirm(`Remove this exam from ${name}'s baseline? Their profile is recomputed from the remaining samples.`)) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const r = await BB_API.removeFromBaseline(sub.id);
      setInBaseline(false); setMessage(BASELINE_MESSAGE[r.status](name));
    } catch (err) { setError(err.message || 'Could not remove from the baseline.'); }
    setBusy(false);
  }

  if (!sub.exam_id) return null;
  return (
    <div className="bb-baseline" style={{ margin: '1rem 0' }}>
      <p style={{ margin: '0 0 .4rem' }}>
        <strong>Writing baseline:</strong>{' '}
        {inBaseline === null ? 'checking…' : inBaseline ? 'In baseline' : 'Not in baseline'}
      </p>
      <p className="bb-hint" style={{ margin: '0 0 .6rem' }}>
        The baseline is {name}'s own reference writing. Only exams you add are used.
      </p>
      {inBaseline === true && <Btn onClick={remove} disabled={busy}>Remove from baseline</Btn>}
      {inBaseline === false && <Btn onClick={add} disabled={busy}>Add to baseline</Btn>}
      <Notice>{message}</Notice>
      <ErrorText>{error}</ErrorText>
    </div>
  );
}
```

In `SubmissionReader`, directly after the closing `</div>` of `<div className="bb-paper">…</div>` and before `<form onSubmit={save}`, add:

```jsx
          {BB_API.hasOriginal() && <BaselineControl sub={sub} />}
```

In `ManageExamScreen`, after `async function exportCsv() {…}`, add:

```jsx
  async function addAllToBaselines() {
    if (!confirm('Add every sealed submission of this examination to the students’ writing baselines? Exams that differ strongly from a student’s existing samples are held for review, not added.')) return;
    setError(''); setNotice('');
    try { setNotice(baselineSummary(await BB_API.addExamToBaselines(examId))); }
    catch (err) { setError(err.message || 'Could not add to baselines.'); }
  }
```

and in its `actions` fragment, after `<Btn onClick={exportCsv}>Export CSV</Btn>`:

```jsx
        {BB_API.hasOriginal() && <Btn onClick={addAllToBaselines}>Add all sealed submissions to baselines</Btn>}
```

- [ ] **Step 4: Build and run the unit tests**

Run: `cd demo/bluebook && npm run build && node --test unit/`
Expected: all unit tests pass, including the two new ones.

- [ ] **Step 5: Write the Playwright journey**

Create `demo/bluebook/e2e/baseline-approval.spec.mjs`:

```js
/**
 * baseline-approval.spec.mjs — a professor approves sealed exams as writing
 * baselines (plan Phase 7): add one from the reader, see it marked, remove
 * it, then add a whole examination's submissions in bulk. A Bluebook-only
 * workspace sees none of these controls.
 *
 * Needs MAINTENANCE_TOKEN set to the server's value (staff registration and
 * the guarded tenant PATCH send it as X-Guard-Token).
 */

import { test, expect } from '@playwright/test'
import { createCourse, provisionStaff, provisionTenantWithStaff, staffStorageState } from './fixtures/api-setup.mjs'

const uid = () => `${process.pid}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`
const ANSWER =
  'Augustine argues that the restless heart finds rest only in God, and he builds the argument ' +
  'slowly, from memory and desire, through the long middle books of the work, until the reader ' +
  'sees that the search was the subject all along. I find the account of desire persuasive.'

async function sealedExam(request, { products }) {
  const id = uid()
  const { tenant, staff } = await provisionTenantWithStaff(request)
  const teacher = { Authorization: `Bearer ${staff.token}` }
  if (products) {
    const operator = await provisionStaff(request, { tenantId: tenant.tenant_id, role: 'operator', name: 'E2E Operator' })
    const patched = await request.patch(`/tenants/${encodeURIComponent(tenant.tenant_id)}`, {
      headers: {
        Authorization: `Bearer ${operator.token}`,
        ...(process.env.MAINTENANCE_TOKEN ? { 'X-Guard-Token': process.env.MAINTENANCE_TOKEN } : {}),
      },
      data: { products },
    })
    expect(patched.status(), await patched.text()).toBe(200)
  }
  const course = await createCourse(request, staff.token, { name: `Baseline course ${id}` })
  const examTitle = `Baseline exam ${id}`
  const created = await request.post('/bluebook/exams', {
    headers: teacher,
    data: { title: examTitle, course: course.code, course_id: course.id, duration: 30, prompt: 'Discuss.', status: 'ACTIVE' },
  })
  expect(created.status(), await created.text()).toBe(201)
  const examId = (await created.json()).id
  const added = await request.post(`/bluebook/courses/${encodeURIComponent(course.id)}/students`, {
    headers: teacher, data: { students: [{ email: `stu-${id}@e2e.test`, name: 'Baseline Student' }] },
  })
  expect(added.status(), await added.text()).toBe(200)
  const invite = new URL((await added.json()).students[0].invite_path, 'http://x').searchParams.get('invite')
  const redeemed = await request.post('/auth/invite/redeem', { data: { token: invite, password: 'e2e-passw0rd!' } })
  expect(redeemed.status(), await redeemed.text()).toBe(200)
  const student = await redeemed.json()
  const asStudent = { Authorization: `Bearer ${student.token}` }
  await request.post(`/bluebook/me/exams/${encodeURIComponent(examId)}/start`, { headers: asStudent })
  const sealed = await request.post('/bluebook/submissions', {
    headers: asStudent,
    data: {
      exam_id: examId, student_id: student.student_id, candidate: 'Baseline Student',
      word_count: 60, text: ANSWER, answers: [ANSWER], submission_uuid: `uuid-${id}`,
    },
  })
  expect(sealed.status(), await sealed.text()).toBe(201)
  return { tenant, staff, examTitle }
}

async function teacherPage(browser, baseURL, { tenant, staff }, products) {
  const ctx = await browser.newContext({
    storageState: staffStorageState(baseURL, { token: staff.token, role: 'professor', tenant_id: tenant.tenant_id }),
  })
  const page = await ctx.newPage()
  await page.addInitScript(p => localStorage.setItem('original_products', JSON.stringify(p)), products)
  return { ctx, page }
}

async function openExam(page, examTitle) {
  await page.goto('/bluebook/')
  await page.getByRole('button', { name: 'Examinations' }).first().click()
  await page.getByRole('button', { name: examTitle }).click()
}

test('a professor adds, removes and bulk-adds sealed exams as baselines', async ({ browser, request, baseURL }) => {
  test.setTimeout(90_000)
  const ws = await sealedExam(request, {})  // fixture tenants hold both products
  const { ctx, page } = await teacherPage(browser, baseURL, ws, ['bluebook', 'original'])

  await openExam(page, ws.examTitle)
  await page.getByRole('button', { name: 'Read & mark' }).first().click()
  await expect(page.getByText('Not in baseline')).toBeVisible()
  await page.getByRole('button', { name: 'Add to baseline' }).click()
  await expect(page.getByText("Added to Baseline Student's baseline.")).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('In baseline', { exact: true })).toBeVisible()

  page.once('dialog', d => d.accept())
  await page.getByRole('button', { name: 'Remove from baseline' }).click()
  await expect(page.getByText("Removed from Baseline Student's baseline.")).toBeVisible({ timeout: 30_000 })

  page.once('dialog', d => d.accept())
  await page.getByRole('button', { name: 'Add all sealed submissions to baselines' }).click()
  await expect(page.getByText('1 added · 0 already in baseline · 0 held for review.')).toBeVisible({ timeout: 30_000 })
  await ctx.close()
})

test('a Bluebook-only workspace sees no baseline controls', async ({ browser, request, baseURL }) => {
  const ws = await sealedExam(request, { products: ['bluebook'] })
  const { ctx, page } = await teacherPage(browser, baseURL, ws, ['bluebook'])

  await openExam(page, ws.examTitle)
  await page.getByRole('button', { name: 'Read & mark' }).first().click()
  await expect(page.getByText('Save mark and feedback')).toBeVisible()
  await expect(page.getByText('Writing baseline')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Add all sealed submissions to baselines' })).toHaveCount(0)
  await ctx.close()
})
```

If a locator does not match the real UI (button names in the teacher navigation or exam list), read the rendered page (`page.content()` or a trace) and use the actual accessible name. Do not loosen what is asserted.

- [ ] **Step 6: Run the browser specs against your own pilot-mode server**

Start the server as in Task 4, Step 4 (port 8771, fresh scratch DB). Run: `cd demo/bluebook && PLAYWRIGHT_BASE_URL=http://localhost:8771 SECRET_KEY=ci-test-only-secret-do-not-deploy MAINTENANCE_TOKEN=ci-test-only npx playwright test e2e/baseline-approval.spec.mjs e2e/professor-journey.spec.mjs e2e/a11y.spec.mjs`
Expected: all pass. Stop the server.

- [ ] **Step 7: Commit**

```bash
git add demo/bluebook/components.jsx demo/bluebook/Teacher.jsx demo/bluebook/*.bundle.* demo/bluebook/unit/baselines.test.mjs demo/bluebook/e2e/baseline-approval.spec.mjs
git commit -m "Add professor controls for approving writing baselines

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Docs and full verification

**Files:**
- Modify: `docs/BLUEBOOK_LAUNCH_CHECKLIST.md` ("Operating it")
- Modify: `docs/data_inventory.md`
- Modify: `docs/release/VERIFICATION_AND_BLOCKERS.md`
- Modify: `docs/superpowers/specs/2026-10-05-baseline-approval-design.md` (bulk `errors` count)

- [ ] **Step 1: Write the docs**

`docs/BLUEBOOK_LAUNCH_CHECKLIST.md`, under "Operating it", after the "Switching Original for a professor" item:

```markdown
- **Approving exams as writing baselines** (workspaces with Original only):
  sealing an exam never adds it to a student's baseline. In the submission
  reader, **Add to baseline** / **Remove from baseline** handles one exam; on an
  examination's page, **Add all sealed submissions to baselines** handles the
  rest. An exam that differs strongly from the student's existing samples is
  held for review rather than added; approval never overrides that check.
```

`docs/data_inventory.md`: in the section describing Original baseline samples (`grep -n "baseline" docs/data_inventory.md`), add one sentence: sealed Bluebook exams enter a student's Original baseline only when a professor approves them (per exam or per examination), and can be removed; approvals and removals are audit-logged without student text.

`docs/release/VERIFICATION_AND_BLOCKERS.md`: under "Still open (owner/operator, Part B)", add: `B2 (counsel): the student notice should say that sealed exams may be used as reference writing if the instructor's workspace uses Original (professor-approved baselines, 2026-10-05).`

In the spec's bulk bullet, add `"errors": n` to the returned counts and one clause: any other failure for a submission is reported as status `error` without stopping the batch.

- [ ] **Step 2: Full CI command with Postgres** (check `uptime` first; wait if the 1-minute load is above 24)

Run (background, ≥40-minute limit): `DATABASE_URL=postgresql://original:original@localhost:55432/original_test /Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -m "not blocker and not certification" -q --cov=original --cov-branch --cov-report=term:skip-covered --cov-fail-under=98`
Expected: 0 failed, 0 errors, coverage ≥ 98%.

- [ ] **Step 3: Known-red lane**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python scripts/known_red.py`
Expected: exit 0; only T-01 listed.

- [ ] **Step 4: Full Playwright suite** (pilot-mode server as in Task 4, Step 4)

Run: `cd demo/bluebook && PLAYWRIGHT_BASE_URL=http://localhost:8771 SECRET_KEY=ci-test-only-secret-do-not-deploy MAINTENANCE_TOKEN=ci-test-only npx playwright test --grep-invert "@serial-lockout"`
Expected: all pass. Stop the server.

- [ ] **Step 5: Commit**

```bash
git add docs/BLUEBOOK_LAUNCH_CHECKLIST.md docs/data_inventory.md docs/release/VERIFICATION_AND_BLOCKERS.md docs/superpowers/specs/2026-10-05-baseline-approval-design.md
git commit -m "Add docs for professor-approved writing baselines

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
