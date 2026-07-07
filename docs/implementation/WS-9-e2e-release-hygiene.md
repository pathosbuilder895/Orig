# WS-9 — E2E build-out & release hygiene

> Part of the [Master Implementation Plan](../AUDIT_2026-07-06.md) (Audit §9).
> **Findings:** T7, B20, D7 · **Effort:** 2–3 weeks · **Depends on:** WS-2, WS-8 (partially) · **Unblocks:** a review surface that can't silently regress (professor journey guarded), a writable VPAT (D15, once `@a11y` specs go blocking), and honest deploy provenance for the pilot.

This is a **wrapper workstream.** The detailed derivation lives in **Audit §12 "Playwright E2E build-out plan"** (Stages 0–3). This file is the execution checklist over §12 — it adds owners, order, decision gates, and acceptance, and folds in the release-hygiene rider (B20, D7) that §9 line 604–605 attaches here. **Read §12 first;** do not re-derive it below.

> ⚠️ **Partially implemented already (working tree, 2026-07-07).** A concurrent session appears to be
> landing parts of this workstream: `_resolve_app_version()` exists at `original/api.py:177` (R.2's
> "derive the app version instead of hardcoding it") and `demo/bluebook/playwright.config.mjs` is
> already `fullyParallel: true` with a "WS-9 Stage 0.2" comment (Stage 0.2's per-worker parallelism).
> The "Current state" snapshots below (hardcoded `version="0.1.0"`, `workers: 1`, `retries: 2`) were
> captured before that and are drifting. **Re-check against the live tree and reconcile before starting**
> so you don't redo landed work — and note the line numbers cited below are already shifting.

## Objective
Extend Playwright from 13 student-flow tests to ~55–70 covering the professor's use of sealed evidence (the T7 gap), on infrastructure that lets the suite run multi-worker. Ride release hygiene along: surface the deployed commit in `/health` (B20) and collapse the three disagreeing version strings to one source of truth (D7). "Done" = a green `professor-journey.spec`, `workers` > 1, and `/health` reporting a real SHA on the pilot.

## Prerequisites & dependencies
- **WS-2 must land first (hard dep for CI).** WS-2 owns the CI reshape and the switch of the e2e job to `requirements-pilot.txt` (B11). Today `.github/workflows/test.yml:49` installs `requirements-demo.txt`; `requirements-pilot.txt` already exists on disk (dated Jun 12) but the e2e job does not use it. **Do not build the CI half of Stage 0.4 until WS-2's four-job shape exists** — build onto it, don't fork it. WS-2 also registers tags/timeouts/concurrency this workstream's job inherits.
- **WS-8 is a partial dep, and the direction is one-way.** Stage 0/1/2 do **not** wait on React — they run against the current committed `bluebook.bundle.js`. But the `@a11y` specs (Stage 2, `a11y.spec`) start non-blocking and **become blocking per page as WS-8 lands** each React page (§12 Stage 2; §9 line 546). The `visual.spec` (Stage 2, optional) must **not** be written before the React markup stabilizes — it would churn weekly (§12 line 701).
- **D7 coordinates with WS-3.** WS-3 task 1 fixes the MODEL_CARD title line (`MODEL_CARD.md:1`, "v1.1.0"). This workstream owns the *single-source-of-truth* decision (which surface is authoritative and how the others derive from it). Fix the version drift **with** WS-3, not twice — see 4.2.
- **Bluebook rebuild rule.** Any `.jsx` touched (unlikely here — specs are additive) requires `cd demo/bluebook && npm run build` + committing the bundle (Render has no Node). Specs live in `demo/bluebook/e2e/`, not `src/` — no rebuild needed for spec-only work.
- Env/tooling: `.venv` on 3.11 (WS-2 task 6); Node for `npm ci` in `demo/bluebook/`; the live app boots via `run.load_legacy_demo_app()` on port **8001** with `--skip-seed ORIGINAL_ENV=pilot` (already the CI pattern, `test.yml:69`).

## Tasks

### Stage 0 — Infrastructure — T7 (enabler)
*Detail: §12 Stage 0. Do this before writing any new spec; it is what makes Stages 1–2 parallelizable.*
- **Current state:** `demo/bluebook/playwright.config.mjs` — `workers: 1`, `fullyParallel: false`, with a documented reason (`config:12-13`: "a separate worker per test is too expensive given the seed-load cost … Stay single-worker"). `trace: 'on-first-retry'` and `screenshot: 'only-on-failure'` are already set (good habits to keep, §12 Stage 3). No `webServer`, `storageState`, or `globalSetup`. The two specs lean on the global demo seed.
- **Change:**
  - **0.1 API-driven fixtures** — a `beforeAll` helper that creates tenant/course/exam/student via REST (the same endpoints `test_bluebook_api.py` exercises), replacing reliance on the global seed. Makes each spec self-contained.
  - **0.2 Per-worker tenancy isolation** — each worker provisions its own tenant so the product's own isolation model keeps workers from colliding; then raise `workers` (drop `workers: 1`, keep `fullyParallel` deliberate). This is the change that retires the `config:12-13` single-worker rationale — **update that comment** when you do, or it becomes stale-by-construction.
  - **0.3 Auth storage-state fixtures** per role (staff, student, operator) — login once per worker, reuse via `storageState`.
  - **0.4 CI (build ON WS-2)** — e2e job installs `requirements-pilot.txt` (B11, WS-2-owned); add `@axe-core/playwright` (not currently a dep — `package.json` has no `axe`); adopt tag conventions `@smoke` / `@a11y` / `@regression`; shard the job once the suite passes ~40 tests.
- **Files touched:** `demo/bluebook/playwright.config.mjs`; new `demo/bluebook/e2e/fixtures/` (api-setup, auth storage-state); `demo/bluebook/package.json` (+`@axe-core/playwright`); `.github/workflows/test.yml` (e2e job — coordinate with WS-2).
- **Verify:** `cd demo/bluebook && npx playwright test` green with `workers` > 1 locally; a deliberately cross-tenant assertion proves worker A cannot see worker B's tenant data.

### Stage 1 — The professor journey — T7 (the gap)
*Detail: §12 Stage 1. The highest-value 8–10 tests in the plan.*
- **Current state:** the five professor pages exist with **zero** e2e coverage: `demo/bluebook/Dashboard.jsx`, `Results.jsx`, `Courses.jsx`, `Students.jsx`, `NewExam.jsx`. The 13 existing tests (`e2e/smoke.spec.mjs` ×5, `e2e/exam-flow.spec.mjs` ×8) cover only page-load, no-CDN, and the student Begin→seal lockdown flow. (Audit T7 line 201 lists `Courses.jsx`; the WS-9 task brief listed `NewExam.jsx` — **both exist and both are in scope**; the journey touches all five.)
- **Change:** one `professor-journey.spec.mjs` walking: create course → create exam (`NewExam` settings incl. the `ToggleRow` states) → student seals a submission (reuse the exam-flow seal helper) → exam appears in `Dashboard` → `Results` shows the score → drill into explanation/narrative → file a correction → correction visible in audit. Exercises Bluebook CRUD + scoring + the review surface end-to-end.
- **Files touched:** new `demo/bluebook/e2e/professor-journey.spec.mjs` (consumes Stage 0 fixtures).
- **Verify:** the spec is green in CI; it is the acceptance gate below. Tag the smoke subset `@smoke`.

### Stage 2 — Breadth — T7
*Detail: §12 Stage 2. Target ≈55–70 tests total.*
- **Current state:** none of the below exist. `test_tenant_isolation.py` (unit) and LTI pytest coverage exist server-side — the E2E specs *complement*, not duplicate, them.
- **Change (one spec each):**
  - `auth.spec` — staff login/logout, throttle lockout **with the message announced** (pairs with WS-4 W4 `role="alert"`), student magic-link, bad-credential errors.
  - `baselines.spec` — batch upload via the **keyboard path** through the file input, request-baseline magic link, readiness surface reflects new samples.
  - `scoring.spec` — submit → score → explanation renders and **matches the API payload**; blend-detection surface.
  - `tenants-admin.spec` — tenant CRUD + the E2E complement of `test_tenant_isolation.py` (student in tenant A invisible from tenant B's session).
  - `lti.spec` — test-RSA-signed `id_token` POSTed at `/lti/launch`. **Decision gate:** this is API-level; a headless browser adds nothing. If browser friction is high, **keep it in pytest** and drop the E2E spec (§12 line 699).
  - `a11y.spec` — axe scan per page + keyboard-walk smoke. **Starts `@a11y` non-blocking; flips to blocking per page as WS-8 lands that page** (the WS-8 coupling).
  - `visual.spec` (**optional, gated**) — Chromium-only screenshot diffs on professor dashboard + student profile. **Do not write before the React migration stabilizes markup** — hard gate, or it churns weekly.
- **Files touched:** `demo/bluebook/e2e/{auth,baselines,scoring,tenants-admin,a11y}.spec.mjs`; optionally `lti.spec.mjs`, `visual.spec.mjs`.
- **Verify:** `npx playwright test` collects ~55–70; `@a11y`-tagged specs run green (non-blocking) and can be promoted per page.

### Stage 3 — Maintenance posture
*Detail: §12 Stage 3.*
- **Change:** review-checklist rule (not tooling): every feature PR that adds a route or page adds/extends one spec. Preserve the config's good habits — `trace: 'on-first-retry'`, artifact upload on failure. **Reconcile the retry count:** §12 line 704 and the CI shape say "single retry in CI only," but `config:24` currently sets `retries: process.env.CI ? 2 : 0`. Set CI retries to **1** to match the audit's stated posture (or amend the audit — flag to orchestrator, see contradictions).
- **Files touched:** `demo/bluebook/playwright.config.mjs` (retries: 1); the PR/review checklist doc (WS-3's checklist, or `CONTRIBUTING`).
- **Verify:** `grep 'retries' demo/bluebook/playwright.config.mjs` shows the single-retry CI value.

### Release hygiene — B20, D7 (the rider; §9 line 604–605)

#### R.1 Surface the deployed commit in `/health` — B20
- **Current state:** `RENDER_GIT_COMMIT` appears **nowhere** in the codebase (grep clean). `/health` exists (`original/api.py:362`) and returns `HealthResponse` (`original/schemas.py:644`) with 4 fields (`status`, `feature_dim`, `students_in_store`, `environment`). `render.yaml:53` is `autoDeploy: false` (manual dashboard deploys → deployed SHA recorded nowhere in the repo); `healthCheckPath: /health` (`render.yaml:21,64`). Zero git tags (`git tag -l` empty). No `CHANGELOG`.
- **Change:**
  - Add `commit: str = "dev"` to `HealthResponse` (`schemas.py:644`); in `health()` (`api.py:363`) populate it from `os.environ.get("RENDER_GIT_COMMIT", "dev")` (Render injects it at runtime; fallback `"dev"` off-platform).
  - Tag each pilot deploy: `pilot-YYYY-MM-DD` (e.g. `pilot-2026-07-04`) — a lightweight, documented convention; note it in OPS_RUNBOOK/DEPLOY.
  - Create `CHANGELOG.md` — one line per deploy. **Skip semver automation** (overkill at this scale, per B20).
- **Files touched:** `original/schemas.py`, `original/api.py`, new `CHANGELOG.md`, deploy runbook (tag convention).
- **Verify:** `RENDER_GIT_COMMIT=abc123 .venv/bin/python -c "..."` (or a `test_health` assertion) shows `/health` returns `commit:"abc123"`; falls back to `"dev"` when unset. The CI curl on `/health` (`test.yml:74`) still passes.

#### R.2 One version source of truth — D7
- **Current state (measured — three disagree):** `pyproject.toml:3` → `0.0.0`; FastAPI app (`api.py:170`) → `0.1.0`; `MODEL_CARD.md:1` title → `v1.1.0`, but its own history table (`MODEL_CARD.md:277`) ends at **1.3.0** (2026-07-04). No `importlib.metadata`/`__version__` read anywhere — the FastAPI string is a hardcoded literal.
- **Change:** pick **pyproject as the source of truth**, bump `pyproject.toml` → `0.1.0` (per B20), and have the FastAPI app read it (`importlib.metadata.version("original")` with a literal fallback) instead of hardcoding `api.py:170`. The MODEL_CARD title (`:1`) is **product/model versioning, a different axis** — it tracks the 1.x scorer history and is **fixed by WS-3 task 1** (align title to the 1.3.0 history line); do not force the app's `0.1.0` onto the model card. Document the two axes so they don't re-drift (a one-line note by `ACTION_THRESHOLDS`-style comment, coordinated with WS-3).
- **Files touched:** `pyproject.toml`, `original/api.py` (FastAPI `version=`); `MODEL_CARD.md` title is **WS-3-owned** (cross-reference, don't double-edit).
- **Verify:** `.venv/bin/python -c "import importlib.metadata as m; print(m.version('original'))"` → `0.1.0`; `/health` app version and pyproject agree; `grep -n '0\.0\.0' pyproject.toml` empty.

## Acceptance criteria
- [ ] `professor-journey.spec` is green in CI (create course → exam → seal → Dashboard → Results score → explanation → correction → audit). **(the T7 acceptance gate)**
- [ ] `workers` > 1 in `playwright.config.mjs` with per-worker tenancy isolation; the stale `config:12-13` single-worker comment is updated/removed.
- [ ] Total collected E2E tests ≈ **55–70** (`npx playwright test --list`).
- [ ] `@a11y`-tagged specs exist and run (non-blocking initially); promotable to blocking per page as WS-8 lands.
- [ ] CI e2e job installs `requirements-pilot.txt` (B11) and has `@axe-core/playwright` available; trace-on-first-retry + failure-artifact upload preserved; CI retries = 1.
- [ ] `/health` returns a `commit` field = `RENDER_GIT_COMMIT` (fallback `"dev"`); the pilot deploy is tagged `pilot-<date>`; `CHANGELOG.md` exists with ≥1 deploy line. **(B20)**
- [ ] `pyproject.toml` = `0.1.0`; FastAPI app version derives from it (not a second literal); the three version surfaces no longer disagree — with MODEL_CARD's model-version axis reconciled by WS-3. **(D7)**

## Risks & watch-outs
- **Tenancy isolation is load-bearing for parallelism.** If per-worker tenants leak (shared global store, a fixture that reuses one tenant id), raising `workers` will produce flaky cross-talk that looks like product bugs. Validate 0.2 with an explicit cross-tenant negative assertion before trusting green runs.
- **Seed dependency is a hidden coupling.** Specs that still lean on the global demo seed after Stage 0 will pass single-worker and fail parallel. Grep new specs for seed assumptions before flipping `workers`.
- **`@a11y` blocking is a WS-8 handshake, not a date.** Flip a page's a11y spec to blocking only when that page's React rebuild has actually landed and passes axe — flipping early red-walls CI on the legacy markup WS-4 only hot-fixed.
- **`visual.spec` before React = weekly churn.** Keep it gated on migration stability (§12 line 701). Do not add it "for completeness."
- **Do not touch scoring behavior.** No spec or health/version change may alter flags-OFF scoring (byte-identical to Phase 1). R.1/R.2 are additive to `/health` and metadata only.
- **CI ownership seam.** The e2e job lives in the CI file WS-2 reshapes. Editing it in parallel with WS-2 risks a merge that reverts B11. Sequence after WS-2's CI PR merges, or coordinate the diff.

## Sequencing within the workstream
1. **Stage 0** (infra) — *must land before any new spec*; not shippable alone but unblocks everything. Do 0.1–0.3 locally, then 0.4 **after WS-2's CI PR merges**.
2. **R.1 + R.2** (release hygiene) — *independently shippable now*, no dependency on the specs; small, high-signal. Land alongside/after WS-3's MODEL_CARD fix (R.2 coordination) and WS-2 (0.4 is unrelated to these). Good first PR.
3. **Stage 1** (`professor-journey.spec`) — ships once Stage 0 fixtures exist; **this is the acceptance gate** — land and keep green before breadth.
4. **Stage 2** breadth — incremental, one spec per PR; `auth`/`baselines`/`scoring`/`tenants-admin` land independently; `lti.spec` only if browser adds value (else keep in pytest); `a11y.spec` non-blocking now; `visual.spec` gated on WS-8.
5. **Stage 3** (maintenance posture + retries:1) — a small config/checklist PR; land last so the retry change doesn't mask flakiness while Stages 0–2 stabilize.
