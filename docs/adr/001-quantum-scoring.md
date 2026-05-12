# ADR 001 — Quantum-Inspired Density Matrix Scoring

**Status:** Accepted
**Date:** 2026-03-17
**Deciders:** Engineering, Academic Integrity Research

---

## Context

We need a scoring model that takes a set of authenticated student writing samples (baseline) and produces a numerical anomaly score for new submissions.  The score must be:

1. **Compositional** — each new baseline sample should refine the model without requiring a full retrain.
2. **Uncertainty-aware** — the model should express low confidence when baseline samples are inconsistent with each other.
3. **Interpretable** — instructors must be able to understand why a submission was flagged.
4. **Deterministic** — given the same inputs the score must be identical.  No random components.

The academic integrity literature offers several candidate approaches:

| Approach | Pros | Cons |
|----------|------|------|
| Cosine distance from mean baseline vector | Simple, fast | Ignores variance; all samples treated as identical |
| Mahalanobis distance | Variance-aware | Requires matrix inversion; unstable with < N features samples |
| SVM one-class classification | High accuracy with enough data | Requires training; not incremental |
| Density matrix (quantum-inspired) | Compositional, uncertainty-aware, no training | Novel; less precedent in production |

---

## Decision

We use a **quantum-inspired density matrix** to represent each student's writing identity.

### Mathematical formulation

Given N authenticated baseline samples with feature vectors ψ₁…ψₙ (each normalised to unit length) and authentication weights w₁…wₙ:

```
ρ = Σᵢ wᵢ (ψᵢ ⊗ ψᵢᵀ) / Σᵢ wᵢ
```

ρ is a D×D positive semi-definite matrix (D = 34 features) with trace = 1 — a valid quantum density matrix in the information-theoretic sense.

**Scoring a new submission** with feature vector ξ (normalised):

```
P = ξᵀ ρ ξ          (Born rule probability)
D = 1 − P            (deviation)
```

P can be interpreted as "how much of the submission's writing style is captured by the baseline density matrix."  P = 1 means the submission lies exactly in the baseline subspace.

**Purity** `tr(ρ²)` measures how concentrated the density matrix is:
- Purity = 1.0 means all baseline samples are identical (pure state).
- Purity = 1/N means all samples are maximally diverse (maximally mixed state).
- Low purity signals an inconsistent baseline; deviation scores are less reliable.

### Authentication weighting

Baseline samples are tagged with a provenance enum (PROCTORED, VERIFIED, UNVERIFIED) and mapped to authentication weights via the `AUTH_WEIGHTS` constant:

```python
AUTH_WEIGHTS = {PROCTORED: 1.0, VERIFIED: 0.8, UNVERIFIED: 0.0}
```

Unverified samples are excluded from the density matrix entirely.  Proctored samples receive full weight.

### Incremental updates

Adding a new baseline sample is O(D²) — just a rank-1 update to ρ.  No retraining, no matrix inversion.

---

## Alternatives considered

### Mahalanobis distance

The covariance matrix Σ requires at least D samples to be full-rank (D = 34), meaning it is singular until the student has submitted 34+ baseline essays.  We expect most students to have 3–10 samples.  Regularisation workarounds (shrinkage estimators) exist but introduce hyperparameters that need empirical calibration.

**Rejected** because it requires more baseline data than we can realistically collect and introduces calibration complexity.

### Cosine distance from centroid

Treats all baseline samples as a single averaged vector.  Loses all information about intra-student variance.  A student whose writing is naturally variable will look anomalous even on a genuine submission.

**Rejected** because it conflates natural style variation with external authorship.

### Neural embedding similarity (SBERT/etc.)

Powerful but black-box.  Explainability is a hard requirement — instructors must be able to see which specific features drove a score.  Neural embeddings do not decompose cleanly into named features.

**Rejected** as primary model; could be added as a secondary signal in a future version.

---

## Consequences

**Positive:**
- Incremental update cost is O(D²) — instant for D = 34.
- Purity gives a principled measure of baseline consistency, surfaced in the API response.
- The Born-rule projection decomposes naturally into per-feature interference terms, enabling the `InterferenceDecomposition` output that shows which features drove the score.
- No training phase; the model is fully described by the feature vectors and weights.

**Negative:**
- The density matrix formalism is unfamiliar to most engineers.  The codebase includes detailed comments and this ADR to mitigate the knowledge risk.
- Deviation thresholds (mapping scores to actions) are set analytically, not empirically calibrated.  This is a known gap; a calibration study against labelled decisions is future work.
- The model does not capture sequential or temporal patterns within a text — only aggregate feature distributions.

---

## References

- Nielsen, M.A. & Chuang, I.L. (2000). *Quantum Computation and Quantum Information*. Cambridge University Press. (Density matrix formalism, Chapter 2)
- Koppel, M., Schler, J., & Argamon, S. (2009). Computational methods in authorship attribution. *Journal of the American Society for Information Science and Technology*, 60(1), 9–26.
- Juola, P. (2006). Authorship attribution. *Foundations and Trends in Information Retrieval*, 1(3), 233–334.
