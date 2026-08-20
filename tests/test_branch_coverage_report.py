"""Unit tests for scripts/branch_coverage_report.py's rollup math."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "branch_coverage_report", REPO_ROOT / "scripts" / "branch_coverage_report.py"
)
bcr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bcr)


def _report():
    return {
        "meta": {"branch_coverage": True},
        "files": {
            "original/store.py": {
                "summary": {
                    "num_branches": 100,
                    "covered_branches": 60,
                    "missing_branches": 40,
                    "percent_covered": 70.0,
                }
            },
            "original/quantum/scoring.py": {
                "summary": {
                    "num_branches": 50,
                    "covered_branches": 45,
                    "missing_branches": 5,
                    "percent_covered": 92.0,
                }
            },
            "original/version.py": {
                "summary": {
                    "num_branches": 0,
                    "covered_branches": 0,
                    "missing_branches": 0,
                    "percent_covered": 100.0,
                }
            },
        },
    }


def test_files_ranked_by_missing_branches():
    rows, _ = bcr.summarize(_report())
    assert rows[0]["path"] == "original/store.py"
    assert rows[0]["missing_branches"] == 40
    assert rows[0]["branch_pct"] == 60.0


def test_cluster_rollup_and_assignment():
    _, clusters = bcr.summarize(_report())
    assert clusters["persistence"]["num_branches"] == 100
    assert clusters["quantum"]["covered_branches"] == 45
    # version.py falls through to "other" and zero-branch files count as 100%
    assert clusters["other"]["branch_pct"] == 100.0


def test_zero_branch_file_does_not_divide_by_zero():
    rows, _ = bcr.summarize(_report())
    version = next(r for r in rows if r["path"] == "original/version.py")
    assert version["branch_pct"] == 100.0
