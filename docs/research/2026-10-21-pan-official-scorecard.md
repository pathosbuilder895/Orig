# Original on the official PAN authorship-verification scorecard

| | |
|---|---|
| **Tool** | Claude Code (Claude Opus 5.5) |
| **Date** | 2026-10-21 |
| **Question** | How do Original's verifiers score on the official PAN 2020 and PAN 2021 authorship-verification test pairs, with PAN's own measures (AUROC, c@1, F1, F0.5u, complement of Brier, overall), next to the published state of the art? |
| **Decision it informs** | How Original's accuracy may be described (`docs/NORTH_STAR.md` rule 2, honest claims); the PAN sections of `MODEL_CARD.md`. Measurement only: no score, constant, threshold or flag changed, and nothing under `original/` was edited. |

## Bottom line

- **On PAN's own protocol, Original does not answer.** A PAN problem is one
  known text and one unknown text. All three verifiers need three approved
  baselines (the live score route returns `insufficient_baseline` below three),
  so each abstains on every one of the 12,238 PAN 2020 and 19,999 PAN 2021
  pairs scored. Scored the way PAN scores a non-answer, that is AUROC 0.500
  and c@1 0.000: overall **0.125** on PAN 2020's four-measure scale (winner,
  boenninghoff20-large: 0.935) and **0.250** on PAN 2021's five-measure scale
  (boenninghoff21: 0.9545). This is the only like-for-like comparison here,
  and on it Original neither matches nor beats the state of the art: it is
  not a PAN-format verifier.
- **Adapted so it can run** (the known text cut into three parts as three
  baselines), on a fixed random sample of 1,000 PAN pairs per year, the best
  AUROC is 0.888 (`fused_score_v1`, PAN 2020) and 0.886 (LUAR fusion, PAN 2021),
  and the best overall is 0.787 (LUAR, PAN 2020, four measures) and 0.798
  (LUAR, PAN 2021, five measures). All are below the published winners (AUROC
  0.969 and 0.9869). The input protocol differs, so these numbers are
  indicative only: they are not a leaderboard placement.
- **The live `deviation_score`** reaches AUROC 0.757 (PAN 2020) and 0.776
  (PAN 2021) adapted, and 0.708 and 0.747 on the repo's own locks. The PAN
  2020 lock figure is in line with the pooled AUC of about 0.71 previously
  cited for the 12-author PAN lock.
- **On the repo's own three-baseline locks**, scored with PAN's measures, the
  validation-only LUAR fusion reaches AUROC 0.922 / 0.938 and overall 0.855
  (four measures, PAN 2020) / 0.867 (five measures, PAN 2021). That protocol
  is easier than PAN's in two ways (three real baseline documents, and a
  closed peer pool that contains every impostor's real author), so these are
  not comparable with the leaderboard either.
- **Ranking is better than deciding.** In the adapted protocol,
  `fused_score_v1` ranks pairs well (AUROC 0.88) but says "same author" on only
  14% of pairs, where 47-50% are same-author, so its F1 is 0.44-0.45; the
  LUAR fusion says "same" on 31-34%. Their fitted decision points do not
  transfer to a one-document baseline. `1 - deviation_score` happens to sit
  near the right rate (52-55%).

## What was measured

**Verifiers.** Each is frozen as committed; nothing was refit or tuned on a test pair.

| Verifier | What it is | PAN score (above 0.5 = same author) |
|---|---|---|
| `deviation_score` | The live scorer, `original/quantum/scoring.py:score()`, under the pilot configuration pinned by `lock_environment()` (`NULL_MODEL=none`, context manifest and adaptive weights off, no sentence-transformers so tier 10 uses its TF-IDF fallback, as on Render). | `1 - deviation_score`. A second row moves the decision point to the live `no_action` boundary (deviation 0.40) with a monotone piecewise-linear map; its AUROC is identical by construction, and every other measure, Brier included, can change. |
| `fused_score_v1` | The committed artifact `original/data/fused_score_v1.json`, called through the production entry point `predict_fused_score_with_reason`. | `1 - probability_different_author`; an abstention scores 0.5. |
| LUAR + style interaction fusion | The validation-only `cross_channel_interactions` variant of `validation/verify/pan_luar_expert.py` (LUAR-MUD at revision `1c11d297`, plus the two style best-peer margins). It has no saved artifact, so it is refit from the same 120 PAN 2020 development authors. Before any test pair is scored, the run checks it reproduces the AUCs recorded in the committed lock JSONs (table below). | Its calibrated logistic P(same author). |

| Refit LUAR fusion vs the committed record | committed AUC | reproduced AUC |
|---|---:|---:|
| calibration (both JSONs) | 0.915944 | 0.915933 |
| PAN 2020 lock (`pan_auth_luar_matched_cal100_lock100.json`) | 0.922128 | 0.922106 |
| PAN 2021 lock (`pan_auth_luar_pan21_open_lock100.json`) | 0.9379 | 0.9379 |

The largest difference is 0.000022, about two swapped trial orderings, from
float differences in the re-run LUAR embeddings (torch 2.14.1, transformers
4.57.1, Apple MPS). The run refuses to score anything if a difference exceeds
0.001.

**Protocols.** Every document goes through the repo's deterministic 2,500-word
window (`pan_corpus._fixed_window`), as in every earlier PAN run here. Every
PAN text is longer than that (median about 3,900 words), so every document is
cut. In a PAN pair, `pair[0]` is the known text and `pair[1]` the unknown text.

- **`pair_strict`: PAN's protocol.** One known text, one unknown text, nothing
  else. This is the only protocol whose numbers can be set against the
  leaderboard.
- **`pair_split3`: PAN's pairs and measures, adapted input.** The smallest
  change that lets each verifier run at all: the known text's window is split
  into three contiguous, near-equal parts used as three baselines, and peer
  profiles come from 99 of the 100 PAN 2020 calibration authors (author-disjoint
  from every scored pair). The scoring and the measures are PAN's; the input is
  not. It is reported beside the strict row, never instead of it. It is scored
  on a fixed random sample of 1,000 kept pairs per year (the first 1,000 in
  `sha256("pan-official-sample:" + pair id)` order), because extracting the 109
  features for all 32,237 kept pairs (124,241 texts) was not feasible on the
  shared, swapping machine this ran on (below). The sample's 95% AUROC
  intervals are about plus or minus 0.02-0.03.
- **`lock_3baseline`: the repo's own protocol.** 100 authors, three
  cross-fandom baseline documents each, a closed enrolled pool (the other 99
  lock authors are the peers), and one matched impostor per genuine trial. PAN
  2020: the committed lock in `pan_auth_luar_matched_cal100_lock100.json` (three
  probes per author, 600 trials). PAN 2021: the committed open-set lock in
  `pan_auth_luar_pan21_open_lock100.json` (99 PAN 2021 authors plus one PAN 2020
  tail author, one probe each, 200 trials). All three verifiers see identical
  trials. `fused_score_v1` takes its eight references from the other lock authors
  in `sha256(author id)` order, as production takes classmates.

**Measures.** `validation/verify/pan_official_metrics.py` reimplements the
official evaluator (`pan-webis-de/pan-code`, `clef21/authorship-verification/pan20_verif_evaluator.py`;
the `clef23` evaluator is the same) and is tested against hand-computed cases
and a line-for-line transcription of its loops (`tests/validation/test_pan_official_metrics.py`).
A score of exactly 0.5 is unanswered. PAN 2020's leaderboard "overall" is the
mean of **four** measures (AUC, c@1, F0.5u, F1; the 2020 evaluator has no
Brier); PAN 2021 and 2023 average **five**. Both are reported, and each year is
compared on its own definition.

## Results

Generated by `pan_official_scorecard report` from
`validation/verify/pan_official_scorecard.json`; nothing below is hand-copied.
Each table ends with the published winner for that year, which was measured
on PAN's protocol and all official pairs. Compare PAN 2020 on **overall (4)**
and PAN 2021 on **overall (5)**. AUROC 95% intervals are trial-level
bootstraps (see Caveats). `pair_split3` rows are the 1,000-pair samples.

**pan20 / pair_strict**

| Verifier | n | unanswered | AUROC | c@1 | F1 | F0.5u | Brier (1-) | overall (5) | overall (4) | AUROC 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|
| deviation_score (live), PAN score = 1 - deviation | 12238 | 12238 | 0.500 | 0.000 | 0.000 | 0.000 | 0.750 | 0.250 | 0.125 | n/a |
| fused_score_v1 (committed artifact) | 12238 | 12238 | 0.500 | 0.000 | 0.000 | 0.000 | 0.750 | 0.250 | 0.125 | n/a |
| LUAR + style interaction fusion (validation-only) | 12238 | 12238 | 0.500 | 0.000 | 0.000 | 0.000 | 0.750 | 0.250 | 0.125 | n/a |
| published: boenninghoff20-large (PAN 2020 winner) (PAN protocol, all pairs) | | | 0.969 | 0.928 | 0.936 | 0.907 |  |  | 0.935 | |

**pan20 / pair_split3**

| Verifier | n | unanswered | AUROC | c@1 | F1 | F0.5u | Brier (1-) | overall (5) | overall (4) | AUROC 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|
| deviation_score (live), PAN score = 1 - deviation | 1000 | 0 | 0.757 | 0.690 | 0.697 | 0.666 | 0.778 | 0.718 | 0.702 | 0.727-0.787 |
| deviation_score (live), decision at no_action boundary 0.40 | 1000 | 0 | 0.757 | 0.618 | 0.365 | 0.554 | 0.774 | 0.614 | 0.574 | 0.727-0.787 |
| fused_score_v1 (committed artifact) | 1000 | 0 | 0.888 | 0.663 | 0.448 | 0.666 | 0.783 | 0.690 | 0.666 | 0.868-0.907 |
| LUAR + style interaction fusion (validation-only) | 1000 | 0 | 0.854 | 0.773 | 0.709 | 0.811 | 0.810 | 0.791 | 0.787 | 0.829-0.876 |
| published: boenninghoff20-large (PAN 2020 winner) (PAN protocol, all pairs) | | | 0.969 | 0.928 | 0.936 | 0.907 |  |  | 0.935 | |

**pan20 / lock_3baseline**

| Verifier | n | unanswered | AUROC | c@1 | F1 | F0.5u | Brier (1-) | overall (5) | overall (4) | AUROC 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|
| deviation_score (live), PAN score = 1 - deviation | 600 | 0 | 0.708 | 0.642 | 0.652 | 0.641 | 0.774 | 0.683 | 0.661 | 0.667-0.749 |
| deviation_score (live), decision at no_action boundary 0.40 | 600 | 0 | 0.708 | 0.615 | 0.449 | 0.606 | 0.768 | 0.629 | 0.594 | 0.667-0.749 |
| fused_score_v1 (committed artifact) | 600 | 0 | 0.850 | 0.770 | 0.768 | 0.772 | 0.842 | 0.800 | 0.790 | 0.819-0.880 |
| LUAR + style interaction fusion (validation-only) | 600 | 0 | 0.922 | 0.825 | 0.802 | 0.870 | 0.863 | 0.856 | 0.855 | 0.899-0.942 |
| published: boenninghoff20-large (PAN 2020 winner) (PAN protocol, all pairs) | | | 0.969 | 0.928 | 0.936 | 0.907 |  |  | 0.935 | |

**pan21 / pair_strict**

| Verifier | n | unanswered | AUROC | c@1 | F1 | F0.5u | Brier (1-) | overall (5) | overall (4) | AUROC 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|
| deviation_score (live), PAN score = 1 - deviation | 19999 | 19999 | 0.500 | 0.000 | 0.000 | 0.000 | 0.750 | 0.250 | 0.125 | n/a |
| fused_score_v1 (committed artifact) | 19999 | 19999 | 0.500 | 0.000 | 0.000 | 0.000 | 0.750 | 0.250 | 0.125 | n/a |
| LUAR + style interaction fusion (validation-only) | 19999 | 19999 | 0.500 | 0.000 | 0.000 | 0.000 | 0.750 | 0.250 | 0.125 | n/a |
| published: boenninghoff21-large (PAN 2021 task page, preliminary) (PAN protocol, all pairs) | | | 0.9869 | 0.9502 | 0.9524 | 0.9378 | 0.9452 | 0.9545 |  | |

**pan21 / pair_split3**

| Verifier | n | unanswered | AUROC | c@1 | F1 | F0.5u | Brier (1-) | overall (5) | overall (4) | AUROC 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|
| deviation_score (live), PAN score = 1 - deviation | 1000 | 0 | 0.776 | 0.710 | 0.715 | 0.705 | 0.783 | 0.738 | 0.726 | 0.748-0.803 |
| deviation_score (live), decision at no_action boundary 0.40 | 1000 | 0 | 0.776 | 0.609 | 0.388 | 0.582 | 0.774 | 0.626 | 0.589 | 0.748-0.803 |
| fused_score_v1 (committed artifact) | 1000 | 0 | 0.880 | 0.642 | 0.442 | 0.659 | 0.770 | 0.679 | 0.656 | 0.858-0.902 |
| LUAR + style interaction fusion (validation-only) | 1000 | 0 | 0.886 | 0.763 | 0.718 | 0.807 | 0.818 | 0.798 | 0.793 | 0.866-0.905 |
| published: boenninghoff21-large (PAN 2021 task page, preliminary) (PAN protocol, all pairs) | | | 0.9869 | 0.9502 | 0.9524 | 0.9378 | 0.9452 | 0.9545 |  | |

**pan21 / lock_3baseline**

| Verifier | n | unanswered | AUROC | c@1 | F1 | F0.5u | Brier (1-) | overall (5) | overall (4) | AUROC 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|
| deviation_score (live), PAN score = 1 - deviation | 200 | 0 | 0.747 | 0.695 | 0.687 | 0.698 | 0.783 | 0.722 | 0.707 | 0.678-0.814 |
| deviation_score (live), decision at no_action boundary 0.40 | 200 | 0 | 0.747 | 0.595 | 0.382 | 0.558 | 0.773 | 0.611 | 0.570 | 0.678-0.814 |
| fused_score_v1 (committed artifact) | 200 | 0 | 0.881 | 0.735 | 0.658 | 0.797 | 0.827 | 0.780 | 0.768 | 0.832-0.926 |
| LUAR + style interaction fusion (validation-only) | 200 | 0 | 0.938 | 0.835 | 0.827 | 0.851 | 0.882 | 0.867 | 0.863 | 0.909-0.966 |
| published: boenninghoff21-large (PAN 2021 task page, preliminary) (PAN protocol, all pairs) | | | 0.9869 | 0.9502 | 0.9524 | 0.9378 | 0.9452 | 0.9545 |  | |

## Exclusions

Only pairs whose author could have shaped a fitted value are excluded: any
pair with a text by a PAN 2020 **development** author (the 120 authors that fit
the LUAR fusion, its PLDA/LDA/character-n-gram/style representations, and
`fused_score_v1`) or **calibration** author (the 100 that selected the LUAR
variant and threshold, held out `fused_score_v1`, and serve as the
`pair_split3` peer pool). The run also checks that no kept pair reuses any
fitting-split text (it found none).

| | PAN 2020 | PAN 2021 |
|---|---:|---:|
| official test pairs | 14,311 | 19,999 |
| excluded: development author | 1,097 | 0 |
| excluded: calibration author | 975 | 0 |
| excluded: one of each | 1 | 0 |
| **kept** (same-author) | **12,238** (5,941) | **19,999** (10,000) |
| scored in `pair_strict` | 12,238 | 19,999 |
| scored in `pair_split3` (fixed sample) | 1,000 | 1,000 |
| unanswered in `pair_strict`, every verifier | 12,238 | 19,999 |
| unanswered in `pair_split3` and the locks, every verifier | 0 | 0 |

PAN 2021 shares no author and no text with PAN 2020 (checked on raw author ids
and on text hashes), so nothing in it touches a fitting split.

Kept PAN 2020 pairs that involve an author earlier repo work used only for
evaluation are kept (nothing was fitted on them) and counted: 978 pairs touch
the 100-author lock, 1,116 the 120 "post-calibration" authors skipped by the
LUAR experiments, 379 the 43-author local-threshold cohort (which set a
threshold this scorecard does not use), 124 the original 12-author lock, and
15 the one PAN 2020 tail author in the PAN 2021 lock.

`fused_score_v1` answered every `pair_split3` and lock trial (production
outcome `hit` each time); its only abstentions are the `pair_strict` ones
(`baseline_below_min`).

## PAN 2023 (cross-discourse): not obtained

The PAN 2023 data (Aston 100 Idiolects corpus) is released only through a FoLD
account and a per-user "Request Item" data request (PAN 2023 task page, read
2026-10-21). The PAN 2022 Zenodo record (6337151) is also restricted. Getting
it needs an account and an owner decision, so this run stops at 2020 and 2021.
The 2023 targets in the brief (Ibrahim et al. AUROC 0.616, overall 0.623;
cngdist baseline AUROC 0.516, overall 0.595) are quoted as given: the 2023 task
page hides its results table, so they were not re-checked here.

## Caveats

- **None of this is student writing.** Every number here is fanfiction from
  fanfiction.net, as every PAN number in the repo already was. Nothing here
  says how any verifier behaves on a teacher's students.
- **`pair_split3` is an adaptation, not PAN's protocol.** Three parts of one
  document are far more alike than three separate documents, so each
  verifier's baseline looks tighter than it was ever fitted on. The parts are
  also about 833 words against a 2,500-word probe, and several of the 109
  features depend on length; that mismatch falls on the feature-based
  verifiers (`deviation_score`, the z-channel of `fused_score_v1`) and not on
  LUAR, which reads only the first 512 tokens of each document. The peer pool
  is fixed and open-set (the unknown text's real author is never in it).
  The LUAR fusion's calibrator was fitted on closed-set blocks, where every
  impostor row's block contained the impostor's real author, so in
  `pair_split3` its peer-margin signals for a different-author pair sit
  outside what it was fitted on (a reviewer expected that to push it toward
  "same"). Its baseline-cohesion signals move the other way: three parts of
  one text agree with each other far more than three separate documents do.
  The net observed effect is that it says "same" on 31-34% of pairs against a
  true 47-50%. Lock and `pair_split3` rows are therefore not comparable for
  LUAR, and only partly for `fused_score_v1` (whose eight references can
  include the impostor's author in the lock).
- **`lock_3baseline` is closed-set.** In an impostor trial the probe's real
  author is one of the 99 enrolled peers, so "claimed author minus best peer"
  signals can see the true author outscore the claimed one. PAN's pairs never
  offer that, so the lock flatters the peer-margin verifiers relative to PAN.
- **PAN 2020 is the easier PAN set** for systems trained on PAN's training
  data (its authors and fandoms appear there). None of Original's verifiers was
  trained on PAN's training data, so that advantage does not apply to them, but
  it does to the published 2020 systems.
- **Intervals** are trial-level percentile bootstraps (1,000 resamples, seed
  1729). Trials share authors and texts, so they are narrower than an
  author-level resample would give; read them as a floor on the uncertainty.
- **The PAN 2020 subset is not the official set.** 2,073 of 14,311 pairs are
  excluded (above), so even a protocol match would be on a different, smaller
  pair set than the leaderboard's.

## Reproduce

Data (public, Zenodo 10.5281/zenodo.5106099; MD5s are the ones the repo already pins):

```bash
mkdir -p .benchmark_cache/pan/2020 .benchmark_cache/pan/2021
curl -L -o .benchmark_cache/pan/2020/pan20-authorship-verification-test.zip "https://zenodo.org/api/records/5106099/files/pan20-authorship-verification-test.zip/content"
curl -L -o .benchmark_cache/pan/2021/pan21-authorship-verification-test.zip "https://zenodo.org/api/records/5106099/files/pan21-authorship-verification-test.zip/content"
md5 .benchmark_cache/pan/*/*.zip   # 655f365ab7b736036bbbee717168012b, 117a355b5ef649a02f15334d63564103
unzip -q .benchmark_cache/pan/2020/pan20-authorship-verification-test.zip -d .benchmark_cache/pan/2020
unzip -q .benchmark_cache/pan/2021/pan21-authorship-verification-test.zip -d .benchmark_cache/pan/2021
```

LUAR needs torch, `transformers` 4.x (5.x cannot load LUAR-MUD's pinned remote
code: its nested `from_pretrained` fails under the meta-device init) and
`einops`, none of which the pilot environment has. A throwaway environment for
the embedding stage only:

```bash
uv venv --python 3.11 .benchmark_cache/luar-venv
VIRTUAL_ENV=.benchmark_cache/luar-venv uv pip install torch==2.14.1 transformers==4.57.1 einops numpy==2.2.6 scipy==1.17.1 scikit-learn==1.6.1 pydantic==2.9.2
```

Then, from the repository root:

```bash
PYTHONPATH=. .benchmark_cache/luar-venv/bin/python -m validation.verify.pan_official_scorecard embed
.venv/bin/python -m validation.verify.pan_official_scorecard features --workers 9
.venv/bin/python -m validation.verify.pan_official_scorecard score
.venv/bin/python -m validation.verify.pan_official_scorecard report
.venv/bin/python -m pytest tests/validation/test_pan_official_metrics.py tests/validation/test_pan_official_scorecard.py -q
```

`score` writes `validation/verify/pan_official_scorecard.json` (committed) and
PAN-format `truth.jsonl` / `answers.jsonl` files for every dataset, protocol and
verifier under `.benchmark_cache/pan/official_answers/`, so the official
evaluator can be pointed at them directly (`-i <protocol dir> -a <verifier dir>`).

**This run.** Code at commit `bb3b98c` on `claude/pan-official-scorecard`.
The result JSON records that commit and the tracked files that differed from
it when it was written: only `docs/STATUS.md`, which was being edited, so no
code. A first run on the same code with that file unedited gave identical
numbers in every row.
`score` ran with `--sample 1000 --workers 5`. Tests: the two test files above,
24 passed. Python 3.11.15, numpy 2.2.6, scikit-learn 1.6.1, spaCy 3.8.14;
scoring flags pinned by `lock_environment()` (listed in the JSON).

The machine was shared with other sessions' jobs throughout (load averages
150-550, about 30 GB of swap in use). LUAR embedding of every kept pair took
about two hours on Apple MPS, feature extraction for the sample about three
hours at roughly one text a second, and `score` 8 to 40 minutes depending on load. To score
every kept pair instead of the sample, run `features` without `--sample` and
then `score --luar-all-pairs` without `--sample`.
