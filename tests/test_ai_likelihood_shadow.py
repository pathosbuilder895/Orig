"""
tests/test_ai_likelihood_shadow.py — shadow mode for the AI-likelihood detector.

Contract under test (see docs/PILOT_RUNBOOK.md):
  AI_LIKELIHOOD_SHADOW=1  → compute + persist to ai_likelihood_scores ONLY;
                            the response field stays null and the rest of the
                            response is byte-identical to flags-off.
  AI_LIKELIHOOD_ENABLED=1 → attach AND persist (strict superset).
  Both off                → no row, field null.
Plus the FERPA surfaces: delete_student purges shadow rows and
data-inventory reports the count.
"""

from __future__ import annotations

import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient

import run
import original.store as store
from tests.test_ai_likelihood import _ESSAY, _make_fixture_artifact

app = run.load_legacy_demo_app()
client = TestClient(app)


@pytest.fixture()
def detector_reset():
    from original.ai_likelihood import reset_for_tests
    reset_for_tests()
    yield
    reset_for_tests()


@pytest.fixture()
def fixture_model(tmp_path, monkeypatch, detector_reset):
    """A loaded fixture artifact with low-band-guaranteeing thresholds off."""
    path = _make_fixture_artifact(tmp_path)
    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(path))
    return path


def _seed_student(sid: str) -> None:
    r = client.post(f"/students/{sid}/baseline",
                    json={"text": _ESSAY, "provenance": "proctored"})
    assert r.status_code == 200, r.text


def _score(sid: str, submission_id: str):
    r = client.post(f"/students/{sid}/score",
                    json={"text": _ESSAY, "submission_id": submission_id})
    assert r.status_code == 200, r.text
    return r.json()


def _rows_for(sid: str):
    return store.get_ai_likelihood_scores(student_id=sid)


# ── 1. Shadow: persists, never surfaces ───────────────────────────────────────

def test_shadow_persists_row_but_response_stays_null(monkeypatch, fixture_model):
    monkeypatch.delenv("AI_LIKELIHOOD_ENABLED", raising=False)
    monkeypatch.setenv("AI_LIKELIHOOD_SHADOW", "1")

    sid = f"shadow_persist_{uuid.uuid4().hex[:8]}"
    _seed_student(sid)
    resp = _score(sid, "shadow_sub_1")

    assert resp["ai_likelihood"] is None, "shadow mode must never surface"
    rows = _rows_for(sid)
    assert len(rows) == 1
    row = rows[0]
    assert row["submission_id"] == "shadow_sub_1"
    assert 0.0 <= row["probability"] <= 1.0
    assert row["band"] in ("low", "elevated", "strong")
    assert row["model_version"] == "v1"

    # The persisted number matches what the detector says for the same vec.
    from original.ai_likelihood import predict_ai_likelihood
    from original.features.pipeline import feature_vector
    direct = predict_ai_likelihood(feature_vector(_ESSAY))
    assert direct is not None
    assert abs(direct.probability - row["probability"]) < 0.05  # adaptive-pipeline vec may differ slightly
    assert isinstance(row["created_at"], str) and row["created_at"]


# ── 2. Both flags off: no row ─────────────────────────────────────────────────

def test_flags_off_writes_no_row(monkeypatch, fixture_model):
    monkeypatch.delenv("AI_LIKELIHOOD_ENABLED", raising=False)
    monkeypatch.delenv("AI_LIKELIHOOD_SHADOW", raising=False)

    sid = f"shadow_off_{uuid.uuid4().hex[:8]}"
    _seed_student(sid)
    resp = _score(sid, "off_sub_1")
    assert resp["ai_likelihood"] is None
    assert _rows_for(sid) == []


# ── 3. Enabled: attaches AND persists ─────────────────────────────────────────

def test_enabled_attaches_and_persists(monkeypatch, fixture_model):
    monkeypatch.setenv("AI_LIKELIHOOD_ENABLED", "1")
    monkeypatch.delenv("AI_LIKELIHOOD_SHADOW", raising=False)

    sid = f"shadow_enabled_{uuid.uuid4().hex[:8]}"
    _seed_student(sid)
    resp = _score(sid, "enabled_sub_1")

    assert resp["ai_likelihood"] is not None
    rows = _rows_for(sid)
    assert len(rows) == 1
    assert rows[0]["probability"] == pytest.approx(
        resp["ai_likelihood"]["probability"], abs=1e-9)
    assert rows[0]["band"] == resp["ai_likelihood"]["band"]


# ── 4. Shadow is byte-invisible ───────────────────────────────────────────────

def test_shadow_response_identical_to_flags_off(monkeypatch, fixture_model):
    # Deterministic Phase 1 path for the comparison.
    monkeypatch.setenv("CONTEXT_MANIFEST_ENABLED", "0")
    monkeypatch.setenv("ADAPTIVE_WEIGHTS_ENABLED", "0")
    monkeypatch.delenv("AI_LIKELIHOOD_ENABLED", raising=False)
    monkeypatch.delenv("AI_LIKELIHOOD_SHADOW", raising=False)

    sid = f"shadow_ident_{uuid.uuid4().hex[:8]}"
    _seed_student(sid)
    resp_off = _score(sid, "ident_sub")

    monkeypatch.setenv("AI_LIKELIHOOD_SHADOW", "1")
    resp_shadow = _score(sid, "ident_sub")

    assert resp_shadow == resp_off, (
        "shadow mode must be byte-invisible in the API response")
    assert len(_rows_for(sid)) == 1  # but the row landed


# ── 5. Re-score keeps one row ─────────────────────────────────────────────────

def test_rescore_same_submission_keeps_one_row(monkeypatch, fixture_model):
    monkeypatch.setenv("AI_LIKELIHOOD_SHADOW", "1")
    monkeypatch.delenv("AI_LIKELIHOOD_ENABLED", raising=False)

    sid = f"shadow_rescore_{uuid.uuid4().hex[:8]}"
    _seed_student(sid)
    _score(sid, "rescore_sub")
    client.post(f"/students/{sid}/score?force=true",
                json={"text": _ESSAY, "submission_id": "rescore_sub"})
    assert len(_rows_for(sid)) == 1, "INSERT OR REPLACE must keep one row"


# ── 6. FERPA surfaces ─────────────────────────────────────────────────────────

def test_delete_student_purges_shadow_rows(monkeypatch, fixture_model):
    monkeypatch.setenv("AI_LIKELIHOOD_SHADOW", "1")
    monkeypatch.delenv("AI_LIKELIHOOD_ENABLED", raising=False)

    sid = f"shadow_ferpa_{uuid.uuid4().hex[:8]}"
    _seed_student(sid)
    _score(sid, "ferpa_sub")
    assert len(_rows_for(sid)) == 1

    inv = client.get(f"/students/{sid}/data-inventory")
    assert inv.status_code == 200
    assert inv.json()["data_categories"]["ai_likelihood_scores"]["count"] == 1

    r = client.delete(f"/students/{sid}")
    assert r.status_code == 200
    assert "AI-likelihood" in r.json()["message"]
    assert _rows_for(sid) == []


# ── 7. Store round-trip on an isolated DB ─────────────────────────────────────

def test_store_roundtrip_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_DB_PATH", tmp_path / "shadow_test.db")
    store.put_ai_likelihood_score("sub_x", "stud_x", 0.7312, "elevated", "v1")
    store.put_ai_likelihood_score("sub_y", "stud_x", 0.1, "low", "v1")
    store.put_ai_likelihood_score("sub_z", "stud_other", 0.95, "strong", "v1")

    rows = store.get_ai_likelihood_scores(student_id="stud_x")
    assert {r["submission_id"] for r in rows} == {"sub_x", "sub_y"}
    assert rows[0]["created_at"] >= rows[1]["created_at"]  # newest first

    all_rows = store.get_ai_likelihood_scores()
    assert len(all_rows) == 3
    x = next(r for r in all_rows if r["submission_id"] == "sub_x")
    assert x["probability"] == pytest.approx(0.7312)
    assert x["band"] == "elevated"
    assert x["model_version"] == "v1"
