# Public-author validation — Test 2 report

_Generated 2026-08-02T14:56:30Z_

## Summary

- **Top-1 attribution accuracy**: 74.07%
- **Mean rank of true author**: 1.63
- **Attribution method**: impostor_calibrated_z
- **Raw-argmin comparison (pre-fix rule)**: top-1 70.37%, mean rank 1.63
- **Method note**: Attribution = argmin over candidates of the impostor-calibrated z-score (deviation - ref_mean[cand]) / ref_std[cand]; each candidate's reference distribution is the deviations of every OTHER eligible author's baseline documents scored against that candidate. Reference sets are baseline-docs-only — held-out essays never inform the calibration. Raw deviation_score is z-normalized against each candidate's own baseline_std, so raw values are not cross-author comparable.
- **Eligible authors**: 11 — augustine, boethius, chesterton, douglass, edwards, emerson, james, kempis, mill, newman, thoreau
- **Held-out essays scored**: 27

## Per-author accuracy

| author | n | correct | accuracy |
|---|---|---|---|
| augustine | 3 | 2 | 66.67% |
| boethius | 2 | 1 | 50.00% |
| chesterton | 2 | 2 | 100.00% |
| douglass | 3 | 2 | 66.67% |
| edwards | 3 | 3 | 100.00% |
| emerson | 2 | 1 | 50.00% |
| james | 4 | 4 | 100.00% |
| kempis | 2 | 2 | 100.00% |
| mill | 2 | 0 | 0.00% |
| newman | 2 | 2 | 100.00% |
| thoreau | 2 | 1 | 50.00% |

## Confusion matrix

| true \ predicted | augustine | boethius | chesterton | douglass | edwards | emerson | james | kempis | mill | newman | thoreau |
|---|---|---|---|---|---|---|---|---|---|---|---|
| augustine | 2 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| boethius | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| chesterton | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| douglass | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| edwards | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 |
| emerson | 0 | 0 | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
| james | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 |
| kempis | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| mill | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 |
| newman | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 |
| thoreau | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |

## Three-engine side-by-side (Task 11)

n_scored_essays (held out, all authors) = 27; n comparable across all three engines below = 27 (narrower only if engine_exceptions excluded any essay). Read the CIs before comparing rows — at this n they are wide.

| engine | accuracy | 95% Wilson CI | n |
|---|---|---|---|
| deviation_calibrated | 74.07% | [0.55, 0.87] | 27 |
| cosine_delta | 81.48% | [0.63, 0.92] | 27 |
| mfw_delta | 100.00% | [0.88, 1.00] | 27 |

- **Ensemble (2-of-3 agreement) coverage**: 100.00%
- **Ensemble accuracy on covered essays**: 81.48%
- **Pairwise agreement**:
  - cosine_delta|deviation_calibrated: 92.59%
  - cosine_delta|mfw_delta: 81.48%
  - deviation_calibrated|mfw_delta: 74.07%
