# Longitudinal drift validation

This runner measures whether the report-only chronological model reduces
false alarms on later genuine writing without changing production scoring.

The manifest uses the standard validation `entries` array. Eligible entries
must have `label: "authentic"`, `author_id`, `filename`, and an ISO
`submitted_at`. At least six dated, authenticated, 300-word samples spanning
60 days are required before the model can select gradual drift.

Run:

```bash
.venv/bin/python -m validation.longitudinal.run \
  --corpus PATH_TO_TEXTS \
  --manifest PATH_TO_MANIFEST.json \
  --output validation/benchmarks/longitudinal.json
```

The report includes static versus drift-adjusted genuine flag rates and a
chronology-permutation diagnostic. It does not tune thresholds. Matched-peer
impostor trials remain the responsibility of `validation.verify`.
