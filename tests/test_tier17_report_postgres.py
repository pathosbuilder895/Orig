"""
tests/test_tier17_report_postgres.py — Postgres mode for the Tier 17
shadow-readiness report script (Task A1, Bluebook sprint 2026-08-11).

Mirrors tests/test_tier17_report.py's coverage, but through the Postgres
path: `scripts.tier17_report`'s pure `_samples_from_states()` helper (unmarked
— runs everywhere), the `--backend postgres` CLI guardrails (unmarked —
hermetic, no live database touched), and a `TestPostgresBackend` integration
class (`@pytest.mark.postgres`, self-skips when no reachable Postgres is
configured via DATABASE_URL — see `_postgres_available()` below, copied from
tests/test_repository_contract.py per the house convention of one copy per
file rather than a shared conftest fixture).
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState

_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "tier17_report_pg", _ROOT / "scripts" / "tier17_report.py"
)
tier17_report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tier17_report)


# ── Synthetic keystroke-data fixtures (copied from tests/test_tier17_report.py) ─
# "composer": hesitant/bursty typing, real revisions, long thinking pauses.
# "transcriber": metronomic typing, zero deletions/revisions, no long pauses —
# the profile you'd expect from someone retyping a finished text.


def _composer_keystroke_data(word_count: int = 300) -> dict:
    keystrokes = []
    elapsed = 0.0
    for i in range(120):
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
        elapsed += 120.0
        keystrokes.append({"key": "a", "elapsed": elapsed})
    return {
        "keystrokes": keystrokes,
        "pauses": [],
        "revisions": [],
        "deletionRate": 0.0,
        "wordCount": word_count,
    }


def _make_state(student_id: str, samples: list[tuple[str, dict | None]]) -> StudentState:
    """samples: list of (provenance, keystroke_data)."""
    state = StudentState(student_id=student_id)
    for provenance, keystroke_data in samples:
        state.add_sample(
            BaselineSample(
                text="irrelevant",
                vector=np.full(FEATURE_DIM, 0.5, dtype=np.float64),
                provenance=provenance,
                auth_weight=1.0,
                keystroke_data=keystroke_data,
            )
        )
    return state


# ── Phase 1: pure _samples_from_states (unmarked) ───────────────────────────


def test_samples_from_states_filters_provenance_and_missing_blobs():
    state = _make_state(
        "stud_mixed",
        [
            ("proctored", _composer_keystroke_data()),
            ("proctored", None),
            ("verified", _composer_keystroke_data()),
            ("unverified", _composer_keystroke_data()),
        ],
    )
    samples = tier17_report._samples_from_states([state])
    assert len(samples) == 1
    assert set(samples[0].keys()) == {"student_id", "keystroke_data"}


def test_samples_from_states_preserves_scoped_student_id():
    state = _make_state("sem:alice", [("proctored", _composer_keystroke_data())])
    samples = tier17_report._samples_from_states([state])
    assert samples[0]["student_id"] == "sem:alice"


# ── Phase 2: --backend postgres CLI guardrails (unmarked, hermetic) ─────────


def test_backend_postgres_rejects_non_postgres_database_url(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    assert tier17_report.main(["--backend", "postgres"]) == 2
    err = capsys.readouterr().err
    assert "postgresql://" in err


def test_backend_postgres_unreachable_database_exits_1(monkeypatch, capsys):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://nobody:nothing@localhost:5432/does_not_exist"
    )
    from original.db import postgres_session

    class _FailingEngine:
        def connect(self):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(postgres_session, "get_engine", lambda: _FailingEngine())
    assert tier17_report.main(["--backend", "postgres"]) == 1
    err = capsys.readouterr().err
    assert "cannot reach Postgres" in err


# ── Phase 3: integration mirror against a live Postgres ─────────────────────


def _postgres_available() -> bool:
    """True iff DATABASE_URL points at Postgres and it's actually reachable.

    Copied from tests/test_repository_contract.py:51-68 — the house
    convention is one copy per file, checked at fixture-setup time (not
    import time) so monkeypatching DATABASE_URL mid-session still works.
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url.startswith("postgresql"):
        return False
    from original.db import postgres_session

    try:
        postgres_session.reset_engine()
        with postgres_session.get_engine().connect():
            return True
    except Exception:
        return False


@pytest.fixture
def pg_live_schema():
    if not _postgres_available():
        pytest.skip(
            "no reachable Postgres — set DATABASE_URL to a postgresql:// "
            "instance to run these"
        )
    from original.db import postgres_session
    from original.db.models.live import LiveBase

    engine = postgres_session.get_engine()  # already reset by _postgres_available()
    LiveBase.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        for table in reversed(LiveBase.metadata.sorted_tables):
            conn.execute(table.delete())
    yield
    with engine.begin() as conn:
        for table in reversed(LiveBase.metadata.sorted_tables):
            conn.execute(table.delete())


def _seed_student(student_id: str, samples: list[tuple[str, dict | None]]) -> None:
    from original.postgres_repository import PostgresRepository

    PostgresRepository().put(_make_state(student_id, samples))


@pytest.mark.postgres
class TestPostgresBackend:
    def test_empty_database_is_not_ready(self, pg_live_schema, capsys):
        assert tier17_report.main(["--backend", "postgres"]) == 0
        out = capsys.readouterr().out
        assert "Verdict: **NOT READY**" in out
        assert "proctored samples with keystroke data: **0**" in out

    def test_non_proctored_and_blobless_samples_are_excluded(self, pg_live_schema):
        _seed_student(
            "stud_mixed",
            [
                ("unverified", _composer_keystroke_data()),
                ("verified", _composer_keystroke_data()),
                ("proctored", _composer_keystroke_data()),
                ("proctored", None),
            ],
        )
        from original.postgres_repository import PostgresRepository

        samples = tier17_report._samples_from_states(PostgresRepository().all_states())
        assert len(samples) == 1

    def test_ready_verdict_on_sufficient_nondegenerate_corpus(self, pg_live_schema, capsys):
        for i in range(5):
            samples = [
                (
                    "proctored",
                    _composer_keystroke_data() if (i + j) % 2 == 0 else _transcriber_keystroke_data(),
                )
                for j in range(5)
            ]
            _seed_student(f"stud_{i}", samples)
        assert tier17_report.main(["--backend", "postgres"]) == 0
        out = capsys.readouterr().out
        assert "proctored samples with keystroke data: **25**" in out
        assert "distinct students: **5**" in out
        assert "Verdict: **READY**" in out

    def test_insufficient_students_is_not_ready(self, pg_live_schema, capsys):
        for i in range(4):
            samples = [
                ("proctored", _composer_keystroke_data() if j % 2 == 0 else _transcriber_keystroke_data())
                for j in range(10)
            ]
            _seed_student(f"stud_{i}", samples)
        assert tier17_report.main(["--backend", "postgres"]) == 0
        out = capsys.readouterr().out
        assert "proctored samples with keystroke data: **40**" in out
        assert "distinct students: **4**" in out
        assert "Verdict: **NOT READY**" in out

    def test_degenerate_distributions_block_ready_despite_volume(self, pg_live_schema):
        for i in range(5):
            samples = [("proctored", _transcriber_keystroke_data()) for _ in range(5)]
            _seed_student(f"stud_{i}", samples)
        from original.postgres_repository import PostgresRepository

        report = tier17_report.build_report(
            tier17_report._samples_from_states(PostgresRepository().all_states())
        )
        assert report["totals"]["proctored_samples_with_keystroke_data"] == 25
        assert report["totals"]["distinct_students"] == 5
        assert report["gate"]["nondegenerate_features"] == 0
        assert report["verdict"] == "NOT READY"

    def test_json_output(self, pg_live_schema, tmp_path):
        for i in range(5):
            samples = [
                (
                    "proctored",
                    _composer_keystroke_data() if (i + j) % 2 == 0 else _transcriber_keystroke_data(),
                )
                for j in range(5)
            ]
            _seed_student(f"stud_{i}", samples)
        out_json = tmp_path / "tier17.json"
        assert (
            tier17_report.main(["--backend", "postgres", "--out-json", str(out_json)])
            == 0
        )
        data = json.loads(out_json.read_text())
        assert data["verdict"] == "READY"
        assert data["totals"]["distinct_students"] == 5

    def test_scoped_tenant_ids_round_trip_into_report(self, pg_live_schema, capsys):
        _seed_student("sem:stud_x", [("proctored", _composer_keystroke_data())])
        assert tier17_report.main(["--backend", "postgres"]) == 0
        out = capsys.readouterr().out
        assert "sem:stud_x" in out
