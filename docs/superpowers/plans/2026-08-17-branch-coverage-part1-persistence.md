# Branch Coverage Part 1 — Persistence Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read `2026-08-17-branch-coverage-index.md` §Global Constraints first — they all apply here.

**Goal:** Close the 74 missing branches in the persistence cluster (baseline 79.67%): `original/postgres_repository.py` (44, at 70.67%), `original/store.py` (27, at 85.48%), `original/db/session.py` (2), `original/db/postgres_session.py` (1) — bringing the layer that holds student data to full reachable-branch coverage under BOTH backends.

**Architecture:** Extend the backend-parametrized contract suite (`tests/test_repository_contract.py`, `BACKENDS` fixture) wherever a gap exists in both backends — one test then closes the SQLite and Postgres twin gaps together and pins cross-backend semantic parity. Only gaps unique to one backend (exception arms, engine bootstrap) get backend-specific tests, postgres-marked where they need the container.

**Tech Stack:** pytest, `@pytest.mark.postgres`, local Postgres via `make db-up`, hypothesis (already used in the contract file).

**Baseline data:** `2026-08-17-branch-coverage-baseline.md` §persistence.

## Global Constraints (additional to the index's)

- Contract tests must express assertions ONLY through the `Repository` protocol (`original/repository.py`) — no reaching into `store._get_conn()` or SQLAlchemy sessions (that file's docstring states the rule).
- Postgres-only tests go through the existing `repo` fixture's `postgres` param or carry `@pytest.mark.postgres` and a `_postgres_available()` guard — the suite must stay green with no container.
- The twin functions must KEEP identical semantics: if a test reveals SQLite and Postgres disagree (e.g. `_status_for` edge, manifest ordering), that is a real bug to fix in the code, not to encode per-backend in the test.

## Measured gap tables (2026-08-17)

`original/postgres_repository.py` — 44 missing:

| Function | Missing/Total branches |
|---|---|
| `roster_for_tenant` | 6/6 |
| `_status_for` | 6/6 |
| `put_correction` | 4/12 |
| `get_fused_scores` | 4/4 |
| `manifest_stats` | 3/10 |
| `delete_student` | 3/8 |
| `set_display_name` | 2/2 |
| `put_manifest` | 2/4 |
| `list_manifests` | 2/12 |
| `list_calibration_runs` | 2/4 |
| `get_ai_likelihood_scores` | 2/2 |
| `student_data_inventory` | 1/4 |

`original/store.py` — 27 missing: `_init_schema` 4/8, `student_data_inventory` 3/6, `put_correction` 3/12, `manifest_stats` 3/10, `_status_for` 3/6, `_latest_actions_for` 3/6, `list_manifests` 2/12, `set_display_name` 1/2, `put_manifest` 1/4, `get_fused_scores` 1/4, `delete_tenant_students` 1/4, `delete_student` 1/6.

`original/db/session.py` — `get_engine` 2/2. `original/db/postgres_session.py` — `get_engine` 1/4.

---

### Task 1: Roster status — the twin `roster_for_tenant`/`_status_for` gap (worked example)

**Files:**
- Modify: `tests/test_repository_contract.py` (append a `TestRosterStatus` class)

**Interfaces:**
- Consumes: the file's existing `repo` fixture (parametrized sqlite/postgres), `_make_state(student_id, n)`, `_seed_manifest(repo, submission_id, student_id, action=...)`, `repo.put(state)`, `repo.set_display_name`, `repo.roster_for_tenant(tenant_id)`.
- Produces: nothing later tasks depend on; the class name `TestRosterStatus` is referenced by Task 6's verification run.

Both backends' `_status_for(sample_count, action)` ladders (`postgres_repository.py:436-443`; `store.py`'s twin) measure 0% and 50% branch respectively, and `roster_for_tenant` (`postgres_repository.py:445-491`) has never run under Postgres tests. The status ladder is instructor-facing triage state — every rung deserves a pin.

- [ ] **Step 1: Write the failing tests**

```python
# ── Roster + status ladder (WS-6 P1 gap closure, branch-coverage part 1) ──────


class TestRosterStatus:
    def test_status_ladder_reflects_latest_action(self, repo):
        # Ladder: 0 samples → no_baseline; escalate/schedule_conversation →
        # needs_review; monitor → monitor; anything else → clear.
        repo.put(_make_state("sem:zero", n=0))
        repo.put(_make_state("sem:esc", n=2))
        _seed_manifest(repo, "sub-r1", "sem:esc", action="monitor")
        _seed_manifest(repo, "sub-r2", "sem:esc", action="escalate")  # last write wins
        repo.put(_make_state("sem:conv", n=1))
        _seed_manifest(repo, "sub-r3", "sem:conv", action="schedule_conversation")
        repo.put(_make_state("sem:mon", n=1))
        _seed_manifest(repo, "sub-r4", "sem:mon", action="monitor")
        repo.put(_make_state("sem:clean", n=1))
        _seed_manifest(repo, "sub-r5", "sem:clean", action="no_action")
        repo.put(_make_state("sem:unscored", n=1))  # no manifest at all

        roster = {r["id"]: r for r in repo.roster_for_tenant("sem")}
        assert roster["sem:zero"]["status"] == "no_baseline"
        assert roster["sem:esc"]["status"] == "needs_review"
        assert roster["sem:conv"]["status"] == "needs_review"
        assert roster["sem:mon"]["status"] == "monitor"
        assert roster["sem:clean"]["status"] == "clear"
        assert roster["sem:unscored"]["status"] == "clear"

    def test_roster_names_counts_and_scoping(self, repo):
        state = _make_state("sem:named", n=3)
        repo.put(state)
        repo.set_display_name("sem:named", "Alice Example")
        repo.put(_make_state("sem:anon", n=1))
        repo.put(_make_state("other:outsider", n=1))  # different tenant

        roster = {r["id"]: r for r in repo.roster_for_tenant("sem")}
        assert set(roster) == {"sem:named", "sem:anon"}
        assert roster["sem:named"]["name"] == "Alice Example"
        assert roster["sem:named"]["has_name"] is True
        assert roster["sem:anon"]["has_name"] is False
        assert roster["sem:anon"]["name"].startswith("Student ")
        assert roster["sem:named"]["sample_count"] == 3
        assert roster["sem:named"]["authenticated_count"] == 3  # instructor_verified
```

- [ ] **Step 2: Run against both backends and verify failure/collection**

Run: `make db-up && DATABASE_URL=$(bash scripts/local_postgres.sh url) .venv/bin/python -m pytest tests/test_repository_contract.py -k RosterStatus -q`
Expected: 4 items collected (2 tests × 2 backends). They should PASS immediately if the twin implementations are correct — the point is branch closure, so "failing test first" here means: if any assertion fails, you have found a real backend divergence; STOP and fix the implementation, not the test.

- [ ] **Step 3: Verify the branches closed**

Run:

```bash
DATABASE_URL=$(bash scripts/local_postgres.sh url) .venv/bin/python -m pytest \
  tests/test_repository_contract.py -q --cov=original.postgres_repository \
  --cov-branch --cov-report=term-missing 2>&1 | grep -A3 "postgres_repository"
```

Expected: `roster_for_tenant` / `_status_for` lines no longer among the missing; module branch % materially above 70.67.

- [ ] **Step 4: Commit**

```bash
git add tests/test_repository_contract.py
git commit -m "Add roster status-ladder contract tests closing the twin roster_for_tenant branch gaps"
```

---

### Task 2: Manifest read-model gaps (`put_manifest`, `list_manifests`, `manifest_stats`, `list_calibration_runs`)

**Files:**
- Modify: `tests/test_repository_contract.py`

- [ ] **Step 1: Extract the exact untaken arms** using the index's per-module extraction snippet for `original/postgres_repository.py` and `original/store.py`, filtered to lines within these four functions (get each function's line range from the same JSON's `functions` keys).

- [ ] **Step 2: Write contract tests, one behavior per untaken arm.** Expected arms from the digest (verify against Step 1's output; write one test per bullet, in the idiom of Task 1):
  - `put_manifest` upsert arm: same `submission_id` written twice → second write wins, no duplicate row in `list_manifests`.
  - `list_manifests` filter arms never exercised together: `student_id=None` vs set, `since`/`until` boundary inclusion, empty result set.
  - `manifest_stats` with zero manifests (empty-store denominator arm) and with a `since` cutoff that excludes everything.
  - `list_calibration_runs` on an empty store, and after two runs (ordering arm).

- [ ] **Step 3: Verify** with the Task 1 Step 3 command; the four functions must disappear from term-missing for both modules (store.py run: swap `--cov=original.store`).

- [ ] **Step 4: Commit** — `git commit -m "Add manifest read-model contract tests for upsert, filter, and empty-store branches"`

---

### Task 3: Deletion + inventory + corrections (`delete_student`, `delete_tenant_students`, `student_data_inventory`, `put_correction`, `set_display_name`, `get_fused_scores`, `get_ai_likelihood_scores`)

**Files:**
- Modify: `tests/test_repository_contract.py`

- [ ] **Step 1: Extract exact arms** (same procedure as Task 2 Step 1).

- [ ] **Step 2: Write contract tests.** Expected arms from the digest (verify first):
  - `delete_student` on an id that does not exist → `False`, and on an id with manifests + display name + fused scores → `True` and every associated read (`student_data_inventory`, `roster_for_tenant`, `get_fused_scores`) reflects the removal. FERPA-relevant: assert NOTHING of the student survives.
  - `delete_tenant_students` with an empty tenant (zero-ids arm).
  - `student_data_inventory` for a student with no manifests vs with manifests; unknown student → `None`.
  - `put_correction` overwrite arm (same key twice) and the optional-field-absent arms.
  - `set_display_name` twice (update arm) — pairs with Task 1's set-once coverage.
  - `get_fused_scores` / `get_ai_likelihood_scores` empty vs populated.

- [ ] **Step 3: Verify + commit** — `git commit -m "Add deletion, inventory, and correction contract tests for both persistence backends"`

---

### Task 4: Backend-specific arms — exception guards and engine bootstrap

**Files:**
- Create: `tests/test_persistence_error_arms.py`

The remaining arms are not expressible through the contract protocol:

- [ ] **Step 1: Postgres exception guards.** `roster_for_tenant`'s `except Exception → []` (`postgres_repository.py:489-491`) and the equivalent guards in the functions from Tasks 2-3. Monkeypatch the session factory to raise:

```python
import pytest

from original import postgres_repository


@pytest.mark.postgres
def test_roster_for_tenant_returns_empty_on_session_failure(monkeypatch):
    def _boom():
        raise RuntimeError("simulated connection failure")

    monkeypatch.setattr(postgres_repository, "session_scope", _boom)
    assert postgres_repository.PostgresRepository().roster_for_tenant("sem") == []
```

(One test per guarded function; same shape. These are postgres-marked only because the module is; no live container is actually needed once the session factory is stubbed — if import-time engine construction fires without `DATABASE_URL`, keep the marker and the container.)

- [ ] **Step 2: `db/session.py` + `db/postgres_session.py` `get_engine` arms** — cached-engine-reuse and the URL-scheme branches. Call `reset_engine()` then `get_engine()` twice under a sqlite URL (via `monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")`) asserting the second call returns the same object; then the postgresql-scheme arm under the container URL (postgres-marked).

- [ ] **Step 3: `store.py:_init_schema` migration arms** — the digest shows 4/8 missing: these are the ALTER-TABLE-if-column-absent upgrade paths. Create a store DB file with an OLD schema (create the table without the newer columns using the store's own public API is impossible — this is the one sanctioned raw-SQL exception, documented in the test), then trigger `_init_schema` and assert the columns exist and data survived. Read `store.py:_init_schema` first and pin each conditional migration arm.

- [ ] **Step 4: Verify + commit** — `git commit -m "Add backend-specific error-arm and schema-migration branch tests"`

---

### Task 5: Sweep the residue to zero-or-annotated

- [ ] **Step 1:** Re-run the full measurement (index §Global Constraints) and re-extract the persistence cluster: `.venv/bin/python scripts/branch_coverage_report.py coverage.json --cluster persistence`.
- [ ] **Step 2:** For every remaining missing branch: write the covering test (Tasks 1-4 idioms) or, if genuinely unreachable, annotate `# pragma: no cover` with a one-line argument. Expected annotation candidates: broad `except Exception` guards around bulk reads that Task 4 could not stub without violating the contract-purity rule.
- [ ] **Step 3:** Also drain the cluster's PARTIAL branches (`num_partial_branches` per file in the JSON) — conditions where only one arm ever ran get the other arm's test now, same idioms.
- [ ] **Step 4: Commit** — `git commit -m "Close remaining persistence branch gaps and annotate the argued-unreachable guards"`

### Task 6: Part completion — re-measure, ratchet, dashboard

- [ ] **Step 1:** Full-suite re-measure (14 min; background it). Suite must be 0 failed.
- [ ] **Step 2:** Record the new persistence-cluster % and totals; update the Status row for Part 1 in `2026-08-17-branch-coverage-index.md` to `done @ <measured %>`.
- [ ] **Step 3:** Apply the index's CI ratchet step for Part 1: add `--cov-branch` to `.github/workflows/test.yml`'s pytest invocation (keep `--cov-fail-under=78`).
- [ ] **Step 4: Commit** — `git commit -m "Record part 1 persistence branch-coverage completion and switch CI coverage to branch mode"`

## Self-Review Notes

- Task 1's code was written against the contract file's actual helpers (`repo.put`, `_make_state`, `_seed_manifest` — verified 2026-08-17); `_make_state("sem:zero", n=0)` produces an empty-samples profile, which is what the `no_baseline` rung needs.
- Task 4 Step 1's monkeypatch target (`postgres_repository.session_scope`) matches the import style seen at `postgres_repository.py:447`; adjust the attribute name if the module imports it differently.
- If any cross-backend assertion diverges, the fix belongs in the implementation — the contract suite exists precisely so a dialect bug shows up once (file docstring).
