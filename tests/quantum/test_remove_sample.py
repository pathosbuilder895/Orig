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

    removed = state.remove_sample(1)

    assert removed is s[1]
    fresh = StudentState(student_id="t:a", samples=[s[0], s[2], s[3]])
    np.testing.assert_allclose(state.density_matrix, fresh.density_matrix)
    assert state.purity == pytest.approx(fresh.purity)
    np.testing.assert_allclose(state.baseline_mean, fresh.baseline_mean)
    np.testing.assert_allclose(state.baseline_std, fresh.baseline_std)
    assert state.loo_distances == pytest.approx(fresh.loo_distances)
    assert state.sample_count == 3


def test_removing_a_missing_index_raises():
    state = StudentState(student_id="t:a", samples=_samples(1))
    with pytest.raises(IndexError):
        state.remove_sample(5)
