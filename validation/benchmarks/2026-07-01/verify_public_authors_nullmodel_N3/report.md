# Binary authorship verification — public_authors_nullmodel_N3

_Generated 2026-07-01T22:43:12.630977Z_

Baselines per author: **3**

## Headline: per-author AUC

Each author's AUC is computed against ITS OWN baseline's score distribution — no cross-author calibration assumption needed. This is the number to quote.

- **median AUC**: 1.0  (IQR [0.9, 1.0])
- **authors evaluated**: 9
- **pair counts**: 22 same-author, 176 different-author

## Secondary: pooled-uncalibrated AUC

Concatenates every author's rows into one AUC. NOT directly comparable across authors — each author's deviation_score is relative to that author's own baseline mean/std, so pooling assumes those distributions sit on the same footing, which is not verified here. Reported as a diagnostic, not the headline claim.

- **AUC**: 0.8993  (95% CI [0.8086, 0.9703])
- **Brier**: 0.0861

### Pooled TPR at fixed FPR (Neyman-Pearson operating points)

| target FPR | pooled TPR |
|---|---|
| 0.01 | 0.1818 |
| 0.05 | 0.7727 |
| 0.10 | 0.8182 |

## Per-author breakdown

| author | n_same | n_diff | AUC | 95% CI | Brier | TPR@FPR=0.01 | TPR@FPR=0.05 | TPR@FPR=0.10 |
|---|---|---|---|---|---|---|---|---|
| augustine | 3 | 19 | 1.0 | [1.0, 1.0] | 0.0653 | 1.0 | 1.0 | 1.0 |
| boethius | 2 | 20 | 0.9 | [0.65, 1.0] | 0.1067 | 0.5 | 0.5 | 0.5 |
| chesterton | 2 | 20 | 1.0 | [1.0, 1.0] | 0.0724 | 1.0 | 1.0 | 1.0 |
| edwards | 3 | 19 | 1.0 | [1.0, 1.0] | 0.0367 | 1.0 | 1.0 | 1.0 |
| emerson | 2 | 20 | 0.95 | [0.8, 1.0] | 0.1473 | 0.5 | 0.5 | 1.0 |
| james | 4 | 18 | 0.5833 | [0.2778, 0.8611] | 0.1389 | 0.25 | 0.25 | 0.25 |
| kempis | 2 | 20 | 1.0 | [1.0, 1.0] | 0.0625 | 1.0 | 1.0 | 1.0 |
| mill | 2 | 20 | 0.9 | [0.75, 1.0] | 0.0856 | 0.0 | 0.0 | 1.0 |
| newman | 2 | 20 | 1.0 | [1.0, 1.0] | 0.0595 | 1.0 | 1.0 | 1.0 |
