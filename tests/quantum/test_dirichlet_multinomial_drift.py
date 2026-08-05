"""Validation-only Dirichlet-multinomial drift primitives."""

from __future__ import annotations

import numpy as np

from validation.longitudinal.dirichlet_multinomial import (
    compare_constant_and_drift,
    count_function_words,
)


def test_function_word_counts_include_every_token():
    vocabulary = ("and", "the", "to")
    counts = count_function_words("The cat and the dog went to town.", vocabulary)
    assert counts.tolist() == [1, 2, 1, 4]
    assert counts.sum() == 8


def test_constant_counts_do_not_require_drift():
    counts = np.array(
        [[40, 30, 20, 110], [42, 28, 21, 109], [39, 31, 19, 111], [41, 29, 20, 110],
         [40, 30, 21, 109], [41, 30, 19, 110], [39, 29, 22, 110], [40, 31, 20, 109]],
        dtype=float,
    )
    result = compare_constant_and_drift(counts)
    assert result.converged_constant
    assert result.selected_model == "constant"
    assert result.n_documents == 8


def test_strong_smooth_count_shift_improves_drift_fit():
    rows = []
    for i in range(14):
        rows.append([15 + 4 * i, 75 - 4 * i, 30, 180])
    result = compare_constant_and_drift(np.asarray(rows, dtype=float))
    assert result.converged_drift
    assert result.drift_log_likelihood > result.constant_log_likelihood
