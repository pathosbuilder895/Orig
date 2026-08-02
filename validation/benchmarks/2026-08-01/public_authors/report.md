# Public-author validation — Test 2 report

_Generated 2026-08-01T18:06:38Z_

## Summary

- **Top-1 attribution accuracy**: 70.37%
- **Mean rank of true author**: 1.63
- **Eligible authors**: 11 — augustine, boethius, chesterton, douglass, edwards, emerson, james, kempis, mill, newman, thoreau
- **Held-out essays scored**: 27

## Per-author accuracy

| author | n | correct | accuracy |
|---|---|---|---|
| augustine | 3 | 3 | 100.00% |
| boethius | 2 | 1 | 50.00% |
| chesterton | 2 | 1 | 50.00% |
| douglass | 3 | 3 | 100.00% |
| edwards | 3 | 1 | 33.33% |
| emerson | 2 | 1 | 50.00% |
| james | 4 | 2 | 50.00% |
| kempis | 2 | 2 | 100.00% |
| mill | 2 | 2 | 100.00% |
| newman | 2 | 2 | 100.00% |
| thoreau | 2 | 1 | 50.00% |

## Confusion matrix

| true \ predicted | augustine | boethius | chesterton | douglass | edwards | emerson | james | kempis | mill | newman | thoreau |
|---|---|---|---|---|---|---|---|---|---|---|---|
| augustine | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| boethius | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| chesterton | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| douglass | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| edwards | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 2 | 0 | 0 |
| emerson | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| james | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 2 | 0 | 0 |
| kempis | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| mill | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 |
| newman | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 |
| thoreau | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
