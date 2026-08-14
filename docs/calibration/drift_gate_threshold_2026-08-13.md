# Phase-8 Drift-Gate Threshold Calibration — 2026-08-13

**Decision: `check_drift` default threshold raised 0.25 → 0.30.** Anchor tiers
({4, 6}) and `consecutive_required` (2) unchanged. Study code and full sweep
data: `validation/drift_calibration_2026-08/`.

## Why this was measured

The 2026-08-13 calibration-gate diagnosis (worktree `peaceful-mccarthy-4f4a3a`)
found the drift gate holding genuine same-author baseline uploads on real
prose: 7 distinct seminary-corpus files across authors 06/07/09/10, magnitudes
0.2512–0.3903 — barely over the 0.25 threshold — with seminary_09 (real
Drummond-era sermons) tripping holds in every LOO fold order. In production
this 202s (`pending_review`) or 409s (`rebaseline_required`) a genuine
student's verified upload purely from within-author heterogeneity.

## Method

Simulation replicating `StudentState.check_drift` bit-for-bit (verified
against the real class before every run — recency-weighted `baseline_mean`,
per-tier `round(…, 4)`, held samples excluded from the baseline, sticky
consecutive counter; both production call sites, `students_baseline.py` and
`imports.py`, share these semantics).

- **Genuine side** — sequential single-author upload simulation (sorted order
  + 5 seeded shuffles, capped at 24 uploads): 11 seminary authors, 7
  historical authors (Burke, Douglass, Lincoln, Paine, Federalist
  Hamilton/Madison/Jay), 11 `validation/public_authors` authors. 1,860
  gated upload checks per config.
- **Impostor side** — register-matched other-author docs probed against each
  author's gated baseline (~1,850 same-family trials per config), plus
  AI-generated (n=110) and ghostwritten (n=55) seminary-register texts, plus
  cross-register probes (n=4,058).
- Swept threshold 0.16–0.45 (×0.01), anchor sets {4}, {6}, {4,6}, {4,6,8,13},
  `consecutive_required` 1/2/3, and cold-start baseline sizes k=3/5/full.

## What the measurement shows

**The anchor-tier magnitude is a weak discriminator, and 0.25 sits in the
overlap zone.** Impostor-vs-genuine AUC for the production {4,6} statistic:
0.73 pooled, **0.65 on seminary-register prose** (tier 6 alone: 0.55 ≈
chance on seminary — it contributes noise there, not signal).

Operating points, production anchor set {4,6}:

| threshold | genuine false-hold (pooled) | seminary | same-register catch | AI catch | wrong-register catch |
|---|---|---|---|---|---|
| 0.25 (old) | 3.4 % | 6.4 % | 6.7 % | 0.9 % | 13.8 % |
| 0.28 | 1.6 % | 3.3 % | 2.6 % | 0.0 % | 6.0 % |
| **0.30 (new)** | **0.5 %** | **0.9 %** | 1.7 % | 0.0 % | 3.2 % |
| 0.35 | 0.1 % | 0.3 % | 0.1 % | 0.0 % | 0.4 % |

At 0.25 the gate held genuine uploads at **half its catch rate of
same-register impostors** and at ~7× its catch rate of AI-generated text —
a genuine student's next sermon was more likely to be held than an AI essay.
No threshold fixes that: it is a property of the statistic (mean |Δ| over 13
anchor features vs. a recency-weighted mean), not of the cut point.

Other findings:

- **Cold start dominates the false holds**: hold rate is 9.8 % when the
  baseline has 1–2 samples vs. ~1.7 % at 3+ (at 0.25). At 0.30: 2.0 % vs.
  ~0.2 %.
- **Worst-case author**: seminary_09 lost 27.8 % of uploads at 0.25 → 3.3 %
  at 0.30. Authors with ≥1 hold anywhere in their sequences: 12/29 → 5/29.
- **409s to genuine students**: at 0.25 with `consecutive_required=2`, 18 of
  63 genuine hold events escalated to `rebaseline_required`. At 0.30: 3 of
  10. (`consecutive_required=3` would cut those to 1 — kept at 2 for now to
  change one knob at a time.)
- **Anchor-set variants**: {4} alone beats {4,6} on AUC everywhere (0.76 vs
  0.73 pooled) because tier 6 is chance-level on seminary prose, but at the
  operational tail (FPR ≤ 1 %) all sets catch ≈ nothing, so the churn of
  changing the anchor set buys nothing measurable. Not changed.

## The honest framing after calibration

At any tolerable false-hold rate this gate does not detect impostors or AI
contamination — the Born-rule scoring path (and `NULL_MODEL=impostor` /
`llr_deviation_score`) owns that job. What the gate can do is stop
*extreme* off-profile ingestion (wrong-file uploads, garbage text, register
collapse — the 0.30+ magnitude regime) from silently entering the
recency-weighted baseline. 0.30 keeps that hygiene function while cutting
genuine-student holds ~6× (~1 in 110 seminary uploads vs. ~1 in 16).

## Follow-ups (not done here)

- **Min-baseline-size guard** (skip the gate below 3 accepted samples) would
  take pooled FPR at 0.30 to ~0.2 % at zero measured catch cost; it is a
  behavior change beyond parameter calibration, so it needs its own decision.
- **A better statistic** (per-feature z against `baseline_std`, as the
  scoring path uses, instead of raw mean |Δ|) is the only route to real
  poisoning protection at this gate; AUC ceiling of the current statistic is
  ~0.65–0.73.
- These corpora are historical/public prose; **re-check against real pilot
  uploads** when Postgres pilot data becomes available (same accepted-risk
  posture as `LLR_ACTION_MODE=gate`).

## Reproduction

```
~/Desktop/Original/.venv/bin/python validation/drift_calibration_2026-08/extract_vectors.py /tmp/drift_vectors.npz
~/Desktop/Original/.venv/bin/python validation/drift_calibration_2026-08/calibrate.py /tmp/drift_vectors.npz /tmp/drift_calibration.json
```

Committed sweep output: `validation/drift_calibration_2026-08/results_2026-08-13.json`.
