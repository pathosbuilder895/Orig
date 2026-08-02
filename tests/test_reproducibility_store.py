"""
Regression test: the validation harness's lock_environment() must point
ORIGINAL_DB at a store that actually persists across connections.

WS-6 P6 removed the in-memory _STORE profile cache, so every
store._get_conn() now opens a fresh sqlite3 connection. With the old
ORIGINAL_DB=":memory:" lock, each connection got its OWN empty in-memory
database — a baseline put() followed by a get() from another request
found nothing, and every TestClient-based validation harness
(validation/public_authors/run.py, validation/stability/measure_lift.py)
silently 404'd on every score call.
"""

from __future__ import annotations

import sqlite3

from validation.benchmark.reproducibility import lock_environment


def test_lock_environment_db_survives_across_connections(monkeypatch):
    report = lock_environment()

    assert report.original_db != ":memory:", (
        "':memory:' gives every sqlite3.connect() its own empty database — "
        "the store has no cross-connection cache since WS-6 P6."
    )

    # Simulate what store._get_conn() does: two independent connections.
    conn_a = sqlite3.connect(report.original_db)
    conn_a.execute("CREATE TABLE IF NOT EXISTS t (k TEXT PRIMARY KEY, v TEXT)")
    conn_a.execute("INSERT OR REPLACE INTO t VALUES ('student', 'profile')")
    conn_a.commit()
    conn_a.close()

    conn_b = sqlite3.connect(report.original_db)
    row = conn_b.execute("SELECT v FROM t WHERE k = 'student'").fetchone()
    conn_b.close()
    assert row == ("profile",), "write from one connection must be visible to the next"


def test_lock_environment_idempotent_db_path():
    # Repeated calls in one process must keep the SAME store — flipping the
    # path mid-run would drop every profile built so far.
    first = lock_environment()
    second = lock_environment()
    assert first.original_db == second.original_db
