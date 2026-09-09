from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from scripts.shadow_soak_report import (
    _readonly_engine,
    build_report,
    summarize_logs,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


def test_absent_is_distinct_from_zero():
    report = summarize_logs(["ordinary application line"])
    assert report["genre"]["no_shadow_lines_found"] is True
    assert "sermon_watch" not in report["genre"]
    assert report["topic"]["signal_absent"] is True
    assert report["topic"]["share_above_0_25"] is None
    assert report["characteristic_weights"]["signal_absent"] is True


def test_log_sections_aggregate_without_identifiers():
    lines = (FIXTURES / "shadow_soak.log").read_text().splitlines()
    report = summarize_logs(lines)
    rendered = str(report)
    assert report["genre"]["abstention_rate"] == pytest.approx(1 / 3)
    assert report["genre"]["sermon_watch"]["v1_sermon_to_v2_scholarly_or_narrative"] == 1
    assert report["topic"]["share_above_0_25"] == pytest.approx(0.5)
    assert report["topic"]["degraded_share"] == pytest.approx(0.5)
    assert "student_id" not in rendered
    assert "submission_id" not in rendered


def test_database_sections_are_aggregated(tmp_path):
    db = tmp_path / "shadow.db"
    conn = sqlite3.connect(db)
    conn.executescript((FIXTURES / "shadow_soak.sql").read_text())
    conn.close()

    report = build_report([], str(db))
    assert report["fused_score"]["rows"] == 4
    assert report["fused_score"]["confound_ready_rows"] == 4
    # the previously-shipped script queried a "fused_score" column that the
    # real schema never had; this asserts against the columns store.py
    # actually creates (fused_log_odds, probability).
    assert report["fused_score"]["probability"]["n"] == 4
    assert report["fused_score"]["baseline_volume_confound"]["verdict"] in (
        "measured",
        "uninformative",
    )

    ai = report["ai_likelihood"]
    assert ai["rows"] == 1
    assert "go_no_go" in ai
    assert "student_id" not in str(ai)
    assert "submission_id" not in str(ai)

    prior = report["bayesian_prior_scope"]
    assert prior["changes_scores"] is True
    assert "measurement" in prior or "error" in prior


def test_database_url_and_path_agree(tmp_path):
    db = tmp_path / "shadow.db"
    conn = sqlite3.connect(db)
    conn.executescript((FIXTURES / "shadow_soak.sql").read_text())
    conn.close()

    by_path = build_report([], str(db))
    by_url = build_report([], f"sqlite:///{db}")
    assert by_path["fused_score"]["rows"] == by_url["fused_score"]["rows"]
    assert by_path["ai_likelihood"]["rows"] == by_url["ai_likelihood"]["rows"]


def test_no_database_supplied_reports_absent_not_zero():
    report = build_report(["ordinary application line"], None)
    assert report["fused_score"]["signal_absent"] is True
    assert report["ai_likelihood"]["signal_absent"] is True
    assert report["bayesian_prior_scope"]["reason"] == "database not supplied"


def test_ai_likelihood_without_fidelity_table_notes_the_gap(tmp_path):
    db = tmp_path / "no_fidelity.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE ai_likelihood_scores (probability REAL, band TEXT);"
        "INSERT INTO ai_likelihood_scores VALUES (0.2, 'low');"
    )
    conn.close()
    report = build_report([], str(db))
    assert report["ai_likelihood"]["rows"] == 1
    assert "go_no_go" not in report["ai_likelihood"]
    assert "gate_note" in report["ai_likelihood"]


@pytest.mark.postgres
def test_postgres_url_fixture_is_supported():
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("set DATABASE_URL to the isolated local Postgres test database")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"local Postgres fixture is unreachable: {exc}")
    finally:
        engine.dispose()
    report = build_report([], url)
    assert set(report) >= {
        "genre",
        "topic",
        "characteristic_weights",
        "fused_score",
        "ai_likelihood",
        "bayesian_prior_scope",
    }


def test_reader_connection_is_read_only(tmp_path):
    """The reporter is pointed straight at the live pilot DB, so its
    connection must reject writes, not merely happen to issue only SELECTs
    (Part 3 Global Constraint; mirrors scripts/tier17_report.py)."""
    db = tmp_path / "ro.db"
    conn = sqlite3.connect(db)
    conn.executescript("CREATE TABLE t (x INTEGER); INSERT INTO t VALUES (1);")
    conn.close()

    engine = _readonly_engine(f"sqlite:///{db}")
    try:
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM t")).scalar() == 1
            with pytest.raises(OperationalError):
                c.execute(text("INSERT INTO t VALUES (2)"))
    finally:
        engine.dispose()
