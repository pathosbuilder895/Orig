"""Reference selection: deterministic, tenant-isolated, self-excluding, floored."""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.fusion import peers
from original.quantum.state import BaselineSample, StudentState

_LONG = (
    "However, a reader might ask why these claims have been made; therefore we reply "
    "that the argument is careful and that it is also sound. "
) * 40  # ~1000 words

# Distinct content from _LONG so the claimed student's Profile.text can never
# collide with a peer's, no matter which peer text/sample-count variant is in
# play in a given test.
_ALICE_TEXT = (
    "Meanwhile, a skeptic might wonder whether the premises hold; nevertheless we "
    "answer that the reasoning is patient and that it is also thorough. "
) * 40  # ~1000 words, different vocabulary from _LONG


def _order_key(student_id: str) -> str:
    """Mirrors peers._order_key so tests can reason about selection order
    without depending on the private helper directly."""
    return hashlib.sha256(student_id.encode("utf-8")).hexdigest()


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
    # The claimed student gets unique text (_ALICE_TEXT, not the peers'
    # _LONG) so their Profile is genuinely distinguishable from every peer's
    # — not just by an incidental count. Every candidate is also placed so
    # its order key sorts *after* the claimed student's: if self-exclusion
    # were ever removed, the claimed student would sort first and be
    # guaranteed a spot among the 8 selected, making this assertion catch
    # the regression deterministically rather than by chance.
    claimed_id = "t1:alice"
    claimed = _state(claimed_id, words=_ALICE_TEXT)
    claimed_key = _order_key(claimed_id)
    peer_ids = []
    i = 0
    while len(peer_ids) < 12:
        candidate_id = f"t1:peer{i}"
        if _order_key(candidate_id) > claimed_key:
            peer_ids.append(candidate_id)
        i += 1
    cohort = [claimed] + [_state(pid) for pid in peer_ids]

    selected = peers.select_references(claimed, cohort)
    assert len(selected) == 8

    claimed_profile = peers.build_profile(claimed)
    assert claimed_profile is not None
    # No selected reference is actually the claimed student's own profile.
    assert all(profile.text != claimed_profile.text for profile in selected)


def test_selection_never_crosses_a_tenant_boundary():
    claimed = _state("t1:alice")
    cohort = [claimed] + [_state(f"t2:peer{i}") for i in range(20)]
    assert peers.select_references(claimed, cohort) == []


def test_selection_is_deterministic_across_input_order():
    # Each peer gets a distinct sample_count (3, 4, 5, ...), so sample_count
    # uniquely identifies which peer a given Profile came from. Comparing
    # the forward and reversed sample_count lists element-by-element proves
    # the same peers were picked in the same order, not just that both runs
    # picked *some* 8-of-20 subset with matching aggregate stats.
    claimed = _state("t1:alice")
    cohort = [_state(f"t1:peer{i}", samples=3 + i) for i in range(20)]
    forward = peers.select_references(claimed, [claimed] + cohort)
    peers.reset_cache_for_tests()
    backward = peers.select_references(claimed, list(reversed(cohort)) + [claimed])

    assert len(forward) == 8
    forward_peer_ids = [p.sample_count for p in forward]
    backward_peer_ids = [p.sample_count for p in backward]
    assert len(set(forward_peer_ids)) == 8  # sanity: sample_count really is unique per peer here
    assert backward_peer_ids == forward_peer_ids


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
