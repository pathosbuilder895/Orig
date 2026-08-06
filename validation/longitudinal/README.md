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

## Two separate drift models, two separate runners

This package holds two independent drift mechanisms that are easy to
conflate:

- **`original/quantum/longitudinal.py`** — the production ridge-shrunk linear
  trend over 109-feature-vector tiers {1,4,5,6,11}. `validation.longitudinal.run`
  (above) exercises this one. It is what ships behind
  `LONGITUDINAL_DRIFT_ENABLED`.
- **`validation/longitudinal/dirichlet_multinomial.py`** — the validation-only
  Dirichlet-multinomial + BIC model this repository cites as "Ross (2020)"
  (`docs/adr/008-longitudinal-drift-reporting.md`). It is NOT wired into
  `validation.longitudinal.run` and never was. Before 2026-08-05 it had only
  ever been exercised by 4-category toy matrices in its own unit tests, which
  is why an unbounded-`maxfun` bug that forced every real-vocabulary fit
  (106 categories, 212 drift parameters) to report `converged_drift=False` —
  and therefore always select `"constant"`, however strong the true signal —
  went undetected. It is not production code and has no promotion path yet.

## Smoke corpus (`build_smoke_corpus.py`, `dm_smoke_run.py`)

Neither drift model had ever been run against real dated prose. The six-author
`validation/public_authors/cross_work_corpus/` corpus can't be used for this:
each author has only two works — two time points — below
`LongitudinalConfig.min_samples_for_trend` (6), so no probe is ever scored.

`build_smoke_corpus.py` fetches eight Mark Twain novels from Project Gutenberg
with real, hand-verified first-publication years (1869-1896) — deliberately
NOT Project Gutenberg's own "issued" date, which is the ebook's 2004 release
date, not the work's original publication date; using it would replace 27
years of real authorial evolution with a few weeks of PG's digitization batch
order. `dm_smoke_run.py` then runs the Dirichlet-multinomial model against it
directly (the runner `validation.longitudinal.run` above does not, per the
previous section). Committed outputs: `smoke_manifest.json`,
`smoke_corpus/twain/*.txt`, `smoke_report.json` (production ridge model),
`dm_smoke_report.json` (Dirichlet-multinomial model).

This is a wiring smoke test, not a locked benchmark: 8 documents from one
author is far below anything that could support a promotion decision. It
answers only "does the pipeline run and does the fit converge," not "is this
author's drift real." Regenerate with:

```bash
.venv/bin/python -m validation.longitudinal.build_smoke_corpus
.venv/bin/python -m validation.longitudinal.dm_smoke_run
```
