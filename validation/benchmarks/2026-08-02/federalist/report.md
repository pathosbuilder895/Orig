# Public-author validation — Test 2 report

_Generated 2026-08-02T22:11:01Z_

## Summary

- **Top-1 attribution accuracy**: 60.34%
- **Mean rank of true author**: 1.397
- **Attribution method**: raw_argmin_fallback
- **Raw-argmin comparison (pre-fix rule)**: top-1 60.34%, mean rank 1.397
- **Method note**: Fell back to raw argmin for the whole run: at least one candidate had fewer than 5 impostor reference points (see reference_warnings).
- **Reference warnings**: hamilton: only 3 reference points (need ≥5); madison: only 3 reference points (need ≥5)
- **Eligible authors**: 2 — hamilton, madison
- **Held-out essays scored**: 58

## Per-author accuracy

| author | n | correct | accuracy |
|---|---|---|---|
| hamilton | 47 | 24 | 51.06% |
| madison | 11 | 11 | 100.00% |

## Confusion matrix

| true \ predicted | hamilton | madison |
|---|---|---|
| hamilton | 24 | 23 |
| madison | 0 | 11 |

## Three-engine side-by-side (Task 11)

n_scored_essays (held out, all authors) = 58; n comparable across all three engines below = 58 (narrower only if engine_exceptions excluded any essay). Read the CIs before comparing rows — at this n they are wide.

| engine | accuracy | 95% Wilson CI | n |
|---|---|---|---|
| deviation_calibrated | 60.34% | [0.47, 0.72] | 58 |
| cosine_delta | 53.45% | [0.41, 0.66] | 58 |
| mfw_delta | 79.31% | [0.67, 0.88] | 58 |

- **Ensemble (2-of-3 agreement) coverage**: 100.00%
- **Ensemble accuracy on covered essays**: 72.41%
- **Pairwise agreement**:
  - cosine_delta|deviation_calibrated: 41.38%
  - cosine_delta|mfw_delta: 63.79%
  - deviation_calibrated|mfw_delta: 50.00%
