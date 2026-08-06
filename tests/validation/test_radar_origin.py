import json

import numpy as np

from validation.cause.faid import DIRECT_AI, HUMAN
from validation.cause.radar_origin import (
    OriginTrial,
    load_padben_task5,
    orient_and_calibrate,
    summarize,
)


def _trial(cause: str, source: str, variant: str = "none") -> OriginTrial:
    return OriginTrial(f"text {source}", cause, source, variant)


def test_orientation_and_threshold_use_source_disjoint_humans():
    trials = []
    probabilities = []
    for index in range(100):
        cause = HUMAN if index % 2 == 0 else DIRECT_AI
        trials.append(_trial(cause, f"source-{index}"))
        ai = 0.1 if cause == HUMAN else 0.9
        probabilities.append([1 - ai, ai])
    result = orient_and_calibrate(trials, np.asarray(probabilities))
    assert result["ai_class_index"] == 1
    assert result["development_auc"] == 1.0
    assert result["source_overlap"] == 0
    assert result["threshold"] > 0.1


def test_summary_reports_merged_and_variant_recall():
    trials = [
        _trial(HUMAN, "h1", "human"),
        _trial(HUMAN, "h2", "human"),
        _trial(DIRECT_AI, "a1", "direct"),
        _trial(DIRECT_AI, "a2", "humanized"),
    ]
    report = summarize(trials, np.asarray([0.1, 0.2, 0.9, 0.8]), 0.5)
    assert report["precision"] == 1.0
    assert report["recall"] == 1.0
    assert report["human_fpr"] == 0.0
    assert set(report["variant_recall"]) == {"direct", "humanized"}


def test_padben_task5_bundles_are_balanced_and_deterministic(tmp_path):
    rows = [
        {"idx": index, "sentence": f"sentence {index}", "label": index % 2}
        for index in range(24)
    ]
    path = tmp_path / "task5.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    first = load_padben_task5(path, bundles_per_class=2, rows_per_bundle=6)
    second = load_padben_task5(path, bundles_per_class=2, rows_per_bundle=6)
    assert first == second
    assert len(first) == 4
    assert sum(trial.cause == HUMAN for trial in first) == 2
    assert all(len(trial.text.split("sentence")) == 7 for trial in first)
