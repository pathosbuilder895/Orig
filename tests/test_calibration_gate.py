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
    _g5_machinery_error_result,
    _g6_insufficient_data_result,
    _paraphrase_proxy,
    _require_healthy_leg,
    _uniformity_features_enabled,
    evaluate_g1_fpr,
    evaluate_g2_bland_impostor,
    evaluate_g2b_paraphrase_resistant,
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
    def test_passes_when_fpr_ratio_at_most_two(self):
        result = evaluate_g6_fairness(
            native_fpr=0.04,
            non_native_fpr=0.06,
        )
        assert result.passed is True

    def test_fails_when_fpr_ratio_exceeds_two(self):
        result = evaluate_g6_fairness(
            native_fpr=0.02,
            non_native_fpr=0.10,  # 5x — matches the documented NNE risk direction
        )
        assert result.passed is False

    def test_handles_zero_native_fpr_without_division_error(self):
        result = evaluate_g6_fairness(native_fpr=0.0, non_native_fpr=0.05)
        assert isinstance(result.passed, bool)

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
        assert result.current_value.startswith("SKIPPED (insufficient data):")
        assert result.detail["n_non_native_scored"] == 0
        assert "0 scored authentic entries" in result.detail["missing"]


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

    def test_paraphrase_proxy_is_deterministic_and_rewrites_the_text(self):
        text = (
            "This point is important. However, the essay shows that we use "
            "many words. Therefore we think the argument is very good."
        )
        out1 = _paraphrase_proxy(text)
        out2 = _paraphrase_proxy(text)
        assert out1 == out2  # deterministic — no hidden randomness
        assert out1 != text  # actually transforms the input


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
