import sqlite3

from scripts.shadow_soak_report import build_report, summarize_logs


def test_absent_is_distinct_from_zero():
    report = summarize_logs(["ordinary application line"])
    assert report["genre"]["no_shadow_lines_found"] is True
    assert report["topic"]["signal_absent"] is True
    assert report["topic"]["share_above_0_25"] is None
    assert report["characteristic_weights"]["signal_absent"] is True


def test_log_sections_aggregate_without_identifiers():
    lines = [
        "genre_shadow v1=correspondence v2=unknown v2_confidence=0.40",
        "topic_inflation mode=shadow d=0.10 mean_inflation=1.0 deviation=0.2",
        "characteristic_weights mode=shadow outcome=applied dispersion=0.005 "
        "deviation=0.2 deviation_preview=0.2",
    ]
    report = build_report(lines)
    rendered = str(report)
    assert report["genre"]["abstention_rate"] == 1.0
    assert report["topic"]["share_above_0_25"] == 0.0
    assert "production no-op" in report["topic"]["verdict"]
    assert "student_id" not in rendered
    assert "submission_id" not in rendered


def test_database_sections_are_aggregated(tmp_path):
    db = tmp_path / "shadow.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE fused_scores (
          fused_score REAL, band TEXT, channels_json TEXT,
          baseline_samples INTEGER, reference_profiles INTEGER
        );
        INSERT INTO fused_scores VALUES (0.7, 'elevated', '{}', 3, 8);
        CREATE TABLE ai_likelihood_scores (probability REAL, band TEXT);
        INSERT INTO ai_likelihood_scores VALUES (0.2, 'low');
        """
    )
    conn.commit()
    conn.close()

    report = build_report([], db)
    assert report["fused_score"]["rows"] == 1
    assert report["fused_score"]["confound_ready_rows"] == 1
    assert report["ai_likelihood"]["bands"] == {"low": 1}
