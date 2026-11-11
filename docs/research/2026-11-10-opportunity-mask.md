# Not scoring what a paper gave no chance to occur (OPPORTUNITY_MASK)

| | |
|---|---|
| **Tool** | Claude Code with web search (research subagents), plus a local before/after run |
| **Date** | 2026-11-10 |
| **Question** | When a new paper has zero opportunities for a share-type measurement, should the placeholder be compared with the student's past values, and can a fix be tested now on committed data? |
| **Decision it informs** | Whether `OPPORTUNITY_MASK` may move from `off` to `shadow`. CLAUDE.md flag table; NORTH_STAR rules 3 and 4. |

Companion brief: `docs/research/2026-11-10-genre-robust-stylometric-features.md`. The per-topic source notes behind both were working files and are not committed.

## The fault

Fourteen measurements are shares: for example "that" uses out of ("that" + "which") uses. When a paper has no eligible place at all, the extractor returns a placeholder (0.5 for most, 0.0 for some). `score()` then compares that placeholder with the student's real past values. A student who always wrote "that", and whose new paper has no such clause, is scored as having changed.

## What the literature says

Support for leaving the measurement out:

- **Variationist linguistics.** A rate is defined only over the places where the form could occur (the principle of accountability). Empty cells are missing data, not zero and not 0.5 ([Bayley, "The Quantitative Paradigm"](https://www.blackwellpublishing.com/content/bpl_images/content_store/WWW_Content/9780631218036/08Chap05.pdf), read in full).
- **Distance measures with missing values.** Dropping unobserved variables and averaging over the observed ones is the long-standing convention (Gower similarity; the partial-distance strategy of Dixon 1979 and Hathaway and Bezdek 2001; seen at abstract or secondary level).
- **Compositional data.** Structural zeros are a different thing from sampling zeros, and replacement methods are for the second kind only (abstract level).
- No source recommends a constant placeholder.

Three refinements the literature adds, none built here:

1. **A few opportunities are nearly as weak as none.** The 95% interval for 0 of n is [0, 0.79] at n = 1, [0, 0.43] at n = 5 and [0, 0.28] at n = 10 (our arithmetic from the Wilson formula). `min_count` exists as a parameter for this, defaulting to 1.
2. **Averaging over fewer features keeps the level of the score but widens its spread.** Under an idealised model the 95th percentile of the distance is 1.12 with 90 features and 1.25 with 20 (our arithmetic). With 14 registered features out of about 90 the effect here is small.
3. **Absence should not be used as evidence by default.** At 2 opportunities per 1,000 words, a 300-word paper has none 55% of the time by chance (our arithmetic). Penalising absence would mostly punish short or off-genre papers.

Not found: any authorship or forensic text paper that marks single features unobservable and renormalises, and any published comparison of exclusion against shrinkage for z-scores on tiny baselines. Guy's "30 tokens per cell" guidance could not be verified in a fetched source.

## What was built

- `original/features/opportunity.py`: the opportunity count for each of the 14 measurements, taken from the same helper its extractor divides by.
- `OPPORTUNITY_MASK` (`off` default, `shadow`, `on`) in `original/quantum/scoring.py`. Under `on`, a measurement with no opportunities in the paper being scored leaves the comparison for that paper and the distance is averaged over what remains. Under `shadow`, nothing changes and the score `on` would give is attached report-only.
- Only the paper being scored is covered. Past-paper vectors are stored without counts, so a placeholder inside a student's history still enters that student's mean and spread.

## The immediate test

`python -m validation.opportunity_mask.run` (about 50 minutes on a laptop). Thirteen pseudo-students from `validation/corpus/` (seven published authors, six synthetic seminary writers), four past papers each, 540 genuine and 2,070 other-writer trials across five length cells. Every trial is scored three ways: off, on, and a control that drops the same number of features at random. Criteria were written into the script before its first run.

| Pooled result | Off | On | Random control |
|---|---|---|---|
| Honest papers flagged (conversation or above) | 29.6% | 29.3% | 29.1% |
| Other writers caught | 63.9% | 63.5% | 63.6% |
| AUC | 0.744 | 0.745 | 0.744 |

- 68% of genuine papers had one or more unmeasured features (0.96 on average), so the mechanism fired.
- Honest decisions changed on 8 of 540 papers: 5 flags removed, 3 added.
- Change in AUC, 95% interval resampled by author: -0.0015 to +0.0033.
- Verdict by the pre-set criteria: **pass** (engaged, honest flag rate not higher, catch rate and AUC within tolerance).

## How to read that

**The fix is safe on this corpus and its benefit is too small to see.** "On" did no better than dropping random features, so the pass means "does no harm", not "reduces false flags". The fault is real in the code, but placeholders are a minor source of false flags here.

**The run exposed a much larger problem.** With 1,200-word past papers and a 300-word new paper, 78% of honest papers were flagged, against 13% when past and new papers were both 300 words. Length mismatch between past and new papers, not missing opportunities, is the dominant false-flag source in this test. No current mechanism handles it.

The exploratory sweep of higher minimum counts (2 to 10) lowered both the honest flag rate and the catch rate together, with no control arm. It is reported in the JSON and must not be used to choose a threshold.

## Limits

- Published authors and synthetic papers, not students. One corpus, no held-out lock, criteria written in the same session as the code.
- 540 genuine trials resolve a false-flag rate near 30% to roughly plus or minus 4 points; the 13 authors, not the trials, are the independent units.
- The machine that ran it lacks `sentence-transformers`, so the tension-arc feature ran on its fallback.
- Typicality bands and the fidelity p-value are withheld when the mask applies under `on`, because their reference sets were built over the full feature set.
- The study ran with default weights. Demo mode uses adaptive weights, which mute some features by setting their weight to zero; such features are never masked (masking one would raise the score, a defect an independent review caught before merge), but the before/after numbers were not re-measured under adaptive weights.
- Under `on`, the staff evidence page can still show a difference for a measurement the score left out.
- Three measurements with the same "nothing to measure" shape are not covered yet: `error_topology_consistency`, `signal_verb_entropy`, `citation_density_cv`.

## Decision this supports

`shadow` on a pilot workspace is reasonable: it changes nothing and counts how often real papers have unmeasured features. `on` is not supported by evidence of benefit. The next piece of work this points to is the length-mismatch effect.
