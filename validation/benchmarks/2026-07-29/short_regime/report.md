# Short-regime operating point (3×500-word baseline, 500-word probes)

| combo | AUC | AUC 95% CI | catch@5% | catch CI | threshold | llr fallbacks |
|---|---|---|---|---|---|---|
| PRIOR+LLR | 0.880 | 0.840–0.915 | 0.693 | 0.614–0.761 | 0.492 | 0 |
| SHRINK+PRIOR+LLR | 0.880 | 0.840–0.915 | 0.693 | 0.614–0.761 | 0.492 | 0 |
| LAW+PRIOR+LLR | 0.859 | 0.819–0.897 | 0.659 | 0.580–0.733 | 0.506 | 0 |
| LAW+SHRINK+PRIOR+LLR | 0.859 | 0.819–0.897 | 0.659 | 0.580–0.733 | 0.506 | 0 |
| LLR | 0.880 | 0.843–0.913 | 0.653 | 0.585–0.767 | 0.622 | 0 |
| SHRINK+LLR | 0.880 | 0.843–0.913 | 0.653 | 0.585–0.767 | 0.622 | 0 |
| LAW+LLR | 0.863 | 0.825–0.897 | 0.642 | 0.534–0.722 | 0.677 | 0 |
| LAW+SHRINK+LLR | 0.863 | 0.825–0.897 | 0.642 | 0.534–0.722 | 0.677 | 0 |
| LAW | 0.868 | 0.822–0.907 | 0.580 | 0.335–0.733 | 0.893 | 0 |
| LAW+SHRINK | 0.868 | 0.822–0.907 | 0.580 | 0.335–0.733 | 0.893 | 0 |
| OFF | 0.862 | 0.815–0.901 | 0.545 | 0.250–0.699 | 0.834 | 0 |
| SHRINK | 0.862 | 0.815–0.901 | 0.545 | 0.250–0.699 | 0.834 | 0 |
| LAW+PRIOR | 0.758 | 0.696–0.815 | 0.159 | 0.051–0.335 | 0.865 | 0 |
| LAW+SHRINK+PRIOR | 0.758 | 0.696–0.815 | 0.159 | 0.051–0.335 | 0.865 | 0 |
| PRIOR | 0.738 | 0.675–0.797 | 0.102 | 0.017–0.387 | 0.807 | 0 |
| SHRINK+PRIOR | 0.738 | 0.675–0.797 | 0.102 | 0.017–0.387 | 0.807 | 0 |

## Marginal effects

Mean across the 8 combos with the lever ON minus mean across the 8 with it OFF.

| lever | Δ catch@5% | Δ AUC |
|---|---|---|
| LLR | +0.3153 | +0.0640 |
| LAW | +0.0113 | -0.0027 |
| SHRINK | +0.0000 | +0.0000 |
| PRIOR | -0.2017 | -0.0598 |

LLR (impostor-null decision statistic) is the dominant lever by a wide margin — it is the
only lever whose marginal effect on catch@5% exceeds the OFF-row bootstrap CI width.
PRIOR (cohort Bayesian prior) is net-negative at this operating point (9 pseudo-students,
3×500-word baselines): it pulls per-student mu/sigma toward the cross-student genre prior,
which lowers sensitivity to genuine per-student deviation given how few baselines there are
per student here. SHRINK (Ledoit-Wolf rank remediation) shows an exact 0.0000 marginal
effect — not a rounding artifact; honest_scores and impostor_scores are bit-identical
between every SHRINK/non-SHRINK pair. This is architecturally expected, not a bug: shrinkage
only transforms the density matrix ρ (`state.density_matrix`), and ρ feeds only the Born
probability P and the amplitude-scoring path (`original/quantum/scoring.py`, gated by
`AMPLITUDE_SCORING_ENABLED`, off in this runner). The deviation_score that drives AUC/catch@5%
here is computed from `state.baseline_mean`/`state.baseline_std` (`original/quantum/scoring.py:504-560`),
which RANK_REMEDIATION never touches. LAW (length-adaptive weights) has a small positive
effect on catch@5% and a negligible/slightly negative effect on AUC.
