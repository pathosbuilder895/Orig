"""PAN authorship-verification measures, matching the official evaluator.

Mirrors ``pan20_verif_evaluator.py`` as shipped in ``pan-webis-de/pan-code``
under ``clef21/authorship-verification`` (the same five measures, unchanged,
are in ``clef23/authorship-verification/evaluator/evaluator.py``). The
``clef20`` copy on that repository's master branch computes only the first
four; its ``overall`` is the mean of four, not five. This module reports
both so a PAN 2020 table can be read either way.

Conventions copied from the evaluator, including its quirks:

* A score of exactly 0.5 is a non-answer.
* A problem in the truth file with no answer is scored 0.5.
* AUC is ``roc_auc_score`` over every problem, non-answers included; a
  ``ValueError`` from scikit-learn becomes 0.0.
* c@1 = (nc + nu * nc / n) / n.
* F1 drops non-answers, then binarises at ``>= 0.5``.
* F0.5u counts non-answers as false negatives at a quarter weight.
* The Brier measure is ``1 - brier_score_loss``, so higher is better; a
  ``ValueError`` (for example a score outside [0, 1]) becomes 0.0.
* ``overall`` is the unrounded mean; every reported value is then rounded to
  three decimals, as the evaluator prints them, with numpy's rounding for the
  values it receives as ``np.float64`` (see ``_round_like_evaluator``).

One deliberate difference: non-finite scores are rejected here. The evaluator
masks them (``np.ma.fix_invalid``), and a masked value then compares falsy, so
a NaN is neither an answer nor a non-answer in F0.5u while AUC and Brier
collapse to 0.0. No verifier scored here emits one, so refusing is safer than
copying that.

Nothing in this module is imported by the live API.
"""

from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np
from sklearn.metrics import brier_score_loss, f1_score, roc_auc_score

UNANSWERED = 0.5
MEASURES = ("auc", "c@1", "f_05_u", "F1", "brier")
PAN20_MASTER_MEASURES = ("auc", "c@1", "f_05_u", "F1")
NUMPY_ROUNDED = frozenset({"auc", "brier", "overall", "overall_pan20_master"})


def binarize(y: Sequence[float], threshold: float = 0.5, triple_valued: bool = False) -> np.ndarray:
    values = np.array(y, dtype=np.float64)
    if triple_valued:
        values[values > threshold] = 1
    else:
        values[values >= threshold] = 1
    values[values < threshold] = 0
    return values


def auc(true_y: Sequence[float], pred_y: Sequence[float]) -> float:
    try:
        return float(roc_auc_score(true_y, pred_y))
    except ValueError:
        return 0.0


def c_at_1(true_y: Sequence[float], pred_y: Sequence[float]) -> float:
    true = np.asarray(true_y, dtype=np.float64)
    pred = np.asarray(pred_y, dtype=np.float64)
    n = float(len(pred))
    unanswered = pred == UNANSWERED
    correct = (~unanswered) & ((pred > 0.5) == (true > 0.5))
    nc, nu = float(correct.sum()), float(unanswered.sum())
    return (1 / n) * (nc + (nu * nc / n))


def f1(true_y: Sequence[float], pred_y: Sequence[float]) -> float:
    true = np.asarray(true_y, dtype=np.float64)
    pred = np.asarray(pred_y, dtype=np.float64)
    answered = pred != UNANSWERED
    return float(f1_score(true[answered], binarize(pred[answered])))


def f_05_u(true_y: Sequence[float], pred_y: Sequence[float]) -> float:
    true = np.asarray(true_y, dtype=np.float64)
    pred = binarize(pred_y, triple_valued=True)
    unanswered = pred == UNANSWERED
    n_tp = int(np.sum((pred == 1) & (true == 1)))
    n_fp = int(np.sum((pred == 1) & (true != 1)))
    n_fn = int(np.sum(~unanswered & (pred != 1) & (true == 1)))
    n_u = int(unanswered.sum())
    return (1.25 * n_tp) / (1.25 * n_tp + 0.25 * (n_fn + n_u) + n_fp)


def brier(true_y: Sequence[float], pred_y: Sequence[float]) -> float:
    try:
        return float(1 - brier_score_loss(true_y, pred_y))
    except ValueError:
        return 0.0


def evaluate_all(
    true_y: Sequence[float], pred_y: Sequence[float], *, digits: int | None = 3
) -> dict[str, float]:
    """The evaluator's ``evaluate_all``, plus the four-measure PAN 2020 mean."""

    if len(true_y) != len(pred_y) or not len(pred_y):
        raise ValueError("truth and predictions must be non-empty and the same length")
    if not np.isfinite(np.asarray(pred_y, dtype=np.float64)).all():
        raise ValueError("non-finite score; see the module docstring")
    results = {
        "auc": auc(true_y, pred_y),
        "c@1": c_at_1(true_y, pred_y),
        "f_05_u": f_05_u(true_y, pred_y),
        "F1": f1(true_y, pred_y),
        "brier": brier(true_y, pred_y),
    }
    results["overall"] = float(np.mean([results[name] for name in MEASURES]))
    results["overall_pan20_master"] = float(
        np.mean([results[name] for name in PAN20_MASTER_MEASURES])
    )
    if digits is not None:
        results = {name: _round_like_evaluator(name, value, digits) for name, value in results.items()}
    return results


def _round_like_evaluator(name: str, value: float, digits: int) -> float:
    """``round(v, 3)`` as the evaluator sees ``v``.

    scikit-learn's AUC and Brier loss, and the evaluator's ``np.mean``, come
    back as ``np.float64``, whose ``round`` scales and rounds half to even;
    c@1, F0.5u and F1 come back as Python floats, whose ``round`` is exact.
    The two disagree when a value sits on a half-thousandth (0.7875 rounds to
    0.788 one way and 0.787 the other).
    """

    if name in NUMPY_ROUNDED:
        return float(round(np.float64(value), digits))
    return round(float(value), digits)


def evaluate_answers(
    truth: Mapping[str, float],
    answers: Mapping[str, float],
    *,
    digits: int | None = 3,
) -> dict[str, float | int]:
    """Score an answers mapping against a truth mapping, as the evaluator does.

    ``truth`` maps problem id to 0/1 (``same``); ``answers`` maps problem id to
    a score in [0, 1]. Ids are visited in sorted order, missing answers become
    0.5, and an answer for an id that is not in the truth is an error.
    """

    extra = set(answers) - set(truth)
    if extra:
        raise ValueError(f"answers for {len(extra)} problems not in the truth file")
    ids = sorted(truth)
    true_y = np.asarray([float(truth[key]) for key in ids], dtype=np.float64)
    pred_y = np.asarray([float(answers.get(key, UNANSWERED)) for key in ids], dtype=np.float64)
    result: dict[str, float | int] = dict(evaluate_all(true_y, pred_y, digits=digits))
    result["n_problems"] = len(ids)
    result["n_unanswered"] = int(np.sum(pred_y == UNANSWERED))
    result["n_same_author"] = int(np.sum(true_y == 1))
    return result
