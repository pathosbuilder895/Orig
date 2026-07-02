# Binary authorship verification — seminary_students_nullmodel_N3

_Generated 2026-07-01T21:49:46.185034Z_

Baselines per author: **3**

## Headline: per-author AUC

Each author's AUC is computed against ITS OWN baseline's score distribution — no cross-author calibration assumption needed. This is the number to quote.

- **median AUC**: 1.0  (IQR [1.0, 1.0])
- **authors evaluated**: 5
- **pair counts**: 10 same-author, 40 different-author

## Secondary: pooled-uncalibrated AUC

Concatenates every author's rows into one AUC. NOT directly comparable across authors — each author's deviation_score is relative to that author's own baseline mean/std, so pooling assumes those distributions sit on the same footing, which is not verified here. Reported as a diagnostic, not the headline claim.

- **AUC**: 0.9325  (95% CI [0.8275, 1.0])
- **Brier**: 0.1668

### Pooled TPR at fixed FPR (Neyman-Pearson operating points)

| target FPR | pooled TPR |
|---|---|
| 0.01 | 0.2 |
| 0.05 | 0.8 |
| 0.10 | 0.9 |

## Per-author breakdown

| author | n_same | n_diff | AUC | 95% CI | Brier | TPR@FPR=0.01 | TPR@FPR=0.05 | TPR@FPR=0.10 |
|---|---|---|---|---|---|---|---|---|
| seminary_01 | 2 | 8 | 1.0 | [1.0, 1.0] | 0.1684 | 1.0 | 1.0 | 1.0 |
| seminary_02 | 2 | 8 | 1.0 | [1.0, 1.0] | 0.1283 | 1.0 | 1.0 | 1.0 |
| seminary_03 | 2 | 8 | 0.6875 | [0.25, 1.0] | 0.1949 | 0.0 | 0.0 | 0.0 |
| seminary_04 | 2 | 8 | 1.0 | [1.0, 1.0] | 0.1734 | 1.0 | 1.0 | 1.0 |
| seminary_05 | 2 | 8 | 1.0 | [1.0, 1.0] | 0.1688 | 1.0 | 1.0 | 1.0 |
