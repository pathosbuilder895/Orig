# Rule D through the six cheating tests: a pre-registered one-off study

*Design, 2026-11-27. Owner: Andrew. Status: proposed (awaiting approval).*

## Why

Andrew wants Original to be the best writing-consistency check there is, measured, for the
case it is built for: a student's approved past writing compared with what they turned in.

Two lines of work have never met:

- **Rule D** (`original/rule_d/`, report-only, on for teachers while testing) compares a new
  paper's character patterns with the student's past papers *relative to their classmates'*.
  In its single pre-registered opening on published scholars it passed 9 of 10 cells: at a
  1,200-word baseline and a 300-word new paper it caught 90-94% of other writers at about 5%
  honest flags, where the scorer that drives the teacher's action catches 19-35%
  (`docs/research/2026-11-12-scholarly-rule-d-locked-test-results.md`).
- **The six cheating tests** (G-A1 to G-A6, `validation/adversarial/`, gates in
  `validation/calibration_gate.py`) were measured on that older scorer only. Five fail and one
  is uninformative (`docs/research/ADVERSARIAL_BASELINE_FINDINGS_2026-09-20.md`). The one
  closest to a classroom, classmates answering the same prompt (G-A4 on the Riddell-Juola
  corpus), shows no separation (AUROC 0.46-0.51).

No report under `validation/adversarial/reports/` contains a rule D value. The battery scores
through the live app, and the rows it saves carry no rule D field; worker logging below WARNING
is silenced. The live route probably did compute rule D on many of those calls, but against
whatever throwaway students earlier cells had left in the worker's SQLite file (same tenant,
including the victim's own earlier runs under other attacks), not a controlled class. No
outcome was recorded or seen, so rule D's first look at this data is still clean.

**What the result decides.** If rule D holds up on same-prompt classmates, the next proposal is
letting it drive the teacher's action (its own gate, a shadow soak and Andrew's approval;
NORTH_STAR rule 4). If it does not, that case is what to fix next.

## Goals

1. Score rule D on the gates' own cells: same corpora, same victims, same baseline sizes
   N in {3, 5, 10}, same seed (`report.HARNESS_SEED`), same documents.
2. Give each counting population a three-valued verdict (`pass` / `fail` / `uninformative`)
   against the gates' own bars.
3. Re-score the existing scorer on the same cells, at the same commit, so both columns come
   from today's code (the October and November reports predate the honest-score change traced
   in `docs/research/2026-11-20-sp1-honest-score-drift.md`).
4. Write the bars down and push them before rule D's first look at this data; open once.

## Non-goals

- No change to rule D: its formula, `core.THRESHOLDS`, the vectorizer artifact
  (`original/data/rule_d_vectorizer_v1.json.gz`), the floors or the explanation text.
- No change to any gate, gate verdict, `report.py` cell definition or the battery.
- No product, route, schema or flag change. `RULE_D_OBSERVATION` stays as it is.
- G-A6 (does anything *notice* a poisoned baseline) is out: it judges the drift gate and the
  integrity notes, not a score. Rule D is measured on the other side of poisoning (G-A5).
- No new corpora and no new LLM generations.
- No decision on promoting rule D. That is a separate proposal after the results.

## Anti-goals (failure even if the code works)

- A second opening after anyone has seen a rule D outcome on this data.
- Any threshold, class size or cell chosen after seeing outcomes.
- A headline number from a comparison where the two sides differ in length.
- Results quoted as "validated on students". These are published authors, one AI model's
  output, and adult MTurk writers.

## Constraints

- Everything runs locally; no text leaves the machine (NORTH_STAR rule 7).
- Honest claims only (rule 2): every number in the write-up recomputes from the committed JSON.
- `.venv/bin/python` from the checkout root.
- CI's 98% coverage bar measures `original/` only (`--cov=original`), so it does not cover this
  study's code under `validation/`. The module still gets tests on fixtures, for correctness.
- Use the repo's validation conventions: three-valued verdicts decided by the gates' own
  document-level interval screens (author-level bootstrap intervals reported alongside, not
  deciding), reviewed by the `validation-gatekeeper` agent before the opening and before results
  are quoted.
  This is a study, not a gate, so it needs no entry in `validation/gate_contracts.py`.

## Approaches considered

| | Approach | Trade-off | |
|---|---|---|---|
| A | **One-off study script, pre-registered, run once** | Fast, changes nothing in the gates or product, and keeps rule D's first look at this data clean. Numbers live in a dated report and do not re-run on their own. | **Chosen** |
| B | Rule D as report-only legs inside the six gates | Re-runs automatically on identical cells, but adds code to a ~5,000-line gate file, each leg needs a failure witness, and the first number comes later. | Later, if A shows rule D is worth tracking |
| C | End-to-end through the live app with real test classes | Closest to what teachers see, but slow, and mostly tests the wiring rather than how well rule D compares writing. | No |

Andrew picked A (2026-11-27).

## Design

### 1. Cells

Build cells with `validation.adversarial.report.build_cells(kinds, NS, HARNESS_SEED)`; do not
redefine them.

| Kind | Gate | Counting? |
|---|---|---|
| `clean` (public authors) | G-A1 (genuine side), G-A2 to G-A5 genuine comparator | yes |
| `rj_clean` | G-A1 (genuine side), G-A4 same-prompt peer swap | yes |
| `llm_imitation` | G-A2 | yes (length-matched comparison only, see 4) |
| `llm_paraphrase`, `llm_roundtrip_de`, `llm_roundtrip_ja` | G-A3 | yes (length-matched) |
| `sigma_inflation` | G-A5 | yes |
| `mechanical_obfuscation`, `rj_self_obfuscation`, `rj_self_imitation` | none | report-only |
| public-author peer swap (`clean` impostor docs) | G-A4 cross-era | report-only |

Not used: `obfuscated_baselines`, `outsourced_baselines`, `rj_embedded_*` (G-A6 only).

Population sizes from the existing reports: public authors 13 victims at N=3 and 6 at N=5
and N=10; LLM attacks 13/6/6 for imitation and 6/6/6 for the others; `rj_clean` 21/19/13.

### 2. Calling rule D

- `original.rule_d.core.observe(new_text, new_vector, claimed, peers)`, with every paper
  profile built by `core.build_paper_profile(text, vector, label, feature_fn, with_pieces=True)`.
- `feature_fn` and `new_vector` are exactly what the live score route passes to
  `original.rule_d.service.observe_for` (find the call in
  `original/routers/students_scoring.py`), under `report.LIVE_SCORING_ENV`.
- **Rule D sees what the live app admits.** In the app, a past paper the drift gate holds never
  reaches rule D, and a refused score (422) stops before rule D runs. So:
  - a victim's claimed papers are the baseline documents the existing scorer's run (section 6)
    admitted for that cell (`held_baseline_indices` removed);
  - a cell whose score was refused is refused for rule D too, reported and not scored;
  - each classmate's papers pass the same admission. Reuse the existing run's admitted set where
    that writer was scored at that N on a clean baseline; otherwise post their papers through
    the same API path to a throwaway student, without scoring.

  This is why the existing scorer's run must finish before the opening.
- Shipped thresholds, vectorizers and floors, untouched. Record `core.THRESHOLDS`,
  `core.STUDY_ID`, `textprofile.artifact_meta()`, the commit and the corpus fingerprints in the
  report's `meta`.
- **Flagged** means `status == "observed"` and `reads_less_like_student is True`.
- **Inconclusive** results are counted and reported per population with their reasons, and
  left out of rates and AUROCs. A population where more than half the documents are
  inconclusive gets `uninformative`.

### 3. The class

Rule D's peers are "the same workspace's other students". Each classmate contributes their
own first N baseline documents (the same N as the victim) as approved papers.

- **Public-author cells.** Each public-author impostor document is another victim's *first*
  baseline document (`profiles.build_victim_profiles`: `candidates[other].baselines[0]`). A class
  holding every victim's full baseline would therefore contain every impostor document.
  So:
  - **Classmate's essay** (counts for G-A5; report-only for the cross-era peer swap and
    `mechanical_obfuscation`): the class is every other victim at the same N (12 at N=3, 5 at N=5
    and N=10), each contributing their baselines **except the first** (N-1 papers each). The
    first is the one handed in. The genuine and impostor documents are scored against this same
    class.
  - **Outside writer** (report-only): as above, with the impostor document's author removed
    from the class for that document. The genuine document is scored against the full class, so
    the two sides differ by one classmate. Say so in the write-up.
- **Riddell-Juola cells:** classmates are other participants with at least N baseline chunks,
  chunks taken in `report._rj_order`. Draw 20 by the seeded order
  `report._digest(f"{seed}:rj-class:{victim}:{p}")`, **excluding** the victim's 5 peer-swap
  sources; take all of them if fewer than 20 are eligible, and record the class size. Two
  readings, both counting for G-A4:
  - **Classmate's essay** (sources in the class): the 20 plus the 5 sources. A student hands
    in a classmate's work.
  - **Outside writer** (sources not in the class): the 20 only.

  Within a reading, the victim's genuine essay and the impostor essays are scored against
  the same class, so the AUROC compares like with like.
- **Leaks:** as a safety check, drop any scored document whose SHA-256 matches a paper of the
  victim or of a classmate, and every `impostor_in_baseline` position the reducers already drop.
  Report how many were dropped; after the public-author rule above it should be none.
- **Floor row (report-only):** for `rj_clean`, also score with the smallest class rule D
  accepts (the first 3 of the drawn classmates), since a first pilot class may be that small.

### 4. Length matching

Rule D picks its threshold by length (`core.configuration`): a paper of 750 words or more is
scored as `matched_1200_1200`, a shorter one against long past papers as
`long_past_1200_short_new_300`. G-A2's genuine documents run 2,500 to 19,400 words, while the
imitations are about 650, so an uncut comparison changes the threshold and the setting along
with the writer.

- For G-A2, the genuine side is `genuine_slice`: the first W words of each genuine held-out
  document, W the word count of that victim's imitation at that N (583 to 722 words), cut on
  the original text as `validation/adversarial/imitation_controls.py` does. That comparison
  counts.
- The uncut comparison (G-A2's own) is reported beside it as non-counting, for continuity.
- G-A3 needs no cut. The rewordings and round trips run 2,414 to 2,775 words against 2,500-word
  genuine documents, so both sides fall in one setting and one range (measured 2026-11-27).
- Riddell-Juola essays are all 375 to 588 words; no cutting. G-A1 uses the genuine holdouts as
  the gate does; the genuine slices' flag rates are reported too.
- **What "differ in length" means here:** a length difference *between the two sides* that
  changes rule D's setting or travels with the side. Public-author documents at N=3 run
  2,500 to about 19,300 words on both sides: one setting (`matched_1200_1200`), same range, so
  G-A5 and the public-author rows count uncut. At N=5 and N=10 every public-author document is
  2,500 words. Report each side's word-count range, and add a report-only check at N=3 with
  every public-author document cut to its first 2,500 words.

### 5. Verdicts

Reuse the gates' helpers (`_ga_auroc`, `_ga_auroc_lower`, `_ga_rate_leg`, `_ga_auc_leg`,
`_ga_result` and the bars `_GA_FPR_BAR`, `_GA_CATCH_BAR`, `_GA_AUC_BAR`, `_GA_SIGMA_DROP_BAR`
from `validation/calibration_gate.py`). Import them rather than copying, so a later change
to a bar cannot leave the study quietly out of step.

| Gate | Rule D criterion (at every N) |
|---|---|
| G-A1 | genuine flag rate <= 5%, public authors and `rj_clean` separately. For `rj_clean` **both** readings must pass: an honest student should not be flagged whichever class they sit in. |
| G-A2, G-A3 | attack flag rate >= 60% AND AUROC of D (attack vs the same victims' genuine documents, length-matched for G-A2 per section 4) >= 0.60 |
| G-A4 | the same, on `rj_clean`, for each of the two readings |
| G-A5 | flag rate under the inflated baseline no more than 10 points below the clean-baseline rate AND AUROC under the inflated baseline >= 0.60, under the "classmate's essay" reading |

**Which interval decides.** The gates' own document-level screens (`_ga_rate_leg`,
`_ga_auc_leg`, `_ga_result`) decide pass, fail or uninformative, exactly as they do for the
gates, so both columns are judged the same way. Author-level bootstrap intervals are reported
beside them and do not decide. With 6 victims at N=5 and N=10 they will be wide, and the
write-up should say so.

**G-A5's guards for rule D.** The gate guards G-A5 three ways. Two apply to rule D:
- the injected document reached the scored baseline (read from the existing scorer's admitted
  set, section 2);
- rule D's own clean-baseline catch is above 10%.

The third, "real-feature `mean_baseline_std` grew by at least 5%", tests the existing scorer's
own mechanism (sigma), which rule D does not depend on. It is not applied to rule D, and the sigma
growth is reported beside the result for context.

**One flag for both sides.** Rule D has a single decision, set at about 5% honest flags on
scholars. That is stricter than the gates' `monitor` floor, so the study uses it for both the
false-flag and the catch legs and says so in the write-up. AUROC is computed on D itself and
needs no threshold.

### 6. The existing scorer's column

At the study's code commit, run the battery's own scoring (`report.run_harness` on the kinds
above, path `api`, `report.LIVE_SCORING_ENV`, plus `RULE_D_OBSERVATION=off`) and save its JSON
next to the study's.
- `RULE_D_OBSERVATION=off` changes no score. It stops the live route computing rule D against
  the harness's leftover throwaway students on every call, which is unsaved and slows the run
  as cells accumulate.
- Score the length-matched genuine slices through the same path, so both columns use the same
  documents.
- Join rows on `(corpus, kind, n, victim_id)`.
- Do not reuse the 2026-10-21 or 2026-11-19 reports.

**Headline table:** both columns are computed by the same helpers on the study's own
populations: the same corpus split, the same length matching and the same readings. The
existing scorer does not use the class, so its numbers are the same under both readings. The
unchanged gate functions' official verdicts on this run (`adversarial_results_from_rows`)
appear as a separate continuity row. They pool G-A1's corpora and compare G-A2 and G-A3 uncut,
so they are not the headline.

This run finishes before the opening, because rule D reads its admitted papers (section 2).
It reveals only the existing scorer's outcomes. The previous full battery took about an hour on
8 workers (125 cells), so run it in the background.

### 7. Pre-registration and the single opening

1. **Pre-registration note** at `docs/research/2026-11-27-rule-d-adversarial-preregistration.md`,
   modelled on `docs/research/2026-11-12-scholarly-locked-test-preregistration.md`. It covers:
   - the study id `rule-d-adversarial-2026-11`;
   - every cell, class, reading, length rule and bar above, and which populations count;
   - the seed and the commit;
   - hashes of `core.THRESHOLDS`, the vectorizer artifact and each corpus;
   - the expected population sizes.

   It is reviewed by `validation-gatekeeper`, then committed and **pushed** before the opening.
2. **Dry run by default.** Without `--open`, the script builds every cell, class and profile and
   prints cell counts, class sizes, leak drops, inconclusive reasons and runtime. It prints and
   writes **no** D value, flag, rate or AUROC.
3. **Which commit binds.** Two commits:
   - **C**, the code commit: the finished module, its tests, and the existing scorer's report
     from section 6.
   - **P**, which adds only the pre-registration note. The note names C.

   `--open` checks that the diff from C to HEAD touches nothing but the note and the openings log.
4. **`--open`** refuses when:
   - the working tree is dirty;
   - HEAD is not on the remote;
   - the pre-registration note is missing at HEAD;
   - the C-to-HEAD check fails;
   - `validation/adversarial/RULE_D_OPENINGS.tsv` already has this study id.

   Those checks run first. Then it appends `timestamp<TAB>study_id<TAB>commit<TAB>started`,
   scores every cell, and writes outcomes only when all have finished, changing the line's last
   field to `completed`. The log, reports and write-up are committed together afterwards.
5. **A crash.** A crash leaves a `started` line and no outcomes, so nothing was seen. A re-run
   needs Andrew's approval in chat (as the scholarly pre-registration required) and a
   `--reopen-after-crash` flag. That flag is accepted only when the study's last line reads
   `started`, and it adds a second line. Any fix commit between the two attempts is listed in the
   results doc, and must not touch the rule D call, cells, classes, length rules or bars.
6. Tests run on small fixtures, never on the real corpora's outcomes.

### 8. Outputs

- `validation/adversarial/reports/<date>_rule_d_study.json`, containing:
  - one row per scored document with D, its three components, the configuration, the flag,
    any inconclusive reason, the class size and the reading;
  - per-population summaries and verdicts;
  - `meta`.
- `validation/adversarial/reports/<date>_rule_d_study_existing_scorer.json` (section 6).
- `docs/research/<date>-rule-d-adversarial-results.md`:
  - per gate, a two-column table (existing scorer, rule D) with rates, AUROCs, intervals and
    verdicts;
  - the report-only rows;
  - limits.
- One addendum paragraph in `ADVERSARIAL_BASELINE_FINDINGS_2026-09-20.md`, a pointer in
  `docs/testing/10-gap-register.md`, and a line in `docs/STATUS.md`.

Limits the write-up must state:
- Published authors and adult MTurk writers, not students.
- One AI model's output.
- Six victims at N=5 and N=10 for most public-author and LLM populations.
- Riddell-Juola baselines are prior writing of a different kind than the essays.
- Rule D's vectorizers and thresholds were fitted on scholarly prose.
- A 20-student class is an assumption.

### 9. Where the work goes

Branch `claude/rule-d-adversarial-study`, one PR to `main` containing:
- this design doc;
- the module `validation/adversarial/rule_d_study.py` and its tests;
- the pre-registration;
- after the opening, the reports and the write-up.

Andrew reviews and merges.

## Left to the builder

- Module layout, CLI flags beyond `--open`, and worker parallelism.
- Profile caching by text SHA-256.
- Fixture design for the tests.
- How to reuse `imitation_controls.py`'s slicing for both columns.
- Exact table formatting in the write-up.
