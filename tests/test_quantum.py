"""
tests/test_quantum.py — Property-based tests for quantum math.

Uses Hypothesis (one genuine `@given` property, see
``test_density_matrix_trace_bounds_property``) plus deterministic,
seeded example-based tests for the remaining invariants of quantum scoring.
"""

import pytest
import numpy as np
from hypothesis import given, settings, strategies as st

from original.quantum.state import StudentState, BaselineSample
from original.quantum.scoring import score
from original.constants import FEATURE_DIM, ALL_FEATURE_CODES

# Fixed seed so every threshold-based assertion in this module is deterministic
# across runs. Do not reseed inside individual tests — reuse this RNG.
_RNG = np.random.default_rng(20260707)


def create_random_vector():
    """Create a seeded, deterministic random normalized feature vector."""
    vector = _RNG.uniform(0, 1, FEATURE_DIM)
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

    # deadline=None: building StudentState/density-matrix per example is
    # numpy-heavy and machine-speed dependent; a wall-clock deadline here
    # would make the test flaky on slower CI runners for reasons unrelated
    # to the invariant under test.
    @settings(deadline=None)
    @given(
        vectors=st.lists(
            st.lists(
                # Lower bound of 1e-3 (rather than 0.0) keeps generated
                # vectors safely away from subnormal-float norms, which
                # blow up numerically on unit-normalization and are
                # irrelevant to the trace/purity invariant under test.
                st.floats(
                    min_value=1e-3,
                    max_value=1.0,
                    allow_nan=False,
                    allow_infinity=False,
                ),
                min_size=FEATURE_DIM,
                max_size=FEATURE_DIM,
            ),
            min_size=1,
            max_size=5,
        )
    )
    def test_density_matrix_trace_bounds_property(self, vectors):
        """Property: for any 1-5 baseline samples, tr(rho) == 1 and purity in [1/N, 1].

        Genuine Hypothesis property test (the module docstring's claim):
        strategy-generates between 1 and 5 raw FEATURE_DIM-length feature
        vectors (each component bounded away from zero/subnormal magnitudes
        so unit-normalization is well-conditioned) and checks the
        trace-normalization and purity-bounds invariants hold for every
        generated baseline, not just a single hand-picked example.
        """
        samples = []
        for raw in vectors:
            arr = np.array(raw, dtype=np.float64)
            norm = np.linalg.norm(arr)
            unit_vec = arr / norm if norm > 0 else arr
            samples.append(
                BaselineSample(
                    text="",
                    vector=unit_vec,
                    provenance="verified",
                    auth_weight=1.0,
                )
            )

        state = StudentState(student_id="test", samples=samples)
        rho = state.density_matrix

        # Trace normalization: tr(rho) == 1 regardless of N or vector content.
        trace = np.trace(rho)
        assert abs(trace - 1.0) < 1e-8

        # Purity bounds: 1/N <= purity <= 1 for N contributing samples.
        n = len(samples)
        purity = state.purity
        assert (1.0 / n) - 1e-8 <= purity <= 1.0 + 1e-8

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
        """authorship_probability and deviation_score move in opposite directions.

        Builds one baseline, then scores a near-baseline submission (the
        baseline vector itself) against a far-from-baseline submission
        (a near-orthogonal vector) and asserts the ordering the two
        signals are supposed to have: the near submission has lower
        deviation *and* higher authorship_probability than the far one.
        """
        baseline_vector = create_random_vector()
        sample = BaselineSample(
            text="",
            vector=baseline_vector,
            provenance="verified",
            auth_weight=1.0,
        )
        state = StudentState(student_id="test", samples=[sample])

        # Near-baseline submission: the baseline vector itself.
        near_result = score(
            state, baseline_vector, vector_to_feature_dict(baseline_vector)
        )

        # Far-from-baseline submission: construct a vector orthogonal to the
        # baseline by zeroing its largest-magnitude component and putting all
        # mass on a component the baseline is weakest in.
        far_vector = np.zeros(FEATURE_DIM)
        far_vector[np.argmin(np.abs(baseline_vector))] = 1.0
        far_result = score(state, far_vector, vector_to_feature_dict(far_vector))

        near_prob = near_result.authorship.authorship_probability
        near_dev = near_result.authorship.deviation_score
        far_prob = far_result.authorship.authorship_probability
        far_dev = far_result.authorship.deviation_score

        for p in (near_prob, far_prob):
            assert 0.0 <= p <= 1.0
        for d in (near_dev, far_dev):
            assert 0.0 <= d <= 1.0

        # The claimed inverse relationship: near submission has lower
        # deviation and higher authorship probability than the far one.
        assert near_dev < far_dev
        assert near_prob > far_prob


class TestQuantumEdgeCases:
    """Tests for edge cases in quantum scoring."""

    def test_empty_state(self):
        """Empty baseline state is handled gracefully, not by raising.

        Confirmed against the real implementation: `quantum/state.py`'s
        ``_build_density_matrix`` explicitly falls back to the maximally
        mixed uniform prior (identity/FEATURE_DIM) when there are zero
        contributing samples (see the ``N == 0`` branch), and
        `quantum/scoring.py`'s `score()` does not raise for this case —
        it scores against that uniform prior. `InsufficientBaselineError`
        (`original/core/exceptions.py`) exists but is only raised by the
        dormant v1 API layer (`original/api/v1/submissions.py:457`), not by
        this quantum module. So the real contract here is: no exception,
        and the resulting signal reflects "no real baseline yet" via
        effective_sample_count == 0 and a maximally-mixed density matrix.
        """
        state = StudentState(student_id="test", samples=[])
        vector = create_random_vector()

        result = score(state, vector, vector_to_feature_dict(vector))

        assert state.effective_sample_count == 0
        assert result.baseline_confidence.sample_count == 0
        assert result.baseline_confidence.effective_sample_count == 0.0
        # Uniform prior: purity of identity/D is exactly 1/D.
        assert abs(state.purity - (1.0 / FEATURE_DIM)) < 1e-9
        assert 0.0 <= result.authorship.deviation_score <= 1.0
        assert 0.0 <= result.authorship.authorship_probability <= 1.0

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
