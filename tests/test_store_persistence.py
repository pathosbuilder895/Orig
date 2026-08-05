"""
tests/test_store_persistence.py — write/load failures must surface, not vanish.

Regression coverage for A1 (WS-1): _persist() (and, historically, _load_all())
used to swallow every exception (`except Exception: pass`), so a failed SQLite
write left memory and disk silently diverged. Post WS-6 P6 there is no
in-memory cache to diverge FROM, but the guarantees themselves survive in
read-through form: a write failure raises to the caller (API 503 mapping), a
missing DB file starts empty, and an existing-but-corrupt DB file raises at
the first read rather than presenting as an empty store.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pytest

import original.store as store
from original.constants import FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Point the store at a fresh temp SQLite DB and reset cache state."""
    db_file = tmp_path / "test_profiles.db"
    monkeypatch.setenv("ORIGINAL_DB", str(db_file))
    monkeypatch.setattr(store, "_DB_PATH", db_file)
    store._GENRE_STATS_CACHE.clear()

    yield

    store._GENRE_STATS_CACHE.clear()


def _make_state(student_id: str = "student-a1") -> StudentState:
    state = StudentState(student_id=student_id)
    rng = np.random.default_rng(1234)
    state.add_sample(
        BaselineSample(
            text="Sample text for persistence testing.",
            vector=rng.random(FEATURE_DIM).astype(np.float64),
            provenance="instructor_verified",
            auth_weight=1.0,
            assignment="A1",
            genre=None,
            submitted_at="2025-01-15",
            word_count=321,
        )
    )
    return state


def test_persist_raises_and_logs_on_write_failure(monkeypatch, caplog):
    """An injected sqlite3.Error on write must surface to the caller, not vanish."""
    state = _make_state()

    class _BoomConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, *args, **kwargs):
            raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(store, "_get_conn", lambda: _BoomConn())

    with caplog.at_level("ERROR"):
        with pytest.raises(sqlite3.Error):
            store._persist(state)

    assert any("persist failed" in rec.message for rec in caplog.records)


def test_put_raises_on_persist_failure(monkeypatch):
    """put() must not swallow a downstream _persist failure."""
    state = _make_state()

    def _boom(_state):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(store, "_persist", _boom)

    with pytest.raises(sqlite3.Error):
        store.put(state)


def test_reads_start_empty_when_db_missing(tmp_path, monkeypatch):
    """A genuinely absent DB file (first boot) must start empty, not raise —
    _get_conn() provisions the schema on first touch."""
    missing_db = tmp_path / "does_not_exist_yet.db"
    monkeypatch.setattr(store, "_DB_PATH", missing_db)

    assert store.count() == 0  # must not raise
    assert store.get("nobody") is None
    assert store.list_ids() == []


def test_reads_raise_on_unreadable_existing_db(tmp_path, monkeypatch):
    """An existing but corrupt/non-DB file must fail loudly at the first read,
    not present as an empty store (the A1 guarantee, read-through form)."""
    junk_db = tmp_path / "junk.db"
    junk_db.write_text("this is not a sqlite database")
    monkeypatch.setattr(store, "_DB_PATH", junk_db)

    with pytest.raises(sqlite3.Error):
        store.count()
    with pytest.raises(sqlite3.Error):
        store.get("anyone")


def test_longitudinal_metadata_round_trips_and_legacy_defaults():
    state = _make_state("longitudinal-persist")
    store.put(state)

    restored = store.get("longitudinal-persist")
    assert restored is not None
    assert restored.samples[0].submitted_at == "2025-01-15"
    assert restored.samples[0].word_count == 321

    import json

    payload = json.loads(store._serialize(state))
    payload["samples"][0].pop("word_count")
    legacy = store._deserialize(json.dumps(payload))
    assert legacy.samples[0].word_count is None
