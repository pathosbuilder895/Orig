"""
validation/threshold_tuner.py — Threshold optimisation from calibration data.

Reads a CalibrationReport (or raw results) and finds optimal thresholds that
satisfy operational constraints:

  - **escalate** threshold: FPR < 2% (we never want to wrongly accuse)
  - **monitor** threshold:  FPR < 10%, TPR > 80%
  - **no_action** ceiling:  maximise TNR while keeping FNR < 5%

The tuner sweeps deviation_score from 0→1 in 0.001 steps and picks the
threshold that best satisfies each constraint.

Usage:
    python -m validation.threshold_tuner --report validation/calibration_report.json
    python -m validation.threshold_tuner --report validation/calibration_report.json --output tuned_thresholds.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class TunedThreshold:
    """A single optimised threshold with its metrics."""
    name: str
    value: float
    true_positive_rate: float
    false_positive_rate: float
    precision: float
    accuracy: float
    f1_score: float
    constraint_satisfied: bool
    constraint_description: str


@dataclass
class ThresholdTuningReport:
    """Complete threshold tuning output."""
    tuned_thresholds: Dict[str, TunedThreshold]
    original_thresholds: Dict[str, float]
    improvement_summary: Dict[str, dict]
    optimal_f1_threshold: float
    equal_error_rate: float        # EER: where FPR == FNR
    eer_threshold: float


# ── Core tuning logic ────────────────────────────────────────────────────────

def tune_thresholds(
    results: List[dict],
    original_thresholds: Optional[Dict[str, float]] = None,
) -> ThresholdTuningReport:
    """
    Find optimal thresholds from scored results.

    Args:
        results: List of dicts with keys: deviation_score, is_same_author
        original_thresholds: Current thresholds to compare against.

    Returns:
        ThresholdTuningReport with optimised thresholds.
    """
    if original_thresholds is None:
        original_thresholds = {
            "no_action": 0.40,
            "monitor": 0.55,
            "escalate": 0.75,
        }

    # Extract arrays
    scores = np.array([r["deviation_score"] for r in results])
    labels = np.array([r["is_same_author"] for r in results])  # True = authentic

    total_positive = labels.sum()       # authentic essays
    total_negative = (~labels).sum()    # non-authentic essays

    if total_positive == 0 or total_negative == 0:
        raise ValueError("Need both authentic and non-authentic samples for tuning")

    # Sweep thresholds
    sweep = np.arange(0.001, 1.0, 0.001)
    metrics_at = []
    for thresh in sweep:
        tp = ((labels) & (scores < thresh)).sum()
        fp = ((labels) & (scores >= thresh)).sum()
        tn = ((~labels) & (scores >= thresh)).sum()
        fn = ((~labels) & (scores < thresh)).sum()

        tpr = tp / max(1, tp + fn)  # sensitivity
        fpr = fp / max(1, fp + tp)  # false positive rate (accusing innocent)
        fnr = fn / max(1, fn + tn)  # false negative rate (missing cheaters)
        tnr = tn / max(1, tn + fn)  # specificity
        prec = tn / max(1, tn + fp)  # precision for flagging
        acc = (tp + tn) / max(1, tp + fp + tn + fn)
        f1 = 2 * prec * tnr / max(1e-10, prec + tnr) if (prec + tnr) > 0 else 0

        metrics_at.append({
            "threshold": round(float(thresh), 3),
            "tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn),
            "tpr": float(tpr), "fpr": float(fpr),
            "fnr": float(fnr), "tnr": float(tnr),
            "precision": float(prec), "accuracy": float(acc),
            "f1": float(f1),
        })

    # ── Find optimal thresholds per constraint ───────────────────────────

    # ESCALATE: FPR < 2%, maximise detection (TNR)
    escalate = _find_best(
        metrics_at,
        constraint=lambda m: m["fpr"] < 0.02,
        optimise="tnr",
        name="escalate",
        constraint_desc="FPR < 2% (minimise false accusations)",
    )

    # MONITOR: FPR < 10%, TPR > 80%
    monitor = _find_best(
        metrics_at,
        constraint=lambda m: m["fpr"] < 0.10 and m["tpr"] > 0.80,
        optimise="f1",
        name="monitor",
        constraint_desc="FPR < 10% and TPR > 80%",
    )

    # NO_ACTION: FNR < 5%, maximise TPR (let authentic through)
    no_action = _find_best(
        metrics_at,
        constraint=lambda m: m["fnr"] < 0.05,
        optimise="tpr",
        name="no_action",
        constraint_desc="FNR < 5% (miss < 5% of non-authentic)",
    )

    # ── Global optimals ──────────────────────────────────────────────────

    # Best F1 threshold
    best_f1 = max(metrics_at, key=lambda m: m["f1"])
    optimal_f1_threshold = best_f1["threshold"]

    # Equal Error Rate (where FPR ≈ FNR)
    eer_diff = [(abs(m["fpr"] - m["fnr"]), m) for m in metrics_at]
    eer_entry = min(eer_diff, key=lambda x: x[0])[1]
    eer = (eer_entry["fpr"] + eer_entry["fnr"]) / 2
    eer_threshold = eer_entry["threshold"]

    # ── Improvement summary ──────────────────────────────────────────────

    tuned = {
        "no_action": no_action,
        "monitor": monitor,
        "escalate": escalate,
    }

    improvement_summary = {}
    for name, tuned_t in tuned.items():
        old_val = original_thresholds.get(name, 0.5)
        old_metrics = _metrics_at_threshold(metrics_at, old_val)
        improvement_summary[name] = {
            "old_threshold": old_val,
            "new_threshold": tuned_t.value,
            "delta": round(tuned_t.value - old_val, 4),
            "old_fpr": old_metrics["fpr"] if old_metrics else None,
            "new_fpr": tuned_t.false_positive_rate,
            "old_accuracy": old_metrics["accuracy"] if old_metrics else None,
            "new_accuracy": tuned_t.accuracy,
        }

    return ThresholdTuningReport(
        tuned_thresholds=tuned,
        original_thresholds=original_thresholds,
        improvement_summary=improvement_summary,
        optimal_f1_threshold=optimal_f1_threshold,
        equal_error_rate=round(eer, 4),
        eer_threshold=eer_threshold,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _find_best(
    metrics: List[dict],
    constraint,
    optimise: str,
    name: str,
    constraint_desc: str,
) -> TunedThreshold:
    """Find the threshold that satisfies constraint and maximises optimise metric."""
    candidates = [m for m in metrics if constraint(m)]
    satisfied = len(candidates) > 0

    if candidates:
        best = max(candidates, key=lambda m: m[optimise])
    else:
        # No threshold satisfies constraint — pick closest to satisfying
        best = max(metrics, key=lambda m: m[optimise])

    return TunedThreshold(
        name=name,
        value=best["threshold"],
        true_positive_rate=round(best["tpr"], 4),
        false_positive_rate=round(best["fpr"], 4),
        precision=round(best["precision"], 4),
        accuracy=round(best["accuracy"], 4),
        f1_score=round(best["f1"], 4),
        constraint_satisfied=satisfied,
        constraint_description=constraint_desc,
    )


def _metrics_at_threshold(metrics: List[dict], threshold: float) -> Optional[dict]:
    """Find metrics closest to a given threshold value."""
    closest = min(metrics, key=lambda m: abs(m["threshold"] - threshold))
    if abs(closest["threshold"] - threshold) < 0.005:
        return closest
    return None


def save_tuning_report(report: ThresholdTuningReport, output_path: str) -> None:
    """Save the tuning report as JSON."""
    data = {
        "tuned_thresholds": {
            name: {
                "name": t.name,
                "value": t.value,
                "tpr": t.true_positive_rate,
                "fpr": t.false_positive_rate,
                "precision": t.precision,
                "accuracy": t.accuracy,
                "f1": t.f1_score,
                "constraint_satisfied": t.constraint_satisfied,
                "constraint": t.constraint_description,
            }
            for name, t in report.tuned_thresholds.items()
        },
        "original_thresholds": report.original_thresholds,
        "improvement_summary": report.improvement_summary,
        "optimal_f1_threshold": report.optimal_f1_threshold,
        "equal_error_rate": report.equal_error_rate,
        "eer_threshold": report.eer_threshold,
        "recommended_config": {
            name: t.value
            for name, t in report.tuned_thresholds.items()
        },
    }
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Tuning report saved to {output_path}")


def load_calibration_results(report_path: str) -> List[dict]:
    """Load individual results from a calibration report JSON."""
    with open(report_path) as f:
        data = json.load(f)
    return data["individual_results"]


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Tune Original thresholds from calibration data")
    parser.add_argument("--report", required=True, help="Path to calibration_report.json")
    parser.add_argument("--output", default="validation/tuned_thresholds.json")
    args = parser.parse_args()

    results = load_calibration_results(args.report)
    report = tune_thresholds(results)

    print(f"\n{'='*60}")
    print("THRESHOLD TUNING RESULTS")
    print(f"{'='*60}")
    print(f"Equal Error Rate: {report.equal_error_rate:.4f} (at threshold {report.eer_threshold})")
    print(f"Optimal F1 threshold: {report.optimal_f1_threshold}")
    print()

    for name, t in report.tuned_thresholds.items():
        imp = report.improvement_summary[name]
        print(f"  {name}:")
        print(f"    Old: {imp['old_threshold']}  →  New: {t.value}")
        print(f"    FPR: {t.false_positive_rate:.2%}  TPR: {t.true_positive_rate:.2%}  "
              f"F1: {t.f1_score:.4f}  Constraint met: {t.constraint_satisfied}")
    print()

    save_tuning_report(report, args.output)
