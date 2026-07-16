# WS-6 — Postgres convergence

> Part of the [Master Implementation Plan](../AUDIT_2026-07-06.md) (Audit §9). Refs are a 2026-07-07 snapshot — resolve each cited `path:line` by its **named symbol** via [ANCHORS.md](ANCHORS.md); the tree is under active edit and line numbers drift.
> **Findings:** A3, A4, A5, A8, A9, F1, F4, F6, B15, B19, T4, T6, S2, S3, part of S4 · **Effort:** 6–9 weeks part-time · **Depends on:** WS-1, WS-2 · **Unblocks:** `--workers N` / Render horizontal scaling, deletion of ~7,700 LOC dormant v1 + 62 CI tests, a real migration story (alembic), and the ADR-002 convergence deadline.

This is a **wrapper workstream**. The detailed design lives in **Audit §10 "Postgres convergence plan"** (lines 609–653): the scope decision, the measured current state, Phases P0–P6, per-phase design decisions, and the risk/mitigation table. **Read §10 first.** This file is the *execution checklist* — it adds owners, entry gates, decision gates, the acceptance/contract-test proof for each phase, and rollback posture. It does **not** re-derive §10; where you need the fine detail, follow the §10 pointer.

## Objective
Move the live pilot backend's persistence from process-local SQLite (`original/store.py`) to Postgres **through the existing Repository seam** (ADR-002), promoting the dormant v1 stack's *infrastructure* (SQLAlchemy models, alembic, pydantic `Settings`) while **deleting its API surface**. "Done" = every `store.*` call in `api.py` routes through a `Repository`; a `PostgresRepository` passes the same contract suite as `SqliteRepository` on both backends in CI; pilot data is migrated with checksums; and the v1 package + its 62 tests + the `run.py` importlib hack are gone. The single most important outcome: **tenant isolation stops being a string-prefix convention and becomes a database constraint** (P2).

## Prerequisites & dependencies
- **WS-1 must land first** (security & data-integrity hotfixes). `store.py`'s `except Exception: pass` blocks (A1) get replaced with log-and-raise there; migrating on top of silent-swallow persistence would hide corruption during P4.
- **WS-2 must land first** (guardrails). P3 needs the CI shape WS-2 builds — coverage gate, service-container support, pinned actions — to run the contract suite against a `postgres:16` container. `.venv` on Python 3.11 (B7) is assumed; the current `.venv` is 3.9.
- **HARD ORDERING — WS-7 step 1 is a prerequisite for P0.** `ScoringConfig` + genre-stats-as-parameter (findings A5, part-S4, A7) must land before `PostgresRepository` work begins. `quantum/scoring.py` reaches persistence directly via two call-time imports — `from ..store import get_authentic_fidelities` (`scoring.py:310`) and `from ..store import get_genre_stats` (`scoring.py:478`). Until the caller fetches those and passes them in, the scoring layer holds a live edge to the store that the migration would otherwise have to port. `ScoringConfig` does not exist yet (grep-confirmed). **WS-6 P0 does not start until that edge is severed.**
- **WS-6 interleaves with WS-7.** WS-7's APIRouter split (step 3) and the P1 seam-widening both edit `api.py`'s call sites; sequence so they don't collide (see "Sequencing"). WS-7 owns the *route/service* shape; WS-6 owns the *persistence* shape.
- **Shared findings — which slice is WS-6's:**
  - **A4 / A8** (process-local singletons, connection churn): the *documentation-of-invariant* mitigation is WS-1/§9; the *structural fix* (demote `_STORE`, session-per-request) is **WS-6 P6 / P2** and is what actually unlocks multi-worker.
  - **S4**: the `ScoringConfig` hoist is **WS-7 step 1**; WS-6 only *consumes* it as the P0 prerequisite. Do not re-do it here.
  - **T4 / T6**: the *interim* rename (`test_api.py` → `test_v1_api_dormant.py`) and dead-module deletion belong to WS-5. WS-6 P6 performs the *final* deletion of the v1 tests and modules.
  - **B15 / F6**: quarantining stale deploy targets is a WS-2/WS-3 banner task now; WS-6 P6 *deletes or retargets* them once the converged stack is the only one.

## Current state (measured — verified against code 2026-07-07)
- `original/repository.py`: `Repository` Protocol covers exactly **9 methods** — formation ×3 (`get/open/advance_formation_pathway`), tenants ×4 (`get_tenant`, `list_tenants`, `put_tenant`, `tenant_stats`), audit ×2 (`list_audit`, `log_audit`). `PostgresRepository` raises `NotImplementedError` on **every** method (`repository.py:98–131`). `get_repository()` **always** returns `SqliteRepository` (`repository.py:153–158`, the `_REPO is None` branch is hard-wired to SQLite).
- `original/store.py`: **67 public `def`s** across **16 tables** — `student_profiles`, `student_names`, `submission_manifests`, `corrections`, `calibration_runs`, `tuned_thresholds_v2`, `fidelity_scores`, `ai_likelihood_scores`, `tenants`, `users`, `bluebook_exams`, `bluebook_submissions`, `bluebook_courses`, `audit_log`, `formation_pathways`, `baseline_requests`. **(Audit §10 cites the table as `tuned_thresholds_v`; the actual name is `tuned_thresholds_v2` — use the real name in DDL/models.)**
- `api.py` bypasses the seam **68:26** — 68 direct `store.*` calls vs 26 `_repo()` calls (grep-confirmed, matches audit). Private reaches into `store._DB_PATH` at `api.py:153, 158, **and 410**` (audit cites only 153,158 — there is a third at 410; all three must move behind a `Repository.db_info()`/`resolve_db_path()` method).
- v1 infrastructure present: `original/db/models/` has **7 model files** (`baseline, canvas, course, institution, student, user, submission`) + `db/base.py`, `db/session.py`; `original/core/config.py` has a pydantic `Settings(BaseSettings)` keyed on `ENVIRONMENT` (Literal, not the live `ORIGINAL_ENV`); `alembic/versions/` has **7 migrations** (`001`–`007`) all targeting v1 ORM models.
- `run.py` loads the live app via an importlib `spec_from_file_location` hack (`run.py:41–45`, `load_legacy_demo_app`) as `original._legacy_demo_api`, because `original/api.py` (file) is name-shadowed by `original/api/` (dormant package) — the A9 collision.
- v1 tests: `test_api.py` (26), `test_auth.py` (17), `test_canvas.py` (19) = **62 tests** importing the dormant stack via `conftest.py`'s `from original.main import app`.
- `render.yaml` has **no** `databases:` block yet (P0 adds it). `.venv` is Python 3.9 (WS-2 rebuilds on 3.11).

## Tasks (Phases P0–P6, mirroring Audit §10)

Each phase is gated. **The critical decision gate is after P1: an explicit "abort → stay on hardened SQLite" checkpoint.** ADR-004 already blesses hardened SQLite for a single-institution pilot; if P1 reveals the seam-widening is riskier or longer than budgeted, the program can stop after P1 having *only improved* the codebase (seam complete, contract tests exist, zero behavior change) and defer Postgres to Phase 2 scale. **Nothing before P5 is user-visible; P5 is the only maintenance window.**

### P0 — Decision & infrastructure — A9 (setup), A7/F3 (config), ADR-006
- **Entry gate:** WS-1 + WS-2 merged; **WS-7 step 1 (`ScoringConfig` + genre-stats-as-param) merged** — verify no `store` import remains in `quantum/scoring.py` (`grep -n "import.*store\|store\." original/quantum/scoring.py` returns only comments).
- **Deliverable:**
  1. Write **ADR-006** capturing the §10 scope decision verbatim: live API keeps routes+behavior; persistence moves to Postgres via the seam; v1 *infrastructure* (models, alembic, Settings) promoted; v1 *API surface* deleted. Include the retirement list (§10 P6) and supersession of ADR-004's "Route A". Cross-link ADR-002 (this closes its action items 3–4) and ADR-004.
  2. Provision Render Postgres, **staging first**: add a `databases:` block to `render.yaml`; create the `DATABASE_URL` secret. **Confirm the ~$7–20/mo pilot-tier cost with the product owner before spending (§10 risk row).**
  3. Promote v1's `original/core/config.py` `Settings` as the live config object; merge the dual `ORIGINAL_ENV` (deploy gate) / `ENVIRONMENT` (repo-seam) into one setting (A7/F3). This also gives the rest of the migration one place to read `DATABASE_URL`.
- **Acceptance / proof:** ADR-006 committed and linked from README's ADR index (WS-3 owns the index). `render.yaml` staging DB provisions cleanly; a throwaway `psql $DATABASE_URL` connects. `Settings` loads under `ORIGINAL_ENV=pilot` and `demo`; existing env-flag tests still green.
- **Rollback posture:** documentation + provisioning only. No production surface touched. Reversible by deleting the staging DB and reverting the `render.yaml`/`Settings` commits.

### P1 — Widen the seam (pure refactor, SQLite stays the backend) — A3, S3, T4
- **Entry gate:** P0 merged.
- **Deliverable (see §10 P1 for the aggregate grouping):**
  1. Extend the `Repository` Protocol from **9 → full coverage of the 67 store functions**, grouped by aggregate: students, baselines, scores, manifests, corrections, calibration, thresholds (`tuned_thresholds_v2`), tenants, users, bluebook, audit, roster, formation, baseline-requests, genre-stats.
  2. Mechanically route `api.py`'s **68 direct `store.*` calls** through `_repo()`. Remove the three `store._DB_PATH` private reaches (`api.py:153, 158, 410`) behind a `Repository.db_info()` / `resolve_db_path()` method — do **not** leave a bare import-time `_DB_PATH` (S3).
  3. Convert `test_store_tenants.py` (17), `test_store_fidelity.py` (28), and the new WS-5 `bluebook_*` store tests into **one parametrizable repository contract suite** that runs against *any* `Repository` implementation.
- **Files touched:** `original/repository.py`, `original/api.py`, `tests/test_store_tenants.py`, `tests/test_store_fidelity.py`, `tests/test_repository_contract.py` (new), `tests/conftest.py` (shared live-stack fixture per S3).
- **Acceptance / proof:** full suite green with **zero behavior change**; `grep -c "store\." original/api.py` shows only `SqliteRepository`-mediated access (target: `api.py` imports `store` *only* via `repository.py`); the contract suite passes against `SqliteRepository`. Byte-identical scoring invariant (flags-OFF) still holds — WS-5's flag-matrix test is the guard.
- **Rollback posture:** pure refactor on SQLite; revert is a `git revert` of the P1 commits. No data shape changed.
- **★ DECISION GATE (after P1): abort → stay on SQLite, or proceed to P2.** If seam-widening overran budget or surfaced store semantics too subtle to port safely, **stop here**. The codebase is strictly better (seam complete, contract tests, DI-clean fixtures) and the pilot runs on ADR-004 hardened SQLite. Record the abort decision in ADR-006 as a "deferred to Phase 2" amendment. Only proceed to P2 if the contract suite is green and the owner re-confirms the Postgres timeline mid-pilot.

### P2 — Schema & models — B19, A8 (session pattern), tenancy upgrade
- **Entry gate:** P1 merged **and** the decision gate cleared "proceed".
- **Deliverable (see §10 P2 for the four design decisions in full):**
  1. Model the 16 tables in SQLAlchemy 2.x. Reuse v1 models where they genuinely fit (`user`, `student`, `institution`≈`tenants`) and extend; write new models for the other ~12. Delete `canvas.py`/`course.py` v1 models unless the Canvas import path needs them.
  2. **Tenancy-as-constraint (the single biggest correctness upgrade):** replace the `"{tenant_id}:{local_id}"` string-prefix convention (`store.py:1976`, `like_prefix` scan at `store.py:2119`) with a real `tenant_id` column + FK + composite unique constraint. Provide a **compatibility shim at the repository boundary** so the API's existing ID scheme keeps working unchanged during migration.
  3. **Density matrices / vectors:** keep the existing numpy→bytes serialization targeting `BYTEA`; feature vectors + JSON blobs → `JSONB`. **Timestamps:** ISO strings → `timestamptz` at the column level, repository returns the same string shapes the API expects (no API change).
  4. **Transactions:** give `PostgresRepository` a session-per-request pattern (FastAPI dependency) — this is also the A8 connection-churn fix if backported to SQLite.
  5. **Reset alembic (B19):** archive the 7 stale v1 migrations (`001`–`007`); generate a fresh baseline migration from the new models. Alembic becomes the *live* migration story.
- **Files touched:** `original/db/models/*.py` (extend + new), `original/db/base.py`, `alembic/versions/` (archive 7, add baseline), `alembic.ini`/`alembic/env.py` (point at new metadata).
- **Acceptance / proof:** `alembic upgrade head` builds the full 16-table schema on an empty Postgres; a fresh `alembic revision --autogenerate` against the built schema produces an *empty* diff (models ⇔ migration in sync). The 28 `test_store_fidelity.py` round-trips define the serialization contract the models must satisfy. No API or store behavior changes in this phase (models are not yet wired into a live path).
- **Rollback posture:** additive — new models + migrations, no live read/write path yet. Revert is dropping the new migration files and model changes.

### P3 — PostgresRepository + parity — A3
- **Entry gate:** P2 merged; `postgres:16` service container available in CI (WS-2).
- **Deliverable (see §10 P3 for aggregate dependency order):**
  1. Implement `PostgresRepository` per aggregate in dependency order: tenants/users → students/baselines → scores/manifests → bluebook → calibration/corrections/thresholds → formation/audit/requests. Replace the `NotImplementedError` skeleton method-by-method.
  2. Run the **P1 contract suite against Postgres** in CI. **Each aggregate lands only when its contract tests pass on BOTH backends.**
  3. Property-test the round-trip: `fidelity(ρ_in, ρ_out) ≈ 1.0` for random density matrices through the Postgres path.
- **Files touched:** `original/repository.py` (`PostgresRepository`), `tests/test_repository_contract.py` (parametrize over both backends), `.github/workflows/*.yml` (postgres service container).
- **Acceptance / proof:** contract suite green against `SqliteRepository` **and** `PostgresRepository` in CI; density-matrix round-trip property passes on the PG path; `get_repository("pilot")` can return a working `PostgresRepository` (still gated off in prod until P5). `PostgresRepository` has zero remaining `NotImplementedError`.
- **Rollback posture:** `PostgresRepository` exists but `get_repository()` still returns SQLite for every environment — production untouched. Rollback = leave the flip un-flipped.

### P4 — Data migration & shadow validation — FERPA-sensitive
- **Entry gate:** P3 merged; contract suite green on both backends.
- **Deliverable (see §10 P4):**
  1. `scripts/migrate_sqlite_to_pg.py`: read via `SqliteRepository`, write via `PostgresRepository`; emit per-table row counts + content checksums as an explicit **report artifact**. **FERPA: run on the Render host or over an encrypted tunnel — no student data on laptops.**
  2. (Recommended) `REPO_SHADOW=postgres`: writes mirrored to both backends, reads from SQLite, divergences logged. Soak **1–2 weeks** of pilot traffic. The repo already has a shadow-mode culture, so this is idiomatic.
  3. Backup story: switch OPS_RUNBOOK from `backup.py` file copies to Render managed backups + nightly `pg_dump`; **rehearse a restore before cutover.**
- **Files touched:** `scripts/migrate_sqlite_to_pg.py` (new), `docs/OPS_RUNBOOK.md`, shadow-mirror hook in `repository.py` (behind `REPO_SHADOW`).
- **Acceptance / proof:** migration report shows row-count + checksum parity for all 16 tables; shadow soak logs **zero unexplained divergences** over the soak window; a restore drill from `pg_dump` succeeds on staging.
- **Rollback posture:** SQLite remains the source of truth throughout P4 (shadow reads from SQLite). Abort = stop mirroring, discard the PG copy; no pilot impact.

### P5 — Cutover (one maintenance window) — the ONLY user-visible step
- **Entry gate:** P4 report shows parity; shadow soak clean; restore drill passed; owner sign-off on the window.
- **Deliverable (see §10 P5):** freeze writes (maintenance flag) → final `migrate_sqlite_to_pg.py` sync run → flip `get_repository()` to `PostgresRepository` for the pilot env → run `PILOT_SMOKE_TEST` → unfreeze. **Keep the SQLite file read-only on disk for ≥4 weeks** as instant rollback.
- **Files touched:** `original/repository.py` (`get_repository` env switch), `render.yaml` (env), the maintenance-flag path.
- **Acceptance / proof:** `PILOT_SMOKE_TEST` passes against Postgres post-flip; `/health` reports the PG backend; a spot-check of a known student's score matches the pre-cutover value.
- **Rollback posture:** **flip the env var back to SQLite** — the read-only SQLite file is the instant rollback for ≥4 weeks. This is the whole point of keeping it. Document the exact revert command in OPS_RUNBOOK before the window opens.

### P6 — Decommission & unlock — A4, A8, F1, F4, F6, B15, T4, T6, A9
- **Entry gate:** P5 stable for ≥4 weeks (the SQLite rollback window elapsed without needing it).
- **Deliverable (see §10 P6):**
  1. Demote the in-memory `_STORE` dict (`store.py`): reads go through the repository; keep at most a bounded per-request cache (A4, A8). **This unlocks `--workers N` and Render horizontal scaling** — move the login throttle to the DB or accept per-worker limits *explicitly and documented*.
  2. Delete the v1 API surface: `original/api/`, `original/canvas/`, `original/main.py`, `original/middleware/`, `original/auth/`, `original/schemas_v1/`, **plus the 62 v1 tests** (`test_api.py`, `test_auth.py`, `test_canvas.py`, v1 fixtures in `conftest.py`) (F1, T4, T6). Also delete the confirmed-dead `original/tasks/` (F4) and `middleware/rbac.py` if WS-5 hasn't already. Use `git rm` (deletion requires explicit permission per CLAUDE.md).
  3. Deleting `original/api/` **dissolves the module-shadowing collision** — `run.py`'s importlib `spec_from_file_location` hack (`run.py:41–45`) goes away *without renaming anything* (A9). Restore a plain `import`.
  4. Delete `frontend/`, `web/`, `legacy_mvp/` (F1); update or delete `Dockerfile`/`docker-compose.yml`/`fly.toml`/`start-prod.sh`/`docker-entrypoint.sh` to target the converged stack (B15, F6). *Status 2026-07-07: `frontend/` and `web/` deleted (ADR-006; see git history); the v1 deploy artifacts are quarantined under `deploy/legacy-v1/` pending retargeting; `legacy_mvp/` is untracked and remains on disk only.*
  5. **Keep (now live):** `original/db/` models, alembic, `Settings`.
- **Files touched:** `original/store.py` (`_STORE` demotion), `run.py` (drop importlib hack), + the deletions above.
- **Acceptance / proof:** `uvicorn --workers 2` serves consistent reads across workers (no divergent `_STORE`); full test suite green after the 62 v1 tests are removed and CI no longer hard-depends on SQLAlchemy/pydantic_settings for dead code; `import original.api` resolves to the live module (collision gone); `docker compose up` runs the converged stack, not `original.main:app`.
- **Rollback posture:** deletions are the point of no return, but they land *after* the ≥4-week PG soak, so SQLite/v1 rollback is already forfeited by design. Git history preserves everything (§10). Do P6 in small commits (demote `_STORE` first, verify multi-worker, *then* delete) so any single step is revertible.

## Acceptance criteria
> Verified against the working tree 2026-07-09, re-verified 2026-07-16. P1 (seam-widening) and P2 (schema/models/alembic) have landed; P0 and P3–P6 have not started.
- [x] **ADR-006 written** and linked, capturing the scope decision + retirement list; ADR-002 action items 3–4 marked done; ADR-004 "Route A" marked superseded. — DONE except ADR-002 item 4: ADR-006 exists and is linked (README ADR index, ARCHITECTURE.md); ADR-002 item 3 (tenant/audit through the protocol) is now ticked — landed in code; item 4 (Postgres impl) correctly remains open, since `PostgresRepository` is still unimplemented; ADR-004 now carries a "partially superseded by ADR-006" note on "Route A".
- [x] **WS-7 step 1 landed before P0** — `quantum/scoring.py` has no `store` import (only `ScoringConfig` params for genre stats/fidelities). — DONE: `ScoringConfig` dataclass exists; `grep -n "os.environ\|from ..store" original/quantum/scoring.py` shows env reads only inside `ScoringConfig.from_env()`, no store import.
- [x] **Repository Protocol covers all 67 store functions**; `api.py` reaches the store *only* through a `Repository` (68 direct calls → 0; three `_DB_PATH` reaches → `db_info()`). — DONE, with a correction to this bullet's own baseline number: `original/store.py` has 68 total `def`s but only **55 are public** (13 are `_`-prefixed helpers); the `Repository` Protocol now covers all 55 public functions plus a new `db_path()` accessor (56 methods total) — not "67," which conflated total defs with public ones. `api.py`'s remaining `store.` hits are all in comments/docstrings/a test-patching import, zero live calls; the three `_DB_PATH` reaches are gone, replaced by `_repo().db_path()`. (Re-verified 2026-07-16: a newly-added store function, `submission_student_id`, briefly landed without Protocol coverage — breaking `POST /submissions/{id}/correct` everywhere — and was added to the seam that day; counts are 55 public store functions + `db_path` = 56 Protocol methods again.)
- [ ] **One parametrizable contract suite** passes against `SqliteRepository` **and** `PostgresRepository` in CI (postgres:16 service container); density-matrix round-trip `fidelity ≈ 1.0` holds on the PG path. — NOT DONE: `tests/test_repository_contract.py` exists and is backend-parametrizable by design, but only `SqliteRepository` is wired in; `PostgresRepository` still raises `NotImplementedError` on every method, and no `postgres:16` service container exists in CI yet.
- [ ] **Tenancy is a constraint, not a convention** — `tenant_id` column + FK + composite unique replaces the `"{tenant}:{local}"` prefix, with a repo-boundary compat shim; existing IDs unchanged. — PARTIAL (P2 landed 2026-07-16): the SQLAlchemy models (`original/db/models/`) and the round-trip `original/db/tenancy.py` compat shim exist; the live `store.py` still uses the `"{tenant_id}:{local_id}"` string-prefix convention with a `LIKE`-based scan — the column/FK/composite-unique swap is later-phase work.
- [ ] **Alembic is the live migration story** — 7 stale v1 migrations archived, fresh baseline autogenerate-diff-clean; `PRAGMA user_version` ladder or PG-native migrations in place before any schema change hits the pilot DB (B19). — PARTIAL (P2 landed 2026-07-16): the 7 v1 migrations are archived under `alembic/versions/archived_v1/` and `008_postgres_convergence_baseline.py` is the single fresh head; the `PRAGMA user_version` ladder / pre-pilot migration gate remains open.
- [ ] **Migration report** shows row-count + checksum parity for all 16 tables; shadow soak clean ≥1 week; restore drill passed. — NOT DONE (P4, not started): no `scripts/migrate_sqlite_to_pg.py`, no `REPO_SHADOW` anywhere in `original/`.
- [ ] **Cutover reversible** — SQLite file kept read-only ≥4 weeks; revert command documented in OPS_RUNBOOK. — NOT DONE (P5, not started — nothing to cut over to yet); `get_repository()` unconditionally returns `SqliteRepository` for every environment.
- [ ] **Multi-worker unlocked** — `_STORE` demoted to bounded cache; `--workers 2` serves consistent reads; throttle relocated or per-worker behavior documented (A4, A8). — NOT DONE (P6, not started): `store.py`'s `_STORE` is still an unbounded in-memory dict.
- [ ] **v1 dissolved** — `original/api/`, `canvas/`, `main.py`, `middleware/`, `auth/`, `schemas_v1/`, `tasks/` + 62 v1 tests deleted; `run.py` importlib hack gone; `frontend/`/`web/`/`legacy_mvp/` removed; Docker/fly targets retargeted (F1, F4, F6, B15, A9, T4, T6). — PARTIAL: `frontend/`/`web/` are deleted and the Docker/fly v1 deploy artifacts are quarantined under `deploy/legacy-v1/` (both ADR-006, 2026-07-07/08) — those sub-items are done. The v1 API/backend surface itself (`original/api/`, `original/main.py`, `original/canvas/`, `original/middleware/`, `original/schemas_v1/`, `original/tasks/` + its 62 tests) is still present; WS-5 only did the *interim* `test_api.py`→`test_v1_api_dormant.py` rename, not the final P6 deletion.
- [x] Flags-OFF scoring remains byte-identical to Phase 1 at every phase (WS-5 flag-matrix guard green throughout). — DONE currently: `tests/test_scoring_flags.py` (landed under WS-5) asserts this invariant; full suite re-verified green 2026-07-16 (a broken correction-endpoint repository seam had 16 tests failing until the `submission_student_id` fix landed that day). Re-verify at each future WS-6 phase as the note says.

## Risks & watch-outs
(Program-level strategy concerns are flagged separately to the orchestrator. These are the workstream execution hazards — see §10's risk row for the canonical list.)
- **Migrating on top of silent-swallow persistence.** If WS-1's `except Exception: pass` fix (A1) is not merged before P4, a mid-migration write failure could be swallowed and corrupt the checksum comparison. Hard-gate P4 on WS-1.
- **`tuned_thresholds_v2` naming.** §10 calls it `tuned_thresholds_v`; the real table is `tuned_thresholds_v2`. Model/DDL the real name. Its versioning semantics are subtle (S2 lists it as a long-tail domain) — port it *with its tests first* (§10 risk row).
- **Tenancy shim correctness.** The compat shim at the repo boundary must round-trip the `"{tenant}:{local}"` id both directions during migration; a mismatch silently cross-contaminates tenants. Contract-test the shim explicitly before P4.
- **`_STORE` demotion timing.** Do it in P6 *only*, in its own commit, verified with `--workers 2` before any deletion — it is the change most likely to surface a latent read-through-cache assumption. Memory is currently unbounded (every tenant's baseline text in RAM, A4); the bounded cache must not reintroduce the divergent-worker bug.
- **Third `_DB_PATH` reach.** Audit cites `api.py:153,158`; there is a third at `:410`. Missing it leaves a private store reach that breaks under Postgres.
- **Density-matrix serialization is the highest-stakes round-trip.** `BYTEA`/`JSONB` must reproduce numpy bytes exactly; the 28 `test_store_fidelity.py` round-trips are the only net. Do not "improve" the serialization during the port.
- **ADR path drift (context, not a task).** ADR-002 references `original/api/v1/`; the real dormant dir is `original/api/`. ADR-006 should use the real paths so the retirement list is executable.

## Sequencing within the workstream
1. **WS-7 step 1** (`ScoringConfig`, genre-stats-as-param) — *external prerequisite, not shippable as WS-6 but blocks P0.*
2. **P0** — ADR-006 + staging Postgres + `Settings` promotion. *Shippable-inert.*
3. **P1** — widen seam, route 68 calls, contract suite. *Shippable; strictly improves the codebase on SQLite.*
4. **★ Decision gate** — abort-to-SQLite or proceed.
5. **P2** — models + tenancy constraint + alembic reset. *Shippable-inert (models not yet on a live path).*
6. **P3** — `PostgresRepository` per aggregate + dual-backend CI. *Shippable-inert (prod still SQLite).*
7. **P4** — migration script + shadow soak (1–2 wk) + backup rehearsal. *Runs alongside live pilot, SQLite still source of truth.*
8. **P5** — **cutover, one maintenance window — the only user-visible step.** *Must land atomically; reversible ≥4 wk.*
9. **P6** — demote `_STORE` (own commit, verify multi-worker) → delete v1 + hack + dead deploy targets. *Land after the ≥4-wk soak, in small revertible commits.*

Interleave with WS-7: run the WS-7 APIRouter split (WS-7 step 3) either fully before P1 or fully after, never concurrently — both edit `api.py` call sites. P1's seam-widening is cleanest applied to the already-split routers, so prefer WS-7 step 3 → P1.
