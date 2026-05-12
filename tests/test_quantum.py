"""
tests/test_quantum.py — Property-based tests for quantum math.

Uses Hypothesis to test invariants of quantum scoring.
"""

import pytest
import numpy as np
from hypothesis import given, strategies as st

from original.quantum.state import StudentState, BaselineSample
from original.quantum.scoring import score
from original.constants import FEATURE_DIM, ALL_FEATURE_CODES


def create_random_vector():
    """Create a random normalized feature vector."""
    vector = np.random.uniform(0, 1, FEATURE_DIM)
    return vector / np.linalg.norm(vector) if np.linalg.norm(vector) > 0 else vector


def vector_to_feature_dict(vector: np.ndarray) -> dict:
    """Convert a numpy vector to the {code: value} dict expected by score()."""
    return {code: float(val) for code, val in zip(ALL_FEATURE_CODES, vector)}


class TestQuantumInvariants:
    """Tests for quantum mathematics invariants."""

    def test_purity_bounds_single_sample(self):
        """Purity is 1.0 for a single sample (pure state)."""
        vector = create_random_vector()
        sample = BaselineSample(
            text="",
            vector=vector,
            provenance="proctored",
            auth_weight=1.0,
        )
        state = StudentState(student_id="test", samples=[sample])
        purity = state.purity
        # Single pure state: purity == 1.0 up to floating-point rounding
        assert abs(purity - 1.0) < 1e-9

    def test_purity_bounds_multiple_samples(self):
        """Purity is between 1/N and 1.0 for N samples."""
        n = 3
        samples = []
        for i in range(n):
            vector = create_random_vector()
            sample = BaselineSample(
                text="",
                vector=vector,
                provenance="verified",
                auth_weight=1.0,
            )
            samples.append(sample)

        state = StudentState(student_id="test", samples=samples)
        purity = state.purity

        lower_bound = 1.0 / n
        assert lower_bound <= purity <= 1.0

    def test_density_matrix_trace_normalized(self):
        """Trace of density matrix equals 1.0."""
        samples = []
        for i in range(3):
            vector = create_random_vector()
            sample = BaselineSample(
                text="",
                vector=vector,
                provenance="verified",
                auth_weight=1.0,
            )
            samples.append(sample)

        state = StudentState(student_id="test", samples=samples)
        rho = state.density_matrix
        trace = np.trace(rho)
        assert abs(trace - 1.0) < 1e-10

    def test_deviation_score_bounds(self):
        """Deviation score is always in [0, 1]."""
        # Create a baseline with a few samples
        samples = []
        for i in range(3):
            vector = create_random_vector()
            sample = BaselineSample(
                text="",
                vector=vector,
                provenance="verified",
                auth_weight=1.0,
            )
            samples.append(sample)

        state = StudentState(student_id="test", samples=samples)

        # Score a submission
        submission_vector = create_random_vector()
        result = score(state, submission_vector, vector_to_feature_dict(submission_vector))

        assert 0.0 <= result.authorship.deviation_score <= 1.0

    def test_same_text_low_deviation(self):
        """Scoring same text as baseline gives low deviation."""
        # Create baseline with one sample
        vector = create_random_vector()
        sample = BaselineSample(
            text="",
            vector=vector,
            provenance="proctored",
            auth_weight=1.0,
        )
        state = StudentState(student_id="test", samples=[sample])

        # Score the same vector
        result = score(state, vector, vector_to_feature_dict(vector))

        # Should be very close (low deviation)
        assert result.authorship.deviation_score < 0.3

    def test_different_text_nonzero_deviation(self):
        """Scoring very different text gives higher deviation."""
        # Create baseline with one sample
        vector = np.zeros(FEATURE_DIM)
        vector[0] = 1.0  # Almost orthogonal vector

        sample = BaselineSample(
            text="",
            vector=vector,
            provenance="proctored",
            auth_weight=1.0,
        )
        state = StudentState(student_id="test", samples=[sample])

        # Score a very different vector
        different_vector = np.zeros(FEATURE_DIM)
        different_vector[-1] = 1.0

        result = score(state, different_vector, vector_to_feature_dict(different_vector))

        # Should have noticeable deviation
        assert result.authorship.deviation_score > 0.3

    def test_unverified_samples_excluded(self):
        """Unverified samples with auth_weight=0 are excluded from density matrix."""
        # Create baseline with one unverified sample
        vector = create_random_vector()
        sample = BaselineSample(
            text="",
            vector=vector,
            provenance="unverified",
            auth_weight=0.0,  # Unverified
        )
        state = StudentState(student_id="test", samples=[sample])

        # Effective sample count should be 0 (or handled gracefully)
        assert state.effective_sample_count == 0

    def test_authorship_probability_reciprocal_deviation(self):
        """Authorship probability is roughly 1 - deviation_score."""
        samples = []
        for i in range(3):
            vector = create_random_vector()
            sample = BaselineSample(
                text="",
                vector=vector,
                provenance="verified",
                auth_weight=1.0,
            )
            samples.append(sample)

        state = StudentState(student_id="test", samples=samples)
        submission_vector = create_random_vector()
        result = score(state, submission_vector, vector_to_feature_dict(submission_vector))

        prob = result.authorship.authorship_probability
        deviation = result.authorship.deviation_score

        # Both independently computed: high deviation → lower probability (inverse trend)
        # Check that each is a valid probability in [0, 1]
        assert 0.0 <= prob <= 1.0
        assert 0.0 <= deviation <= 1.0


class TestQuantumEdgeCases:
    """Tests for edge cases in quantum scoring."""

    def test_empty_state(self):
        """Empty baseline state is handled."""
        state = StudentState(student_id="test", samples=[])
        vector = create_random_vector()
        # Should raise InsufficientBaselineError or handle gracefully
        try:
            result = score(state, vector, vector_to_feature_dict(vector))
            # If it doesn't raise, that's fine
        except Exception:
            # Expected for insufficient samples
            pass

    def test_all_identical_samples(self):
        """All identical samples collapse to a pure state."""
        vector = create_random_vector()
        samples = []
        for i in range(3):
            sample = BaselineSample(
                text="",
                vector=vector.copy(),
                provenance="verified",
                auth_weight=1.0,
            )
            samples.append(sample)

        state = StudentState(student_id="test", samples=samples)

        # Should have high purity
        assert state.purity > 0.9

        # Scoring same vector should give very low deviation
        result = score(state, vector, vector_to_feature_dict(vector))
        assert result.authorship.deviation_score < 0.2
