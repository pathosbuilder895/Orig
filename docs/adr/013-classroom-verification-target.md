# ADR-013: Aim verification at the classroom case, not at PAN and not at distance from self

**Status:** Proposed
**Date:** 2026-10-22
**Deciders:** Andrew (owner). Any step that changes a score or an action also needs its validation gate and a human approval (NORTH_STAR rule 4).
**Relates to:** ADR-001 (density-matrix scoring), ADR-007 (AI-likelihood gating), `docs/superpowers/specs/2026-09-20-adversarial-verification-threat-model-design.md`, PR 308 (official PAN scorecard), PR 311 (adversarial gates G-A1 to G-A6).

Every number below is already recorded in the repo or in those two PRs; sources are given inline. None of it is real student writing.

## Context

### The question Original answers

A teacher asks: does this submission fit the writing this student has proven is theirs? The proof is teacher-approved writing, at best sealed Bluebook sessions. In the field's terms this is **authorship verification with enrollment**: one claimed author, a few known samples, one questioned text, and a decision that must protect honest students first.

That premise is sound and it is the right product. This ADR is about how it is measured and built.

### How the live path answers it today

- `deviation_score` (`original/quantum/scoring.py`): per-feature z-scores of the submission against the student's own baseline mean and spread, over the 109-feature pipeline, mapped to an action by fixed thresholds.
- The pilot sets `NULL_MODEL=none` (`render.yaml`), so no other writer enters the decision.
- `ScoreSubmissionRequest.assignment` (`original/schemas.py`) is accepted but never read by scoring. The scorer does not know which prompt a piece answers, or what anyone else wrote for it.
- Baseline provenance is weighted (`AUTH_WEIGHTS` in `original/constants.py`: proctored 2.0, verified 1.0, canvas 0.8, unverified 0.5).

### What the measurements say

| Scorer | Test | Result | Source |
|---|---|---|---|
| Live `deviation_score` | Classmate's essay to the **same prompt** vs the student's own (Riddell-Juola, N=3/5/10) | AUROC 0.461 / 0.507 / 0.465 | PR 311, G-A4 |
| Live `deviation_score` | Honest new-topic essays at `schedule_conversation`+ | 30% / 21% / 15% (non-professional writers); 4-8% (published prose) | PR 311, G-A1 |
| Collections "worth a look" mark | Honest Riddell-Juola essays marked | 45% / 63% / 54% | PR 311, G-A1 |
| Live `deviation_score` | Baseline padded with someone else's writing | catch at `schedule_conversation`+ falls from 61% to 24% | PR 311, G-A5 |
| Live `deviation_score` | Own work in a new genre vs another author (C.S. Lewis vs Chesterton) | AUROC 0.387 | `validation/genre_crossgenre_2026-08/` |
| Peer-relative LLR | Same Lewis corpus | AUROC 0.863 | same |
| Peer-pool null model | Public authors, decontaminated, N=3 | pooled AUC 0.8868 → 0.9527 | `validation/benchmarks/2026-08-01/*public_authors*` |
| Fused score (peer-centred z + compression) | PAN cross-fandom | AUC 0.889 vs 0.798 for the production score | fused-score design spec |
| MFW Delta (Burrows) | Attribution among 11 public authors | top-1 100% [0.88, 1.00] vs deviation-calibrated 74.07% | `validation/benchmarks/2026-08-02/public_authors/` |
| LUAR + style fusion (validation-only) | PAN 2021 lock / Gutenberg lock | AUC 0.938 / 0.973 | `MODEL_CARD.md` |
| Fitted cut-offs | Moved to a new population | 0.78% false accepts became 6.0%; a PAN-fit cut-off gave 92% false positives on Gutenberg | `MODEL_CARD.md` |

Three patterns:

1. **The representation is the bottleneck.** In G-A4 the student's own essay and the classmate's essay answer the same prompt, so topic is already held constant, and the live scorer still cannot separate them. The Riddell-Juola corpus exists because standard stylometry identifies these writers from their earlier writing before they try to disguise it. Per-feature z-scores over 109 hand-built features, against 3-10 short samples, are not carrying that signal.
2. **Every measurement that adds other writers beats distance from self.** The LLR, null model, fused score and LUAR fusion all ask "more like this student than like other writers?". The live path asks only "how far from this student?", which also grows when the topic, genre or length changes.
3. **Cut-offs fitted on one population do not carry over to another.** Any threshold has to be set on, or checked against, the population it will be used on.

### Where PAN fits

PAN asks a different question: given two texts and no enrollment, were they written by the same person? Its tasks are open-set and use balanced pairs, scored by AUROC, c@1, F1, F0.5u and Brier. The published winners reach AUROC 0.969 (2020) and 0.987 (2021) on fanfiction, but only 0.616 when the kind of writing changes (2023, cross-discourse).

On PAN's own pairs Original abstains every time (overall 0.125 / 0.250; PR 308), because a PAN problem gives one known text and every verifier here needs three. That is NORTH_STAR rule 3 working as intended, not a defect. Raising the PAN overall score would mean answering from one known text, which rules 3 and 4 rule out.

PAN is still useful for one thing: **choosing the style representation**. Its data is large, public and split by author, and it scores representations the same way whatever decision layer sits on top.

### What Original has that PAN systems do not

1. **Proctored enrollment.** Sealed Bluebook sessions are writing we know the student produced. PAN has no such anchor.
2. **A known cohort.** Every classmate who answered the same prompt, within the same workspace.
3. **The same prompt.** The cohort's answers hold topic and genre fixed for the reference set.
4. **History.** Dated baselines across a term.
5. **A teacher who decides, and permission to say "inconclusive".**

No public benchmark rewards these. They are the structural advantage, and the current build uses only the first, as a weight.

## Decision

Proposed: set the target architecture to **classroom verification**, built and judged in two layers.

**Layer 1: a style representation that carries authorship on short, same-prompt writing.**
Choose it by measurement, not by preference. Compare the candidates the repo already has on the Riddell-Juola same-prompt cells (G-A4) and on PAN:
- MFW Delta (`validation/attribution/delta.py`)
- character n-grams
- compression (`original/fusion/`)
- peer-centred features
- the existing 109-feature vector
- LUAR, if hosting allows

The cheap candidates come first: they fit the current instance and need no external inference (rule 7).

**Layer 2: a decision relative to who else could have written the piece.**
For a submission *s* from claimed student *A* to prompt *P*:
- **Reference set.** Other students' submissions to *P* in the same writing session and workspace, plus the workspace's baseline pool (today's `null_pool`). Machine-written answers to *P* are added only if they can be produced without sending student writing out (rule 7) and the owner approves. Never another workspace's writing.
- **Evidence.** How much closer *s* is to *A*'s baseline than the reference set is: a rank within the cohort and a calibrated likelihood ratio.
- **Anchor.** Proctored writing defines *A*'s profile. Other approved samples count only where they agree with it, which targets the padding attack (G-A5).
- **Abstain** when:
  - the cohort is too small (start at 8, the fused score's reference count);
  - there is no proctored anchor;
  - the texts are too short.

  A cohort rank has a floor of 1/(N+1): with 20 classmates it can never say less than 5%. It must not be presented as rarer than that.
- **Output.** A consistency observation for the teacher, for example "less like Maya's sealed writing than most classmates' answers to this prompt". It never names another student and is never a verdict (rules 1 and 10).

**The scorecard is the classroom gates, not PAN.** Primary:
- honest-student flags at `schedule_conversation`+ and on the Collections mark (G-A1);
- same-prompt classmate separation (G-A4);
- padding resistance (G-A5);
- AI imitation and AI rewording (G-A2, G-A3), once measured.

Secondary: calibration (Brier, Cllr) and the inconclusive rate. PAN's official scorecard stays in PR 308 as a representation benchmark only.

Until a candidate beats the live path on those gates, on real student writing, `deviation_score` stays the live path, and anything new runs report-only or in shadow first.

## Options considered

### Option A: Keep distance from self and retune thresholds (status quo)

| Dimension | Assessment |
|---|---|
| Complexity | Low: built |
| Cost | Low: runs on the current instance |
| Fit to the classroom threat | Poor: AUROC 0.46-0.51 on same-prompt classmates |
| Evidence | Fails G-A1, G-A4, G-A5; the 2.35 divisor was tuned on the same 11 authors it was then certified on |
| NORTH_STAR fit | Weak on rule 4: 15-30% of honest new-topic essays reach the conversation bar |

**Pros:** simple; explainable per feature; needs no other students.
**Cons:** it cannot tell a classmate from the student; it flags honest topic changes; padding the baseline defeats it; every retune so far has been in-sample.

### Option B: Score relative to the workspace's baselines (built: `NULL_MODEL=impostor`, fused score, style expert, characteristic weights)

| Dimension | Assessment |
|---|---|
| Complexity | Medium: built and tested, off or shadow today |
| Cost | Medium: a full state scan per scoring request |
| Fit to the classroom threat | Unmeasured on same-prompt classmates; better than A everywhere it has been measured |
| Evidence | 0.863 vs 0.387 (Lewis); 0.9527 vs 0.8868 (public authors); 0.889 vs 0.798 (PAN) |
| NORTH_STAR fit | Good, if shadowed first |

**Pros:** the code exists; it moves in the right direction on every corpus measured; the shadow paths are tested to be inert.
**Cons:** peers' baselines answer other prompts, so their topic does not match the submission's; needs 3-8 peers with baselines; the fused score's compression channel drifts as a baseline grows; nothing here has seen student writing.

### Option C: Classroom verification (proposed)

| Dimension | Assessment |
|---|---|
| Complexity | Medium-high: needs the prompt and session id passed through to scoring, scoring after the session closes, and a representation bake-off |
| Cost | Low with the cheap channels; LUAR would need a larger instance |
| Fit to the classroom threat | Designed for it: a same-prompt reference, a proctored anchor, abstention |
| Evidence | None yet; the decisive test (Action 1) is cheap and offline |
| NORTH_STAR fit | Good, with three owner decisions (see Consequences) |

**Pros:**
- It targets the measured failures directly.
- A rank within the cohort is calibrated on the population being scored, which sidesteps the cut-off transport failures.
- It uses the advantages only Bluebook has.

**Cons:**
- It must wait until the cohort has submitted, so it cannot score live.
- Small classes will often abstain.
- Classmates' sealed writing informs another student's result.
- A cohort that shares one ghostwriter or one AI tool could mask itself.
- It is entirely unmeasured.

### Option D: Chase PAN with an open-set pairwise neural verifier

| Dimension | Assessment |
|---|---|
| Complexity | High |
| Cost | High: transformer weights do not fit the ~512 MB Starter instance, and the hosting plan is still undecided |
| Fit to the classroom threat | Indirect: no enrollment, no cohort, one known text |
| Evidence | Strongest representations measured (LUAR fusion 0.938 on the PAN 2021 lock), but PAN cut-offs gave 92% false positives on Gutenberg |
| NORTH_STAR fit | Poor: it pushes toward answering from one known text (rules 3, 4) |

**Pros:** a public number to compare with; the strongest known representations.
**Cons:** it answers the wrong question; it is costly to host; its thresholds do not transfer.

## Trade-off analysis

- **Representation before decision rule.** G-A4 already compares the student's essay with same-prompt classmates and gets about 0.5. A better reference set alone cannot fix a representation that does not separate these writers. So Layer 1 is the first experiment, and Layer 2 is what makes a good representation safe to show a teacher.
- **Timing against accuracy.** C gives up scoring each piece the moment it arrives in exchange for scoring against the people who answered the same question. Teachers review after a session closes anyway, so the teacher path loses little. The student self-check (`/me/work`) has no cohort and keeps the A/B path, labelled as such.
- **Privacy against accuracy.** C uses classmates' sealed writing as reference: same workspace only (the `null_pool` rule), never shown, never named. Rule 10 tells students their sealed work may be used as reference writing; whether that wording covers informing a classmate's result is an owner decision, and the student notice may need to say so.
- **Cheap against strong.** PAN results say neural embeddings are strongest. The repo's own results say MFW Delta and compression get much of the way for free. Start cheap, and move to LUAR only if it wins the bake-off by enough to justify the hosting cost.
- **ADR-001 is not overturned.** The density-matrix layer is the scoring geometry. This ADR changes what it is fed (the representation) and what it is compared against (the reference set).

## Consequences

**Easier:**
- One scorecard (the classroom gates) instead of competing headline numbers.
- Thresholds set on the population they are used on.
- A reason to keep the PAN comparison honest instead of chasing it.

**Harder:**
- Scoring waits for a cohort.
- Bluebook must pass a prompt and session identity into scoring; today `assignment` is a free-text label that scoring ignores.
- Small classes abstain more.

**To revisit:**
- Whether machine-written reference answers are allowed, and how they are produced (rule 7).
- The minimum cohort size.
- Whether the Collections "worth a look" mark (45-63% of honest Riddell-Juola essays) should stay switched on while Original is in testing.

**Owner decisions needed:**
1. Classmates' sealed writing as reference: is the notice wording enough?
2. Machine-written reference answers: allowed, and by what route?
3. Is the Collections mark's honest-essay rate acceptable for the testing phase?

## Action items

1. [ ] **Representation bake-off (offline, cheap, decides Layer 1).** Score the G-A4 and G-A1 Riddell-Juola cells with each candidate from Layer 1 through the SP1 harness (`validation/adversarial/`). Report AUROC with intervals, plus honest flags at a matched severity. Pass bar: the same-prompt AUROC's lower bound above 0.5, and well clear of the live path's 0.46-0.51, without raising G-A1.
2. [ ] Make G-A1, G-A4 and G-A5 (and G-A2/G-A3 once measured) the primary scorecard in `validation/README.md`. Keep PAN (PR 308) labelled as a representation benchmark.
3. [ ] Pass a prompt and session id from Bluebook into `score_submission`, as metadata only, with no score change.
4. [ ] Add a proctored-anchor rule to baseline assembly, behind a flag, and re-run G-A5.
5. [ ] Build the cohort reference and abstention rules as a report-only field, with byte-identity tests for flag-off.
6. [ ] Get the three owner decisions above.
7. [ ] Make the first real measurement in the volunteer alpha, using same-prompt sessions, so Layer 2's first real number is a classroom one.
8. [ ] Run shadow before on. Promote nothing without its gate and Andrew's approval.
