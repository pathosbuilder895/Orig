"""
Genre-prior blend weight must scale with how well-estimated the prior is.

score() blends the student's own baseline toward the genre prior with
    mu_eff = a*mu_student + (1-a)*mu_prior,  a = N/(N + w)
and w was a flat `prior_weight` regardless of pool size. That treats a prior
estimated from 3 peers as carrying exactly the same authority as one estimated
from 300 — at N=1 baseline sample, 75% of the reference mean either way. A
prior mean is itself an estimate; ignoring its sampling error imports peer
noise fastest at exactly the pool sizes where it is least trustworthy.

w is now damped by the pool's distinct-student count, so the prior earns
influence as the cohort grows and converges on the old behaviour for large
pools.
"""

from __future__ import annotations

import numpy as np

from original.constants import FEATURE_DIM
from original.quantum.scoring import ScoringConfig, score
from original.quantum.state import BaselineSample, StudentState

GENRE = "sermon"


def _cold_start_state(n: int = 1) -> StudentState:
    rng = np.random.default_rng(3)
    state = StudentState(student_id="damp:student")
    for i in range(n):
        state.add_sample(
            BaselineSample(
                text=f"baseline {i}",
                vector=np.full(FEATURE_DIM, 0.30),
                provenance="instructor_verified",
                auth_weight=1.0,
                assignment=f"a{i}",
                genre=GENRE,
            )
        )
    assert rng is not None
    return state


def _prior(n_students: int) -> dict:
    """A prior whose mean is far from the student's, so the blend is visible."""
    return {
        "mean": np.full(FEATURE_DIM, 0.80),
        "std": np.full(FEATURE_DIM, 0.10),
        "n_samples": n_students * 2,
        "n_students": n_students,
    }


def _config(prior: dict | None) -> ScoringConfig:
    return ScoringConfig(bayesian_prior_enabled=True, prior_weight=3.0, genre_stats=prior)


def _score_with(prior: dict | None) -> float:
    state = _cold_start_state()
    submission = np.full(FEATURE_DIM, 0.30)  # identical to the baseline
    return score(
        state=state,
        submission_vector=submission,
        feature_dict={},
        scoring_config=_config(prior),
    ).authorship.deviation_score


def test_small_pool_moves_the_score_less_than_a_large_pool():
    # The submission matches the student's baseline exactly, so ALL deviation
    # here comes from the prior dragging mu away from the student. A 3-student
    # pool must drag it less than a 50-student one.
    small = _score_with(_prior(3))
    large = _score_with(_prior(50))
    assert small < large, (
        f"3-student prior moved the score {small:.4f}, 50-student moved it "
        f"{large:.4f} — the blend weight is not damped by pool size"
    )


def test_damping_is_strictly_monotone_in_pool_size():
    # STRICTLY increasing, not merely sorted: without damping every score is
    # identical, and a constant list is trivially sorted — the weaker
    # assertion would pass against the very bug this file exists to catch.
    scores = [_score_with(_prior(n)) for n in (3, 5, 10, 30, 100)]
    assert all(a < b for a, b in zip(scores, scores[1:])), (
        f"not strictly increasing in pool size: {scores}"
    )


def test_large_pool_approaches_the_undamped_blend():
    # Damping must vanish asymptotically, not permanently discount the prior.
    huge = _score_with(_prior(100_000))
    undamped = _score_with({**_prior(10), "n_students": None})
    assert abs(huge - undamped) < 1e-6, (
        f"large-pool damped score {huge:.6f} should converge on the undamped "
        f"blend {undamped:.6f}"
    )


def test_absent_n_students_falls_back_to_undamped():
    # Older/hand-built genre_stats dicts have no n_students key. That must not
    # raise, and must reproduce the pre-damping blend.
    legacy = {k: v for k, v in _prior(10).items() if k != "n_students"}
    assert _score_with(legacy) == _score_with({**_prior(10), "n_students": None})


def test_no_prior_still_scores():
    # Sanity: the prior is optional; its absence is the documented fallback.
    assert _score_with(None) >= 0.0
