# A learned same-author verifier against a 5% honest flag / 85% catch target

| | |
|---|---|
| **Tool** | Claude Code; `validation/scholarly/verifier.py` on the scholarly corpus |
| **Date** | 2026-11-12 |
| **Question** | Can a verifier built from the scorer's features plus standard authorship signals reach a 5% honest flag rate with an 85% other-writer catch rate, and where? |
| **Decision it informs** | Whether a learned verifier is worth proposing as a research channel next to Original's deviation score. Follows `docs/research/2026-11-12-scholarly-comparison-adjustments.md`. Nothing in `original/` changed and no flag was enabled. |

**Academics are not students**, and formal academic prose is the register where published
stylometric methods are weakest. This is validation-only research code; the product is
unchanged. `locked_test` was not opened.

## Method

* Per trial (4 past papers cut to the new paper's length, 2 honest new papers): signals per
  new paper are the scorer's per-feature |z| against the author's length-matched baseline and
  against a peer pool; character 3-5-gram, topic-masked character 3-6-gram (text distortion:
  content words replaced by their shapes), part-of-speech 1-3-gram and function-word channels,
  each as similarity to the author's baseline relative to every other author (centroid and
  nearest single piece). A gradient-boosted classifier, one model across the three length
  configurations.
* **Three probe kinds**, reported separately: 5 random other authors; up to 12 other authors
  from the **same subfield** (topic no longer gives them away); up to 12 from the **same
  venue** (same journal or repository host, so house style and boilerplate cannot give them
  away). A probe's own author is always removed from the comparison pools: a ghostwriter is
  not normally one of the class.
* **Development**: 2-fold author-disjoint cross-fit (a probe's source author is kept in the
  same fold as the author being checked), so each score comes from a model that never saw
  either author. The design (channels, model, pooled training, nearest piece) was chosen on
  these cross-fit numbers.
* **Calibration**: the design was then frozen, a final model trained on all development
  authors, and calibration scored once. Primary calibration figure: catch at a 5% honest flag
  rate set on calibration (the protocol used in the earlier Step 4). Also reported: the
  threshold carried over from development out-of-fold scores.

## Results: catch at a 5% honest flag rate (95% author-bootstrap interval)

**Humanities** (development 157 authors cross-fit; calibration 112 authors)

| configuration | probe kind | development | calibration | calibration AUC |
|---|---|---|---|---|
| 300 vs 300 | random | 84.5% | 74.8% [67.6, 82.6] | 0.953 |
| | same subfield | 68.2% | 54.7% [47.3, 64.7] | 0.909 |
| | same venue | 72.9% | 61.6% [54.3, 71.0] | 0.926 |
| 1200 vs 1200 | random | 98.9% | **95.0%** [89.2, 97.3] | 0.985 |
| | same subfield | 96.3% | 81.3% [70.3, 87.4] | 0.963 |
| | same venue | 97.2% | **86.5%** [76.1, 91.3] | 0.970 |
| 1200 past vs 300 new | random | 92.5% | **86.0%** [81.6, 91.0] | 0.972 |
| | same subfield | 85.8% | 67.6% [60.2, 76.9] | 0.937 |
| | same venue | 86.2% | 73.8% [65.8, 82.8] | 0.948 |

**Science** (development 61 authors cross-fit; calibration 36 authors)

| configuration | probe kind | development | calibration | calibration AUC |
|---|---|---|---|---|
| 300 vs 300 | random | 97.3% | **86.5%** [69.8, 95.0] | 0.977 |
| | same subfield | 94.4% | 77.9% [61.3, 91.0] | 0.967 |
| | same venue | 97.5% | **87.9%** [74.8, 95.0] | 0.980 |
| 1200 vs 1200 | random | 99.6% | **98.3%** [95.4, 99.3] | 0.996 |
| | same subfield | 98.9% | **96.7%** [88.8, 98.4] | 0.991 |
| | same venue | 99.3% | **98.6%** [95.6, 99.4] | 0.996 |
| 1200 past vs 300 new | random | 98.7% | **91.9%** [87.6, 98.2] | 0.988 |
| | same subfield | 95.4% | 83.1% [75.7, 95.6] | 0.975 |
| | same venue | 98.9% | **91.9%** [87.5, 97.9] | 0.987 |

Bold = meets 85% at 5% honest flags on calibration. For comparison, the shipped scorer
catches 18.8% (humanities) and 35.4% (science) on calibration at 5% honest flags with a
1200-word past / 300-word new paper; length matching plus the LLR decision reached 42.0% and
44.8%. (Those earlier figures use the loader's random probes.)

## Where the target is met and where it is not

* **Met on calibration**: science in 6 of 9 cells (every random and same-venue cell; same
  subfield at 1200/1200); humanities in 3 of 9 (random at 1200/1200 and 1200/300; same venue
  at 1200/1200).
* **Not met**: a 300-word new paper against a writer from the same subfield or the same
  journal (humanities 55-74%, science 78-83%), and any 300/300 humanities comparison. With
  only 1,200 words of baseline and a 300-word paper, the evidence is thin when topic and venue
  give nothing away.
* **Development was optimistic.** Humanities same-subfield 1200/300 fell from 85.8%
  (development) to 67.6% (calibration). The design was chosen after trying several variants on
  development cross-fit; that selection effect is the likeliest cause. Calibration is the
  honest number. No change was made after calibration was seen.

## Threshold transfer failed, and why

The development out-of-fold thresholds, applied to the final model, gave honest flag rates of
8-10% (humanities) and 10-20% (science) on calibration instead of 5%. The out-of-fold scores
came from models trained on half the authors; the final model, trained on all of them, scores
more confidently, so its score scale differs. A deployable version must set its threshold on
held-out data scored by the exact model it will ship.

## Limits

* Academics are not students; nothing here is validated on student writing. `locked_test`
  is unopened and is now the only clean confirmation left: calibration has been seen.
* Probes are other scholars' published papers. A ghostwriter imitating a student, or AI text,
  is a different and harder case that this corpus does not contain.
* Science calibration has 36 authors; its intervals are wide.
* The verifier is a learned model on stylometric and n-gram signals. It is not part of
  Original, and adopting anything like it in the product would need your approval, its own
  validation gate, and NORTH_STAR's rule that results are framed as consistency observations,
  never verdicts.

## Files

`validation/scholarly/verifier.py`;
`validation/scholarly/verifier_{humanities,science}_development_crossfit_2026-11-12.json`;
`validation/scholarly/verifier_{humanities,science}_calibration_frozen_2026-11-12.json`.
