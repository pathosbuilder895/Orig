# Public-author validation — Test 2 report

_Generated 2026-08-01T02:00:40Z_

## Summary

- **Top-1 attribution accuracy**: 72.73%
- **Mean rank of true author**: 1.591
- **Attribution method**: impostor_calibrated_z
- **Raw-argmin comparison (pre-fix rule)**: top-1 36.36%, mean rank 2.727
- **Method note**: Attribution = argmin over candidates of the impostor-calibrated z-score (deviation - ref_mean[cand]) / ref_std[cand]; each candidate's reference distribution is the deviations of every OTHER eligible author's baseline documents scored against that candidate. Reference sets are baseline-docs-only — held-out essays never inform the calibration. Raw deviation_score is z-normalized against each candidate's own baseline_std, so raw values are not cross-author comparable.
- **Eligible authors**: 9 — augustine, boethius, chesterton, edwards, emerson, james, kempis, mill, newman
- **Held-out essays scored**: 22
- **Skipped authors**: 2 — see report.json for reasons

## Per-author accuracy

| author | n | correct | accuracy |
|---|---|---|---|
| augustine | 3 | 3 | 100.00% |
| boethius | 2 | 1 | 50.00% |
| chesterton | 2 | 2 | 100.00% |
| edwards | 3 | 3 | 100.00% |
| emerson | 2 | 2 | 100.00% |
| james | 4 | 1 | 25.00% |
| kempis | 2 | 2 | 100.00% |
| mill | 2 | 0 | 0.00% |
| newman | 2 | 2 | 100.00% |

## Confusion matrix

| true \ predicted | augustine | boethius | chesterton | edwards | emerson | james | kempis | mill | newman |
|---|---|---|---|---|---|---|---|---|---|
| augustine | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| boethius | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| chesterton | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| edwards | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 |
| emerson | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 |
| james | 0 | 0 | 0 | 2 | 0 | 1 | 0 | 0 | 1 |
| kempis | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 |
| mill | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 |
| newman | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 |

## Three-engine side-by-side (Task 11)

n_scored_essays (held out, all authors) = 22; n comparable across all three engines below = 22 (narrower only if engine_exceptions excluded any essay). Read the CIs before comparing rows — at this n they are wide.

| engine | accuracy | 95% Wilson CI | n |
|---|---|---|---|
| deviation_calibrated | 72.73% | [0.52, 0.87] | 22 |
| cosine_delta | 77.27% | [0.57, 0.90] | 22 |
| mfw_delta | 90.91% | [0.72, 0.97] | 22 |

- **Ensemble (2-of-3 agreement) coverage**: 95.45%
- **Ensemble accuracy on covered essays**: 80.95%
- **Pairwise agreement**:
  - cosine_delta|deviation_calibrated: 86.36%
  - cosine_delta|mfw_delta: 72.73%
  - deviation_calibrated|mfw_delta: 72.73%
