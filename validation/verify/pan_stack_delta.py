"""Does adding Burrows'-Delta to the pan_stack fusion improve same-author
verification -- higher recall at a fixed low FPR, without raising it?

Reuses pan_stack.py's exact scoring/partitioning machinery (same
development/calibration/locked split, same LUAR-family style trials, same
peer-relative Original signals) so the two runs -- with and without Delta --
are a clean ablation, not two differently-built experiments. pan_stack.py's
own 4-channel stack was already rejected (see docs/research/
CROSS_WORK_AUTHORSHIP_FINDINGS_2026-08-04.md); this does not re-litigate
that verdict, it asks the one question that verdict didn't answer: does a
genuinely independent, never-tried signal change the outcome.

    .venv/bin/python -m validation.verify.pan_stack_delta
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
from validation.verify.binary_auc import auc, tpr_at_fpr
from validation.verify.delta_signals import delta_trial_signals
from validation.verify.pan_corpus import DEFAULT_CACHE
from validation.verify.pan_stack import _summary, combine_trials, original_trial_signals
from validation.verify.pan_style_expert import (
    SEED,
    _fit_representations,
    _score_partition,
    _threshold_at_fpr,
    load_author_partitions,
)


def _merge_delta(trials, delta_rows: dict[str, dict[str, float]]):
    merged = []
    missing = [t.trial_id for t in trials if t.trial_id not in delta_rows][:3]
    if missing:
        raise ValueError(f"delta signal missing for trials, e.g. {missing}")
    for trial in trials:
        signals = dict(trial.signals)
        signals.update(delta_rows[trial.trial_id])
        merged.append(dataclasses.replace(trial, signals=signals))
    return merged


def run(
    *,
    cache_dir: Path = DEFAULT_CACHE,
    output_path: Path | None = None,
    n_style_development: int = 120,
    n_fusion_development: int = 20,
    n_threshold_calibration: int = 20,
    n_locked: int = 12,
    fusion_fn=fit_grouped_fusion,
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

    print("[pan-stack-delta] fitting style representations...", file=sys.stderr)
    vectorizer, scaler = _fit_representations(partitions["development"])
    style_trials = {
        name: _score_partition(authors, vectorizer, scaler)
        for name, authors in scoring_partitions.items()
    }
    peer_reference = list(fusion_authors) + list(threshold_authors) + list(locked_authors)
    print("[pan-stack-delta] scoring Original signals...", file=sys.stderr)
    original = original_trial_signals(scoring_partitions, peer_reference=peer_reference)
    print("[pan-stack-delta] building Delta profiles...", file=sys.stderr)
    delta = delta_trial_signals(scoring_partitions)

    base_combined = {
        name: combine_trials(style_trials[name], original[name]) for name in scoring_partitions
    }
    delta_combined = {
        name: _merge_delta(base_combined[name], delta[name]) for name in scoring_partitions
    }
    assert_no_group_overlap(base_combined["fusion_development"], base_combined["locked"])
    assert_no_group_overlap(base_combined["threshold_calibration"], base_combined["locked"])

    base_signals = ("raw_probability", "peer_probability", "character_similarity", "content_reduced_similarity")
    delta_signal_names = base_signals + ("delta_neg_distance", "delta_peer_z")

    def _run_fusion(combined, signal_names, target_fpr=(0.01, 0.05, 0.10)):
        fusion = fusion_fn(
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

    print("[pan-stack-delta] fitting fusion WITHOUT delta (ablation baseline)...", file=sys.stderr)
    without_delta = _run_fusion(base_combined, base_signals)
    print("[pan-stack-delta] fitting fusion WITH delta...", file=sys.stderr)
    with_delta = _run_fusion(delta_combined, delta_signal_names)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": ENV_LOCK.__dict__,
        "partitions": {name: [a.author_id for a in rows] for name, rows in scoring_partitions.items()},
        "without_delta": without_delta,
        "with_delta": with_delta,
        "comparison": {
            "auc_delta": with_delta["locked_summary"]["auc"] - without_delta["locked_summary"]["auc"],
            "recall_at_1pct_fpr_delta": (
                with_delta["locked_operating_points"]["0.01"]["recall"]
                - without_delta["locked_operating_points"]["0.01"]["recall"]
            ),
            "note": (
                "Positive deltas favor adding Delta as a fifth/sixth fusion signal. "
                "Both runs share the identical dev/calibration/locked author split "
                "and the identical LUAR-family + Original base signals -- only the "
                "presence of the two Delta signals differs."
            ),
        },
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run(
        output_path=Path("validation/benchmarks/2026-08-05/pan_stack_delta_ablation.json")
    )
    print(json.dumps(result["comparison"], indent=2))
    print(
        "without_delta locked recall@1%:",
        result["without_delta"]["locked_operating_points"]["0.01"]["recall"],
    )
    print(
        "with_delta    locked recall@1%:",
        result["with_delta"]["locked_operating_points"]["0.01"]["recall"],
    )
