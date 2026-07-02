# Benchmark — raid

_Generated 2026-07-01T14:37:53.426355Z_

## Summary

- **AUC**: 0.4484
- **Brier**: 0.3755
- **Authors**: 1
- **Essays scored**: 36
- **Baseline samples**: 3
- **Mean scoring time**: 645.53 ms / essay

## Per-label deviation

| label | n | mean | std |
|---|---|---|---|
| ai_generated | 31 | 0.6898 | 0.0757 |
| authentic | 5 | 0.7094 | 0.0668 |

## Action-threshold metrics

| name | threshold | TP | FP | TN | FN | precision | recall | F1 |
|---|---|---|---|---|---|---|---|---|
| no_action | 0.4 | 0 | 0 | 31 | 5 | 0.0 | 0.0 | 0.0 |
| monitor | 0.55 | 0 | 1 | 30 | 5 | 0.0 | 0.0 | 0.0 |
| escalate | 0.75 | 4 | 25 | 6 | 1 | 0.1379 | 0.8 | 0.2353 |

## Calibration curve (10 bins)

| bin | n | mean predicted | fraction positive |
|---|---|---|---|
| 0.50–0.60 | 2 | 0.5786 | 0.0 |
| 0.60–0.70 | 32 | 0.651 | 0.0938 |
| 0.70–0.80 | 2 | 0.7069 | 1.0 |

## Bias audit

### ai_provider

| value | n | mean dev | AUC | FPR (authentic-only) |
|---|---|---|---|---|
| chatgpt | 14 | 0.7046 | 0.5 | nan |
| none | 22 | 0.6849 | 0.7294 | 1.0 |

### word_count_bucket

| value | n | mean dev | AUC | FPR (authentic-only) |
|---|---|---|---|---|
| <500 | 36 | 0.6926 | 0.6968 | 1.0 |

### label

| value | n | mean dev | AUC | FPR (authentic-only) |
|---|---|---|---|---|
| ai_generated | 31 | 0.6898 | 0.5 | nan |
| authentic | 5 | 0.7094 | 0.5 | 1.0 |
