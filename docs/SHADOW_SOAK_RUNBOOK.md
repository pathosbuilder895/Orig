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

Do not set `BAYESIAN_PRIOR_ENABLED`, `FUSED_SCORE_ENABLED`,
`TOPIC_VARIANCE_INFLATION=on`, or `LLR_ACTION_MODE=blend` for this soak.
The flag-off/shadow-inert contracts are pinned in the genre dispatch, topic
inflation router, characteristic-weight wiring, fusion wiring, AI shadow, and
blend tests.

## Weekly read

```bash
render logs --tail 200000 > /tmp/pilot-shadow.log
.venv/bin/python scripts/shadow_soak_report.py --log /tmp/pilot-shadow.log --db "$DATABASE_URL"
```

Read “signal absent” as “the flag did not run in this log window,” never as a
zero rate. Decision signals:

- Genre: compare abstention with G8's 50% ceiling and inspect sermon-like
  `scholarly_essay`/`narrative_prose` claims.
- Topic: report mass above distance 0.25. Approximately zero means the
  mechanism is inert on pilot traffic.
- Characteristic weights: mostly abstain or near-zero active-feature
  dispersion means the mechanism is inert. Return this flag to `off` when
  its measurement ends because shadow performs a peer-state scan.
- Fused score: do not enable until the baseline-volume regression on real
  rows clears the C1 confound and a replacement artifact/thresholds exist if
  normalization changes.
- AI likelihood: require at least 30 instructor-labeled joins and authentic
  FPR within the model-card bar. Window values are low-confidence ordering
  hints within one document only.
- Bayesian prior: measure pool reachability offline; do not enable the prior
  to collect telemetry.

Record each verdict in the corresponding `CLAUDE.md` row and `MODEL_CARD.md`.
Fused shadow may stay on to grow its cheap longitudinal dataset; tear down
characteristic shadow after its latency-bounded measurement.

The peer-state scan benchmark is reproducible at the three pre-registered
volumes with:

```bash
.venv/bin/python scripts/benchmark_characteristic_shadow.py --backend sqlite
TERMSIM_BENCHMARK_DATABASE_URL="$LOCAL_POSTGRES_URL" \
  .venv/bin/python scripts/benchmark_characteristic_shadow.py --backend postgres
```

The 2026-08-26 SQLite fixture measured p95 2.08/2.42/32.59 ms at
50/500/5,000 profiles (`validation/characteristic_shadow_latency_2026-08-26.json`),
so the bounded-pilot decision is to retain the scan with a 100 ms p95 alert.
The Postgres measurement remains required before cutover; the campaign host's
Docker daemon was unavailable, and the script refuses to target any implicit or
production DSN. A Postgres result over the alert changes the decision to a bounded,
tenant-scoped peer-stat query before shadow is enabled.

## Other Postgres-ready checks

```bash
.venv/bin/python scripts/tier17_report.py --db "$DATABASE_URL"
.venv/bin/python scripts/measure_genre_prior_scope.py
```

Also rerun the Phase-8 drift gate against real uploads before any scoring-flag
default changes. No flag default is changed by this runbook.
