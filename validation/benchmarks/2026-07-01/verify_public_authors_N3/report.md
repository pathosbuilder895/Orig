# Binary authorship verification — public_authors_N3

_Generated 2026-07-01T21:07:01.108724Z_

Baselines per author: **3**

> ⚠ **Corpus caveat**: for 8 author(s) — augustine, boethius, chesterton, edwards, james, kempis, mill, newman — the baseline and held-out scoring essays are drawn from the SAME source work (consecutive chunks of one book). Their same-author AUC measures within-work continuity, not just cross-work authorial voice. Read their numbers as a narrower claim than the corpus-wide headline implies until a disjoint second work is added per author.

## Headline: per-author AUC

Each author's AUC is computed against ITS OWN baseline's score distribution — no cross-author calibration assumption needed. This is the number to quote.

- **median AUC**: 1.0  (IQR [0.95, 1.0])
- **authors evaluated**: 9
- **pair counts**: 22 same-author, 176 different-author

## Secondary: pooled-uncalibrated AUC

Concatenates every author's rows into one AUC. NOT directly comparable across authors — each author's deviation_score is relative to that author's own baseline mean/std, so pooling assumes those distributions sit on the same footing, which is not verified here. Reported as a diagnostic, not the headline claim.

- **AUC**: 0.8551  (95% CI [0.7758, 0.9241])
- **Brier**: 0.3443

### Pooled TPR at fixed FPR (Neyman-Pearson operating points)

| target FPR | pooled TPR |
|---|---|
| 0.01 | 0.2273 |
| 0.05 | 0.5909 |
| 0.10 | 0.5909 |

## Per-author breakdown

| author | n_same | n_diff | AUC | 95% CI | Brier | TPR@FPR=0.01 | TPR@FPR=0.05 | TPR@FPR=0.10 |
|---|---|---|---|---|---|---|---|---|
| augustine | 3 | 19 | 1.0 | [1.0, 1.0] | 0.4077 | 1.0 | 1.0 | 1.0 |
| boethius | 2 | 20 | 0.775 | [0.4, 1.0] | 0.438 | 0.5 | 0.5 | 0.5 |
| chesterton | 2 | 20 | 1.0 | [1.0, 1.0] | 0.4251 | 1.0 | 1.0 | 1.0 |
| edwards | 3 | 19 | 1.0 | [1.0, 1.0] | 0.2557 | 1.0 | 1.0 | 1.0 |
| emerson | 2 | 20 | 0.975 | [0.9, 1.0] | 0.3602 | 0.5 | 1.0 | 1.0 |
| james | 4 | 18 | 0.4722 | [0.1944, 0.7778] | 0.4739 | 0.0 | 0.0 | 0.0 |
| kempis | 2 | 20 | 1.0 | [1.0, 1.0] | 0.1392 | 1.0 | 1.0 | 1.0 |
| mill | 2 | 20 | 0.95 | [0.8, 1.0] | 0.1661 | 0.5 | 0.5 | 1.0 |
| newman | 2 | 20 | 1.0 | [1.0, 1.0] | 0.4326 | 1.0 | 1.0 | 1.0 |
