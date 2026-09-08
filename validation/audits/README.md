# Validation audits

Audit scripts answer evidence-quality questions around the main gate battery.
Their dated JSON outputs are immutable measured results rather than defaults.

- `g2_floor_asymmetry_2026-08-26.json`: **genuine**. Holdouts were at their
  conformal floor in 8/19 cases (42.1%); impostors were at their floor in
  20/23 cases (87.0%). Expressing observations as within-reference ranks
  therefore preserves rather than erases the separation; unequal `N` alone
  does not explain G2's margin.
- `pooling_exchangeability_2026-09-07.json`: first real-corpus run of the
  Task 7 assessor (`pooling_exchangeability.assess_exchangeability`; until
  this run it had only ever been exercised on synthetic data, so the
  "validated within seminary and Plato separately" wording that circulated
  in CLAUDE.md / MODEL_CARD / calibration_gate.py had no measurement behind
  it). Quantity: each entity's `loo_distances` after uploading all of its
  texts. Verdicts — **plato_g1_eligible exchangeable** (19 dialogues with
  ≥ 5 chunks; between/within variance ratio 0.025, KS max 0.393);
  **g6_native_english exchangeable** (ratio 0.049, KS 0.382);
  **seminary heterogeneous** (ratio 0.228 clears the 1.0 limit but KS max
  0.726 does not — one group sits far from the pooled rest);
  public_authors heterogeneous (ratio 0.944, KS 0.871) and G1-ineligible
  regardless (3–4 texts each); every union heterogeneous (seminary+plato
  KS 0.79, all three KS 0.95). Consequence: the battery's pooled G1 leg
  (`G1p`) pools within Plato only; cross-corpus pooling and seminary
  pooling are not licensed. Produced by
  `python -m validation.audits.pooling_exchangeability_corpora` (~30 min).
