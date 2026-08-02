# Binary authorship verification — public_authors_nullmodel_N3

_Generated 2026-08-02T05:12:16.717593Z_

Baselines per author: **3**

## Headline: per-author AUC

Each author's AUC is computed against ITS OWN baseline's score distribution — no cross-author calibration assumption needed. This is the number to quote.

- **median AUC**: 1.0  (IQR [0.96, 1.0])
- **authors evaluated**: 11
- **pair counts**: 27 same-author, 270 different-author

## Secondary: pooled-uncalibrated AUC

Concatenates every author's rows into one AUC. NOT directly comparable across authors — each author's deviation_score is relative to that author's own baseline mean/std, so pooling assumes those distributions sit on the same footing, which is not verified here. Reported as a diagnostic, not the headline claim.

- **AUC**: 0.9527  (95% CI [0.9195, 0.9782])
- **Brier**: 0.1271

### Pooled TPR at fixed FPR (Neyman-Pearson operating points)

| target FPR | pooled TPR |
|---|---|
| 0.01 | 0.4815 |
| 0.05 | 0.6667 |
| 0.10 | 0.8519 |

## Per-author breakdown

| author | n_same | n_diff | AUC | 95% CI | Brier | TPR@FPR=0.01 | TPR@FPR=0.05 | TPR@FPR=0.10 |
|---|---|---|---|---|---|---|---|---|
| augustine | 3 | 24 | 1.0 | [1.0, 1.0] | 0.1187 | 1.0 | 1.0 | 1.0 |
| boethius | 2 | 25 | 0.96 | [0.84, 1.0] | 0.1365 | 0.5 | 0.5 | 1.0 |
| chesterton | 2 | 25 | 0.84 | [0.68, 0.96] | 0.1303 | 0.0 | 0.0 | 0.0 |
| douglass | 3 | 24 | 1.0 | [1.0, 1.0] | 0.1462 | 1.0 | 1.0 | 1.0 |
| edwards | 3 | 24 | 0.9722 | [0.875, 1.0] | 0.1287 | 0.6667 | 0.6667 | 1.0 |
| emerson | 2 | 25 | 1.0 | [1.0, 1.0] | 0.1118 | 1.0 | 1.0 | 1.0 |
| james | 4 | 23 | 1.0 | [1.0, 1.0] | 0.0672 | 1.0 | 1.0 | 1.0 |
| kempis | 2 | 25 | 1.0 | [1.0, 1.0] | 0.0822 | 1.0 | 1.0 | 1.0 |
| mill | 2 | 25 | 0.96 | [0.84, 1.0] | 0.2135 | 0.5 | 0.5 | 1.0 |
| newman | 2 | 25 | 1.0 | [1.0, 1.0] | 0.0968 | 1.0 | 1.0 | 1.0 |
| thoreau | 2 | 25 | 0.74 | [0.36, 1.0] | 0.1657 | 0.5 | 0.5 | 0.5 |
