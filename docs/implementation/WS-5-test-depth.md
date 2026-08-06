# WS-5 — Test depth: unit/API

> Part of the [Master Implementation Plan](../AUDIT_2026-07-06.md) (Audit §9). Refs are a 2026-07-07 snapshot — resolve each cited `path:line` by its **named symbol** via [ANCHORS.md](ANCHORS.md); the tree is under active edit and line numbers drift.
> **Findings:** T1, T2, T3, T4, T5, T6, T10 · **Effort:** 4–6 days · **Depends on:** WS-2 (CI coverage gate + shared fixtures) · **Unblocks:** a trustworthy `--cov-fail-under` floor so WS-6/WS-7 refactors can't silently regress the live pilot backend, and the shared live-app fixture every future live-stack test reuses.

## Objective
Raise real test execution over the **live** pilot stack (`api.py` 61%, `store.py` 73%) so the code the pilot actually runs — Bluebook sealed-exam CRUD, flag-gated production scoring, FERPA persistence — is verified, then lock it in with a ratcheted coverage gate. Today the well-tested paths are the *default* scoring core and tenant isolation; the gaps are precisely the opt-in features a configured deployment ships and the sealed-evidence write path. "Done" = coverage ≥78% overall, `api.py` ≥75%, `store.py` ≥85%, with `--cov-fail-under` set to match, and the dormant v1 tests renamed so contributors stop landing new tests in the wrong stack.

## Prerequisites & dependencies
- **WS-2 must land first (or concurrently).** WS-2 step 4 adds `--cov=original --cov-fail-under=70` to CI and registers the `slow` marker; WS-2 step 1 removes the Finder-duplicate test files. WS-5 raises that floor as tasks land — do not add a second coverage invocation.
- **Shared fixture (§9 WS-5.1) is the gate for T1/T3.** The live-app `TestClient` pattern (`run.load_legacy_demo_app()` + monkeypatched `original.store` globals) is currently copy-pasted across 9 files (`test_pilot_lockdown.py:32`, `test_tenant_isolation.py:19`, `test_null_model.py:27`, `test_lti.py`, `test_staff_auth.py`, `test_readiness.py`, `test_voice_leak.py`, `test_ai_likelihood*.py`). Factor it once so new live-stack tests are the low-friction default. This fixture is the S3 mitigation noted in §9.
- **Shared findings with WS-6 (Postgres):** T4 and T6 overlap WS-6 Phase 6, which deletes the entire v1 API surface and its ~62 tests. **WS-5 owns only the interim slice:** rename `test_api.py` → `test_v1_api_dormant.py` (a signpost, not a deletion) and delete the two provably-dead modules (`middleware/rbac.py`, `tasks/scoring.py`). **WS-6 owns the final deletion** of `original/main.py`, `conftest.py`'s v1 fixtures, and `test_v1_api_dormant.py`/`test_auth.py`/`test_canvas.py`. Do not delete the v1 app or its `conftest.py` fixtures here — other dormant-stack tests still import them.
- F4 (delete `tasks/scoring.py`) is folded into T6 here per §9 WS-5.5.

## Tasks

### 5.1 Shared live-app fixture in `conftest.py` — T4 (prereq), S3
- **Current state:** `tests/conftest.py:32` does `from original.main import app` — every fixture (`db`, `client`, `admin_user`, …) targets the **dormant v1 SQLAlchemy stack**. The live app has no shared fixture; each of the 9 files above re-derives `app = run.load_legacy_demo_app()` + `client = TestClient(app)` + `api_mod = sys.modules["original._legacy_demo_api"]` at module scope.
- **Change:** add live-stack fixtures **without touching the existing v1 fixtures** (they stay until WS-6 deletes them). Add a `live_app`/`live_client` fixture and a `store_reset` helper that snapshots/restores `original.store` in-memory globals so tests don't leak state. Put them in `conftest.py` (session-scoped app, function-scoped client) so `test_bluebook_api.py` and the T3 store tests consume them.
- **Files touched:** `tests/conftest.py`.
- **Verify:** `.venv/bin/python -m pytest tests/test_pilot_lockdown.py -q` still green after the affected files switch to the shared fixture; `grep -c "load_legacy_demo_app" tests/conftest.py` == 1.

### 5.2 Live Bluebook API + `store` coverage — T1, T3
- **Current state (T1):** Bluebook endpoints are live and near-uncovered — `api.py:623` `POST /bluebook/exams`, `:647` `GET /bluebook/exams`, `:659` `GET /bluebook/exams/{exam_id}`, `:673` `POST /bluebook/submissions`, `:702` `GET /bluebook/submissions`; tenant is derived in `_bluebook_tenant()` (`api.py:609`). Their only exercise is the Playwright job (2 endpoints). Also uncovered: `lifespan` (`api.py:117`) with its fail-closed guard `raise RuntimeError(...)` at `:123` when `ORIGINAL_ENV` is a real deploy (`_IS_REAL_DEPLOY`, `:114`) and no stable `SECRET_KEY`.
- **Current state (T3):** `store.py:1653-1813` is the entire Bluebook persistence layer — `put_bluebook_exam` (`:1653`), `get_bluebook_exam` (`:1679`), `list_bluebook_exams` (`:1694`), `put_bluebook_submission` (`:1730`), `list_bluebook_submissions` (`:1750`), `put_bluebook_course` (`:1778`), `list_bluebook_courses` (`:1797`). Sealed-exam evidence is written by code no unit test executes. (Note: there is **no** `get_bluebook_submission` — retrieval is list-only; test via `list_*` filtered by tenant.)
- **Change — new `tests/test_bluebook_api.py`** (live fixture from 5.1, pattern per `test_pilot_lockdown.py`):
  - exam create → returns 201 + id; list returns it; get by id returns it; get unknown id → 404.
  - submission create → 201; list returns it.
  - **Tenant scoping:** an exam/submission written under tenant A must not appear in a list scoped to tenant B. `list_bluebook_exams(None)` (demo path) vs a pilot tenant id — assert isolation, mirroring `test_tenant_isolation.py`.
  - Error paths: malformed body (missing title) → 4xx not 500; CSV/upload-batch error branches if reachable through the live app.
  - **`lifespan` fail-closed:** unit-test that entering `lifespan` with `ORIGINAL_ENV=pilot` and empty `SECRET_KEY` raises `RuntimeError` (`monkeypatch.setenv` + `pytest.raises`); with a stable key it does not.
- **Change — new `tests/test_store_bluebook.py`** (direct `original.store` calls, in-memory DB):
  - `put_*`/`list_*`/`get_*` round-trip for exam, submission, course; **upsert semantics** (second `put` with same id replaces, does not duplicate); tenant filtering returns only the caller's rows; malformed `conditions`/JSON payload handled, not crashed.
  - **Injected-error test:** monkeypatch the store's SQLite cursor/execute to raise `sqlite3.Error` and assert the failure **surfaces** (does not get silently swallowed) — the T3/A1 concern that `except` branches hide corruption. (Coordinate with WS-1.2, which rewrites the two `except Exception: pass` blocks in `_persist`/`_load_all`; this test is the shared acceptance proof for both.)
- **Files touched:** `tests/test_bluebook_api.py` (new), `tests/test_store_bluebook.py` (new).
- **Verify:** `.venv/bin/python -m pytest tests/test_bluebook_api.py tests/test_store_bluebook.py -v`; then `--cov=original.store --cov=original.api` shows the `1653-1813` and `623-742` blocks executed.

### 5.3 Flag-matrix scoring tests — T2
- **Current state:** `quantum/scoring.py` is 80%; the misses are the opt-in production branches, all confirmed present: `_amplitude_score` internals (`:239-318`), the `AMPLITUDE_SCORING_ENABLED` branch in `score()` (`:559-579`), the `BAYESIAN_PRIOR_ENABLED` cold-start prior (`:475-495`, reads `PRIOR_WEIGHT`), and the conformal action-nudge (`:969-994`). Building blocks are unit-tested in isolation (`amplitude.py` 99%, `conformal.py` 100%, `null_pool.py` 97%) but nothing runs `score()` with the flags ON.
- **Change — new `tests/test_scoring_flags.py`**, parametrized over flag combinations via `monkeypatch.setenv`:
  - **(a) In-bounds:** for every combination, `deviation_score`, `authorship_probability`, `quantum_fidelity` ∈ [0,1] and `action` ∈ the four allowed values.
  - **(b) Flags-OFF byte-identical invariant** (the project's stated core invariant): with `AMPLITUDE_SCORING_ENABLED`/`BAYESIAN_PRIOR_ENABLED` unset and `SECRET_KEY` empty, `score()` output equals a captured Phase-1 baseline for a fixed seeded input — assert field-equality (fidelity `0.0`, conformal_p `None`, unchanged action). This is the guard that the new ON-path tests never perturb the default path.
  - **(c) Conformal escalation-only property:** run `score()` on inputs spanning both nudge directions and assert the conformal branch **only ever raises** severity, never lowers it. Verified in code (`scoring.py:978-994`): the up-nudge fires only when `_action_severity[verdict] > _action_severity[action] and action != "escalate"`; the disagreement branch (`conformal_p > 0.20 and action == "escalate"`) **only attaches a note**, never demotes. Test: for a fixed action, sweep `conformal_p` and assert `severity(result.action) >= severity(action_without_conformal)`.
- **Files touched:** `tests/test_scoring_flags.py` (new). Test-only; **no change to `scoring.py`** (invariant #4).
- **Verify:** `.venv/bin/python -m pytest tests/test_scoring_flags.py -v`; coverage of `scoring.py` reaches the `239-318`, `475-495`, `559-579`, `969-994` blocks.

### 5.4 Fix quality defects in `tests/test_quantum.py` — T5
- **Current state:** docstring (`:1-5`) and import (`:9`, `from hypothesis import given, strategies as st`) claim Hypothesis, but there are **zero** `@given` decorators. `test_empty_state` (`:189-199`) is `try/except Exception: pass` with no assertion — it can never fail. `test_authorship_probability_reciprocal_deviation` (`:160-183`) claims an inverse relationship but only asserts both values ∈ [0,1]. `create_random_vector()` (`:16-19`) uses unseeded `np.random.uniform` behind threshold assertions — latent flakiness.
- **Change:**
  - Either add a genuine `@given` property (e.g. purity/trace bounds over strategy-generated vectors) **or** drop the `hypothesis` import and fix the module docstring to stop over-claiming. Prefer adding one real property so the docstring becomes true.
  - Replace `test_empty_state` with an explicit assertion of the actual contract: `with pytest.raises(<the real InsufficientBaseline exception>): score(...)` (confirm the exception type from `quantum/state.py`/`scoring.py`).
  - Give the reciprocal test a real invariant (construct a near-baseline submission → low deviation/high prob and a far one → the reverse; assert the ordering), or rename it to what it actually checks.
  - Seed the RNG (`np.random.seed(...)` / `np.random.default_rng(seed)`) so threshold assertions are deterministic.
  - (Adjacent, note-only per scope: `test_features.py` docstrings say "34 features" vs `FEATURE_DIM=103`. Not in T5's task list — leave to a docs sweep; do not expand this task.)
- **Files touched:** `tests/test_quantum.py`.
- **Verify:** `.venv/bin/python -m pytest tests/test_quantum.py -v`; `grep -c "@given" tests/test_quantum.py` matches the import (both >0, or both absent); run twice to confirm the seeded tests are stable.

### 5.5 Delete dead modules; decide the v1 deletion CLI — T6 (also F4)
- **Current state:** `middleware/rbac.py` (79 stmts, 0%) and `tasks/scoring.py` (71 stmts, 0%) have **no Python importer**. The only reference is `original/cli/security_audit.py:233-243` (`check_rbac_middleware`), which does a **filesystem existence check** (`rbac_file.exists()`), not an import — deleting `rbac.py` will make that check fail. `cli/delete_student.py` (101 stmts, v1 FERPA deletion CLI with `--force`) is 0% and unverified against a real DB.
- **Change:**
  - `git rm original/middleware/rbac.py original/tasks/scoring.py` (deletion requires permission per CLAUDE.md — use `git rm`, not `rm`).
  - **Update `original/cli/security_audit.py`:** remove/repoint `check_rbac_middleware()` (`:233-243`) and its call site (`:385`) so the audit doesn't assert a now-deleted file. (`security_audit.py` is itself 0% and slated for WS-6 review, but it must not reference a deleted path in the interim.)
  - `cli/delete_student.py`: per §9, **either** add a focused test for `delete_student_data()` **or** add a module header stating the live FERPA deletion path is the API endpoint (the one `test_pilot_lockdown.py` already proves purges name + audit history), not this v1 CLI. Given WS-6 deletes the v1 stack, the header-redirect is the lower-cost choice; note the decision inline.
- **Files touched:** `original/middleware/rbac.py` (deleted), `original/tasks/scoring.py` (deleted), `original/cli/security_audit.py` (edited), `original/cli/delete_student.py` (header or new test).
- **Verify:** `grep -rn "rbac\|tasks.scoring\|tasks/scoring" original/ --include='*.py'` returns no live importer; full suite green: `.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q`.

### 5.6 Stubbed sentence-transformers test for tier10; rename dormant v1 tests — T10, T4
- **Current state (T10):** `features/tier10.py` is 60%; the missed lines are the `SentenceTransformer("all-MiniLM-L6-v2")` backend (`_get_st_model`, `:57-71`; `SentenceTransformer(...)` at `:66`). Only the TF-IDF backend (`_tfidf_encode`, `:75`) runs in the test env. If production has torch, scoring flows through unrun code — a determinism risk for the 103-dim vector.
- **Current state (T4):** `tests/test_api.py` (26 tests, incl. the 5 rate-limit `xfail` `TestAuthEndpoints` at `:89-154`) and `tests/test_canvas.py` hit `/api/v1/*` on the dormant v1 app. The name inverts reality — a contributor "adding an API test" lands in the wrong stack.
- **Change:**
  - **New `tests/test_tier10_st_backend.py`:** stub a fake `sentence_transformers` module into `sys.modules` (a `SentenceTransformer` class whose `.encode()` returns a fixed deterministic array), force `_st_model` re-init, run `extract_tier10_*`/`compute_tier10_comparison`, and assert outputs are **bounded** and **deterministic** across two calls, and that the backend-choice log line fires. Pairs with the existing `validation/test_tier10_optional.py`.
  - **Rename** `tests/test_api.py` → `tests/test_v1_api_dormant.py` (`git mv`); add a one-line module docstring: "Dormant v1 API surface — retained until WS-6 Phase 6 deletes the v1 stack. New live-stack API tests belong in `test_bluebook_api.py` / the live fixture." This is an **interim signpost only**; WS-6 deletes the file.
- **Files touched:** `tests/test_tier10_st_backend.py` (new), `tests/test_api.py` → `tests/test_v1_api_dormant.py` (renamed).
- **Verify:** `.venv/bin/python -m pytest tests/test_tier10_st_backend.py -v`; `.venv/bin/python -m pytest tests/test_v1_api_dormant.py -q` still collects the 26 tests (xfails still XPASS); no import references the old `test_api` name.

## Acceptance criteria
> Verified against the working tree 2026-07-09.
- [ ] **Coverage ≥78% overall**, `original/api.py` **≥75%**, `original/store.py` **≥85%** (from 61%/73%), measured by `.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py --cov=original --cov-report=term-missing`. — NOT DONE: measured **74% overall / 68% api.py / 80% store.py** — real progress over the 61%/73% baseline, but short of all three targets.
- [ ] `--cov-fail-under` in CI **ratcheted** from WS-2's floor (70) up to **78**; CI goes red if coverage drops below it. — NOT DONE: CI currently sets `--cov-fail-under=72` (already ratcheted once from 70, but not yet to 78 — consistent with coverage not yet reaching 78%).
- [x] `test_bluebook_api.py` executes `api.py:623-742` (Bluebook CRUD) and the `lifespan` fail-closed guard (`:117-135`); tenant-scoping assertion present. — DONE.
- [x] `test_store_bluebook.py` executes `store.py:1653-1813`; one injected-`sqlite3.Error` test proves a write failure surfaces (shared with WS-1.2). — DONE (three separate `pytest.raises(sqlite3.Error)` tests, not just one).
- [x] `test_scoring_flags.py` runs `score()` under each flag combination; **flags-OFF output is byte-identical to the captured Phase-1 baseline**; the conformal-nudge escalation-only property holds. — DONE, all three sub-properties present and passing.
- [x] `test_quantum.py`: `@given` count matches the Hypothesis import (both present or both removed); `test_empty_state` has a real `pytest.raises`; RNG seeded. — DONE, with one deliberate deviation from the doc's literal suggestion: `test_empty_state` asserts the real contract (does not raise) rather than `pytest.raises`, since that's what the actual code does — a justified correction, not a gap.
- [x] `middleware/rbac.py` and `tasks/scoring.py` deleted; `cli/security_audit.py` no longer references the deleted `rbac.py`; `cli/delete_student.py` tested or header-redirected. — DONE.
- [x] `test_api.py` renamed to `test_v1_api_dormant.py`; `tier10` ST backend test green. — DONE.
- [x] Full suite clean: `0 failed` (the 5 `TestAuthEndpoints` xfails remain XFAIL/XPASS, never failures). — DONE: confirmed 0 failed, 5 xpassed.

## Risks & watch-outs
- **Flags-OFF byte-identical invariant (core project invariant):** 5.3 tests near `score()`. Assert against a *captured* Phase-1 baseline, never regenerate the baseline from the flags-ON path. Any test that would require changing `scoring.py` default behavior is out of scope — the task is tests only.
- **Store global state leakage:** the live app holds `original.store` in-memory caches at module scope; without the 5.1 `store_reset` fixture, `test_bluebook_api.py` will bleed rows across tests and produce order-dependent passes. Snapshot/restore, don't mutate blindly.
- **Rate-limit exhaustion:** the 5 `TestAuthEndpoints` xfails 429 under full-suite load. New live-app tests that hit auth-adjacent endpoints can *also* trip the limiter — scope them to Bluebook/scoring paths, or reset the limiter in the fixture, so they don't add new flakiness.
- **Deleting `rbac.py` breaks `security_audit.py`:** the filesystem existence check at `:233-243` is not caught by import-graph tools. Must edit `security_audit.py` in the same commit as the delete, or CI's audit step fails.
- **Ordering trap with WS-6:** do **not** delete `original/main.py`, the v1 `conftest.py` fixtures, or `test_v1_api_dormant.py`/`test_auth.py`/`test_canvas.py` here — WS-6 Phase 6 owns that. Other dormant-stack tests still import the v1 app; premature deletion breaks collection.
- **`get_bluebook_submission` does not exist:** submission retrieval is list-only (`list_bluebook_submissions`). Don't write a test against a non-existent single-get endpoint.

## Sequencing within the workstream
1. **5.1 shared fixture** — foundational; independently shippable. Migrate one file (`test_pilot_lockdown.py`) to it as proof, leave the rest for later cleanup.
2. **5.4 test_quantum fixes** and **5.5 dead-module deletion** — independent, small, ship early (5.5 lifts coverage denominator by removing 150 uncovered stmts).
3. **5.3 flag-matrix scoring** — independent of the fixture; lands the biggest correctness gain (T2, the flag-gated production paths).
4. **5.2 Bluebook API + store** — depends on 5.1; the largest coverage mover for `api.py`/`store.py`. Land the store tests (5.2b) and API tests (5.2a) together so the injected-error test lands with WS-1.2.
5. **5.6 tier10 + rename** — independent; do the rename last so it doesn't churn diffs while other test files are moving. Must land together with the CI ratchet.
6. **Ratchet `--cov-fail-under` to 78** — the final step, only after 1–5 are green, so the floor reflects the new reality.
