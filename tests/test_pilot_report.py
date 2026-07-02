"""
tests/test_pilot_report.py — the weekly ops report script against a seeded tmp DB.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

import original.store as store

_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "pilot_report", _ROOT / "scripts" / "pilot_report.py")
pilot_report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pilot_report)


@pytest.fixture()
def seeded_db(tmp_path, monkeypatch):
    db = tmp_path / "pilot.db"
    monkeypatch.setattr(store, "_DB_PATH", db)

    store.put_fidelity_score("sub_1", "stud_a", 0.8, is_authentic=True)
    store.put_fidelity_score("sub_2", "stud_a", 0.4, is_authentic=False)
    store.put_ai_likelihood_score("sub_1", "stud_a", 0.2, "low", "v1")
    store.put_ai_likelihood_score("sub_2", "stud_a", 0.88, "elevated", "v1")
    store.put_ai_likelihood_score("sub_3", "stud_b", 0.97, "strong", "v1")
    store.log_audit(action="score", student_id="stud_a")
    store.log_audit(action="score", student_id="stud_b")
    store.log_audit(action="baseline_add", student_id="stud_a")
    return db


def test_report_renders_all_sections(seeded_db, capsys):
    assert pilot_report.main(["--db", str(seeded_db), "--since-days", "7"]) == 0
    out = capsys.readouterr().out
    for heading in ("## Activity", "## Scoring outcomes", "## Corrections",
                    "## AI-likelihood (shadow)", "## Data hygiene"):
        assert heading in out
    assert "Distinct active students: **2**" in out
    assert "'elevated': 1" in out and "'strong': 1" in out
    assert "1 at elevated" not in out  # elevated+strong = 2 would-be flags
    assert "2 at elevated" in out and "1 at strong" in out


def test_json_output(seeded_db, tmp_path):
    out_json = tmp_path / "report.json"
    assert pilot_report.main(
        ["--db", str(seeded_db), "--json", str(out_json)]) == 0
    data = json.loads(out_json.read_text())
    assert data["ai_likelihood"]["rows"] == 3
    assert data["ai_likelihood"]["would_flag_at_elevated"] == 2
    assert data["scoring"]["fidelity_rows"] == 2
    assert data["scoring"]["labeled_authentic"] == 1


def test_missing_db_exits_1(tmp_path):
    assert pilot_report.main(["--db", str(tmp_path / "nope.db")]) == 1


def test_window_filters_old_rows(seeded_db):
    # A 0-day window excludes everything written "now"? No — since is now-0d
    # = now, and rows were written momentarily before. Use a large negative
    # test instead: a 1000-day window includes all rows.
    conn = pilot_report._connect_readonly(seeded_db)
    try:
        data = pilot_report.collect(conn, "2020-01-01T00:00:00")
    finally:
        conn.close()
    assert data["ai_likelihood"]["rows"] == 3
    conn = pilot_report._connect_readonly(seeded_db)
    try:
        future = pilot_report.collect(conn, "2999-01-01T00:00:00")
    finally:
        conn.close()
    assert future["ai_likelihood"]["rows"] == 0
    assert future["scoring"]["fidelity_rows"] == 0
