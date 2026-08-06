"""Does adding LambdaG to the pan_stack fusion improve same-author
verification on top of the already-confirmed Delta gain (dbb97455,
f401172a)?

Three-way ablation, same discipline as pan_stack_delta.py: identical
development/calibration/locked author split, identical base signals
(raw/peer/character/content), only the added signal set differs between
runs.

    .venv/bin/python -m validation.verify.pan_stack_lambdag
"""

from __future__ import annotations

from validation.benchmark.reproducibility import lock_environment

ENV_LOCK = lock_environment()

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from validation.stacked.fusion import assert_no_group_overlap, fit_grouped_fusion
from validation.verify.delta_signals import delta_trial_signals
from validation.verify.lambdag_signals import lambdag_trial_signals
from validation.verify.pan_corpus import DEFAULT_CACHE
from validation.verify.pan_stack import _summary, combine_trials, original_trial_signals
from validation.verify.pan_style_expert import (
    SEED,
    _fit_representations,
    _score_partition,
    _threshold_at_fpr,
    load_author_partitions,
)


def _merge(trials, *signal_row_dicts):
    merged = []
    for trial in trials:
        signals = dict(trial.signals)
        for rows in signal_row_dicts:
            missing = [t.trial_id for t in trials if t.trial_id not in rows][:3]
            if missing:
                raise ValueError(f"signal missing for trials, e.g. {missing}")
            signals.update(rows[trial.trial_id])
        merged.append(dataclasses.replace(trial, signals=signals))
    return merged


def run(
    *,
    cache_dir: Path = DEFAULT_CACHE,
    output_path: Path | None = None,
    n_style_development: int = 20,
    n_fusion_development: int = 8,
    n_threshold_calibration: int = 8,
    n_locked: int = 10,
    lambdag_order: int = 10,
    lambdag_repetitions: int = 30,
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

    print("[pan-stack-lambdag] fitting style representations...", file=sys.stderr)
    vectorizer, scaler = _fit_representations(partitions["development"])
    style_trials = {
        name: _score_partition(authors, vectorizer, scaler)
        for name, authors in scoring_partitions.items()
    }
    peer_reference = list(fusion_authors) + list(threshold_authors) + list(locked_authors)
    print("[pan-stack-lambdag] scoring Original signals...", file=sys.stderr)
    original = original_trial_signals(scoring_partitions, peer_reference=peer_reference)
    print("[pan-stack-lambdag] building Delta profiles...", file=sys.stderr)
    delta = delta_trial_signals(scoring_partitions)
    print("[pan-stack-lambdag] building LambdaG grammars (slow: ~19s/candidate)...", file=sys.stderr)
    lambdag = lambdag_trial_signals(
        scoring_partitions, order=lambdag_order, repetitions=lambdag_repetitions
    )

    base_combined = {
        name: combine_trials(style_trials[name], original[name]) for name in scoring_partitions
    }
    delta_combined = {
        name: _merge(base_combined[name], delta[name]) for name in scoring_partitions
    }
    lambdag_combined = {
        name: _merge(base_combined[name], delta[name], lambdag[name]) for name in scoring_partitions
    }
    assert_no_group_overlap(base_combined["fusion_development"], base_combined["locked"])
    assert_no_group_overlap(base_combined["threshold_calibration"], base_combined["locked"])

    base_signals = ("raw_probability", "peer_probability", "character_similarity", "content_reduced_similarity")
    delta_signal_names = base_signals + ("delta_neg_distance", "delta_peer_z")
    lambdag_signal_names = delta_signal_names + ("lambdag_score",)

    def _run_fusion(combined, signal_names, target_fpr=(0.01, 0.05, 0.10)):
        fusion = fit_grouped_fusion(
            combined["fusion_development"], signal_names=signal_names, n_splits=5, seed=SEED
        )
        calibration_probability = fusion.predict(combined["threshold_calibration"])
        locked_probability = fusion.predict(combined["locked"])
        calibration_labels = np.asarray(
            [t.label for t in combined["threshold_calibration"]], dtype=np.int8
        )
        locked_labels = np.asarray([t.label for t in combined["locked"]], dtype=np.int8)
        thresholds = {
            str(t): _threshold_at_fpr(calibration_labels, calibration_probability, t)
            for t in target_fpr
        }
        operating = {}
        for target, threshold in thresholds.items():
            predicted = locked_probability >= threshold
            tp = int(np.sum(predicted & (locked_labels == 1)))
            fp = int(np.sum(predicted & (locked_labels == 0)))
            n_pos = int(np.sum(locked_labels == 1))
            n_neg = int(np.sum(locked_labels == 0))
            operating[target] = {
                "threshold": threshold,
                "precision": tp / max(1, tp + fp),
                "recall": tp / max(1, n_pos),
                "fpr": fp / max(1, n_neg),
                "n_locked_genuine": n_pos,
                "n_locked_impostor": n_neg,
            }
        logistic = fusion.estimator.named_steps["logistic"]
        return {
            "signal_names": list(signal_names),
            "standardized_coefficients": logistic.coef_[0].tolist(),
            "locked_summary": _summary(combined["locked"], locked_probability),
            "locked_operating_points": operating,
        }

    print("[pan-stack-lambdag] fitting fusion: base only...", file=sys.stderr)
    base_only = _run_fusion(base_combined, base_signals)
    print("[pan-stack-lambdag] fitting fusion: base + delta...", file=sys.stderr)
    with_delta = _run_fusion(delta_combined, delta_signal_names)
    print("[pan-stack-lambdag] fitting fusion: base + delta + lambdag...", file=sys.stderr)
    with_lambdag = _run_fusion(lambdag_combined, lambdag_signal_names)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": ENV_LOCK.__dict__,
        "partitions": {name: [a.author_id for a in rows] for name, rows in scoring_partitions.items()},
        "lambdag_hyperparameters": {"order": lambdag_order, "repetitions": lambdag_repetitions},
        "base_only": base_only,
        "with_delta": with_delta,
        "with_lambdag": with_lambdag,
        "comparison": {
            "auc_delta_vs_base": with_delta["locked_summary"]["auc"] - base_only["locked_summary"]["auc"],
            "auc_lambdag_vs_delta": with_lambdag["locked_summary"]["auc"] - with_delta["locked_summary"]["auc"],
            "recall_at_1pct_fpr_lambdag_vs_delta": (
                with_lambdag["locked_operating_points"]["0.01"]["recall"]
                - with_delta["locked_operating_points"]["0.01"]["recall"]
            ),
        },
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run(
        output_path=Path("validation/benchmarks/2026-08-05/pan_stack_lambdag_ablation.json")
    )
    print(json.dumps(result["comparison"], indent=2))
    for label in ("base_only", "with_delta", "with_lambdag"):
        op = result[label]["locked_operating_points"]
        print(
            f"{label}: AUC={result[label]['locked_summary']['auc']:.4f} "
            f"recall@1%={op['0.01']['recall']:.3f} recall@5%={op['0.05']['recall']:.3f}"
        )
