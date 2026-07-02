# Binary authorship verification — seminary_students_N3

_Generated 2026-07-01T20:25:56.350912Z_

Baselines per author: **3**

## Headline: per-author AUC

Each author's AUC is computed against ITS OWN baseline's score distribution — no cross-author calibration assumption needed. This is the number to quote.

- **median AUC**: 0.8125  (IQR [0.8125, 0.875])
- **authors evaluated**: 5
- **pair counts**: 10 same-author, 40 different-author

## Secondary: pooled-uncalibrated AUC

Concatenates every author's rows into one AUC. NOT directly comparable across authors — each author's deviation_score is relative to that author's own baseline mean/std, so pooling assumes those distributions sit on the same footing, which is not verified here. Reported as a diagnostic, not the headline claim.

- **AUC**: 0.8925  (95% CI [0.7825, 0.97])
- **Brier**: 0.5078

### Pooled TPR at fixed FPR (Neyman-Pearson operating points)

| target FPR | pooled TPR |
|---|---|
| 0.01 | 0.2 |
| 0.05 | 0.6 |
| 0.10 | 0.6 |

## Per-author breakdown

| author | n_same | n_diff | AUC | 95% CI | Brier | TPR@FPR=0.01 | TPR@FPR=0.05 | TPR@FPR=0.10 |
|---|---|---|---|---|---|---|---|---|
| seminary_01 | 2 | 8 | 1.0 | [1.0, 1.0] | 0.4811 | 1.0 | 1.0 | 1.0 |
| seminary_02 | 2 | 8 | 0.8125 | [0.375, 1.0] | 0.5349 | 0.5 | 0.5 | 0.5 |
| seminary_03 | 2 | 8 | 0.8125 | [0.5, 1.0] | 0.5119 | 0.0 | 0.0 | 0.0 |
| seminary_04 | 2 | 8 | 0.875 | [0.6219, 1.0] | 0.5094 | 0.5 | 0.5 | 0.5 |
| seminary_05 | 2 | 8 | 0.75 | [0.375, 1.0] | 0.5021 | 0.0 | 0.0 | 0.0 |
