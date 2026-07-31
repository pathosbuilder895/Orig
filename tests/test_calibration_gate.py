"""
tests/test_calibration_gate.py — pure-math unit tests for the calibration
gate criteria. The full corpus-driven run (validation/calibration_gate.py
executed as a script against seminary+public_authors+Plato) is slow and
belongs in CI's validation job, not the fast unit-test suite — this file
only tests the gate LOGIC on small synthetic inputs.
"""

from __future__ import annotations

import pytest

from validation.calibration_gate import (
    GateResult,
    _conformal_p_floor,
    _g5_machinery_error_result,
    _g6_insufficient_data_result,
    _g6_short_group_message,
    _g6_unreachable_threshold_result,
    _min_n_for_threshold,
    _paraphrase_proxy,
    _reachability_block,
    _require_healthy_leg,
    _threshold_reachable,
    _uniformity_features_enabled,
    _uniformity_slice_summary,
    evaluate_g1_fpr,
    evaluate_g2_bland_impostor,
    evaluate_g2b_paraphrase_resistant,
    evaluate_g3_attribution,
    evaluate_g5_permutation_null,
    evaluate_g6_fairness,
    run_g5,
)


class TestG1Fpr:
    def test_passes_when_flagged_rate_at_or_below_five_percent(self):
        actions = ["no_action"] * 95 + ["monitor"] * 5
        result = evaluate_g1_fpr(actions, per_corpus={"synthetic": actions})
        assert result.passed is True

    def test_fails_when_flagged_rate_above_five_percent(self):
        actions = ["no_action"] * 85 + ["monitor"] * 15
        result = evaluate_g1_fpr(actions, per_corpus={"synthetic": actions})
        assert result.passed is False

    def test_reports_per_corpus_breakdown_not_just_pooled(self):
        per_corpus = {
            "good_corpus": ["no_action"] * 100,
            "bad_corpus": ["escalate"] * 20 + ["no_action"] * 80,
        }
        pooled = per_corpus["good_corpus"] + per_corpus["bad_corpus"]
        result = evaluate_g1_fpr(pooled, per_corpus=per_corpus)
        assert "bad_corpus" in result.detail["per_corpus_flagged_rate"]
        assert result.detail["per_corpus_flagged_rate"]["bad_corpus"] > 0.05


class TestConformalReachability:
    """The shared reachability guard. A conformal p-value cannot fall below
    1/(n+1), so a gate thresholding p at 0.02 with n=4 is testing something
    structurally impossible — its 'zero flags' result is vacuous, not fair."""

    def test_p_floor_is_one_over_n_plus_one(self):
        assert _conformal_p_floor(4) == pytest.approx(0.2)
        assert _conformal_p_floor(49) == pytest.approx(0.02)
        assert _conformal_p_floor(0) == pytest.approx(1.0)

    def test_threshold_unreachable_below_required_n(self):
        assert _threshold_reachable(4, 0.02) is False
        assert _threshold_reachable(48, 0.02) is False

    def test_threshold_reachable_at_exactly_required_n(self):
        """Spec §5's reachability table: the .02 central boundary needs N>=49."""
        assert _threshold_reachable(49, 0.02) is True

    def test_min_n_matches_the_specs_reachability_table(self):
        assert _min_n_for_threshold(0.02) == 49
        assert _min_n_for_threshold(0.03) == 33
        # Self-consistency at every boundary: n-1 unreachable, n reachable.
        for threshold in (0.005, 0.015, 0.02, 0.03, 0.05, 0.1):
            n = _min_n_for_threshold(threshold)
            assert _threshold_reachable(n, threshold) is True
            assert _threshold_reachable(n - 1, threshold) is False

    def test_block_reports_the_binding_minimum_n(self):
        block = _reachability_block([60, 4, 12], 0.02)
        assert block["observed"] is True
        assert block["min_typicality_n"] == 4
        assert block["p_floor"] == pytest.approx(0.2)
        assert block["required_n"] == 49
        assert block["reachable"] is False

    def test_block_records_when_no_typicality_n_was_observed(self):
        """No typicality_n on any fold means the actions came from the
        deviation path, not the conformal band — the floor does not apply
        and the block must say so rather than inventing a verdict."""
        block = _reachability_block([], 0.02)
        assert block["observed"] is False
        assert block["reachable"] is None


class TestG1ReachabilityAnnotation:
    """G1's flagged rate is genuinely defined, so its verdict is unchanged —
    but a 0.0% rate produced at an N where no flag is structurally possible
    must never read as demonstrated discrimination."""

    def test_unreachable_threshold_annotates_current_value_without_changing_verdict(self):
        actions = ["no_action"] * 100
        result = evaluate_g1_fpr(
            actions, per_corpus={"synthetic": actions}, typicality_ns=[12] * 100
        )
        assert result.passed is True  # verdict unchanged
        assert "UNINFORMATIVE" in result.current_value
        assert "n<=12" in result.current_value
        assert result.detail["reachability"]["min_typicality_n"] == 12
        assert result.detail["reachability"]["reachable"] is False

    def test_reachable_threshold_leaves_current_value_clean(self):
        actions = ["no_action"] * 100
        result = evaluate_g1_fpr(
            actions, per_corpus={"synthetic": actions}, typicality_ns=[60] * 100
        )
        assert "UNINFORMATIVE" not in result.current_value
        assert result.detail["reachability"]["reachable"] is True

    def test_annotation_is_absent_when_no_typicality_ns_are_supplied(self):
        actions = ["no_action"] * 100
        result = evaluate_g1_fpr(actions, per_corpus={"synthetic": actions})
        assert result.current_value == "0.0%"
        assert result.detail["reachability"]["observed"] is False


class TestG2BlandImpostor:
    def test_passes_when_impostor_q_is_lower_than_holdout_q(self):
        """q = min(p_far, p_central). Impostor should score LOWER (more
        anomalous) than genuine holdouts."""
        holdout_q = [0.5, 0.45, 0.5, 0.48]
        impostor_q = [0.05, 0.03, 0.02]
        result = evaluate_g2_bland_impostor(holdout_q, impostor_q)
        assert result.passed is True

    def test_fails_when_impostor_q_exceeds_holdout_q(self):
        """Reproduces the CURRENT defect: Eryxias-like impostor looks MORE
        typical than genuine holdouts."""
        holdout_q = [0.5, 0.45, 0.5, 0.48]
        impostor_q = [0.9, 0.85, 0.88]
        result = evaluate_g2_bland_impostor(holdout_q, impostor_q)
        assert result.passed is False


class TestG5PermutationNull:
    def test_passes_when_shuffled_labels_collapse_to_chance(self):
        result = evaluate_g5_permutation_null(
            real_g1_mean_deviation=0.42,      # same-author LOO deviations
            shuffled_g1_mean_deviation=0.71,  # cross-author blends look MORE deviant -> good
            shuffled_g3_accuracy=0.12,        # near 1/n_authors, not 0.7+ -> good
            g4_nonmonotone_draws=3,           # no draw retains chronological signal -> good
            g4_total_draws=3,
        )
        assert result.passed is True

    def test_fails_when_shuffled_labels_still_pass_the_real_gates(self):
        """If G1/G3/G4 still look good on shuffled labels, the pipeline is
        measuring the selection procedure, not authorship signal."""
        result = evaluate_g5_permutation_null(
            real_g1_mean_deviation=0.42,
            shuffled_g1_mean_deviation=0.40,  # blending baselines changed nothing -> suspicious
            shuffled_g3_accuracy=0.75,        # suspiciously still high on noise
            g4_nonmonotone_draws=0,           # every draw still "monotone" on blends
            g4_total_draws=3,
        )
        assert result.passed is False

    def test_single_suspicious_leg_fails_the_gate(self):
        """ANY leg that still looks like real signal fails G5. Here only the
        G1 leg is suspicious: shuffled mean == real mean, i.e. the measurement
        is insensitive to cross-author baseline blending."""
        result = evaluate_g5_permutation_null(
            real_g1_mean_deviation=0.42,
            shuffled_g1_mean_deviation=0.42,  # <= real -> suspicious
            shuffled_g3_accuracy=0.12,
            g4_nonmonotone_draws=3,
            g4_total_draws=3,
        )
        assert result.passed is False

    def test_two_of_three_nonmonotone_draws_counts_as_collapsed(self):
        """Majority boundary: 2 of 3 non-monotone draws IS a majority — the
        G4 leg reads as collapsed and (with the other legs collapsed) the
        gate passes."""
        result = evaluate_g5_permutation_null(
            real_g1_mean_deviation=0.42,
            shuffled_g1_mean_deviation=0.71,
            shuffled_g3_accuracy=0.12,
            g4_nonmonotone_draws=2,
            g4_total_draws=3,
        )
        assert result.passed is True

    def test_one_of_three_nonmonotone_draws_is_still_suspicious(self):
        """Majority boundary: only 1 of 3 draws non-monotone means shuffled
        labels still produce 'chronological' orderings most of the time —
        suspicious, gate fails."""
        result = evaluate_g5_permutation_null(
            real_g1_mean_deviation=0.42,
            shuffled_g1_mean_deviation=0.71,
            shuffled_g3_accuracy=0.12,
            g4_nonmonotone_draws=1,
            g4_total_draws=3,
        )
        assert result.passed is False


class TestRequireHealthyLeg:
    def test_exactly_ten_percent_errors_is_tolerated(self):
        """10/100 == 0.10 is NOT > 0.10 — the guard is strictly greater-than."""
        _require_healthy_leg("leg", n_success=90, n_errors=10)  # must not raise

    def test_above_ten_percent_errors_raises(self):
        with pytest.raises(RuntimeError, match="11/100"):
            _require_healthy_leg("leg", n_success=89, n_errors=11)

    def test_zero_successful_folds_raises(self):
        with pytest.raises(RuntimeError, match="zero successful"):
            _require_healthy_leg("leg", n_success=0, n_errors=0)


class TestG6Fairness:
    """All four zero/non-zero rate cases are pinned. The inherited
    'handles zero native fpr without division error' test (whose only
    assertion was isinstance(passed, bool)) was REMOVED: it blessed the
    defect below — an infinite disparity silently returning ratio 1.0."""

    def test_passes_when_both_rates_nonzero_and_ratio_at_most_two(self):
        result = evaluate_g6_fairness(
            native_fpr=0.04,
            non_native_fpr=0.06,
        )
        assert result.passed is True
        assert result.detail["ratio"] == pytest.approx(1.5)

    def test_fails_when_both_rates_nonzero_and_ratio_exceeds_two(self):
        result = evaluate_g6_fairness(
            native_fpr=0.02,
            non_native_fpr=0.10,  # 5x — matches the documented NNE risk direction
        )
        assert result.passed is False

    def test_exactly_one_zero_rate_is_an_infinite_disparity_not_a_pass(self):
        """One group never flagged and the other flagged 5% of the time is
        the most fairness-relevant small-sample case there is. It must fail,
        never collapse to ratio 1.0. This IS real signal (Task 6): verdict
        stays "fail", not "uninformative" — unlike the both-zero case, this
        is genuine evidence of disparity, not an absence of evidence."""
        result = evaluate_g6_fairness(native_fpr=0.0, non_native_fpr=0.05)
        assert result.passed is False
        assert result.verdict == "fail"
        assert result.detail["ratio_status"] == "one_group_zero"
        assert result.detail["ratio"] == float("inf")
        assert "infinite" in result.current_value.lower()
        # Direction-symmetric.
        mirrored = evaluate_g6_fairness(native_fpr=0.05, non_native_fpr=0.0)
        assert mirrored.passed is False
        assert mirrored.verdict == "fail"

    def test_both_rates_zero_is_undefined_not_a_pass(self):
        """Zero flags in both groups demonstrates no fairness — it is an
        absence of evidence, and must not render as a green gate. This is a
        genuinely can't-know outcome (Task 6): verdict is "uninformative",
        not "fail" — a "fail" would claim disparity evidence that isn't
        there."""
        result = evaluate_g6_fairness(native_fpr=0.0, non_native_fpr=0.0)
        assert result.passed is False
        assert result.verdict == "uninformative"
        assert result.detail["ratio_status"] == "undefined_both_zero"
        assert result.detail["ratio"] is None
        assert result.current_value.startswith("UNDEFINED")

    def test_medium_effect_size_is_surfaced_in_current_value(self):
        """The Welch bridge is contradicting evidence — _analyze_dimension
        would read a medium effect as NOT FAIR. The ratio stays the verdict
        (per spec), but the disagreement cannot hide in attach-only detail."""
        result = evaluate_g6_fairness(
            native_fpr=0.04,
            non_native_fpr=0.06,
            welch_effect_magnitude="medium",
            welch_cohens_d=0.504,
        )
        assert result.passed is True
        assert "medium" in result.current_value
        assert "0.504" in result.current_value

    def test_negligible_effect_size_adds_no_caveat(self):
        result = evaluate_g6_fairness(
            native_fpr=0.04,
            non_native_fpr=0.06,
            welch_effect_magnitude="negligible",
            welch_cohens_d=0.03,
        )
        assert "CAVEAT" not in result.current_value

    def test_informational_cannot_overwrite_verdict_bearing_detail(self):
        result = evaluate_g6_fairness(
            native_fpr=0.04,
            non_native_fpr=0.06,
            informational={"ratio": 999.0, "native_fpr": 999.0},
        )
        assert result.detail["ratio"] == pytest.approx(1.5)
        assert result.detail["native_fpr"] == pytest.approx(0.04)

    def test_unreachable_threshold_records_loud_skip_not_a_pass(self):
        """CRITICAL: 5 essays/author scored LOO gives typicality_n=4, whose
        p_central support is {0.2 … 1.0} — the 0.02 flag threshold cannot be
        crossed by construction, so 'zero flags in both groups' is vacuous."""
        result = _g6_unreachable_threshold_result(
            observed_n=4,
            threshold=0.02,
            n_native_scored=15,
            n_non_native_scored=10,
        )
        assert result.passed is False
        assert result.verdict == "uninformative"
        assert result.current_value == (
            "SKIPPED (threshold unreachable): p_central floor 1/(n+1)=0.200 at "
            "n=4, flag threshold 0.02 needs n>=49"
        )
        assert result.detail["min_typicality_n"] == 4
        assert result.detail["p_floor"] == pytest.approx(0.2)
        assert result.detail["threshold"] == 0.02
        assert result.detail["required_n"] == 49
        assert result.detail["n_native_scored"] == 15
        assert result.detail["n_non_native_scored"] == 10

    def test_short_group_message_names_both_groups_when_both_are_short(self):
        both = _g6_short_group_message(2, 1, 5)
        assert "native_english=true" in both and "native_english=false" in both
        only_non_native = _g6_short_group_message(15, 1, 5)
        assert "native_english=false" in only_non_native
        assert "native_english=true" not in only_non_native

    def test_insufficient_data_records_loud_skip_not_a_pass(self):
        """Honest-instrument convention: a corpus without enough
        native_english-annotated authentic entries must surface as a loud
        SKIPPED result — passed must NOT be silently true."""
        result = _g6_insufficient_data_result(
            "native_english=false group has 0 scored authentic entries (need >= 5)",
            n_native_scored=15,
            n_non_native_scored=0,
        )
        assert result.name == "G6"
        assert result.passed is False
        assert result.verdict == "uninformative"
        assert result.current_value.startswith("SKIPPED (insufficient data):")
        assert result.detail["n_non_native_scored"] == 0
        assert "0 scored authentic entries" in result.detail["missing"]

    def test_criterion_scopes_the_verdict_to_the_p_central_action(self):
        """Spec's G6 row also names the Phase-4 uniformity features. Those
        are recorded as measurement, not gated — the criterion string must
        say so plainly rather than implying full coverage."""
        criterion = evaluate_g6_fairness(0.04, 0.06).criterion
        assert "p_central action ONLY" in criterion
        assert "not gated" in criterion


class TestUniformitySliceSummary:
    def test_reports_per_group_means_and_flags_constant_features(self):
        summary = _uniformity_slice_summary(
            {
                True: [{"a": 0.5, "b": 0.1}, {"a": 0.5, "b": 0.3}],
                False: [{"a": 0.5, "b": 0.9}],
            }
        )
        assert summary["native_english_true_means"]["b"] == pytest.approx(0.2)
        assert summary["native_english_false_means"]["b"] == pytest.approx(0.9)
        # "a" never varies anywhere in the slice — a constant feature cannot
        # carry a fairness signal, and the Tier-18 bounds miscalibration makes
        # that a real possibility, so it is called out by name.
        assert summary["constant_across_slice"] == ["a"]
        assert summary["gated"] is False

    def test_empty_groups_do_not_raise(self):
        summary = _uniformity_slice_summary({True: [], False: []})
        assert summary["native_english_true_means"] == {}
        assert summary["constant_across_slice"] == []


class TestG2bParaphraseResistance:
    def test_passes_when_paraphrased_impostor_q_still_lower_than_holdout(self):
        result = evaluate_g2b_paraphrase_resistant(
            holdout_q=[0.5, 0.48, 0.5],
            paraphrased_impostor_q=[0.15, 0.1],
        )
        assert result.passed is True

    def test_fails_when_paraphrase_defeats_the_signal(self):
        """Documents the expected real-world outcome per the design spec's
        research review — this SHOULD fail with a naive implementation,
        which is itself the finding G2b exists to surface."""
        result = evaluate_g2b_paraphrase_resistant(
            holdout_q=[0.5, 0.48, 0.5],
            paraphrased_impostor_q=[0.6, 0.55],  # paraphrase raised q above holdout
        )
        assert result.passed is False

    def test_criterion_and_detail_label_the_mechanical_proxy(self):
        """Standing decision: G2b must never be presentable as an
        LLM-paraphrase robustness claim. Both the criterion string and the
        detail must carry the proxy label."""
        result = evaluate_g2b_paraphrase_resistant(
            holdout_q=[0.5], paraphrased_impostor_q=[0.1]
        )
        proxy_label = "paraphrase proxy (mechanical transformation, not LLM paraphrase)"
        assert proxy_label in result.criterion
        assert proxy_label in result.detail["proxy_note"]

    def test_proxy_note_states_the_measured_limits_of_the_transform(self):
        """The reviewer measured them: ~1% of tokens substituted, and three
        of the six Tier-18 features invariant by construction. Those numbers
        belong in the gate's own report, not in a review thread."""
        note = evaluate_g2b_paraphrase_resistant([0.5], [0.1]).detail["proxy_note"]
        assert "~1% of tokens" in note
        assert "sentence_length_dispersion_ratio" in note
        assert "punctuation_dispersion_ratio" in note
        assert "clause_depth_variance_ratio" in note
        assert "invariant" in note

    def test_informational_cannot_overwrite_the_proxy_note(self):
        result = evaluate_g2b_paraphrase_resistant(
            [0.5], [0.1], informational={"proxy_note": "validated against real attacks"}
        )
        assert "not LLM paraphrase" in result.detail["proxy_note"]

    def test_paraphrase_proxy_is_deterministic_and_rewrites_the_text(self):
        text = (
            "This point is important. However, the essay shows that we use "
            "many words. Therefore we think the argument is very good."
        )
        out1 = _paraphrase_proxy(text)
        out2 = _paraphrase_proxy(text)
        assert out1 == out2  # deterministic — no hidden randomness
        assert out1 != text  # actually transforms the input

    def test_paraphrase_proxy_preserves_paragraph_structure(self):
        """The first cut split on sentences and rejoined with single spaces,
        collapsing every 6-paragraph essay to 1 — which moved
        avg_paragraph_length by 0.77 normalized and pushed two features to
        their 'cannot compute' placeholder, swamping the <=0.036 movement in
        the Tier-18 features the gate actually exists to stress."""
        text = (
            "Alpha one. Beta two.\n\n"
            "Gamma three. Delta four.\n\n"
            "Epsilon five. Zeta six."
        )
        out = _paraphrase_proxy(text)
        assert out.count("\n\n") == text.count("\n\n") == 2
        paragraphs = out.split("\n\n")
        assert len(paragraphs) == 3
        # Sentences swap WITHIN a paragraph, never across the boundary.
        assert paragraphs[0].startswith("Beta two.")
        assert paragraphs[1].startswith("Delta four.")
        assert "Gamma" not in paragraphs[0]

    def test_paraphrase_proxy_preserves_the_exact_original_separators(self):
        text = "One. Two.\n\n\nThree. Four.\n\nFive. Six."
        out = _paraphrase_proxy(text)
        assert "\n\n\n" in out
        assert out.count("\n") == text.count("\n")


class TestUniformityEnablementGuard:
    def test_restores_exact_prior_state_even_on_exception(self):
        """DISABLED_FEATURE_GROUPS is a process-global module-level set read
        at feature-extraction call time — a leaked discard('uniformity')
        would silently change every later leg's feature vectors. The guard
        must restore the exact prior state on both the clean and the
        exception path."""
        from original.constants import DISABLED_FEATURE_GROUPS

        before = set(DISABLED_FEATURE_GROUPS)
        try:
            # Clean path.
            with _uniformity_features_enabled():
                assert "uniformity" not in DISABLED_FEATURE_GROUPS
            assert DISABLED_FEATURE_GROUPS == before
            # Exception path.
            with pytest.raises(RuntimeError, match="boom"):
                with _uniformity_features_enabled():
                    assert "uniformity" not in DISABLED_FEATURE_GROUPS
                    raise RuntimeError("boom")
            assert DISABLED_FEATURE_GROUPS == before
        finally:
            # Belt-and-braces: never let THIS test leak state either.
            DISABLED_FEATURE_GROUPS.clear()
            DISABLED_FEATURE_GROUPS.update(before)


class TestG5MachineryErrors:
    def test_machinery_error_result_fails_without_masquerading_as_a_verdict(self):
        """run_all()'s G5 wrapper: a crash in the shuffled legs must render as
        a FAILED gate clearly labeled as a machinery error, so it can neither
        discard the four completed real gates nor read as a genuine null
        verdict."""
        result = _g5_machinery_error_result(
            RuntimeError("G5 shuffled G3 leg: zero successful scoring folds")
        )
        assert result.name == "G5"
        assert result.passed is False
        assert result.current_value.startswith("ERROR (machinery):")
        assert "zero successful scoring folds" in result.detail["machinery_error"]

    def test_run_g5_refuses_an_empty_real_deviation_sample(self):
        """The deviation-shift criterion needs the real leg's sample; an empty
        one is a machinery failure, not a comparison point."""
        with pytest.raises(RuntimeError):
            run_g5(real_g1_deviations=[])

    def test_run_g5_health_checks_the_real_anchor_leg(self):
        """A 4xx-riddled real G1 anchor (>10% scoring errors) must become a
        machinery error, not a silently weakened comparison baseline."""
        with pytest.raises(RuntimeError):
            run_g5(real_g1_deviations=[0.4] * 89, real_g1_n_errors=11)


from validation.power import conformal_p_floor


class TestGateVerdicts:
    def test_verdict_defaults_from_passed(self):
        r = GateResult(name="X", passed=True, criterion="c", current_value="v")
        assert r.verdict == "pass"
        r = GateResult(name="X", passed=False, criterion="c", current_value="v")
        assert r.verdict == "fail"

    def test_explicit_uninformative_verdict_sticks(self):
        r = GateResult(
            name="X", passed=False, criterion="c", current_value="v",
            verdict="uninformative",
        )
        assert r.verdict == "uninformative"
        assert r.passed is False


class TestG1Informativeness:
    def test_unreachable_band_turns_clean_pass_into_uninformative(self):
        actions = ["no_action"] * 216
        result = evaluate_g1_fpr(
            actions,
            per_corpus={"seminary": actions},
            entity_baseline_counts={"s1": 12, "s2": 8},
            band_threshold=0.03,
        )
        assert result.verdict == "uninformative"
        assert result.passed is False
        power = result.detail["power"]
        assert power["min_conformal_p_at_max_n"] == conformal_p_floor(12)
        assert power["entities_reachable"] == 0
        assert power["rule_of_three_fpr_upper"] == 3 / 216

    def test_reachable_entities_keep_a_clean_pass_informative(self):
        actions = ["no_action"] * 216
        result = evaluate_g1_fpr(
            actions,
            per_corpus={"seminary": actions},
            entity_baseline_counts={"s1": 40},
            band_threshold=0.03,
        )
        assert result.verdict == "pass"

    def test_a_real_failure_is_never_downgraded_to_uninformative(self):
        actions = ["monitor"] * 30 + ["no_action"] * 70
        result = evaluate_g1_fpr(
            actions,
            per_corpus={"seminary": actions},
            entity_baseline_counts={"s1": 12},
        )
        assert result.verdict == "fail"

    def test_omitting_counts_preserves_legacy_behavior(self):
        actions = ["no_action"] * 95 + ["monitor"] * 5
        result = evaluate_g1_fpr(actions, per_corpus={"synthetic": actions})
        assert result.verdict == "pass"
        assert result.passed is True


class TestG3Informativeness:
    """
    G1's arithmetic floor has a sampling-uncertainty twin. At n=22 held-out
    essays a G3 FAIL is real (CI upper 0.653 < 0.7) but a G3 PASS is not
    evidence (0.818 → CI [0.615, 0.927], straddling the bar).
    """

    def test_measured_failure_stays_a_real_failure(self):
        result = evaluate_g3_attribution(0.455, n_essays=22)
        assert result.verdict == "fail"
        assert result.detail["power"]["bar_decidable"] == "below"

    def test_pass_above_the_bar_is_uninformative_at_n22(self):
        result = evaluate_g3_attribution(18 / 22, n_essays=22)
        assert result.verdict == "uninformative"
        assert result.passed is False
        ci = result.detail["power"]["wilson_ci"]
        assert ci[0] < 0.7 < ci[1]

    def test_pass_is_informative_when_n_supports_it(self):
        result = evaluate_g3_attribution(230 / 306, n_essays=306)
        assert result.verdict == "pass"

    def test_omitting_n_preserves_legacy_behavior(self):
        assert evaluate_g3_attribution(0.9).verdict == "pass"
        assert evaluate_g3_attribution(0.455).verdict == "fail"
