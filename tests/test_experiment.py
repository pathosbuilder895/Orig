"""
tests/test_experiment.py — every validation report must carry a
machine-readable record of what was measured. The mandatory task label is
the structural fix for "a verification number wore an attribution label".
"""
from __future__ import annotations

import pytest

from validation.experiment import (
    VALID_TASKS,
    build_spec,
    diff_specs,
    spec_to_dict,
    summarize_author_docs,
)


def _spec(task="verification", **over):
    kwargs = dict(
        task=task,
        corpora={"seminary": summarize_author_docs({"a": ["one two three"] * 3}, "student_pilot")},
        windowing={"length": 800, "overlap": 0.0},
        aggregation={"tier_rule": "median"},
        thresholds={"g1_flagged_rate": 0.05},
    )
    kwargs.update(over)
    return build_spec(**kwargs)


class TestBuildSpec:
    def test_rejects_unknown_task(self):
        with pytest.raises(ValueError):
            _spec(task="benchmarking")

    def test_valid_tasks_cover_the_design_set(self):
        assert VALID_TASKS == {
            "verification", "attribution", "drift",
            "weight_derivation", "calibration_suite",
        }

    def test_captures_git_sha_seed_and_env_lock(self):
        d = spec_to_dict(_spec())
        assert len(d["git_sha"]) == 40
        assert d["seed"] == 1729
        assert d["env_lock"]["ADAPTIVE_WEIGHTS_ENABLED"] == "0"

    def test_feature_statuses_summarized(self):
        d = spec_to_dict(_spec())
        counts = d["features"]["status_counts"]
        assert counts["measurable"] > 0
        assert sum(counts.values()) == d["features"]["total"]


class TestSummarize:
    def test_author_docs_summary(self):
        s = summarize_author_docs(
            {"a": ["w " * 400, "w " * 300], "b": ["w " * 500]}, "real_historical"
        )
        assert s["n_authors"] == 2
        assert s["n_documents"] == 3
        assert s["total_words"] == 1200
        assert s["provenance"] == "real_historical"


class TestDiff:
    def test_diff_lists_changed_fields(self):
        a = spec_to_dict(_spec())
        b = spec_to_dict(_spec(windowing={"length": 250, "overlap": 0.0}))
        changes = diff_specs(a, b)
        assert any("windowing.length: 800 != 250" in c for c in changes)

    def test_diff_refuses_cross_task_comparison(self):
        a = spec_to_dict(_spec(task="verification"))
        b = spec_to_dict(_spec(task="attribution"))
        with pytest.raises(ValueError, match="different tasks"):
            diff_specs(a, b)
