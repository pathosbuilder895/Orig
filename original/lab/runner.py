"""
lab/runner.py — Threaded calibration runner.

Wraps ``validation.calibration.run_calibration`` with persistence so the
lab UI can fire-and-poll. Single global thread pool with max_workers=1
serialises runs (calibrations are CPU-heavy + share file I/O; running
two simultaneously would just thrash).

Lifecycle:
    1. ``trigger_run`` inserts a row with status="running" and returns the id.
    2. A background thread calls ``run_calibration`` with the dataset's
       paths + author filter; writes status="completed" + report on success
       or status="failed" + error on exception.
    3. UI polls ``store.get_calibration_run`` until status flips.

Cancellation isn't supported — once started, a run completes or fails on
its own. The thread is daemon=True so it won't block process exit.
"""

from __future__ import annotations

import logging
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .. import store
from .datasets import DatasetSpec, get_dataset

log = logging.getLogger(__name__)

# Module-level pool; one worker so runs queue rather than overlap.
_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lab-calibration")
_POOL_LOCK = threading.Lock()


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def trigger_run(
    dataset_label: str,
    *,
    run_label: Optional[str] = None,
    max_scoring: Optional[int] = None,
    thresholds: Optional[Dict[str, float]] = None,
) -> Tuple[Optional[int], Optional[str]]:
    """
    Insert a `running` row and queue a background thread to execute the
    calibration. Returns ``(run_id, error)``; on success ``error`` is None.

    The endpoint should return the run_id immediately — the calibration
    itself takes minutes for the multi-author corpus.
    """
    try:
        spec = get_dataset(dataset_label)
    except KeyError as e:
        return None, str(e)

    config = {
        "dataset_label":  dataset_label,
        "max_scoring":    max_scoring,
        "thresholds":     thresholds,
        "author_filter":  spec.author_filter,
    }
    run_id = store.start_calibration_run(
        dataset_label=dataset_label, run_label=run_label, config=config,
    )
    if run_id is None:
        return None, "Failed to insert calibration run row"

    # Submit to the pool — single worker, so runs queue.
    with _POOL_LOCK:
        _POOL.submit(_execute_run, run_id, spec, max_scoring, thresholds)

    return run_id, None


def _execute_run(
    run_id: int,
    spec: DatasetSpec,
    max_scoring: Optional[int],
    thresholds: Optional[Dict[str, float]],
) -> None:
    """
    Background-thread body. Runs calibration; persists result or error.

    Imports validation.calibration LAZILY so the import path doesn't cost
    anything when the module is imported but no run has been triggered.
    """
    try:
        # Make the validation package importable when running under FastAPI
        # (working directory may be elsewhere).
        repo_root = Path(__file__).resolve().parent.parent.parent
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))

        from validation.calibration import run_calibration

        # If author_filter is set, we mutate the manifest copy in-flight by
        # passing it through. The cleanest path is to load the manifest,
        # filter, write to a tmp file, and pass that — but that requires
        # touching run_calibration. Simpler: rely on the Federalist subset
        # being a no-op since the full multi-author corpus already runs OK
        # for both. If a corpus restriction is needed later, we'll add a
        # `--authors` flag to validation.calibration.
        report = run_calibration(
            corpus_dir=spec.corpus_dir,
            manifest_path=spec.manifest_path,
            thresholds=thresholds,
            max_scoring=max_scoring,
        )

        # Apply author filter on the report side: drop results outside
        # the filter and recompute summary stats.
        report_dict = _serialize_report(report)
        if spec.author_filter:
            report_dict = _filter_report_by_authors(report_dict, spec.author_filter)

        store.complete_calibration_run(
            run_id,
            auc=report_dict.get("summary", {}).get("auc", 0.0),
            n_essays_scored=report_dict.get("summary", {}).get("total_essays_scored", 0),
            n_authors=report_dict.get("summary", {}).get("total_authors", 0),
            report=report_dict,
        )
        log.info("calibration run %d completed (AUC=%.4f)",
                 run_id, report_dict.get("summary", {}).get("auc", 0.0))
    except Exception as exc:
        # Capture the full traceback in the error column for debugging.
        tb = traceback.format_exc()
        log.warning("calibration run %d failed: %s", run_id, exc)
        store.fail_calibration_run(run_id, error=tb)


# ══════════════════════════════════════════════════════════════════════════════
# Report serialisation + filter
# ══════════════════════════════════════════════════════════════════════════════

def _serialize_report(report) -> Dict:
    """
    Convert a ``validation.calibration.CalibrationReport`` dataclass into
    the JSON shape the dashboard expects (mirrors ``save_report``).
    """
    return {
        "summary": {
            "total_authors":         report.total_authors,
            "total_essays_scored":   report.total_essays_scored,
            "total_baseline_samples": report.total_baseline_samples,
            "avg_scoring_time_ms":   report.avg_scoring_time_ms,
            "auc":                   report.auc,
        },
        "threshold_metrics": {
            name: {
                "threshold":       m.threshold,
                "true_positives":  m.true_positives,
                "false_positives": m.false_positives,
                "true_negatives":  m.true_negatives,
                "false_negatives": m.false_negatives,
                "tpr":             round(m.tpr, 4),
                "fpr":             round(m.fpr, 4),
                "precision":       round(m.precision, 4),
                "accuracy":        round(m.accuracy, 4),
            }
            for name, m in report.threshold_metrics.items()
        },
        "per_label_stats":  report.per_label_stats,
        "tier_importance":  report.tier_importance,
        "roc_points":       report.roc_points,
        "individual_results": [
            {
                "filename":               r.filename,
                "author_id":              r.author_id,
                "label":                  r.label.value,
                "deviation_score":        round(r.deviation_score, 4),
                "authorship_probability": round(r.authorship_probability, 4),
                "recommended_action":     r.recommended_action,
                "is_same_author":         r.is_same_author,
                "word_count":             r.word_count,
                "scoring_time_ms":        r.scoring_time_ms,
                "notes":                  getattr(r, "notes", "") or "",
            }
            for r in report.results
        ],
    }


def _filter_report_by_authors(report_dict: Dict, authors: List[str]) -> Dict:
    """
    Re-derive summary + per-label stats over a subset of results.

    Used for the Federalist preset: the full calibration runs against the
    8-author corpus, but the dashboard view shows only Hamilton/Madison/
    Jay/disputed.
    """
    if not authors:
        return report_dict
    keep = set(authors)
    results = [r for r in report_dict.get("individual_results", [])
               if r.get("author_id") in keep]

    # Re-derive AUC + per-label stats from the filtered set so the
    # dashboard doesn't show inflated numbers from authors the user
    # filtered out.
    import numpy as np
    if results:
        positives = [r["deviation_score"] for r in results if r["is_same_author"]]
        negatives = [r["deviation_score"] for r in results if not r["is_same_author"]]
        n_pos = len(positives)
        n_neg = len(negatives)
        # Trapezoidal AUC over a 200-point sweep.
        if n_pos > 0 and n_neg > 0:
            thresholds = np.linspace(0, 1, 200)
            roc_points = [(0.0, 0.0)]
            for t in thresholds:
                tp = sum(1 for s in positives if s < t)
                fp = sum(1 for s in negatives if s < t)
                roc_points.append((fp / n_neg, tp / n_pos))
            roc_points.append((1.0, 1.0))
            roc_points.sort()
            auc = 0.0
            for i in range(1, len(roc_points)):
                x0, y0 = roc_points[i - 1]
                x1, y1 = roc_points[i]
                auc += (x1 - x0) * (y0 + y1) / 2
            auc = round(auc, 4)
        else:
            roc_points = [(0.0, 0.0), (1.0, 1.0)]
            auc = 0.5

        # Per-label stats roll-up.
        from collections import defaultdict
        by_label: Dict[str, List[float]] = defaultdict(list)
        for r in results:
            by_label[r["label"]].append(r["deviation_score"])
        per_label_stats: Dict[str, Dict] = {}
        for label, scores in by_label.items():
            arr = np.array(scores)
            per_label_stats[label] = {
                "count":           len(scores),
                "mean_deviation":  round(float(arr.mean()), 4),
                "std_deviation":   round(float(arr.std()), 4),
                "min_deviation":   round(float(arr.min()), 4),
                "max_deviation":   round(float(arr.max()), 4),
            }
    else:
        roc_points = [(0.0, 0.0), (1.0, 1.0)]
        auc = 0.5
        per_label_stats = {}

    out = dict(report_dict)
    out["individual_results"] = results
    out["roc_points"] = [list(p) for p in roc_points]
    out["per_label_stats"] = per_label_stats
    summary = dict(report_dict.get("summary", {}))
    summary["total_authors"] = len(set(r["author_id"] for r in results))
    summary["total_essays_scored"] = len(results)
    summary["auc"] = auc
    out["summary"] = summary
    return out
