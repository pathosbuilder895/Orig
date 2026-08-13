"""Report-only fused stylometric score.

See docs/superpowers/specs/2026-08-11-fused-score-design.md. Never changes
deviation_score, quantum_fidelity, or the recommended action.
"""

from .expert import (
    FusedScoreResult,
    predict_fused_score,
    predict_fused_score_with_reason,
    reset_for_tests,
)

__all__ = [
    "FusedScoreResult",
    "predict_fused_score",
    "predict_fused_score_with_reason",
    "reset_for_tests",
]
