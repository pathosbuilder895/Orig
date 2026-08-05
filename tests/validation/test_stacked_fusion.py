from __future__ import annotations

import numpy as np
import pytest

from validation.stacked import (
    Trial,
    assert_no_group_overlap,
    cllr,
    fit_grouped_fusion,
    select_cause,
)


def _trials() -> list[Trial]:
    rows = []
    for author_idx in range(8):
        for genuine in (0, 1):
            for repeat in range(3):
                # Genuine values are high for claimed-author/conformal and low
                # for AI. Some unavailable AI signals exercise missing flags.
                rows.append(
                    Trial(
                        trial_id=f"{author_idx}-{genuine}-{repeat}",
                        author_id=f"author-{author_idx}",
                        work_id=f"work-{author_idx}-{repeat}",
                        label=genuine,
                        signals={
                            "claimed": 0.85 if genuine else 0.15,
                            "conformal": 0.75 if genuine else 0.25,
                            "ai": None if repeat == 0 else (0.1 if genuine else 0.7),
                        },
                    )
                )
    return rows


def test_grouped_fusion_is_out_of_fold_and_predicts() -> None:
    trials = _trials()
    result = fit_grouped_fusion(trials, n_splits=4)
    assert len(result.oof_probability) == len(trials)
    assert np.all((result.oof_probability >= 0) & (result.oof_probability <= 1))
    for author in {t.author_id for t in trials}:
        folds = {result.fold_by_trial[i] for i, t in enumerate(trials) if t.author_id == author}
        assert len(folds) == 1
    labels = [t.label for t in trials]
    assert cllr(labels, result.oof_probability) < 1.0
    assert result.predict(trials[:2]).shape == (2,)


def test_overlap_guard_checks_author_and_work() -> None:
    dev = _trials()[:2]
    with pytest.raises(ValueError, match="author leakage"):
        assert_no_group_overlap(dev, [dev[0]])
    locked = [Trial("x", "new-author", dev[0].work_id, 1, {"x": 1.0})]
    with pytest.raises(ValueError, match="work leakage"):
        assert_no_group_overlap(dev, locked)


def test_cllr_reference_values() -> None:
    assert cllr([1, 0], [0.5, 0.5]) == pytest.approx(1.0)
    assert cllr([1, 0], [0.99, 0.01]) < 0.02


def test_cause_selection_abstains_on_weak_or_ambiguous_evidence() -> None:
    chosen = select_cause({"human_impostor": 0.1, "direct_ai": 0.82, "humanized_ai": 0.08})
    assert chosen.label == "direct_ai" and not chosen.abstained
    weak = select_cause({"human_impostor": 0.4, "direct_ai": 0.35})
    assert weak.label == "unknown_other" and weak.abstained
    close = select_cause({"direct_ai": 0.78, "humanized_ai": 0.72})
    assert close.label == "unknown_other" and close.abstained
