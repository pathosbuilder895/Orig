"""Leakage-safe fusion of Original, impostor-null, and PAN style signals."""

from __future__ import annotations

from validation.benchmark.reproducibility import lock_environment

ENV_LOCK = lock_environment()

import json
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import numpy as np

from original.constants import ALL_FEATURE_CODES
from original.quantum.scoring import ScoringConfig, score
from original.quantum.state import BaselineSample, StudentState
from validation.stacked.fusion import Trial, assert_no_group_overlap, cllr, fit_grouped_fusion
from validation.verify.binary_auc import auc, brier, tpr_at_fpr
from validation.verify.feature_cache import extract_many
from validation.verify.null_models import fit_impostor_gaussian
from validation.verify.pan_corpus import DEFAULT_CACHE
from validation.verify.pan_style_expert import (
    SEED,
    StyleAuthor,
    TrialScores,
    _fit_representations,
    _labels,
    _operating_result,
    _per_author_auc,
    _score_partition,
    _signals,
    _threshold_at_fpr,
    load_author_partitions,
)


def trial_id(target_author: str, source_author: str, probe_index: int) -> str:
    return f"{target_author}|{source_author}|probe-{probe_index}"


def _build_states(authors: Sequence[StyleAuthor]) -> tuple[dict, dict, dict]:
    all_texts = [text for author in authors for text in author.baselines]
    all_texts += [text for author in authors for text in author.probes]
    vectors_by_text = extract_many(all_texts, progress_label="pan-stack")

    states = {}
    baseline_vectors = {}
    for author in authors:
        samples = []
        vectors = []
        for text in author.baselines:
            vector = vectors_by_text[text]
            vectors.append(vector)
            samples.append(
                BaselineSample(
                    text=text,
                    vector=vector,
                    provenance="verified",
                    auth_weight=1.0,
                    assignment=author.baseline_fandom,
                    submitted_at="2026-01-01",
                )
            )
        states[author.author_id] = StudentState(student_id=author.author_id, samples=samples)
        baseline_vectors[author.author_id] = vectors

    return (states, baseline_vectors, vectors_by_text)


def original_trial_signals(
    partitions: dict[str, Sequence[StyleAuthor]],
    *,
    peer_reference: Sequence[StyleAuthor],
) -> dict[str, dict[str, dict[str, float]]]:
    """Compute raw and peer-relative signals, scoring only within each split."""
    states, baseline_vectors, vectors_by_text = _build_states(peer_reference)
    peer_stats = {}
    for target in peer_reference:
        pool = [
            vector
            for source in peer_reference
            if source.author_id != target.author_id
            for vector in baseline_vectors[source.author_id]
        ]
        peer_stats[target.author_id] = fit_impostor_gaussian(pool)

    config = replace(ScoringConfig.from_env(), null_model="impostor")
    output = {}
    start = time.perf_counter()
    for partition_name, authors in partitions.items():
        rows = {}
        for target in authors:
            state = states[target.author_id]
            for source in authors:
                for probe_index, text in enumerate(source.probes):
                    vector = vectors_by_text[text]
                    feature_dict = dict(zip(ALL_FEATURE_CODES, vector))
                    identifier = trial_id(target.author_id, source.author_id, probe_index)
                    result = score(
                        state,
                        vector,
                        feature_dict,
                        submission_id=identifier,
                        impostor_stats=peer_stats[target.author_id],
                        scoring_config=config,
                    )
                    llr = result.authorship.llr_deviation_score
                    rows[identifier] = {
                        "raw_probability": float(result.authorship.authorship_probability),
                        "peer_probability": float(1.0 - llr),
                    }
        output[partition_name] = rows
        print(f"[pan-stack] {partition_name}: {len(rows)} Original trials", file=sys.stderr)
    print(f"[pan-stack] scoring completed in {time.perf_counter() - start:.1f}s", file=sys.stderr)
    return output


def _style_map(trials: Sequence[TrialScores]) -> dict[str, TrialScores]:
    result = {}
    for row in trials:
        identifier = trial_id(row.target_author, row.source_author, row.probe_index)
        if identifier in result:
            raise ValueError(f"duplicate style trial: {identifier}")
        result[identifier] = row
    return result


def combine_trials(
    style_trials: Sequence[TrialScores],
    original_signals: dict[str, dict[str, float]],
) -> list[Trial]:
    style = _style_map(style_trials)
    if set(style) != set(original_signals):
        missing_original = sorted(set(style) - set(original_signals))[:3]
        missing_style = sorted(set(original_signals) - set(style))[:3]
        raise ValueError(
            f"trial alignment failure: missing_original={missing_original}, missing_style={missing_style}"
        )
    combined = []
    for identifier in sorted(style):
        row = style[identifier]
        original = original_signals[identifier]
        combined.append(
            Trial(
                trial_id=identifier,
                author_id=row.target_author,
                work_id=f"{row.source_author}:probe-{row.probe_index}",
                label=row.label,
                signals={
                    "raw_probability": original["raw_probability"],
                    "peer_probability": original["peer_probability"],
                    "character_similarity": row.char_similarity,
                    "content_reduced_similarity": row.content_reduced_similarity,
                },
            )
        )
    return combined


def _summary(trials: Sequence[Trial], scores: np.ndarray) -> dict:
    labels = np.asarray([trial.label for trial in trials], dtype=np.int8)
    return {
        "auc": float(auc(labels, scores)),
        "brier": float(brier(labels, scores)),
        "cllr": float(cllr(labels, scores)),
        "tpr_at_fpr": {
            str(target): float(tpr_at_fpr(labels, scores, target))
            for target in (0.01, 0.05, 0.10)
        },
    }


def run_stack(
    *,
    cache_dir: Path = DEFAULT_CACHE,
    output_path: Path | None = None,
    n_style_development: int = 120,
    n_fusion_development: int = 20,
    n_threshold_calibration: int = 20,
    n_locked: int = 12,
) -> dict:
    partitions = load_author_partitions(
        cache_dir=cache_dir,
        n_development=n_style_development,
        n_calibration=n_fusion_development + n_threshold_calibration,
        n_locked=n_locked,
    )
    fusion_authors = partitions["calibration"][:n_fusion_development]
    threshold_authors = partitions["calibration"][n_fusion_development:]
    locked_authors = partitions["locked"]
    scoring_partitions = {
        "fusion_development": fusion_authors,
        "threshold_calibration": threshold_authors,
        "locked": locked_authors,
    }

    vectorizer, scaler = _fit_representations(partitions["development"])
    style_trials = {
        name: _score_partition(authors, vectorizer, scaler)
        for name, authors in scoring_partitions.items()
    }
    peer_reference = list(fusion_authors) + list(threshold_authors) + list(locked_authors)
    original = original_trial_signals(scoring_partitions, peer_reference=peer_reference)
    combined = {
        name: combine_trials(style_trials[name], original[name]) for name in scoring_partitions
    }
    assert_no_group_overlap(combined["fusion_development"], combined["locked"])
    assert_no_group_overlap(combined["threshold_calibration"], combined["locked"])

    signal_names = (
        "raw_probability",
        "peer_probability",
        "character_similarity",
        "content_reduced_similarity",
    )
    fusion = fit_grouped_fusion(
        combined["fusion_development"], signal_names=signal_names, n_splits=5, seed=SEED
    )
    calibration_probability = fusion.predict(combined["threshold_calibration"])
    locked_probability = fusion.predict(combined["locked"])
    calibration_labels = np.asarray(
        [trial.label for trial in combined["threshold_calibration"]], dtype=np.int8
    )
    locked_labels = np.asarray([trial.label for trial in combined["locked"]], dtype=np.int8)
    thresholds = {
        str(target): _threshold_at_fpr(calibration_labels, calibration_probability, target)
        for target in (0.01, 0.05, 0.10)
    }

    locked_metrics = {"stacked_fusion": _summary(combined["locked"], locked_probability)}
    for signal in signal_names[:2]:
        values = np.asarray([trial.signals[signal] for trial in combined["locked"]], dtype=np.float64)
        locked_metrics[signal] = _summary(combined["locked"], values)
    # Similarities are ranks rather than probabilities, so report AUC/ROC only.
    for signal in signal_names[2:]:
        values = np.asarray([trial.signals[signal] for trial in combined["locked"]], dtype=np.float64)
        locked_metrics[signal] = {
            "auc": float(auc(locked_labels, values)),
            "tpr_at_fpr": {
                str(target): float(tpr_at_fpr(locked_labels, values, target))
                for target in (0.01, 0.05, 0.10)
            },
        }

    logistic = fusion.estimator.named_steps["logistic"]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": ENV_LOCK.__dict__,
        "partitions": {name: [author.author_id for author in rows] for name, rows in scoring_partitions.items()},
        "signal_order": list(signal_names),
        "standardized_coefficients": logistic.coef_[0].tolist(),
        "intercept": float(logistic.intercept_[0]),
        "fusion_development_oof": _summary(
            combined["fusion_development"], fusion.oof_probability
        ),
        "threshold_calibration": _summary(
            combined["threshold_calibration"], calibration_probability
        ),
        "locked_metrics": locked_metrics,
        "thresholds": thresholds,
        "calibration_operating_points": {
            target: _operating_result(calibration_labels, calibration_probability, threshold)
            for target, threshold in thresholds.items()
        },
        "locked_operating_points": {
            target: _operating_result(locked_labels, locked_probability, threshold)
            for target, threshold in thresholds.items()
        },
    }
    report["promotion_gate"] = {
        "passed": False,
        "conditions": {
            "no_auc_regression_vs_style_only": locked_metrics["stacked_fusion"]["auc"] >= 0.88952,
            "no_strict_tpr_regression_vs_style_only": locked_metrics["stacked_fusion"]["tpr_at_fpr"]["0.01"] >= 0.472222,
            "at_least_30_locked_authors": n_locked >= 30,
            "at_least_100_locked_genuine_trials": int(locked_labels.sum()) >= 100,
        },
        "decision": "reject_four_channel_stack",
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run_stack(output_path=Path("validation/benchmarks/2026-08-04/pan_stacked_fusion.json"))
    print(json.dumps({"locked": result["locked_metrics"], "operating": result["locked_operating_points"]}, indent=2))
