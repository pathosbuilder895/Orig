import numpy as np
import pytest

from validation.verify.pan_official_metrics import (
    auc,
    binarize,
    brier,
    c_at_1,
    evaluate_all,
    evaluate_answers,
    f1,
    f_05_u,
)


# Hand-computed case. Problems 1 and 5 are unanswered (exactly 0.5).
# Answered: 0 right (0.9, same), 2 right (0.2, different),
#           3 wrong (0.7, different), 4 wrong (0.4, same).
TRUTH = [1, 1, 0, 0, 1, 0]
PRED = [0.9, 0.5, 0.2, 0.7, 0.4, 0.5]


def test_c_at_1_hand_computed():
    # nc=2, nu=2, n=6: (2 + 2*2/6) / 6
    assert c_at_1(TRUTH, PRED) == pytest.approx((2 + 4 / 6) / 6)


def test_f1_drops_non_answers():
    # Answered truth [1,0,0,1] vs predicted [1,0,1,0]: tp=1 fp=1 fn=1.
    assert f1(TRUTH, PRED) == pytest.approx(0.5)


def test_f_05_u_counts_non_answers_as_quarter_weight_false_negatives():
    # tp=1 fp=1 fn=1 u=2: 1.25 / (1.25 + 0.25*(1+2) + 1)
    assert f_05_u(TRUTH, PRED) == pytest.approx(1.25 / 3.0)


def test_brier_complement_hand_computed():
    # Squared errors .01 .25 .04 .49 .36 .25 sum to 1.40.
    assert brier(TRUTH, PRED) == pytest.approx(1 - 1.40 / 6)


def test_auc_counts_ties_as_half():
    # Same-author scores {.9,.5,.4} vs different {.2,.7,.5}: 5.5 of 9 orderings.
    assert auc(TRUTH, PRED) == pytest.approx(5.5 / 9)


def test_evaluate_all_rounds_and_averages_like_the_evaluator():
    exact = evaluate_all(TRUTH, PRED, digits=None)
    five = (5.5 / 9 + (2 + 4 / 6) / 6 + 1.25 / 3 + 0.5 + (1 - 1.40 / 6)) / 5
    four = (5.5 / 9 + (2 + 4 / 6) / 6 + 1.25 / 3 + 0.5) / 4
    assert exact["overall"] == pytest.approx(five)
    assert exact["overall_pan20_master"] == pytest.approx(four)
    rounded = evaluate_all(TRUTH, PRED)
    assert rounded == {
        "auc": 0.611,
        "c@1": 0.444,
        "f_05_u": 0.417,
        "F1": 0.5,
        "brier": 0.767,
        "overall": 0.548,
        "overall_pan20_master": 0.493,
    }


def test_rounding_follows_the_type_the_evaluator_rounds():
    # AUC 0.7875 (63 of 80 orderings) is the double just below 0.7875. The
    # evaluator rounds sklearn's np.float64 with numpy's half-to-even scaling
    # (0.788); Python's exact round of a float would give 0.787.
    # Discordant orderings: 7 x 2 (0.9 under 0.95) + 3 (0.3 under 0.95, 0.95, 0.4) = 17.
    truth = [1] * 8 + [0] * 10
    positives = [0.9] * 7 + [0.3]
    negatives = [0.95, 0.95, 0.4] + [0.2] * 7
    pred = positives + negatives
    assert auc(truth, pred) == pytest.approx(63 / 80)
    assert round(63 / 80, 3) == 0.787
    assert evaluate_all(truth, pred)["auc"] == 0.788


def test_all_unanswered_scores_quarter_overall():
    result = evaluate_all([1, 0, 1, 0], [0.5] * 4)
    assert result["auc"] == 0.5
    assert result["c@1"] == 0.0
    assert result["F1"] == 0.0
    assert result["f_05_u"] == 0.0
    assert result["brier"] == 0.75
    assert result["overall"] == 0.25


def test_perfect_answers_score_one_everywhere():
    result = evaluate_all([1, 0, 1, 0], [1.0, 0.0, 1.0, 0.0])
    assert all(value == 1.0 for value in result.values())


def test_c_at_1_rewards_abstaining_over_a_wrong_answer():
    assert c_at_1([1, 0], [0.9, 0.5]) == pytest.approx(0.75)
    assert c_at_1([1, 0], [0.9, 0.6]) == pytest.approx(0.5)


def test_out_of_range_score_zeroes_brier_like_the_evaluator():
    assert brier([1, 0], [1.2, 0.1]) == 0.0
    assert auc([1, 0], [1.2, 0.1]) == 1.0


def test_binarize_two_and_three_valued():
    np.testing.assert_array_equal(binarize([0.2, 0.5, 0.8]), [0, 1, 1])
    np.testing.assert_array_equal(binarize([0.2, 0.5, 0.8], triple_valued=True), [0, 0.5, 1])


def test_non_finite_and_empty_inputs_are_refused():
    with pytest.raises(ValueError):
        evaluate_all([1, 0], [np.nan, 0.2])
    with pytest.raises(ValueError):
        evaluate_all([], [])
    with pytest.raises(ValueError):
        evaluate_all([1, 0], [0.2])


def _reference_c_at_1(true_y, pred_y):
    """Line-for-line transcription of the official evaluator's loop."""
    n = float(len(pred_y))
    nc, nu = 0.0, 0.0
    for gt_score, pred_score in zip(true_y, pred_y):
        if pred_score == 0.5:
            nu += 1
        elif (pred_score > 0.5) == (gt_score > 0.5):
            nc += 1.0
    return (1 / n) * (nc + (nu * nc / n))


def _reference_f_05_u(true_y, pred_y, pos_label=1, threshold=0.5):
    pred_y = binarize(pred_y, triple_valued=True)
    n_tp = n_fn = n_fp = n_u = 0
    for i, pred in enumerate(pred_y):
        if pred == threshold:
            n_u += 1
        elif pred == pos_label and pred == true_y[i]:
            n_tp += 1
        elif pred == pos_label and pred != true_y[i]:
            n_fp += 1
        elif true_y[i] == pos_label and pred != true_y[i]:
            n_fn += 1
    return (1.25 * n_tp) / (1.25 * n_tp + 0.25 * (n_fn + n_u) + n_fp)


def test_vectorised_measures_match_the_evaluator_loops_on_random_scores():
    rng = np.random.default_rng(1729)
    for _ in range(50):
        n = int(rng.integers(5, 60))
        truth = rng.integers(0, 2, size=n).astype(float)
        pred = np.round(rng.random(n), 1)  # rounding to 0.1 produces exact 0.5s
        assert c_at_1(truth, pred) == pytest.approx(_reference_c_at_1(truth, pred))
        assert f_05_u(truth, pred) == pytest.approx(_reference_f_05_u(truth, pred))


def test_evaluate_answers_fills_missing_answers_with_half():
    truth = {"b": 1, "a": 0, "c": 1}
    result = evaluate_answers(truth, {"a": 0.1, "b": 0.9}, digits=None)
    assert result["n_problems"] == 3
    assert result["n_unanswered"] == 1
    assert result["n_same_author"] == 2
    assert result["c@1"] == pytest.approx((2 + 1 * 2 / 3) / 3)
    with pytest.raises(ValueError):
        evaluate_answers(truth, {"z": 0.4})
