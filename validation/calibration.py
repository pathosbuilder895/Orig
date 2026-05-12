"""
validation/calibration.py — Calibration study runner.

Reads the validation corpus, builds baselines per author, scores every
non-baseline essay, and produces:
  - Per-author scoring results
  - ROC curve data and AUC
  - Per-tier contribution analysis
  - True/false positive/negative rates at each threshold
  - A JSON report suitable for inclusion in the sales deck

Usage:
    python -m validation.calibration --corpus validation/corpus --manifest validation/manifest.json
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from original.features.pipeline import compute_full_features, extract_features, feature_vector
from original.quantum.state import StudentState, BaselineSample
from original.quantum.scoring import score
from original.constants import ALL_FEATURE_CODES, FEATURE_DIM
from validation.manifest_schema import (
    AuthorshipLabel,
    CorpusEntry,
    ValidationManifest,
)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ScoringResult:
    """Result of scoring a single essay."""
    filename: str
    author_id: str
    label: AuthorshipLabel
    deviation_score: float
    authorship_probability: float
    recommended_action: str
    is_same_author: bool          # True if label == authentic
    word_count: int
    scoring_time_ms: float
    notes: str = ""
    tier_contributions: Dict[str, float] = field(default_factory=dict)


@dataclass
class ThresholdMetrics:
    """Metrics at a specific threshold."""
    threshold: float
    true_positives: int           # authentic correctly below threshold
    false_positives: int          # authentic incorrectly above threshold
    true_negatives: int           # non-authentic correctly above threshold
    false_negatives: int          # non-authentic incorrectly below threshold

    @property
    def tpr(self) -> float:
        """True positive rate (sensitivity / recall)."""
        return self.true_positives / max(1, self.true_positives + self.false_negatives)

    @property
    def fpr(self) -> float:
        """False positive rate (accusing innocent students)."""
        return self.false_positives / max(1, self.false_positives + self.true_positives)

    @property
    def precision(self) -> float:
        return self.true_negatives / max(1, self.true_negatives + self.false_positives)

    @property
    def accuracy(self) -> float:
        total = self.true_positives + self.false_positives + self.true_negatives + self.false_negatives
        return (self.true_positives + self.true_negatives) / max(1, total)


@dataclass
class CalibrationReport:
    """Complete calibration study report."""
    total_authors: int
    total_essays_scored: int
    total_baseline_samples: int
    avg_scoring_time_ms: float
    results: List[ScoringResult]
    roc_points: List[Tuple[float, float]]     # (FPR, TPR) pairs
    auc: float
    threshold_metrics: Dict[str, ThresholdMetrics]  # keyed by threshold name
    tier_importance: Dict[str, float]               # tier → avg contribution
    per_label_stats: Dict[str, dict]


# ── Main runner ───────────────────────────────────────────────────────────────

def run_calibration(
    corpus_dir: str,
    manifest_path: str,
    thresholds: Optional[Dict[str, float]] = None,
    max_scoring: Optional[int] = None,
) -> CalibrationReport:
    """
    Run the full calibration study.

    Args:
        corpus_dir: Path to the corpus directory containing essay text files.
        manifest_path: Path to the manifest.json file.
        thresholds: Optional dict of named thresholds to evaluate.
                    Defaults to the action thresholds from the roadmap.
        max_scoring: If set, cap the number of scoring entries per author to
                     this value (randomly sampled). Useful for large corpora.

    Returns:
        CalibrationReport with all metrics.
    """
    import random as _random
    if thresholds is None:
        thresholds = {
            "no_action": 0.40,
            "monitor": 0.55,
            "escalate": 0.75,
        }

    # Load manifest
    with open(manifest_path) as f:
        manifest = ValidationManifest(**json.load(f))

    authors = manifest.all_authors()
    all_results: List[ScoringResult] = []
    total_baseline = 0

    print(f"Calibration study: {len(authors)} authors, {len(manifest.entries)} total entries")
    if max_scoring:
        print(f"  (capped at {max_scoring} scoring entries per author)")

    for author_id in authors:
        baseline_entries = manifest.baseline_entries(author_id)
        scoring_entries = manifest.scoring_entries(author_id)

        # Cap scoring entries to keep runtime manageable
        if max_scoring and len(scoring_entries) > max_scoring:
            _random.seed(42)
            scoring_entries = _random.sample(scoring_entries, max_scoring)

        if len(baseline_entries) < 3:
            print(f"  SKIP {author_id}: only {len(baseline_entries)} baseline samples (need 3+)")
            continue

        # Build baseline
        baseline_texts = []
        baseline_samples = []
        for b_idx, entry in enumerate(baseline_entries):
            text = _read_essay(corpus_dir, entry.filename)
            if not text:
                continue
            print(f"    baseline {b_idx+1}/{len(baseline_entries)}: {entry.filename}", flush=True)
            fv = feature_vector(text)
            baseline_samples.append(BaselineSample(
                text=text,
                vector=fv,
                provenance="verified",
                auth_weight=0.7,
                assignment=entry.prompt,
                submitted_at="2026-01-01T00:00:00",
            ))
            baseline_texts.append(text)

        if len(baseline_samples) < 3:
            print(f"  SKIP {author_id}: baseline files missing or unreadable")
            continue

        total_baseline += len(baseline_samples)
        state = StudentState(student_id=author_id, samples=baseline_samples)

        # Score each non-baseline entry
        for s_idx, entry in enumerate(scoring_entries):
            text = _read_essay(corpus_dir, entry.filename)
            if not text:
                continue

            print(f"    scoring {s_idx+1}/{len(scoring_entries)}: {entry.filename}", flush=True)
            t0 = time.perf_counter()
            features = compute_full_features(text, baseline_texts)
            sub_vector = np.array([features[c] for c in ALL_FEATURE_CODES], dtype=np.float64)
            result = score(state, sub_vector, features, entry.filename)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            # Determine if same author
            is_same = entry.label == AuthorshipLabel.AUTHENTIC

            # Extract tier contributions from interference decomposition
            tier_contribs = {}
            for fc in (result.interference.constructive_features + result.interference.destructive_features):
                tier = _feature_to_tier(fc.code)
                tier_contribs[tier] = tier_contribs.get(tier, 0.0) + abs(fc.contribution)

            all_results.append(ScoringResult(
                filename=entry.filename,
                author_id=author_id,
                label=entry.label,
                notes=getattr(entry, 'notes', ''),
                deviation_score=result.authorship.deviation_score,
                authorship_probability=result.authorship.authorship_probability,
                recommended_action=result.recommendation.action,
                is_same_author=is_same,
                word_count=entry.word_count,
                scoring_time_ms=round(elapsed_ms, 2),
                tier_contributions=tier_contribs,
            ))

        print(f"  {author_id}: {len(baseline_samples)} baseline, {len(scoring_entries)} scored")

    if not all_results:
        raise ValueError("No results — check corpus and manifest")

    # Compute metrics
    roc_points, auc = _compute_roc_auc(all_results)
    threshold_metrics = {
        name: _compute_threshold_metrics(all_results, thresh)
        for name, thresh in thresholds.items()
    }
    tier_importance = _compute_tier_importance(all_results)
    per_label_stats = _compute_per_label_stats(all_results)
    avg_time = sum(r.scoring_time_ms for r in all_results) / len(all_results)

    return CalibrationReport(
        total_authors=len(authors),
        total_essays_scored=len(all_results),
        total_baseline_samples=total_baseline,
        avg_scoring_time_ms=round(avg_time, 2),
        results=all_results,
        roc_points=roc_points,
        auc=auc,
        threshold_metrics=threshold_metrics,
        tier_importance=tier_importance,
        per_label_stats=per_label_stats,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_essay(corpus_dir: str, filename: str) -> Optional[str]:
    """Read an essay file and return its text."""
    path = os.path.join(corpus_dir, filename)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"    WARNING: file not found: {path}")
        return None


def _feature_to_tier(code: str) -> str:
    """Map a feature code to its tier name using the authoritative FEATURE_TIER dict."""
    from original.constants import FEATURE_TIER
    t = FEATURE_TIER.get(code)
    if t is None:
        return "comparison"   # comparison features not in FEATURE_TIER
    return f"tier{t}"


def _compute_roc_auc(results: List[ScoringResult]) -> Tuple[List[Tuple[float, float]], float]:
    """Compute ROC curve points and AUC."""
    # Sort by deviation score
    sorted_results = sorted(results, key=lambda r: r.deviation_score)

    total_positive = sum(1 for r in results if r.is_same_author)      # authentic
    total_negative = sum(1 for r in results if not r.is_same_author)  # non-authentic

    if total_positive == 0 or total_negative == 0:
        return [(0, 0), (1, 1)], 0.5

    roc_points = [(0.0, 0.0)]
    tp = total_positive  # at threshold = 0, all authentic are "below threshold"
    fp = total_negative  # all non-authentic are also "below threshold"

    thresholds = np.linspace(0, 1, 200)
    for thresh in thresholds:
        tp = sum(1 for r in results if r.is_same_author and r.deviation_score < thresh)
        fp = sum(1 for r in results if not r.is_same_author and r.deviation_score < thresh)
        tpr = tp / total_positive
        fpr = fp / total_negative
        roc_points.append((fpr, tpr))

    roc_points.append((1.0, 1.0))
    roc_points.sort()

    # AUC via trapezoidal rule
    auc = 0.0
    for i in range(1, len(roc_points)):
        x0, y0 = roc_points[i - 1]
        x1, y1 = roc_points[i]
        auc += (x1 - x0) * (y0 + y1) / 2

    return roc_points, round(auc, 4)


def _compute_threshold_metrics(
    results: List[ScoringResult], threshold: float
) -> ThresholdMetrics:
    """Compute TP/FP/TN/FN at a given deviation threshold."""
    tp = sum(1 for r in results if r.is_same_author and r.deviation_score < threshold)
    fp = sum(1 for r in results if r.is_same_author and r.deviation_score >= threshold)
    tn = sum(1 for r in results if not r.is_same_author and r.deviation_score >= threshold)
    fn = sum(1 for r in results if not r.is_same_author and r.deviation_score < threshold)
    return ThresholdMetrics(
        threshold=threshold,
        true_positives=tp,
        false_positives=fp,
        true_negatives=tn,
        false_negatives=fn,
    )


def _compute_tier_importance(results: List[ScoringResult]) -> Dict[str, float]:
    """Average tier contributions across all scored essays."""
    tier_totals: Dict[str, float] = {}
    tier_counts: Dict[str, int] = {}
    for r in results:
        for tier, contrib in r.tier_contributions.items():
            tier_totals[tier] = tier_totals.get(tier, 0.0) + contrib
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
    return {
        tier: round(tier_totals[tier] / tier_counts[tier], 4)
        for tier in sorted(tier_totals.keys())
    }


def _compute_per_label_stats(results: List[ScoringResult]) -> Dict[str, dict]:
    """Compute mean/std deviation for each label category."""
    from collections import defaultdict
    by_label = defaultdict(list)
    for r in results:
        by_label[r.label.value].append(r.deviation_score)

    stats = {}
    for label, scores in by_label.items():
        arr = np.array(scores)
        stats[label] = {
            "count": len(scores),
            "mean_deviation": round(float(arr.mean()), 4),
            "std_deviation": round(float(arr.std()), 4),
            "min_deviation": round(float(arr.min()), 4),
            "max_deviation": round(float(arr.max()), 4),
        }
    return stats


def save_report(report: CalibrationReport, output_path: str) -> None:
    """Save the calibration report as JSON."""
    data = {
        "summary": {
            "total_authors": report.total_authors,
            "total_essays_scored": report.total_essays_scored,
            "total_baseline_samples": report.total_baseline_samples,
            "avg_scoring_time_ms": report.avg_scoring_time_ms,
            "auc": report.auc,
        },
        "threshold_metrics": {
            name: {
                "threshold": m.threshold,
                "true_positives": m.true_positives,
                "false_positives": m.false_positives,
                "true_negatives": m.true_negatives,
                "false_negatives": m.false_negatives,
                "tpr": round(m.tpr, 4),
                "fpr": round(m.fpr, 4),
                "precision": round(m.precision, 4),
                "accuracy": round(m.accuracy, 4),
            }
            for name, m in report.threshold_metrics.items()
        },
        "per_label_stats": report.per_label_stats,
        "tier_importance": report.tier_importance,
        "roc_points": report.roc_points,
        "individual_results": [
            {
                "filename": r.filename,
                "author_id": r.author_id,
                "label": r.label.value,
                "deviation_score": round(r.deviation_score, 4),
                "authorship_probability": round(r.authorship_probability, 4),
                "recommended_action": r.recommended_action,
                "is_same_author": r.is_same_author,
                "word_count": r.word_count,
                "scoring_time_ms": r.scoring_time_ms,
                "notes": r.notes,
            }
            for r in report.results
        ],
    }
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Report saved to {output_path}")


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run Original calibration study")
    parser.add_argument("--corpus", required=True, help="Path to corpus directory")
    parser.add_argument("--manifest", required=True, help="Path to manifest.json")
    parser.add_argument("--output", default="validation/calibration_report.json")
    parser.add_argument("--max-scoring", type=int, default=None,
                        help="Cap scoring entries per author (default: no cap)")
    args = parser.parse_args()

    report = run_calibration(args.corpus, args.manifest, max_scoring=args.max_scoring)

    print(f"\n{'='*60}")
    print(f"CALIBRATION RESULTS")
    print(f"{'='*60}")
    print(f"Authors: {report.total_authors}")
    print(f"Essays scored: {report.total_essays_scored}")
    print(f"AUC: {report.auc}")
    print(f"Avg scoring time: {report.avg_scoring_time_ms:.1f}ms")
    print()
    for name, m in report.threshold_metrics.items():
        print(f"Threshold '{name}' ({m.threshold}):")
        print(f"  TPR: {m.tpr:.2%}  FPR: {m.fpr:.2%}  Accuracy: {m.accuracy:.2%}")
    print()
    print("Per-label stats:")
    for label, stats in report.per_label_stats.items():
        print(f"  {label}: mean={stats['mean_deviation']:.3f} std={stats['std_deviation']:.3f} (n={stats['count']})")
    print()
    print("Tier importance:")
    for tier, imp in report.tier_importance.items():
        print(f"  {tier}: {imp:.4f}")

    save_report(report, args.output)
