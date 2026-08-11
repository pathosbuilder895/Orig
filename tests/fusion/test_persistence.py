"""fused_scores: round-trip, idempotency, FERPA purge, inventory."""

from __future__ import annotations

import uuid

import numpy as np

import original.store as store
from original.constants import FEATURE_DIM


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


def test_malformed_channels_json_degrades_per_row_not_entire_student():
    """When one row has valid JSON but non-numeric channel values, that row
    alone should degrade to channels={}, while all other rows for the student
    are returned intact. Tests the fix for the bug where float coercion on a
    single malformed row would cause the entire get_fused_scores() call to
    return [] for the whole student.
    """
    student_id = _sid()

    # Write two healthy rows
    healthy_submission_id = uuid.uuid4().hex
    corrupted_submission_id = uuid.uuid4().hex

    store.put_fused_score(
        healthy_submission_id,
        student_id,
        fused_log_odds=1.0,
        probability=0.8,
        band="divergent",
        channels={"peer_centered_z": 0.5, "compression": -0.25},
        model_version="v1",
    )
    store.put_fused_score(
        corrupted_submission_id,
        student_id,
        fused_log_odds=0.5,
        probability=0.6,
        band="consistent",
        channels={"compression": 0.1},
        model_version="v1",
    )

    # Verify both rows exist
    rows = store.get_fused_scores(student_id)
    assert len(rows) == 2

    # Corrupt one row's channels_json in the database to have non-numeric value
    with store._get_conn() as conn:
        conn.execute(
            "UPDATE fused_scores SET channels_json = ? WHERE submission_id = ?",
            ('{"compression": "n/a"}', corrupted_submission_id),
        )
        conn.commit()

    # After corruption, get_fused_scores should still return both rows
    rows = store.get_fused_scores(student_id)
    assert len(rows) == 2, f"Expected 2 rows, got {len(rows)}"

    # Find each row by submission_id
    healthy_row = next(r for r in rows if r["submission_id"] == healthy_submission_id)
    corrupted_row = next(r for r in rows if r["submission_id"] == corrupted_submission_id)

    # The corrupted row should have channels={}
    assert corrupted_row["channels"] == {}

    # The healthy row should still have its channels intact as floats
    assert healthy_row["channels"] == {"peer_centered_z": 0.5, "compression": -0.25}
    assert isinstance(healthy_row["channels"]["peer_centered_z"], float)
    assert isinstance(healthy_row["channels"]["compression"], float)


def test_delete_student_clears_the_fusion_peer_cache():
    """FERPA (C2): erasure must clear original.fusion.peers._cache too.

    That module-level cache holds each student's full concatenated raw
    baseline text (plus derived matrices) for the process lifetime — the
    fused-score channels need it, but nothing evicted it on erasure before
    this fix. store.delete_student already clears _GENRE_STATS_CACHE for
    exactly this reason; this proves the same now happens for the fusion
    peer cache.

    Discrimination: this test fails if store.delete_student's call to
    peers.clear_student is ever removed, because the cache would still
    contain the student's fingerprint (and their raw text with it) after
    "erasure" returns True.
    """
    from original.fusion import peers as fusion_peers
    from original.quantum.state import BaselineSample, StudentState

    fusion_peers.reset_cache_for_tests()
    student_id = _sid()
    long_text = (
        "The careful reader will note the argument's structure and weigh "
        "each premise on its own terms before accepting the conclusion. "
    ) * 40  # comfortably above peers.MIN_WORDS

    state = StudentState(student_id=student_id)
    rng = np.random.default_rng(0)
    for index in range(3):
        state.add_sample(
            BaselineSample(
                text=long_text,
                vector=rng.uniform(0.3, 0.7, FEATURE_DIM),
                provenance="proctored",
                auth_weight=1.0,
                assignment=f"{student_id}-{index}",
            )
        )
    store.put(state)

    profile = fusion_peers.build_profile(state)
    assert profile is not None
    # The cache genuinely holds this student's raw baseline text before
    # erasure — the premise the rest of the test depends on.
    assert student_id in fusion_peers._cache_students
    cached_key = next(iter(fusion_peers._cache_students[student_id]))
    assert fusion_peers._cache[cached_key].text  # raw text is actually resident

    assert store.delete_student(student_id) is True

    assert student_id not in fusion_peers._cache_students
    assert cached_key not in fusion_peers._cache
    assert cached_key not in fusion_peers._key_student
