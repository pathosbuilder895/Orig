# ADR-008: Model longitudinal drift as report-only evidence

**Status:** Accepted (report-only implementation; action integration deferred)

## Context

The production deviation score compares a submission with a recency-weighted
student baseline. A genuine writer can evolve over time, so distance from a
lifetime profile is not equivalent to evidence of another author. Ross (2020)
demonstrates both gradual drift and abrupt changes in long, homogeneous author
corpora using Dirichlet-multinomial change-point regression.

Original student histories are usually much shorter and more heterogeneous
than the paper's 35-62 novel examples. A full change-point model cannot safely
be treated as a production authorship decision with three to five essays.

## Decision

Add a separate longitudinal analysis that:

1. uses only authenticated, dated, sufficiently long baseline samples;
2. compares constant style with a ridge-shrunk linear trend by forward
   prediction;
3. never fits the disputed submission into its own trajectory;
4. reports historical deviation, predicted-current deviation, and drift
   relief;
5. reports at most one diagnostic change point with a longer history;
6. never changes the density matrix, primary deviation, or recommendation;
7. remains behind `LONGITUDINAL_DRIFT_ENABLED=0` by default.

The Ross-style Dirichlet-multinomial count model is implemented only in the
validation package. It may inform later versions after function-word count
metadata, sample-size behavior, and cross-context performance are validated.

## Interpretation contract

- `drift_compatible` means an authenticated trajectory explains material
  historical distance.
- `unexplained_change` means the trajectory does not explain the probe.
- `unexplained_discontinuity` means a break may exist, not that an impostor has
  been identified.
- `insufficient_history` is the required result below the evidence floor.

Positive impostor evidence requires a separate matched-peer/null comparison.

## Promotion gate

Any future influence on actions requires an independent institutional holdout
showing that drift adjustment reduces genuine false positives without an
unacceptable reduction in matched-impostor rejection. Initial action influence,
if approved, may only lower severity; drift analysis must never independently
raise it.

## Consequences

- Existing production behavior remains stable with the flag off.
- API consumers receive a nullable additive field.
- Baseline serialization gains nullable `word_count`; legacy rows remain valid.
- Chronological validation requires real ISO dates and authentic provenance.
- A change point remains a request for corroboration rather than a causal or
  disciplinary conclusion.
