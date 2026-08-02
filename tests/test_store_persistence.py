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
from pathlib import Path

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


@pytest.fixture
def memory_store(monkeypatch):
    """Point the store at ORIGINAL_DB=':memory:' with a guaranteed-fresh
    shared-cache in-memory database, isolated from any other test's data.

    ``_isolated_store`` (autouse, above) already points ``_DB_PATH`` at a
    temp *file* for every test in this module; this fixture overrides that
    to the literal ``":memory:"`` sentinel for the tests below. Calls
    ``store.reset_memory_conn()`` before AND after — the same reset hook a
    real caller (e.g. a harness that runs more than one logical "run" in one
    process) would use — so this test neither inherits another test's
    in-memory data nor leaks its own into a later one.
    """
    monkeypatch.setattr(store, "_DB_PATH", Path(":memory:"))
    store.reset_memory_conn()
    yield store
    store.reset_memory_conn()


def test_memory_db_survives_a_write_then_read_round_trip(memory_store):
    """ORIGINAL_DB=':memory:' must behave like a shared database within one
    process, not a fresh anonymous database per connection.

    Regression for the bug where every ``_get_conn()`` call did
    ``sqlite3.connect(":memory:")`` — which creates a brand-new, unshared,
    anonymous in-memory database each time, not a shared one. Since
    ``with _get_conn() as conn: ...`` only manages the transaction (commit /
    rollback), never closes the connection, each connection became eligible
    for GC right after use, taking its anonymous database with it. A
    baseline written by one call was therefore invisible to a later read —
    exactly what ``validation/benchmark/reproducibility.py``'s
    ``lock_environment()`` (``ORIGINAL_DB=":memory:"``, used by every
    validation script) hits on any baseline-then-score round trip in one
    process.
    """
    state = _make_state("student-memtest")
    memory_store.put(state)

    reloaded = memory_store.get("student-memtest")

    assert reloaded is not None, (
        "a baseline written via put() must be visible to a later get() "
        "within the same process when ORIGINAL_DB=':memory:'"
    )
    assert reloaded.student_id == "student-memtest"
    assert len(reloaded.samples) == 1


def test_memory_db_connections_are_distinct_objects_that_share_data(memory_store):
    """Every _get_conn() call under ORIGINAL_DB=':memory:' returns a fresh
    Connection object -- the same shape as the file-backed path, via SQLite's
    named shared-cache URI rather than a single reused connection -- but
    every such connection attaches to the SAME underlying database, so a
    write from one is immediately visible to a read from another."""
    conn1 = store._get_conn()
    conn2 = store._get_conn()
    assert conn1 is not conn2, (
        "each call must return its own Connection object, matching the "
        "file-backed path's fresh-connection-per-call shape"
    )
    with conn1:
        conn1.execute(
            "INSERT OR REPLACE INTO student_profiles (student_id, data) VALUES (?, ?)",
            ("probe", "{}"),
        )
    rows = conn2.execute(
        "SELECT student_id FROM student_profiles WHERE student_id = ?", ("probe",)
    ).fetchall()
    assert rows == [("probe",)]
    conn1.close()
    conn2.close()


def test_reset_memory_conn_gives_a_genuinely_empty_database(memory_store):
    """reset_memory_conn() must make the NEXT _get_conn() call see a fresh,
    empty database, not the previous run's leftover data -- the guarantee
    validation/benchmark/reproducibility.py's docstring promises ("no
    cross-run store contamination") for any caller that constructs more than
    one logical "run" (e.g. more than one TestClient / more than one
    baseline-then-score pass) within a single process.
    """
    state = _make_state("student-before-reset")
    memory_store.put(state)
    assert memory_store.get("student-before-reset") is not None  # sanity check

    store.reset_memory_conn()

    assert memory_store.get("student-before-reset") is None


def test_reset_memory_conn_is_safe_from_a_different_thread(memory_store):
    """A harness that runs more than one logical "run" in one process (e.g.
    validation/audits/pooled_calibration_payoff.py, comparing pooled vs. self
    calibration by constructing two separate TestClient/app instances and
    calling reset_memory_conn() between them) does not control which thread
    lazily creates the keepalive connection -- FastAPI's TestClient can serve
    a request on a worker thread distinct from the caller's own. Reproduces
    the real failure directly: touch _get_conn() (lazily creating
    _MEMORY_KEEPALIVE_CONN) on a background thread, then call
    reset_memory_conn() from THIS thread. Before the fix this raised
    sqlite3.ProgrammingError: SQLite objects created in a thread can only be
    used in that same thread.
    """
    import threading

    def _touch_from_worker_thread():
        store._get_conn().close()

    worker = threading.Thread(target=_touch_from_worker_thread)
    worker.start()
    worker.join()

    store.reset_memory_conn()  # must not raise


def test_memory_db_does_not_affect_file_backed_path(tmp_path, monkeypatch):
    """The fix must be scoped to ':memory:' only -- the file-backed
    (production default) path keeps its existing fresh-connection-per-call
    behaviour, and reset_memory_conn() must be harmless to call there (it
    only touches ':memory:'-mode state that this path never uses)."""
    db_file = tmp_path / "profiles.db"
    monkeypatch.setattr(store, "_DB_PATH", db_file)

    conn1 = store._get_conn()
    conn2 = store._get_conn()
    assert conn1 is not conn2
    conn1.close()
    conn2.close()

    store.reset_memory_conn()  # must not raise, must not touch the file DB
