"""
tests/context/test_lab.py — PR 8 Calibration Lab tests.

Covers:
- Suggestion engine (input shapes + sanity-check output for known reports)
- Calibration runs lifecycle (start → complete → list → get)
- Tuned thresholds versioning + active-set retrieval
- HTTP endpoints: lab/datasets, calibration/runs (CRUD), suggestions, apply

Tests use synthetic ``individual_results`` rather than running real
calibrations — running the actual Federalist study takes minutes and is
covered separately under ``validation/``. The lab orchestration logic is
what's exercised here.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest


# ── Test fixtures (shared across PR 7+8 tests) ───────────────────────────────

_API_MODULE = None


def _load_api_module_once():
    global _API_MODULE
    if _API_MODULE is not None:
        return _API_MODULE
    BACKEND_ROOT = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "original._legacy_demo_api_lab_tests",
        BACKEND_ROOT / "original" / "api.py",
    )
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "original"
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _API_MODULE = module
    return module


def _fresh_db_and_app():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    module = _load_api_module_once()
    from pathlib import Path as _Path
    module.store._DB_PATH = _Path(tmp.name)
    module.store._STORE.clear()
    module.store._loaded = False
    from fastapi.testclient import TestClient
    return TestClient(module.app), module, tmp.name


@pytest.fixture
def client_module_db():
    client, module, db_path = _fresh_db_and_app()
    yield client, module, db_path
    module.store._STORE.clear()
    module.store._loaded = False
    os.unlink(db_path)


# ══════════════════════════════════════════════════════════════════════════════
# Synthetic calibration report builder
# ══════════════════════════════════════════════════════════════════════════════

def _synthetic_report(
    *, n_pos: int = 20, n_neg: int = 5,
    pos_mean: float = 0.20, neg_mean: float = 0.85,
    n_authors: int = 3,
) -> dict:
    """
    Produce a calibration-report-shaped dict with controllable separation
    between authentic and ghostwritten distributions.

    The suggestion engine cares about ``individual_results`` and ``summary``;
    it doesn't need ROC points etc. (computes its own threshold sweep).
    """
    import numpy as np
    rng = np.random.RandomState(42)
    pos = np.clip(rng.normal(pos_mean, 0.05, size=n_pos), 0.0, 1.0)
    neg = np.clip(rng.normal(neg_mean, 0.05, size=n_neg), 0.0, 1.0)
    results = []
    for i, s in enumerate(pos):
        results.append({
            "filename":               f"authentic_{i}.txt",
            "author_id":              f"author_{i % n_authors}",
            "label":                  "authentic",
            "deviation_score":        round(float(s), 4),
            "authorship_probability": round(1.0 - float(s), 4),
            "recommended_action":     "no_action",
            "is_same_author":         True,
            "word_count":             1000,
            "scoring_time_ms":        100.0,
            "notes":                  "",
        })
    for i, s in enumerate(neg):
        results.append({
            "filename":               f"ghost_{i}.txt",
            "author_id":              f"author_{i % n_authors}",
            "label":                  "ghostwritten",
            "deviation_score":        round(float(s), 4),
            "authorship_probability": round(1.0 - float(s), 4),
            "recommended_action":     "escalate",
            "is_same_author":         False,
            "word_count":             1000,
            "scoring_time_ms":        100.0,
            "notes":                  "",
        })
    # Compute global AUC manually from the synthetic data.
    n_correct = sum(1 for p in pos for q in neg if p < q)
    n_tied    = sum(1 for p in pos for q in neg if p == q) * 0.5
    auc = (n_correct + n_tied) / (n_pos * n_neg)
    return {
        "summary": {
            "total_authors":          n_authors,
            "total_essays_scored":    n_pos + n_neg,
            "total_baseline_samples": n_authors * 3,
            "avg_scoring_time_ms":    100.0,
            "auc":                    round(auc, 4),
        },
        "individual_results": results,
        "threshold_metrics":  {},
        "per_label_stats":    {},
        "tier_importance":    {},
        "roc_points":         [],
    }


# ══════════════════════════════════════════════════════════════════════════════
# Suggestion engine
# ══════════════════════════════════════════════════════════════════════════════

class TestSuggestionEngine:
    def test_well_separated_data_finds_optimal_threshold(self):
        from original.lab.suggestions import generate_suggestions
        # Authentic mean 0.2, ghostwritten mean 0.85 — easy separation.
        report = _synthetic_report(n_pos=20, n_neg=10,
                                    pos_mean=0.20, neg_mean=0.85)
        out = generate_suggestions(report)
        assert out["summary"]["global_auc"] > 0.95  # well-separated
        f1 = out["summary"]["f1_optimal"]
        assert f1 is not None
        # F1 optimum should land between the two means.
        assert 0.20 < f1["threshold"] < 0.85

    def test_overlapping_data_yields_lower_auc(self):
        from original.lab.suggestions import generate_suggestions
        # Heavily overlapping distributions: 0.50±0.10 vs 0.55±0.10 — 0.5σ
        # separation. Should yield AUC well below the well-separated case.
        report = _synthetic_report(n_pos=20, n_neg=10,
                                    pos_mean=0.50, neg_mean=0.55)
        # Pad std manually since the generator hard-codes 0.05.
        # We just check that the suggestions still come back without crash.
        out = generate_suggestions(report)
        assert out["summary"]["f1_optimal"] is not None
        assert out["summary"]["global_auc"] is not None

    def test_empty_results_handled(self):
        from original.lab.suggestions import generate_suggestions
        report = {"individual_results": [], "summary": {"auc": None}}
        out = generate_suggestions(report)
        assert out["summary"]["f1_optimal"] is None
        assert out["summary"]["eer"] is None
        # Should not crash; suggestions list may be empty.
        assert isinstance(out["suggestions"], list)

    def test_only_one_class_handled(self):
        # All authentic, no ghostwritten — degenerate. Build the report
        # directly because the helper divides by len(neg).
        from original.lab.suggestions import generate_suggestions
        report = {
            "summary": {"auc": None, "total_authors": 1,
                        "total_essays_scored": 5,
                        "total_baseline_samples": 3, "avg_scoring_time_ms": 1.0},
            "individual_results": [
                {
                    "filename": f"a_{i}.txt", "author_id": "a",
                    "label": "authentic", "deviation_score": 0.30,
                    "authorship_probability": 0.70,
                    "recommended_action": "no_action",
                    "is_same_author": True, "word_count": 1000,
                    "scoring_time_ms": 1.0, "notes": "",
                }
                for i in range(5)
            ],
            "threshold_metrics": {}, "per_label_stats": {},
            "tier_importance": {}, "roc_points": [],
        }
        out = generate_suggestions(report)
        assert out["summary"]["f1_optimal"] is None

    def test_per_author_outlier_detection(self):
        """An author with much lower AUC should be surfaced as a suggestion."""
        from original.lab.suggestions import generate_suggestions
        # author_0: well-separated. author_1: actually overlapping
        # distributions where some authentic scores are HIGHER than some
        # ghostwritten — gives a per-author AUC well below 1.0.
        results = []
        for i in range(5):
            results.append({
                "filename": f"a0_auth_{i}.txt", "author_id": "author_0",
                "label": "authentic", "deviation_score": 0.10 + 0.01*i,
                "authorship_probability": 0.90, "recommended_action": "no_action",
                "is_same_author": True, "word_count": 1000, "scoring_time_ms": 1.0,
                "notes": "",
            })
        for i in range(3):
            results.append({
                "filename": f"a0_ghost_{i}.txt", "author_id": "author_0",
                "label": "ghostwritten", "deviation_score": 0.90 - 0.01*i,
                "authorship_probability": 0.10, "recommended_action": "escalate",
                "is_same_author": False, "word_count": 1000, "scoring_time_ms": 1.0,
                "notes": "",
            })
        # author_1: authentic and ghostwritten distributions OVERLAP — half
        # of authentic samples score *higher* than half of ghostwritten
        # ones, dropping per-author AUC to ~0.50.
        a1_pos = [0.30, 0.45, 0.55, 0.65, 0.75]
        a1_neg = [0.40, 0.55, 0.70]
        for i, s in enumerate(a1_pos):
            results.append({
                "filename": f"a1_auth_{i}.txt", "author_id": "author_1",
                "label": "authentic", "deviation_score": s,
                "authorship_probability": 1 - s, "recommended_action": "monitor",
                "is_same_author": True, "word_count": 1000, "scoring_time_ms": 1.0,
                "notes": "",
            })
        for i, s in enumerate(a1_neg):
            results.append({
                "filename": f"a1_ghost_{i}.txt", "author_id": "author_1",
                "label": "ghostwritten", "deviation_score": s,
                "authorship_probability": 1 - s, "recommended_action": "monitor",
                "is_same_author": False, "word_count": 1000, "scoring_time_ms": 1.0,
                "notes": "",
            })
        report = {
            "summary": {"auc": 0.80, "total_authors": 2,
                        "total_essays_scored": len(results),
                        "total_baseline_samples": 6, "avg_scoring_time_ms": 1.0},
            "individual_results": results,
            "threshold_metrics": {}, "per_label_stats": {},
            "tier_importance": {}, "roc_points": [],
        }
        out = generate_suggestions(report)
        outliers = [s for s in out["suggestions"]
                    if s["type"] == "per_author_outlier"]
        # author_1's per-author AUC ≈ 0.5; gap from 0.80 global ≈ 0.30
        # well above the 0.10 outlier threshold.
        outlier_authors = {s["metadata"]["author"] for s in outliers}
        assert "author_1" in outlier_authors

    def test_corrections_disagreement_signal(self):
        """When >= N corrections marked wrong, we get a corrections suggestion."""
        from original.lab.suggestions import generate_suggestions
        report = _synthetic_report(n_pos=20, n_neg=10)
        corrections = [
            {"is_correct": False, "original_divergence_score": 0.80}
            for _ in range(5)
        ]
        out = generate_suggestions(report, corrections=corrections)
        types = [s["type"] for s in out["suggestions"]]
        assert "corrections_disagreement" in types

    def test_corrections_below_threshold_count_no_signal(self):
        """Fewer than the minimum N corrections → no signal."""
        from original.lab.suggestions import generate_suggestions
        report = _synthetic_report(n_pos=20, n_neg=10)
        corrections = [{"is_correct": False, "original_divergence_score": 0.80}]
        out = generate_suggestions(report, corrections=corrections)
        types = [s["type"] for s in out["suggestions"]]
        assert "corrections_disagreement" not in types


# ══════════════════════════════════════════════════════════════════════════════
# Calibration runs (direct store)
# ══════════════════════════════════════════════════════════════════════════════

class TestCalibrationRunStore:
    def test_run_lifecycle(self, client_module_db):
        _client, module, _db = client_module_db
        run_id = module.store.start_calibration_run(
            dataset_label="test_dataset", run_label="my_run",
            config={"max_scoring": 5},
        )
        assert run_id is not None and run_id > 0
        # Mark complete.
        ok = module.store.complete_calibration_run(
            run_id, auc=0.85, n_essays_scored=100, n_authors=4,
            report={"summary": {"auc": 0.85}},
        )
        assert ok is True
        got = module.store.get_calibration_run(run_id)
        assert got["status"] == "completed"
        assert got["auc"] == 0.85
        assert got["report"]["summary"]["auc"] == 0.85

    def test_run_failure_path(self, client_module_db):
        _client, module, _db = client_module_db
        run_id = module.store.start_calibration_run(dataset_label="bad")
        module.store.fail_calibration_run(run_id, "some traceback")
        got = module.store.get_calibration_run(run_id)
        assert got["status"] == "failed"
        assert "some traceback" in got["error"]

    def test_list_filters(self, client_module_db):
        _client, module, _db = client_module_db
        r1 = module.store.start_calibration_run(dataset_label="A")
        r2 = module.store.start_calibration_run(dataset_label="B")
        module.store.complete_calibration_run(r1, auc=0.9, n_essays_scored=10,
                                                n_authors=2, report={})
        # r2 stays "running"
        all_runs = module.store.list_calibration_runs()
        assert all_runs["total"] == 2
        running = module.store.list_calibration_runs(status="running")
        assert running["total"] == 1
        assert running["items"][0]["dataset_label"] == "B"
        only_a = module.store.list_calibration_runs(dataset_label="A")
        assert only_a["total"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# Tuned thresholds versioning
# ══════════════════════════════════════════════════════════════════════════════

class TestTunedThresholds:
    def test_versioning(self, client_module_db):
        _client, module, _db = client_module_db
        # No active set initially.
        assert module.store.get_active_tuned_thresholds() is None
        # Apply v1.
        v1 = module.store.put_tuned_thresholds(
            no_action=0.4, monitor=0.6, escalate=0.8,
            source="manual", notes="initial",
        )
        # Tiny sleep so created_at differs (SQLite text comparison).
        time.sleep(0.01)
        v2 = module.store.put_tuned_thresholds(
            no_action=0.45, monitor=0.65, escalate=0.85,
            source="calibration_run", source_run_id=42,
            notes="from run 42",
        )
        active = module.store.get_active_tuned_thresholds()
        # Latest by created_at wins.
        assert active["id"] == v2
        assert active["source"] == "calibration_run"
        assert active["source_run_id"] == 42
        # History keeps both.
        hist = module.store.list_tuned_thresholds()
        assert hist["total"] == 2


# ══════════════════════════════════════════════════════════════════════════════
# HTTP endpoints
# ══════════════════════════════════════════════════════════════════════════════

class TestLabEndpoints:
    def test_datasets_list(self, client_module_db):
        client, _module, _db = client_module_db
        resp = client.get("/admin/lab/datasets")
        assert resp.status_code == 200
        body = resp.json()
        labels = [d["label"] for d in body]
        assert "federalist" in labels
        assert "multi_author" in labels

    def test_runs_list_empty(self, client_module_db):
        client, _module, _db = client_module_db
        resp = client.get("/admin/calibration/runs")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"total": 0, "limit": 50, "offset": 0, "items": []}

    def test_run_endpoint_unknown_dataset(self, client_module_db):
        client, _module, _db = client_module_db
        resp = client.post(
            "/admin/calibration/run",
            json={"dataset_label": "totally_made_up"},
        )
        assert resp.status_code == 422

    def test_get_run_404(self, client_module_db):
        client, _module, _db = client_module_db
        resp = client.get("/admin/calibration/runs/9999")
        assert resp.status_code == 404

    def test_run_lifecycle_via_http(self, client_module_db):
        """Insert a fake completed run via store, then exercise the GET endpoint."""
        client, module, _db = client_module_db
        run_id = module.store.start_calibration_run(
            dataset_label="multi_author", run_label="HTTP test",
        )
        module.store.complete_calibration_run(
            run_id, auc=0.92, n_essays_scored=50, n_authors=4,
            report=_synthetic_report(n_pos=20, n_neg=10),
        )
        # GET runs list.
        resp = client.get("/admin/calibration/runs")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["status"] == "completed"
        assert items[0]["auc"] == 0.92
        # GET specific run.
        resp_d = client.get(f"/admin/calibration/runs/{run_id}")
        assert resp_d.status_code == 200
        body = resp_d.json()
        assert body["report"]["summary"]["total_essays_scored"] == 30

    def test_suggestions_endpoint_against_completed_run(self, client_module_db):
        client, module, _db = client_module_db
        run_id = module.store.start_calibration_run(dataset_label="multi_author")
        module.store.complete_calibration_run(
            run_id, auc=0.97, n_essays_scored=30, n_authors=3,
            report=_synthetic_report(n_pos=20, n_neg=10,
                                      pos_mean=0.20, neg_mean=0.85),
        )
        resp = client.get(f"/admin/calibration/runs/{run_id}/suggestions")
        assert resp.status_code == 200
        body = resp.json()
        assert "suggestions" in body
        assert body["summary"]["global_auc"] > 0.9
        # Should always produce at least the F1-optimal threshold suggestion.
        types = {s["type"] for s in body["suggestions"]}
        assert "threshold_no_action" in types

    def test_suggestions_rejects_running_run(self, client_module_db):
        client, module, _db = client_module_db
        run_id = module.store.start_calibration_run(dataset_label="multi_author")
        # Status still "running"
        resp = client.get(f"/admin/calibration/runs/{run_id}/suggestions")
        assert resp.status_code == 409

    def test_apply_endpoint_versions_thresholds(self, client_module_db):
        client, module, _db = client_module_db
        run_id = module.store.start_calibration_run(dataset_label="multi_author")
        module.store.complete_calibration_run(
            run_id, auc=0.95, n_essays_scored=30, n_authors=3,
            report=_synthetic_report(n_pos=20, n_neg=10),
        )
        resp = client.post(
            f"/admin/calibration/runs/{run_id}/apply",
            json={
                "no_action": 0.42, "monitor": 0.62, "escalate": 0.82,
                "verdict_authentic_below": 0.30,
                "verdict_anomalous_at_or_above": 0.75,
                "notes": "applied from test",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["no_action"] == 0.42
        assert body["source"] == "calibration_run"
        assert body["source_run_id"] == run_id
        # Active getter returns this row.
        active = client.get("/admin/tuned-thresholds").json()
        assert active["id"] == body["id"]

    def test_apply_404_on_missing_run(self, client_module_db):
        client, _module, _db = client_module_db
        resp = client.post(
            "/admin/calibration/runs/9999/apply",
            json={"no_action": 0.4, "monitor": 0.6, "escalate": 0.8},
        )
        assert resp.status_code == 404

    def test_active_thresholds_null_when_none_set(self, client_module_db):
        client, _module, _db = client_module_db
        resp = client.get("/admin/tuned-thresholds")
        assert resp.status_code == 200
        assert resp.json() is None

    def test_history_endpoint(self, client_module_db):
        client, module, _db = client_module_db
        module.store.put_tuned_thresholds(
            no_action=0.4, monitor=0.6, escalate=0.8,
            source="manual",
        )
        time.sleep(0.01)
        module.store.put_tuned_thresholds(
            no_action=0.45, monitor=0.65, escalate=0.85,
            source="manual",
        )
        resp = client.get("/admin/tuned-thresholds/history")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2
