from __future__ import annotations

import numpy as np

from validation.cause.invariant_origin import (
    FEATURE_NAMES,
    NonNegativeLogistic,
    OriginRows,
    evaluate_domain_held,
    stable_feature_orientation,
)


def _fixture() -> OriginRows:
    X = []
    labels = []
    domains = []
    sources = []
    variants = []
    for domain_index, domain in enumerate(("a", "b", "c", "d")):
        for index in range(160):
            ai = index % 2 == 0
            row = np.zeros(len(FEATURE_NAMES), dtype=np.float64)
            row[0] = 3.0 if ai else -3.0  # stable in every domain
            # Corpus-specific nuisance reverses direction in alternating domains.
            row[1] = (2.0 if ai else -2.0) * (1 if domain_index % 2 == 0 else -1)
            row[-1] = 1.0 if ai else 0.0
            X.append(row)
            labels.append(ai)
            domains.append(domain)
            sources.append(f"{domain}:{index // 2}")
            variants.append("attacked" if ai else "human")
    return OriginRows(
        X=np.asarray(X),
        labels=np.asarray(labels),
        domains=np.asarray(domains, dtype=object),
        sources=np.asarray(sources, dtype=object),
        variants=np.asarray(variants, dtype=object),
    )


def test_nonnegative_logistic_never_learns_negative_feature_weights() -> None:
    X = np.asarray([[-2.0, 2.0], [-1.0, 1.0], [1.0, -1.0], [2.0, -2.0]])
    y = np.asarray([False, False, True, True])
    model = NonNegativeLogistic().fit(X, y)
    assert np.all(model.coef_ >= 0)
    assert model.coef_[0] > 0
    assert model.coef_[1] < 1e-8


def test_stability_filter_rejects_direction_reversal() -> None:
    data = _fixture()
    selected, _, audit = stable_feature_orientation(data.X, data.labels, data.domains)
    assert 0 in selected
    assert 1 not in selected
    assert any(row["feature"] == FEATURE_NAMES[0] for row in audit)


def test_domain_held_pipeline_has_no_source_overlap_and_recovers_stable_signal() -> None:
    result = evaluate_domain_held(_fixture())
    assert set(result["folds"]) == {"a", "b", "c", "d"}
    for fold in result["folds"].values():
        assert fold["locked_source_overlap"] == 0
        assert fold["constrained"]["auc"] == 1.0
        assert fold["constrained"]["human_fpr"] == 0.0
        assert fold["constrained"]["ai_tpr"] == 1.0
