# Fixing `resolve_genre` — problem statement and scoped approach

**Status:** scoping only (2026-08 Bluebook sprint, buffer day). Deliberately
NOT started here — queued as the next sprint's first task. Companion brief:
`2026-08-13-genre-classification-approaches-brief.md`.

## The problem, precisely

`resolvers.resolve_genre` classifies a submission's genre from surface
rules. Measured failure (2026-08 cross-genre study,
`validation/genre_crossgenre_2026-08/`): **84% of an independent
10-author corpus lands in `correspondence`**, which is not a positive
classification — it is rule 8's terminal `else`. All six of Lewis's
hand-labelled genres collapse into it. Two shipped mechanisms are
casualties:

1. `GENRE_INVARIANT_WEIGHTS_ENABLED` is inert (its gate fired in 1 of 6
   leave-one-genre-out folds, and that one was classifier noise) — the
   flag is built, tested, and unenableable.
2. `manifest.baseline_match["genre_covered"]` reads ~100% covered in any
   deployment, which silently defeats the coverage telemetry.
3. Downstream, the genre-matched Bayesian prior
   (`BAYESIAN_PRIOR_ENABLED`) pools by this same genre label — a broken
   label means the "same-genre peers" pool is really an
   "everything" pool.

## Proposed approach (from the research brief)

Replace the rule chain with a **TF-IDF (word + char n-gram) linear
classifier** — calibrated logistic regression or linear SVM, one-vs-rest —
with an explicit **abstain** outcome replacing the terminal `else`:

- **Why linear + TF-IDF:** the CORE register literature puts linear
  models at ~74% F1 on 26-class register tasks (transformers: ~68–80%),
  at sklearn-only runtime cost, with per-class coefficients a professor
  can be shown ("classified as sermon because: second-person address,
  vocative openings, …"). Explainability is a product constraint, not a
  nicety.
- **Abstain, don't default:** when the max calibrated probability is
  below threshold, return `unknown` — downstream consumers already treat
  "genre not covered by baseline" conservatively, and `unknown` must
  flow through as "make no genre-based adjustment," never as a
  positive class. This alone fixes casualty #2 (coverage telemetry
  becomes honest even before accuracy improves).
- **Training data:** CORE-mapped categories + self-labeled public-domain
  theological texts (CCEL/Gutenberg — the same sources as
  `validation/public_authors/`). No labeled seminary-genre corpus
  exists; that gap is the schedule risk, not the modeling.
- **Optional second head:** sentence-transformer prototype similarity,
  A/B'd against the TF-IDF head, degrading exactly like Tier 10 when the
  dependency is absent.

## What would prove it works (decided now, before any code)

1. **Primary:** on the hand-labelled Lewis corpus (6 genres), macro-F1
   materially above the rule chain's (which is near-zero given the
   collapse), with `correspondence` no longer absorbing > 30% of
   non-correspondence texts.
2. **Distributional:** on `validation/public_authors/`, no single class
   receives > 40% of predictions (the current failure signature).
3. **Downstream re-run:** `genre_crossgenre_2026-08/genre_invariant_validate.py`
   end-to-end — the genre-invariant gate must fire in the majority of
   leave-one-genre-out folds on genuinely shifted submissions before
   `GENRE_INVARIANT_WEIGHTS_ENABLED` leaves its INERT warning.
4. **No regression:** with the resolver swapped but the flag off,
   scoring output stays byte-identical (the resolver only feeds the
   manifest until the flag is on).

## Explicit non-goals for the first iteration

- Perfect seminary-genre taxonomy — start with the six hand-labelled
  Lewis genres plus `unknown`.
- Enabling `GENRE_INVARIANT_WEIGHTS_ENABLED` — that remains its own
  gated decision after criterion 3 passes.
- Touching `resolve_topic` (separate resolver, separate failure modes,
  own spec: `2026-08-06-topic-invariant-scoring-design.md`).
