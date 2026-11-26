# Comparing a short paper with short pieces (LENGTH_MATCHED_BASELINE)

| | |
|---|---|
| **Tool** | Claude Code, local before/after run on committed data |
| **Date** | 2026-11-14 |
| **Question** | When a new paper is much shorter than the student's past papers, does re-measuring the past papers in pieces of the new paper's length stop honest papers being flagged, and can other writers still be told apart? |
| **Decision it informs** | Whether `LENGTH_MATCHED_BASELINE` may move from `off` to `shadow`. CLAUDE.md flag table; NORTH_STAR rules 3 and 4. |

Follows `docs/research/2026-11-10-opportunity-mask.md`, which found the fault.

## The fault

Past papers are measured whole. A 1,200-word paper gives steadier numbers than a 300-word one, and some measurements move with length by construction. So four long past papers agree closely with each other, and a short new paper by the same writer falls outside that narrow band. On `validation/corpus/`, 78% of honest 300-word papers were flagged against 1,200-word past papers, and 13% against 300-word ones.

## What was built

- `original/quantum/length_match.py`. Each past paper at least twice the length of the new paper is cut into consecutive pieces no shorter than the new paper, and each piece is measured. The mean, the spread and the set of compared features then come from the pieces.
- Everything else stays the student's real history: the number of papers (which readiness and confidence are judged on), the trajectory, the density matrix. Each paper keeps the weight it had, shared among its pieces. The floor under the spread keeps the paper count, so sixteen pieces of four papers do not earn the tighter floor sixteen papers would.
- `LENGTH_MATCHED_BASELINE` (`off` default, `shadow`, `on`) in `original/quantum/scoring.py`. `shadow` changes nothing and attaches the score `on` would give; that preview is `score()` itself run under `on`, so the two cannot differ.
- Pieces are slices of the paper's body: line and paragraph breaks are kept, and the bibliography and other back matter are removed first, as when a paper is measured whole.
- It abstains (exactly `off`) when the new paper is under 100 words, when no past paper is twice its length, when any past paper's text is missing, or when more than 24 past papers would be cut.

## The test

`python -m validation.length_match.run --out validation/length_match/report_2026-11-14.json` (about three minutes). Same 13 pseudo-students and split as the earlier study. Every trial is scored three ways: `off`, `on`, and `wide`, a simpler study-only alternative that leaves past papers whole and widens every feature's spread by the square root of the length ratio. Criteria were written into the script before its first run.

| Past / new words | Honest flagged: off | on | wide | Others caught: off | on | wide | AUC: off | on | wide |
|---|---|---|---|---|---|---|---|---|---|
| 1,200 / 300 | 77.7% | 1.7% | 0.8% | 95.3% | 10.9% | 3.2% | 0.765 | 0.787 | 0.746 |
| 1,200 / 600 | 24.2% | 5.3% | 1.1% | 64.6% | 20.2% | 11.6% | 0.771 | 0.773 | 0.757 |
| 600 / 300 | 42.3% | 3.9% | 3.1% | 82.0% | 18.8% | 14.7% | 0.764 | 0.775 | 0.747 |
| **Pooled** (346 genuine, 1,332 other-writer) | 49.7% | 3.5% | 1.7% | 81.5% | 16.4% | 9.8% | 0.740 | 0.771 | 0.725 |
| 300 / 300 (nothing to cut) | 13.1% | 13.1% | 13.1% | 50.8% | 50.8% | 50.8% | 0.777 | 0.777 | 0.777 |

- Honest flag rate fell by 46.2 points (95% interval, resampled by author: 40.5 to 51.7).
- AUC rose by 0.031 (95% interval by author: +0.011 to +0.049).
- With `off`'s bar moved until it flags honest papers as rarely as `on` does (3.5%), `off` catches 11.6% of other writers; `on` catches 16.4%.
- In the 300 / 300 cell `on` was identical to `off` on every trial, as designed (asserted in the script).
- Verdict by the pre-set criteria: **pass**.

## How to read that

**The false flags go away, and the comparison itself gets slightly better.** Unlike the opportunity mask, this is evidence of benefit: AUC improves in every engaged cell and the interval excludes zero. The simpler alternative (`wide`) removes the false flags too but makes separation worse, so the gain needs the pieces, not just a wider band.

**It overshoots the bar.** At the product's fixed action thresholds, `on` flags 3.5% of honest papers and catches 16% of other writers, where the like-for-like 300 / 300 cell flags 13% and catches 51%. The thresholds were set on references built from a few whole papers, whose spread is underestimated; a reference built from sixteen pieces is wider and better estimated, so every score is lower. `off` caught 82% only by flagging half of everyone.

Read at a fixed honest flag rate instead (added after the first run, so exploratory): at 13% honest flagged, `on` catches 46%, `off` 38%, `wide` 33%; at 5%, 23%, 21%, 18%.

So `on` trades a severe false-flag problem for a weak detector on short papers. That is the right direction under "protect honest students first", but the thresholds need setting for this reference before `on` is useful, and that must not be done on this corpus.

## Limits

- Published authors and synthetic papers, not students. Past "papers" are consecutive slices of one continuous text, so they share a topic more than a student's separate papers would. One corpus, no held-out lock, criteria written in the same session as the code. 13 authors are the independent units.
- The choice to keep the paper-count floor was made before the run on principle and was not compared with the alternative.
- Cost: one feature extraction per piece on every scoring request, capped at 24. `shadow` pays it too.
- Only the mean, spread and active set are matched. The density matrix, trajectory and topic distance use whole papers, and `quantum_fidelity` under `on` mixes the two, so it is not comparable with its off value.
- Every peer-side quantity stays whole-paper. `llr_deviation_score` therefore moves toward "claimed author" for every short paper, other writers included; where the peer pool is on (demo mode), its default gate can add a one-step downgrade on top of the catch rate above. This is reasoned from the code and not measured: the run had no peer pool. The same mix applies to the cold-start prior and to characteristic weights, both off by default.
- The corpus texts have no paragraph breaks or bibliographies, so the run does not exercise how pieces keep the first and drop the second. An independent review found both were mishandled in the first draft; they are fixed and unit-tested, not measured.
- Typicality bands and the fidelity p-value are withheld under `on`, and that paper's fidelity is not stored, because their reference sets came from whole papers.
- Past papers between one and two times the new paper's length stay whole. A new paper longer than the past papers is not handled at all.
- Only `POST /students/{id}/score` builds the matched reference. `/score/blend` window rescores and the admin playground behave as `off`.
- The staff evidence page shows past papers' whole-paper values, so under `on` it can show a difference the score did not use.
- The run used default weights and no peer pool; it was not repeated under demo mode's adaptive weights.
- The machine that ran it lacks `sentence-transformers`, so the tension-arc feature ran on its fallback.

## Decision this supports

`shadow` on a pilot workspace is reasonable: it changes nothing and records how often real papers are much shorter than a student's past papers and what the score would have been. `on` is not supported yet: it needs action thresholds set for the matched reference, on a corpus other than this one, and a test on real separate papers per author.

## Addendum, 2026-11-19: cut points for the matched reference

The cut points this note asked for are set and tested
(`validation/length_match_thresholds/`, README there). They were chosen on the
`calibration` partition of `validation/scholarly/` humanities (separate journal
articles per author, mostly theology) and passed once on the author-disjoint
`locked_test` partition: 60 authors, 360 honest and 900 other-writer trials.

| Honest short paper vs long past papers | Off | On, new cut points |
|---|---|---|
| Honest at "worth a conversation" or higher | 48.3% | 0.6% |
| Honest at "monitor" or higher | 99.4% | 11.4% |
| Other writers caught | 83.7% | 13.9% (off at the same honest rate: 5.9%) |

The cut points are monitor 0.517, worth a conversation 0.622 and very
differently 0.703. Under `on` they apply whenever the match is applied
(`LENGTH_MATCHED_ACTION_THRESHOLDS`).

The same branch fixes a fault the review of #334 found: the new paper's length
was counted with its bibliography while past papers were cut on their body.

Still published writing, not students; `shadow` on the pilot is next.
