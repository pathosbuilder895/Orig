import numpy as np
import pytest

from original.quantum.pooled_calibration import (
    build_pooled_reference,
    pooled_reference_stats,
)


def test_pools_across_students():
    per_student = [np.array([1.0, 1.1, 0.9]), np.array([1.2, 0.8]), np.array([1.0, 1.3])]
    ref = build_pooled_reference(per_student, min_students=3, min_total=5)
    assert ref is not None
    assert len(ref) == 7
    assert np.all(np.diff(ref) >= 0), "reference must be sorted for p-value lookup"


def test_returns_none_below_the_student_floor():
    """Two students is not a population — refuse rather than pretend."""
    per_student = [np.array([1.0, 1.1, 0.9]), np.array([1.2, 0.8])]
    assert build_pooled_reference(per_student, min_students=3, min_total=5) is None


def test_returns_none_below_the_total_floor():
    per_student = [np.array([1.0]), np.array([1.1]), np.array([0.9])]
    assert build_pooled_reference(per_student, min_students=3, min_total=30) is None


def test_ignores_empty_and_nonfinite_contributions():
    per_student = [
        np.array([1.0, 1.1, 0.9]),
        np.array([]),
        np.array([np.nan, 1.2]),
        np.array([1.0, 1.3]),
    ]
    ref = build_pooled_reference(per_student, min_students=3, min_total=5)
    assert ref is not None
    assert np.all(np.isfinite(ref))
    assert len(ref) == 6


def test_stats_report_the_reachable_floor():
    ref = build_pooled_reference([np.arange(20.0)] * 3, min_students=3, min_total=30)
    stats = pooled_reference_stats(ref)
    assert stats["n"] == 60
    assert stats["p_floor"] == pytest.approx(1 / 61)
    assert stats["n_students"] is None  # not recoverable from the pooled array


def test_stats_none_ref_reports_zero_n_and_floor_of_one():
    """The caller's real-world None comes from build_pooled_reference itself
    (below-floor cohort) — every other test here only ever passes a
    non-empty ref through, so the guard's True arm has no coverage."""
    stats = pooled_reference_stats(None)
    assert stats == {"n": 0, "p_floor": 1.0, "n_students": None}


def test_stats_empty_ref_array_reports_same_as_none():
    """`ref is None` and `len(ref) == 0` are two different ways into the same
    guard body — an empty (but non-None) array must be handled identically."""
    stats = pooled_reference_stats(np.array([]))
    assert stats == {"n": 0, "p_floor": 1.0, "n_students": None}
