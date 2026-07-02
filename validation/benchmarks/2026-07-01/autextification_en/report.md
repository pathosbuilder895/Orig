# Benchmark — autextification_en

_Generated 2026-07-02T00:43:12.889137Z_

## Summary

- **AUC**: 0.6091
- **Brier**: 0.2771
- **Authors**: 3
- **Essays scored**: 213
- **Baseline samples**: 9
- **Mean scoring time**: 200.27 ms / essay

## Per-label deviation

| label | n | mean | std |
|---|---|---|---|
| ai_generated | 111 | 0.793 | 0.0886 |
| authentic | 102 | 0.7574 | 0.0838 |

## Action-threshold metrics

| name | threshold | TP | FP | TN | FN | precision | recall | F1 |
|---|---|---|---|---|---|---|---|---|
| no_action | 0.4 | 0 | 0 | 111 | 102 | 0.0 | 0.0 | 0.0 |
| monitor | 0.55 | 1 | 0 | 111 | 101 | 1.0 | 0.0098 | 0.0194 |
| escalate | 0.75 | 44 | 38 | 73 | 58 | 0.5366 | 0.4314 | 0.4783 |

## Calibration curve (10 bins)

| bin | n | mean predicted | fraction positive |
|---|---|---|---|
| 0.40–0.50 | 4 | 0.4713 | 0.25 |
| 0.50–0.60 | 39 | 0.5636 | 0.4103 |
| 0.60–0.70 | 116 | 0.6531 | 0.4655 |
| 0.70–0.80 | 53 | 0.7383 | 0.566 |
| 0.80–0.90 | 1 | 0.809 | 1.0 |

## Bias audit

### ai_provider

| value | n | mean dev | AUC | FPR (authentic-only) |
|---|---|---|---|---|
| none | 213 | 0.776 | 0.5707 | 0.9902 |

### word_count_bucket

| value | n | mean dev | AUC | FPR (authentic-only) |
|---|---|---|---|---|
| <500 | 213 | 0.776 | 0.5707 | 0.9902 |

### label

| value | n | mean dev | AUC | FPR (authentic-only) |
|---|---|---|---|---|
| ai_generated | 111 | 0.793 | 0.5 | nan |
| authentic | 102 | 0.7574 | 0.5 | 0.9902 |
