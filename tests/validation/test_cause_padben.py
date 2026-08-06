from __future__ import annotations

import numpy as np
import pytest

from validation.cause.padben import (
    CAUSES,
    TYPE_FIELDS,
    bundle_padben_records,
    evaluate_ai_subtypes,
    evaluate_cause_matrix,
)


def _records() -> list[dict]:
    rows = []
    for source in ("a", "b"):
        for idx in range(4):
            row = {"idx": idx, "dataset_source": source}
            for fields in TYPE_FIELDS.values():
                for field in fields:
                    row[field] = f"{source} {idx} {field} sentence"
            rows.append(row)
    return rows


def test_bundles_preserve_paired_row_groups() -> None:
    bundles = bundle_padben_records(_records(), rows_per_bundle=2)
    assert len(bundles) == 2 * 2 * 5
    grouped = {}
    for bundle in bundles:
        grouped.setdefault((bundle.source, bundle.row_ids), set()).add(bundle.cause)
    assert all(causes == set(CAUSES) for causes in grouped.values())


def test_domain_held_out_evaluation_and_abstention() -> None:
    rng = np.random.default_rng(7)
    X, labels, sources = [], [], []
    centers = {"human": -2.0, "direct_ai": 0.0, "humanized_ai": 2.0}
    for source_shift, source in enumerate(("a", "b", "c")):
        for cause, center in centers.items():
            for _ in range(12):
                X.append(rng.normal(center + source_shift * 0.02, 0.1, size=3))
                labels.append(cause)
                sources.append(source)
    report = evaluate_cause_matrix(np.asarray(X), labels, sources)
    assert report["coverage"] > 0.9
    assert report["selective_accuracy"] > 0.95


def test_evaluation_rejects_single_source() -> None:
    with pytest.raises(ValueError, match="at least two"):
        evaluate_cause_matrix(np.zeros((3, 2)), list(CAUSES), ["one"] * 3)


def test_ai_subtype_selective_evaluation() -> None:
    rng = np.random.default_rng(9)
    X, labels, sources = [], [], []
    for source in ("a", "b", "c"):
        for cause, center, frozen in (("direct_ai", -2.0, 0.9), ("humanized_ai", 2.0, 0.85)):
            for _ in range(15):
                X.append([rng.normal(center, 0.15), frozen])
                labels.append(cause)
                sources.append(source)
    report = evaluate_ai_subtypes(np.asarray(X), labels, sources)
    assert report["coverage"] > 0.8
    assert report["selective_accuracy"] > 0.95
