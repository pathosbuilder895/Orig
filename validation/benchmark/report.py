"""
report.py — write the benchmark report to disk.

Each benchmark run produces a date- and dataset-stamped directory:

  validation/benchmarks/<YYYY-MM-DD>/<dataset_label>/
    ├── report.json           # machine-readable, diff-able across runs
    ├── report.md             # one-page human summary
    ├── roc_curve.svg         # ROC plotted from the existing roc_points
    ├── calibration_curve.svg # reliability diagram
    ├── ablation.csv          # one row per tier: tier, ΔAUC, ΔBrier
    └── bias.csv              # one row per (group, value): n, AUC, mean dev

The JSON is the source of truth — the Markdown and CSVs are derived from
it. Two runs with the same plan should produce diff-able JSON (modulo the
timestamp), which is the canonical reproducibility check.

The plots are optional: if ``matplotlib`` isn't installed, the SVGs are
skipped and the report is still complete (text-only). This keeps the
production runtime light — only dev installs need matplotlib.
"""

from __future__ import annotations

import csv
import datetime
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# ── Paths the runner cares about ─────────────────────────────────────────────

@dataclass(frozen=True)
class ReportPaths:
    root: Path
    json_path: Path
    md_path: Path
    roc_svg: Path
    calibration_svg: Path
    ablation_csv: Path
    bias_csv: Path


def output_dir(dataset_label: str, base: str = "validation/benchmarks") -> Path:
    """Today's directory for this dataset."""
    today = datetime.date.today().isoformat()
    p = Path(base) / today / dataset_label
    p.mkdir(parents=True, exist_ok=True)
    return p


def paths_for(dataset_label: str, base: str = "validation/benchmarks") -> ReportPaths:
    root = output_dir(dataset_label, base=base)
    return ReportPaths(
        root=root,
        json_path=root / "report.json",
        md_path=root / "report.md",
        roc_svg=root / "roc_curve.svg",
        calibration_svg=root / "calibration_curve.svg",
        ablation_csv=root / "ablation.csv",
        bias_csv=root / "bias.csv",
    )


# ── Main writer ───────────────────────────────────────────────────────────────

def write_report(
    paths: ReportPaths,
    *,
    dataset_label: str,
    env_lock: object,            # _EnvLockReport from reproducibility.py
    calibration_report,          # CalibrationReport from validation.calibration
    metrics: dict,               # metrics_dict() output
    ablation: Optional[list] = None,        # List[TierAblationResult] or None
    bias_slices: Optional[Dict[str, list]] = None,  # field name → List[BiasSlice]
    extra: Optional[dict] = None,
) -> ReportPaths:
    """
    Write the full report family to disk. Idempotent — re-runs overwrite.

    Returns the same `paths` for chaining.
    """
    bias_slices = bias_slices or {}
    ablation = ablation or []
    extra = extra or {}

    # ── 1. The JSON source-of-truth ──
    j = {
        "dataset_label": dataset_label,
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "environment": _env_lock_to_dict(env_lock),
        "summary": {
            "total_authors": calibration_report.total_authors,
            "total_essays_scored": calibration_report.total_essays_scored,
            "total_baseline_samples": calibration_report.total_baseline_samples,
            "avg_scoring_time_ms": calibration_report.avg_scoring_time_ms,
            "auc": calibration_report.auc,
        },
        "metrics": metrics,
        "per_label_stats": calibration_report.per_label_stats,
        "threshold_metrics_legacy": _threshold_metrics_legacy(calibration_report),
        "tier_importance_observed": calibration_report.tier_importance,
        "ablation": [asdict(r) for r in ablation],
        "bias": {field: [asdict(s) for s in slices] for field, slices in bias_slices.items()},
        "extra": extra,
    }
    paths.json_path.write_text(json.dumps(j, indent=2, default=_json_default))

    # ── 2. The CSVs (ablation, bias) ──
    if ablation:
        _write_ablation_csv(paths.ablation_csv, ablation)
    if bias_slices:
        _write_bias_csv(paths.bias_csv, bias_slices)

    # ── 3. The Markdown summary ──
    paths.md_path.write_text(_render_markdown(j))

    # ── 4. Plots (optional) ──
    try:
        _write_roc_svg(paths.roc_svg, calibration_report.roc_points)
        _write_calibration_svg(paths.calibration_svg, metrics.get("calibration_curve", []))
    except ImportError:
        # matplotlib not installed — skip plots, report is still complete.
        pass

    return paths


# ── Internal helpers ──────────────────────────────────────────────────────────

def _env_lock_to_dict(env_lock) -> dict:
    if env_lock is None:
        return {}
    if hasattr(env_lock, "__dict__"):
        return dict(env_lock.__dict__)
    if hasattr(env_lock, "_asdict"):
        return env_lock._asdict()
    return asdict(env_lock)


def _threshold_metrics_legacy(report) -> dict:
    """Pull the per-threshold TP/FP from CalibrationReport for the JSON."""
    return {
        name: {
            "threshold": m.threshold,
            "tp": m.true_positives,
            "fp": m.false_positives,
            "tn": m.true_negatives,
            "fn": m.false_negatives,
            "tpr": round(m.tpr, 4),
            "fpr": round(m.fpr, 4),
            "precision": round(m.precision, 4),
            "accuracy": round(m.accuracy, 4),
        }
        for name, m in report.threshold_metrics.items()
    }


def _json_default(o):
    """Fallback serialiser for things json doesn't know about (Enum, etc.)."""
    if hasattr(o, "value"):
        return o.value
    if hasattr(o, "__dict__"):
        return o.__dict__
    return str(o)


def _write_ablation_csv(path: Path, ablation: list) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tier", "n_features_zeroed", "baseline_auc",
                    "ablated_auc", "delta_auc", "baseline_brier",
                    "ablated_brier", "delta_brier"])
        for r in ablation:
            w.writerow([r.tier, r.n_features_zeroed, r.baseline_auc,
                        r.ablated_auc, r.delta_auc, r.baseline_brier,
                        r.ablated_brier, r.delta_brier])


def _write_bias_csv(path: Path, bias_slices: Dict[str, list]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["field", "value", "count", "mean_deviation",
                    "std_deviation", "auc_in_group", "false_positive_rate"])
        for field, slices in bias_slices.items():
            for s in slices:
                w.writerow([s.field, s.value, s.count, s.mean_deviation,
                            s.std_deviation, s.auc_in_group, s.false_positive_rate])


def _render_markdown(j: dict) -> str:
    """One-page summary. Designed to be the thing a reviewer reads first."""
    s = j["summary"]
    m = j["metrics"]
    lines: List[str] = []
    lines.append(f"# Benchmark — {j['dataset_label']}")
    lines.append("")
    lines.append(f"_Generated {j['generated_at']}_")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **AUC**: {s['auc']}")
    lines.append(f"- **Brier**: {m.get('brier', 'n/a'):.4f}" if "brier" in m else "- **Brier**: n/a")
    lines.append(f"- **Authors**: {s['total_authors']}")
    lines.append(f"- **Essays scored**: {s['total_essays_scored']}")
    lines.append(f"- **Baseline samples**: {s['total_baseline_samples']}")
    lines.append(f"- **Mean scoring time**: {s['avg_scoring_time_ms']} ms / essay")
    lines.append("")
    lines.append("## Per-label deviation")
    lines.append("")
    lines.append("| label | n | mean | std |")
    lines.append("|---|---|---|---|")
    for label, st in sorted((j.get("per_label_stats") or {}).items()):
        lines.append(f"| {label} | {st['count']} | {st['mean_deviation']} | {st['std_deviation']} |")
    lines.append("")
    if m.get("threshold_metrics"):
        lines.append("## Action-threshold metrics")
        lines.append("")
        lines.append("| name | threshold | TP | FP | TN | FN | precision | recall | F1 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for name, t in m["threshold_metrics"].items():
            lines.append(
                f"| {name} | {t['threshold']} | {t['tp']} | {t['fp']} | "
                f"{t['tn']} | {t['fn']} | {t['precision']} | {t['recall']} | {t['f1']} |"
            )
        lines.append("")
    if m.get("calibration_curve"):
        lines.append("## Calibration curve (10 bins)")
        lines.append("")
        lines.append("| bin | n | mean predicted | fraction positive |")
        lines.append("|---|---|---|---|")
        for b in m["calibration_curve"]:
            lines.append(
                f"| {b['lower']:.2f}–{b['upper']:.2f} | {b['count']} | "
                f"{b['mean_predicted']} | {b['fraction_positive']} |"
            )
        lines.append("")
    if j.get("ablation"):
        lines.append("## Per-tier ablation")
        lines.append("")
        lines.append("Each row: zero out that tier's features → re-score → compare AUC + Brier vs the baseline run.")
        lines.append("")
        lines.append("| tier | n features | baseline AUC | ablated AUC | ΔAUC | ΔBrier |")
        lines.append("|---|---|---|---|---|---|")
        for r in j["ablation"]:
            lines.append(
                f"| {r['tier']} | {r['n_features_zeroed']} | "
                f"{r['baseline_auc']} | {r['ablated_auc']} | {r['delta_auc']} | {r['delta_brier']} |"
            )
        lines.append("")
    if j.get("bias"):
        lines.append("## Bias audit")
        lines.append("")
        for field_name, slices in j["bias"].items():
            lines.append(f"### {field_name}")
            lines.append("")
            lines.append("| value | n | mean dev | AUC | FPR (authentic-only) |")
            lines.append("|---|---|---|---|---|")
            for s in slices:
                lines.append(
                    f"| {s['value']} | {s['count']} | {s['mean_deviation']} | "
                    f"{s['auc_in_group']} | {s['false_positive_rate']} |"
                )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write_roc_svg(path: Path, roc_points) -> None:
    """Plot the ROC curve. Skips silently if matplotlib isn't installed."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(4.2, 4.2))
    if roc_points:
        xs = [p[0] for p in roc_points]
        ys = [p[1] for p in roc_points]
        ax.plot(xs, ys, color="#002147", linewidth=1.5, label="ROC")
    ax.plot([0, 1], [0, 1], color="#888", linestyle="--", linewidth=0.8, label="chance")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_xlabel("False positive rate")
    ax.set_ylabel("True positive rate")
    ax.set_title("ROC curve")
    ax.set_aspect("equal")
    ax.legend(loc="lower right", frameon=False)
    fig.tight_layout()
    fig.savefig(path, format="svg")
    plt.close(fig)


def _write_calibration_svg(path: Path, bins: list) -> None:
    """Plot the calibration curve (reliability diagram)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(4.2, 4.2))
    ax.plot([0, 1], [0, 1], color="#888", linestyle="--", linewidth=0.8, label="perfect")
    if bins:
        x = [b["mean_predicted"] for b in bins]
        y = [b["fraction_positive"] for b in bins]
        sizes = [max(20, min(b["count"] * 5, 250)) for b in bins]
        ax.scatter(x, y, s=sizes, color="#002147", alpha=0.85, label="bin")
        # Connect points with a thin line for the eye.
        ax.plot(x, y, color="#002147", linewidth=0.7, alpha=0.5)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Observed fraction of positives")
    ax.set_title("Calibration curve")
    ax.set_aspect("equal")
    ax.legend(loc="upper left", frameon=False)
    fig.tight_layout()
    fig.savefig(path, format="svg")
    plt.close(fig)
