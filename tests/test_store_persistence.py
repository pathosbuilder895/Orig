"""
tests/test_store_persistence.py — write/load failures must surface, not vanish.

Regression coverage for A1 (WS-1): _persist() and _load_all() used to swallow
every exception (`except Exception: pass`), so a failed SQLite write left the
in-memory cache and disk silently diverged. Both now re-raise sqlite3.Error
after logging, so callers (and the API's 503 mapping) see the failure.
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
    """Point the store at a fresh temp SQLite DB and reset in-memory state."""
    db_file = tmp_path / "test_profiles.db"
    monkeypatch.setenv("ORIGINAL_DB", str(db_file))
    monkeypatch.setattr(store, "_DB_PATH", db_file)
    store._STORE.clear()
    store._GENRE_STATS_CACHE.clear()
    store._loaded = False

    yield

    store._STORE.clear()
    store._GENRE_STATS_CACHE.clear()
    store._loaded = False


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


def test_load_all_starts_empty_when_db_missing(tmp_path, monkeypatch):
    """A genuinely absent DB file (first boot) must start empty, not raise."""
    missing_db = tmp_path / "does_not_exist_yet.db"
    monkeypatch.setattr(store, "_DB_PATH", missing_db)
    store._loaded = False

    store._load_all()  # must not raise

    assert store.count() == 0


def test_load_all_raises_on_unreadable_existing_db(tmp_path, monkeypatch):
    """An existing but corrupt/non-DB file must fail startup, not present as empty."""
    junk_db = tmp_path / "junk.db"
    junk_db.write_text("this is not a sqlite database")
    monkeypatch.setattr(store, "_DB_PATH", junk_db)
    store._loaded = False

    with pytest.raises(sqlite3.Error):
        store._load_all()
