"""
null_models.py — fit an explicit "not this student" distribution.

The evaluator in binary_auc.py measures how well Original separates
same-author from different-author submissions using ``deviation_score``
(a monotone function of "distance from the CLAIMED author's baseline").
That is an approximation of −log P(ξ | H₁) — it says nothing about what
"different" should look like, so there is no way to guarantee a false-
positive rate at any threshold.

The impostor-Gaussian fit itself now lives in
``original/quantum/null_pool.py`` — it graduated to the production
package when the API path learned to build per-tenant pools (the numbers
that justified that move are in
validation/benchmarks/2026-07-01/*nullmodel*). This module re-exports it
so every existing harness import keeps working unchanged.

Kept deliberately simple: diagonal Gaussian, not a full-covariance or
mixture model. A GMM-UBM upgrade (Reynolds 2000, the classical forensic
speaker-verification technique) is the natural next step if the impostor
Gaussian under-performs — same interface, just a richer p(ξ|H0).
"""

from __future__ import annotations

from original.quantum.null_pool import fit_impostor_gaussian

__all__ = ["fit_impostor_gaussian"]
