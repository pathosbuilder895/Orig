"""Reference selection: deterministic, tenant-isolated, self-excluding, floored."""

from __future__ import annotations

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.fusion import peers
from original.quantum.state import BaselineSample, StudentState

_LONG = (
    "However, a reader might ask why these claims have been made; therefore we reply "
    "that the argument is careful and that it is also sound. "
) * 40  # ~1000 words


def _state(student_id: str, *, samples: int = 3, words: str = _LONG) -> StudentState:
    state = StudentState(student_id=student_id)
    rng = np.random.default_rng(abs(hash(student_id)) % (2**32))
    for index in range(samples):
        state.add_sample(
            BaselineSample(
                text=words,
                vector=rng.uniform(0.3, 0.7, FEATURE_DIM),
                provenance="proctored",
                auth_weight=1.0,
                assignment=f"{student_id}-{index}",
            )
        )
    return state


@pytest.fixture(autouse=True)
def _clear_cache():
    peers.reset_cache_for_tests()
    yield
    peers.reset_cache_for_tests()


def test_build_profile_returns_none_below_baseline_floor():
    assert peers.build_profile(_state("t1:alice", samples=2)) is None


def test_build_profile_returns_none_when_text_is_too_short():
    assert peers.build_profile(_state("t1:alice", words="too short")) is None


def test_build_profile_populates_every_field():
    profile = peers.build_profile(_state("t1:alice"))
    assert profile is not None
    assert profile.sample_count == 3
    assert profile.compressed_size > 0
    assert profile.baseline_mean.shape == (FEATURE_DIM,)
    assert profile.baseline_std.shape == (FEATURE_DIM,)
    assert float(np.linalg.norm(profile.fw_matrix)) == pytest.approx(1.0)


def test_selection_abstains_below_eight_eligible_peers():
    claimed = _state("t1:alice")
    cohort = [claimed] + [_state(f"t1:peer{i}") for i in range(7)]
    assert peers.select_references(claimed, cohort) == []


def test_selection_returns_exactly_eight_when_more_are_available():
    claimed = _state("t1:alice")
    cohort = [claimed] + [_state(f"t1:peer{i}") for i in range(20)]
    assert len(peers.select_references(claimed, cohort)) == peers.N_REFERENCES


def test_selection_never_includes_the_claimed_student():
    claimed = _state("t1:alice")
    cohort = [claimed] + [_state(f"t1:peer{i}") for i in range(12)]
    selected = peers.select_references(claimed, cohort)
    assert all(profile.text is not None for profile in selected)
    assert len(selected) == 8
    # Self-exclusion is observable through the cache: 8 peers built, not 9.
    assert peers.cache_build_count() == 8


def test_selection_never_crosses_a_tenant_boundary():
    claimed = _state("t1:alice")
    cohort = [claimed] + [_state(f"t2:peer{i}") for i in range(20)]
    assert peers.select_references(claimed, cohort) == []


def test_selection_is_deterministic_across_input_order():
    claimed = _state("t1:alice")
    cohort = [_state(f"t1:peer{i}") for i in range(20)]
    forward = peers.select_references(claimed, [claimed] + cohort)
    peers.reset_cache_for_tests()
    backward = peers.select_references(claimed, list(reversed(cohort)) + [claimed])
    assert [p.compressed_size for p in forward] == [p.compressed_size for p in backward]
    assert [p.sample_count for p in forward] == [p.sample_count for p in backward]


def test_profiles_are_cached_not_rebuilt():
    claimed = _state("t1:alice")
    cohort = [claimed] + [_state(f"t1:peer{i}") for i in range(12)]
    peers.select_references(claimed, cohort)
    first_builds = peers.cache_build_count()
    peers.select_references(claimed, cohort)
    assert peers.cache_build_count() == first_builds


def test_ineligible_peers_do_not_count_toward_the_floor():
    claimed = _state("t1:alice")
    cohort = [claimed] + [_state(f"t1:ok{i}") for i in range(5)]
    cohort += [_state(f"t1:short{i}", words="tiny") for i in range(10)]
    assert peers.select_references(claimed, cohort) == []
