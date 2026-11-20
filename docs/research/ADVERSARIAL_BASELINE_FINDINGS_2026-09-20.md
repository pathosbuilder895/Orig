# Adversarial verification: first SP1 measurement (G-A1 to G-A6)

*Run 2026-10-21. Programme date 2026-09-20: this is the Task 20 measurement
for `docs/superpowers/specs/2026-09-20-adversarial-verification-threat-model-design.md`
and `docs/superpowers/plans/2026-09-20-adversarial-verification-sp1.md`.
Raw rows, summary and gate results:
`validation/adversarial/reports/2026-10-21_sp1_first_run.json`.*

## Bottom line

Measured on the live scoring path with the pilot's flags, against published
authors and against the CC0 Riddell-Juola corpus of non-professional writers:

| Gate | Verdict | In one line |
|---|---|---|
| G-A1 cold-start FPR | **fail** | 85% / 94% / 88% of genuine documents land at `monitor` or above at N=3/5/10 (bar 5%). At `schedule_conversation` or above: 15% / 16% / 12%. |
| G-A2 LLM imitation | **uninformative** | Measured 2026-11-19 (addendum below). The gate reads uninformative on sample size, but its separation does not survive length matching: against the author's own excerpts of the same length, the imitations were not told apart (AUROC 0.27 to 0.43). |
| G-A3 LLM paraphrase / MT | **fail** | Measured 2026-11-19 (addendum below): an AI rewording or German round trip of a student's own work was not told apart from the work itself (AUROC 0.56 to 0.59, bar 0.60). |
| G-A4 peer swap | **fail** | Published authors from other eras separate well (AUROC 0.86 to 0.90 at `4bab200`; see the addendum for drift since). For classmates answering the **same prompt** no separation was observed (AUROC 0.46 to 0.51; the 95% intervals reach about 0.7, so modest separation is not excluded). |
| G-A5 sigma inflation | **fail** | Replacing a third to two fifths of a baseline with someone else's writing cuts the catch of other people's writing at `schedule_conversation`+ from 61% to 24% (same documents, same victims), and at `monitor`+ below the bar at N=5 and N=10. |
| G-A6 baseline integrity | **fail** | A drift-gate hold or an integrity outlier note appears on 15% to 58% of **clean** baselines and points at the injected document on 0% to 33% of poisoned ones: it does not tell them apart. |

What this says, plainly:

1. **`monitor` carries no information on its own.** It is the normal outcome
   for honest work (73% to 100% of genuine documents, depending on corpus
   and N). The bar that asks a teacher to act is `schedule_conversation`;
   there, honest published prose is flagged 4% to 8% of the time (first run,
   at `4bab200`; 8% to 25% at `216c3e2d`, see the 2026-11-19 addendum) and honest
   non-professional essays on a new topic 15% to 30%.
2. **The classroom case was not detected.** On a classmate's essay to the
   same prompt, no separation from the student's own essay was observed
   (AUROC 0.46 to 0.51 at every N). The intervals are wide enough that a
   modest effect is not ruled out, but nothing like the 0.86 to 0.90 seen on
   published authors, whose separation comes from writers of different
   centuries and genres: the easy case.
3. **Baseline padding works.** A student who mixes someone else's writing
   into a minority of their baseline widens it enough to keep most later
   impostor work below the conversation bar. The drift gate held the
   injected document in 2 of 25 profiles.
4. **The integrity note is not a poisoning detector, and it fires on honest
   baselines.** Its outlier note ("one sample stylistically unlike the
   others") rides on every live `/score` response at a rate far above G1's
   5% budget. No teacher sees it today: Collections reads only the block's
   `readiness`, and Task 7's mirror into the professor narrative never fires
   on the live path (the narrative reads `Layer7Output.baseline_integrity`,
   which nothing sets, and the report that builds the narrative needs the
   context manifest, which the pilot leaves off). This false-alarm rate is
   the thing to fix before anyone surfaces the note.
5. **Collections' "worth a look" mark: never on one corpus, about half on
   the other.** It never fired on the public-author documents (0 of 50
   genuine, 0 of 125 peer swaps), and fired on 45% to 63% of honest
   Riddell-Juola essays and 49% to 60% of same-prompt peer swaps. The two
   corpora differ in length, writer and genre at once, so this does not say
   which of those drives it; on the essay-length, non-professional corpus it
   marks about half of everyone, honest or not.

None of this changed a score, a constant or a flag. These are measurements
of the pipeline as it ships, and the numbers every later sub-project must
report against.

## Addendum 2026-11-19: LLM attacks (G-A2, G-A3)

*Corpus: `validation/adversarial/corpus/llm_attacks/`, 61 documents written
by Claude Opus 5.5 through Claude Code subagents. No API key was available,
so the owner approved generating them with Claude itself; how they were
made, and every way that differs from `gen_llm_attacks.py`, is in that
directory's `PROVENANCE.md`. Report:
`validation/adversarial/reports/2026-11-19_llm_attacks.json`, scored at
`216c3e2d` on the live path with the same pilot flags as the first run. That
report re-scored only the public-author clean cells and the LLM cells, so
read only G-A2 and G-A3 from it.*

| Gate | Verdict | In one line |
|---|---|---|
| G-A2 LLM imitation | **uninformative** | The gate's own verdict: every point estimate clears its bar (caught at `monitor`+ 100%, AUROC 0.83 to 0.87), but with 13 and 6 victims no AUROC's 95% lower bound clears 0.60 (0.58 / 0.44 / 0.44). That separation does not survive length matching: scored against the author's own excerpts cut to the imitation's length, the imitations were not told apart (AUROC 0.27 to 0.43). |
| G-A3 LLM paraphrase / MT | **fail** | Paraphrases and German round trips of a student's own work were not told apart from the work itself: AUROC 0.56 to 0.59 at N=3, 5 and 10, below the 0.60 bar on the point estimate. Japanese round trips 0.61 to 0.64, none demonstrated. |

Each population is scored against the same victims' genuine held-out
documents at the same N: all 13 victims for imitation at N=3, the 6
cross-work victims everywhere else.

| Attack | N | Docs | `monitor`+ | `schedule_conversation`+ | Genuine at `schedule_conversation`+ | AUROC (95% lower bound) |
|---|---|---|---|---|---|---|
| imitation | 3 | 13 | 100% | 46% | 8% (2/26) | 0.867 (0.578) |
| imitation | 5 | 6 | 100% | 67% | 17% (2/12) | 0.833 (0.436) |
| imitation | 10 | 6 | 100% | 67% | 25% (3/12) | 0.847 (0.436) |
| paraphrase | 3 | 12 | 83% | 17% | 17% (2/12) | 0.556 |
| paraphrase | 5 | 12 | 100% | 17% | 17% (2/12) | 0.583 |
| paraphrase | 10 | 12 | 92% | 17% | 25% (3/12) | 0.590 |
| round trip, German | 3 | 12 | 83% | 25% | 17% (2/12) | 0.576 |
| round trip, German | 5 | 12 | 83% | 25% | 17% (2/12) | 0.562 |
| round trip, German | 10 | 12 | 92% | 17% | 25% (3/12) | 0.576 |
| round trip, Japanese | 3 | 12 | 92% | 17% | 17% (2/12) | 0.611 |
| round trip, Japanese | 5 | 12 | 92% | 8% | 17% (2/12) | 0.639 |
| round trip, Japanese | 10 | 12 | 92% | 17% | 25% (3/12) | 0.632 (0.391) |

For comparison, another published author's own writing under the same
victims' names (the clean cells' peer swaps) reaches
`schedule_conversation`+ 65% / 60% / 70% of the time at N=3/5/10.

What this says, plainly:

1. **AI imitation was not told apart from the author; the gate's separation
   came from length.**
   Claude's imitations are about 650 words, and G-A2 compares them with
   genuine documents of 2,500 to 19,400 words. A short paper against long
   past papers reads as unlike them whoever wrote it
   (`docs/research/2026-11-14-length-matched-baseline.md`), so a control
   scored each victim's genuine held-out documents cut to the imitation's
   own length, on the same path and baselines (the length and layout
   controls below). Against those, the imitations were not told apart from
   the author: AUROC 0.27 / 0.35 / 0.43 at N=3/5/10, and the author's own
   excerpts reached `schedule_conversation`+ more often (77% / 75% / 67%)
   than the imitations (46% / 67% / 67%). The reverse ordering, imitations
   reading as more like the author than the author's excerpts, is not
   demonstrated either (lower bounds 0.50 / 0.30 / 0.19 in that
   direction). So G-A2's uninformative verdict understates the gap: more
   victims under this design would most likely produce a pass for the
   wrong reason. Before a G-A2 pass can be read, its genuine comparator
   has to be matched in length (a gate change, with its own failure
   witness; recorded as T-71's debt).
2. **AI rewording of a student's own work was not told apart from the
   work.** A paraphrase or a German round trip of a genuine document is
   flagged about as often as the document itself (within one or two
   documents of 12 at either bar). No separation was observed; with 12
   documents a side the intervals reach about 0.8, so modest separation is
   not excluded. This asks whether the laundering step is visible, and on
   this corpus it was not: the rewrites keep each document's order and
   content, though the paraphrases keep only 2% to 17% of its word 8-grams.
   This corpus laundered only the victims' own texts, so it says nothing
   about a purchased essay passing as the student's.
3. **Japanese round trips keep less of the source's wording than German
   ones** (7% to 18% of its word 8-grams against 16% to 54%). Their AUROCs
   are higher (0.61 to 0.64 against 0.56 to 0.58), but that gap is within
   the noise of 12 documents a side and is not demonstrated.

### Length and layout controls for G-A2 (report-only)

`validation/adversarial/imitation_controls.py`, results in
`validation/adversarial/reports/2026-11-19_imitation_controls.json`, scored
at `216c3e2d` on the same live path and baselines as G-A2 (50 cells). Two
controls for the two differences the validation review found:

- **genuine_slice:** each genuine held-out document cut to the first W
  words, W the word count of that victim's imitation at that N, keeping
  its own formatting. Matches length.
- **imitation_flat:** the imitation with its paragraph breaks removed, for
  the six cross-work victims, whose baselines and held-out documents are
  each one unbroken paragraph (the imitations have 3 to 27). Matches
  layout as well; it turned out not to matter (below).

| N | Victims | Imitation vs full-length genuine | Imitation vs same-length genuine | Flattened imitation vs same-length genuine | `schedule_conversation`+: imitation / same-length genuine / full-length genuine |
|---|---|---|---|---|---|
| 3 | 13 | 0.867 | 0.269 | 0.275 | 46% / 77% / 8% |
| 5 | 6 | 0.833 | 0.347 | 0.361 | 67% / 75% / 17% |
| 10 | 6 | 0.847 | 0.431 | 0.389 | 67% / 67% / 25% |

Mean deviation: imitations 0.59 / 0.62 / 0.64, same-length genuine
excerpts 0.66 / 0.64 / 0.65. The separation does not survive length
matching; at N=3 the screen's upper bound in the detection direction is
about 0.50, below the 0.60 bar. Removing the paragraph breaks changes almost
nothing, and could not change much: these victims' paragraph length is the same in every baseline, so the score leaves that feature out (`StudentState.active_feature_mask`, `original/quantum/state.py`). Ten of the 18 flattened
imitations score exactly as before and the rest move by at most 0.025.

Two caveats on the excerpts. An excerpt starts mid-sentence and is cut from
a longer work, while an imitation is a complete piece. And in five of the
seven plain-manifest victims the first ~650 words are not ordinary prose:
douglass, newman and kempis open with chapter or discourse headings,
all-capitals synopses or footnotes, boethius and james with indented verse
or quotation. That raises those excerpts' scores and pushes the AUROC down,
but it does not drive the result: the six cross-work victims, whose
excerpts are running prose (an inline chapter title at most), give 0.18 at N=3 on their own, and the seven
plain-manifest victims 0.30.

```bash
.venv/bin/python -m validation.adversarial.imitation_controls \
    --report validation/adversarial/reports/2026-11-19_llm_attacks.json \
    --out /tmp/imitation_controls.json
```

Caveats that go with these numbers:

- **One generator, published authors, and the model knew.** Every document
  is Claude Opus 5.5 answering a brief that said it was a test; the victims
  are nineteenth- and early-twentieth-century prose. See `PROVENANCE.md`.
- **Famous originals can be recalled.** A German round trip of Mill shares
  54% of its word 8-grams with Mill's own text, likely from memory. That
  makes a round trip look more like its author than it would for a student,
  so these round trips are, if anything, harder to catch than a student's.
- **G-A3 at N=3 covers 6 of 13 victims.** The seven plain-manifest victims
  (held-out documents 2,800-19,400 words, 12 of 14 over 7,500) have
  imitations only (the owner deferred the rest), so a G-A3 pass at N=3
  would have been withheld anyway; the fail stands on its point estimates.
- **Small, repeated samples.** Each G-A3 comparison is 12 laundered against
  12 genuine documents, two per victim from six victims, so the effective
  sample is nearer six; G-A2 at N=3 compares 13 imitations with 26 genuine
  documents. The same 36 laundered documents are scored at every N, so
  "at every N" is one corpus against three baseline sizes, not three
  independent replications. The AUROC screen assumes independent documents
  (lower bound 0.39 at 0.63).
- **Paraphrases added paragraphs.** The sources of the six victims are each
  one paragraph; the paraphrases of chesterton, dickens and emerson split
  them into about 15 to 55. That likely matters little: these victims' paragraph length is the same in every baseline, so the score leaves that feature out (`StudentState.active_feature_mask`, `original/quantum/state.py`), and
  flattening the imitations moved their scores by at most 0.025.
- **The report's metadata was annotated by hand.** Its `reused_from` and
  `read_only_these_gates` fields were written by hand (the scratch paths
  replaced), and its top-level `kinds`, `n_cells`, `corpus_fingerprint` and
  `runtime_seconds` describe run A only, because `--reuse` keeps the first
  input's metadata; both runs' are under `merged_meta`. The G-A1, G-A4, G-A5
  and G-A6 entries in it are partial and are not results.
- **Honest-paper scores moved since the first run.** Re-scored at
  `216c3e2d`, the public-author genuine documents reach `monitor`+ 62% /
  83% / 75% at N=3/5/10 (first run, at `4bab200`: 73% / 83% / 92%) and
  `schedule_conversation`+ 8% / 17% / 25% (4% / 8% / 8%). The mean
  deviation moved by -0.016, the largest single document by 0.29. Peer-swap
  AUROC on public authors moved too, from 0.892 / 0.897 / 0.864 to
  0.907 / 0.808 / 0.817 (drift, not a G-A4 result: this run has no
  Riddell-Juola cells). 86 commits touching `original/` landed between the
  two; which one moved these was not investigated here, and every other
  number in this document outside this addendum is from the first run.

```bash
.venv/bin/python -m validation.adversarial.report --out /tmp/a.json --kinds clean,llm_imitation,llm_paraphrase
.venv/bin/python -m validation.adversarial.report --out /tmp/b.json --kinds llm_roundtrip_de,llm_roundtrip_ja
.venv/bin/python -m validation.adversarial.report --out /tmp/llm.json --reuse /tmp/a.json /tmp/b.json
```

Run A took 635 s on 8 workers, run B 157 s.

## What was measured, and how

**Scoring path.** Every number below is the **live** `deviation_score`,
`authorship_probability` and `recommendation.action`: each document goes
through the real `POST /students/{id}/baseline` and
`POST /students/{id}/score` routes (in-process FastAPI `TestClient`, a
throwaway SQLite file per worker), with the pilot blueprint's scoring
configuration: `lock_environment()` plus
`validation/adversarial/report.py:LIVE_SCORING_ENV` (research flags off,
`NULL_MODEL=none`, `TYPICALITY_SCORING=0`, `MIN_BASELINE_SAMPLES=3`). The
battery's G1 to G6 run the typicality path instead; these gates do not. The
Phase 8 drift gate runs on every baseline upload, so a poisoned document can
be held before it reaches the profile, and the route refuses to score (422)
when fewer than three baselines were admitted; refusals are recorded, never
counted as flags or passes. Tier 10 used its TF-IDF backend, which is also
what the pilot runs (`requirements-pilot.txt` leaves out
sentence-transformers). The harness database is fresh, so the static
`ACTION_THRESHOLDS` apply; if an operator ever applies tuned thresholds in
the pilot, the bands move.

**Two live decision rules.** The classic analysis page shows the action
band. Collections (Bluebook) marks a sealed exam "worth a look" from a
different number: `authorship_probability` below 0.70 on a ready baseline
(`bbSealStatus` in `demo/bluebook/Exam.jsx`). Both are reported.

**One severity bar for the gates.** A genuine document is "flagged", and an
attack document "caught", when its action is `monitor` or above. The
borrowed bars are defined at exactly that severity: G1's 5% same-author
budget and T-2's 60% ghostwriter detection floor; the separation bar (AUROC
0.60) is G7's. `monitor` is the mildest band ("keep this in context, no
urgency now"); every table also gives `schedule_conversation`+ (the bar
T-01's cold-start certification uses) and `escalate`.

**Statistics.** Every population is split by N, because the same documents
recur at N=3, 5 and 10. Proportions carry Wilson intervals; AUROCs a Wilson
bound over the smaller side's document count. Both assume independent
documents, which windows of one book, or one peer essay scored against five
classmates' baselines, are not: treat them as screens.

## Corpus

**Public authors** (`validation/public_authors/` through
`validation/adversarial/profiles.py`, harness seed 20260920; 107 distinct
documents, fingerprint `4b520d42…`):

| N | victims | genuine holdouts | peer documents | where the victims come from |
|---|---:|---:|---:|---|
| 3 | 13 | 26 | 65 | 6 cross-work authors (2,500-word windows, holdouts from a different book) and 7 plain-manifest authors (documents up to 19,372 words, holdouts from the same work family) |
| 5 | 6 | 12 | 30 | the 6 cross-work authors only |
| 10 | 6 | 12 | 30 | the 6 cross-work authors only |

Each victim's peer documents are five other victims' own first baseline
document: a different person's real writing under this student's name.

**Riddell-Juola** (CC0, Zenodo 10.5281/zenodo.18729526; 699 distinct
documents, fingerprint `068c7afb…`). 66 adults wrote one essay to a single
prompt ("describe your neighbourhood") under one of three instructions:
none (control, 21), disguise your style (obfuscation, 27), write like
Cormac McCarthy (imitation, 18). Each participant also supplied earlier
writing, committed on 2026-10-21 with the owner's approval as 856 chunks of
86 to 889 words (median 525) for 65 participants. A participant is eligible
at N when they have N+1 chunks: N baselines plus one held out.

| N | control | obfuscation | imitation |
|---|---:|---:|---:|
| 3 | 21 | 27 | 17 |
| 5 | 19 | 27 | 16 |
| 10 | 13 | 22 | 15 |

## Results

### G-A1: genuine work against a clean baseline

| Corpus | N | genuine docs | `monitor`+ | `schedule_conversation`+ | `escalate` | Collections mark |
|---|---|---:|---:|---:|---:|---:|
| public authors | 3 | 26 | 19 (73%) | 1 (4%) | 0 | 0 |
| public authors | 5 | 12 | 10 (83%) | 1 (8%) | 0 | 0 |
| public authors | 10 | 12 | 11 (92%) | 1 (8%) | 0 | 0 |
| Riddell-Juola | 3 | 20 | 20 (100%) | 6 (30%) | 1 (5%) | 9 (45%) |
| Riddell-Juola | 5 | 19 | 19 (100%) | 4 (21%) | 1 (5%) | 12 (63%) |
| Riddell-Juola | 10 | 13 | 11 (85%) | 2 (15%) | 1 (8%) | 7 (54%) |

Pooled per N (the gate): 39/46, 29/31 and 22/25 at `monitor`+. One
Riddell-Juola participant at N=3 was refused scoring (the drift gate held
enough of their earlier writing to leave fewer than three baselines). The
Riddell-Juola genuine document is a new-topic essay against earlier writing
on other subjects, which is what a real assignment looks like (R7).

### G-A4: someone else's writing under this student's name

| Population | N | docs | `monitor`+ | `schedule_conversation`+ | `escalate` | Collections mark | AUROC vs genuine (95% low) |
|---|---|---:|---:|---:|---:|---:|---:|
| public authors | 3 | 65 | 100% | 62% | 2% | 0% | 0.892 (0.710) |
| public authors | 5 | 30 | 100% | 63% | 0% | 0% | 0.897 (0.646) |
| public authors | 10 | 30 | 100% | 57% | 3% | 0% | 0.864 (0.552) |
| Riddell-Juola, same prompt | 3 | 100 | 96% | 26% | 2% | 49% | **0.461** (0.258) |
| Riddell-Juola, same prompt | 5 | 95 | 94% | 26% | 1% | 60% | **0.507** (0.317) |
| Riddell-Juola, same prompt | 10 | 65 | 75% | 8% | 0% | 60% | **0.465** (0.232) |

The same-prompt peer swap is
caught at `schedule_conversation`+ at roughly the rate honest essays are
flagged (26% against 30% at N=3; 8% against 15% at N=10), and its scores
were not observed to be higher than the student's own (the AUROC intervals
are wide: 0.26 to 0.66, 0.32 to 0.73, 0.23 to 0.71). Nothing on the live path knows who the classmates
are (`NULL_MODEL=none`); this is the structural blind spot the spec named.

### Deliberate restyling by the writer (Riddell-Juola, report-only)

The participant's own obfuscation or imitation essay against their own
earlier writing, compared with the honest essays of the OTHER participants
(the control group) against theirs:

| Essay | N | `monitor`+ | `schedule_conversation`+ | mean deviation | AUROC vs control essays (95% low) |
|---|---|---:|---:|---:|---:|
| obfuscation | 3 | 92% | 46% | 0.562 | 0.500 (0.299) |
| obfuscation | 5 | 100% | 48% | 0.584 | 0.639 (0.410) |
| obfuscation | 10 | 91% | 27% | 0.540 | 0.629 (0.355) |
| imitation | 3 | 88% | 47% | 0.543 | 0.541 (0.310) |
| imitation | 5 | 100% | 44% | 0.601 | 0.691 (0.444) |
| imitation | 10 | 80% | 33% | 0.507 | 0.554 (0.291) |

Deliberate restyling moved the live score only a little beyond what an
honest change of topic already does (AUROC 0.50 to 0.69, with lower bounds
of 0.29 to 0.44, so a modest effect is not excluded). The comparison is
between groups of writers, not the same writer both ways.

### G-A5: sigma inflation

`sigma_inflation` replaces a strict minority of the baseline (1 of 3, 2 of
5, 4 of 10 documents) with another author's writing. Compared only on
victims whose injected document reached the scored baseline, on the same
peer documents against both baselines. The donor author is drawn from the
same pool as the peer documents, so a peer document can be the very text
injected into the baseline; those (3, 6 and 6 at N=3/5/10) are dropped from
both sides, since scoring a document against a baseline that contains it
says nothing about the attack:

| N | pairs | spread clean | spread inflated | `monitor`+ clean | `monitor`+ inflated (bar: clean minus 10pt) | `schedule_conversation`+ clean | `schedule_conversation`+ inflated | AUROC inflated (95% low) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 3 | 11 | 0.0471 | 0.0759 | 52/52 (100%) | 47/52 (90%) | 34/52 (65%) | 12/52 (23%) | 0.750 (0.611) |
| 5 | 6 | 0.0621 | 0.0823 | 24/24 (100%) | **19/24 (79%)** | 14/24 (58%) | 4/24 (17%) | 0.663 (0.444) |
| 10 | 6 | 0.0756 | 0.0939 | 24/24 (100%) | **20/24 (83%)** | 13/24 (54%) | 8/24 (33%) | 0.653 (0.444) |

"Spread" is the unfloored per-feature standard deviation over the
measurable features, so the drift gate and the `0.15/sqrt(N)` floor cannot
fake growth. Pooled at `schedule_conversation`+: 61 of 100 caught against
the clean baseline, 24 of 100 against the padded one. Two N=3 profiles were
refused scoring: the drift gate held only the injected document, which left
two baselines, below the minimum of three. A first pass at this gate
counted the leaked documents and read 89% at N=3; the harness now records
them (`Cell.impostor_in_baseline`) and every reducer drops them.

### G-A6: does anything notice a poisoned baseline?

A detection is the drift gate holding, or the integrity block calling an
outlier, an **injected** document; on a clean baseline any hold or outlier
note is a false alarm (the Riddell-Juola control false alarms are 2, 2 and
2 holds and 6, 9 and 6 outlier notes at N=3/5/10; the public-author ones are
all outlier notes).

| Population | N=3 | N=5 | N=10 |
|---|---:|---:|---:|
| public authors, whole baseline obfuscated | 3/13 | 1/6 | 2/6 |
| public authors, whole baseline someone else's | 4/13 | 0/6 | 2/6 |
| Riddell-Juola, obfuscation essay added as a baseline | 4/27 | 5/27 | 6/22 |
| Riddell-Juola, imitation essay added as a baseline | 2/17 | 2/16 | 3/15 |
| **false alarm:** public authors, clean | 2/13 | 1/6 | 3/6 |
| **false alarm:** Riddell-Juola, honest control essay added | 8/21 | 11/19 | 6/13 |

The drift gate never held a wholesale-poisoned document, and held the
embedded essay in 2 of 53 control and 1 of 76 obfuscation profiles. For
wholesale poisoning a "detection" is any outlier at all, which happens at
the same rate on clean baselines: an internal-consistency check cannot see
a baseline written entirely in another voice, by construction.

### What a poisoned baseline does to the student's own later work

| Baseline | genuine flagged at `schedule_conversation`+ (N=3 / 5 / 10) |
|---|---|
| clean | 4% / 8% / 8% |
| sigma-inflated | 9% / 8% / 8% |
| whole baseline obfuscated | 35% / 33% / 17% |
| whole baseline someone else's | 65% / 50% / 50% |

Outsourcing the whole baseline makes the student's own later work look
foreign, and other authors' work then scores about the same as the
student's own against it (AUROC 0.456 / 0.535 / 0.535 at N=3/5/10, with the
donor's own documents dropped), so it only pays if the ghostwriter keeps
writing. Sigma inflation costs the attacker nothing on their own work.

### Mechanical obfuscation of a submission (report-only)

Running a peer's document through `MechanicalObfuscation` before submitting
it **raises** the catch at `schedule_conversation`+ from 61% to 76% (`escalate`
2% to 11%): against a one-class verifier, dumbing text down makes it look
less like anyone's established voice, as R2 predicts.

## What was excluded, and why

- **LLM attacks (G-A2, G-A3), in this first run.** The cache did not exist
  on 2026-10-21, so both gates read uninformative. They were measured on
  2026-11-19 once it was generated; see the addendum below.
- **Seminary corpus.** It has no real per-author grouping (G1 buckets its
  files into pseudo-students), so it cannot supply a genuine same-author
  holdout.
- **PAN20 cross-fandom.** `profiles.py` (Task 13) draws victims from
  `validation/public_authors/` only.
- **Riddell-Juola participant `cfeec8`** (no earlier writing in the bundle),
  and at each N the participants with fewer than N+1 chunks.
- **Validation-only verifiers** (delta engines, LUAR, the fused score). The
  plan measures the live path only; scoring other verifiers on this harness
  is later work.
- **The harness's fast path** (`runner.py`, `path="score"`): not the live
  extraction path, and no gate reads it.

## Honesty caveats

- **Not students.** The public authors are published nineteenth- and
  early-twentieth-century prose, mostly 2,500 words or longer. The
  Riddell-Juola writers are adults recruited online writing short essays to
  one prompt; closer to a classroom, still not this pilot's students. The
  absolute rates will not transfer exactly; the same-prompt result is the
  closest thing to a classroom this repository has measured.
- **Thin populations.** Six victims at N=5 and N=10 on public authors; 13 to
  27 participants per Riddell-Juola cell. Several verdicts would read
  uninformative rather than pass even if the point estimates cleared their
  bars; every fail here is a fail on its point estimate and is not softened.
- **R1 is contested.** Wang, Juola and Riddell's reproduction found the 2012
  obfuscation and imitation effects real but smaller than first reported.
  This measures the same human attack essays against one-class verification,
  which is a different question from their closed-set attribution.
- **R2: verification is not attribution.** These are one-class questions (is
  this the claimed student?) against one student's baseline. Attribution
  numbers do not carry over in either direction.
- **The bars are borrowed, not derived.** They come from G1, T-2 and G7 so a
  later sub-project cannot move them; none was tuned on these runs.
- **Reproducible.** Scoring is deterministic with amplitude scoring off: two
  independent public-author runs (one exploratory, one at `4bab200`) agreed
  on all 125 cells, every action, score, hold and integrity block.

## Provenance and commands

- Public-author cells scored at `4bab200` (8 workers, 3,610 s on a 12-core
  Mac shared with another session's 8-worker job); Riddell-Juola cells at
  `dd1e52d` after its corpus was committed (4 workers, 1,603 s). The
  scoring code is identical across `4bab200..51f9ead`: the later commits add
  corpus data, a metadata fix, the report format and the leak fix, none of
  which touches how a document is scored. The two row sets were merged and
  gated with `--reuse` at `51f9ead`, which also re-derived each row's
  `impostor_in_baseline` by rebuilding the cells (nothing re-scored; each
  rebuilt cell's injected positions matched its row). The public-author
  run's own metadata wrongly reads Riddell-Juola as present: it read corpus
  status after scoring, while the baselines were being committed. `dd1e52d`
  fixed that; that run built no Riddell-Juola cells.
- Environment: Python 3.11.15, numpy 2.2.6, scikit-learn 1.6.1, spaCy
  3.8.14, tier-10 backend `tfidf`.
- Verification through the battery: `python -m validation.calibration_gate
  --strict --only "G-A1,G-A2,G-A3,G-A4,G-A5,G-A6"`, scored afresh with the
  code at `ebf6d5d` (330 gate cells, 8 workers, 1,573 s; its report's
  `git_sha` reads `51f9ead`, the checkout when it was written). Same six
  verdicts; every leg of G-A1, G-A2, G-A3, G-A4 and G-A6 identical to this
  report's; G-A5 matched the pre-fix numbers (49/55, 21/30, 22/30), as it
  should before `51f9ead`. Exit 1, as `--strict` requires with any fail or
  uninformative gate.
- G-A5 re-run through the battery at `51f9ead` (`--only G-A5`, 50 cells,
  482 s): 47/52, 19/24, 20/24, AUROC 0.750 / 0.663 / 0.653, identical to
  this report.

```bash
.venv/bin/python -m validation.adversarial.report --out /tmp/adversarial.json
.venv/bin/python -m validation.calibration_gate --strict --only "G-A1,G-A2,G-A3,G-A4,G-A5,G-A6"
```

The first command scores every cell, report-only ones included; the second
scores only the cells the gates need. With the Riddell-Juola baselines
committed, one run now covers both corpora.
