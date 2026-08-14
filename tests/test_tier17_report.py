"""
tests/test_tier17_report.py — the Tier 17 shadow-readiness report script.

Seeds a scratch SQLite DB with raw `student_profiles` rows carrying a
`keystroke_data` blob per sample — the shape Bbook's proctored submissions
produce once persisted. Rows are inserted directly via sqlite3 rather than
through `original.store`, to isolate this script's own parsing/aggregation
logic from the store's serialization round trip (that round trip has its own
dedicated coverage in tests/test_keystroke_data_persistence.py, including an
end-to-end test that seeds through `original.store.put()` and points this
script at the resulting file).

`store._serialize()` now does round-trip `keystroke_data` (see
original/store.py) — this file's use of raw inserts is a deliberate test
isolation choice, not a workaround for a missing capability.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "tier17_report", _ROOT / "scripts" / "tier17_report.py"
)
tier17_report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tier17_report)


# ── Synthetic keystroke-data fixtures ──────────────────────────────────────────
# "composer": hesitant/bursty typing, real revisions, long thinking pauses.
# "transcriber": metronomic typing, zero deletions/revisions, no long pauses —
# the profile you'd expect from someone retyping a finished text.


def _composer_keystroke_data(word_count: int = 300) -> dict:
    keystrokes = []
    elapsed = 0.0
    for i in range(120):
        # Alternate rapid bursts and hesitant gaps -> high CV, mixed burst ratio.
        gap = 60.0 if i % 2 == 0 else 420.0
        elapsed += gap
        key = "Backspace" if i % 15 == 0 else "a"
        keystrokes.append({"key": key, "elapsed": elapsed})
    return {
        "keystrokes": keystrokes,
        "pauses": [{"duration": 3500}, {"duration": 4200}, {"duration": 5000}],
        "revisions": [
            {"type": "delete", "charsAffected": 3},
            {"type": "delete", "charsAffected": 12},
            {"type": "backspace", "charsAffected": 1},
        ],
        "wordCount": word_count,
    }


def _transcriber_keystroke_data(word_count: int = 300) -> dict:
    keystrokes = []
    elapsed = 0.0
    for _i in range(120):
        elapsed += 120.0  # uniform interval -> low CV, high burst ratio
        keystrokes.append({"key": "a", "elapsed": elapsed})
    return {
        "keystrokes": keystrokes,
        "pauses": [],
        "revisions": [],
        "deletionRate": 0.0,
        "wordCount": word_count,
    }


def _insert_student(conn: sqlite3.Connection, student_id: str, samples: list[dict]) -> None:
    conn.execute(
        "INSERT INTO student_profiles (student_id, data) VALUES (?, ?)",
        (student_id, json.dumps({"student_id": student_id, "samples": samples})),
    )
    conn.commit()


def _sample(provenance: str = "proctored", keystroke_data: dict | None = None) -> dict:
    s = {"text": "irrelevant", "provenance": provenance, "auth_weight": 1.0}
    if keystroke_data is not None:
        s["keystroke_data"] = keystroke_data
    return s


@pytest.fixture()
def empty_db(tmp_path) -> Path:
    db = tmp_path / "empty.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE student_profiles (student_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
    conn.commit()
    conn.close()
    return db


@pytest.fixture()
def ready_db(tmp_path) -> Path:
    """5 students x 5 proctored samples, alternating composer/transcriber."""
    db = tmp_path / "ready.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE student_profiles (student_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
    for i in range(5):
        samples = []
        for j in range(5):
            kd = _composer_keystroke_data() if (i + j) % 2 == 0 else _transcriber_keystroke_data()
            samples.append(_sample("proctored", kd))
        _insert_student(conn, f"stud_{i}", samples)
    conn.close()
    return db


def test_missing_db_exits_1(tmp_path):
    assert tier17_report.main(["--db", str(tmp_path / "nope.db")]) == 1


def test_no_keystroke_data_is_not_ready(empty_db, capsys):
    assert tier17_report.main(["--db", str(empty_db)]) == 0
    out = capsys.readouterr().out
    assert "Verdict: **NOT READY**" in out
    assert "proctored samples with keystroke data: **0**" in out


def test_current_production_shape_has_no_keystroke_data(tmp_path, capsys):
    """Samples exist (vectors, provenance) but none carry keystroke_data —
    today's actual persisted shape, since the baseline endpoint discards the
    raw blob after feature extraction. Must not crash; must report 0/NOT READY."""
    db = tmp_path / "prod_shape.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE student_profiles (student_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
    _insert_student(
        conn,
        "stud_real",
        [_sample("proctored", keystroke_data=None), _sample("verified", keystroke_data=None)],
    )
    conn.close()
    assert tier17_report.main(["--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "Verdict: **NOT READY**" in out
    assert "proctored samples with keystroke data: **0**" in out


def test_non_proctored_samples_are_excluded(tmp_path):
    db = tmp_path / "unverified.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE student_profiles (student_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
    samples = [
        _sample("unverified", _composer_keystroke_data()),
        _sample("verified", _composer_keystroke_data()),
        _sample("proctored", _composer_keystroke_data()),
    ]
    _insert_student(conn, "stud_mixed", samples)
    conn.close()
    conn = tier17_report._connect_readonly(db)
    try:
        samples_found = tier17_report._fetch_keystroke_samples(conn)
    finally:
        conn.close()
    assert len(samples_found) == 1


def test_ready_verdict_on_sufficient_nondegenerate_corpus(ready_db, capsys):
    assert tier17_report.main(["--db", str(ready_db)]) == 0
    out = capsys.readouterr().out
    assert "proctored samples with keystroke data: **25**" in out
    assert "distinct students: **5**" in out
    assert "Verdict: **READY**" in out


def test_insufficient_sample_count_is_not_ready(tmp_path):
    """4 students (< 5), each with plenty of varied samples: student-count
    gate must block READY even though the feature distributions vary."""
    db = tmp_path / "few_students.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE student_profiles (student_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
    for i in range(4):
        samples = [
            _sample(
                "proctored",
                _composer_keystroke_data() if j % 2 == 0 else _transcriber_keystroke_data(),
            )
            for j in range(10)
        ]
        _insert_student(conn, f"stud_{i}", samples)
    conn.close()
    report = tier17_report.build_report(
        tier17_report._fetch_keystroke_samples(tier17_report._connect_readonly(db))
    )
    assert report["totals"]["proctored_samples_with_keystroke_data"] == 40
    assert report["totals"]["distinct_students"] == 4
    assert report["verdict"] == "NOT READY"


def test_degenerate_distributions_block_ready_despite_volume(tmp_path):
    """25 samples across 5 students clears the volume gate, but every sample
    uses the identical profile -> p10 == p90 on every feature -> NOT READY."""
    db = tmp_path / "degenerate.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE student_profiles (student_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
    for i in range(5):
        samples = [_sample("proctored", _transcriber_keystroke_data()) for _ in range(5)]
        _insert_student(conn, f"stud_{i}", samples)
    conn.close()
    report = tier17_report.build_report(
        tier17_report._fetch_keystroke_samples(tier17_report._connect_readonly(db))
    )
    assert report["totals"]["proctored_samples_with_keystroke_data"] == 25
    assert report["totals"]["distinct_students"] == 5
    assert report["gate"]["nondegenerate_features"] == 0
    assert report["verdict"] == "NOT READY"


def test_build_report_percentiles_are_computed_per_feature(ready_db):
    conn = tier17_report._connect_readonly(ready_db)
    try:
        samples = tier17_report._fetch_keystroke_samples(conn)
    finally:
        conn.close()
    report = tier17_report.build_report(samples)
    for feature in tier17_report.FEATURES:
        stats = report["features"][feature]
        assert stats["n"] == 25
        assert stats["p10"] <= stats["p50"] <= stats["p90"]


def test_json_output(ready_db, tmp_path):
    out_json = tmp_path / "tier17.json"
    assert tier17_report.main(["--db", str(ready_db), "--out-json", str(out_json)]) == 0
    data = json.loads(out_json.read_text())
    assert data["verdict"] == "READY"
    assert data["totals"]["distinct_students"] == 5


# ── Postgres path ──────────────────────────────────────────────────────────────
# No live server in the suite (conftest pins DATABASE_URL to sqlite:///:memory:),
# so these exercise the real routing, parsing, and fetcher code against stubs.
# The fetcher's SQL runs against a duck-typed cursor; only the network is faked.


class _FakeCursor:
    def __init__(self, regclass, rows):
        self._regclass = regclass
        self._rows = rows
        self._last_sql = ""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql):
        self._last_sql = sql

    def fetchone(self):
        return (self._regclass,)

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, regclass="student_profiles", rows=()):
        self.cursor_obj = _FakeCursor(regclass, list(rows))
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


def test_postgres_url_detection():
    assert tier17_report._is_postgres_url("postgres://u:p@host/db")
    assert tier17_report._is_postgres_url("postgresql://u:p@host/db")
    assert not tier17_report._is_postgres_url("profiles.db")
    assert not tier17_report._is_postgres_url("/data/profiles.db")


def test_profile_row_parser_accepts_jsonb_dicts():
    """Postgres JSONB rows arrive already parsed — same filtering as SQLite."""
    rows = [
        (
            "tenant_a:stud_1",
            {
                "samples": [
                    _sample("proctored", _composer_keystroke_data()),
                    _sample("verified", _composer_keystroke_data()),
                    _sample("proctored", keystroke_data=None),
                ]
            },
        ),
        ("tenant_a:stud_2", {"samples": [_sample("proctored", _transcriber_keystroke_data())]}),
    ]
    samples = tier17_report._samples_from_profile_rows(rows)
    assert [s["student_id"] for s in samples] == ["tenant_a:stud_1", "tenant_a:stud_2"]


def test_pg_fetcher_namespaces_students_by_tenant():
    """Same local student id at two tenants must count as two students."""
    doc = {"samples": [_sample("proctored", _composer_keystroke_data())]}
    conn = _FakeConn(rows=[("tenant_a", "stud_1", doc), ("tenant_b", "stud_1", doc)])
    samples = tier17_report._fetch_keystroke_samples_pg(conn)
    report = tier17_report.build_report(samples)
    assert report["totals"]["distinct_students"] == 2
    assert set(report["per_student"]) == {"tenant_a:stud_1", "tenant_b:stud_1"}


def test_pg_fetcher_missing_table_returns_empty():
    conn = _FakeConn(regclass=None, rows=[("t", "s", {"samples": []})])
    assert tier17_report._fetch_keystroke_samples_pg(conn) == []


def test_postgres_url_routes_to_pg_fetcher(monkeypatch, capsys):
    """main() with a postgresql:// --db must not touch the SQLite path (no
    file-exists check) and must close the connection."""
    conn = _FakeConn()
    canned = [
        {"student_id": f"t:stud_{i}", "keystroke_data": _composer_keystroke_data()}
        for i in range(3)
    ]
    monkeypatch.setattr(tier17_report, "_connect_pg", lambda url: conn)
    monkeypatch.setattr(tier17_report, "_fetch_keystroke_samples_pg", lambda c: canned)
    assert tier17_report.main(["--db", "postgresql://example.invalid/pilot"]) == 0
    out = capsys.readouterr().out
    assert "proctored samples with keystroke data: **3**" in out
    assert "Verdict: **NOT READY**" in out
    assert conn.closed


def test_postgres_driver_missing_is_a_clean_error(monkeypatch, capsys):
    def _raise(url):
        raise RuntimeError("psycopg2 is not installed — the Postgres path needs the pilot install")

    monkeypatch.setattr(tier17_report, "_connect_pg", _raise)
    assert tier17_report.main(["--db", "postgresql://example.invalid/pilot"]) == 1
    assert "psycopg2 is not installed" in capsys.readouterr().err
