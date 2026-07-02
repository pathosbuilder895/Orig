"""
validation/verify/ — binary authorship verification evaluator.

Produces the exact number the pilot needs to claim: given a student A's
3 baseline essays, can Original tell whether a submission is theirs?

For each author A with ≥ N baseline essays, the evaluator scores:
  - A's own held-out essays against A's baseline → y_true = 1 (same-author)
  - Every other author's held-out essay against A's baseline → y_true = 0

Reports per-author AUC + Brier + TPR at fixed FPR ∈ {0.01, 0.05, 0.10}
with 95% bootstrap CIs, aggregated across the corpus.

The math is unchanged. The evaluator only re-frames how existing
``score()`` outputs are combined into a binary hypothesis test.
"""
