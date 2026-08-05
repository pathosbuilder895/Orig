# Stylometry literature sweep: what could close the recall/FPR gap

Seven parallel research agents (six survey angles + one synthesis), real
web/PDF fetches with cross-checked citations, not summaries from memory.
Full per-agent transcripts: workflow run `wf_6f09fdc4-4a1`.

## The finding that matters more than any technique on this list

PAN (CLEF) runs an annual, competitive, peer-reviewed authorship
verification shared task — the same PAN 2020 corpus already used
throughout this repo's validation suite is literally that task's data. The
overview papers give a field-wide answer to "what's actually achievable,"
not just this codebase's own measurements:

- **PAN 2020** (closed-set, in-domain): winning system (Boenninghoff et
  al., deep Bayes factor scoring over a Siamese encoder) reached AUC 0.969.
- **PAN 2021** (open-set, unseen authors *and* unseen domains): the same
  lineage held up, AUC 0.987 — genuinely strong cross-domain generalization,
  but on a system trained end-to-end on thousands of labeled same/
  different-author pairs, an asset this codebase does not have.
- **PAN 2023** (cross-*discourse-type*: essay vs. email vs. interview vs.
  speech transcript — a genre-shift task, structurally the same problem
  `GENRE_INVARIANT_WEIGHTS_ENABLED` is blocked on): the **winning** system
  across 11 teams and 27 submitted runs reached only **AUROC 0.616**, and a
  score drops sharply whenever known/unknown text crosses the
  written/spoken register boundary. A naive character-4-gram baseline
  (0.595) beat most neural entrants.

Read together: strong numbers exist in this field, but they require either
in-domain data or a large labeled pair-training corpus. On the one PAN task
that isolates genuine cross-genre transfer with no such corpus advantage,
the field's best published result is ~0.60 AUROC — close to, not
dramatically above, the ~50-60% recall @ 1-5% FPR ceiling already measured
repeatedly in this repo. This is independent, external confirmation that
the ceiling reflects where the field's state of the art actually sits on
this specific problem shape, not a gap specific to Original's
implementation.

## Ranked shortlist (from the synthesis agent)

1. **Cllr-calibrated logistic-regression score fusion** (Ishihara 2017,
   *Forensic Sci. Int.* 278; Brümmer & du Preez 2021, arXiv:2104.08846;
   Nandakumar et al. 2008, IEEE TPAMI). Reuses every signal already
   computed (LUAR cosine, Delta, character/content margins) — the change is
   fusing via a logistic layer trained to minimize **Cllr** (a proper
   scoring rule for the exact recall/FPR tradeoff this project reports on)
   instead of accuracy. Ishihara's own system, fusing near-identical
   feature families, beat every individual method at every tested document
   length. **Effort: medium. Reuses 100% of existing infrastructure.**
2. **Weighted conformal prediction under covariate shift** (Tibshirani,
   Barber, Candès, Ramdas 2019, arXiv:1904.06019). Reweights the existing
   conformal-typicality calibration by an estimated likelihood ratio
   between the calibration cohort and the live submission's cohort —
   directly targets the repeatedly-measured "threshold doesn't transfer to
   a fresh cohort" failure. Doesn't need `resolve_genre` fixed first.
   **Effort: small-medium.**
3. **LambdaG grammar-based likelihood ratio** (Nini et al. 2026, *Humanities
   & Soc. Sci. Comms.* 13:455). A PCFG-style grammar-statistics signal,
   explicitly validated for **robustness to small reference-population
   variation** — the closest published claim to the exact 3-8-document
   constraint. Grammar-structure-based, plausibly decorrelated from every
   signal already in the stack (embeddings, lexical frequency). **Effort:
   medium-large — no PCFG/grammar model currently in the codebase.**
4. **Few-shot LUAR prototypes** (Rivera Soto et al., ICLR 2024 workshop,
   arXiv:2401.06712 — same research group as LUAR itself). Public code,
   directly compatible with the LUAR embeddings already wired up.
   **Effort: small — lowest integration cost on this list.**
5. **Square Root / Hapax closed-form LR corrections** (Barlow, Nini, Manino
   2026, *Forensic Sci. Int.*). Recalibrates a raw score into a likelihood
   ratio without fitting a case-specific logistic model — built
   specifically for too-few-pairs-to-calibrate scenarios. Hapax beat
   logistic calibration in ~45% of 15 corpora tested. **Effort: small, two
   closed-form formulas.**
6. **O2D2 abstention layer** (Boenninghoff, Nickel, Kolossa 2021, PAN@CLEF
   winner). An explicit reject-option that flags a trial "undecidable"
   under domain shift instead of forcing a score — maps directly onto the
   `pass`/`fail`/`uninformative` gate philosophy already in this codebase.
   **Effort: medium.**
7. **Poh & Bengio user-specific score normalization** (2005/2013 line).
   Per-student rescaling of each matcher's score using only that student's
   own sparse enrollment stats, cheaper than learning per-user fusion
   weights. **Effort: small.**

## Flagged as not worth pursuing here

- The **PAN 2020/2021 winning encoders** themselves — top raw numbers, but
  trained end-to-end on thousands of labeled pairs this codebase has no
  equivalent of. The *scoring mechanism* (items 2/6 above) is separable and
  reusable; the *encoder* is not.
- **StyleDistance / CISR** — same axis as the content-reduced margins
  already implemented; the novelty is a synthetic-paraphrase training
  pipeline this codebase would have to build from scratch for incremental
  gain.
- **SADIRI** — a RoBERTa fine-tuning curriculum, not a feature/signal;
  needs encoder fine-tuning infrastructure absent here.
- **OSST / one-shot LLM Bayesian attribution** — no evidence at
  recall-at-low-FPR (only raw accuracy, N=10 authors); both need
  per-verification LLM inference, a new and nontrivial operational cost.
- **SELMA / CROSSNEWS** — promising for the genre-mismatch problem
  specifically, but unvalidated at this project's scale or low-reference-
  document regime.
- **Multi-source domain-adversarial adaptation** (speaker-recognition
  lineage) — needs adversarial training infrastructure with no text-domain
  evidence it transfers.

## Single best "try this next"

**#1, Cllr-calibrated LR fusion.** Experiment design (matching the Delta
ablation's own discipline): same locked cohort, same author-disjoint
GroupKFold splits already used for the Delta and shrinkage-LDA runs. Fit a
multinomial logistic-regression fusion layer per fold minimizing Cllr
(FoCal-style recipe) instead of the current fixed/regularized-logistic
weighting. Compare against current fusion on recall @ 1%/5% FPR (this
project's standing metric) and Cllr itself as a secondary honesty check.
Positive result = recall improves at matched FPR without Cllr regressing;
report a null result plainly if it doesn't, same standard the Delta
ablation held itself to.

## Search coverage note

Two specific angles the search was asked to check — PAC-Bayes bounds
applied to stylometry, and MAML/episodic meta-learning for authorship
verification — returned no on-topic published work. Recorded as a genuine
absence in the literature as of this search, not a search failure.
