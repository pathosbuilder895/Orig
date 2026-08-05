from __future__ import annotations

from dataclasses import replace

import numpy as np

from validation.cause.joint_stack import (
    CAUSES,
    CLAIMED_AUTHOR,
    DIRECT_AI,
    HUMANIZED_AI,
    HUMAN_IMPOSTOR,
    CauseTrial,
    _precision_thresholds,
    assess_enrolled_peer_gate,
    evaluate_selective_stack,
    evaluate_hierarchical_evidence,
    evaluate_enrolled_peer_identity,
)


def test_enrolled_peer_gate_requires_closed_set_precision_recall_and_support() -> None:
    passing = {
        "per_class": {"human_impostor": {"precision": 0.91, "recall": 0.30, "support": 100}}
    }
    gate = assess_enrolled_peer_gate(passing)
    assert gate["passed"]
    assert gate["outside_pool_policy"] == "unknown_writer"
    passing["per_class"]["human_impostor"]["recall"] = 0.29
    assert not assess_enrolled_peer_gate(passing)["passed"]


def test_peer_identity_gate_rejects_outside_writer_naming() -> None:
    calibration = [
        replace(
            _trial(HUMAN_IMPOSTOR, index, "calibration"),
            best_alternative_author=f"peer-{index}",
            true_source_author=f"peer-{index}",
            best_alternative_runner_up_margin=0.5,
        )
        for index in range(20)
    ]
    known = [replace(row, partition="locked") for row in calibration]
    outside = [
        replace(
            row,
            partition="outside",
            true_source_author=f"outside-{index}",
        )
        for index, row in enumerate(calibration)
    ]
    report = evaluate_enrolled_peer_identity(calibration, known, outside)
    assert report["known_enrolled_peer"]["precision_exact_identity"] == 1.0
    assert not report["promotion_gate"]["passed"]
    assert report["outside_pool"]["outside_writer_naming_rate"] == 1.0


def _trial(cause: str, index: int, partition: str) -> CauseTrial:
    centers = {
        CLAIMED_AUTHOR: (0.95, 0.05),
        HUMAN_IMPOSTOR: (0.05, 0.05),
        DIRECT_AI: (0.05, 0.95),
        HUMANIZED_AI: (0.05, 0.55),
    }
    style, ai = centers[cause]
    jitter = (index % 7 - 3) * 0.002
    return CauseTrial(
        partition,
        f"author-{index % 20}",
        f"source-{partition}-{cause}-{index}",
        cause,
        "text",
        style + jitter,
        ai + jitter,
        best_alternative_probability=(0.95 if cause == HUMAN_IMPOSTOR else 0.10),
        alternative_over_claimed_margin=(0.90 if cause == HUMAN_IMPOSTOR else -0.10),
        general_impostors_score=(0.05 if cause == HUMAN_IMPOSTOR else 0.95),
    )


def _partition(name: str, n: int = 80) -> list[CauseTrial]:
    return [_trial(cause, index, name) for cause in CAUSES for index in range(n)]


def test_precision_threshold_returns_disable_value_when_class_is_unsupported() -> None:
    labels = np.asarray([CLAIMED_AUTHOR] * 10 + [HUMAN_IMPOSTOR] * 10, dtype=object)
    probability = np.tile(np.asarray([[0.5, 0.5, 0.0, 0.0]]), (20, 1))
    thresholds = _precision_thresholds(labels, probability, np.asarray(CAUSES, dtype=object))
    assert thresholds[DIRECT_AI] == 1.01
    assert thresholds[HUMANIZED_AI] == 1.01


def test_selective_joint_stack_recovers_separable_causes() -> None:
    report, _, thresholds = evaluate_selective_stack(
        _partition("development"),
        _partition("calibration"),
        _partition("locked"),
    )
    assert set(thresholds) == set(CAUSES)
    assert report["promotion_gate"]["passed"]
    assert report["coverage"] == 1.0
    assert all(values["precision"] == 1.0 for values in report["per_class"].values())
    assert all(values["recall"] == 1.0 for values in report["per_class"].values())


def test_hierarchy_merges_ai_subtypes_without_mislabeling_human_impostor() -> None:
    calibration = _partition("calibration")
    locked = _partition("locked")
    report = evaluate_hierarchical_evidence(
        calibration,
        locked,
        strict_style_threshold=0.85,
    )
    assert report["promotion_gate"]["passed"]
    assert report["per_class"]["ai_origin_unknown_subtype"]["support"] == 160
    assert report["per_class"]["human_impostor"]["precision"] == 1.0
