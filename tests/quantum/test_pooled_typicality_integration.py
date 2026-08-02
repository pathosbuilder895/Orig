import dataclasses
import os

import numpy as np
import pytest

from original.constants import ALL_FEATURE_CODES, FEATURE_DIM
from original.quantum.scoring import ScoringConfig, score
from original.quantum.state import BaselineSample, StudentState


def test_flag_defaults_off():
    cfg = ScoringConfig.from_env()
    assert cfg.typicality_pooled_calibration is False


def test_flag_reads_env(monkeypatch):
    monkeypatch.setenv("TYPICALITY_POOLED_CALIBRATION", "1")
    assert ScoringConfig.from_env().typicality_pooled_calibration is True


def test_pooled_mode_reaches_bands_that_self_mode_cannot():
    """The whole point: with 8 own samples the floor is 1/9=0.111 and no
    band is reachable; against a 200-sample pooled reference the floor is
    0.005 and every band is."""
    from original.quantum.typicality import p_far, SCHEDULE_FAR_THRESHOLD

    own = np.linspace(0.5, 1.5, 8)
    pooled = np.linspace(0.5, 1.5, 200)
    extreme = 99.0

    assert p_far(extreme, own) > SCHEDULE_FAR_THRESHOLD      # unreachable
    assert p_far(extreme, pooled) <= SCHEDULE_FAR_THRESHOLD  # reachable


def test_falls_back_to_self_when_reference_too_thin():
    """A thin population must degrade to self-calibration, never to a
    confident p-value against a reference that cannot support one."""
    from original.quantum.pooled_calibration import build_pooled_reference

    assert build_pooled_reference([np.array([1.0, 1.1])], min_students=3) is None


def _vec():
    rng = np.random.default_rng(20260731)
    return rng.uniform(0.3, 0.7, FEATURE_DIM)


def _feature_dict(vector):
    return {code: float(v) for code, v in zip(ALL_FEATURE_CODES, vector)}


def test_byte_identical_when_flag_off_or_unset(monkeypatch):
    """Non-negotiable Phase-1 guarantee: with TYPICALITY_POOLED_CALIBRATION
    unset, or explicitly "0", score() must reproduce EXACTLY what the
    pre-this-task code produced — i.e. calling score() with none of the new
    pooled_states/student_id/typicality_pooled_calibration inputs at all.
    typicality_calibration is a brand-new field with no pre-task counterpart,
    so it alone is excused from the comparison (and asserted None on its own).
    """
    rng = np.random.default_rng(20260731)
    samples = [
        BaselineSample(
            text="", vector=rng.uniform(0.3, 0.7, FEATURE_DIM), provenance="proctored", auth_weight=1.0
        )
        for _ in range(6)
    ]
    state = StudentState(student_id="byte-identical-test", samples=samples)
    sub_vector = rng.uniform(0.3, 0.7, FEATURE_DIM)
    feature_dict = _feature_dict(sub_vector)

    # Pre-task-equivalent call: no scoring_config, no pooled_states, no student_id.
    baseline = score(state=state, submission_vector=sub_vector, feature_dict=feature_dict)

    monkeypatch.delenv("TYPICALITY_POOLED_CALIBRATION", raising=False)
    run_unset = score(
        state=state,
        submission_vector=sub_vector,
        feature_dict=feature_dict,
        scoring_config=ScoringConfig.from_env(),
    )

    monkeypatch.setenv("TYPICALITY_POOLED_CALIBRATION", "0")
    run_zero = score(
        state=state,
        submission_vector=sub_vector,
        feature_dict=feature_dict,
        scoring_config=ScoringConfig.from_env(),
    )

    d_baseline = dataclasses.asdict(baseline)
    d_baseline.pop("typicality_calibration", None)

    for other, label in [(run_unset, "env-unset"), (run_zero, "env-explicit-0")]:
        assert other.typicality_calibration is None, label
        d_other = dataclasses.asdict(other)
        d_other.pop("typicality_calibration", None)
        assert d_other == d_baseline, f"byte-identical guarantee violated for {label}"
