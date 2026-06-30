"""
validation/benchmark — accuracy benchmark instrumentation.

Wraps Original's existing scoring pipeline (`validation/calibration.py` +
`original/quantum/scoring.py`) with the four metric families a buyer or
auditor expects to see:

  1. AUC + ROC + per-label means        (run_calibration() already does this)
  2. Brier + calibration curve (NEW)    (validation/benchmark/metrics.py)
  3. Per-tier ablation       (NEW)      (validation/benchmark/ablation.py)
  4. Bias audit             (NEW)       (validation/benchmark/bias_slicer.py)

Both the wide benchmark (`validation/wide/`) and the public-author test
(`validation/public_authors/`) use this package — never re-implement.

The math is unchanged: every metric is computed on the same Layer7Output
payloads the live system produces. We never compute our own deviation,
never re-weight features, never replace `score()`. We measure, we don't
re-implement.

See /Users/andrew/.claude/plans/refactored-napping-bee.md for the full
plan.
"""

from .reproducibility import lock_environment, BENCHMARK_SEED
from .metrics import (
    brier_score,
    calibration_curve,
    confusion_at_threshold,
    f1_at_threshold,
)
from .ablation import per_tier_ablation, TierAblationResult
from .bias_slicer import slice_by, BiasSlice
from .report import write_report, ReportPaths

__all__ = [
    "lock_environment",
    "BENCHMARK_SEED",
    "brier_score",
    "calibration_curve",
    "confusion_at_threshold",
    "f1_at_threshold",
    "per_tier_ablation",
    "TierAblationResult",
    "slice_by",
    "BiasSlice",
    "write_report",
    "ReportPaths",
]
