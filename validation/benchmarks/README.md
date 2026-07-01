# Benchmark reports — how to read them

Each benchmark run drops a dated directory:

```
validation/benchmarks/<YYYY-MM-DD>/<dataset_label>/
  ├── report.json                # machine-readable, diff-able across runs
  ├── report.md                  # one-page human summary
  ├── roc_curve.svg              # ROC plotted from the existing roc_points
  ├── calibration_curve.svg      # reliability diagram (10 bins by default)
  ├── ablation.csv               # one row per tier: tier, ΔAUC, ΔBrier
  └── bias.csv                   # one row per (group, value): n, AUC, mean dev
```

These reports are git-ignored by default (see `.gitignore` at the repo root).
To commit a specific run as evidence (a buyer asked for the exact JSON
of the AUC you cited, e.g.), `git add` it explicitly.

---

## What every metric in the report means, in plain English

### `auc` — Area under the ROC curve

How well Original separates **authentic submissions** from **non-authentic
ones**, across every possible deviation threshold. 0.5 = a coin flip;
1.0 = perfect separation; anything ≥ 0.80 is "solid" for an authorship
system. The number stored is the standard sklearn-style AUC computed
over `(false-positive-rate, true-positive-rate)` pairs.

### `brier` — Brier score

Mean squared error between Original's predicted probability of authentic
(`authorship.authorship_probability`) and the actual outcome (1 if
authentic, 0 otherwise). **Lower is better.** A perfect predictor
scores 0.00; a "I always say 50% confident" baseline scores 0.25;
truly bad confident-and-wrong predictors approach 1.0.

A low AUC + low Brier means "confident calls, well-discriminated" — what
we want. A low Brier + high AUC means "well-calibrated but indecisive."
A high Brier + low AUC means the predictor is both wrong and confident.

### `calibration_curve` — reliability diagram

Ten equal-width bins of predicted probability. For each bin, the report
shows the **mean predicted probability** and the **fraction of submissions
in that bin that were actually positive**. A perfectly calibrated system
sits on the diagonal: bins where Original said "70% authentic" should
contain 70% authentic submissions. Bins above the diagonal are
**under-confident**; bins below are **over-confident**.

The SVG plots count as the dot size — small dots are sparsely-populated
bins (less trustworthy), big dots are well-populated.

### `threshold_metrics` — confusion at action thresholds

Action thresholds (from `original/constants.py`):
- `no_action`        — deviation below **0.40**
- `monitor`          — deviation **0.40 – 0.55**
- `schedule_conversation` — deviation **0.55 – 0.75**
- `escalate`         — deviation **above 0.75**

For each named threshold the report shows TP / FP / TN / FN /
precision / recall / accuracy / F1. The decision rule:
**deviation < threshold ⇒ predicted authentic**.

Look at `precision` at the `monitor` threshold to know how often
Original would correctly identify a submission as authentic when it
chooses not to flag it. Look at `recall` to know what fraction of
truly-authentic submissions Original would correctly call authentic.

### `ablation` — per-tier knock-out

Each row of `ablation.csv` (and the matching section of `report.md`)
zeroes out **one of Original's 17 tiers** in both the baseline vector
and the submission vector, then re-runs the calibration. We report the
resulting AUC and Brier deltas vs the no-ablation baseline run.

- **Large positive ΔAUC** (baseline_AUC − ablated_AUC > 0): that tier
  is doing real work. Removing it hurts accuracy.
- **Near-zero ΔAUC**: that tier contributes little; it might be safe
  to drop.
- **Negative ΔAUC** (ablated_AUC > baseline_AUC): removing the tier
  *helped*. That's a strong signal the tier's features are degenerate
  or noisy — investigate.

### `bias` — per-group AUC + FPR

Slices the corpus by manifest field (`native_english`, `ai_provider`,
`theological_tradition`, `word_count_bucket`) and reports per-group
AUC + mean deviation + false-positive-rate-on-authentic-only.

A healthy system has roughly equal per-group AUCs. Spreads >0.10
between groups warrant a closer look. The doc/calibration audit
(`docs/calibration/norm_bounds_calibration_2026-03-17.md`) already
flagged Tier 1 features as high-risk for non-native-English speakers —
the bias slicer surfaces that risk in every benchmark run.

---

## Pass criteria

### Test 1 (wide-dataset benchmark — RAID + PAN AV + M4)

| | Pass | Concern | Investigate |
|---|---|---|---|
| `auc` | ≥ 0.80 | 0.65–0.80 | < 0.65 |
| `brier` | ≤ 0.12 | 0.12–0.20 | > 0.20 |
| any per-group AUC spread | < 0.08 | 0.08–0.15 | > 0.15 |
| ablation ΔAUC (any tier) | < 0 means investigate that tier | | |

### Test 2 (public-author attribution — Wikisource + Gutenberg)

| | Pass | Concern | Investigate |
|---|---|---|---|
| top-1 accuracy | ≥ 0.70 | 0.50–0.70 | < 0.50 |
| mean rank of true author | ≤ 1.5 | 1.5–2.0 | > 2.0 |
| any per-author accuracy | ≥ 0.50 | 0.30–0.50 | < 0.30 |

---

## How to reproduce a report

Every report records its environment lock at the top of `report.json`:
SECRET_KEY (redacted), `ADAPTIVE_WEIGHTS_ENABLED`, `ENVIRONMENT`,
`ORIGINAL_DB`, and whether NumPy + Python random were seeded. Two runs
that share the same lock should diff-clean (modulo timestamp).

```bash
# Same dataset, same sample, same seed → should reproduce.
python -m validation.wide.run --dataset raid --sample 1000 > run1.json
python -m validation.wide.run --dataset raid --sample 1000 > run2.json
diff <(jq -S 'del(.generated_at)' run1.json) \
     <(jq -S 'del(.generated_at)' run2.json)   # expect: empty
```

If the diff is non-empty, the environment lock missed something — file
an issue against `validation/benchmark/reproducibility.py`.

---

## Adding a new dataset

1. Write an adapter in `validation/wide/<dataset>.py` that returns a
   ValidationManifest + a corpus directory in the same shape
   `validation/calibration.py:run_calibration()` expects.
2. Add a `DatasetSpec` entry in `original/lab/datasets.py` so the lab UI
   sees it.
3. Run `python -m validation.wide.run --dataset <dataset>` — the
   orchestrator picks it up automatically.

---

## Adding a public author to Test 2

The corpus is curated by hand in
`validation/public_authors/build_corpus.py`:

- Add an `EssayRef(...)` to `ESSAYS` if you can find a stable Wikisource
  URL.
- Add a `GutenbergWork(...)` to `GUTENBERG_WORKS` if you only have a
  Project Gutenberg ID — the script will chunk the full work into
  `n_chunks` essays automatically.

Re-run `python -m validation.public_authors.build_corpus` to fetch + regenerate
the manifest. Then run Test 2.
