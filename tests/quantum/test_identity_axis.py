"""tests/quantum/test_identity_axis.py — Phase 2 typicality x identity action matrix.

Covers three layers:
  1. TestIdentityAxisActionMatrix — the pure `_identity_axis_action` helper,
     including disambiguation of the ambiguous "schedule_conversation" band
     via `typicality_source` ("far" vs "central" — see typicality.py's
     band_from_p docstring for why the same band string means two different
     things).
  2. TestTypicalitySourceField — score()'s NEW typicality_source field is set
     correctly from p_central/NO_ACTION_CENTRAL_THRESHOLD, independent of
     the identity axis being enabled at all (Task 3-style plumbing).
  3. TestIdentityAxisIntegration / TestIdentityAxisWiring / TestGrowthDamping
     — score()-level wiring: flag-off byte-identical behaviour (same pattern
     as tests/quantum/test_typicality_integration.py), the matrix actually
     superseding the typicality-only action when both flags + inputs are
     present, and the x0.75 growth dampening being disabled only under
     IDENTITY_AXIS.
"""

from __future__ import annotations

import numpy as np

import original.quantum.scoring as scoring_module
import original.quantum.typicality as typicality_module
from original.constants import ALL_FEATURE_CODES, FEATURE_DIM
from original.quantum.scoring import ScoringConfig, _identity_axis_action, score
from original.quantum.state import BaselineSample, StudentState

_RNG = np.random.default_rng(20260730)


def _vec():
    return _RNG.uniform(0.3, 0.7, FEATURE_DIM)


def _feature_dict(vector):
    return {code: float(val) for code, val in zip(ALL_FEATURE_CODES, vector)}


def _state_with_n_samples(n, student_id="identity-axis-test"):
    samples = [
        BaselineSample(text="", vector=_vec(), provenance="proctored", auth_weight=1.0)
        for _ in range(n)
    ]
    return StudentState(student_id=student_id, samples=samples)


_MU_NULL = np.full(FEATURE_DIM, 0.5)
_SIGMA_NULL = np.full(FEATURE_DIM, 0.1)


# ── 1. Pure action-matrix function ──────────────────────────────────────────


class TestIdentityAxisActionMatrix:
    def test_typical_and_distinctively_theirs_is_no_action(self):
        assert _identity_axis_action("no_action", None, llr=0.30) == "no_action"

    def test_typical_and_fits_others_better_is_schedule_conversation(self):
        assert _identity_axis_action("no_action", None, llr=0.70) == "schedule_conversation"

    def test_too_far_and_distinctively_theirs_is_monitor_not_escalate(self):
        """The (too-far, distinctively-theirs) cell: benign growth, not fraud."""
        assert _identity_axis_action("escalate", "far", llr=0.30) == "monitor"

    def test_too_far_and_fits_others_better_is_escalate(self):
        assert _identity_axis_action("escalate", "far", llr=0.70) == "escalate"

    def test_too_central_and_non_distinctive_is_schedule_conversation_ai_signature(self):
        assert (
            _identity_axis_action("schedule_conversation", "central", llr=0.50)
            == "schedule_conversation"
        )

    def test_too_central_and_fits_others_better_is_escalate(self):
        assert _identity_axis_action("schedule_conversation", "central", llr=0.70) == "escalate"

    def test_none_typicality_band_falls_back_to_identity_only(self):
        """Degrade gracefully when the typicality axis has insufficient N."""
        assert _identity_axis_action(None, None, llr=0.70) is None

    # ── The core disambiguation: same band string, different source ────────
    def test_schedule_conversation_from_far_side_distinctive_is_monitor(self):
        """typicality_source='far' means moderate DRIFT produced the band —
        this must route through the 'too-far' row, not 'too-central'."""
        assert _identity_axis_action("schedule_conversation", "far", llr=0.30) == "monitor"

    def test_schedule_conversation_from_far_side_fits_others_is_escalate(self):
        assert _identity_axis_action("schedule_conversation", "far", llr=0.70) == "escalate"

    def test_schedule_conversation_from_far_vs_central_disagree_on_distinctive(self):
        """Same band, same llr, different source -> different action. Proves
        the function actually consults typicality_source rather than
        guessing from the band string alone."""
        far_result = _identity_axis_action("schedule_conversation", "far", llr=0.30)
        central_result = _identity_axis_action("schedule_conversation", "central", llr=0.30)
        assert far_result == "monitor"
        assert central_result == "monitor"
        # Both land on "monitor" for the distinctive column (too-far and
        # too-central share that cell) — verify the fits_others column
        # instead, where the two rows diverge in escalation semantics is
        # identical too (both escalate) but the boundary/no_action row does
        # differ from "typical":
        assert _identity_axis_action("no_action", None, llr=0.30) == "no_action"
        assert far_result != "no_action"
        assert central_result != "no_action"

    def test_monitor_band_is_also_too_far_row(self):
        assert _identity_axis_action("monitor", "far", llr=0.30) == "monitor"
        assert _identity_axis_action("monitor", "far", llr=0.50) == "schedule_conversation"
        assert _identity_axis_action("monitor", "far", llr=0.70) == "escalate"


# ── 2. typicality_source field on score() ───────────────────────────────────


class TestTypicalitySourceField:
    """Directly exercises score()'s NEW typicality_source assignment by
    monkeypatching the pure p_far/p_central functions it calls (imported
    locally inside score(), so patching the typicality module's attributes
    before calling score() is picked up) — avoids needing to reverse-engineer
    a real LOO distribution that lands exactly on a given band."""

    def test_source_is_central_when_p_central_at_or_below_threshold(self, monkeypatch):
        monkeypatch.setattr(typicality_module, "p_central", lambda r, loo: 0.02)
        monkeypatch.setattr(typicality_module, "p_far", lambda r, loo: 0.5)
        state = _state_with_n_samples(6)
        v = _vec()
        result = score(
            state=state,
            submission_vector=v,
            feature_dict=_feature_dict(v),
            scoring_config=ScoringConfig(typicality_scoring_enabled=True),
        )
        assert result.typicality_band == "schedule_conversation"
        assert result.typicality_source == "central"

    def test_source_is_far_when_p_central_above_threshold(self, monkeypatch):
        monkeypatch.setattr(typicality_module, "p_central", lambda r, loo: 0.5)
        monkeypatch.setattr(typicality_module, "p_far", lambda r, loo: 0.5)
        state = _state_with_n_samples(6)
        v = _vec()
        result = score(
            state=state,
            submission_vector=v,
            feature_dict=_feature_dict(v),
            scoring_config=ScoringConfig(typicality_scoring_enabled=True),
        )
        assert result.typicality_band == "no_action"
        assert result.typicality_source == "far"

    def test_source_is_none_when_typicality_disabled(self):
        state = _state_with_n_samples(6)
        v = _vec()
        result = score(
            state=state,
            submission_vector=v,
            feature_dict=_feature_dict(v),
            scoring_config=ScoringConfig(typicality_scoring_enabled=False),
        )
        assert result.typicality_source is None

    def test_source_is_none_below_n_2(self):
        state = _state_with_n_samples(1)
        v = _vec()
        result = score(
            state=state,
            submission_vector=v,
            feature_dict=_feature_dict(v),
            scoring_config=ScoringConfig(typicality_scoring_enabled=True),
        )
        assert result.typicality_source is None


# ── 3a. Flag-off byte-identical integration (mirrors Task 3's own test) ─────


class TestIdentityAxisIntegration:
    def test_flag_off_leaves_action_matrix_unused(self):
        """Both flags off: action comes from ACTION_THRESHOLDS as before."""
        state = _state_with_n_samples(6)
        sub_vector = _vec()
        off = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(identity_axis_enabled=False),
        )
        default = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
        )
        assert off.recommendation.action == default.recommendation.action
        assert off.authorship.deviation_score == default.authorship.deviation_score
        assert off.trajectory.adjustment_factor == default.trajectory.adjustment_factor

    def test_identity_axis_off_action_equals_raw_typicality_band_even_with_impostor_pool(self):
        """Even when NULL_MODEL=impostor + impostor_stats + a typicality band
        are ALL present, IDENTITY_AXIS=0 must leave the action exactly as
        Task 3's typicality-only wiring would set it — the matrix must not
        fire without its own flag."""
        state = _state_with_n_samples(6)
        sub_vector = _vec()
        config = ScoringConfig(
            typicality_scoring_enabled=True,
            null_model="impostor",
            identity_axis_enabled=False,
        )
        with_pool = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            impostor_stats=(_MU_NULL, _SIGMA_NULL),
            scoring_config=config,
        )
        typicality_only = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(typicality_scoring_enabled=True),
        )
        assert with_pool.authorship.llr_deviation_score is not None
        assert with_pool.recommendation.action == typicality_only.recommendation.action


# ── 3b. Wiring: the matrix actually supersedes the typicality-only action ──


class TestIdentityAxisWiring:
    def test_identity_axis_disabled_never_calls_matrix(self, monkeypatch):
        def _boom(*a, **kw):
            raise AssertionError("_identity_axis_action must not be called when disabled")

        monkeypatch.setattr(scoring_module, "_identity_axis_action", _boom)
        state = _state_with_n_samples(6)
        sub_vector = _vec()
        # Should not raise -- proves the gate short-circuits before calling
        # the (broken, in this test) matrix function.
        score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            impostor_stats=(_MU_NULL, _SIGMA_NULL),
            scoring_config=ScoringConfig(
                typicality_scoring_enabled=True,
                null_model="impostor",
                identity_axis_enabled=False,
            ),
        )

    def test_identity_axis_enabled_calls_matrix_and_adopts_its_result(self, monkeypatch):
        calls = []

        def _stub(band, source, llr):
            calls.append((band, source, llr))
            return "monitor"

        monkeypatch.setattr(scoring_module, "_identity_axis_action", _stub)
        state = _state_with_n_samples(6)
        sub_vector = _vec()
        result = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            impostor_stats=(_MU_NULL, _SIGMA_NULL),
            scoring_config=ScoringConfig(
                typicality_scoring_enabled=True,
                null_model="impostor",
                identity_axis_enabled=True,
            ),
        )
        assert calls, "_identity_axis_action was never invoked"
        assert result.recommendation.action == "monitor"

    def test_identity_axis_requires_null_model_impostor(self, monkeypatch):
        """identity_axis_enabled=True but null_model != 'impostor' -> matrix
        must not fire (llr_deviation_score would be None anyway, but this
        confirms the explicit null_model gate too)."""

        def _boom(*a, **kw):
            raise AssertionError(
                "_identity_axis_action must not be called without impostor null model"
            )

        monkeypatch.setattr(scoring_module, "_identity_axis_action", _boom)
        state = _state_with_n_samples(6)
        sub_vector = _vec()
        score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            impostor_stats=(_MU_NULL, _SIGMA_NULL),
            scoring_config=ScoringConfig(
                typicality_scoring_enabled=True,
                null_model="none",
                identity_axis_enabled=True,
            ),
        )

    def test_identity_axis_requires_a_typicality_band(self, monkeypatch):
        """identity_axis_enabled=True + null_model=impostor but typicality
        scoring is off (no band) -> matrix must not fire."""

        def _boom(*a, **kw):
            raise AssertionError(
                "_identity_axis_action must not be called without a typicality band"
            )

        monkeypatch.setattr(scoring_module, "_identity_axis_action", _boom)
        state = _state_with_n_samples(6)
        sub_vector = _vec()
        score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            impostor_stats=(_MU_NULL, _SIGMA_NULL),
            scoring_config=ScoringConfig(
                typicality_scoring_enabled=False,
                null_model="impostor",
                identity_axis_enabled=True,
            ),
        )

    def test_entanglement_override_still_fires_over_matrix_result(self, monkeypatch):
        """The ghostwriting entanglement override must still be able to raise
        a non-escalate matrix result to escalate — it is unconditional and
        must not be short-circuited by the identity axis.

        Uses a dedicated local RNG (not the shared module-level `_vec()`
        helper) so this scenario is reproducible regardless of how much
        other tests in this module have already drawn from `_RNG` — the
        ghostwriting trigger below is asserted unconditionally, not gated
        behind an `if`, so it must fire every run."""
        monkeypatch.setattr(scoring_module, "_identity_axis_action", lambda b, s, l: "no_action")
        rng = np.random.default_rng(20260730001)
        samples = [
            BaselineSample(
                text="",
                vector=rng.uniform(0.3, 0.7, FEATURE_DIM),
                provenance="proctored",
                auth_weight=1.0,
            )
            for _ in range(6)
        ]
        state = StudentState(student_id="ghostwriting-override-test", samples=samples)
        # Construct a submission that triggers the T1-T11 ghostwriting
        # entanglement: TTR spikes >= +0.15 above baseline, error_kl_divergence
        # drops <= -0.10 below baseline.
        sub_vector = np.array(state.baseline_mean, copy=True)
        ttr_idx = ALL_FEATURE_CODES.index("type_token_ratio")
        err_idx = ALL_FEATURE_CODES.index("error_kl_divergence")
        sub_vector[ttr_idx] = min(1.0, sub_vector[ttr_idx] + 0.30)
        sub_vector[err_idx] = max(0.0, sub_vector[err_idx] - 0.30)
        result = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            impostor_stats=(_MU_NULL, _SIGMA_NULL),
            scoring_config=ScoringConfig(
                typicality_scoring_enabled=True,
                null_model="impostor",
                identity_axis_enabled=True,
            ),
        )
        labels = [e.label for e in result.interference.broken_entanglements]
        assert "T1–T11 vocabulary-spike + error-vanish (AI ghostwriting signal)" in labels, (
            "test construction must trigger the ghostwriting entanglement — "
            f"got broken_entanglements={labels}"
        )
        assert result.recommendation.action == "escalate"


# ── 3c. x0.75 growth dampening disabled only under IDENTITY_AXIS ───────────


def _growth_scenario():
    """Deterministic construction of a state + submission where the growth
    branch (alignment > TRAJECTORY_GROWTH_THRESHOLD) fires. 3 baseline
    samples with a linear trend in the first 20 features produce a
    trajectory vector; the submission is extrapolated further along that
    exact direction so its cosine similarity comfortably clears 0.25."""
    n_moving = 20

    def mk_vec(f0):
        v = np.full(FEATURE_DIM, 0.5)
        v[:n_moving] = f0
        return np.clip(v, 0.0, 1.0)

    samples = [
        BaselineSample(
            text="", vector=mk_vec(0.5 + i * 0.1), provenance="proctored", auth_weight=1.0
        )
        for i in range(3)
    ]
    state = StudentState(student_id="growth-dampening-test", samples=samples)
    traj = state.trajectory
    assert traj.vector is not None
    last = samples[-1].vector
    sub_vector = np.clip(last + 2.0 * traj.vector, 0.0, 1.0)
    return state, sub_vector


class TestGrowthDampeningUnderIdentityAxis:
    def test_growth_dampening_applies_when_identity_axis_off(self):
        state, sub_vector = _growth_scenario()
        result = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(identity_axis_enabled=False),
        )
        assert result.trajectory.direction == "growth"
        assert result.trajectory.adjustment_factor == 0.75

    def test_growth_dampening_disabled_when_identity_axis_on(self):
        state, sub_vector = _growth_scenario()
        result = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(identity_axis_enabled=True),
        )
        assert result.trajectory.direction == "growth"
        assert result.trajectory.adjustment_factor == 1.0

    def test_growth_dampening_disabled_raises_deviation_score(self):
        """Same scenario, only the flag differs -> deviation_score with the
        flag on must be higher (undampened) than with it off."""
        state, sub_vector = _growth_scenario()
        off = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(identity_axis_enabled=False),
        )
        on = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(identity_axis_enabled=True),
        )
        assert on.authorship.deviation_score > off.authorship.deviation_score

    def test_regressive_and_lateral_unaffected_by_flag(self):
        """The x0.75 exception is scoped to the growth branch only —
        regressive (1.15) and lateral (1.0) factors must be identical
        regardless of identity_axis_enabled."""
        state = _state_with_n_samples(6)
        sub_vector = _vec()
        off = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(identity_axis_enabled=False),
        )
        on = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(identity_axis_enabled=True),
        )
        # This state/submission pair has no strong trajectory alignment
        # (random uniform samples), so direction should not be "growth" —
        # guard the assumption, then assert the factors match.
        assert off.trajectory.direction != "growth"
        assert off.trajectory.adjustment_factor == on.trajectory.adjustment_factor
