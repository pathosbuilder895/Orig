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
.venv/bin/python -m pytest tests/ -q                  # full suite (~1050 tests as of 2026-08-01, ~145s; ~1053 with validation/test_tier10_optional.py)
.venv/bin/python -m pytest tests/quantum/ -v          # quantum module only
.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q   # exact CI command
```
Test count grows regularly — treat the numbers above as approximate (get the
current count with `.venv/bin/python -m pytest --collect-only -q tests/ 2>&1 | tail -1`),
not a pinned figure to keep in sync by hand.
The 5 `TestAuthEndpoints` tests that 429 under full-suite rate-limit exhaustion are
marked `xfail(strict=False)` — they show as XFAIL/XPASS, never as failures. A clean
run is **0 failed**; treat any failure as real. (Historical note: counts before
2026-06 were inflated ~2× by macOS Finder-duplicate test files, since removed.)

---

## Validation Layer
`validation/` enforces instrument hygiene — see `validation/README.md`.
The rules that bite during development:
- Aggregating over a feature column requires it to be MEASURABLE in
  `validation/measurability.py`; blank/scoring-only/disabled columns raise
  `MeasurabilityError` instead of silently averaging in.
- Gate verdicts are three-valued: `pass` / `fail` / `uninformative`. A gate
  whose criterion is unreachable at the current corpus size downgrades a
  would-be pass to uninformative — never quote it as a pass. Run
  `python -m validation.calibration_gate --strict` before citing results
  (folds `uninformative` into `fail`; the non-strict default still runs but
  prints which gates were uninformative).
- Every new gate needs a failure witness registered in
  `validation/gate_contracts.py` (`GATE_CONTRACTS`) or
  `tests/test_gate_falsifiability.py` fails the suite.
- Corpus floors (`validation/corpus_policy.py`): only the **attribution**
  floor is actually enforced today, by `validation/public_authors/run.py`
  calling `check_attribution_pool()` at load time — >= 300 words (not
  500 — raising it to 500 drops author `kempis`'s baseline docs entirely,
  all 393-499 words) and >= 3 baseline docs per candidate. A thin baseline
  does **not** abort the run — the author is excluded from the candidate
  pool and scoring continues on whoever remains. The **verification**
  floor (`VERIFICATION_MIN_WORDS=300`, `check_verification_pool()`) is a
  declared constant with no production caller yet — tests only.

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
| `GENRE_INVARIANT_WEIGHTS_ENABLED` | `0` | ⚠️ **Still not authorised — but the blocker changed on 2026-08-08.** Implies `ADAPTIVE_WEIGHTS_ENABLED`. Phase 5 addition (2026-08 cross-genre study, `validation/genre_crossgenre_2026-08/`): when the submission's classified genre isn't one this student's baseline has ever covered (`context/baseline_match.py:genre_covered_by_baseline`), additionally attenuates `weighting.GENRE_MISMATCH_ATTENUATE_TIERS` (tiers 2/3/9/10) by the existing `ATTENUATE_FACTOR`. **Resolved:** the classifier no longer mislabels silently. v1 sorted 86% of prose into rule 8's terminal `else`, so the gate fired only on classifier noise; `GENRE_RESOLVER_V2` abstains instead, and `genre_covered_by_baseline` now attenuates only on a **confident mismatch** — `unknown` on either side means do nothing. **Not resolved:** the tier set 2/3/9/10 remains independently unvalidated (`weighting.py`) — no work so far has measured it. Gate G8 now passes (min per-class precision 1.000, abstention 33.3%, shuffled control 0.353 vs 0.333 chance), so the classifier is no longer the blocker; the tier set is. Note that a working classifier does **not** make this fire more often — v2 still abstains on 23% of the committed corpora, and a high firing rate would be grounds for suspicion, not celebration. See `docs/superpowers/specs/2026-08-08-genre-resolution-design.md`. |
| `GENRE_RESOLVER_V2` | `off` | Genre resolver with abstention. `off` is **byte-identical** to the v1 rules (tested over the committed corpora — `tests/context/test_genre_dispatch.py`). ⚠️ **`on` can change scores**: the genre label drives tier-16 muting and T8/T13 anchor expansion (`context/manifest.py:223,225`, `quantum/state.py:427`) and is a Bayesian prior pooling key (`store.py:get_genre_stats`) — so "fix the classifier" is a score- and drift-gating change, not a cleanup. **Why it exists:** v1 does not classify genre. Measured 2026-08-08 over 356 committed documents in 23 provenance groups, 86% come out `correspondence` — rule 8's terminal `else`, not a positive class — and 4 of its 8 labels are never produced at all; seminary papers never once classify as `academic_exegesis`. Rules 1–3 gate on signal-verb count and imperative density whose medians are **0** on every corpus including oratory; rule 7 needs markup 0% of documents have; rule 6's dialogue regex matched straight quotes only, so it could not fire on Gutenberg-sourced prose (Douglass 0% straight / 64% curly). v2 fixes the quote bug, drops the two labels it has no evidence for (`blog_post`, `correspondence`), and returns `unknown` rather than inventing one. Every consumer treats `unknown` as *do nothing*: no mute, base anchors `{4,6}`, excluded from pooling (explicitly — `genre=None` there means the genre-**agnostic** pool), 0.0 genre similarity (two abstentions are not a match), and never a reason to attenuate. `shadow` attaches `shadow_primary`/`shadow_confidence` and logs one `genre_shadow v1=… v2=…` INFO line per call without touching `primary`. Stage 2 replaces the rule tree with a calibrated **3-class** multinomial (`original/data/genre_model_v1.json` — plain JSON coefficients, no pickle, no sklearn at inference; the loader fails **closed** to abstention and never falls back to the rules). Classes are `academic_exegesis`, `scholarly_essay`, `narrative_prose`. ✅ **Gate G8 PASSES**: minimum per-class precision **1.000** over 36 claimed documents on the author-disjoint hold-out, abstention **33.3%** (ceiling 50%), author-shuffled control **0.353** against 0.333 chance. Getting there took eight more public-domain authors (`validation/genre_2026-08/fetch_authors.py` — the thin classes had 2-3 authors, so leave-one-author-out trained on 1-2 and scored 0.000), a threshold selector aligned with the conjunction rather than one leg of it, and one taxonomy change: `creative_fiction` and `personal_essay` were separated by TRUTH CLAIM ("fiction does not assert that its events happened"), which is not a property text carries — every hold-out error was *Huckleberry Finn* predicted as autobiography, which stylometrically it is. They are merged into `narrative_prose` on a mode-of-discourse axis; both old labels stay in `GENRE_LABELS` for stored values and are never emitted. ⚠️ G8 passing does **not** authorise `on` by itself: the hold-out was consulted repeatedly across that work, so its independence is weakened, and nothing here is validated against student writing. **Run `shadow` first** — the abstention rate on real submissions is what decides whether the class set fits, and it is the ONE number no corpus can supply. To collect it: set `GENRE_RESOLVER_V2=shadow` on the deployment (inert — `primary` still comes from v1, nothing downstream moves), let normal traffic run, then `render logs --tail 100000 | .venv/bin/python validation/genre_2026-08/read_shadow_log.py`. Both baseline ingestion and scoring call `resolve_genre`, so every submission emits one line. The reader distinguishes "shadow ran and never abstained" from "shadow was never on" — in a bare abstention rate those are identical and only one is a measurement. ⚠️ This has **not** been run: pilot data is Postgres on Render and no DSN is available locally; every genre number so far comes from 19th-century published prose plus 25 seminary papers. See `docs/superpowers/specs/2026-08-08-genre-resolution-design.md`. |
| `AMPLITUDE_SCORING_ENABLED` | `0` | Phase 6 complex amplitude encoding + quantum fidelity |
| `SECRET_KEY` | `""` | Keyed random unitary projection (adversarial robustness) |
| `BAYESIAN_PRIOR_ENABLED` | `0` | Hierarchical Bayesian cold-start prior. **Tenant-scoped**: `get_genre_stats(genre, tenant, exclude_student_id)` pools same-tenant baselines only (`store.py`, `postgres_repository.py`), mirroring `null_pool.build_impostor_stats`. `tenant=None` (legacy-flat ids) is its own cohort. Floors: `MIN_GENRE_VECTORS=5` **and** `MIN_GENRE_STUDENTS=3` distinct contributing students (`store.py`), mirroring `null_pool.MIN_IMPOSTOR_STUDENTS` — one prolific student cannot stand in for a tenant population. **Self-excluding**: the scored student is dropped from their own prior (mirroring `build_impostor_stats`), so the blend is toward peers rather than partly toward themselves; both floors are re-checked against what remains. Genre pools are sparser per-tenant than the old cross-tenant pool, so the prior returns `None` more often and falls back to the student-only baseline. Run `scripts/measure_genre_prior_scope.py` against real pilot data before enabling this flag — the 2026-07-29 measurement found no reachable dataset with genre-labelled samples to size that coverage drop. The prior's blend weight is **damped by cohort size** (`scoring.py`): the virtual sample count is `PRIOR_WEIGHT × n_students/(n_students+PRIOR_WEIGHT)`, so a 3-peer prior carries half the authority of a large one and converges on `PRIOR_WEIGHT` as the cohort grows — a prior mean estimated from few peers is itself uncertain. Once enabled, `students_scoring.py` logs one INFO `bayesian_prior outcome=hit\|miss genre=… tenant=… n_prior=… n_students=…` line per cold-start scoring call — count miss vs hit for the live per-(tenant, genre) `None` rate. No student ids are logged. |
| `PRIOR_WEIGHT` | `3.0` | Virtual sample count for the prior |
| `NULL_MODEL` | `none` | `impostor` = per-tenant peer-pool null model; attaches `llr_deviation_score`. Whether that's allowed to change the recommended action is a separate flag, `LLR_ACTION_MODE`. |
| `LLR_ACTION_MODE` | `gate` | Only read when `NULL_MODEL=impostor` **and** a real `llr_deviation_score` was computed. A 2026-08 leave-one-genre-out study (C.S. Lewis corpus vs. a Chesterton impostor pool, `validation/genre_crossgenre_2026-08/`) found the raw `deviation_score` alone WORSE than chance (mean AUC 0.39) at telling a genuine cross-genre submission from a different author's writing, vs. 0.86 for `llr_deviation_score` alone. ⚠️ **`gate` (default as of 2026-08) changes actions** — one asymmetric step, in `quantum/scoring.py` (`_apply_llr_action_mode`): may only **downgrade** an action one severity step when llr confidently reads "more like the claimed author" (targets the genre-shift false positive directly — validated: cuts the Lewis-corpus false-positive rate at schedule_conversation+ from 50%→42% and at escalate from 11%→7%, with only a 1–2pt drop in Chesterton catch rate at the same bars; a second independent 10-author test against `validation/public_authors/` confirmed the underlying `llr` route generalizes, mean AUC 0.867→0.952). **Deliberately not yet validated against real student submissions** — accepted as a known risk, not an oversight; re-check against real pilot data as it becomes available. `shadow` is the explicit opt-in for the previous byte-identical attach-only behavior (log-only, never changes `recommendation`). `trigger` may only **upgrade** `no_action`→`monitor` when llr confidently reads "impostor-like" — measured as a no-op on the cross-genre corpus (there were essentially no `no_action` cases to upgrade from once genre has shifted; may behave differently on same-genre cold-start traffic, untested). `blend` re-derives the action tier from a 50/50 mix of `deviation_score` and `llr_deviation_score` — **do not enable**: it looked best on false-positive rate alone, but at a matched severity bar it also collapsed the Chesterton catch rate at schedule_conversation+ from 33%→3% and escalate from 3%→0% — it suppresses genuine impostor severity, not just genre-driven noise. |
| `COHORT_PRIOR_FALLBACK` | `0` | ⚠️ **Changes scores.** Only read when `BAYESIAN_PRIOR_ENABLED=1`. When the same-genre prior above comes back `None` (cold start), fall back to the **genre-agnostic** prior over the same pool (`get_cohort_stats(tenant, exclude_student_id)`, `original/routers/students_scoring.py`). Same code path as the genre prior with the genre filter dropped, so it inherits every invariant listed under `BAYESIAN_PRIOR_ENABLED` unchanged: tenant scoping, self-exclusion, both floors, and cohort-size damping via `n_students`. Logged separately (`bayesian_prior_cohort_fallback outcome=hit\|miss …`) so it does not contaminate the genre prior's coverage measurement. Trades a genre-*matched* reference distribution for a larger one — see `docs/calibration/short_regime_thresholds_2026-07-29.md` §3.1/§4 and its erratum: the 2026-07-29 grid measured an in-process cohort prior, not this code path, and found `PRIOR` net-negative on `deviation_score` alone (catch@5% 0.102 vs. the 0.545 flags-off floor) and net-positive only when the decision is made on `llr_deviation_score`. `LLR_ACTION_MODE=gate` (today's default) is **not** that rebind — it only downgrades one severity step. Do not enable on the strength of that grid alone. |
| `LENGTH_ADAPTIVE_WEIGHTS` | `0` | ⚠️ **Changes scores.** Rescales the per-feature deviation weight vector by submission length (`quantum/scoring.py:515`). |
| `TOPIC_VARIANCE_INFLATION` | `off` | ⚠️ **`on` changes scores.** Widens each feature's expected band in proportion to the submission's topic distance from the student's baseline centroid (`quantum/scoring.py:_topic_inflation_vector`), targeting the measured cross-topic false-positive failure: raw `deviation_score` AUC is **0.387 — inverted** on the leave-one-genre-out Lewis corpus (`validation/genre_crossgenre_2026-08/`), and `LLR_ACTION_MODE=gate` still leaves 42.4% of genuine cross-topic submissions at schedule_conversation+. `sigma_eff = sigma × (1 + TOPIC_INFLATE_GAIN × d_eff × s_norm)`, where `d_eff` is zero at or below `TOPIC_NOVELTY_BOUNDS["low"]` (0.25) — so **`d ≤ 0.25` is bit-for-bit identical to off**, structurally, not approximately. `baseline_distance` is only ever `∈ [0, 0.5]` in production (non-negative TF-IDF cosine similarity bounds it there — see `TOPIC_INFLATE_GAIN`'s row for the real ceiling), so `d_eff` tops out at `0.333`, not `1.0`. `resolve_topic` also returns its `0.5` sentinel — the ceiling of that reachable range — on every degraded path (missing sklearn, empty baseline, centroid underflow, internal exception); those paths now carry an explicit `degraded: True` marker that `_topic_inflation_vector` checks and treats as "no inflation," so a resolver failure can no longer silently apply the strongest possible sigma widening. `shadow` attaches `deviation_score_inflated` and the `topic_distance` / `topic_mean_inflation` diagnostics without touching `deviation_score` or `recommendation`; it is tested to equal exactly what `on` produces (the preview mirrors `D_adjusted` including trajectory adjustment, not `D_raw`). **Run `shadow` first** — if pilot `d` clusters below 0.25 the mechanism is a no-op in production regardless of corpus performance, which is precisely the trap `GENRE_INVARIANT_WEIGHTS_ENABLED` fell into. ⚠️ **`TOPIC_SENSITIVITY` currently ships EMPTY**, meaning uniform per-feature sensitivity — the correction is proportional to topic distance but does not yet distinguish topic-invariant features (`semicolon_colon_rate`) from genre chameleons (`theological_register_score`). Populating it is blocked on corpus work: `validation/public_authors/cross_work_manifest.json` has 2 works per author, and a drift estimate over two work-means cannot support a 109-dim constant. ⚠️ **Not validated against real student submissions** — same accepted risk as `LLR_ACTION_MODE=gate`. Gate G7 (spec §Validation) is now implemented (`validation/calibration_gate.py:evaluate_g7_cross_topic_fpr`, wired into `run_all()`) but has **never returned a verdict**: its corpus is not committed, so it reports `uninformative` and `--strict` exits 1 on a fresh checkout. Do not set `on` before G7 actually passes in both hold-out directions. Traps the gate now catches rather than letting you walk into. (a) **`shadow` can never produce a G7 pass.** Shadow leaves `deviation_score` and `recommendation` untouched, so all three G7 legs come out bit-identical to flag-off — and since the prescribed rollout is "run `shadow` first", a `G7 [PASS]` there would be the likeliest possible misreading; G7 downgrades it to `uninformative` and tells you to re-measure with `on`. (b) **Under `on`, a run where the mechanism never fired is `uninformative`, not a pass** (the `inflation_fire_rate == 0` guard; it does not apply in `off`/`shadow`, where a zero fire rate is simply expected). (c) The cached `vectors.npy` alone **cannot** make it fire, because topic distance is computed from TEXT and `vectors_meta.json` carries none — so `chunks.json` must survive corpus regeneration, and it must cover the genuine and impostor sides **equally** or G7 refuses the run (partial coverage widens only one side's sigma, which biases both action legs toward a pass). Typicality withholds its band whenever inflation is active (`loo_distances` are computed against an un-inflated reference). See `docs/superpowers/specs/2026-08-06-topic-invariant-scoring-design.md`. |
| `TOPIC_INFLATE_GAIN` | `1.0` | Multiplier strength at maximum *reachable* topic distance (`constants.py`). `resolve_topic`'s TF-IDF vectors are non-negative, so `cosine_sim ∈ [0, 1]` and `baseline_distance = (1 − cosine_sim) / 2 ∈ [0, 0.5]` in practice — **`d = 1.0` is unreachable**, do not calibrate or sweep against it. At the real ceiling `d = 0.5`: `d_eff = (0.5 − 0.25) / 0.75 = 0.333`, so the shipped `GAIN = 1.0` yields a true maximum multiplier of **`1.333×`** for a median-sensitivity feature, not the `2×` that `d = 1.0` would have implied. Must be swept on the derivation corpus and fixed before the hold-out is touched — tuning it against the hold-out converts the hold-out into a training set. |
| `RANK_REMEDIATION` | unset | ⚠️ **Changes scores.** `=shrinkage` blends the density matrix ρ toward isotropic I/D via Ledoit-Wolf shrinkage, altering the density-matrix estimator (`quantum/state.py:190`). |
| `AI_LIKELIHOOD_ENABLED` | `0` | Turns on the optional AI-likelihood second scorer (report-only, corpus-level detector). |
| `AI_LIKELIHOOD_SHADOW` | `0` | Runs the AI-likelihood detector in shadow mode (computed but not surfaced) ahead of full enablement. |
| `AI_LIKELIHOOD_MODEL_PATH` | unset | Path to the committed calibrated classifier artifact for the AI-likelihood detector. |
| `LONGITUDINAL_DRIFT_ENABLED` | `0` | Attaches report-only constant-vs-gradual longitudinal analysis for sufficiently long dated authenticated histories. Never changes `deviation_score` or the action. |
| `LONGITUDINAL_MIN_SAMPLES` | `6` | Minimum dated authenticated samples (also subject to length/span checks) before gradual-drift analysis is eligible. |
| `LONGITUDINAL_CHANGEPOINT_MIN_SAMPLES` | `12` | Minimum dated authenticated samples before the report-only one-change-point diagnostic runs. |
| `STYLE_AUTHORSHIP_ENABLED` | `0` | Attaches the report-only peer-aligned authorship-consistency expert. Requires retained raw text, 3 authenticated claimed-author baselines, and 10 eligible same-tenant peer profiles; otherwise returns null. Never changes the score or action. |
| `STYLE_AUTHORSHIP_MODEL_PATH` | unset | Optional path override for the versioned style-authorship artifact. Loader validation fails closed on schema, signal-order, vocabulary, or reference-prediction drift. |
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
| `SENDGRID_API_KEY` | — | No-op without config. Email delivery integration. |

Demo mode turns on CONTEXT_MANIFEST_ENABLED, ADAPTIVE_WEIGHTS_ENABLED, and NULL_MODEL=impostor automatically (set in run.py).

### Feature dimensionality
109 dimensional / **97 active** in the default pilot config — Tier 17 behavioral
biometrics (6 features: `typing_speed_cv, burst_ratio, deletion_rate,
pause_density, paste_event_rate, revision_depth`) and Tier 18 uniformity
(6 features: `sentence_length_dispersion_ratio, window_feature_variance_ratio,
function_word_burstiness_ratio, punctuation_dispersion_ratio,
vocab_introduction_flatness, clause_depth_variance_ratio`) are both in
`DISABLED_FEATURE_GROUPS` by default — Tier 17 pending live keystroke data
from Bbook, Tier 18 pending gates G2b (paraphrase-resistance) and G6
(fairness parity); Tier 10 semantic (2 features:
`semantic_field_dispersion, semantic_centroid_proximity`) has a genuine TF-IDF
fallback backend (`original/features/tier10.py`) that produces real, non-neutral
values when sentence-transformers is unavailable — it is not a placeholder-only
degrade. The 0.5 neutral value only fires when there are too few usable
sentences to encode at all (< 3 for `semantic_field_dispersion`, < 2 for the
embeddings behind `semantic_centroid_proximity`), regardless of which backend
would otherwise run. `BASE_FEATURE_DIM = 102` (was 96 before Tier 18 landed)
is the stored-baseline width (tier-17 and tier-18 included as 0.5 placeholders)
— a distinct number from the 97 "active" count; don't conflate the two.

---

## Key Architecture
```
Text → 109-feature pipeline (original/features/)
     → StudentState (density matrix ρ, baseline_mean, baseline_std)
     → quantum/scoring.py:score() → Layer7Output
     → API response (deviation_score, action, quantum_fidelity, professor_explanation)
```

**Feature pipeline:** `original/features/` — 109 features across 18 tiers
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
- `FEATURE_DIM = 109` (current)
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
