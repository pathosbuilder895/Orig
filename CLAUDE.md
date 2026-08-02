# Original — Claude Code Instructions

## Project Overview
Stylometric authorship verification system for academic integrity. Per-student quantum density matrix profiles scored via Born-rule projection. Targets seminaries and colleges. Positioned as pastoral, explainable, FERPA-compliant.

**Working directory:** `~/Desktop/Original`
**Python environment:** always use `.venv/bin/python` and `.venv/bin/pytest` — NOT system python3
**Run server:** `python run.py --demo` (port 8001 by default)

---

## Server Management
- **NEVER kill or restart running dev servers** without explicit user permission. Find a code-level workaround (env override, redirect flag, config change) and confirm first.
- When starting servers, always check the correct `--frontend-dir` before launching. It should match the demo/ directory: `python run.py --demo --frontend-dir demo/`
- The `.venv` is at `~/Desktop/Original/.venv/` — the system python3 has a broken pydantic_settings install that will cause conftest import errors.

---

## Testing
```bash
.venv/bin/python -m pytest tests/ -q                  # full suite
.venv/bin/python -m pytest tests/quantum/ -v          # quantum module only
DATABASE_URL=postgresql://user:pass@host/db \
  .venv/bin/python -m pytest tests/ validation/test_tier10_optional.py \
  --cov=original --cov-fail-under=78                  # exact CI command (see .github/workflows/test.yml)
```
Test count grows regularly — treat any number below as a point-in-time
measurement, not a pinned figure to keep in sync by hand (get the current
count with `.venv/bin/python -m pytest --collect-only -q tests/ 2>&1 | tail -1`).
There are no `xfail`-marked tests and no `TestAuthEndpoints` class in the
current suite (`grep -rn xfail tests/` and `grep -rn "class TestAuthEndpoints"
tests/` both return nothing) — the older 429-under-rate-limit-exhaustion
xfail pattern this section used to describe is gone. A clean run is **0
failed**; treat any failure as real.

CI sets `DATABASE_URL` so `tests/test_repository_contract.py`'s Postgres
parametrization runs for real instead of self-skipping. Measured 2026-08-02
against `origin/main` HEAD `718ef29`, `tests/ validation/test_tier10_optional.py`:
with a local Postgres and `DATABASE_URL` set, **1,112 passed, 0 failed**;
without it, **954 passed, 158 skipped, 0 failed** (all 158 are the
Postgres-only contract tests self-skipping with "no reachable Postgres — set
DATABASE_URL to a postgresql:// instance …", not failures). Both counts
drift as work lands — re-run rather than trust them.

---

## Design Philosophy
- **Prefer simple over elaborate.** Start with the minimal working solution. Do not propose multi-state scroll systems, 3D models, or complex animations unless explicitly asked.
- **Non-destructive first.** When something breaks, look for a workaround (env var, flag, config) before rebuilding or restarting.
- **Verify visually after UI changes.** Build → test → preview. Don't declare done until all three pass.

---

## Environment Flags
All production features are opt-in via env flags. Default OFF preserves Phase 1 byte-identical behaviour.

| Flag | Default | What it enables |
|------|---------|-----------------|
| `CONTEXT_MANIFEST_ENABLED` | `0` | Phase 3 resolver + context manifest |
| `ADAPTIVE_WEIGHTS_ENABLED` | `0` | Phase 5 cluster-matched adaptive weights |
| `GENRE_INVARIANT_WEIGHTS_ENABLED` | `0` | ⚠️ **Currently INERT — do not enable; blocked on `resolve_genre` (see below).** Implies `ADAPTIVE_WEIGHTS_ENABLED`. Phase 5 addition (2026-08 cross-genre study, `validation/genre_crossgenre_2026-08/`): when the submission's classified genre isn't one this student's baseline has ever covered (`context/baseline_match.py:genre_covered_by_baseline`), additionally attenuates `weighting.GENRE_MISMATCH_ATTENUATE_TIERS` (tiers 2/3/9/10) by the existing `ATTENUATE_FACTOR`. The mechanism is built and tested, but the gate cannot fire in practice: `resolvers.resolve_genre` does not discriminate genre on real prose (84% of an independent 10-author corpus lands in `correspondence`, which is rule 8's terminal `else`, not a positive class; all six of Lewis's hand-labelled genres collapse into it). Measured firing rate: 1 of 6 leave-one-genre-out folds, and that one is classifier noise. The tier set is therefore **unvalidated on independent data** — the validating test could not be run at all. Fix `resolve_genre` first, then re-run `validation/genre_crossgenre_2026-08/genre_invariant_validate.py`. `manifest.baseline_match["genre_covered"]` is recorded once `ADAPTIVE_WEIGHTS_ENABLED` is on regardless of this flag — watch it in production: a ~100% covered rate is the symptom of this same classifier problem. |
| `AMPLITUDE_SCORING_ENABLED` | `0` | Phase 6 complex amplitude encoding + quantum fidelity |
| `SECRET_KEY` | `""` | Keyed random unitary projection (adversarial robustness) |
| `BAYESIAN_PRIOR_ENABLED` | `0` | Hierarchical Bayesian cold-start prior. **Tenant-scoped**: `get_genre_stats(genre, tenant, exclude_student_id)` pools same-tenant baselines only (`store.py`, `postgres_repository.py`), mirroring `null_pool.build_impostor_stats`. `tenant=None` (legacy-flat ids) is its own cohort. Floors: `MIN_GENRE_VECTORS=5` **and** `MIN_GENRE_STUDENTS=3` distinct contributing students (`store.py`), mirroring `null_pool.MIN_IMPOSTOR_STUDENTS` — one prolific student cannot stand in for a tenant population. **Self-excluding**: the scored student is dropped from their own prior (mirroring `build_impostor_stats`), so the blend is toward peers rather than partly toward themselves; both floors are re-checked against what remains. Genre pools are sparser per-tenant than the old cross-tenant pool, so the prior returns `None` more often and falls back to the student-only baseline. Run `scripts/measure_genre_prior_scope.py` against real pilot data before enabling this flag — the 2026-07-29 measurement found no reachable dataset with genre-labelled samples to size that coverage drop. The prior's blend weight is **damped by cohort size** (`scoring.py`): the virtual sample count is `PRIOR_WEIGHT × n_students/(n_students+PRIOR_WEIGHT)`, so a 3-peer prior carries half the authority of a large one and converges on `PRIOR_WEIGHT` as the cohort grows — a prior mean estimated from few peers is itself uncertain. Once enabled, `students_scoring.py` logs one INFO `bayesian_prior outcome=hit\|miss genre=… tenant=… n_prior=… n_students=…` line per cold-start scoring call — count miss vs hit for the live per-(tenant, genre) `None` rate. No student ids are logged. |
| `PRIOR_WEIGHT` | `3.0` | Virtual sample count for the prior |
| `NULL_MODEL` | `none` | `impostor` = per-tenant peer-pool null model; attaches `llr_deviation_score`. Whether that's allowed to change the recommended action is a separate flag, `LLR_ACTION_MODE`. |
| `LLR_ACTION_MODE` | `gate` | Only read when `NULL_MODEL=impostor` **and** a real `llr_deviation_score` was computed. A 2026-08 leave-one-genre-out study (C.S. Lewis corpus vs. a Chesterton impostor pool, `validation/genre_crossgenre_2026-08/`) found the raw `deviation_score` alone WORSE than chance (mean AUC 0.39) at telling a genuine cross-genre submission from a different author's writing, vs. 0.86 for `llr_deviation_score` alone. ⚠️ **`gate` (default as of 2026-08) changes actions** — one asymmetric step, in `quantum/scoring.py` (`_apply_llr_action_mode`): may only **downgrade** an action one severity step when llr confidently reads "more like the claimed author" (targets the genre-shift false positive directly — validated: cuts the Lewis-corpus false-positive rate at schedule_conversation+ from 50%→42% and at escalate from 11%→7%, with only a 1–2pt drop in Chesterton catch rate at the same bars; a second independent 10-author test against `validation/public_authors/` confirmed the underlying `llr` route generalizes, mean AUC 0.867→0.952). **Deliberately not yet validated against real student submissions** — accepted as a known risk, not an oversight; re-check against real pilot data as it becomes available. `shadow` is the explicit opt-in for the previous byte-identical attach-only behavior (log-only, never changes `recommendation`). `trigger` may only **upgrade** `no_action`→`monitor` when llr confidently reads "impostor-like" — measured as a no-op on the cross-genre corpus (there were essentially no `no_action` cases to upgrade from once genre has shifted; may behave differently on same-genre cold-start traffic, untested). `blend` re-derives the action tier from a 50/50 mix of `deviation_score` and `llr_deviation_score` — **do not enable**: it looked best on false-positive rate alone, but at a matched severity bar it also collapsed the Chesterton catch rate at schedule_conversation+ from 33%→3% and escalate from 3%→0% — it suppresses genuine impostor severity, not just genre-driven noise. |
| `COHORT_PRIOR_FALLBACK` | `0` | ⚠️ **Changes scores.** Only read when `BAYESIAN_PRIOR_ENABLED=1`. When the same-genre prior above comes back `None` (cold start), fall back to the **genre-agnostic** prior over the same pool (`get_cohort_stats(tenant, exclude_student_id)`, `original/routers/students_scoring.py`). Same code path as the genre prior with the genre filter dropped, so it inherits every invariant listed under `BAYESIAN_PRIOR_ENABLED` unchanged: tenant scoping, self-exclusion, both floors, and cohort-size damping via `n_students`. Logged separately (`bayesian_prior_cohort_fallback outcome=hit\|miss …`) so it does not contaminate the genre prior's coverage measurement. Trades a genre-*matched* reference distribution for a larger one — see `docs/calibration/short_regime_thresholds_2026-07-29.md` §3.1/§4 and its erratum: the 2026-07-29 grid measured an in-process cohort prior, not this code path, and found `PRIOR` net-negative on `deviation_score` alone (catch@5% 0.102 vs. the 0.545 flags-off floor) and net-positive only when the decision is made on `llr_deviation_score`. `LLR_ACTION_MODE=gate` (today's default) is **not** that rebind — it only downgrades one severity step. Do not enable on the strength of that grid alone. |
| `LENGTH_ADAPTIVE_WEIGHTS` | `0` | ⚠️ **Changes scores.** Rescales the per-feature deviation weight vector by submission length (`quantum/scoring.py:515`). |
| `RANK_REMEDIATION` | unset | ⚠️ **Changes scores.** `=shrinkage` blends the density matrix ρ toward isotropic I/D via Ledoit-Wolf shrinkage, altering the density-matrix estimator (`quantum/state.py:190`). |
| `AI_LIKELIHOOD_ENABLED` | `0` | Turns on the optional AI-likelihood second scorer (report-only, corpus-level detector). |
| `AI_LIKELIHOOD_SHADOW` | `0` | Runs the AI-likelihood detector in shadow mode (computed but not surfaced) ahead of full enablement. |
| `AI_LIKELIHOOD_MODEL_PATH` | unset | Path to the committed calibrated classifier artifact for the AI-likelihood detector. |
| `GUARD_DESTRUCTIVE` | — | Security/ops flag — see `docs/OPS_RUNBOOK.md` (owned by WS-1) for semantics. |
| `MAINTENANCE_TOKEN` | — | Role-granting `X-Guard-Token` secret (`api.py:2642`) — see `docs/OPS_RUNBOOK.md` (owned by WS-1). |
| `LOGIN_THROTTLE_MAX_ATTEMPTS` | `10` | Failed-login attempts allowed within the throttle window before lockout (`api.py`, near the login-throttle helpers). CI sets this higher for the e2e job's login volume only. |
| `LOGIN_THROTTLE_WINDOW_SEC` | `300` | Rolling window (seconds) the above attempt count is measured over (`api.py`). |
| `ENABLE_HSTS` | — | Security/ops flag — see `docs/OPS_RUNBOOK.md` (owned by WS-1). |
| `ALLOWED_ORIGINS` | — | CORS allowlist; fails closed if unset in production — see `docs/OPS_RUNBOOK.md` (owned by WS-1). |
| `ORIGINAL_ENV` | — | **The** deploy-mode variable for the live stack (`run.py:59,96`; surfaced as `/health.environment`). The old `ENVIRONMENT` var was retired in WS-7.4 — it was passed into `get_repository()`, which never read it. Persistence backend is `REPO_BACKEND`/`REPO_SHADOW`; tenant scoping is the tenant record's `environment` column. `ENVIRONMENT` is now read only by the dormant v1 `Settings` (`original/core/config.py`, reached via `original/cli/*`) and has no effect on the live stack. |
| `ORIGINAL_DB` | `profiles.db` | SQLite database path (`store.py:41`). |
| `BACKUP_DIR` | — | No-op without config. Directory for in-app SQLite backups. |
| `BACKUP_INTERVAL_MINUTES` | — | No-op without config. Backup cadence. |
| `BACKUP_KEEP` | — | No-op without config. Backup retention count. |
| `BBOOK_API_URL` | — | No-op without config. Bluebook integration endpoint. |
| `BBOOK_EXTERNAL_SECRET` | — | No-op without config. Bluebook shared secret. |
| `CANVAS_BASE_URL` | — | Canvas instance URL for `/canvas/baseline/*` live import (`canvas/live_import.py`). Without it (and no request-supplied token) those endpoints 400 with manual-upload guidance. |
| `CANVAS_API_TOKEN` | — | Canvas API bearer token for the same endpoints; a request-body `access_token` overrides it. |
| `LTI_PLATFORMS` | — | No-op without config. Registered LTI platform configs for `/lti/*`. |
| `LTI_PRIVATE_KEY` | — | No-op without config. LTI signing key (inline). |
| `LTI_PRIVATE_KEY_FILE` | — | No-op without config. LTI signing key (file path). |
| `LTI_PRIVATE_KEY_PEM` | — | No-op without config. LTI signing key (PEM string). |
| `LTI_TOOL_URL` | — | No-op without config. Public tool URL registered with the LMS. |
| `ADMIN_EMAIL` | — | No-op without config. Seed admin account email. |
| `ADMIN_PASSWORD` | — | No-op without config. Seed admin account password. |
| `SENDGRID_API_KEY` | — | **Currently a documented no-op even when set** — nothing reads it and no email is ever sent (`routers/_shared.py:_send_notification_email`). Setting it logs one warning at startup saying so. |

Demo mode turns on CONTEXT_MANIFEST_ENABLED, ADAPTIVE_WEIGHTS_ENABLED, and NULL_MODEL=impostor automatically (set in run.py).

### Feature dimensionality
103 dimensional / **97 active** in the default pilot config — Tier 17 behavioral
biometrics (6 features: `typing_speed_cv, burst_ratio, deletion_rate,
pause_density, paste_event_rate, revision_depth`) is in `DISABLED_FEATURE_GROUPS`
by default pending live keystroke data from Bbook; Tier 10 semantic (2 features:
`semantic_field_dispersion, semantic_centroid_proximity`) has a genuine TF-IDF
fallback backend (`original/features/tier10.py`) that produces real, non-neutral
values when sentence-transformers is unavailable — it is not a placeholder-only
degrade. The 0.5 neutral value only fires when there are too few usable
sentences to encode at all (< 3 for `semantic_field_dispersion`, < 2 for the
embeddings behind `semantic_centroid_proximity`), regardless of which backend
would otherwise run. `BASE_FEATURE_DIM = 96` (`constants.py:222`)
is the stored-baseline width (tier-17 included as 0.5 placeholders) — a distinct
number from the 97 "active" count; don't conflate the two.

---

## Key Architecture
```
Text → 103-feature pipeline (original/features/)
     → StudentState (density matrix ρ, baseline_mean, baseline_std)
     → quantum/scoring.py:score() → Layer7Output
     → API response (deviation_score, action, quantum_fidelity, professor_explanation)
```

**Feature pipeline:** `original/features/` — 103 features across 17 tiers
**Quantum state:** `original/quantum/state.py` — density matrix builder
**Scoring:** `original/quantum/scoring.py` — Born-rule + amplitude (Phase 6)
**Professor narrative:** `original/quantum/professor_narrative.py` — plain-English explanation
**Context pipeline:** `original/context/pipeline.py` — adaptive Stage 5+6 (parallelized)
**Store:** `original/store.py` — SQLite persistence + in-memory cache
**API:** `original/api.py` — FastAPI endpoints (THE pilot backend)

⚠️ **Two backends exist** — see `docs/ARCHITECTURE.md` before
touching auth or LTI. The live stack is `original/api.py` + `demo/` +
`demo/bluebook/` with LTI at `/lti/*` (`original/lti.py`). The v1 package
(`original/api/`, `original/main.py`, `/canvas/lti/*`) is dormant. The dead
`frontend/` and `web/` trees were removed 2026-07-07 (ADR-006); see git
history. New pilot features go in the live stack only.

**Bluebook frontend:** after editing any `demo/bluebook/*.jsx`, rebuild and
commit the bundle: `cd demo/bluebook && npm run build` (Render has no Node —
the committed `bluebook.bundle.js` is what production serves).

---

## Feature Dimensions
- `FEATURE_DIM = 103` (current)
- Legacy profiles serialized with 74 or 89 features will be padded with 0.5 on load (you'll see warnings). Fix with `python scripts/reextract_baselines.py` (the old `python -m original.cli rebuild-baselines` was deleted with the v1 stack in WS-6 P6 — it only ever operated on the v1 database).
- `ALL_FEATURE_CODES` in `original/constants.py` is the canonical ordered list — don't reorder it.

---

## Known Sandbox / Preview Issues
- Preview server sandbox restricts file access. Use the `/tmp` keeper script pattern if the preview server can't serve static assets.
- The Claude Preview MCP tool requires a running preview server started via `mcp__Claude_Preview__preview_start`.
- `chrome-in-extension` tools can navigate and click but NOT type into IDE terminals — use Bash tool for shell commands.

---

## Commit Style
- One focused commit per logical change
- Conventional: `Fix ...`, `Add ...`, `Refactor ...` (not `update` for new features)
- Co-author line: `Co-Authored-By: Claude <current model name> <noreply@anthropic.com>` (e.g. Claude Fable 5)
- Branch: `commit-changes` → PR to `main` on `pathosbuilder895/Orig`

---

## What Requires Explicit Permission
- Killing or restarting the dev server
- Pushing to main/master directly
- Deleting files (use git rm, not rm)
- Any change to `original/constants.py` feature ordering or NORM_BOUNDS
