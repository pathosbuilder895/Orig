"""
tests/test_gate_falsifiability.py — no gate may pass by construction.

Meta-test: every evaluate_g* in validation.calibration_gate must have a
GateContract (validation/gate_contracts.py) whose failure witness actually
produces verdict == "fail". This turns "the gate cannot fail" — the exact
defect the original G5 permutation-null control shipped with (its shuffle
was measurement-invariant, so it compared a quantity to itself and would
have recorded a confident, meaningless PASS) — from a review finding into
an unmergeable state.

Beyond the generic per-gate checks (TestContracts), TestWitnessesFailForThe
RightReason pins each failure witness to the SPECIFIC criterion it is
supposed to violate — not just "verdict == fail" for any old reason. This
guards against a witness that fails incidentally (e.g. via a missing dict
key, a degenerate/uninformative branch, or a machinery error) rather than
via the guard the gate is actually about — the trap a prior task's
almost-shipped test fell into (it raised via numpy's shape-mismatch check
rather than the guard it meant to exercise).
"""
from __future__ import annotations

import inspect

import pytest

import validation.calibration_gate as calibration_gate
from validation.gate_contracts import GATE_CONTRACTS


def _all_gate_evaluators() -> list[str]:
    # LIMITATION: inspect.isfunction only matches plain `def`/lambda objects.
    # A future gate exposed as a functools.partial, a callable class instance,
    # or wrapped by a decorator that returns a non-function callable would
    # silently evade this scan (and therefore test_no_unregistered_gates)
    # without raising anything here — it would just never be found.
    return sorted(
        name
        for name, obj in inspect.getmembers(calibration_gate, inspect.isfunction)
        if name.startswith("evaluate_g")
    )


class TestEveryGateHasAContract:
    def test_no_unregistered_gates(self):
        missing = [n for n in _all_gate_evaluators() if n not in GATE_CONTRACTS]
        assert missing == [], (
            f"gates without falsifiability contracts: {missing} — register a "
            "failure witness in validation/gate_contracts.py before merging"
        )

    def test_no_stale_contracts(self):
        stale = [n for n in GATE_CONTRACTS if n not in _all_gate_evaluators()]
        assert stale == [], (
            f"contracts registered for gates that no longer exist: {stale} — "
            "remove them from validation/gate_contracts.py"
        )


@pytest.mark.parametrize("name", sorted(GATE_CONTRACTS))
class TestContracts:
    def test_failure_witness_fails(self, name):
        result = GATE_CONTRACTS[name].failure_witness()
        assert result.verdict == "fail", (
            f"{name}'s failure witness returned {result.verdict!r} — "
            "the gate can no longer fail on its registered counterexample. "
            "'uninformative' is NOT a failure — it means 'could not tell', "
            "which is exactly the state this registry exists to distinguish "
            "from a real failure."
        )
        # FIX 6 in calibration_gate.py enforces passed == (verdict == "pass")
        # unconditionally, but pin it here too: a failure witness is only
        # honest if `passed` agrees with `verdict`.
        assert result.passed is False
        # A witness that fails is only proof of ANYTHING if it actually
        # exercised the gate it's registered under. Without this, a
        # mis-wired contract whose failure_witness calls a DIFFERENT gate
        # that happens to fail would report green here while the gate it's
        # supposedly registered for could be unconditionally passed
        # (passed=True hardcoded) and nothing above would catch it — the
        # exact hole this registry exists to close.
        assert result.name == GATE_CONTRACTS[name].gate, (
            f"{name}'s failure witness returned a result for gate "
            f"{result.name!r}, not {GATE_CONTRACTS[name].gate!r} — the "
            "witness is calling the wrong gate function"
        )

    def test_label_destruction_never_passes(self, name):
        contract = GATE_CONTRACTS[name]
        if contract.label_destruction is None:
            assert contract.notes, (
                f"{name} has no label-destruction leg and no notes explaining "
                "why — either register one or say why label destruction "
                "doesn't apply to this gate's own criterion"
            )
            pytest.skip("no label-destruction leg for this gate (see notes)")
        result = contract.label_destruction()
        assert result.verdict != "pass", (
            f"{name} passed on label-destroyed input — it is not measuring "
            "authorship"
        )


class TestWitnessesFailForTheRightReason:
    """Per-gate assertions that pin the failure witness (and, where
    registered, the label-destruction leg) to the SPECIFIC criterion it is
    supposed to violate, not merely to "verdict got set to fail somehow".
    """

    def test_g1_fails_on_the_pooled_rate_not_on_reachability(self):
        result = GATE_CONTRACTS["evaluate_g1_fpr"].failure_witness()
        # The witness's 100% flagged rate must itself exceed the 5% bar —
        # if this were 0 or <=0.05 the "fail" would have to come from
        # somewhere else (there is no "else" in evaluate_g1_fpr's pass/fail
        # branch, but this pins the intended mechanism regardless of future
        # refactors).
        assert result.detail["pooled_flagged_rate"] > 0.05
        assert result.detail["flagged"] == result.detail["n"]
        # No typicality_ns/entity_baseline_counts were supplied, so the
        # reachability/uninformative downgrade path is untouched — the
        # failure is not an artifact of the conformal-floor machinery.
        assert result.detail["reachability"]["observed"] is False
        assert "power" not in result.detail

    def test_g2_fails_because_impostor_looks_more_typical(self):
        import statistics

        result = GATE_CONTRACTS["evaluate_g2_bland_impostor"].failure_witness()
        holdout_q = result.detail["holdout_q"]
        impostor_q = result.detail["impostor_q"]
        assert statistics.median(impostor_q) > statistics.median(holdout_q)

    def test_g2b_fails_because_impostor_looks_more_typical_and_keeps_proxy_label(self):
        import statistics

        result = GATE_CONTRACTS["evaluate_g2b_paraphrase_resistant"].failure_witness()
        holdout_q = result.detail["holdout_q"]
        impostor_q = result.detail["paraphrased_impostor_q"]
        assert statistics.median(impostor_q) > statistics.median(holdout_q)
        assert "proxy" in result.criterion.lower()
        assert "proxy_note" in result.detail

    def test_g3_fails_on_the_plain_threshold_not_the_wilson_interval(self):
        result = GATE_CONTRACTS["evaluate_g3_attribution"].failure_witness()
        assert result.detail["top1_accuracy"] < 0.7
        # n_essays was not supplied, so the Wilson-interval informativeness
        # branch never runs — this must be a plain-threshold fail, not a
        # sample-size-driven "uninformative" that happens to also not be
        # "pass".
        assert "power" not in result.detail

    def test_g4_fails_on_a_genuine_order_violation_with_all_three_groups_present(self):
        result = GATE_CONTRACTS["evaluate_g4_career_drift_monotone"].failure_witness()
        means = result.detail["group_means"]
        # All three groups must be present — a missing group ALSO fails
        # (len(values) == 3 check) but for the wrong reason (missing data,
        # not a broken order), which would make this witness fail
        # incidentally rather than for the ordering guard it exists to test.
        assert set(means) == {"early", "middle", "late"}
        assert not (means["early"] <= means["middle"] <= means["late"])

    def test_g5_fails_because_all_three_shuffled_legs_still_look_like_signal(self):
        """The motivating case for this whole task: the original G5 shipped
        with a shuffle that was measurement-invariant. This witness
        reproduces exactly that shape (every shuffled leg indistinguishable
        from, or stronger than, the real signal) and pins that all THREE
        sub-checks independently flag it — not just one incidentally
        tipping the overall verdict while the other two would (wrongly)
        look fine.
        """
        result = GATE_CONTRACTS["evaluate_g5_permutation_null"].failure_witness()
        d = result.detail
        g1_is_suspicious = d["shuffled_g1_mean_deviation"] <= d["real_g1_mean_deviation"]
        g3_is_suspicious = d["shuffled_g3_accuracy"] >= 0.30
        g4_majority = d["g4_total_draws"] // 2 + 1
        g4_is_suspicious = d["g4_nonmonotone_draws"] < g4_majority
        assert g1_is_suspicious, "witness no longer exercises the G1-leg guard"
        assert g3_is_suspicious, "witness no longer exercises the G3-leg guard"
        assert g4_is_suspicious, "witness no longer exercises the G4-leg guard"

    def test_g6_fails_on_the_ratio_not_on_a_zero_rate_special_case(self):
        result = GATE_CONTRACTS["evaluate_g6_fairness"].failure_witness()
        # ratio_status distinguishes the three verdict branches
        # (both_nonzero / one_group_zero / undefined_both_zero) — pinning it
        # here proves the fail came from the >2x ratio criterion the gate
        # claims to enforce, not from the infinite-disparity zero-rate
        # special case (a real but DIFFERENT failure mode) or the
        # can't-know both-zero case (which is "uninformative", not "fail").
        assert result.detail["ratio_status"] == "both_nonzero"
        assert result.detail["ratio"] > 2.0

    def test_g3_label_destruction_is_a_mathematical_guarantee_not_luck(self):
        """1/9 chance-level accuracy is registered as G3's label-destruction
        leg. Pin that it fails via the same plain threshold (not the
        Wilson-interval path — n_essays is not supplied here either), so the
        claim in gate_contracts.py's notes ("chance accuracy is always
        below the 0.7 bar for any pool of >= 2 authors, since chance
        <= 1/2") is checkable, not asserted on faith.
        """
        contract = GATE_CONTRACTS["evaluate_g3_attribution"]
        result = contract.label_destruction()
        assert result.detail["top1_accuracy"] < 0.5  # chance for >= 2 authors
        assert "power" not in result.detail

    def test_g4_label_destruction_is_a_genuine_order_violation(self):
        contract = GATE_CONTRACTS["evaluate_g4_career_drift_monotone"]
        result = contract.label_destruction()
        means = result.detail["group_means"]
        assert set(means) == {"early", "middle", "late"}
        assert not (means["early"] <= means["middle"] <= means["late"])


class TestG2FamilyLabelDestructionIsHonestlyNone:
    """G2/G2b/G6 register label_destruction=None. This is not an omission —
    for these gates, feeding truly indistinguishable ("label-destroyed")
    populations is PROVABLY a legitimate pass by construction, so no "must
    never pass" witness can be registered honestly. These tests are the
    concrete proof backing that claim (see gate_contracts.py's notes for
    each).
    """

    def test_g2_identical_populations_legitimately_pass(self):
        result = calibration_gate.evaluate_g2_bland_impostor(
            holdout_q=[0.3, 0.4, 0.5], impostor_q=[0.3, 0.4, 0.5]
        )
        assert result.verdict == "pass"

    def test_g2b_identical_populations_legitimately_pass(self):
        result = calibration_gate.evaluate_g2b_paraphrase_resistant(
            holdout_q=[0.3, 0.4, 0.5], paraphrased_impostor_q=[0.3, 0.4, 0.5]
        )
        assert result.verdict == "pass"

    def test_g6_equal_rates_legitimately_pass(self):
        result = calibration_gate.evaluate_g6_fairness(
            native_fpr=0.05, non_native_fpr=0.05
        )
        assert result.verdict == "pass"


class TestG2bProxyLabelSurvives:
    def test_proxy_label_in_criterion_and_detail(self):
        result = GATE_CONTRACTS["evaluate_g2b_paraphrase_resistant"].failure_witness()
        assert "proxy" in result.criterion.lower()
        assert "proxy_note" in result.detail
