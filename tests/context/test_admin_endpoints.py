"""
tests/context/test_admin_endpoints.py — PR 7 admin / playground / corrections.

Covers:
- Direct store helpers: list_manifests filters, manifest_stats roll-ups,
  put_correction auto-fill, list_corrections filters
- HTTP endpoints via FastAPI TestClient:
  - GET  /admin/manifests       (pagination + filter combinations)
  - GET  /admin/manifests/stats (roll-ups under date filter)
  - POST /submissions/{id}/correct (validation, auto-fill, multi-correction)
  - GET  /admin/corrections     (filters)
  - POST /test/score            (no-DB-write playground, blend on/off)
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from typing import Tuple

import numpy as np
import pytest

from original.constants import FEATURE_DIM


# ── Test fixtures ────────────────────────────────────────────────────────────

_API_MODULE = None         # Loaded once per process — costly import.

def _load_api_module_once():
    """Load api.py via the run.py shim once per process and reuse."""
    global _API_MODULE
    if _API_MODULE is not None:
        return _API_MODULE
    BACKEND_ROOT = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "original._legacy_demo_api_admin_tests",
        BACKEND_ROOT / "original" / "api.py",
    )
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "original"
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _API_MODULE = module
    return module


def _fresh_db_and_app():
    """
    Build a TestClient bound to a *fresh* SQLite DB.

    Strategy: keep the api module loaded for the whole session (avoiding
    the multi-second import cost), but redirect the existing
    ``original.store`` module's DB path + caches at each test's tmp file.
    Way faster + simpler than tearing down sys.modules between tests.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()

    module = _load_api_module_once()

    # Redirect the live store at this test's DB and clear in-memory caches.
    # `_DB_PATH` is read each time `_get_conn()` is called, so flipping the
    # module-level constant takes effect immediately.
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
    # Clean up: clear caches so the next test sees a clean store.
    module.store._STORE.clear()
    module.store._loaded = False
    os.unlink(db_path)


def _seed_manifests(module, n: int = 5):
    """Populate the manifest audit table with N synthetic rows."""
    from original.context.manifest import build_manifest
    from original.context.resolvers import run_resolvers
    for i in range(n):
        text = "test text " * (50 + i * 20)
        out = run_resolvers(text, ["B1.", "B2."])
        m = build_manifest(f"sub_{i}", out)
        action = "no_action" if i < 3 else "monitor"
        div = 0.1 + i * 0.15
        module.store.put_manifest(
            f"sub_{i}", f"student_{i % 2}", m,
            divergence_score=div, action=action,
        )


# ══════════════════════════════════════════════════════════════════════════════
# Direct store-helper tests (no HTTP)
# ══════════════════════════════════════════════════════════════════════════════

class TestStoreHelpers:
    def test_list_manifests_pagination(self, client_module_db):
        _client, module, _db = client_module_db
        _seed_manifests(module, n=5)
        r = module.store.list_manifests(limit=2, offset=0)
        assert r["total"] == 5
        assert len(r["items"]) == 2
        r2 = module.store.list_manifests(limit=2, offset=2)
        assert r2["total"] == 5
        assert len(r2["items"]) == 2
        # No overlap between pages.
        page1_ids = {x["submission_id"] for x in r["items"]}
        page2_ids = {x["submission_id"] for x in r2["items"]}
        assert not (page1_ids & page2_ids)

    def test_list_manifests_filter_by_action(self, client_module_db):
        _client, module, _db = client_module_db
        _seed_manifests(module, n=5)
        r = module.store.list_manifests(action="monitor")
        assert r["total"] == 2
        assert all(i["action"] == "monitor" for i in r["items"])

    def test_list_manifests_filter_by_student(self, client_module_db):
        _client, module, _db = client_module_db
        _seed_manifests(module, n=5)
        r = module.store.list_manifests(student_id="student_0")
        # student_0 gets sub_0, sub_2, sub_4 (i % 2 == 0)
        assert r["total"] == 3
        assert all(i["student_id"] == "student_0" for i in r["items"])

    def test_list_manifests_filter_by_flag(self, client_module_db):
        _client, module, _db = client_module_db
        _seed_manifests(module, n=5)
        # All synthetic manifests built from this short text fire
        # `topic_novelty_high` (the resolvers see no overlap with the
        # "B1./B2." baselines). So filter must return 5.
        r = module.store.list_manifests(flag="topic_novelty_high")
        assert r["total"] == 5

    def test_manifest_stats_roll_ups(self, client_module_db):
        _client, module, _db = client_module_db
        _seed_manifests(module, n=5)
        s = module.store.manifest_stats()
        assert s["total"] == 5
        assert s["by_action"].get("no_action") == 3
        assert s["by_action"].get("monitor") == 2
        assert s["by_flag"].get("topic_novelty_high") == 5
        assert s["mean_divergence"] is not None

    def test_put_correction_auto_fills_from_manifest(self, client_module_db):
        _client, module, _db = client_module_db
        _seed_manifests(module, n=5)
        cid = module.store.put_correction(
            "sub_3", is_correct=False,
            corrected_verdict="authentic",
            reviewer="prof_a", notes="Stylistically consistent.",
        )
        assert cid is not None and cid > 0
        listed = module.store.list_corrections()
        assert listed["total"] == 1
        item = listed["items"][0]
        # Auto-filled from the manifest audit log.
        assert item["student_id"] == "student_1"      # sub_3 → student_(3%2)
        assert item["original_action"] == "monitor"
        assert item["original_divergence_score"] is not None
        assert item["is_correct"] is False
        assert item["corrected_verdict"] == "authentic"

    def test_list_corrections_filters(self, client_module_db):
        _client, module, _db = client_module_db
        _seed_manifests(module, n=3)
        module.store.put_correction("sub_0", is_correct=True, reviewer="a")
        module.store.put_correction("sub_1", is_correct=False, reviewer="b")
        module.store.put_correction("sub_2", is_correct=False, reviewer="c")
        all_ = module.store.list_corrections()
        assert all_["total"] == 3
        only_wrong = module.store.list_corrections(is_correct=False)
        assert only_wrong["total"] == 2
        for_sub_1 = module.store.list_corrections(submission_id="sub_1")
        assert for_sub_1["total"] == 1
        assert for_sub_1["items"][0]["reviewer"] == "b"


# ══════════════════════════════════════════════════════════════════════════════
# HTTP endpoint tests
# ══════════════════════════════════════════════════════════════════════════════

class TestAdminManifestsEndpoint:
    def test_empty_db_returns_zero(self, client_module_db):
        client, _module, _db = client_module_db
        resp = client.get("/admin/manifests")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"total": 0, "limit": 100, "offset": 0, "items": []}

    def test_seed_and_list(self, client_module_db):
        client, module, _db = client_module_db
        _seed_manifests(module, n=4)
        resp = client.get("/admin/manifests")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 4
        assert len(body["items"]) == 4
        # Ordering: most-recent first (DESC by created_at).
        # All four were inserted in the same loop so ordering by created_at
        # may be ambiguous; only check the shape.
        for item in body["items"]:
            assert {"submission_id", "student_id", "created_at", "flags",
                    "anchor_tiers", "length_regime"}.issubset(item.keys())

    def test_filter_by_action_via_http(self, client_module_db):
        client, module, _db = client_module_db
        _seed_manifests(module, n=5)
        resp = client.get("/admin/manifests", params={"action": "monitor"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2

    def test_pagination_via_http(self, client_module_db):
        client, module, _db = client_module_db
        _seed_manifests(module, n=5)
        page1 = client.get("/admin/manifests", params={"limit": 2, "offset": 0}).json()
        page2 = client.get("/admin/manifests", params={"limit": 2, "offset": 2}).json()
        assert page1["total"] == 5 and page2["total"] == 5
        assert len(page1["items"]) == 2 and len(page2["items"]) == 2
        assert {i["submission_id"] for i in page1["items"]} \
                .isdisjoint({i["submission_id"] for i in page2["items"]})

    def test_invalid_limit_returns_422(self, client_module_db):
        client, _module, _db = client_module_db
        resp = client.get("/admin/manifests", params={"limit": 0})
        assert resp.status_code == 422
        resp = client.get("/admin/manifests", params={"limit": 5000})
        assert resp.status_code == 422


class TestAdminStatsEndpoint:
    def test_stats_endpoint(self, client_module_db):
        client, module, _db = client_module_db
        _seed_manifests(module, n=5)
        resp = client.get("/admin/manifests/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5
        assert body["by_action"]["no_action"] == 3
        assert body["by_action"]["monitor"] == 2
        assert "topic_novelty_high" in body["by_flag"]


class TestCorrectionEndpoint:
    def test_correction_flow_round_trip(self, client_module_db):
        client, module, _db = client_module_db
        _seed_manifests(module, n=3)
        # Submit a correction.
        resp = client.post(
            "/submissions/sub_2/correct",
            json={
                "is_correct": False,
                "corrected_verdict": "authentic",
                "corrected_action": "no_action",
                "reviewer": "prof_x",
                "notes": "Style is consistent across baselines.",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["submission_id"] == "sub_2"
        assert body["is_correct"] is False
        assert body["corrected_verdict"] == "authentic"
        assert body["reviewer"] == "prof_x"
        # Auto-fill from manifest audit log.
        assert body["student_id"] is not None
        assert body["original_action"] is not None

    def test_correction_validation_rejects_bad_verdict(self, client_module_db):
        client, _module, _db = client_module_db
        resp = client.post(
            "/submissions/whatever/correct",
            json={"is_correct": False, "corrected_verdict": "totally_made_up"},
        )
        assert resp.status_code == 422

    def test_correction_validation_rejects_bad_action(self, client_module_db):
        client, _module, _db = client_module_db
        resp = client.post(
            "/submissions/whatever/correct",
            json={"is_correct": False, "corrected_action": "explode_user"},
        )
        assert resp.status_code == 422

    def test_correction_minimal_payload(self, client_module_db):
        # is_correct is the only required field.
        client, _module, _db = client_module_db
        resp = client.post(
            "/submissions/abc/correct",
            json={"is_correct": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_correct"] is True

    def test_multiple_corrections_per_submission_allowed(self, client_module_db):
        client, _module, _db = client_module_db
        for _ in range(3):
            resp = client.post(
                "/submissions/sub_x/correct",
                json={"is_correct": False, "reviewer": "ta"},
            )
            assert resp.status_code == 200
        listed = client.get(
            "/admin/corrections", params={"submission_id": "sub_x"},
        ).json()
        assert listed["total"] == 3


class TestAdminCorrectionsListEndpoint:
    def test_list_corrections_via_http(self, client_module_db):
        client, _module, _db = client_module_db
        client.post("/submissions/s1/correct", json={"is_correct": True})
        client.post("/submissions/s2/correct", json={"is_correct": False})
        resp = client.get("/admin/corrections")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2

    def test_filter_by_is_correct(self, client_module_db):
        client, _module, _db = client_module_db
        client.post("/submissions/s1/correct", json={"is_correct": True})
        client.post("/submissions/s2/correct", json={"is_correct": False})
        client.post("/submissions/s3/correct", json={"is_correct": False})
        wrong_only = client.get(
            "/admin/corrections", params={"is_correct": "false"},
        ).json()
        assert wrong_only["total"] == 2


# ══════════════════════════════════════════════════════════════════════════════
# Playground endpoint
# ══════════════════════════════════════════════════════════════════════════════

class TestPlaygroundEndpoint:
    def test_playground_runs_pipeline(self, client_module_db):
        client, _module, _db = client_module_db
        text = "The committee considered the proposal carefully. " * 30
        resp = client.post(
            "/test/score",
            json={
                "text": text,
                "baseline_texts": [
                    "Earlier baseline submission for the test student.",
                    "Another baseline with similar style.",
                    "A third baseline rounding out the corpus.",
                ],
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Layer7 must be populated.
        assert body["layer7"]["submission_id"] == "playground"
        assert "authorship" in body["layer7"]
        assert body["layer7"]["context_manifest"] is not None
        assert body["layer7"]["report"] is not None
        # By default, blend is OFF.
        assert body["blend"] is None

    def test_playground_with_blend(self, client_module_db):
        client, _module, _db = client_module_db
        text = "The committee considered the proposal carefully. " * 60
        resp = client.post(
            "/test/score",
            json={
                "text": text,
                "baseline_texts": [
                    "Earlier baseline submission for the test student.",
                    "Another baseline with similar style.",
                ],
                "enable_blend": True,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["blend"] is not None
        assert "blend_index" in body["blend"]
        assert isinstance(body["blend"]["per_section"], list)

    def test_playground_no_db_writes(self, client_module_db):
        client, module, _db = client_module_db
        # Confirm the audit table is empty before.
        before = module.store.list_manifests()["total"]
        client.post(
            "/test/score",
            json={
                "text": "An inline submission. " * 30,
                "baseline_texts": ["Inline baseline 1.", "Inline baseline 2."],
            },
        )
        # ... and after.
        after = module.store.list_manifests()["total"]
        assert before == after, "playground must not persist manifests"
        # Same for corrections.
        assert module.store.list_corrections()["total"] == 0

    def test_playground_validation_empty_baselines(self, client_module_db):
        client, _module, _db = client_module_db
        resp = client.post(
            "/test/score",
            json={"text": "Some submission text.", "baseline_texts": []},
        )
        assert resp.status_code == 422

    def test_playground_validation_too_many_baselines(self, client_module_db):
        client, _module, _db = client_module_db
        resp = client.post(
            "/test/score",
            json={
                "text": "Some submission text.",
                "baseline_texts": ["b"] * 11,
            },
        )
        assert resp.status_code == 422

    def test_playground_validation_strips_blanks(self, client_module_db):
        client, _module, _db = client_module_db
        resp = client.post(
            "/test/score",
            json={
                "text": "Some submission text. " * 20,
                # All baselines are blank → rejected.
                "baseline_texts": ["", "  ", "\n"],
            },
        )
        assert resp.status_code == 422
