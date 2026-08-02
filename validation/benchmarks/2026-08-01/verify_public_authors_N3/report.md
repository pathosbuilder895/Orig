# Binary authorship verification — public_authors_N3

_Generated 2026-08-02T02:24:13.686381Z_

Baselines per author: **3**

> ⚠ **Corpus caveat**: for 9 author(s) — augustine, boethius, chesterton, douglass, edwards, james, kempis, mill, newman — the baseline and held-out scoring essays are drawn from the SAME source work (consecutive chunks of one book). Their same-author AUC measures within-work continuity, not just cross-work authorial voice. Read their numbers as a narrower claim than the corpus-wide headline implies until a disjoint second work is added per author.

## Headline: per-author AUC

Each author's AUC is computed against ITS OWN baseline's score distribution — no cross-author calibration assumption needed. This is the number to quote.

- **median AUC**: 0.98  (IQR [0.8767, 0.9946])
- **authors evaluated**: 11
- **pair counts**: 27 same-author, 270 different-author

## Secondary: pooled-uncalibrated AUC

Concatenates every author's rows into one AUC. NOT directly comparable across authors — each author's deviation_score is relative to that author's own baseline mean/std, so pooling assumes those distributions sit on the same footing, which is not verified here. Reported as a diagnostic, not the headline claim.

- **AUC**: 0.8868  (95% CI [0.7926, 0.9556])
- **Brier**: 0.6369

### Pooled TPR at fixed FPR (Neyman-Pearson operating points)

| target FPR | pooled TPR |
|---|---|
| 0.01 | 0.3704 |
| 0.05 | 0.6667 |
| 0.10 | 0.6667 |

## Per-author breakdown

| author | n_same | n_diff | AUC | 95% CI | Brier | TPR@FPR=0.01 | TPR@FPR=0.05 | TPR@FPR=0.10 |
|---|---|---|---|---|---|---|---|---|
| augustine | 3 | 24 | 1.0 | [1.0, 1.0] | 0.6374 | 1.0 | 1.0 | 1.0 |
| boethius | 2 | 25 | 0.48 | [0.0, 1.0] | 0.6624 | 0.0 | 0.5 | 0.5 |
| chesterton | 2 | 25 | 0.98 | [0.92, 1.0] | 0.6359 | 0.5 | 1.0 | 1.0 |
| douglass | 3 | 24 | 1.0 | [1.0, 1.0] | 0.5907 | 1.0 | 1.0 | 1.0 |
| edwards | 3 | 24 | 0.8333 | [0.6385, 1.0] | 0.6353 | 0.3333 | 0.3333 | 0.3333 |
| emerson | 2 | 25 | 0.6 | [0.42, 0.8] | 0.6451 | 0.0 | 0.0 | 0.0 |
| james | 4 | 23 | 0.9891 | [0.9565, 1.0] | 0.6149 | 0.75 | 1.0 | 1.0 |
| kempis | 2 | 25 | 1.0 | [1.0, 1.0] | 0.6439 | 1.0 | 1.0 | 1.0 |
| mill | 2 | 25 | 0.96 | [0.88, 1.0] | 0.6439 | 0.0 | 1.0 | 1.0 |
| newman | 2 | 25 | 0.98 | [0.92, 1.0] | 0.6556 | 0.5 | 1.0 | 1.0 |
| thoreau | 2 | 25 | 0.92 | [0.76, 1.0] | 0.6404 | 0.5 | 0.5 | 0.5 |
