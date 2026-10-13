# Natural/shadow study protocol

| | |
|---|---|
| **Tool** | Claude Code (Claude Opus 5.5) |
| **Date** | 2026-10-13 |
| **Question** | When a student deliberately writes as a named classmate, does Original's `deviation_score` against that classmate's baseline read higher (less consistent) than on the classmate's own natural writing, and at what `deviation_score` cut-off does that come without false flags on natural writing? |
| **Decision it informs** | Whether the Collections flag (`demo/bluebook/Exam.jsx` `bbSealStatus`: Collections score, round(100 x authorship probability), below 70) should move to a cut-off on `deviation_score`, via a candidate from `scripts/propose_thresholds.py` judged by gate G-S1 (`validation/calibration_gate.py`). NORTH_STAR milestone 3 (Original reports in teacher workspaces, labelled as testing) and rule 4 (no score-changing move without a passed gate and a human approval). |

Tooling this protocol relies on (PR `claude/study-analysis-calibration`):
`validation/study_contract.py` (the CSV contract, `study-csv-v2`),
`validation/study_eval.py` (the analysis), `scripts/propose_thresholds.py` (the
candidate), gate G-S1, and the staff panel "Study label (research, staff
only)" on the exam view. The export (`scripts/study_export.py`), the
`study-label` route and the server-side study scoring are Codex's (PR #274,
`codex/study-labels-export`); this protocol states what they must deliver, and
`tests/test_study_eval_on_export.py` checks the export against the contract
once both are merged.

## 1. What this study can and cannot tell us

It **can** estimate, for one cohort on one day: how often the current flag
rule marks a student's own writing (false flags), how often it marks a
classmate's deliberate imitation (catches), how often Original cannot read an
attempt at all (INCONCLUSIVE), and which `deviation_score` cut-off would trade
those off within a 5% false-flag cap.

It **cannot**:

- show that Original detects ghostwriting, AI use or misconduct. A shadow
  attempt is an on-request imitation by a classmate in a classroom, with
  little time and no stake. Real impersonation differs in motive, skill,
  time and tools;
- validate Original (NORTH_STAR milestone 4). It is one cohort;
- certify a 5% false-flag rate. With about 20 students it is not big enough
  to (section 6).

Nothing from this study is presented to teachers or students as an accuracy
figure (NORTH_STAR rule 2).

## 2. Ethics, consent and data handling

These are preconditions, not steps. If one is not met, do not run the session.

- **Owner approval.** Andrew approves the study, the cohort and the teacher.
  Original is switched on for the workspace only with the owner's agreement
  and the teacher's informed consent (`scripts/set_products.py`), and every
  Original result the teacher sees carries the testing-phase label
  (NORTH_STAR rule 10).
- **Student consent.** Every participant agrees in writing to both sittings
  and to being a shadow *target*. A student who declines any part takes no
  part and is not a target. Withdrawal at any time deletes their rows.
  - [ANDREW: student ages are still open in NORTH_STAR. Under-18 participants
    need parental consent; does this study also need ethics review before any
    result is shared outside the team?]
- **No consequences.** No sitting is graded. A shadow attempt is never held
  against its writer or its target, never reported as misconduct, and **never
  approved as a baseline sample** for anyone. Collections will score a shadow
  attempt against its *writer's* own baseline at sealing, and may mark it
  "worth a look": the teacher disregards that mark for study sittings. That
  seal-time reading is not the study's number (section 6).
- **No prose leaves the deployment.** The study CSV carries scores, counts and
  derived feature values, never text (NORTH_STAR rule 7). No keystroke or
  timing columns (rule 6): the contract has none, and `f_` columns from tier 17
  would be excluded as disabled anyway.
- **Outputs stay out of git.** `validation/study/out/` (per-row results) and
  `validation/study/candidates/` are git-ignored. Ids in the CSV are
  pseudonymous. Delete the CSV and outputs when the study closes, unless the
  owner decides otherwise in writing.

## 3. Cohort and preparation

- **Size.** About 20 students to start. At least 10 are needed before gate
  G-S1 can pass at all. To *demonstrate* a false-flag rate at or below 5% with
  95% confidence needs conclusive natural attempts from at least 73 different
  students with none flagged (G-S1 counts a student's repeat attempts once), so
  plan a second, fresh cohort of different students (section 7) rather than
  expecting this one to settle it.
- **Baselines first.** Each participant needs at least 3 teacher-approved
  reference samples (5 or more preferred) of their own earlier writing,
  approved **before** the session, in the same broad genre as the prompts.
  Below 3, every attempt scored against that student is INCONCLUSIVE, which is
  a valid answer (NORTH_STAR rule 3) but carries no information for this study.
  Record each student's baseline count at the session.
- **Prompts.** Two prompts, P1 and P2, in the same genre and of similar
  difficulty, neither used in any baseline sample.
- **Exams: two per session.** Create two Collections exams for the session,
  both published to the cohort's course, 25 minutes each, with a minimum
  length so most attempts reach the 300-word reliability floor:
  - **exam N**, the natural sitting (sitting 1);
  - **exam S**, the shadow sitting (sitting 2).

  Each exam carries both prompts, labelled P1 and P2, and each student answers
  only the one their sheet names (section 4, step 4: group A answers P1 in
  exam N and P2 in exam S, group B the reverse), so the prompt counterbalancing
  survives the split. Check in a rehearsal that a submission answering one of
  the two prompts seals with its own word count above the minimum.

  Keeping the two kinds in separate exams means the exam a submission sits in
  already says which kind it should be, so a label that disagrees with its
  exam is caught at the second-person check (section 5, step 7). Switch
  **Authorship comparison (Original)** on for both when creating them. An exam
  without it is not an Original exam: the server stores no study score for
  it, and the study label panel does not appear on it.
- **Note both exam ids** on the assignment sheet; the export takes them
  (section 8).

## 4. Assigning shadow targets

Assign before the session, from the consented roster, and keep the sheet.

1. Put the consented students in a list sorted by their Collections student
   id. Draw a seed (any integer) and write it on the sheet.
2. Shuffle the list with that seed, then give student `i` the target
   `order[(i + 1) % n]`: a single cyclic shift. Nobody imitates themselves,
   everyone is imitated exactly once, and everyone writes exactly one shadow.

```python
import random
roster = sorted(consented_student_ids)
order = roster[:]
random.Random(SEED).shuffle(order)
target = {order[i]: order[(i + 1) % len(order)] for i in range(len(order))}
```

3. The teacher may veto a pair (for example students who routinely co-write)
   before the session; redraw with a new seed and record both seeds.
4. **Counterbalance prompt and order.** Split the shuffled list in half.
   Group A writes natural on P1 first, then shadow on P2. Group B writes
   natural on P2 first, then shadow on P1. Prompt and order are then not
   confounded with the label.
5. **Material for the imitator.** With the target's consent, the imitator
   reads two of the target's approved reference samples for 10 minutes before
   the shadow sitting, then hands them back. Use the same condition for the
   whole cohort and write it on the sheet. A target who does not consent to
   sharing is not a target.

## 5. Running the session

Before students arrive:

- Check Original is on for the workspace and shows its testing label.
- Check every participant's baseline readiness (3 or more approved samples).
- Have the assignment sheet: student, group, target, seed(s).

In the room:

1. Explain the study, that nothing is graded, and how to withdraw. Collect
   consent forms.
2. **Sitting 1, exam N** (25 minutes): each student writes as themselves
   (group A on P1, group B on P2).
3. Break of at least 10 minutes. Imitators read their target's two samples
   (10 minutes), then hand them back.
4. **Sitting 2, exam S** (25 minutes): each student writes *as their target*
   on the other prompt. Instruction: "Write the way your classmate writes:
   their word choice, sentence length, punctuation, how they open and close.
   Do not copy sentences from their samples."
5. Sealing works as for any exam.

The same day, in each exam's view, **Study label (research, staff only)**
panel:

6. Label every submission from the assignment sheet, never from memory:
   *natural* for every submission in exam N, *shadow* plus the target for
   every submission in exam S. A submission left unlabelled is left out of
   the analysis (the loader counts and names it).
7. A second staff member checks every label against the sheet and against
   the exam it sits in.
8. Do not approve any study submission as a baseline sample.

## 6. What is measured

The export (`scripts/study_export.py --exam N --exam S --study-id ...`,
section 8) produces one CSV row per submission of both exams, in contract
`study-csv-v2` (`validation/study_contract.py`): `student_id` (the writer),
`study_label`, `imitated_student_id`, `verdict`, `deviation_score`,
`baseline_count`, `word_count` and `f_<feature>` columns.

**Shadow attempts are scored against the imitated student's baseline.** That
is the study's question: does the imitation pass as the classmate it
imitates? So for a shadow row, `deviation_score`, `verdict` and
`baseline_count` all come from scoring the text against the *imitated*
student's approved baseline, never the writer's. A natural row is scored
against the writer's own baseline. Collections scores every sitting against
the writer's own baseline at sealing; that reading and that status answer a
different question ("does this look like the writer?") and must not be the
ones exported for a shadow row. The contract therefore never reads a stored
`status` as the verdict, and the loader warns when a row's verdict and its
baseline count disagree, which is what a writer-baseline verdict looks like.

`deviation_score` runs from 0 to 1, and **higher means less consistent** with
the claimed student (`SCORE_DIRECTION` in the contract). A cut-off flags an
attempt when its `deviation_score` is at or above the cut-off, the same
convention as Original's action bands (monitor from 0.40, schedule a
conversation from 0.60, escalate from 0.75).

`validation/study_eval.py` reports, all over conclusive attempts unless noted:

| Measure | Read it as |
|---|---|
| AUC on `deviation_score`, natural vs shadow, with a student-cluster bootstrap 95% interval | does the score separate the two kinds at all |
| Confusion matrix at the live rule, read from the exported `verdict` (checked against round(100 x authorship probability) < 70 when the CSV carries the probability) | today's false flags and catches, plus inconclusive and unscored counts |
| Threshold sweep on `deviation_score`, every 0.01, action bands marked | the full false-flag vs catch trade-off |
| INCONCLUSIVE rate, per label | how often Original declines to read |
| The above by baseline count (0-2, 3-4, 5-9, 10+) and word count (<150, 150-299, 300-499, 500+) | where it works and where it does not |
| Each student's shadow mean minus natural mean, against the same baseline | whether the effect is general or carried by a few students |
| Separation per `f_` feature, permutation p within student, BH q | exploratory leads for the next study only |

`scripts/propose_thresholds.py` then proposes a candidate cut-off on
`deviation_score` (most shadow catches with natural false flags at or under
5%, highest cut-off on ties), re-runs that selection leave-one-student-out
(each fold may flag as many natural attempts as the whole cohort may, so folds
are not stricter than the candidate), and writes the out-of-sample counts gate
G-S1 reads. Tier weights stay unchanged: the scores were computed under the
current weights.

## 7. Success criteria, set in advance

Fixed on 2026-10-13, before any data. They are gate G-S1's legs, and a change
to any of them after data exists must be reported as a deviation.

| Leg | Criterion (out of sample) | Pass | Fail | Otherwise |
|---|---|---|---|---|
| A, protect honest students | false-flag rate on conclusive natural attempts at the candidate cut-off, 5% or less | Wilson 95% upper bound below 5%, counting each student once | observed rate above 5% | undecided |
| B, separation | AUC natural vs shadow | interval lower bound above 0.5 | AUC 0.5 or below | undecided |
| C, usefulness | catch rate on conclusive shadow attempts, above 5% | Wilson 95% lower bound above 5%, counting each student once | observed rate 5% or below | undecided |

- **Out of sample only.** In-sample numbers never decide anything: the
  candidate was chosen on those rows, so they meet the cap by construction.
  Evidence is leave-one-student-out on this cohort, or the frozen cut-off on a
  fresh cohort (`--fresh-cohort-eval`). A fresh cohort shares **no student and
  no submission** with the first; the proposal refuses one that does.
- **The selection cap is pre-registered at 5%.** A candidate chosen at any
  other cap cannot pass (a fail still fails), so the cap cannot be swept until
  a cohort passes. To pre-register a stricter cap (for example 2%, which would
  make a pass more reachable, because the gate's bar is also 5%), change it
  here and in `validation/calibration_gate.py` before any data exists.
- **Verdict.** Any leg failing is FAIL, never downgraded. Any leg undecided is
  UNINFORMATIVE. Fewer than 10 students with conclusive attempts cannot PASS.
  A candidate that flags more than every leave-one-student-out fold (a
  `deviation_score` cut-off below all of theirs) cannot pass on fold evidence. A candidate that changes tier weights is always
  UNINFORMATIVE: G-S1 does not judge weights (see below).
- **Expected result for about 20 students: UNINFORMATIVE**, because leg A
  cannot be decided below 73 students' conclusive natural attempts. That
  outcome is recorded as uninformative, not as a pass and not as a failure.
- **Only a fresh-cohort PASS is adoption evidence.** A leave-one-student-out
  PASS says so in the gate's own output.
- **Reported whatever the gate says:** the live rule's observed false-flag
  rate on natural attempts. If it is above 5%, that goes to the owner as a
  finding in its own right.
- **Adoption** of any cut-off needs all of: G-S1 PASS on a fresh cohort; a
  shadow measurement on live pilot submissions (how often the candidate
  cut-off would have flagged real, natural submissions, computed without
  changing what teachers see), because both study cohorts are one room, one
  day, one genre; the owner's approval; and a separate PR that changes
  `Exam.jsx` (the score its flag reads as well as the cut-off) and the
  snapshot `validation/study/current_operating_point.json` together. No
  research flag is turned on by this study.
- **Weights are out of scope.** Tier factors from `--weights study` are fitted
  on this cohort, so re-scoring this cohort under them would be in-sample. A
  weight change needs a fresh cohort scored under the candidate weights and
  the score-changing-flag process in `validation/README.md`.
- **Analysis plan.** The defaults are the plan: seed 20261013, 2000 bootstrap
  resamples, 1000 permutations, cap 5%. Unscored rows are excluded and
  counted; INCONCLUSIVE rows are reported, never folded into either side; no
  attempt is dropped for length (the word-count breakdown shows its effect);
  withdrawn students' rows are deleted before analysis.

## 8. Analysis

Export both of the session's exams in one run, so every student carries one
pseudonymous id across the two (a shadow row's `imitated_student_id` must match
the target's `student_id` in exam N). N and S are the two exam ids from the
assignment sheet; `--study-id` names the study. The export is Codex's (PR #274):
see its `--help` for the pseudonymisation salt.

```bash
.venv/bin/python scripts/study_export.py --exam N --exam S --study-id STUDY_ID > study.csv
.venv/bin/python -m validation.study_eval --csv study.csv --out-dir validation/study/out/cohort1
.venv/bin/python scripts/propose_thresholds.py --eval validation/study/out/cohort1/study_eval.json
STUDY_CANDIDATE=validation/study/candidates/candidate_operating_point.json \
  .venv/bin/python -m validation.calibration_gate --strict --only S
```

`study.csv` holds per-row results: keep it out of git, beside the
git-ignored outputs, and delete it with them when the study closes.

With a second cohort, evaluate it the same way and pass its report to the
proposal: `--fresh-cohort-eval validation/study/out/cohort2/study_eval.json`.

## 9. Limits

- **Small sample.** About 20 students gives wide intervals on every rate; a
  false-flag rate near 5% cannot be told apart from 10%. Read the intervals.
- **Clustering.** Attempts are not independent. The bootstrap resamples
  claimed students (baselines) and the permutation tests shuffle within them,
  but a writer's natural and shadow attempts land in different clusters, so
  dependence through the writer is not captured and the intervals may still be
  too narrow. Wilson intervals in the sweep treat rows as independent and are
  narrower still; gate G-S1 counts each student once instead.
- **Leave-one-student-out leakage.** Holding out a student removes the
  attempts scored against their baseline, but the shadow attempt that student
  *wrote* against a classmate stays in training.
- **Shadow is not the threat model.** Peer imitation in 25 minutes, with two
  samples to read, is a weak and specific attack. A good result here says
  little about paid ghostwriting or AI text; a bad one is still informative.
- **Same room, same day, same genre.** Results do not transfer to other
  genres, other prompts or other cohorts without another study.
- **Order and fatigue.** Shadow always comes second. Prompt order is
  counterbalanced, sitting order is not.
- **Labels are human.** A mislabelled row moves both rates; the second-person
  check exists for that.
- **Baseline quality varies.** Baseline size is recorded and broken down, but
  genre match and sample length are not controlled beyond the preparation
  rules.
- **The score studied is `deviation_score`**, not the number the live
  Collections flag reads (round(100 x Born-rule authorship probability)) and
  not `llr_deviation_score`. The report takes the live rule's outcome from the
  exported verdict and never re-derives it from `deviation_score`, so a
  candidate cut-off is a change of the score the flag reads, not only of its
  threshold.
- **Feature separation is exploratory.** Dozens of features on about 20
  students; nothing there is a finding, and no weight is changed from it.
