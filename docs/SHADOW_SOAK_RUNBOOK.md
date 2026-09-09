# Pilot shadow-soak runbook

Run only after the DPA is signed and the pilot is on Postgres. Shadow modes
collect evidence without changing the production score or action.

## Configure

```env
GENRE_RESOLVER_V2=shadow
TOPIC_VARIANCE_INFLATION=shadow
CHARACTERISTIC_WEIGHTS=shadow
FUSED_SCORE_SHADOW=1
AI_LIKELIHOOD_SHADOW=1
```

Do **not** set `BAYESIAN_PRIOR_ENABLED`, `FUSED_SCORE_ENABLED`,
`TOPIC_VARIANCE_INFLATION=on`, or `LLR_ACTION_MODE=blend` for this soak. The
byte-identical / flag-off-inert contracts above are pinned in
`tests/context/test_genre_dispatch.py`,
`tests/quantum/test_topic_variance_inflation.py`,
`tests/test_characteristic_weights_wiring.py`, `tests/fusion/test_wiring.py`,
and `tests/test_ai_likelihood_shadow.py` / `tests/context/test_blend.py`.

## Weekly read

```bash
render logs --tail 200000 > /tmp/pilot-shadow.log
.venv/bin/python scripts/shadow_soak_report.py \
  --log /tmp/pilot-shadow.log --db "$DATABASE_URL" --out shadow_week_N.json
```

`--db` accepts either a bare SQLite path or a `postgres://`/`postgresql://`
URL — both go through the same SQLAlchemy query layer, so the report reads
identically off either backend. Omit `--out` to print to stdout.

Read `"signal_absent": true` as "the flag did not run in this log/DB window,"
never as a zero rate — the report distinguishes the two explicitly at every
section. Decision signals, one per report section:

1. **Genre** — compare `abstention_rate` against G8's 50% ceiling.
   `sermon_watch.v1_sermon_to_v2_scholarly_or_narrative` is the specific
   count to watch: v2 carries no `sermon` class, so a genuine sermon
   landing on `scholarly_essay` or `narrative_prose` (rather than
   `unknown`) is the known taxonomy gap CLAUDE.md names as "the first thing
   to look for in the shadow soak."
2. **Topic** — `share_above_0_25` near zero means the mechanism is a
   production no-op regardless of G7's corpus result (the same trap
   `GENRE_INVARIANT_WEIGHTS_ENABLED` fell into).
3. **Characteristic weights** — mostly `abstain` or median dispersion near
   zero over active features means the mechanism is inert. Return this flag
   to `off` when its latency-bounded measurement window ends.
4. **Fused score** — `baseline_volume_confound` regresses the compression
   and fused-log-odds channels on baseline count, reporting the implied
   3→30-baseline shift as a fraction of the FA5→FA1 threshold gap when the
   fused artifact's thresholds are available. `verdict: "uninformative"`
   below four complete rows is a real state, not a bug. Do not enable
   `FUSED_SCORE_ENABLED` until this regression on real rows clears the C1
   confound and, if normalization changes, a refit artifact ships.
5. **AI likelihood** — `go_no_go` is the real go/no-go computation, joined
   against instructor-corrected `fidelity_scores.is_authentic`
   (`scripts/shadow_report.py`, aggregate-only — no identifier survives
   into the report). Require at least 30 instructor-labeled joins and
   authentic FPR within the model-card bar before citing it. If the pilot
   database has no `fidelity_scores` table yet, the section reports
   `gate_note` instead and cannot compute real-world FPR. Window-level
   values attached to the blend endpoint are separate, low-confidence
   ordering hints within one document only — never comparable across
   documents or to the document-level bands above.
6. **Bayesian prior scope** — `bayesian_prior_scope` runs
   `scripts/measure_genre_prior_scope.py` as a read-only offline subprocess
   against the same database and reports its output verbatim (or an error).
   This flag changes scores; never enable it just to collect this number.

Record each verdict in the corresponding `CLAUDE.md` row and `MODEL_CARD.md`.
Fused shadow may stay on indefinitely to grow its cheap longitudinal
dataset; tear down characteristic shadow once its latency measurement ends.

## Characteristic-weight shadow cost

Any non-`off` `CHARACTERISTIC_WEIGHTS` value makes `students_scoring.py`
build the impostor pool — a full peer-state table scan
(`repository.all_states()`) — on every scoring request that would
otherwise skip it. `original/quantum/impostor_cache.py` amortises this:
under `CHARACTERISTIC_WEIGHTS=shadow` with `NULL_MODEL != impostor`, the
built pool is cached per (tenant, student) for 30 seconds and invalidated
immediately on that tenant's next baseline write
(`original/routers/_shared.py`). Enabled/`on` mode and the action-capable
impostor null model always rebuild fresh — the cache only ever touches the
report-only shadow preview.

The measured cold-cache cost — i.e. exactly what the cache amortises — is
reproducible with:

```bash
.venv/bin/python scripts/benchmark_characteristic_shadow.py --backend sqlite
TERMSIM_BENCHMARK_DATABASE_URL="$LOCAL_POSTGRES_URL" \
  .venv/bin/python scripts/benchmark_characteristic_shadow.py --backend postgres
```

The 2026-08-26 SQLite fixture measured p95 2.08/2.42/32.59 ms at
50/500/5,000 profiles (`validation/characteristic_shadow_latency_2026-08-26.json`).
Because the cache only ever removes *repeat* scans inside a 30 s window, that
number is still the right one to alert on — it is the cache-miss cost, not
the amortised average. Keep the 100 ms p95 alert on cache-miss latency during
the soak. The Postgres measurement remains required before cutover; the
campaign host's Docker daemon was unavailable when the SQLite number was
taken, and the script refuses to target any implicit or production DSN. A
Postgres cache-miss result over the alert would mean tightening the query
(a bounded, tenant-scoped peer-stat query) rather than the TTL.

## Other Postgres-ready checks

```bash
.venv/bin/python scripts/tier17_report.py --db "$DATABASE_URL"
.venv/bin/python scripts/measure_genre_prior_scope.py
```

Also rerun the Phase-8 drift gate against real uploads before any
scoring-flag default changes. No flag default is changed by this runbook.
Human teardown is limited to changing Render flags. Never copy raw pilot
rows or student identifiers into reports or tickets — `shadow_soak_report.py`
is built to make that unnecessary; if a manual query ever seems needed, that
is a sign the report is missing a section, not a reason to run the query.
