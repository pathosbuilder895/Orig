# What carried the verifier's gain, and what could go into Original

| | |
|---|---|
| **Tool** | Claude Code; `validation/scholarly/ablation.py` on the development partition of the scholarly corpus |
| **Date** | 2026-11-12 |
| **Question** | Which ingredients of the learned verifier (`docs/research/2026-11-12-scholarly-learned-verifier.md`) caused its improvement over today's flags-off scorer, and which could become comparison rules inside Original without a trained model? |
| **Decision it informs** | Whether to build a class-relative character-profile comparison into Original (`original/`), and what validation it would need first. This note proposes; nothing has been changed or enabled. |

**This is a diagnosis on development only.** It uses the frozen verifier design and the same
development cross-fit: author-disjoint halves, each probe's source author kept in the same
fold, and the probe author removed from every comparison pool. Calibration was not used again,
`locked_test` was not opened, nothing under `original/` changed and no flag was enabled.
**Academics are not students**, and formal academic prose is the register where published
stylometric methods are weakest.

## Results: 1200-word past papers, 300-word new paper

Catch at a 5% honest flag rate, with author-bootstrap 95% intervals. Probes are random other
authors, other authors in the same subfield, or other authors in the same venue. The last
column is same-subfield catch at 300/300 and 1200/1200.

**Humanities (157 development authors)**

| variant | random | same subfield | same venue | same subfield 300/300 / 1200/1200 |
|---|---|---|---|---|
| full verifier | 92.5% [87.1, 96.5] | 85.8% [75.8, 91.8] | 86.2% [76.8, 92.4] | 68.2% / 96.3% |
| flags-off `deviation_score` | 24.4% [19.7, 28.8] | 22.6% [18.6, 26.2] | 18.6% [14.9, 22.4] | 21.1% / 34.8% |
| fixed combination (no training) | 86.8% [78.3, 90.8] | 72.0% [61.3, 78.1] | 76.7% [67.6, 82.9] | 52.9% / 83.7% |
| minus 1 length-matched pieces | 94.9% [91.9, 97.9] | 87.8% [81.5, 95.5] | 89.0% [83.3, 96.0] | 67.1% / 96.9% |
| minus 2 character channel | 78.2% [73.8, 83.0] | 70.0% [64.5, 75.0] | 68.5% [62.4, 74.9] | 43.5% / 93.4% |
| minus 3 topic-masked channel | 90.5% [85.6, 95.3] | 81.5% [74.0, 89.2] | 84.0% [75.5, 91.4] | 64.6% / 95.0% |
| minus 4 function words | 91.1% [86.6, 96.3] | 81.8% [73.8, 91.6] | 81.8% [75.0, 92.3] | 71.1% / 95.8% |
| minus 5 part of speech | 92.4% [87.2, 97.2] | 84.4% [74.8, 93.9] | 84.2% [75.8, 94.6] | 70.0% / 96.7% |
| minus 6 impostor comparison | 65.6% [59.7, 77.0] | 48.6% [44.1, 61.3] | 53.1% [47.7, 65.0] | 50.4% / 76.7% |
| minus 7 nearest piece | 89.9% [84.7, 94.3] | 79.3% [69.8, 87.1] | 81.5% [73.0, 87.8] | 66.1% / 94.9% |
| minus 8 Original's z-scores | 92.6% [85.8, 97.4] | 83.9% [73.0, 92.9] | 85.7% [75.9, 94.3] | 67.8% / 97.3% |
| plus 1 length-matched deviation | 28.6% [22.9, 34.4] | 26.6% [21.9, 32.4] | 23.7% [19.1, 29.3] | 17.1% / 25.9% |
| plus 2 character channel | 93.2% [81.0, 96.9] | 83.2% [63.9, 91.8] | 85.1% [68.2, 93.2] | 64.1% / 97.9% |
| plus 3 topic-masked channel | 68.5% [59.7, 74.3] | 57.7% [47.5, 64.0] | 57.8% [47.9, 63.8] | 39.5% / 90.0% |
| plus 4 function words | 37.5% [31.5, 44.6] | 31.7% [27.0, 38.2] | 31.3% [24.8, 38.0] | 21.7% / 62.0% |
| plus 5 part of speech | 54.9% [46.9, 63.5] | 44.7% [36.4, 53.7] | 44.8% [37.4, 53.3] | 36.0% / 75.2% |
| plus 6 LLR (impostor) score | 29.9% [23.4, 36.5] | 26.1% [21.4, 31.9] | 26.4% [20.2, 31.7] | 23.2% / 48.5% |
| plus 7 nearest piece | 87.2% [79.8, 92.5] | 74.4% [65.2, 83.5] | 79.3% [70.3, 88.0] | 59.1% / 96.4% |
| plus 8 Original's z-scores | 49.2% [44.9, 54.3] | 42.8% [38.7, 47.7] | 40.6% [36.0, 46.7] | 31.2% / 60.2% |

**Science (61 development authors)**

| variant | random | same subfield | same venue | same subfield 300/300 / 1200/1200 |
|---|---|---|---|---|
| full verifier | 98.7% [96.7, 99.8] | 95.4% [90.8, 98.3] | 98.9% [96.9, 99.8] | 94.4% / 98.9% |
| flags-off `deviation_score` | 38.6% [30.1, 49.3] | 29.3% [20.0, 41.5] | 33.3% [22.7, 43.6] | 28.5% / 50.7% |
| fixed combination (no training) | 97.9% [95.4, 99.2] | 93.7% [89.0, 96.7] | 97.6% [95.9, 99.0] | 81.7% / 98.4% |
| minus 1 length-matched pieces | 99.6% [97.7, 100.0] | 98.4% [95.4, 99.4] | 99.7% [98.4, 100.0] | 93.2% / 98.5% |
| minus 2 character channel | 91.6% [85.0, 97.6] | 88.0% [79.9, 95.6] | 91.8% [87.7, 97.8] | 70.1% / 98.9% |
| minus 6 impostor comparison | 95.0% [90.7, 97.7] | 85.0% [77.8, 90.6] | 95.3% [91.5, 97.2] | 75.4% / 91.5% |
| minus 7 nearest piece | 98.7% [96.5, 99.8] | 95.1% [90.9, 98.7] | 98.8% [97.2, 99.8] | 92.1% / 98.8% |
| plus 2 character channel | 97.9% [95.6, 100.0] | 95.1% [88.4, 98.1] | 98.1% [94.8, 99.7] | 86.9% / 97.5% |
| plus 3 topic-masked channel | 93.5% [89.7, 97.1] | 88.7% [82.9, 96.2] | 92.2% [88.3, 97.7] | 76.1% / 99.2% |
| plus 7 nearest piece | 98.3% [95.7, 100.0] | 91.4% [87.1, 97.4] | 97.4% [95.1, 99.5] | 87.2% / 99.3% |
| plus 8 Original's z-scores | 64.1% [56.3, 71.3] | 55.2% [45.9, 64.5] | 62.5% [54.7, 69.6] | 36.4% / 69.7% |

The other science rows (minus 3, 4, 5 and 8; plus 1, 4, 5 and 6) are in
`validation/scholarly/ablation_science_development_2026-11-12.json`. Each changes the full
verifier by 1.4 points or less; added alone, function words and the LLR score barely move
today's score, while part of speech alone reaches 91.2%.

## Which ingredients carried the gain

1. **The character n-gram profile, compared against other authors, is the main ingredient.**
   Added alone to today's score, it reaches the full verifier's level in both collections.
   Removing it costs the most of any single channel: 16 points on humanities same-subfield
   probes and 25 points at 300/300.
2. **The impostor comparison is what makes the profile work.** It compares the new paper's
   similarity to this author's past papers with its similarity to other authors' papers.
   Removing it halves humanities same-subfield catch (85.8% to 48.6%). Own-baseline similarity
   alone is not enough, because some writers simply score high or low on every comparison.
3. **Nearest-piece comparison adds a few points.** That is about 7 on humanities same-subfield,
   and nothing measurable in science. A short paper often matches one passage of an earlier
   paper better than the average of all of them.
4. **The topic-masked, function-word and part-of-speech channels add 1 to 4 points each** in
   humanities. They are cheap insurance on topic-matched probes, not a main source of gain.
5. **Original's own feature z-scores add almost nothing once the profile is present.** Removing
   them costs at most 2 points. Their main value is the Part 2 finding: with length-matched
   pieces they stop the false alarms under the shipped bands.
6. **Length-matched pieces help Original's z-scores but slightly hurt the n-gram channels.**
   Whole 1200-word past papers give the profiles more text, so they are better.
7. **Most of the gain needs no trained model.** An unweighted average of the
   impostor-relative z values reaches 86.8% / 72.0% / 76.7% in humanities and
   97.9% / 93.7% / 97.6% in science at 1200/300. Training adds 6 to 14 points in humanities and
   about 1 to 2 in science.

## Proposal: comparison rules Original could adopt without a trained model

| rule | what it does | needs |
|---|---|---|
| **A. Length-matched baseline pieces for Original's existing z-scores** (Part 2) | When the new paper is shorter than the past papers, cut each approved past paper into pieces of the new paper's length before building the baseline mean and spread. | No new stored data (works from the stored baseline texts or re-extraction). A change to how `original/` builds the state for short submissions; a flag, default off; a gate with a failure witness in `validation/gate_contracts.py`; a shadow soak; your approval. |
| **B. Class-relative character profile** | Store a character 3-5-gram profile per approved past paper. Score the new paper's similarity to its own student's profiles relative to the same workspace's other students, as a rank or z, using both centroid and nearest-piece comparison. Report it as a separate consistency observation, never as a probability. | **New stored profiles**: n-gram vectors per approved past paper, kept inside the deployment (NORTH_STAR rule 7) and deleted with the student (rule 8). A minimum class size, like `null_pool`'s 3-student floor; below it, say "inconclusive". A new report-only flag, default off. A gate with a failure witness. A shadow soak to learn real class sizes and the score distribution on student writing. Your approval. |
| **C. Topic-masked profile next to B** | The same as B on text with content words replaced by their shapes. It holds up when classmates share a topic, as they do on a common assignment. | The same as B. Cheap to compute alongside it. |
| **D. Fixed combination of B, C and Original's z** | An unweighted average of the relative z values, with no training. | The same as B and C. This is the rule closest to what was measured here (the fixed-combination row). |

Not proposed: the learned model itself. It adds up to 14 points in humanities, but it needs
training data from real classes, it would turn Original into a trained classifier with its own
drift and fairness questions, and its thresholds failed to transfer between models here.
Function-word and part-of-speech channels are not proposed as separate rules, because their
measured contribution is small.

## What would have to be true before any of this ships

* Academics are not students. B, C and D have been measured only on published scholarly
  prose. A shadow soak on consented student writing is the first real test, and a class's
  shared assignment topic is exactly the case the same-subfield probes approximate.
* Calibration has been seen and `locked_test` is the last clean check. A pre-registration for
  D (study id, hypotheses, the exact fixed rule, a single opening) should come before it is
  opened.
* NORTH_STAR rules 1 to 4 apply: decision support, honest claims, "inconclusive" for small
  classes or short texts, and protecting honest students first. Even a 5% honest flag rate
  means 1 honest student in 20. Any result shown to a teacher stays labelled as a
  testing-phase consistency observation.
