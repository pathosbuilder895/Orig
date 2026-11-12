# Original used as intended on a scholarly same-author corpus

| | |
|---|---|
| **Tool** | Claude Code; `validation/scholarly/intended_use.py` run on this repository at `main` after PR 335 |
| **Date** | 2026-11-12 |
| **Question** | When Original is used as intended (a baseline from an author's past papers, then a new paper by the same author or by someone else), how often does the existing flags-off scorer flag honest writers, how often does it flag other writers, and what does a threshold chosen on a separate calibration partition do? |
| **Decision it informs** | Whether the product's flag bands are usable when past papers are long and the new paper is short; what to pre-register before opening `locked_test` (`validation/scholarly/README.md`, "Partitions"). Follows `docs/research/2026-11-10-opportunity-mask.md`. |

**This is a description of the existing scorer, not a validation.** Nothing under
`original/` changed, nothing was tuned, and nothing was registered in
`validation/calibration_gate.py`. **Academics are not students**, and formal academic
prose is the register where published stylometric methods are weakest. These numbers say
how the scorer behaves on scholarly writing, not how it behaves on student writing.

## Method

* Corpus: `validation/scholarly/manifest/` (humanities 385 authors, science 130), each
  author with at least 6 usable single-author papers. Restore and verify found every
  manifest paper present and hash-matched (humanities 3,190 of 3,190, science 1,032 of
  1,032; nothing restored, mismatched or unreachable), so no author fell below 6 papers.
* Per author: 4 past papers form the baseline, 2 held-out new papers by the same author
  are scored (honest), and 5 other authors' new papers are scored against the same
  baseline (probes). No paper is on both sides. Three length configurations: 300 vs 300
  words, 1200 vs 1200, and 1200-word past papers against a 300-word new paper.
* Scorer: `ScoringConfig()` defaults with every research flag in CLAUDE.md unset. spaCy
  `en_core_web_sm` was installed; sentence-transformers was not, so Tier 10 used its
  TF-IDF fallback.
* "Flagged" = the product's recommended action is `schedule_conversation` or `escalate`.
  AUC is of `deviation_score`.
* Seeds 7, 11 and 23 (they change which papers are past or new and where each cut
  starts), pooled by author. 95% intervals are author-level bootstraps (1,000 resamples
  of authors, each carrying all of its documents from every seed).
* Partitions are fixed by a hash of the author id. **Calibration** chose one thing only:
  per collection and configuration, the `deviation_score` threshold giving a 5% honest
  flag rate there (95th percentile of calibration honest scores). The thresholds were
  committed (commits `5a0a520`, `2945c93`) before the development partition was scored
  against them. **Development** reports the product's own behaviour and the out-of-sample
  rates at the calibration threshold. **`locked_test` was not opened.**
* Check: seed 7 on development reproduces the committed 2026-11-11 baselines exactly.

## Humanities (never pooled with science)

Product flag bands, as shipped:

| configuration | partition | authors | honest flag rate | other-writer catch | AUC |
|---|---|---|---|---|---|
| 300 vs 300 | development | 157 | 10.2% [8.4, 12.1] | 37.2% [34.6, 40.1] | 0.751 [0.730, 0.772] |
| 1200 vs 1200 | development | 157 | 5.8% [4.1, 7.5] | 44.8% [41.8, 47.9] | 0.860 [0.842, 0.878] |
| 1200 past vs 300 new | development | 157 | **73.5%** [70.3, 76.6] | 93.5% [92.2, 94.7] | 0.745 [0.726, 0.766] |
| 300 vs 300 | calibration | 112 | 10.7% [8.5, 13.0] | 35.1% [32.0, 38.3] | 0.745 [0.719, 0.771] |
| 1200 vs 1200 | calibration | 112 | 5.8% [3.9, 8.0] | 44.5% [41.1, 47.9] | 0.857 [0.836, 0.876] |
| 1200 past vs 300 new | calibration | 112 | 74.0% [70.1, 77.5] | 93.9% [92.6, 95.3] | 0.738 [0.712, 0.763] |

At the threshold chosen on calibration (development is the out-of-sample check):

| configuration | threshold | calibration honest / catch (in-sample) | development honest | development catch |
|---|---|---|---|---|
| 300 vs 300 | 0.631955 | 4.9% / 20.2% | 4.6% [3.3, 5.8] | 21.7% [19.4, 24.1] |
| 1200 vs 1200 | 0.604764 | 4.9% / 41.6% | 5.4% [3.8, 6.9] | 42.6% [39.7, 45.6] |
| 1200 past vs 300 new | 0.722117 | 4.9% / 18.8% | 4.1% [3.0, 5.2] | 22.4% [19.9, 25.0] |

## Science (never pooled with humanities)

Product flag bands, as shipped:

| configuration | partition | authors | honest flag rate | other-writer catch | AUC |
|---|---|---|---|---|---|
| 300 vs 300 | development | 61 | 6.8% [4.6, 9.3] | 37.9% [33.9, 42.7] | 0.805 [0.777, 0.835] |
| 1200 vs 1200 | development | 61 | 2.7% [1.1, 4.6] | 52.7% [48.1, 57.3] | 0.906 [0.885, 0.926] |
| 1200 past vs 300 new | development | 61 | **64.2%** [57.4, 70.2] | 93.9% [92.1, 95.4] | 0.814 [0.786, 0.843] |
| 300 vs 300 | calibration | 36 | 4.2% [1.8, 6.5] | 31.5% [25.4, 38.0] | 0.756 [0.713, 0.802] |
| 1200 vs 1200 | calibration | 36 | 1.8% [0.5, 3.7] | 38.5% [31.3, 46.5] | 0.877 [0.841, 0.913] |
| 1200 past vs 300 new | calibration | 36 | 67.6% [59.2, 75.5] | 89.1% [85.0, 92.8] | 0.754 [0.710, 0.802] |

At the threshold chosen on calibration:

| configuration | threshold | calibration honest / catch (in-sample) | development honest | development catch |
|---|---|---|---|---|
| 300 vs 300 | 0.598387 | 4.6% / 32.4% | 6.8% [4.6, 9.3] | 38.4% [34.4, 43.2] |
| 1200 vs 1200 | 0.580644 | 4.6% / 48.5% | 5.2% [2.7, 7.6] | 63.2% [59.0, 67.3] |
| 1200 past vs 300 new | 0.692789 | 4.6% / 35.4% | 6.6% [3.5, 9.3] | 44.0% [40.0, 48.1] |

## What it shows

1. **Long past papers against a short new paper break the shipped flag bands.** About
   three in four honest humanities writers (73.5%) and two in three honest science writers
   (64.2%) are flagged. This reproduces the 2026-11-10 opportunity-mask finding (78% on 13
   authors) on 157 and 61 independent authors.
2. **The failure is mostly calibration, partly discrimination.** At matched lengths the
   shipped bands are already near a 5% honest rate. With the length mismatch, a threshold
   moved to 0.72 (humanities) or 0.69 (science) restores about 5% honest flags out of
   sample, but the AUC is only 0.75 (humanities) and 0.81 (science), so the catch rate
   falls to 22% and 44%. Fixing the threshold alone would leave a weak test.
3. **Length helps more than anything else here.** 1200 vs 1200 gives the best separation
   in both collections (AUC 0.86 and 0.91). A 300-word new paper carries little signal
   even against matched 300-word past papers (AUC 0.75 and 0.81).
4. **Calibration thresholds transfer.** Development honest rates at the calibration
   thresholds land between 4.1% and 6.8% against a 5% target, inside or near the
   intervals. Science calibration has only 36 authors, so its thresholds are the least
   certain.

## Limits

* Academics are not students; formal academic prose is the register where published
  stylometric methods are weakest. No number here transfers to student writing without a
  student corpus.
* One author's honest documents come from the same author's other papers, often on
  related topics; probes come from other scholars in the same broad collection, not
  necessarily the same subfield. Topic, not style, may drive part of the separation.
* Science papers lose inline mathematics in cleaning, leaving gaps in sentences.
* Five lower-priority findings from the PR 335 review remain open: Greek words are removed
  from humanities text, the manifest does not record its paper cap, the original
  `baseline.py` clears only two flags (this runner clears all), the locked-partition gate
  sits only in `load_trials`, and one test is a source grep.
* Seeds share authors, so pooled intervals reflect author variation, not seed variation;
  per-seed values are in the result files.

## Files

* `validation/scholarly/intended_use.py`: the runner.
* `validation/scholarly/intended_use_thresholds_{humanities,science}.json`: thresholds
  chosen on calibration, committed before development scoring.
* `validation/scholarly/intended_use_{collection}_{partition}_2026-11-12.json`: all
  results, per seed and pooled.
