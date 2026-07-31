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
    evaluate_g1_fpr,
    evaluate_g2_bland_impostor,
    evaluate_g5_permutation_null,
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
