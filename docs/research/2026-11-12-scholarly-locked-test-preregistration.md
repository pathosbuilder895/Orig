# Pre-registration: rule D on the scholarly locked_test partition

| | |
|---|---|
| **Tool** | Claude Code; `validation/scholarly/rule_d.py` |
| **Date** | 2026-11-12 (written and committed before `locked_test` was opened) |
| **Question** | Does rule D, a fixed comparison rule with no trained weights, catch at least 85% of other writers at about a 5% honest flag rate on authors it has never seen? |
| **Decision it informs** | Whether rule D (`docs/research/2026-11-12-scholarly-verifier-ablation-proposal.md`) is worth proposing as a report-only consistency observation in Original. A pass would not enable anything: product changes still need the owner's approval, a validation gate and a shadow soak. |

**Study id:** `scholarly-rule-d-2026-11-12`

**This is the single opening of `locked_test` for this study. Nothing about the rule, the
thresholds, the vectorizers, the seeds, the trial design or the pass bar will change after
this file is committed, and the results will be reported exactly as they come out, pass or
fail.** Academics are not students, and formal academic prose is the register where published
stylometric methods are weakest; a pass here says nothing yet about student writing.

## Rule D, exactly

For a new paper scored against claimed author A in one trial set, O is every other author in
the same partition and trial set, minus the probe's own author when the paper is a probe.

* **B, character profile.** Character 3-5-gram TF-IDF (sublinear tf, min_df 3, at most
  60,000 features).
  * zB_c = (cos(paper, A's centroid) − mean over O) / sd over O.
  * zB_n = the same with each author's nearest past paper.
  * B = (zB_c + zB_n) / 2.
* **C, topic-masked profile.** The same on `verifier.mask_topic` text, with 3-6-grams:
  C = (zC_c + zC_n) / 2. `mask_topic` keeps function words and punctuation, replaces other
  letters with `*` and digits with `#`.
* **zO, Original's z.**
  * r(X) is the rms of |z| of the paper against author X's baseline, capped at 6, active
    features only, using Original's `StudentState` mean and spread.
  * zO = −(r(A) − mean over O of r(X)) / sd over O.
* **D = −(B + C + zO) / 3.** A paper is flagged when D is strictly above the threshold.
* **Baseline cut.**
  * B and C use the whole past papers: the 4 past-paper cuts at the configuration's past
    length, not split. The centroid is the mean of the 4, and "nearest" is the nearest of
    the 4.
  * zO uses the past papers cut into pieces of the new paper's length
    (`adjust.length_matched`).
* **Frozen vectorizers.** Fit once on development texts, with no labels, and stored outside
  git. SHA-256 of the pickle:
  * humanities `56ca76c8486e5ee61144688ebb6f9cd78914cb873664d18c776d1a5e6d651a06`;
  * science `58f3cef702f3698f6cbe2210750c5bf5a536726f3d8cfe332dc237d032521d36`.

  The `locked` step refuses to run if the hash differs.

## Thresholds (fixed on calibration, 95th percentile of honest D, seeds pooled)

| collection | 300 vs 300 | 1200 vs 1200 | 1200 past vs 300 new |
|---|---|---|---|
| humanities | −0.529301 | −1.244517 | −0.919008 |
| science | −0.938747 | −1.629903 | −1.239804 |

Source: `validation/scholarly/rule_d_thresholds_{humanities,science}.json`, commit `faef583`.

## Design

* **Data:** `locked_test` partition. Humanities has **116 authors** and science **33 authors**
  (counted from the manifest). With 33 authors, the science intervals will be wide.
* **Trials:** seeds 7, 11 and 23. Per author: 4 past papers and 2 new papers. Probes are 5
  random other authors, plus up to 12 same-subfield and up to 12 same-venue other authors,
  each represented by that author's first held-out paper. The probe's own author is always
  removed from the comparison pool.
* **Metrics:** for each collection, configuration and probe kind:
  * honest flag rate at the threshold;
  * catch rate at the threshold;
  * AUC of D.

  Each comes with an author-level bootstrap 95% interval (1,000 resamples of authors).
  Collections are never pooled.

## Hypotheses (pass bar per counting cell)

A counting cell passes only if, on `locked_test` at the fixed threshold:
1. the catch rate is at least 85%;
2. the lower end of the catch rate's 95% interval is at least 80%;
3. the upper end of the honest flag rate's 95% interval is at most 10%.

Counting cells, each for humanities and for science separately (10 hypotheses):

| configuration | probe kinds |
|---|---|
| 1200 past vs 300 new | random; same venue |
| 1200 vs 1200 | random; same subfield; same venue |

Every other cell is reported but does not count. For reference, calibration fails two
humanities counting cells: 1200/1200 same-subfield at 83.9%, and 1200 past / 300 new
same-venue at 80.3% (`rule_d_humanities_calibration_2026-11-12.json`). Those cells are
expected to fail here too.

## Opening procedure

1. Commit and push this file, the code and the thresholds before anything is opened.
2. Run once per collection:
   `python -m validation.scholarly.rule_d locked --collection <c> --study scholarly-rule-d-2026-11-12`.
   It calls `loader.load_trial_grid(..., "locked_test", allow_locked_for="scholarly-rule-d-2026-11-12")`,
   which opens the partition once and appends exactly one line per collection to
   `validation/scholarly/LOCKED_OPENINGS.tsv`.
3. Results go to `validation/scholarly/rule_d_{collection}_locked_test_2026-11-12.json`. The
   step refuses to run again if that file exists.
4. If a run crashes after the opening is logged but before scoring, it is not re-run without
   the owner's approval, and the crash is reported.
