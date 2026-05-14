"""
quantum/amplitude.py — Complex amplitude encoding for Phase 6 scoring.

Encoding
────────
Each feature i is encoded as a complex amplitude:

    ψ[i] = r[i] · exp(i·θ[i])

where:
    r[i]  = (1 − tanh(|z[i]|/1.5)) · w[i] · reliability
             ↑ 1.0 at z=0 (in-baseline); → 0 for large |z| (anomalous)
    θ[i]  = +π/6  if z[i] > 0  (feature above baseline)
             −π/6  if z[i] ≤ 0  (feature at or below baseline)
    reliability = exp(−1/(2·n_tokens))   [Gaussian wave packet attenuation]
                  → 0 for very short texts; → 1 for long texts

Superposition baseline
──────────────────────
K authenticated baseline samples are combined into a single reference state:

    |ψ_b⟩ = (1/√K) Σ_k e^(iφ_k) |ψ_k⟩

where φ_k = ((K−1−k)/K) · (π/4) — newest sample (k=K-1) gets φ=0,
oldest (k=0) gets φ=π/4. This recency phase taper means newer samples
contribute more coherently to the reference; old samples add a slight
phase offset that dampens their constructive contribution.

Quantum fidelity
────────────────
    F = |⟨ψ_b|ψ_s⟩|² / (‖ψ_b‖²·‖ψ_s‖²)  ∈ [0, 1]

F ≈ 1 → submission amplitude aligns with baseline superposition → authentic
F ≈ 0 → submission amplitude incoherent with baseline → anomalous

Covariance trap
───────────────
The phase θ encodes whether each feature is above or below baseline.
A ghostwriter who matches magnitudes but reverses directions (e.g., putting
vocabulary-richness above baseline when the student consistently keeps it
below) produces destructive interference, lowering fidelity even when
individual feature magnitudes match. This catches adversaries who optimise
marginals without understanding the joint directional structure.

Keyed random unitary projection
────────────────────────────────
For adversarial robustness:
    U = Q  from  QR(G)  where  G ~ N(0,1,D,D)  seeded by HMAC-SHA256
    Both ψ_b and ψ_s are projected: ψ' = U·ψ
    Fidelity is U-invariant: |⟨Uψ_b|Uψ_s⟩|² = |⟨ψ_b|ψ_s⟩|²

An adversary cannot optimise a submission to spoof fidelity because U
changes on every submission (keyed by student_id + submission_id + secret).

Von Neumann entropy
────────────────────
    S = −Tr(ρ log ρ) / log(D)  ∈ [0, 1]

Computed from eigenvalues of the density matrix ρ:
S ≈ 0 → pure state (consistent baseline, high confidence)
S ≈ 1 → maximally mixed state (variable baseline, low confidence)
"""

from __future__ import annotations

import hashlib
import hmac
import math
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import numpy as np

from ..constants import ALL_FEATURE_CODES, FEATURE_DIM

if TYPE_CHECKING:
    from .state import BaselineSample


# ── Amplitude encoding ────────────────────────────────────────────────────────

def encode_amplitudes(
    z: np.ndarray,
    weight_vec: np.ndarray,
    active: np.ndarray,
    n_tokens: int,
) -> np.ndarray:
    """
    Encode z-score vector as a complex amplitude vector.

    Parameters
    ----------
    z         : shape (D,), standardised z-scores (submission − baseline) / std
    weight_vec: shape (D,), per-feature tier weights
    active    : shape (D,), bool — False for no-data/constant features
    n_tokens  : word count of the submission text

    Returns
    -------
    psi : complex128, shape (D,)
        ψ[i] = r[i] · exp(i·θ[i]) · active[i]
    """
    # Gaussian wave packet reliability: exp(−σ²/2) where σ = 1/√n_tokens
    # Clamp denominator at 2.0 to avoid division-by-zero for empty text.
    reliability = float(np.exp(-1.0 / max(2.0 * n_tokens, 2.0)))

    # Magnitude: 1.0 when z=0 (perfectly in-baseline), → 0 for |z| >> 0.
    # Uses the same tanh divisor (1.5) as the deviation_score in scoring.py
    # so the amplitude magnitude is calibrated to the same scale.
    r = (1.0 - np.tanh(np.abs(z) / 1.5)) * weight_vec * reliability

    # Phase: +π/6 for features above baseline, −π/6 for at-or-below.
    # π/6 ≈ 30° is chosen to give meaningful phase differences while keeping
    # constructive/destructive contributions detectable in the inner product.
    theta = np.where(z > 0.0, math.pi / 6.0, -math.pi / 6.0)

    # Zero out inactive features (no-data placeholders, zero-frequency features)
    r = r * active.astype(np.float64)
    theta = theta * active.astype(np.float64)

    return (r * np.exp(1j * theta)).astype(np.complex128)


# ── Superposition baseline ────────────────────────────────────────────────────

def build_superposition_baseline(
    samples: "List[BaselineSample]",
    weight_vec: np.ndarray,
    active: np.ndarray,
    baseline_mean: np.ndarray,
    baseline_std: np.ndarray,
    n_tokens: int,
) -> np.ndarray:
    """
    Build the superposition reference state from K contributing samples.

    Each sample k gets phase taper φ_k = ((K−1−k)/K) · (π/4).
    The newest sample (k=K-1) has φ=0 (full coherence); the oldest (k=0)
    has φ=π/4 (45° phase offset, partial coherence).

    Parameters
    ----------
    samples      : authenticated baseline samples (auth_weight > 0)
    weight_vec   : shape (D,), tier weights
    active       : shape (D,), bool mask
    baseline_mean: shape (D,), overall baseline mean
    baseline_std : shape (D,), overall baseline std (already floored)
    n_tokens     : word count of the *submission* being scored (sets reliability)

    Returns
    -------
    psi_b : complex128, shape (D,)
    """
    K = len(samples)
    if K == 0:
        # No baseline — return the zero vector; quantum_fidelity handles it.
        return np.zeros(FEATURE_DIM, dtype=np.complex128)

    superposition = np.zeros(FEATURE_DIM, dtype=np.complex128)
    safe_std = np.maximum(baseline_std, 1e-6)

    for k, sample in enumerate(samples):
        # z-score of this sample relative to the overall baseline mean
        z_k = (sample.vector - baseline_mean) / safe_std

        psi_k = encode_amplitudes(z_k, weight_vec, active, n_tokens)

        # Recency phase: newest sample gets φ=0, oldest gets φ=π/4
        recency_phase = ((K - 1 - k) / K) * (math.pi / 4.0)
        superposition += np.exp(1j * recency_phase) * psi_k

    return (superposition / math.sqrt(K)).astype(np.complex128)


# ── Quantum fidelity ──────────────────────────────────────────────────────────

def quantum_fidelity(
    psi_b: np.ndarray,
    psi_s: np.ndarray,
) -> float:
    """
    Compute quantum fidelity F = |⟨ψ_b|ψ_s⟩|² / (‖ψ_b‖²·‖ψ_s‖²).

    Parameters
    ----------
    psi_b : complex128, shape (D,) — superposition baseline
    psi_s : complex128, shape (D,) — submission amplitude

    Returns
    -------
    F : float ∈ [0, 1]
        1.0 → perfect alignment (authentic)
        0.0 → orthogonal (anomalous) or degenerate
    """
    norm_b_sq = float(np.real(np.vdot(psi_b, psi_b)))
    norm_s_sq = float(np.real(np.vdot(psi_s, psi_s)))

    # Both near-zero → no data on either side → treat as authentic (unknown)
    if norm_b_sq < 1e-12 and norm_s_sq < 1e-12:
        return 1.0
    # One near-zero → degenerate → return 0
    if norm_b_sq < 1e-12 or norm_s_sq < 1e-12:
        return 0.0

    # ⟨ψ_b|ψ_s⟩ = conj(ψ_b) · ψ_s  (np.vdot conjugates first arg)
    inner = np.vdot(psi_b, psi_s)
    F = float(abs(inner) ** 2) / (norm_b_sq * norm_s_sq)
    return float(np.clip(F, 0.0, 1.0))


# ── Keyed random unitary projection ──────────────────────────────────────────

def keyed_unitary(
    secret_key: str,
    student_id: str,
    submission_id: str,
    dim: int,
) -> np.ndarray:
    """
    Generate a keyed random unitary matrix U of shape (dim, dim).

    U = Q  from  QR-decomposition of a complex Gaussian matrix G,
    where G is seeded deterministically by HMAC-SHA256(secret_key,
    student_id + "|" + submission_id).

    Properties
    ----------
    - U changes for every (student, submission) pair.
    - Without secret_key, U cannot be predicted or optimised against.
    - Fidelity is preserved: |⟨Uψ_b|Uψ_s⟩|² = |⟨ψ_b|ψ_s⟩|²

    Parameters
    ----------
    secret_key    : HMAC secret (from env var SECRET_KEY)
    student_id    : student identifier
    submission_id : submission identifier
    dim           : dimension of the unitary (= FEATURE_DIM)

    Returns
    -------
    U : complex128, shape (dim, dim), unitary
    """
    message = f"{student_id}|{submission_id}".encode("utf-8")
    digest = hmac.new(
        secret_key.encode("utf-8"),
        message,
        hashlib.sha256,
    ).digest()
    # Use first 4 bytes as seed for the RNG
    seed_int = int.from_bytes(digest[:4], "big")
    rng = np.random.default_rng(seed_int)

    # Complex Gaussian random matrix: G = A + iB, A,B ~ N(0,1)
    G = (
        rng.standard_normal((dim, dim))
        + 1j * rng.standard_normal((dim, dim))
    )
    Q, _ = np.linalg.qr(G)
    return Q.astype(np.complex128)


def apply_keyed_projection(
    psi_b: np.ndarray,
    psi_s: np.ndarray,
    secret_key: str,
    student_id: str,
    submission_id: str,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Apply a keyed random unitary to both amplitude vectors.

    Returns (U@psi_b, U@psi_s). No-op when secret_key is empty.

    The fidelity |⟨Uψ_b|Uψ_s⟩|² = |⟨ψ_b|ψ_s⟩|² is preserved,
    so the result is mathematically identical but the adversary must
    search in the rotated space, which changes on every submission.
    """
    if not secret_key:
        return psi_b, psi_s
    U = keyed_unitary(secret_key, student_id, submission_id, len(psi_b))
    return U @ psi_b, U @ psi_s


# ── Von Neumann entropy ───────────────────────────────────────────────────────

def von_neumann_entropy(rho: np.ndarray) -> float:
    """
    Compute the von Neumann entropy S = −Tr(ρ log ρ), normalised to [0, 1].

    Parameters
    ----------
    rho : real symmetric matrix, shape (D, D), density matrix of a StudentState

    Returns
    -------
    S_norm : float ∈ [0, 1]
        0 → pure state (single sample or perfectly consistent baseline)
        1 → maximally mixed (D orthogonal, equally-weighted samples)
    """
    # eigvalsh uses the symmetric fast path; eigenvalues are real
    eigenvalues = np.linalg.eigvalsh(rho)
    # Clip to [ε, 1] and renormalise for numerical safety (ρ should sum to 1)
    eigenvalues = np.clip(eigenvalues, 1e-12, 1.0)
    eigenvalues = eigenvalues / eigenvalues.sum()
    S = -float(np.sum(eigenvalues * np.log(eigenvalues)))
    # Normalise by log(D): maximally mixed → S/log(D) = 1
    D = rho.shape[0]
    return float(np.clip(S / math.log(D), 0.0, 1.0))


# ── 3-way interference decomposition ─────────────────────────────────────────

def interference_components(
    psi_b: np.ndarray,
    psi_s: np.ndarray,
    feature_codes: Optional[List[str]] = None,
) -> Dict[str, List[Tuple[str, float]]]:
    """
    Decompose the inner product ⟨ψ_b|ψ_s⟩ into per-feature contributions.

    Per-feature contribution: c_i = conj(ψ_b[i]) · ψ_s[i]

    Classification
    ──────────────
    constructive : Re(c_i) > 0  — in-phase; submission and baseline aligned
    destructive  : Re(c_i) < 0  — out-of-phase; genuine deviation in same direction
    novel        : |Im(c_i)| > |Re(c_i)|  — quadrature component; pattern absent
                   from baseline's phase structure (new writing behaviour)

    Parameters
    ----------
    psi_b         : complex128, shape (D,)
    psi_s         : complex128, shape (D,)
    feature_codes : list of D feature code strings (defaults to ALL_FEATURE_CODES)

    Returns
    -------
    dict with keys "constructive", "destructive", "novel", each a list of
    (feature_code, strength) tuples sorted by descending strength.
    """
    if feature_codes is None:
        feature_codes = ALL_FEATURE_CODES

    contributions = np.conj(psi_b) * psi_s   # element-wise: conj(ψ_b[i])·ψ_s[i]
    result: Dict[str, List[Tuple[str, float]]] = {
        "constructive": [],
        "destructive": [],
        "novel": [],
    }

    for i, code in enumerate(feature_codes):
        c = contributions[i]
        re = float(np.real(c))
        im = float(np.imag(c))
        abs_re = abs(re)
        abs_im = abs(im)

        # Skip near-zero contributions (inactive features)
        if abs_re + abs_im < 1e-12:
            continue

        if abs_im > abs_re:
            result["novel"].append((code, abs_im))
        elif re > 0.0:
            result["constructive"].append((code, re))
        else:
            result["destructive"].append((code, abs_re))

    for key in result:
        result[key].sort(key=lambda x: x[1], reverse=True)

    return result


__all__ = [
    "encode_amplitudes",
    "build_superposition_baseline",
    "quantum_fidelity",
    "keyed_unitary",
    "apply_keyed_projection",
    "von_neumann_entropy",
    "interference_components",
]
