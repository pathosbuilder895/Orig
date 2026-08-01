"""
tests/test_gate_properties.py — property-based invariants (Hypothesis) for
gate logic and conformal machinery. These are the "formal-ish spec": each
test states an invariant the code must satisfy on ALL inputs, not one
example.

Two corrections relative to the Task 13 plan draft (see
.superpowers/sdd/task-13-report.md for the full account):

  1. Every optional argument to `evaluate_g1_fpr` is passed BY KEYWORD.
     Its third positional parameter is `typicality_ns`, not
     `entity_baseline_counts` — a positional call would silently bind
     counts to the wrong parameter.

  2. `test_never_pass_when_no_entity_can_reach_the_band` (the plan's name)
     asserted `verdict != "pass"` whenever no entity's baseline count could
     reach the conformal band, full stop. That was true when the plan was
     drafted, but evaluate_g1_fpr's downgrade-to-"uninformative" rule was
     subsequently and deliberately tightened to additionally require
     `flagged == 0`: a nonzero flagged rate is real evidence from the
     deviation-score path, not the conformal band, so it must never be
     suppressed just because the band happens to be unreachable. The
     corrected property (renamed
     test_never_pass_when_the_band_is_unreachable_and_nothing_flagged below)
     states the TRUE invariant: verdict != "pass" only when the band is
     unreachable for every entity AND flagged == 0.
"""
from __future__ import annotations

from hypothesis import given, settings, strategies as st

from original.quantum.typicality import p_far
from validation.calibration_gate import (
    evaluate_g1_fpr,
    evaluate_g4_career_drift_monotone,
)
from validation.power import band_reachable, conformal_p_floor

_SETTINGS = settings(max_examples=50, deadline=None)

_actions = st.lists(
    st.sampled_from(["no_action", "monitor", "review", "schedule_meeting"]),
    min_size=1,
    max_size=300,
)

# Every count here is <= 30, so conformal_p_floor(count) == 1/(count+1) >=
# 1/31 ~= 0.0323 > 0.03 (NO_ACTION_FAR_THRESHOLD / the band_threshold used
# below) for every entity — band_reachable is False for all of them, so
# entity_unreachable is guaranteed True in evaluate_g1_fpr regardless of
# which counts Hypothesis draws. This is what makes the two properties
# below load-bearing rather than vacuous: they exercise the gate at a point
# where the unreachability signal is actually live.
_unreachable_counts = st.dictionaries(
    st.text(min_size=1, max_size=6), st.integers(1, 30),
    min_size=1, max_size=8,
)


class TestG1Properties:
    @_SETTINGS
    @given(_actions)
    def test_verdict_agrees_with_the_rate_arithmetic(self, actions):
        rate = sum(1 for a in actions if a != "no_action") / len(actions)
        result = evaluate_g1_fpr(actions, per_corpus={"c": actions})
        assert result.verdict == ("pass" if rate <= 0.05 else "fail")

    @_SETTINGS
    @given(_actions, _unreachable_counts)
    def test_never_pass_when_the_band_is_unreachable_and_nothing_flagged(self, actions, counts):
        # CORRECTED property (see module docstring, point 2): the
        # unreachability downgrade only fires when flagged == 0. When
        # flagged > 0, evaluate_g1_fpr must NOT downgrade a clean rate to
        # "uninformative" even though the band is unreachable for every
        # entity — those flags are real evidence from the deviation-score
        # path, not the conformal band, and the invariant must reflect that
        # or Hypothesis reliably finds the counterexample (confirmed while
        # drafting this test; see the report).
        result = evaluate_g1_fpr(
            actions, per_corpus={"c": actions},
            entity_baseline_counts=counts, band_threshold=0.03,
        )
        flagged = sum(1 for a in actions if a != "no_action")
        if flagged == 0:
            assert result.verdict != "pass"

    @_SETTINGS
    @given(_actions, _unreachable_counts)
    def test_reachability_never_downgrades_a_failure(self, actions, counts):
        # Uses the SAME guaranteed-unreachable counts as the property above
        # (not a reachable band, as the plan's draft used) so this actually
        # stresses the "only a would-be PASS can be downgraded" guard: with
        # entity_unreachable forced True here, a version of the gate that
        # dropped the `verdict == "pass"` condition on the downgrade would
        # turn a genuine failure into "uninformative" and this assertion
        # would catch it. With an always-reachable band (band_reachable
        # True for every entity) the assertion holds no matter what the
        # downgrade guard does, since entity_unreachable is False either
        # way — that version could never fail and was not load-bearing.
        result = evaluate_g1_fpr(
            actions, per_corpus={"c": actions},
            entity_baseline_counts=counts, band_threshold=0.03,
        )
        rate = sum(1 for a in actions if a != "no_action") / len(actions)
        if rate > 0.05:
            assert result.verdict == "fail"


class TestConformalProperties:
    @_SETTINGS
    @given(
        st.lists(
            st.floats(0, 100, allow_nan=False, allow_infinity=False),
            min_size=1, max_size=60,
        ),
        st.floats(0, 100, allow_nan=False, allow_infinity=False),
    )
    def test_p_far_respects_the_conformal_floor_and_ceiling(self, loo, r_sub):
        p = p_far(r_sub, loo)
        assert conformal_p_floor(len(loo)) <= p <= 1.0

    @_SETTINGS
    @given(st.integers(1, 1000), st.floats(0.001, 0.5))
    def test_band_reachability_is_monotone_in_n(self, n, threshold):
        if band_reachable(n, threshold):
            assert band_reachable(n + 1, threshold)


class TestG4Properties:
    @_SETTINGS
    @given(st.lists(st.floats(0, 10, allow_nan=False), min_size=3, max_size=3))
    def test_verdict_is_exactly_monotonicity(self, values):
        early, middle, late = values
        result = evaluate_g4_career_drift_monotone(
            {"early": early, "middle": middle, "late": late}
        )
        expected = early <= middle <= late
        assert (result.verdict == "pass") is expected
