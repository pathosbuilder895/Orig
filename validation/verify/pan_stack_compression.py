"""Does adding a character-LM / compression channel to the pan_stack fusion
improve same-author verification on top of the existing four base signals?

Same discipline as pan_stack_delta.py and pan_stack_lambdag.py: identical
development / calibration / locked author split, identical base signals
(raw/peer probability + LUAR-family character/content similarity), and the
identical fusion helper (``fit_grouped_fusion``, fixed C=0.5 -- the one the
lambdag runner uses, so this ablation is apples-to-apples with that one).
Only the added signal set differs between arms.

Hyperparameters (character LM order, peer-pool size, NCD backend and
truncation) were selected on the ``fusion_development`` partition alone --
see ``HYPERPARAMETER_PROVENANCE`` below. The locked partition is read once,
at scoring time, and never used to choose anything.

    .venv/bin/python -m validation.verify.pan_stack_compression
"""

from __future__ import annotations

from validation.benchmark.reproducibility import lock_environment

ENV_LOCK = lock_environment()

import dataclasses
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

from validation.stacked.fusion import assert_no_group_overlap, fit_grouped_fusion
from validation.verify.compression_signals import (
    abstention_rate,
    compression_trial_signals,
)
from validation.verify.pan_corpus import DEFAULT_CACHE
from validation.verify.pan_stack import _summary, combine_trials, original_trial_signals
from validation.verify.pan_style_expert import (
    SEED,
    _fit_representations,
    _score_partition,
    _threshold_at_fpr,
    load_author_partitions,
)

BASE_SIGNALS = (
    "raw_probability",
    "peer_probability",
    "character_similarity",
    "content_reduced_similarity",
)

HYPERPARAMETER_PROVENANCE = (
    "order=4, peer_pool_chars=200000, ncd_backend=zlib, ncd_max_chars=16000. "
    "Chosen by standalone signal AUC on the fusion_development partition only "
    "(orders 3/4/5/6 -> compression_delta AUC 0.859/0.877/0.869/0.878; peer "
    "pool matched/100k/200k/400k -> 0.877/0.881/0.884/0.885, 200k taken as the "
    "largest value reachable in all three partitions; NCD zlib@16k/lzma@16k/"
    "zlib@8k -> 0.885/0.870/0.834). The locked partition was not scored during "
    "selection. ncd_max_chars=16000 is additionally bounded a priori by "
    "DEFLATE's 32 KiB window, not by any measurement."
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
    n_style_development: int = 120,
    n_fusion_development: int = 20,
    n_threshold_calibration: int = 20,
    n_locked: int = 12,
    compression_order: int = 4,
    peer_pool_chars: int | None = 200_000,
    ncd_backend: str = "zlib",
    ncd_max_chars: int = 16_000,
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

    print("[pan-stack-compression] fitting style representations...", file=sys.stderr)
    vectorizer, scaler = _fit_representations(partitions["development"])
    style_trials = {
        name: _score_partition(authors, vectorizer, scaler)
        for name, authors in scoring_partitions.items()
    }
    peer_reference = list(fusion_authors) + list(threshold_authors) + list(locked_authors)
    print("[pan-stack-compression] scoring Original signals...", file=sys.stderr)
    original = original_trial_signals(scoring_partitions, peer_reference=peer_reference)
    print("[pan-stack-compression] building character LMs...", file=sys.stderr)
    compression = compression_trial_signals(
        scoring_partitions,
        order=compression_order,
        peer_pool_chars=peer_pool_chars,
        ncd_backend=ncd_backend,
        ncd_max_chars=ncd_max_chars,
    )

    base_combined = {
        name: combine_trials(style_trials[name], original[name]) for name in scoring_partitions
    }
    compression_combined = {
        name: _merge(base_combined[name], compression[name]) for name in scoring_partitions
    }
    assert_no_group_overlap(base_combined["fusion_development"], base_combined["locked"])
    assert_no_group_overlap(base_combined["threshold_calibration"], base_combined["locked"])

    arms = {
        "base_only": (base_combined, BASE_SIGNALS),
        "with_compression_delta": (
            compression_combined,
            BASE_SIGNALS + ("compression_delta",),
        ),
        "with_compression_delta_ncd": (
            compression_combined,
            BASE_SIGNALS + ("compression_delta", "compression_ncd"),
        ),
        "with_compression_all": (
            compression_combined,
            BASE_SIGNALS + ("compression_delta", "compression_h_author", "compression_ncd"),
        ),
    }

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
            "fusion_development_oof": _summary(
                combined["fusion_development"], fusion.oof_probability
            ),
            "locked_summary": _summary(combined["locked"], locked_probability),
            "locked_operating_points": operating,
        }

    results = {}
    for name, (combined, signal_names) in arms.items():
        print(f"[pan-stack-compression] fitting fusion: {name}...", file=sys.stderr)
        results[name] = _run_fusion(combined, signal_names)

    base = results["base_only"]
    augmented = results["with_compression_delta"]

    def _gate(candidate: dict) -> dict:
        d_auc = candidate["locked_summary"]["auc"] - base["locked_summary"]["auc"]
        d_cllr = candidate["locked_summary"]["cllr"] - base["locked_summary"]["cllr"]
        d_recall_1 = (
            candidate["locked_operating_points"]["0.01"]["recall"]
            - base["locked_operating_points"]["0.01"]["recall"]
        )
        criteria = {
            "cllr_strictly_improves": bool(d_cllr < 0.0),
            "auc_gain_at_least_0.005": bool(d_auc >= 0.005),
            "recall_at_1pct_fpr_does_not_regress": bool(d_recall_1 >= 0.0),
        }
        return {
            "delta_auc": d_auc,
            "delta_cllr": d_cllr,
            "delta_recall_at_1pct_fpr": d_recall_1,
            "delta_recall_at_5pct_fpr": (
                candidate["locked_operating_points"]["0.05"]["recall"]
                - base["locked_operating_points"]["0.05"]["recall"]
            ),
            "criteria": criteria,
            "verdict": "PASS" if all(criteria.values()) else "FAIL",
        }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": ENV_LOCK.__dict__,
        "partitions": {
            name: [a.author_id for a in rows] for name, rows in scoring_partitions.items()
        },
        "hyperparameters": {
            "n_style_development": n_style_development,
            "n_fusion_development": n_fusion_development,
            "n_threshold_calibration": n_threshold_calibration,
            "n_locked": n_locked,
            "compression_order": compression_order,
            "peer_pool_chars": peer_pool_chars,
            "ncd_backend": ncd_backend,
            "ncd_max_chars": ncd_max_chars,
            "fusion_fn": fusion_fn.__name__,
            "seed": SEED,
            "provenance": HYPERPARAMETER_PROVENANCE,
        },
        "abstention_rate": {
            partition: {
                signal: abstention_rate(compression[partition], signal)
                for signal in ("compression_delta", "compression_h_author", "compression_ncd")
            }
            for partition in scoring_partitions
        },
        **results,
        "comparison": {
            "gate_G_P1": _gate(augmented),
            "with_compression_delta_ncd_vs_base": _gate(results["with_compression_delta_ncd"]),
            "with_compression_all_vs_base": _gate(results["with_compression_all"]),
            "note": (
                "Gate G-P1 is evaluated on with_compression_delta vs base_only. "
                "All arms share the identical author split, the identical base "
                "signals and the identical fusion helper; only the added signal "
                "set differs. The other two arms are reported for completeness "
                "and are NOT the gate."
            ),
        },
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run(
        output_path=Path(
            f"validation/benchmarks/{date.today().isoformat()}/pan_stack_compression_ablation.json"
        )
    )
    for label in (
        "base_only",
        "with_compression_delta",
        "with_compression_delta_ncd",
        "with_compression_all",
    ):
        summary = result[label]["locked_summary"]
        op = result[label]["locked_operating_points"]
        print(
            f"{label:28s} AUC={summary['auc']:.4f} cllr={summary['cllr']:.4f} "
            f"recall@1%={op['0.01']['recall']:.3f} recall@5%={op['0.05']['recall']:.3f}"
        )
    print()
    print(json.dumps(result["comparison"]["gate_G_P1"], indent=2))
    print("G-P1:", result["comparison"]["gate_G_P1"]["verdict"])
