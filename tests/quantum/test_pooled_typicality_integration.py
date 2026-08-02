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


def _make_state(student_id: str, n_samples: int, seed: int) -> StudentState:
    """A StudentState with ``n_samples`` proctored baseline samples, enough
    to give ``loo_distances`` a real (non-trivial) length."""
    rng = np.random.default_rng(seed)
    samples = [
        BaselineSample(
            text="",
            vector=rng.uniform(0.3, 0.7, FEATURE_DIM),
            provenance="proctored",
            auth_weight=1.0,
        )
        for _ in range(n_samples)
    ]
    return StudentState(student_id=student_id, samples=samples)


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


# ── End-to-end coverage: the pooled branch actually driven through score() ────
#
# The tests above exercise build_pooled_reference/p_far directly and the
# flag's defaults/byte-identical-when-off behaviour, but nothing here drove
# score() itself with a real pooled_states dict — a future refactor could
# silently break the wiring (score.py's `if config.typicality_pooled_calibration
# and pooled_states is not None:` block) with nothing catching it. These three
# tests close that gap by calling score() the same way a real caller would:
# real StudentState objects (built via _make_state, same BaselineSample
# convention as test_byte_identical_when_flag_off_or_unset above) assembled
# into a {student_id: StudentState} pooled_states dict, tenant-scoped ids
# ("tenant:student") so tenant_of()/DEMO_TENANT resolve the way
# collect_tenant_distances expects.
#
# All three use a submission_vector set to the TARGET's own baseline_mean.
# Since score() computes z = (sub_raw - state.baseline_mean) / state.baseline_std
# with sub_raw == submission_vector verbatim (scoring.py, no unit-normalisation
# for this branch), this makes z == 0 for every active feature and therefore
# rms_z == 0.0 exactly — a "too-perfect" submission that sits below every
# leave-one-out distance in any reference built from real (non-degenerate)
# random baselines. That drives the p_central ("too consistent to be genuine")
# tail down to its reachable floor 1/(N+1), giving deterministic, seed-
# independent assertions about which band is reached without needing to
# hand-tune rms_z against a specific reference distribution.


def test_pooled_calibration_reaches_band_unreachable_by_self():
    """A same-tenant pool with 4 peers x 20 samples (80 total, four
    students) clears build_pooled_reference's default min_students=3 /
    min_total=30 and reaches typicality_calibration == "pooled" with
    typicality_n reflecting the pooled count, not the target's own tiny
    LOO count. The reached band ("schedule_conversation", via the
    too-perfect/central tail) is unreachable under self-calibration alone
    at the target's own N=3 (floor 1/4 = 0.25, far above every band
    threshold in typicality.py) — demonstrating the reachability gain
    pooling exists for."""
    target_id = "tenantA:target"
    target = _make_state(target_id, n_samples=3, seed=101)

    peers = {
        (sid := f"tenantA:peer{i}"): _make_state(sid, n_samples=20, seed=200 + i)
        for i in range(4)
    }
    # Real callers assemble every student in the tenant pool, including the
    # one being scored; collect_tenant_distances is responsible for
    # excluding the target via exclude_sid, not the caller.
    pooled_states = {target_id: target, **peers}

    submission_vector = target.baseline_mean
    feature_dict = _feature_dict(submission_vector)
    cfg = ScoringConfig(typicality_scoring_enabled=True, typicality_pooled_calibration=True)

    pooled_out = score(
        state=target,
        submission_vector=submission_vector,
        feature_dict=feature_dict,
        scoring_config=cfg,
        pooled_states=pooled_states,
        student_id=target_id,
    )

    assert pooled_out.typicality_calibration == "pooled"
    assert pooled_out.typicality_n == 80  # 4 peers x 20 contributing samples, target excluded
    assert pooled_out.typicality_band == "schedule_conversation"

    # Same target, same submission, self-calibration only (no pool) — the
    # band above must be unreachable this way, not merely "different".
    self_out = score(
        state=target,
        submission_vector=submission_vector,
        feature_dict=feature_dict,
        scoring_config=ScoringConfig(typicality_scoring_enabled=True, typicality_pooled_calibration=False),
    )
    assert self_out.typicality_calibration == "self"
    assert self_out.typicality_n == len(target.loo_distances) == 3
    assert self_out.typicality_band == "no_action"


def test_pooled_calibration_falls_back_to_self_when_pool_too_thin():
    """Only 2 same-tenant peers — below build_pooled_reference's
    min_students=3 default — must fall back to self-calibration exactly as
    if pooling were never attempted, not to a confident-looking pooled
    number built on too little data."""
    target_id = "tenantA:target-thin"
    target = _make_state(target_id, n_samples=3, seed=301)

    peers = {
        (sid := f"tenantA:peer-thin{i}"): _make_state(sid, n_samples=5, seed=400 + i)
        for i in range(2)  # 2 students < min_students=3
    }
    pooled_states = {target_id: target, **peers}

    submission_vector = target.baseline_mean
    feature_dict = _feature_dict(submission_vector)
    cfg = ScoringConfig(typicality_scoring_enabled=True, typicality_pooled_calibration=True)

    out = score(
        state=target,
        submission_vector=submission_vector,
        feature_dict=feature_dict,
        scoring_config=cfg,
        pooled_states=pooled_states,
        student_id=target_id,
    )

    assert out.typicality_calibration == "self"
    assert out.typicality_n == len(target.loo_distances) == 3


def test_pooled_calibration_falls_back_to_self_when_only_cross_tenant_peers():
    """pooled_states populated entirely by a DIFFERENT tenant's students —
    collect_tenant_distances must exclude all of them (tenant_of mismatch),
    leaving build_pooled_reference an empty list, so this falls back to
    self exactly like the too-thin case, even though the cross-tenant pool
    alone would easily clear min_students/min_total if it were (wrongly)
    allowed to mix tenants."""
    target_id = "tenantA:target-xtenant"
    target = _make_state(target_id, n_samples=3, seed=501)

    # Same shape as the successful pool in the first test (4 x 20 = 80,
    # comfortably over min_students/min_total) but in a different tenant.
    peers = {
        (sid := f"tenantB:peer{i}"): _make_state(sid, n_samples=20, seed=600 + i)
        for i in range(4)
    }
    pooled_states = {target_id: target, **peers}

    submission_vector = target.baseline_mean
    feature_dict = _feature_dict(submission_vector)
    cfg = ScoringConfig(typicality_scoring_enabled=True, typicality_pooled_calibration=True)

    out = score(
        state=target,
        submission_vector=submission_vector,
        feature_dict=feature_dict,
        scoring_config=cfg,
        pooled_states=pooled_states,
        student_id=target_id,
    )

    assert out.typicality_calibration == "self"
    assert out.typicality_n == len(target.loo_distances) == 3
