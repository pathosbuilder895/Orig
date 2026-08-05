"""Leakage-resistant research stack for authorship-verification experts."""

from .fusion import (
    CauseDecision,
    FusionFit,
    Trial,
    assert_no_group_overlap,
    cllr,
    fit_grouped_fusion,
    fit_grouped_fusion_cllr,
    select_cause,
)

__all__ = [
    "CauseDecision",
    "FusionFit",
    "Trial",
    "assert_no_group_overlap",
    "cllr",
    "fit_grouped_fusion",
    "fit_grouped_fusion_cllr",
    "select_cause",
]
