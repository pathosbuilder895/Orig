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

## Other Postgres-ready checks

```bash
.venv/bin/python scripts/tier17_report.py --db "$DATABASE_URL"
.venv/bin/python scripts/measure_genre_prior_scope.py
```

Also rerun the Phase-8 drift gate against real uploads before any scoring-flag
default changes. No flag default is changed by this runbook.
