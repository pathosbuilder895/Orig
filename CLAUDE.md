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
| `GENRE_INVARIANT_WEIGHTS_ENABLED` | `0` | ⚠️ **Currently INERT — do not enable; blocked on `resolve_genre` (see below).** Implies `ADAPTIVE_WEIGHTS_ENABLED`. Phase 5 addition (2026-08 cross-genre study, `validation/genre_crossgenre_2026-08/`): when the submission's classified genre isn't one this student's baseline has ever covered (`context/baseline_match.py:genre_covered_by_baseline`), additionally attenuates `weighting.GENRE_MISMATCH_ATTENUATE_TIERS` (tiers 2/3/9/10) by the existing `ATTENUATE_FACTOR`. The mechanism is built and tested, but the gate cannot fire in practice: `resolvers.resolve_genre` does not discriminate genre on real prose (84% of an independent 10-author corpus lands in `correspondence`, which is rule 8's terminal `else`, not a positive class; all six of Lewis's hand-labelled genres collapse into it). Measured firing rate: 1 of 6 leave-one-genre-out folds, and that one is classifier noise. The tier set is therefore **unvalidated on independent data** — the validating test could not be run at all. Fix `resolve_genre` first, then re-run `validation/genre_crossgenre_2026-08/genre_invariant_validate.py`. `manifest.baseline_match["genre_covered"]` is recorded once `ADAPTIVE_WEIGHTS_ENABLED` is on regardless of this flag — watch it in production: a ~100% covered rate is the symptom of this same classifier problem. |
| `AMPLITUDE_SCORING_ENABLED` | `0` | Phase 6 complex amplitude encoding + quantum fidelity |
| `SECRET_KEY` | `""` | Keyed random unitary projection (adversarial robustness) |
| `BAYESIAN_PRIOR_ENABLED` | `0` | Hierarchical Bayesian cold-start prior. **Tenant-scoped**: `get_genre_stats(genre, tenant, exclude_student_id)` pools same-tenant baselines only (`store.py`, `postgres_repository.py`), mirroring `null_pool.build_impostor_stats`. `tenant=None` (legacy-flat ids) is its own cohort. Floors: `MIN_GENRE_VECTORS=5` **and** `MIN_GENRE_STUDENTS=3` distinct contributing students (`store.py`), mirroring `null_pool.MIN_IMPOSTOR_STUDENTS` — one prolific student cannot stand in for a tenant population. **Self-excluding**: the scored student is dropped from their own prior (mirroring `build_impostor_stats`), so the blend is toward peers rather than partly toward themselves; both floors are re-checked against what remains. Genre pools are sparser per-tenant than the old cross-tenant pool, so the prior returns `None` more often and falls back to the student-only baseline. Run `scripts/measure_genre_prior_scope.py` against real pilot data before enabling this flag — the 2026-07-29 measurement found no reachable dataset with genre-labelled samples to size that coverage drop. The prior's blend weight is **damped by cohort size** (`scoring.py`): the virtual sample count is `PRIOR_WEIGHT × n_students/(n_students+PRIOR_WEIGHT)`, so a 3-peer prior carries half the authority of a large one and converges on `PRIOR_WEIGHT` as the cohort grows — a prior mean estimated from few peers is itself uncertain. Once enabled, `students_scoring.py` logs one INFO `bayesian_prior outcome=hit\|miss genre=… tenant=… n_prior=… n_students=…` line per cold-start scoring call — count miss vs hit for the live per-(tenant, genre) `None` rate. No student ids are logged. |
| `PRIOR_WEIGHT` | `3.0` | Virtual sample count for the prior |
| `NULL_MODEL` | `none` | `impostor` = per-tenant peer-pool null model; attaches `llr_deviation_score`. Whether that's allowed to change the recommended action is a separate flag, `LLR_ACTION_MODE`. |
| `LLR_ACTION_MODE` | `gate` | Only read when `NULL_MODEL=impostor` **and** a real `llr_deviation_score` was computed. A 2026-08 leave-one-genre-out study (C.S. Lewis corpus vs. a Chesterton impostor pool, `validation/genre_crossgenre_2026-08/`) found the raw `deviation_score` alone WORSE than chance (mean AUC 0.39) at telling a genuine cross-genre submission from a different author's writing, vs. 0.86 for `llr_deviation_score` alone. ⚠️ **`gate` (default as of 2026-08) changes actions** — one asymmetric step, in `quantum/scoring.py` (`_apply_llr_action_mode`): may only **downgrade** an action one severity step when llr confidently reads "more like the claimed author" (targets the genre-shift false positive directly — validated: cuts the Lewis-corpus false-positive rate at schedule_conversation+ from 50%→42% and at escalate from 11%→7%, with only a 1–2pt drop in Chesterton catch rate at the same bars; a second independent 10-author test against `validation/public_authors/` confirmed the underlying `llr` route generalizes, mean AUC 0.867→0.952). **Deliberately not yet validated against real student submissions** — accepted as a known risk, not an oversight; re-check against real pilot data as it becomes available. `shadow` is the explicit opt-in for the previous byte-identical attach-only behavior (log-only, never changes `recommendation`). `trigger` may only **upgrade** `no_action`→`monitor` when llr confidently reads "impostor-like" — measured as a no-op on the cross-genre corpus (there were essentially no `no_action` cases to upgrade from once genre has shifted; may behave differently on same-genre cold-start traffic, untested). `blend` re-derives the action tier from a 50/50 mix of `deviation_score` and `llr_deviation_score` — **do not enable**: it looked best on false-positive rate alone, but at a matched severity bar it also collapsed the Chesterton catch rate at schedule_conversation+ from 33%→3% and escalate from 3%→0% — it suppresses genuine impostor severity, not just genre-driven noise. |
| `COHORT_PRIOR_FALLBACK` | `0` | ⚠️ **Changes scores.** Only read when `BAYESIAN_PRIOR_ENABLED=1`. When the same-genre prior above comes back `None` (cold start), fall back to the **genre-agnostic** prior over the same pool (`get_cohort_stats(tenant, exclude_student_id)`, `original/routers/students_scoring.py`). Same code path as the genre prior with the genre filter dropped, so it inherits every invariant listed under `BAYESIAN_PRIOR_ENABLED` unchanged: tenant scoping, self-exclusion, both floors, and cohort-size damping via `n_students`. Logged separately (`bayesian_prior_cohort_fallback outcome=hit\|miss …`) so it does not contaminate the genre prior's coverage measurement. Trades a genre-*matched* reference distribution for a larger one — see `docs/calibration/short_regime_thresholds_2026-07-29.md` §3.1/§4 and its erratum: the 2026-07-29 grid measured an in-process cohort prior, not this code path, and found `PRIOR` net-negative on `deviation_score` alone (catch@5% 0.102 vs. the 0.545 flags-off floor) and net-positive only when the decision is made on `llr_deviation_score`. `LLR_ACTION_MODE=gate` (today's default) is **not** that rebind — it only downgrades one severity step. Do not enable on the strength of that grid alone. |
| `LENGTH_ADAPTIVE_WEIGHTS` | `0` | ⚠️ **Changes scores.** Rescales the per-feature deviation weight vector by submission length (`quantum/scoring.py:515`). |
| `TOPIC_VARIANCE_INFLATION` | `off` | ⚠️ **`on` changes scores.** Widens each feature's expected band in proportion to the submission's topic distance from the student's baseline centroid (`quantum/scoring.py:_topic_inflation_vector`), targeting the measured cross-topic false-positive failure: raw `deviation_score` AUC is **0.387 — inverted** on the leave-one-genre-out Lewis corpus (`validation/genre_crossgenre_2026-08/`), and `LLR_ACTION_MODE=gate` still leaves 42.4% of genuine cross-topic submissions at schedule_conversation+. `sigma_eff = sigma × (1 + TOPIC_INFLATE_GAIN × d_eff × s_norm)`, where `d_eff` is zero at or below `TOPIC_NOVELTY_BOUNDS["low"]` (0.25) — so **`d ≤ 0.25` is bit-for-bit identical to off**, structurally, not approximately. `baseline_distance` is only ever `∈ [0, 0.5]` in production (non-negative TF-IDF cosine similarity bounds it there — see `TOPIC_INFLATE_GAIN`'s row for the real ceiling), so `d_eff` tops out at `0.333`, not `1.0`. `resolve_topic` also returns its `0.5` sentinel — the ceiling of that reachable range — on every degraded path (missing sklearn, empty baseline, centroid underflow, internal exception); those paths now carry an explicit `degraded: True` marker that `_topic_inflation_vector` checks and treats as "no inflation," so a resolver failure can no longer silently apply the strongest possible sigma widening. `shadow` attaches `deviation_score_inflated` and the `topic_distance` / `topic_mean_inflation` diagnostics without touching `deviation_score` or `recommendation`; it is tested to equal exactly what `on` produces (the preview mirrors `D_adjusted` including trajectory adjustment, not `D_raw`). **Run `shadow` first** — if pilot `d` clusters below 0.25 the mechanism is a no-op in production regardless of corpus performance, which is precisely the trap `GENRE_INVARIANT_WEIGHTS_ENABLED` fell into. ⚠️ **`TOPIC_SENSITIVITY` currently ships EMPTY**, meaning uniform per-feature sensitivity — the correction is proportional to topic distance but does not yet distinguish topic-invariant features (`semicolon_colon_rate`) from genre chameleons (`theological_register_score`). Populating it is blocked on corpus work: `validation/public_authors/cross_work_manifest.json` has 2 works per author, and a drift estimate over two work-means cannot support a 109-dim constant. ⚠️ **Not validated against real student submissions** — same accepted risk as `LLR_ACTION_MODE=gate`. Gate G7 (spec §Validation) is not yet implemented; do not set `on` before it passes in both hold-out directions. Typicality withholds its band whenever inflation is active (`loo_distances` are computed against an un-inflated reference). See `docs/superpowers/specs/2026-08-06-topic-invariant-scoring-design.md`. |
| `TOPIC_INFLATE_GAIN` | `1.0` | Multiplier strength at maximum *reachable* topic distance (`constants.py`). `resolve_topic`'s TF-IDF vectors are non-negative, so `cosine_sim ∈ [0, 1]` and `baseline_distance = (1 − cosine_sim) / 2 ∈ [0, 0.5]` in practice — **`d = 1.0` is unreachable**, do not calibrate or sweep against it. At the real ceiling `d = 0.5`: `d_eff = (0.5 − 0.25) / 0.75 = 0.333`, so the shipped `GAIN = 1.0` yields a true maximum multiplier of **`1.333×`** for a median-sensitivity feature, not the `2×` that `d = 1.0` would have implied. Must be swept on the derivation corpus and fixed before the hold-out is touched — tuning it against the hold-out converts the hold-out into a training set. |
| `CHARACTERISTIC_WEIGHTS` | `off` | ⚠️ **`on` changes scores.** Per-student feature weighting by the representative-and-distinctive criterion: `w_char_i ∝ sigma_null_i / max(baseline_std_i, 0.005)` — the impostor pool's between-student spread over this student's own within-student spread (`quantum/scoring.py:_characteristic_weight_factor`). Every other weighting in the system is population-derived (static `TIER_WEIGHTS`, manifest-adaptive weights, the per-tier length schedule); this is the only one that asks which features are characteristic of *this* student. The ratios are median-centred, clipped to `[0.5, 2.0]` (same band as `LENGTH_WEIGHT_SCHEDULE`'s raw factors — one feature whose `baseline_std` sits at the floor against a wide peer pool can otherwise take a ratio in the tens and dominate `rms_z` alone), then **rescaled to preserve `Σ(w²)` over the ACTIVE feature set** (`state.active_feature_mask`) against the vector actually selected at the call site — inactive features are pinned at exactly 1.0, which preserves `Σ(w²)` over the full 109-wide vector as a side effect. The active set is the load-bearing one: `_rms_z_from_z`, `_llr_deviation` and `encode_amplitudes` all zero inactive features and divide by `n_active`, so that is the only sum of squares reaching `rms_z`. Normalising over all `FEATURE_DIM` features instead **inflated every score** — tiers 17/18 (12 features, ~18% of `Σ(w²)`, the two highest tier weights) are in `DISABLED_FEATURE_GROUPS`, so they sit at exactly 0.5 in every baseline *and* in every peer, which pins their ratio deterministically on the clip floor; one uniform alpha then handed that released energy to the live features. Measured on a realistic profile (5 baselines, 4 peers, `n_active` 95/109): active `Σ(w²)` +16%, `rms_z` ×1.077, `deviation_score` +0.023/+0.033/+0.030 at `rms_z` 0.5/1.0/1.5 — a uniform upward false-positive bias, same regression class as the mean-1.0 normalisation below. That rescale is load-bearing and is *not* interchangeable with a "mean factor = 1.0" normalisation — see the `LENGTH_WEIGHT_SCHEDULE` block comment in `constants.py`, which records that the mean-1.0 version still inflated `Σ(w²)` (variance adds to a sum of squares), moved mean deviation 0.796 → 0.893 on 717 samples, and collapsed threshold classification. Order at the call site is fixed: **select → characteristic → length**. **Abstains to identity** (no multiply at all, so `on` is then bit-for-bit `off`) when `impostor_stats` is absent — no peer pool, or the tenant is under `null_pool`'s 3-student/5-vector floors — or the student has < 2 contributing baseline samples, where `baseline_std` is the flat 0.15 uncertainty prior rather than a measurement. `shadow` leaves `weight_vec` completely untouched (so `_llr_deviation` and amplitude fidelity are untouched too) and attaches `characteristic_rms_z_preview` / `characteristic_deviation_preview` / `characteristic_factor_dispersion` report-only; the preview is tested to equal exactly what `on` produces, including the trajectory adjustment, under adaptive **and** length-adaptive weights. Typicality withholds its band whenever `on` is active — `loo_distances` are computed under the unweighted reference. `students_scoring.py` logs one INFO `characteristic_weights mode=… outcome=applied\|abstain dispersion=… ` line per scoring call (no student ids); **`dispersion` is the number that matters in a shadow soak** — it is `mean(|factor − 1|)` **over active features only** (dead features are pinned at 1.0 and can move no score; counting them made the headline number ~28% larger than the real one), and a soak that returns mostly `abstain` or a near-zero dispersion means the mechanism is inert in production regardless of any corpus result. That is exactly the trap `GENRE_INVARIANT_WEIGHTS_ENABLED` fell into (built, tested, and fires in 1 of 6 folds — that once being noise). ⚠️ **`on` is NOT VALIDATED: gate G-P3 has not been run**, and cannot be from this checkout — it needs the leave-one-genre-out corpus in `validation/genre_crossgenre_2026-08/`, which is not committed. Ships default-off as a mechanism plus its validation debt, not as an improvement. Run `shadow` first. ⚠️ **Shadow is not free**: any non-`off` value makes `students_scoring.py` build the impostor pool (`_repo().all_states()` — a full state scan) on **every** scoring request, including on `NULL_MODEL=none` deployments that previously never scanned. That is unavoidable — the factor *is* `sigma_null / baseline_std` — but it is a real per-request cost in the mode operators are told to run in production; watch scoring latency when turning shadow on, and turn it back to `off` when the soak ends. **Scope**: only `POST /students/{id}/score` supplies the peer pool. `POST /students/{id}/score/blend`'s per-window rescores (`context/blend.py`) and the admin playground (`/admin/test/score`) pass no `impostor_stats`, so under `on` they abstain while the document score does not — per-window deviations are not comparable to the document deviation under this flag (and the playground will always show `characteristic_mode: null`). |
| `RANK_REMEDIATION` | unset | ⚠️ **Changes scores.** `=shrinkage` blends the density matrix ρ toward isotropic I/D via Ledoit-Wolf shrinkage, altering the density-matrix estimator (`quantum/state.py:190`). |
| `AI_LIKELIHOOD_ENABLED` | `0` | Turns on the optional AI-likelihood second scorer (report-only, corpus-level detector). |
| `AI_LIKELIHOOD_SHADOW` | `0` | Runs the AI-likelihood detector in shadow mode (computed but not surfaced) ahead of full enablement. **Also attaches per-window AI-likelihood to the blend endpoint** (`POST /students/{id}/score/blend`): `original/context/blend.py:_attach_window_ai_shadow` makes one batched `predict_ai_likelihood_batch` call over the window feature vectors the rolling-stylometry loop already builds, filling `WindowScore.ai_probability` plus `BlendResult.ai_window_max` / `ai_window_mean` (summaries computed only over windows that actually got a probability; `None` if none did). Read inline from env in `blend.py` — deliberately **not** routed through `ScoringConfig`, because it is a blend-local report-only gate. Report-only in the strict sense: nothing in `blend.py` reads these fields back, so they cannot move `blend_detected`, `blend_index`, `shift_positions`, `deviation_score`, or any recommendation; flag-off output is byte-identical (proved by `tests/context/test_blend.py::TestWindowAiShadow::test_flag_off_output_is_byte_identical`) and the detector module is not even imported on the flag-off path. A window whose feature extraction failed contributes no vector and keeps `ai_probability=None` — probabilities are written back by recorded window index, never by position. ⚠️ The detector's document-level enablement gate still **FAILS** (`MODEL_CARD.md`: FPR 8% vs. a 5% bar, uninformative at n=25), so `AI_LIKELIHOOD_ENABLED` stays off; this window wiring exists to collect shadow evidence, not because the detector is trusted. |
| `AI_LIKELIHOOD_MODEL_PATH` | unset | Path to the committed calibrated classifier artifact for the AI-likelihood detector. |
| `FUSED_SCORE_ENABLED` | `0` | Attaches the report-only fused stylometric score (`original/fusion/`) — peer-centered diagonal z + LZMA conditional compression, logistic-fused into one calibrated evidence weight. The channel set the *shipped* artifact (`original/data/fused_score_v1.json`) actually fuses is **two** channels, not three: `train_fused_score.py`'s ablation drops `function_word_network` (gain below `ABLATION_MIN_AUC_GAIN`), so the committed model's `channel_order` is `["peer_centered_z", "compression"]`. The third channel is still implemented, tested, and computed on every scoring call (see the note near `CHANNEL_NAMES` in `original/fusion/channels.py` for why it's retained), but it does not feed this model's log-odds. Requires retained raw text, 3 authenticated baselines, and **exactly 8** eligible same-tenant peers (the artifact is calibrated at 8 references; below that it abstains rather than extrapolate). Never changes `deviation_score`, `quantum_fidelity`, or the recommended action — held by `tests/fusion/test_wiring.py`. The shipped artifact's own held-out AUC is **0.8907** (`provenance.held_out_auc` in the committed JSON, PAN cross-fandom hold-out, 2026-08-11 training run) — not the 0.889/three-channel figure an earlier draft of this row quoted from a since-superseded gate audit. **Not yet validated against real student submissions** — run `FUSED_SCORE_SHADOW=1` first. ⚠️ **The compression channel is not normalized for baseline length** (C1, 2026-08 fix pass): its distance is computed against `Profile.text`, an uncapped concatenation of every one of the claimed student's authenticated baselines, and that distance falls monotonically as the baseline grows (measured 0.799 at 3 baselines → 0.730 at 48 in the derivation corpus) — so a genuine student's score drifts over the course of a term purely as their own baseline accumulates, independent of anything about the submission. `threshold_fa5`/`threshold_fa1` were selected on the PAN corpus, where every author has exactly 3 baselines by construction, and are **not yet meaningful on real student data**, whose baseline counts vary and grow. Every `fused_scores` row persists `baseline_samples`/`reference_profiles` precisely so this confound can be regressed out of the shadow data before enablement is reconsidered — do not set `ENABLED` before that analysis lands. `FUSED_SCORE_SHADOW=1` remains safe (it changes nothing observable) and is the intended way to accumulate that data. |
| `FUSED_SCORE_SHADOW` | `0` | Computes and persists the fused score to `fused_scores` without attaching it (`result.fused_score` stays `None`). `channels_json` stores the peer-centered value for **every** computed channel (all of `channels.CHANNEL_NAMES`, currently 3), not just the ones the shipped model fuses — I1, 2026-08 fix pass — so a future ablation-revisit or refit has the full picture even though only `channel_order`'s subset feeds today's log-odds. Each row also carries `baseline_samples`/`reference_profiles` (C1) so the compression channel's baseline-volume confound (see `FUSED_SCORE_ENABLED`'s caveat) can be regressed out of the shadow data. Enablement is then one env flip with unbroken data continuity. |
| `FUSED_SCORE_MODEL_PATH` | unset | Path override for the committed `original/data/fused_score_v1.json`. The loader fails closed (→ `None`, identical to flag-off) on schema-version, channel-name, vector-length, threshold-monotonicity, or reference-prediction drift. Regenerate with `.venv/bin/python scripts/train_fused_score.py`. |
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
