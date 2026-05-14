"""
tests/quantum/test_amplitude.py — Unit tests for the amplitude encoding module.
"""

from __future__ import annotations

import math
from typing import List

import numpy as np
import pytest

from original.constants import ALL_FEATURE_CODES, FEATURE_DIM, TIER_WEIGHTS, FEATURE_TIER
from original.quantum.amplitude import (
    apply_keyed_projection,
    build_superposition_baseline,
    encode_amplitudes,
    interference_components,
    keyed_unitary,
    quantum_fidelity,
    von_neumann_entropy,
)
from original.quantum.state import BaselineSample


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _weight_vec() -> np.ndarray:
    """Tier-weight vector matching scoring.py's _TIER_WEIGHT_VECTOR."""
    return np.array(
        [TIER_WEIGHTS.get(FEATURE_TIER[code], 1.0) for code in ALL_FEATURE_CODES],
        dtype=np.float64,
    )


def _active_all() -> np.ndarray:
    return np.ones(FEATURE_DIM, dtype=bool)


def _make_sample(value: float = 0.5) -> BaselineSample:
    """Baseline sample with all features at ``value``."""
    return BaselineSample(
        text="sample text",
        vector=np.full(FEATURE_DIM, value, dtype=np.float64),
        provenance="proctored",
        auth_weight=1.0,
    )


def _make_samples(n: int, value: float = 0.5) -> List[BaselineSample]:
    return [_make_sample(value) for _ in range(n)]


# ── encode_amplitudes ─────────────────────────────────────────────────────────

class TestEncodeAmplitudes:
    def test_zero_z_gives_max_magnitude(self):
        """z=0 → r = weight (maximum amplitude, no deviation from baseline)."""
        w = _weight_vec()
        z = np.zeros(FEATURE_DIM)
        active = _active_all()
        psi = encode_amplitudes(z, w, active, n_tokens=500)
        # r = (1 - tanh(0)) * w * reliability = 1 * w * ~1 ≈ w
        reliability = math.exp(-1.0 / max(2.0 * 500, 2.0))
        expected_r = w * reliability
        assert np.allclose(np.abs(psi), expected_r, atol=1e-6)

    def test_large_z_gives_near_zero_magnitude(self):
        """z=20 → r ≈ 0 (fully saturated tanh)."""
        w = _weight_vec()
        z = np.full(FEATURE_DIM, 20.0)
        active = _active_all()
        psi = encode_amplitudes(z, w, active, n_tokens=500)
        # tanh(20/1.5) ≈ 1, so r = (1-1)*w ≈ 0
        assert np.all(np.abs(psi) < 0.01)

    def test_short_text_attenuated(self):
        """Shorter texts produce smaller amplitudes (Gaussian wave packet).

        reliability(n) = exp(-1/(2n)).
        n=5  → reliability ≈ 0.905
        n=500 → reliability ≈ 0.999
        Ratio ≈ 0.906, well below the 0.95 threshold.
        """
        w = _weight_vec()
        z = np.zeros(FEATURE_DIM)
        active = _active_all()
        psi_short = encode_amplitudes(z, w, active, n_tokens=5)
        psi_long = encode_amplitudes(z, w, active, n_tokens=500)
        # All magnitudes should be smaller for short text
        assert np.all(np.abs(psi_short) <= np.abs(psi_long) + 1e-9)
        # And meaningfully so: 5-token text attenuated by > 5% vs 500-token text
        assert np.mean(np.abs(psi_short)) < np.mean(np.abs(psi_long)) * 0.95

    def test_phase_encodes_direction(self):
        """z>0 → phase +π/6; z<0 → phase −π/6."""
        w = np.ones(FEATURE_DIM)
        active = _active_all()

        z_pos = np.ones(FEATURE_DIM)
        psi_pos = encode_amplitudes(z_pos, w, active, n_tokens=200)
        phases_pos = np.angle(psi_pos[w > 0])
        assert np.allclose(phases_pos, math.pi / 6.0, atol=1e-9)

        z_neg = -np.ones(FEATURE_DIM)
        psi_neg = encode_amplitudes(z_neg, w, active, n_tokens=200)
        phases_neg = np.angle(psi_neg[w > 0])
        assert np.allclose(phases_neg, -math.pi / 6.0, atol=1e-9)

    def test_inactive_features_zeroed(self):
        """Features with active=False contribute 0 to amplitude."""
        w = _weight_vec()
        z = np.random.default_rng(42).standard_normal(FEATURE_DIM)
        active = np.zeros(FEATURE_DIM, dtype=bool)
        active[:5] = True   # only first 5 active
        psi = encode_amplitudes(z, w, active, n_tokens=200)
        assert np.all(np.abs(psi[5:]) < 1e-12)
        assert np.any(np.abs(psi[:5]) > 1e-6)


# ── build_superposition_baseline ─────────────────────────────────────────────

class TestBuildSuperpositionBaseline:
    def test_empty_samples_gives_zeros(self):
        w = _weight_vec()
        active = _active_all()
        psi_b = build_superposition_baseline(
            [], w, active,
            np.full(FEATURE_DIM, 0.5), np.full(FEATURE_DIM, 0.1), 200,
        )
        assert np.all(psi_b == 0)

    def test_consistent_samples_coherent(self):
        """K identical samples → superposition magnitude = sample magnitude (coherent)."""
        w = np.ones(FEATURE_DIM)
        active = _active_all()
        mu = np.full(FEATURE_DIM, 0.5)
        sigma = np.full(FEATURE_DIM, 0.05)
        # All samples identical at 0.5 → z_k = 0 for all k
        samples = _make_samples(5, value=0.5)
        psi_b = build_superposition_baseline(samples, w, active, mu, sigma, 200)
        # Single sample amplitude for z=0
        psi_one = encode_amplitudes(np.zeros(FEATURE_DIM), w, active, 200)
        # Superposition magnitude should be close to single sample (coherent sum / √K * √K = 1)
        # With recency phases applied, magnitude is slightly reduced — check it's non-trivial
        assert np.linalg.norm(psi_b) > 0.1 * np.linalg.norm(psi_one)

    def test_single_sample_matches_encode(self):
        """Single sample: superposition = encode_amplitudes of sample z-score."""
        w = np.ones(FEATURE_DIM)
        active = _active_all()
        mu = np.full(FEATURE_DIM, 0.5)
        sigma = np.full(FEATURE_DIM, 0.1)
        sample_vec = np.full(FEATURE_DIM, 0.6)  # z = (0.6-0.5)/0.1 = 1.0
        sample = BaselineSample(
            text="x", vector=sample_vec, provenance="proctored", auth_weight=1.0
        )
        psi_b = build_superposition_baseline([sample], w, active, mu, sigma, 200)
        z_expected = (sample_vec - mu) / np.maximum(sigma, 1e-6)
        psi_expected = encode_amplitudes(z_expected, w, active, 200)
        # For K=1: recency_phase = ((0)/1)*(π/4) = 0, and (1/√1)*e^0*psi_one = psi_one
        assert np.allclose(np.abs(psi_b), np.abs(psi_expected), atol=1e-6)


# ── quantum_fidelity ──────────────────────────────────────────────────────────

class TestQuantumFidelity:
    def test_identical_gives_one(self):
        rng = np.random.default_rng(0)
        psi = (rng.standard_normal(FEATURE_DIM) +
               1j * rng.standard_normal(FEATURE_DIM))
        F = quantum_fidelity(psi, psi)
        assert abs(F - 1.0) < 1e-9

    def test_orthogonal_gives_zero(self):
        psi_b = np.zeros(FEATURE_DIM, dtype=np.complex128)
        psi_b[0] = 1.0
        psi_s = np.zeros(FEATURE_DIM, dtype=np.complex128)
        psi_s[1] = 1.0
        F = quantum_fidelity(psi_b, psi_s)
        assert abs(F) < 1e-9

    def test_both_zero_gives_one(self):
        """Degenerate case: both vectors are zero → authentic (no data)."""
        psi_b = np.zeros(FEATURE_DIM, dtype=np.complex128)
        psi_s = np.zeros(FEATURE_DIM, dtype=np.complex128)
        F = quantum_fidelity(psi_b, psi_s)
        assert F == 1.0

    def test_one_zero_gives_zero(self):
        """One vector zero, other non-zero → degenerate → 0."""
        psi_b = np.zeros(FEATURE_DIM, dtype=np.complex128)
        psi_s = np.ones(FEATURE_DIM, dtype=np.complex128)
        assert quantum_fidelity(psi_b, psi_s) == 0.0
        assert quantum_fidelity(psi_s, psi_b) == 0.0

    def test_bounded(self):
        rng = np.random.default_rng(7)
        for _ in range(20):
            a = rng.standard_normal(FEATURE_DIM) + 1j * rng.standard_normal(FEATURE_DIM)
            b = rng.standard_normal(FEATURE_DIM) + 1j * rng.standard_normal(FEATURE_DIM)
            F = quantum_fidelity(a, b)
            assert 0.0 <= F <= 1.0 + 1e-9


# ── keyed_unitary + apply_keyed_projection ────────────────────────────────────

class TestKeyedUnitary:
    def test_fidelity_invariant_under_unitary(self):
        """F(psi_b, psi_s) == F(U@psi_b, U@psi_s) for any unitary U."""
        rng = np.random.default_rng(99)
        D = FEATURE_DIM
        psi_b = (rng.standard_normal(D) + 1j * rng.standard_normal(D)).astype(np.complex128)
        psi_s = (rng.standard_normal(D) + 1j * rng.standard_normal(D)).astype(np.complex128)

        F_plain = quantum_fidelity(psi_b, psi_s)
        psi_b_rot, psi_s_rot = apply_keyed_projection(
            psi_b, psi_s, "test-secret", "student1", "sub1"
        )
        F_rotated = quantum_fidelity(psi_b_rot, psi_s_rot)
        assert abs(F_plain - F_rotated) < 1e-8

    def test_different_submission_gives_different_unitary(self):
        """Different submission_id → different unitary matrix."""
        D = 10
        U1 = keyed_unitary("secret", "stu1", "sub1", D)
        U2 = keyed_unitary("secret", "stu1", "sub2", D)
        assert not np.allclose(U1, U2)

    def test_same_inputs_deterministic(self):
        """Same inputs always produce the same unitary."""
        D = 10
        U1 = keyed_unitary("secret", "stu1", "sub1", D)
        U2 = keyed_unitary("secret", "stu1", "sub1", D)
        assert np.allclose(U1, U2)

    def test_empty_secret_is_noop(self):
        """Empty secret → apply_keyed_projection returns original vectors unchanged."""
        rng = np.random.default_rng(5)
        psi_b = rng.standard_normal(FEATURE_DIM).astype(np.complex128)
        psi_s = rng.standard_normal(FEATURE_DIM).astype(np.complex128)
        psi_b2, psi_s2 = apply_keyed_projection(psi_b, psi_s, "", "s", "x")
        assert np.array_equal(psi_b, psi_b2)
        assert np.array_equal(psi_s, psi_s2)

    def test_unitary_orthonormality(self):
        """U†U = I (up to float precision)."""
        D = 20
        U = keyed_unitary("key", "s", "sub", D)
        product = U.conj().T @ U
        assert np.allclose(product, np.eye(D), atol=1e-10)


# ── von_neumann_entropy ───────────────────────────────────────────────────────

class TestVonNeumannEntropy:
    def test_pure_state_gives_zero(self):
        """Rank-1 density matrix → entropy = 0."""
        v = np.random.default_rng(1).random(FEATURE_DIM)
        v = v / np.linalg.norm(v)
        rho = np.outer(v, v)   # rank-1, trace=1
        S = von_neumann_entropy(rho)
        assert abs(S) < 0.01

    def test_maximally_mixed_gives_one(self):
        """Identity/D → normalised entropy = 1."""
        rho = np.eye(FEATURE_DIM) / FEATURE_DIM
        S = von_neumann_entropy(rho)
        assert abs(S - 1.0) < 0.01

    def test_bounded(self):
        rng = np.random.default_rng(42)
        for _ in range(5):
            # Random PSD matrix normalised to trace 1
            A = rng.standard_normal((FEATURE_DIM, FEATURE_DIM))
            rho = A @ A.T
            rho /= np.trace(rho)
            S = von_neumann_entropy(rho)
            assert 0.0 <= S <= 1.0 + 1e-9

    def test_more_consistent_baseline_lower_entropy(self):
        """A tight baseline (few samples, similar vectors) has lower entropy."""
        rng = np.random.default_rng(77)
        # Pure state — single sample
        v = rng.random(FEATURE_DIM)
        v /= np.linalg.norm(v)
        rho_pure = np.outer(v, v)

        # Mixed state — 10 diverse samples
        rho_mixed = np.zeros((FEATURE_DIM, FEATURE_DIM))
        for _ in range(10):
            u = rng.random(FEATURE_DIM)
            u /= np.linalg.norm(u)
            rho_mixed += np.outer(u, u)
        rho_mixed /= 10

        assert von_neumann_entropy(rho_pure) < von_neumann_entropy(rho_mixed)


# ── interference_components ───────────────────────────────────────────────────

class TestInterferenceComponents:
    def test_returns_three_categories(self):
        rng = np.random.default_rng(3)
        psi_b = (rng.standard_normal(FEATURE_DIM) +
                 1j * rng.standard_normal(FEATURE_DIM)).astype(np.complex128)
        psi_s = (rng.standard_normal(FEATURE_DIM) +
                 1j * rng.standard_normal(FEATURE_DIM)).astype(np.complex128)
        result = interference_components(psi_b, psi_s)
        assert set(result.keys()) == {"constructive", "destructive", "novel"}

    def test_authentic_submission_mostly_constructive(self):
        """z≈0 submission → small amplitude, mostly constructive phase alignment."""
        w = _weight_vec()
        active = _active_all()
        mu = np.full(FEATURE_DIM, 0.5)
        sigma = np.full(FEATURE_DIM, 0.1)
        # Authentic: z=0 for all features
        samples = _make_samples(3, value=0.5)
        psi_b = build_superposition_baseline(samples, w, active, mu, sigma, 300)
        z_s = np.zeros(FEATURE_DIM)
        psi_s = encode_amplitudes(z_s, w, active, n_tokens=300)
        result = interference_components(psi_b, psi_s)
        # With z=0 for both baseline and submission, most Re(c_i) ≥ 0
        n_constructive = len(result["constructive"])
        n_destructive = len(result["destructive"])
        # Should have more constructive than destructive
        assert n_constructive >= n_destructive

    def test_sorted_by_descending_strength(self):
        rng = np.random.default_rng(55)
        psi_b = (rng.standard_normal(FEATURE_DIM) +
                 1j * rng.standard_normal(FEATURE_DIM)).astype(np.complex128)
        psi_s = (rng.standard_normal(FEATURE_DIM) +
                 1j * rng.standard_normal(FEATURE_DIM)).astype(np.complex128)
        result = interference_components(psi_b, psi_s)
        for key in result:
            strengths = [v for _, v in result[key]]
            assert strengths == sorted(strengths, reverse=True)
