# Rule D on locked_test: results of the single pre-registered opening

| | |
|---|---|
| **Tool** | Claude Code; `validation/scholarly/rule_d.py locked` |
| **Date** | 2026-11-12 |
| **Question** | Pre-registered in `docs/research/2026-11-12-scholarly-locked-test-preregistration.md` (study `scholarly-rule-d-2026-11-12`, commit `8c2f5c1`): does rule D catch at least 85% of other writers at about a 5% honest flag rate on authors it has never seen? |
| **Decision it informs** | Whether to propose rule D as a report-only consistency observation in Original (proposal D in `docs/research/2026-11-12-scholarly-verifier-ablation-proposal.md`). Nothing has been changed or enabled. |

**Academics are not students**, and formal academic prose is the register where published
stylometric methods are weakest. These results describe a fixed rule on published scholarly
papers. They are not evidence about student writing.

## What was done

* **The opening.** `locked_test` was opened once for each collection, after the
  pre-registration was committed and pushed. `validation/scholarly/LOCKED_OPENINGS.tsv`
  records exactly two lines:
  * `2026-11-12T21:45:56 science scholarly-rule-d-2026-11-12`;
  * `2026-11-12T21:56:08 humanities scholarly-rule-d-2026-11-12`.
* **No changes.** The rule, thresholds, vectorizers (hash-checked before opening), seeds and
  trial design are exactly as pre-registered. Nothing was changed, and nothing was re-run.
* **Authors:** humanities 116, science 33. With 33 authors, the science intervals are wide.
  **No authors or papers were skipped** in any configuration or seed.

## Counting cells: the pre-registered test

The pass bar has three conditions: catch at least 85%, the catch interval's lower end at least
80%, and the honest-flag interval's upper end at most 10%. Intervals are author-level
bootstrap 95%.

| collection | configuration | probe kind | honest flag rate | catch rate | AUC | result |
|---|---|---|---|---|---|---|
| humanities | 1200 vs 1200 | random | 4.7% [3.2, 6.6] | 94.8% [93.6, 96.0] | 0.983 | **pass** |
| humanities | 1200 vs 1200 | same subfield | 4.7% [3.2, 6.6] | 87.2% [85.1, 89.2] | 0.969 | **pass** |
| humanities | 1200 vs 1200 | same venue | 4.7% [3.2, 6.6] | 88.2% [86.1, 90.1] | 0.971 | **pass** |
| humanities | 1200 past vs 300 new | random | 6.6% [4.7, 8.8] | 90.1% [88.5, 91.7] | 0.973 | **pass** |
| humanities | 1200 past vs 300 new | same venue | 6.6% [4.7, 8.8] | 80.8% [78.1, 83.1] | 0.956 | **fail** (catch below 85%; interval lower end below 80%) |
| science | 1200 vs 1200 | random | 1.5% [0.0, 4.0] | 98.0% [96.0, 99.6] | 0.999 | **pass** |
| science | 1200 vs 1200 | same subfield | 1.5% [0.0, 4.0] | 95.0% [92.0, 96.9] | 0.995 | **pass** |
| science | 1200 vs 1200 | same venue | 1.5% [0.0, 4.0] | 97.1% [95.8, 98.2] | 0.999 | **pass** |
| science | 1200 past vs 300 new | random | 3.5% [1.5, 6.1] | 93.5% [90.7, 96.0] | 0.993 | **pass** |
| science | 1200 past vs 300 new | same venue | 3.5% [1.5, 6.1] | 94.1% [92.4, 95.8] | 0.993 | **pass** |

**9 of 10 counting cells pass.** Science passes all 5; humanities passes 4 of 5.

Calibration had predicted two humanities failures. One of them, 1200/1200 same subfield, passed
here at 87.2% (83.9% on calibration).

## Other cells (reported, not counting)

| collection | configuration | probe kind | honest flag rate | catch rate | AUC |
|---|---|---|---|---|---|
| humanities | 300 vs 300 | random | 5.6% [3.7, 7.6] | 79.5% [76.8, 82.3] | 0.952 |
| humanities | 300 vs 300 | same subfield | 5.6% [3.7, 7.6] | 66.7% [63.0, 70.1] | 0.924 |
| humanities | 300 vs 300 | same venue | 5.6% [3.7, 7.6] | 68.2% [64.6, 71.6] | 0.929 |
| humanities | 1200 past vs 300 new | same subfield | 6.6% [4.7, 8.8] | 78.0% [75.2, 80.6] | 0.950 |
| science | 300 vs 300 | random | 5.1% [2.0, 8.6] | 89.9% [86.3, 92.7] | 0.981 |
| science | 300 vs 300 | same subfield | 5.1% [2.0, 8.6] | 79.3% [73.9, 84.0] | 0.962 |
| science | 300 vs 300 | same venue | 5.1% [2.0, 8.6] | 88.8% [86.1, 91.3] | 0.979 |
| science | 1200 past vs 300 new | same subfield | 3.5% [1.5, 6.1] | 88.5% [84.2, 92.2] | 0.985 |

## What it shows

* **The rule holds up out of sample.** A fixed rule with no trained weights, with thresholds set
  on a separate partition, held near its 5% honest flag target on unseen authors: 1.5-6.6%
  across configurations, with every upper interval end at most 8.8%. With full-length papers
  on both sides it caught 87-98% of other writers in both collections, including writers from
  the same subfield or the same journal.
* **A short new paper is the hard case.** A 300-word new paper against a writer from the same
  venue is where it falls short in humanities: 80.8%. With a 300-word paper against 300-word
  past papers, humanities catch is 67-80%.
* **For comparison:** the shipped scorer catches 18.8% (humanities) and 35.4% (science) on
  calibration at 5% honest flags, for 1200 past vs 300 new with random probes.

## Limits

* **Not student writing.** Academics are not students. The probes are other scholars'
  published papers, not ghostwriting or AI text written to imitate a student.
* **The partition is now spent.** `locked_test` has been opened for this study. Any change to
  rule D would need new held-out authors to test it.
* **Science is thin.** With 33 science authors, the science intervals are wide.
* **A pass is not adoption.** Adopting rule D in Original would need:
  * stored n-gram profiles per approved past paper, kept inside the deployment;
  * a minimum class size;
  * a report-only flag, default off;
  * a validation gate with a failure witness;
  * a shadow soak on student writing;
  * the owner's approval.

## Files

* `validation/scholarly/rule_d.py`
* `validation/scholarly/rule_d_thresholds_{humanities,science}.json`
* `validation/scholarly/rule_d_{humanities,science}_calibration_2026-11-12.json`
* `validation/scholarly/rule_d_{humanities,science}_locked_test_2026-11-12.json`
* `validation/scholarly/LOCKED_OPENINGS.tsv`
