"""
llr_action_mode: letting llr_deviation_score (NULL_MODEL=impostor) actually
change the recommended action, instead of only being attached for display.

Motivation: a 2026-08 leave-one-genre-out study (C.S. Lewis corpus, held out
by genre, vs a Chesterton impostor pool) found the raw deviation_score alone
WORSE than chance (mean AUC 0.39) at telling a genuine cross-genre submission
apart from a different author's writing, while llr_deviation_score alone
scored 0.86 on the same data. See validation/genre_crossgenre_2026-08/.

Two layers, matching tests/test_null_model.py's own split:
  1. Unit — _llr_action_candidates / _apply_llr_action_mode as pure functions
     of (action, deviation, llr_deviation_score, mode).
  2. Integration — score() with a real ScoringConfig.llr_action_mode actually
     changes Layer7Output.recommendation.action; "shadow" (the default)
     never does, preserving the existing attach-only contract.
"""

from __future__ import annotations

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.quantum.scoring import (
    LLR_ACTION_GENUINE_THRESHOLD,
    LLR_ACTION_IMPOSTOR_THRESHOLD,
    RecommendedAction,
    ScoringConfig,
    _apply_llr_action_mode,
    _llr_action_candidates,
    score,
)
from original.quantum.state import BaselineSample, StudentState

# ── Unit: _llr_action_candidates ──────────────────────────────────────────────


def test_gate_downgrades_one_step_on_confident_genuine_llr():
    candidates = _llr_action_candidates("escalate", deviation=0.90, llr_deviation_score=0.05)
    assert candidates["gate"] == "schedule_conversation"


def test_gate_never_upgrades():
    candidates = _llr_action_candidates("no_action", deviation=0.10, llr_deviation_score=0.95)
    assert candidates["gate"] == "no_action"


def test_gate_no_change_when_llr_is_neutral():
    candidates = _llr_action_candidates("escalate", deviation=0.90, llr_deviation_score=0.50)
    assert candidates["gate"] == "escalate"


def test_gate_floor_at_no_action():
    candidates = _llr_action_candidates("no_action", deviation=0.05, llr_deviation_score=0.01)
    assert candidates["gate"] == "no_action"


def test_trigger_upgrades_from_no_action_on_confident_impostor_llr():
    candidates = _llr_action_candidates("no_action", deviation=0.10, llr_deviation_score=0.95)
    assert candidates["trigger"] == "monitor"


def test_trigger_never_downgrades():
    candidates = _llr_action_candidates("escalate", deviation=0.90, llr_deviation_score=0.05)
    assert candidates["trigger"] == "escalate"


def test_trigger_only_fires_from_no_action():
    # Starting from "monitor" (not "no_action"), trigger must not fire even
    # with a maximally impostor-like llr — it only adds a first foothold of
    # sensitivity, never escalates further on its own.
    candidates = _llr_action_candidates("monitor", deviation=0.45, llr_deviation_score=0.99)
    assert candidates["trigger"] == "monitor"


def test_blend_re_derives_tier_from_combined_score():
    # deviation alone -> no_action (0.30 < 0.40); llr alone would be far into
    # "escalate" territory. Blended 0.5*0.30 + 0.5*0.90 = 0.60 -> schedule_conversation.
    candidates = _llr_action_candidates("no_action", deviation=0.30, llr_deviation_score=0.90)
    assert candidates["blend"] == "schedule_conversation"


def test_thresholds_are_symmetric_around_the_documented_midpoint():
    # AuthorshipSignal.llr_deviation_score docstring: 0.5 = "as consistent
    # with one as the other". The action thresholds must straddle it evenly.
    assert LLR_ACTION_GENUINE_THRESHOLD < 0.5 < LLR_ACTION_IMPOSTOR_THRESHOLD
    assert 0.5 - LLR_ACTION_GENUINE_THRESHOLD == pytest.approx(
        LLR_ACTION_IMPOSTOR_THRESHOLD - 0.5
    )


# ── Unit: _apply_llr_action_mode ──────────────────────────────────────────────


def _action(action: str) -> RecommendedAction:
    return RecommendedAction(action=action, confidence=0.8, rationale="baseline rationale.")


def test_shadow_mode_never_changes_the_recommendation():
    for action in ("no_action", "monitor", "schedule_conversation", "escalate"):
        for llr in (0.02, 0.5, 0.98):
            rec = _action(action)
            out = _apply_llr_action_mode(rec, deviation=0.5, llr_deviation_score=llr, mode="shadow")
            assert out is rec, f"shadow mode changed identity for action={action} llr={llr}"
            assert out.action == action


def test_gate_mode_changes_action_and_annotates_rationale():
    rec = _action("escalate")
    out = _apply_llr_action_mode(rec, deviation=0.90, llr_deviation_score=0.05, mode="gate")
    assert out.action == "schedule_conversation"
    assert "LLR gate" in out.rationale
    assert rec.rationale in out.rationale  # original rationale preserved, not replaced


def test_mode_is_a_noop_when_no_candidate_change():
    rec = _action("escalate")
    out = _apply_llr_action_mode(rec, deviation=0.90, llr_deviation_score=0.50, mode="gate")
    assert out is rec  # unchanged input returned as-is, not a rebuilt copy


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        _apply_llr_action_mode(_action("no_action"), deviation=0.1, llr_deviation_score=0.9, mode="bogus")


# ── Integration: score() actually threads llr_action_mode through ────────────

# Own baseline centred at 0.30 (n=1 -> baseline_std is the flat 0.15 prior).
# FAR / IMPOSTOR_* are empirically chosen (see git history for the search)
# so the raw deviation_score alone lands in "escalate" while the impostor
# pool is close enough to the submission that llr_deviation_score reads
# confidently "genuine" -- the exact genre-shift failure mode this study
# targets, reproduced with hand-picked vectors instead of real prose.
FAR = 0.55
IMPOSTOR_MEAN, IMPOSTOR_SIGMA = 0.90, 0.05


def _baseline_state(mean: float, n: int = 1) -> StudentState:
    # n=1 deliberately: active_feature_mask excludes any feature that's
    # constant across >=2 baseline samples (zero-variance -> unbounded
    # z-scores), so a >1-sample identical-vector baseline would silently
    # zero out every feature and make rms_z always 0 regardless of the
    # submission. A single sample keeps the mask at its "not enough data
    # yet" all-True default so these hand-picked vectors actually drive z.
    state = StudentState(student_id="llr_action:student")
    for i in range(n):
        state.add_sample(
            BaselineSample(
                text=f"baseline {i}",
                vector=np.full(FEATURE_DIM, mean),
                provenance="proctored",
                auth_weight=1.0,
                assignment=f"a{i}",
            )
        )
    return state


def test_default_config_is_shadow_and_leaves_action_untouched():
    # Own baseline tight at 0.30 (n=1 -> flat sigma=0.15); submission at FAR
    # (0.55) drives rms_z far enough for raw deviation alone to escalate.
    # Impostor pool centred close to the submission (0.90 +/- 0.05) so
    # rms_z_null << rms_z -> llr says "genuine" (confidently low). Default
    # llr_action_mode="shadow" must NOT change the resulting action.
    state = _baseline_state(0.30)
    submission = np.full(FEATURE_DIM, FAR)
    impostor_stats = (np.full(FEATURE_DIM, IMPOSTOR_MEAN), np.full(FEATURE_DIM, IMPOSTOR_SIGMA))

    config = ScoringConfig(null_model="impostor")  # llr_action_mode defaults to "shadow"
    result = score(
        state=state,
        submission_vector=submission,
        feature_dict={},
        impostor_stats=impostor_stats,
        scoring_config=config,
    )
    assert result.authorship.llr_deviation_score is not None
    assert result.authorship.llr_deviation_score < LLR_ACTION_GENUINE_THRESHOLD, (
        "test setup should produce a confidently-genuine llr_deviation_score"
    )
    baseline_action = result.recommendation.action

    # Same scenario but without null_model=impostor at all -- must match,
    # proving shadow mode really is a no-op end to end.
    off = score(
        state=_baseline_state(0.30),
        submission_vector=submission,
        feature_dict={},
        scoring_config=ScoringConfig(),
    )
    assert off.recommendation.action == baseline_action


def test_gate_mode_softens_a_genre_driven_false_positive_end_to_end():
    state = _baseline_state(0.30)
    submission = np.full(FEATURE_DIM, FAR)
    impostor_stats = (np.full(FEATURE_DIM, IMPOSTOR_MEAN), np.full(FEATURE_DIM, IMPOSTOR_SIGMA))

    shadow_result = score(
        state=_baseline_state(0.30),
        submission_vector=submission,
        feature_dict={},
        impostor_stats=impostor_stats,
        scoring_config=ScoringConfig(null_model="impostor", llr_action_mode="shadow"),
    )
    gated_result = score(
        state=state,
        submission_vector=submission,
        feature_dict={},
        impostor_stats=impostor_stats,
        scoring_config=ScoringConfig(null_model="impostor", llr_action_mode="gate"),
    )

    assert shadow_result.recommendation.action == "escalate"
    assert gated_result.recommendation.action == "schedule_conversation"
    assert "LLR gate" in gated_result.recommendation.rationale


def test_gate_mode_does_not_touch_deviation_score_or_llr_value():
    # The gate changes `recommendation` only -- the underlying scores stay
    # exactly as computed, so professor_narrative / UI numbers don't lie.
    state = _baseline_state(0.30)
    submission = np.full(FEATURE_DIM, FAR)
    impostor_stats = (np.full(FEATURE_DIM, IMPOSTOR_MEAN), np.full(FEATURE_DIM, IMPOSTOR_SIGMA))

    shadow_result = score(
        state=_baseline_state(0.30),
        submission_vector=submission,
        feature_dict={},
        impostor_stats=impostor_stats,
        scoring_config=ScoringConfig(null_model="impostor", llr_action_mode="shadow"),
    )
    gated_result = score(
        state=state,
        submission_vector=submission,
        feature_dict={},
        impostor_stats=impostor_stats,
        scoring_config=ScoringConfig(null_model="impostor", llr_action_mode="gate"),
    )
    assert gated_result.authorship.deviation_score == shadow_result.authorship.deviation_score
    assert gated_result.authorship.llr_deviation_score == shadow_result.authorship.llr_deviation_score


def test_trigger_mode_catches_a_no_action_impostor_end_to_end():
    # Own baseline at 0.30, submission at 0.37 (small rms_z, stays well under
    # the no_action ceiling of 0.40) but the impostor pool matches almost
    # exactly (rms_z_null ~ 0) -> llr says "impostor-like" even though the
    # raw score alone would wave it through.
    state = _baseline_state(0.30)
    submission = np.full(FEATURE_DIM, 0.37)
    impostor_stats = (np.full(FEATURE_DIM, 0.37), np.full(FEATURE_DIM, 0.02))

    shadow_result = score(
        state=_baseline_state(0.30),
        submission_vector=submission,
        feature_dict={},
        impostor_stats=impostor_stats,
        scoring_config=ScoringConfig(null_model="impostor", llr_action_mode="shadow"),
        n_tokens=400,
    )
    triggered_result = score(
        state=state,
        submission_vector=submission,
        feature_dict={},
        impostor_stats=impostor_stats,
        scoring_config=ScoringConfig(null_model="impostor", llr_action_mode="trigger"),
        n_tokens=400,
    )

    assert shadow_result.recommendation.action == "no_action"
    assert shadow_result.authorship.llr_deviation_score >= LLR_ACTION_IMPOSTOR_THRESHOLD, (
        f"test setup should produce a confidently-impostor-like llr, got "
        f"{shadow_result.authorship.llr_deviation_score}"
    )
    assert triggered_result.recommendation.action == "monitor"
    assert "LLR trigger" in triggered_result.recommendation.rationale


def test_catastrophic_drift_still_overrides_a_gate_downgrade():
    # The emergency override (rms_z >= 3 SDs) must win regardless of what the
    # LLR gate would have softened -- it fires on the FINAL action, after
    # llr_action_mode has already been applied, so a gate downgrade cannot
    # mask a genuinely catastrophic deviation.
    state = _baseline_state(0.30)
    submission = np.full(FEATURE_DIM, 0.999)  # extreme -- drives rms_z well past 3
    impostor_stats = (np.full(FEATURE_DIM, 0.9999), np.full(FEATURE_DIM, 0.005))

    result = score(
        state=state,
        submission_vector=submission,
        feature_dict={},
        impostor_stats=impostor_stats,
        scoring_config=ScoringConfig(null_model="impostor", llr_action_mode="gate"),
    )
    assert result.catastrophic_drift is True
    assert result.recommendation.action == "escalate"
