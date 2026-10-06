"""StudentState.remove_sample: the professor can take an approved exam back
out of a student's baseline (plan Phase 7). The profile afterwards must be
exactly the one built from the remaining samples."""

from __future__ import annotations

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState


def _samples(n: int) -> list[BaselineSample]:
    rng = np.random.default_rng(7)
    return [
        BaselineSample(
            text=f"sample {i}",
            vector=rng.uniform(0.1, 0.9, FEATURE_DIM),
            provenance="proctored",
            auth_weight=1.0,
        )
        for i in range(n)
    ]


def test_removing_a_sample_matches_a_profile_built_without_it():
    s = _samples(4)
    state = StudentState(student_id="t:a", samples=list(s))
    # Fill every cache first, so a missed invalidation would show.
    _ = (state.density_matrix, state.purity, state.trajectory, state.loo_distances)
    # Set drift counter and vectorizer to non-default values.
    state._consecutive_drift_count = 2
    state._tfidf_vectorizer = object()

    removed = state.remove_sample(1)

    assert removed is s[1]
    fresh = StudentState(student_id="t:a", samples=[s[0], s[2], s[3]])
    np.testing.assert_allclose(state.density_matrix, fresh.density_matrix)
    assert state.purity == pytest.approx(fresh.purity)
    np.testing.assert_allclose(state.baseline_mean, fresh.baseline_mean)
    np.testing.assert_allclose(state.baseline_std, fresh.baseline_std)
    assert state.loo_distances == pytest.approx(fresh.loo_distances)
    assert state.trajectory.confidence == pytest.approx(fresh.trajectory.confidence)
    # Verify drift counter and vectorizer are reset.
    assert state._consecutive_drift_count == 0
    assert not hasattr(state, "_tfidf_vectorizer")
    assert state.sample_count == 3


def test_removing_a_missing_index_raises():
    state = StudentState(student_id="t:a", samples=_samples(1))
    with pytest.raises(IndexError):
        state.remove_sample(5)


def test_removing_an_unverified_sample_from_mixed_baseline():
    """Removing an unverified (auth_weight=0) sample from a mixed baseline."""
    rng = np.random.default_rng(42)
    proctored_1 = BaselineSample(
        text="proctored 0",
        vector=rng.uniform(0.1, 0.9, FEATURE_DIM),
        provenance="proctored",
        auth_weight=1.0,
    )
    unverified = BaselineSample(
        text="unverified sample",
        vector=rng.uniform(0.1, 0.9, FEATURE_DIM),
        provenance="unverified",
        auth_weight=0.0,
    )
    proctored_2 = BaselineSample(
        text="proctored 1",
        vector=rng.uniform(0.1, 0.9, FEATURE_DIM),
        provenance="proctored",
        auth_weight=1.0,
    )
    state = StudentState(student_id="t:b", samples=[proctored_1, unverified, proctored_2])
    # Fill cache before removal
    _ = (state.density_matrix, state.active_feature_mask)

    removed = state.remove_sample(1)

    # Fresh state built without the unverified sample
    fresh = StudentState(student_id="t:b", samples=[proctored_1, proctored_2])
    assert removed.auth_weight == 0.0
    np.testing.assert_array_equal(state.active_feature_mask, fresh.active_feature_mask)
    np.testing.assert_allclose(state.density_matrix, fresh.density_matrix)
