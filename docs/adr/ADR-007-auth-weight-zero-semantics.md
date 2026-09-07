# ADR-007: Authentication-weight zero semantics

Status: Proposed — human decision required

## Context

`AUTH_WEIGHTS` gives every accepted provenance a positive weight. Consequently,
the `AUTH_WEIGHTS[provenance] > 0` false arms in baseline and import routes are
unreachable, despite comments implying that an unverified provenance may skip
authenticated-count and drift processing. Branch-coverage work confirmed this
is structural, not a missing test.

## Options

1. Set `unverified` to `0.0`. This makes the comments and guards meaningful but
   changes which samples contribute to state and drift.
2. Keep all weights positive and correct the comments/remove the defensive
   arms. This preserves behavior and acknowledges that provenance is graded,
   not excluded.
3. Retain the arms for a future zero-weight provenance and explicitly mark them
   as reserved defensive code.

## Recommendation

Choose option 2 unless product policy explicitly requires unauthenticated text
to be stored without influencing the profile. A zero weight is a product and
evidence-policy change, so no code change should precede that decision.
