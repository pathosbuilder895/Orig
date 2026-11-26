# Alpha batch scoring report (internal, never shown to students)

- submissions: 10; scored: 10; errors: 0
- INCONCLUSIVE (baseline below minimum): 0/10 (0%)
- deviation min/median/max: 0.277 / 0.793 / 0.848
- deterministic on rerun: 10/10
- scoring time: per paper max 3979 ms; per student run (incl. app start) max 9.5 s
- baseline-size effect |dev(all) - dev(first 3)|: mean 0.039, max 0.158 (n=8)

## Accuracy against labels (strict = schedule_conversation/escalate; INCONCLUSIVE excluded)
- **False flags on own work:** 0/4 (0%), 95% CI 0%–0%
- **Caught not-own work:** 6/6 (100%), 95% CI 100%–100%
- lenient (+monitor): false flags 1/4 (25%), caught 6/6 (100%)

| strict | flagged | not flagged |
|---|---|---|
| not_own | 6 (TP) | 0 (FN) |
| natural | 0 (FP) | 4 (TN) |

### Deviation threshold sweep (flag if deviation >= t)
| t | caught | false flags |
|---|---|---|
| 0.05 | 6/6 (100%) | 4/4 (100%) |
| 0.10 | 6/6 (100%) | 4/4 (100%) |
| 0.15 | 6/6 (100%) | 4/4 (100%) |
| 0.20 | 6/6 (100%) | 4/4 (100%) |
| 0.25 | 6/6 (100%) | 4/4 (100%) |
| 0.30 | 6/6 (100%) | 3/4 (75%) |
| 0.35 | 6/6 (100%) | 2/4 (50%) |
| 0.40 | 6/6 (100%) | 1/4 (25%) |
| 0.45 | 6/6 (100%) | 1/4 (25%) |
| 0.50 | 6/6 (100%) | 0/4 (0%) |
| 0.55 | 6/6 (100%) | 0/4 (0%) |
| 0.60 | 6/6 (100%) | 0/4 (0%) |
| 0.65 | 6/6 (100%) | 0/4 (0%) |
| 0.70 | 6/6 (100%) | 0/4 (0%) |
| 0.75 | 6/6 (100%) | 0/4 (0%) |
| 0.80 | 4/6 (67%) | 0/4 (0%) |
| 0.85 | 0/6 (0%) | 0/4 (0%) |
| 0.90 | 0/6 (0%) | 0/4 (0%) |
| 0.95 | 0/6 (0%) | 0/4 (0%) |

### Pre-registered criteria: false-flag rate <= 5% AND catch rate >= 75%
**PASS** on the point estimates.

> Small-sample caveat: with ~20 natural and ~20 not-own papers, each paper is 5 points of rate and the 95% intervals above are wide (0/20 false flags is still compatible with ~15%). Treat a PASS as "no red flags in the math on real writing", not as validated accuracy. Fix the criteria before the session and do not tune thresholds on this same data and then re-score it.

## Problems
- none

| student | submission | label | baselines | words | deviation | dev(first3) | action | strict flag | det |
|---|---|---|---|---|---|---|---|---|---|
| d5e00d61 | 6e26f75ee1 | not_own | 4 | 674 | 0.815 | 0.804 | escalate | True | True |
| d5e00d61 | e04324ea52 | natural | 4 | 674 | 0.466 | 0.441 | monitor | False | True |
| 66d04eda | 9f2c0c4138 | natural | 4 | 654 | 0.319 | 0.288 | no_action | False | True |
| 66d04eda | c063cdf6e5 | not_own | 4 | 654 | 0.848 | 0.843 | escalate | True | True |
| ec291907 | b5daf3c435 | not_own | 4 | 668 | 0.787 | 0.945 | escalate | True | True |
| ec291907 | f913ca5760 | not_own | 4 | 668 | 0.799 | 0.827 | escalate | True | True |
| e0f636d4 | 05d1b64d74 | natural | 3 | 490 | 0.277 | - | no_action | False | True |
| e0f636d4 | 65afbc20ca | not_own | 3 | 490 | 0.820 | - | escalate | True | True |
| 24616929 | 285dbd960e | natural | 5 | 834 | 0.357 | 0.392 | no_action | False | True |
| 24616929 | c534e4ded7 | not_own | 5 | 834 | 0.835 | 0.813 | escalate | True | True |
