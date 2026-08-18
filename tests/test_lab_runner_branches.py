"""
tests/test_lab_runner_branches.py — Branch-coverage tests for the
calibration-lab support modules (Part 4 of the branch-coverage effort):

- original/lab/runner.py       (``_filter_report_by_authors``, ``trigger_run``,
                                 ``_execute_run``)
- original/lab/suggestions.py  (``generate_suggestions`` skip arms,
                                 ``_per_author_auc`` degenerate-input arm)
- original/lab/datasets.py     (``get_dataset`` unknown-name arm)

``tests/context/test_lab.py`` already covers the calibration-lab lifecycle
end-to-end (store CRUD, HTTP endpoints, the suggestion engine's headline
behaviour) but never runs ``runner.py``'s own logic — its one HTTP test that
touches ``trigger_run`` monkeypatches the whole function away, and every
completed run in that file is seeded directly via ``store`` rather than
through ``_execute_run``. This file targets exactly the arms that leaves
dark: no real background execution and no real dataset scans — the thread
pool and ``validation.calibration.run_calibration`` are both stubbed so
everything below runs synchronously and fast.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ══════════════════════════════════════════════════════════════════════════════
# datasets.py — get_dataset
# ══════════════════════════════════════════════════════════════════════════════


class TestGetDataset:
    def test_unknown_label_raises_keyerror(self):
        from original.lab.datasets import get_dataset

        with pytest.raises(KeyError, match="unknown dataset"):
            get_dataset("does_not_exist_xyz")

    def test_known_label_returns_spec(self):
        from original.lab.datasets import get_dataset

        spec = get_dataset("federalist")
        assert spec.label == "federalist"
        assert spec.author_filter == ["hamilton", "madison", "jay", "disputed_vs_madison"]


# ══════════════════════════════════════════════════════════════════════════════
# runner.py — _filter_report_by_authors
# ══════════════════════════════════════════════════════════════════════════════


def _result(author_id: str, label: str, is_same_author: bool, deviation_score: float) -> dict:
    return {
        "filename": f"{author_id}_{label}_{deviation_score}.txt",
        "author_id": author_id,
        "label": label,
        "deviation_score": deviation_score,
        "authorship_probability": round(1.0 - deviation_score, 4),
        "recommended_action": "no_action" if is_same_author else "escalate",
        "is_same_author": is_same_author,
        "word_count": 500,
        "scoring_time_ms": 10.0,
        "notes": "",
    }


def _report(individual_results: list[dict]) -> dict:
    return {
        "summary": {
            "total_authors": len({r["author_id"] for r in individual_results}),
            "total_essays_scored": len(individual_results),
            "total_baseline_samples": 3,
            "avg_scoring_time_ms": 10.0,
            "auc": 0.5,
        },
        "threshold_metrics": {},
        "per_label_stats": {},
        "tier_importance": {},
        "roc_points": [],
        "individual_results": individual_results,
    }


class TestFilterReportByAuthors:
    def test_empty_author_filter_returns_report_unchanged(self):
        """``if not authors:`` True arm — the exact same dict is handed back."""
        from original.lab.runner import _filter_report_by_authors

        report = _report([_result("a", "authentic", True, 0.1)])
        out = _filter_report_by_authors(report, [])
        assert out is report

    def test_filter_matching_none_hits_empty_results_arm(self):
        """Non-empty filter, but no result's author_id is in it — ``results``
        comes out empty, exercising the ``else`` branch of ``if results:``."""
        from original.lab.runner import _filter_report_by_authors

        report = _report(
            [_result("a", "authentic", True, 0.1), _result("b", "ghostwritten", False, 0.9)]
        )
        out = _filter_report_by_authors(report, ["nobody_here"])
        assert out["individual_results"] == []
        assert out["roc_points"] == [[0.0, 0.0], [1.0, 1.0]]
        assert out["summary"]["auc"] == 0.5
        assert out["per_label_stats"] == {}
        assert out["summary"]["total_authors"] == 0
        assert out["summary"]["total_essays_scored"] == 0

    def test_filter_matching_some_prunes_the_rest(self):
        """Per-section pruning: the comprehension's ``if`` keeps matches and
        drops non-matches in the same call."""
        from original.lab.runner import _filter_report_by_authors

        report = _report(
            [
                _result("keep", "authentic", True, 0.1),
                _result("drop", "authentic", True, 0.2),
                _result("keep", "ghostwritten", False, 0.9),
            ]
        )
        out = _filter_report_by_authors(report, ["keep"])
        assert [r["author_id"] for r in out["individual_results"]] == ["keep", "keep"]

    def test_only_positive_class_after_filter_defaults_auc(self):
        """``n_pos > 0 and n_neg > 0`` False arm via the second operand
        (n_neg == 0 after filtering) — falls back to the 0.5/degenerate ROC."""
        from original.lab.runner import _filter_report_by_authors

        report = _report(
            [
                _result("a", "authentic", True, 0.1),
                _result("a", "authentic", True, 0.15),
            ]
        )
        out = _filter_report_by_authors(report, ["a"])
        assert out["summary"]["auc"] == 0.5
        assert out["roc_points"] == [[0.0, 0.0], [1.0, 1.0]]
        # Per-label roll-up still runs (results is non-empty).
        assert out["per_label_stats"]["authentic"]["count"] == 2

    def test_only_negative_class_after_filter_defaults_auc(self):
        """Same compound condition, False arm via the first operand
        (n_pos == 0 after filtering)."""
        from original.lab.runner import _filter_report_by_authors

        report = _report([_result("a", "ghostwritten", False, 0.8)])
        out = _filter_report_by_authors(report, ["a"])
        assert out["summary"]["auc"] == 0.5
        assert out["per_label_stats"]["ghostwritten"]["count"] == 1

    def test_both_classes_present_recomputes_auc_and_per_label_stats(self):
        """True arm of the compound condition: real trapezoidal AUC + a
        multi-label per_label_stats roll-up (2 iterations of the label loop)."""
        from original.lab.runner import _filter_report_by_authors

        report = _report(
            [
                _result("a", "authentic", True, 0.1),
                _result("a", "authentic", True, 0.2),
                _result("a", "ghostwritten", False, 0.9),
                _result("b", "ghostwritten", False, 0.8),
            ]
        )
        out = _filter_report_by_authors(report, ["a", "b"])
        assert out["summary"]["auc"] > 0.9  # well-separated -> near-perfect AUC
        assert set(out["per_label_stats"].keys()) == {"authentic", "ghostwritten"}
        assert out["per_label_stats"]["authentic"]["count"] == 2
        assert out["per_label_stats"]["ghostwritten"]["count"] == 2
        assert out["summary"]["total_authors"] == 2
        assert out["summary"]["total_essays_scored"] == 4
        # Non-filtered top-level keys pass through untouched.
        assert out["threshold_metrics"] == {}


# ══════════════════════════════════════════════════════════════════════════════
# runner.py — trigger_run
# ══════════════════════════════════════════════════════════════════════════════


class TestTriggerRun:
    def test_unknown_dataset_returns_error(self):
        import original.lab.runner as runner_module

        run_id, error = runner_module.trigger_run("not_a_real_dataset")
        assert run_id is None
        assert error is not None and "unknown dataset" in error

    def test_requires_build_dataset_returns_build_instructions(self):
        """``spec.requires_build`` True arm — the wide-benchmark datasets
        (raid/pan/m4/autextification) all set this; the lab UI can't run
        them until the on-disk corpus is built."""
        import original.lab.runner as runner_module

        run_id, error = runner_module.trigger_run("raid")
        assert run_id is None
        assert error is not None
        assert "must be built first" in error
        assert "validation.wide.run" in error

    def test_store_insert_failure_returns_error(self, monkeypatch):
        """``run_id is None`` arm — ``store.start_calibration_run`` failed
        (e.g. a DB error) and returned None."""
        import original.lab.runner as runner_module

        monkeypatch.setattr(runner_module.store, "start_calibration_run", lambda **kw: None)
        run_id, error = runner_module.trigger_run("federalist")
        assert run_id is None
        assert error == "Failed to insert calibration run row"

    def test_success_submits_execute_run_to_the_pool(self, monkeypatch):
        """Success arm: a real row id comes back and ``_execute_run`` is
        queued on the pool with the right arguments — pool.submit is stubbed
        so nothing actually runs in the background."""
        import original.lab.runner as runner_module

        monkeypatch.setattr(runner_module.store, "start_calibration_run", lambda **kw: 4242)

        submitted = {}

        class _FakePool:
            def submit(self, fn, *args, **kwargs):
                submitted["fn"] = fn
                submitted["args"] = args
                return None

        monkeypatch.setattr(runner_module, "_POOL", _FakePool())

        run_id, error = runner_module.trigger_run(
            "federalist", run_label="lab-test", max_scoring=5, thresholds={"no_action": 0.4}
        )
        assert run_id == 4242
        assert error is None
        assert submitted["fn"] is runner_module._execute_run
        assert submitted["args"][0] == 4242
        assert submitted["args"][1].label == "federalist"
        assert submitted["args"][2] == 5
        assert submitted["args"][3] == {"no_action": 0.4}


# ══════════════════════════════════════════════════════════════════════════════
# runner.py — _execute_run
# ══════════════════════════════════════════════════════════════════════════════


def _fake_calibration_report(author_ids: list[str]):
    """Build a real ``validation.calibration.CalibrationReport`` (not a mock)
    so ``_serialize_report``'s attribute access matches production shapes
    exactly."""
    from validation.calibration import CalibrationReport, ScoringResult, ThresholdMetrics
    from validation.manifest_schema import AuthorshipLabel

    results = []
    for i, author in enumerate(author_ids):
        results.append(
            ScoringResult(
                filename=f"{author}_{i}.txt",
                author_id=author,
                label=AuthorshipLabel.AUTHENTIC,
                deviation_score=0.15,
                authorship_probability=0.85,
                recommended_action="no_action",
                is_same_author=True,
                word_count=800,
                scoring_time_ms=12.5,
            )
        )
        results.append(
            ScoringResult(
                filename=f"{author}_ghost_{i}.txt",
                author_id=author,
                label=AuthorshipLabel.GHOSTWRITTEN,
                deviation_score=0.85,
                authorship_probability=0.15,
                recommended_action="escalate",
                is_same_author=False,
                word_count=800,
                scoring_time_ms=12.5,
            )
        )
    return CalibrationReport(
        total_authors=len(author_ids),
        total_essays_scored=len(results),
        total_baseline_samples=len(author_ids) * 3,
        avg_scoring_time_ms=12.5,
        results=results,
        roc_points=[(0.0, 0.0), (1.0, 1.0)],
        auc=0.95,
        threshold_metrics={
            "no_action": ThresholdMetrics(
                threshold=0.4,
                true_positives=len(author_ids),
                false_positives=0,
                true_negatives=len(author_ids),
                false_negatives=0,
            )
        },
        tier_importance={},
        per_label_stats={},
    )


class TestExecuteRun:
    def test_success_without_author_filter_completes_the_run(self, monkeypatch):
        """``if spec.author_filter:`` False arm (multi_author has none) —
        the serialized report is persisted as-is."""
        import original.lab.runner as runner_module
        import validation.calibration as calibration_module
        from original.lab.datasets import get_dataset

        spec = get_dataset("multi_author")
        assert spec.author_filter == []
        report = _fake_calibration_report(["hamilton", "madison"])
        monkeypatch.setattr(calibration_module, "run_calibration", lambda **kw: report)

        completed = {}

        def fake_complete(run_id, *, auc, n_essays_scored, n_authors, report):
            completed["run_id"] = run_id
            completed["auc"] = auc
            completed["n_essays_scored"] = n_essays_scored
            completed["n_authors"] = n_authors
            completed["report"] = report
            return True

        monkeypatch.setattr(runner_module.store, "complete_calibration_run", fake_complete)

        runner_module._execute_run(101, spec, None, None)

        assert completed["run_id"] == 101
        assert completed["auc"] == 0.95
        assert completed["n_essays_scored"] == report.total_essays_scored
        assert completed["n_authors"] == 2
        # Every author from the fake report survived (no filtering applied).
        authors = {r["author_id"] for r in completed["report"]["individual_results"]}
        assert authors == {"hamilton", "madison"}

    def test_success_with_author_filter_prunes_the_persisted_report(self, monkeypatch):
        """``if spec.author_filter:`` True arm (federalist restricts to
        hamilton/madison/jay/disputed_vs_madison) — an author outside that
        set must not survive into the persisted report."""
        import original.lab.runner as runner_module
        import validation.calibration as calibration_module
        from original.lab.datasets import get_dataset

        spec = get_dataset("federalist")
        assert spec.author_filter
        report = _fake_calibration_report(["hamilton", "an_outsider"])
        monkeypatch.setattr(calibration_module, "run_calibration", lambda **kw: report)

        completed = {}
        monkeypatch.setattr(
            runner_module.store,
            "complete_calibration_run",
            lambda run_id, **kw: completed.update(run_id=run_id, **kw) or True,
        )

        runner_module._execute_run(102, spec, None, None)

        authors = {r["author_id"] for r in completed["report"]["individual_results"]}
        assert authors == {"hamilton"}
        assert "an_outsider" not in authors
        assert completed["n_authors"] == 1

    def test_exception_is_captured_as_a_failed_run(self, monkeypatch):
        """The broad ``except Exception`` arm: a real exception from
        ``run_calibration`` must be caught and persisted via
        ``store.fail_calibration_run`` with a full traceback, not raised."""
        import original.lab.runner as runner_module
        import validation.calibration as calibration_module
        from original.lab.datasets import get_dataset

        spec = get_dataset("multi_author")

        def boom(**kw):
            raise RuntimeError("scoring exploded")

        monkeypatch.setattr(calibration_module, "run_calibration", boom)

        failed = {}

        def fake_fail(run_id, error):
            failed["run_id"] = run_id
            failed["error"] = error

        monkeypatch.setattr(runner_module.store, "fail_calibration_run", fake_fail)

        # Must not raise.
        runner_module._execute_run(103, spec, None, None)

        assert failed["run_id"] == 103
        assert "RuntimeError" in failed["error"]
        assert "scoring exploded" in failed["error"]

    def test_inserts_repo_root_into_syspath_when_missing(self, monkeypatch):
        """``if str(repo_root) not in sys.path:`` True arm."""
        import original.lab.runner as runner_module
        import validation.calibration as calibration_module
        from original.lab.datasets import get_dataset

        repo_root_str = str(Path(runner_module.__file__).resolve().parent.parent.parent)
        trimmed_path = [p for p in sys.path if p != repo_root_str]
        monkeypatch.setattr(sys, "path", trimmed_path)

        spec = get_dataset("multi_author")
        report = _fake_calibration_report(["hamilton"])
        monkeypatch.setattr(calibration_module, "run_calibration", lambda **kw: report)
        monkeypatch.setattr(
            runner_module.store, "complete_calibration_run", lambda run_id, **kw: True
        )

        runner_module._execute_run(104, spec, None, None)

        assert repo_root_str in sys.path

    def test_skips_syspath_insert_when_already_present(self, monkeypatch):
        """``if str(repo_root) not in sys.path:`` False arm."""
        import original.lab.runner as runner_module
        import validation.calibration as calibration_module
        from original.lab.datasets import get_dataset

        repo_root_str = str(Path(runner_module.__file__).resolve().parent.parent.parent)
        path_with_root = list(sys.path)
        if repo_root_str not in path_with_root:
            path_with_root.append(repo_root_str)
        monkeypatch.setattr(sys, "path", path_with_root)
        before_len = len(sys.path)

        spec = get_dataset("multi_author")
        report = _fake_calibration_report(["hamilton"])
        monkeypatch.setattr(calibration_module, "run_calibration", lambda **kw: report)
        monkeypatch.setattr(
            runner_module.store, "complete_calibration_run", lambda run_id, **kw: True
        )

        runner_module._execute_run(105, spec, None, None)

        # Not inserted again — length unchanged.
        assert len(sys.path) == before_len


# ══════════════════════════════════════════════════════════════════════════════
# suggestions.py — generate_suggestions skip arms + _per_author_auc
# ══════════════════════════════════════════════════════════════════════════════


def _suggestions_report(individual_results: list[dict], auc: float) -> dict:
    return {
        "summary": {
            "total_authors": len({r["author_id"] for r in individual_results}),
            "total_essays_scored": len(individual_results),
            "total_baseline_samples": 6,
            "avg_scoring_time_ms": 10.0,
            "auc": auc,
        },
        "individual_results": individual_results,
        "threshold_metrics": {},
        "per_label_stats": {},
        "tier_importance": {},
        "roc_points": [],
    }


def _sep_results(n_pos: int, n_neg: int, n_authors: int = 3) -> list[dict]:
    import numpy as np

    rng = np.random.RandomState(7)
    pos = np.clip(rng.normal(0.20, 0.05, size=n_pos), 0.0, 1.0)
    neg = np.clip(rng.normal(0.85, 0.05, size=n_neg), 0.0, 1.0)
    results = []
    for i, s in enumerate(pos):
        results.append(_result(f"author_{i % n_authors}", "authentic", True, round(float(s), 4)))
    for i, s in enumerate(neg):
        results.append(
            _result(f"author_{i % n_authors}", "ghostwritten", False, round(float(s), 4))
        )
    return results


class TestPerAuthorAucDegenerateInput:
    def test_single_class_author_is_skipped(self):
        """``if not pos or not neg: continue`` — an author with only one
        class of labels contributes no AUC entry, but authors with both
        classes still compute normally."""
        from original.lab.suggestions import _per_author_auc

        results = [
            _result("solo_authentic", "authentic", True, 0.1),
            _result("solo_authentic", "authentic", True, 0.2),
            _result("solo_ghost", "ghostwritten", False, 0.9),
            _result("both", "authentic", True, 0.1),
            _result("both", "ghostwritten", False, 0.9),
        ]
        aucs = _per_author_auc(results)
        assert "solo_authentic" not in aucs
        assert "solo_ghost" not in aucs
        assert "both" in aucs
        assert aucs["both"] == 1.0

    def test_generate_suggestions_does_not_crash_on_single_class_authors(self):
        """Exercised through the public entrypoint too, per the task brief."""
        from original.lab.suggestions import generate_suggestions

        results = _sep_results(n_pos=20, n_neg=10) + [_result("lonely", "authentic", True, 0.05)]
        report = _suggestions_report(results, auc=0.9)
        out = generate_suggestions(report)
        outlier_authors = {
            s["metadata"]["author"] for s in out["suggestions"] if s["type"] == "per_author_outlier"
        }
        assert "lonely" not in outlier_authors


class TestGenerateSuggestionsSkipArms:
    def test_no_action_suggestion_skipped_when_already_at_the_optimum(self):
        """``if abs(suggested - cur_no_action) > 0.01:`` False arm — current
        threshold is already within 0.01 of the F1-optimal point, so no
        threshold_no_action suggestion is emitted."""
        from original.lab.suggestions import _sweep_thresholds, generate_suggestions

        results = _sep_results(n_pos=20, n_neg=10)
        report = _suggestions_report(results, auc=0.95)
        sweep = _sweep_thresholds(results)
        f1_threshold = sweep["f1_optimal"]["threshold"]

        out = generate_suggestions(
            report,
            current_thresholds={
                "no_action": round(f1_threshold, 3),
                "monitor": 0.55,
                "escalate": 0.75,
            },
        )
        types = [s["type"] for s in out["suggestions"]]
        assert "threshold_no_action" not in types

    def test_corrections_disagreement_skipped_without_divergence_scores(self):
        """``if divs:`` False arm — enough wrong corrections to pass the
        count gate, but none carries an ``original_divergence_score``, so
        ``divs`` comes out empty and no suggestion is emitted."""
        from original.lab.suggestions import generate_suggestions

        results = _sep_results(n_pos=20, n_neg=10)
        report = _suggestions_report(results, auc=0.95)
        corrections = [{"is_correct": False} for _ in range(5)]  # no divergence score key

        out = generate_suggestions(report, corrections=corrections)
        types = [s["type"] for s in out["suggestions"]]
        assert "corrections_disagreement" not in types
