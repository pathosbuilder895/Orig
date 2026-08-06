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


def test_drift_is_selectable_at_the_real_vocabulary_width():
    """The BIC comparison must be able to reach `gradual_drift` at production width.

    The other tests here use 4-category toy matrices, where the drift model
    carries 8 parameters and L-BFGS-B settles easily. The real vocabulary is
    105 function words plus `other`, so the drift model carries 212 parameters
    and — with no analytic gradient — costs ~213 function evaluations per
    iteration. scipy's default maxfun of 15000 was therefore spent around
    iteration 63, the fit reported success=False, and compare_constant_and_drift's
    convergence guard returned "constant" no matter how strong the evidence:
    a planted drift worth +4227 BIC still came back constant. Nothing in the
    toy-width tests could see that, because 8 parameters never hit the ceiling.
    """
    from validation.longitudinal.dirichlet_multinomial import DEFAULT_VOCABULARY

    categories = len(DEFAULT_VOCABULARY) + 1
    base = np.random.default_rng(7).dirichlet(np.ones(categories) * 2.0)

    def corpus(drift_strength: float) -> np.ndarray:
        rng = np.random.default_rng(1)
        direction = rng.normal(size=categories)
        direction -= direction.mean()
        rows = []
        for i in range(12):
            t = i / 11
            probabilities = np.exp(np.log(base) + drift_strength * t * direction)
            probabilities /= probabilities.sum()
            rows.append(rng.multinomial(1000, probabilities))
        return np.asarray(rows, dtype=float)

    drifting = compare_constant_and_drift(corpus(4.0))
    assert drifting.converged_drift, "the drift fit must converge at production width"
    assert drifting.bic_improvement > 0
    assert drifting.selected_model == "gradual_drift"

    # The other half of the guarantee: real width must not manufacture drift
    # from a corpus that has none.
    steady = compare_constant_and_drift(corpus(0.0))
    assert steady.converged_drift
    assert steady.bic_improvement < 0
    assert steady.selected_model == "constant"


def test_real_dated_corpus_converges_and_stays_conservative():
    """Regression for the maxfun bug, pinned against real prose instead of a
    synthetic matrix: 8 Mark Twain novels, real 1869-1896 publication years
    (validation/longitudinal/smoke_corpus/, built by build_smoke_corpus.py).

    Before the maxfun fix, the drift model reported `success=False` on any
    fit at real vocabulary width (106 categories, 212 drift parameters) and
    `compare_constant_and_drift` silently fell back to "constant" regardless
    of the actual evidence. This asserts the fit now converges — and that on
    this particular corpus it still, correctly, does not manufacture drift:
    Twain's function-word usage across 27 years doesn't clear the BIC bar at
    n=8 documents, and the model should say so rather than guess.
    """
    import json
    from pathlib import Path

    from validation.longitudinal.dirichlet_multinomial import (
        permutation_false_selection_rate,
    )

    root = Path(__file__).resolve().parents[2] / "validation" / "longitudinal"
    manifest = json.loads((root / "smoke_manifest.json").read_text())
    entries = sorted(manifest["entries"], key=lambda e: e["submitted_at"])
    corpus = root / "smoke_corpus"

    counts = np.stack(
        [count_function_words((corpus / e["filename"]).read_text()) for e in entries]
    ).astype(float)
    years = np.array([int(e["submitted_at"][:4]) for e in entries], dtype=float)

    result = compare_constant_and_drift(counts, times=years)

    assert result.converged_constant
    assert result.converged_drift, "the drift fit must converge on real prose, not just toy matrices"
    assert result.n_categories == 106

    # Twain's real corpus genuinely doesn't clear the bar at this sample size —
    # both the BIC comparison and the permutation control should agree.
    assert result.selected_model == "constant"
    # Each repeat is a full 212-parameter fit; keep this small enough that the
    # test stays fast (20 repeats ~ a few seconds, not the ~1 minute 50 costs).
    assert permutation_false_selection_rate(counts, repeats=20) < 0.2
