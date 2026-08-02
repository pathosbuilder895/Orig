# 2026-08-01 public-author benchmark rerun — contamination before/after

The committed public-author corpus was found contaminated on 2026-08-01
(five modes: a Stephen Leacock essay filed under Douglass, a French
science-fiction novel filed under Edwards, Wikisource site chrome in every
Wikisource-sourced file, index/footnote back-matter chunked as James
"essays", and 6-41-word TOC stubs for mill/kempis). The corpus was rebuilt
from verified sources — see the `Rebuild contaminated public-author corpus`
commit and the header of `validation/public_authors/build_corpus.py`.

This directory holds the rerun on the clean corpus. This note compares it
against the previously recorded 2026-07-01 results and against a
measured-for-comparison run on the old contaminated corpus.

## Two invalidations, not one

Historical accuracy numbers were unreliable for **two independent
reasons**:

1. **Corpus contamination** (above) — affects everything ever measured on
   `validation/public_authors`.
2. **`ORIGINAL_DB=:memory:` store bug** — after WS-6 P6 removed the store's
   in-memory profile cache, every per-call SQLite connection to `:memory:`
   opened a fresh empty database, so every benchmark write was silently
   dropped: baselines "uploaded" then vanished, and every scoring call
   404'd → all-NaN deviations. Any harness run between WS-6 P6 and the
   `Fix ORIGINAL_DB=:memory:` commit produced garbage (a Test 2 run in that
   window reports top-1 = 13.6%, which is exactly the alphabetical-tie
   artifact of all-NaN scores). The 2026-07-01 verify reports predate the
   bug and are real measurements — of the contaminated corpus.

## Comparability caveats

The clean corpus is not entry-for-entry the old one, by necessity:

- **edwards** switched works: pg24962 (the French novel) → pg34632
  *Selected Sermons of Jonathan Edwards* (*Religious Affections* is not on
  Project Gutenberg).
- **douglass** and **thoreau** are newly eligible (11 authors vs 9): the
  old build left them with 1 baseline each after silent fetch failures.
- **james** parts are re-cut from prose only (the old parts 6-8 were the
  book's INDEX + FOOTNOTES sections).
- Editor/translator front matter (introductions by James M'Cune Smith,
  H. Norman Gardiner, W. Benham, H.R. James) is now excluded everywhere.

## Test 2 — top-1 attribution (pass ≥ 0.70)

No valid historical Test 2 record exists (see invalidation 2), so the
"before" column was measured on 2026-08-01 by running the fixed harness
against the old contaminated corpus extracted from git.

|                     | contaminated corpus | clean corpus |
|---------------------|--------------------:|-------------:|
| eligible authors    | 9                   | 11           |
| held-out essays     | 22                  | 27           |
| **top-1 accuracy**  | **45.5%**           | **70.4%**    |
| mean rank of true   | 2.50                | 1.63         |

Contamination *depressed* Test 2: garbage held-outs (an index, a French
novel chunk, TOC stubs) can't match their nominal author's baseline. The
clean corpus passes the ≥ 0.70 criterion.

## Binary verification (verify N3, no null model)

|                       | 2026-07-01 (contaminated) | 2026-08-01 (clean) |
|-----------------------|--------------------------:|-------------------:|
| authors               | 9                         | 11                 |
| same / diff pairs     | 22 / 176                  | 27 / 270           |
| median per-author AUC | 1.00 (IQR 0.95-1.00)      | 0.98 (IQR 0.88-0.99) |
| pooled AUC            | 0.8551 [0.776, 0.924]     | 0.8868 [0.793, 0.956] |
| pooled TPR @ FPR 1/5/10% | 0.23 / 0.59 / 0.59     | 0.37 / 0.67 / 0.67 |

Per-author AUC, old → new:

| author | old | new | reading |
|---|---|---|---|
| augustine | 1.00 | 1.00 | unchanged |
| boethius | 0.775 | 0.48 | honest number is worse — Books IV-V held-outs are genuinely hard |
| chesterton | 1.00 | 0.98 | ~unchanged |
| douglass | — | 1.00 | newly eligible |
| edwards | 1.00 | 0.83 | the old 1.00 was fake — it separated a FRENCH NOVEL from English impostors |
| emerson | 0.975 | 0.60 | old number inflated: every file shared identical Wikisource chrome, a spurious "authorial signature" |
| james | 0.47 | 0.99 | old number wrecked by index/footnote garbage held-outs |
| kempis | 1.00 | 1.00 | real prose now (was 6-17-word stubs) |
| mill | 0.95 | 0.96 | real chapters now (was 6-41-word stubs) |
| newman | 1.00 | 0.98 | ~unchanged |
| thoreau | — | 0.92 | newly eligible (cross-work: 3 different essays as baseline) |

Net: the pooled headline moved little (0.855 → 0.887), but that masks
large per-author corrections in both directions — two inflated 1.00s were
fake wins on garbage data, and james' 0.47 was a fake loss.

## Impostor-null A/B (run_null_model.py, N=3)

Measured by `validation/verify/run_null_model.py` (same scorer call yields
the flag-off deviation and the `NULL_MODEL=impostor` LLR — a true A/B).
Note: an earlier attempt at this rerun invoked `verify/run.py` with the
env var, which does not exercise the LLR path; that invocation was
discarded. The rerun finished shortly after midnight, so `generated_at`
inside the report reads 2026-08-02.

|                       | 2026-07-01 (contaminated) | 2026-08-01 (clean) |
|-----------------------|--------------------------:|-------------------:|
| impostor-arm pooled AUC | 0.8993 [0.809, 0.970]   | 0.9527 [0.920, 0.978] |
| baseline-arm pooled AUC (same run) | —            | 0.8883             |
| impostor-arm TPR @ FPR 1/5/10% | 0.18 / 0.77 / 0.82 | 0.48 / 0.67 / 0.85 |
| median per-author AUC | 1.00                      | 1.00 (IQR 0.96-1.00) |

On clean data the impostor null delivers a +0.064 pooled-AUC lift over the
flag-off baseline within the same run, and TPR at the strict 1% FPR
operating point more than doubles vs the contaminated measurement.

## Follow-ups

- The `validation/verify/run.py` same-work limitation still applies: 9 of
  11 authors draw baseline and held-out chunks from a single work
  (emerson and thoreau are the cross-work exceptions).
- The length-stability study reads `_full_work_cache.txt` directly and
  consumed the contaminated edwards/james caches; it is being re-checked
  separately.
