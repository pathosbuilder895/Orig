# Plan 04 — TermSim: an ecological validation harness that tests the system the way it will be used

> **For agentic workers (Codex):** This is the campaign's flagship build. Goal-oriented
> brief; goals T1–T6 are ordered (each consumes the previous), T7–T8 follow once the
> harness runs. Read the Motivation section before writing code — the design decisions
> below exist because specific past measurements failed in deployment-shaped ways, and
> the harness is only worth building if it preserves those failure modes.

**Goal:** A deterministic, seeded simulator — `validation/termsim/` — that replays an
entire academic term through the **real** API surface (baseline ingestion, scoring,
blend, drift gate, null pools, priors — the actual FastAPI app against a real
database), for whole cohorts of synthetic students built from committed corpora, and
scores the system on **deployment outcomes**: per-student-per-term false-flag
probability at each action tier, time-to-detection for injected misconduct scenarios,
cold-start behavior, and score drift as baselines grow. One command, a config matrix
over env flags, a scorecard per config, and new registered gates on top.

**Why this and not more corpus AUC:** Turnitin-style benchmarks — and every number in
this repo's MODEL_CARD so far — score one-shot document classification: here is a text,
here is a reference set, produce a score, compute AUC/FPR over a pile of such trials.
The product does not work like that. It accumulates baselines over months, scores each
submission against a *moving* profile, pools nulls per-tenant, blends priors on cold
start, applies a drift-hygiene gate to its own inputs, and emits *actions* (whose costs
are wildly asymmetric), not scores. The repo's own history shows the gap is where the
bodies are — each of these was invisible to one-shot benchmarking and was caught late
or by luck:

- The fused score's compression channel drifts monotonically as a genuine student's
  baseline grows (0.799 @ 3 baselines → 0.730 @ 48) — a *time-series* failure no
  fixed-baseline corpus trial can exhibit.
- The typicality axis is mathematically inert at pilot N (p-floor 1/(N+1) above every
  threshold) — invisible unless you evaluate at realistic, growing N.
- The Bayesian cold-start prior *regressed* AUC by 0.25 — a cohort-composition effect.
- `deviation_score` alone is **worse than chance (AUC 0.39)** on cross-genre
  same-author submissions — surfaced only when someone simulated "the student's next
  assignment is in a genre their baseline lacks," which is a *curriculum* event.
- The drift gate held 28% of one real-register author's uploads at the old threshold —
  a per-student longitudinal rate, not a corpus statistic.

TermSim's job is to make this class of failure cheap to find *before* real students are
exposed to it, and to make "flag X is safe to enable" a scorecard diff instead of an
argument.

**Architecture:** A new `validation/termsim/` package that (a) compiles committed
corpora into student personas, (b) generates a seeded term script of dated events,
(c) executes the script through the real app (FastAPI `TestClient`; SQLite by default,
Postgres via the existing `scripts/local_postgres.sh` machinery for the
persistence-faithful run), (d) computes outcome metrics, (e) renders scorecards and
evaluates new gates T-1…T-4 registered in `gate_contracts.py`.

## Global constraints

Same base set as Plan 01 (venv absolute path; 11–12 min full suite; postgres marker
tests when persistence is touched; coverage margin ~1.6 pt — this plan adds a lot of
code, so it adds a lot of tests; `git rm` not `rm`; no pushes to main; commit style).
Plus, specific to this plan:

- **Go through the API, not the internals.** Ingest baselines and score via the real
  routes (`POST /students/{id}/baseline…`, `POST /students/{id}/score`, the blend
  route) on a `TestClient` app instance. This is what makes the harness ecological —
  store caching, manifest resolution, null-pool floors, tenant scoping, and the drift
  gate all engage exactly as deployed. It also sidesteps the known benchmark trap
  (`score()` no longer reads `os.environ`; `validation/calibration.py`'s
  `run_calibration()` silently measures flag-off) because the app builds its own
  `ScoringConfig` per request the same way production does.
- **Flags via app construction, not ambient env mutation mid-run:** build one app/
  config per matrix cell; never flip env vars inside a running cell.
- **Determinism is a feature requirement:** every run takes a `--seed`; export
  `PYTHONHASHSEED=0` at entry and assert it; two runs with the same seed and config
  must produce byte-identical metrics JSON (coordinate with Plan 02 C9, which is
  hunting the known nondeterminism — until it lands, the assertion is your guard).
- **Honesty labels:** every scorecard carries a fixed header block stating that
  personas are corpus-derived synthetic students (19th-c. PD prose + the committed
  seminary corpus), not real student data, and that absolute rates do not transfer —
  *differences between configs* on identical scripts are the meaningful output. This
  harness complements, and cannot replace, the pilot shadow soak (Plan 03).
- **Measurability rules apply:** any per-feature aggregation goes through
  `validation/measurability.py`'s checks — blank/disabled columns must raise, not
  average in.
- New gates need failure witnesses in `validation/gate_contracts.py` (the suite
  enforces this via `tests/test_gate_falsifiability.py`).

---

## T1. Personas: corpus authors → synthetic students

`validation/termsim/personas.py`. Compile committed corpora into a persona pool:

- Sources: `validation/public_authors/` (11 authors), `validation/genre_2026-08/`
  (labeled, multi-genre), `validation/corpus/` (the seminary corpus — the closest
  thing to target-register writing), `validation/plato/` (a longitudinal author),
  Plan 02 C5's Chesterton/Newman analogue corpus and C6's sermon corpus when they land.
- Each persona = an author with an ordered pool of submission-sized documents.
  Chunk long works into 400–1,500-word pieces at paragraph boundaries; respect the
  300-word attribution floor; carry per-doc provenance and (where known) genre labels.
- Personas declare capabilities the script generator can query: `n_docs`,
  `genres_available`, `has_longitudinal_order` (Plato: yes, by dialogue period).
- The pool ships as a deterministic build step (`personas.py --build` writes a
  manifest under `.benchmark_cache/termsim/`; nothing corpus-derived is recommitted).

**Acceptance:** `--build` runs from a fresh checkout (given Plan 02's committed
corpora) and reports pool size ≥ 25 personas, ≥ 15 docs median per persona; unit tests
cover chunking floors and manifest determinism.

## T2. Term scripts: seeded curricula of dated events

`validation/termsim/script.py`. A term script is a JSON-serializable list of dated
events per student per tenant, generated from `(seed, scenario_config)`:

- **Tenant shapes:** cohorts of 3, 8, and 25 students (below the null-pool floor, at
  the fused-score calibration point, and comfortable), each its own tenant id so
  tenant scoping and per-tenant pools are exercised for real.
- **Timeline:** 15 weeks. Onboarding: 3 authenticated baselines in week 0 (the modal
  pilot profile). Then one submission every ~1.5 weeks, with realistic dates (the
  longitudinal expert needs ≥60-day spans and dated samples). Optionally, accepted
  submissions accrete to the baseline (two modes: accrete / frozen — both run, the
  delta is itself a metric, see T5's drift slope).
- **Curriculum events:** at scripted weeks, the assignment changes genre (drawn from
  the persona's other genres — the cross-genre AUC-0.39 failure must be reproducible)
  and topic (drawn from a different work by the same author).
- **Scenarios** (each student is assigned exactly one for the term):
  - `HONEST` — every submission is the persona's own writing. This population is the
    denominator for every false-positive claim.
  - `GHOST` — from week `w` (sampled mid-term), submissions come from a different
    persona in the same register (seminary↔seminary, essayist↔essayist).
  - `AI` — from week `w`, submissions come from the committed AI-generated pool
    (`validation/corpus/ai_*.txt`; extend via the AuTexTification-adjacent material
    only if licensing is clean — otherwise the committed pool suffices).
  - `HYBRID` — the persona's own text passed through mechanical paraphrase
    (`distort_corpus.py` output from Plan 02 C10). **Label it a proxy everywhere it
    appears** — the same honesty rule G2b's report follows; it is not an
    LLM-paraphrase claim.
  - `COLDSTART` — only 1–2 onboarding baselines (below `TRAJECTORY_MIN_SAMPLES` and
    the flat-σ prior regime), honest thereafter; measures the thin-baseline experience.
  - `TRANSFER` — baselines in one genre, entire term's submissions in another
    (`genre_covered_by_baseline` false all term).

**Acceptance:** same `(seed, config)` → byte-identical script JSON; property tests
that every scenario's constraints hold (GHOST swap week in bounds, COLDSTART baseline
count, floors respected); a `--describe` mode prints a human-readable term calendar.

## T3. Runner: execute a script through the real app

`validation/termsim/runner.py`. For each matrix cell (flag config × script):

- Build the FastAPI app with an isolated fresh database. Default backend SQLite
  (fast path); `--backend postgres` uses `scripts/local_postgres.sh` + a per-run
  schema/database so the production persistence path is exercised (postgres-marked in
  tests). Never touch `profiles.db` or any existing file.
- Replay events in date order via HTTP: enroll → upload baselines (authenticated
  provenance) → score each submission (capture the full response: `deviation_score`,
  `recommendation`, `llr_deviation_score`, typicality fields, drift-gate outcome,
  every expert's attach/abstain state) → on accrete-mode acceptance, add to baseline.
- **Feature-vector cache:** extraction dominates cost. Cache extracted vectors keyed
  by `sha256(text) + FEATURE_DIM + extraction-relevant config` under
  `.benchmark_cache/termsim/vectors/`. The clean seam is a test-only extraction hook
  (e.g., monkeypatched extractor in the harness app factory) that consults the cache —
  document exactly where the seam is so it's auditable; **never** ship a cache path in
  production code. Comparison features (baseline-dependent) are computed fresh — only
  the 102 base dims are cacheable (`BASE_FEATURE_DIM`); measure whether that still
  wins (it should — tiers 5/8/13 are the expensive ones).
- **Parallelism:** run matrix cells and tenants as separate worker processes
  (`concurrent.futures`), one isolated DB each. Target: the standard matrix (6
  scenarios × 3 cohort shapes × ~6 flag configs) in **≤ 15 minutes** on a laptop with
  a warm vector cache; print per-cell timing so regressions are visible.
- Emit one JSONL event log per cell: `(student, week, scenario, response-extract)`.

**Acceptance:** a smoke config (1 tenant, 4 students, 6 weeks) runs green in CI-scale
time (< 60 s warm) under both backends; full standard matrix meets the time target
locally; runner tests cover isolation (two cells can't share a DB) and cache
correctness (warm vs cold runs byte-identical metrics).

## T4. Outcome metrics

`validation/termsim/metrics.py`, computed from the event logs:

- **Honest-term flag probability** — for each action tier `a`:
  `P(an HONEST student's term contains ≥1 submission with action ≥ a)`, per cohort
  shape and per flag config, with Wilson intervals. This is the number a dean actually
  experiences; per-submission FPR understates it by roughly the number of submissions
  per term.
- **Time-to-detection** — for GHOST/AI/HYBRID: submissions elapsed between scenario
  onset week `w` and first action ≥ `monitor` and ≥ `schedule_conversation`;
  censored-at-term-end handled explicitly (report the caught fraction and the median
  among caught).
- **Tier precision** — among all submissions at action ≥ `a`, the fraction whose
  student is in a misconduct scenario at that date.
- **Baseline-growth drift** — for HONEST accrete-mode students: slope of
  `deviation_score` (and each attached expert score) against baseline count. The
  main-path analogue of the fused C1 confound. Near-zero slope is the pass condition.
- **Cold-start / transfer deltas** — honest-term flag probability for COLDSTART and
  TRANSFER vs HONEST; the TRANSFER row is the deployed measurement of the cross-genre
  failure and of `LLR_ACTION_MODE=gate`'s real-world value.
- **Mechanism engagement** — drift-gate hold rate on honest uploads (the 0.30
  threshold's longitudinal check); null-pool/prior/fused/typicality abstain rates by
  cohort size (does the 3-student tenant ever get an informative null?); inflation
  fire rate; blend shift-detection rate on single-author documents (its false-positive
  side has never been measured longitudinally).

**Acceptance:** metrics module is pure (event-log JSONL in, metrics JSON out) with
golden-file tests; every metric that aggregates per-feature data passes through the
measurability layer; intervals present on every rate.

## T5. Scorecards and the config matrix

`validation/termsim/scorecard.py` + `matrix.py`:

- A matrix config names its cells explicitly. Standard matrix, first edition:
  `baseline` (pilot defaults: manifest+adaptive+impostor-null, `LLR_ACTION_MODE=gate`),
  `llr-shadow` (the pre-2026-08 behavior, as control), `no-context` (all context flags
  off — the Phase-1 core), and one cell per candidate mechanism under evaluation
  (`TOPIC_VARIANCE_INFLATION=on`, `CHARACTERISTIC_WEIGHTS=on`,
  `GENRE_RESOLVER_V2=on`) — each diffed against `baseline` on identical scripts.
- Scorecard per cell: MD + JSON, the honesty header (see Global constraints), the
  metric tables, and a diff section against `baseline` with the largest movements
  first. The MD is written for the founder to read without a decoder ring — full
  sentences, thresholds restated inline.
- `python -m validation.termsim run --matrix standard --seed 20260826` is the whole
  interface; `--cell` runs one.

**Acceptance:** standard matrix produces scorecards; diff section verified by a test
that perturbs one flag and detects the expected direction of movement on the TRANSFER
row (a real end-to-end assertion: `gate` mode must reduce TRANSFER honest-flag
probability vs `llr-shadow`, per the already-measured 50%→42% corpus result).

## T6. Gates on top: T-1 … T-4, registered and falsifiable

`validation/termsim/gate.py`, wired into `calibration_gate.py`'s `run_all()` as a new
section (three-valued verdicts like everything else) and registered in
`gate_contracts.py` with failure witnesses:

- **T-1 honest-term budget:** HONEST `P(term ever ≥ schedule_conversation) ≤ 10%` and
  `P(term ever ≥ escalate) ≤ 2%` at cohort 8+, baseline config. (Initial bars —
  restate them in the gate's docstring as provisional, same convention as the
  typicality thresholds; they exist to catch regressions, not to certify absolutes.)
- **T-2 detection floor:** GHOST caught-by-term-end ≥ 60% at ≥ monitor under the
  baseline config. (AI/HYBRID reported but ungated in v1 — their generators are
  narrow; gating them would certify against a proxy.)
- **T-3 growth neutrality:** |baseline-growth drift slope| for HONEST accrete students
  below a bound calibrated so the known-bad fused compression channel **fails it**
  when attached — that's the gate's failure witness, and it's a real one.
- **T-4 cold-start parity:** COLDSTART honest-term flag probability ≤ 2× HONEST's.
- Each gate is `uninformative` (never `pass`) when its scenario count is under a
  minimum-N floor, when the vector cache was cold-invalid, or when determinism
  asserts failed — the same honesty machinery the battery already uses.

**Acceptance:** `tests/test_gate_falsifiability.py` passes with the four new
witnesses; `python -m validation.calibration_gate --strict` includes the T-gates;
T-3's witness demonstrably fails when the fused channel is wired in un-normalized.

## T7. First full campaign run + report

Run the standard matrix at three seeds. Commit
`validation/termsim/reports/2026-XX-XX-first-light.md`: per-config scorecard links,
the cross-seed stability of every gated metric, and a ranked list of surprises (any
mechanism whose TermSim behavior contradicts its corpus-benchmark story gets a
dedicated paragraph). This report is the explainer artifact's "what the new harness
found" section — write it to be read.

**Acceptance:** committed report; every number traceable to a scorecard JSON in
`.benchmark_cache` by seed + config hash recorded in the report.

## T8. Institutionalize: the pre-enablement bar

Add a section to `validation/README.md` and a row-note pattern to CLAUDE.md's flag
table: from now on, a score-changing flag's enablement case consists of (1) its
corpus gate(s) pass, (2) its TermSim scorecard diff is acceptable on the standard
matrix, (3) its pilot shadow soak (Plan 03) shows the mechanism is live and sane on
real traffic. Update the rows for `TOPIC_VARIANCE_INFLATION`,
`CHARACTERISTIC_WEIGHTS`, and `GENRE_RESOLVER_V2` to reference their TermSim cells.

**Acceptance:** docs updated; the three flag rows point at real scorecards.

---

## Out of scope

- Real-traffic measurement (Plan 03 owns the soak; TermSim's honesty header exists
  precisely because it is not that).
- LLM-generated paraphrase or LLM-simulated students — worth a future extension, but
  it imports a licensing/provenance problem and a "which generator" confound; v1
  certifies nothing it can't source from committed material.
- Changing any production scoring behavior. TermSim only ever *reads* the system.
