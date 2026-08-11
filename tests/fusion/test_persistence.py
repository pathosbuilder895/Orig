"""fused_scores: round-trip, idempotency, FERPA purge, inventory."""

from __future__ import annotations

import uuid

import original.store as store


def _sid() -> str:
    return f"persist-test:{uuid.uuid4().hex[:8]}"


def test_put_and_get_round_trip():
    student_id = _sid()
    submission_id = uuid.uuid4().hex
    store.put_fused_score(
        submission_id,
        student_id,
        fused_log_odds=1.25,
        probability=0.777,
        band="divergent",
        channels={"peer_centered_z": -0.1, "compression": 0.4},
        model_version="v1",
    )
    rows = store.get_fused_scores(student_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["submission_id"] == submission_id
    assert row["fused_log_odds"] == 1.25
    assert row["probability"] == 0.777
    assert row["band"] == "divergent"
    assert row["channels"] == {"peer_centered_z": -0.1, "compression": 0.4}
    assert row["model_version"] == "v1"


def test_rewriting_the_same_submission_keeps_one_row():
    student_id = _sid()
    submission_id = uuid.uuid4().hex
    for probability in (0.10, 0.90):
        store.put_fused_score(
            submission_id,
            student_id,
            fused_log_odds=0.0,
            probability=probability,
            band="consistent",
            channels={},
        )
    rows = store.get_fused_scores(student_id)
    assert len(rows) == 1
    assert rows[0]["probability"] == 0.90


def test_channels_survive_as_structured_data_not_a_string():
    """The refit path depends on reading per-channel values back as numbers."""
    student_id = _sid()
    store.put_fused_score(
        uuid.uuid4().hex,
        student_id,
        fused_log_odds=0.0,
        probability=0.5,
        band="consistent",
        channels={"compression": -0.25},
    )
    value = store.get_fused_scores(student_id)[0]["channels"]["compression"]
    assert isinstance(value, float)
    assert value == -0.25


def test_persistence_failure_does_not_raise(monkeypatch):
    monkeypatch.setattr(
        store, "_get_conn", lambda: (_ for _ in ()).throw(RuntimeError("db down"))
    )
    store.put_fused_score(
        uuid.uuid4().hex, _sid(), fused_log_odds=0.0, probability=0.5, band="consistent",
        channels={},
    )  # must not raise


def test_delete_student_purges_fused_rows():
    student_id = _sid()
    store.get_or_create(student_id)
    store.put_fused_score(
        uuid.uuid4().hex, student_id, fused_log_odds=0.0, probability=0.5,
        band="consistent", channels={},
    )
    assert store.get_fused_scores(student_id)
    store.delete_student(student_id)
    assert store.get_fused_scores(student_id) == []


def test_data_inventory_reports_the_count():
    student_id = _sid()
    store.get_or_create(student_id)
    store.put_fused_score(
        uuid.uuid4().hex, student_id, fused_log_odds=0.0, probability=0.5,
        band="consistent", channels={},
    )
    inventory = store.student_data_inventory(student_id)
    assert inventory["data_categories"]["fused_scores"]["count"] == 1


def test_repository_exposes_the_write_and_marks_it_a_write_method():
    from original.repository import _WRITE_METHODS, SqliteRepository

    assert "put_fused_score" in _WRITE_METHODS
    repo = SqliteRepository()
    student_id = _sid()
    repo.put_fused_score(
        uuid.uuid4().hex, student_id, fused_log_odds=0.5, probability=0.6,
        band="inconclusive", channels={"compression": 0.1}, model_version="v1",
    )
    assert repo.get_fused_scores(student_id)[0]["band"] == "inconclusive"
