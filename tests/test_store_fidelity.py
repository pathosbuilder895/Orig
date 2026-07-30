"""
tests/test_store_fidelity.py — store.py internals not expressible against the
Repository contract.

The fidelity-score, genre-stats, and delete_student *behavior* assertions
moved to tests/test_repository_contract.py (WS-6 P1 deliverable #3) — they
call only Repository-protocol methods, so they run against any backend.
What's left here reaches into store.py internals a Postgres backend won't
have in the same shape (``store._GENRE_STATS_CACHE``, raw SQL via
``store._get_conn()``), so it stays a SQLite-specific regression test.
"""

from __future__ import annotations

from datetime import UTC

import numpy as np
import pytest

# These imports must appear ABOVE the fixture definition so that `store`
# is already in the module namespace when _isolated_store is called.
# (Python resolves names in fixture bodies at call time, not at definition
# time — but keeping the import before the fixture makes the dependency
# explicit and avoids surprising future maintainers.)
import original.store as store
from original.constants import FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState


# Point the store at an isolated temp DB for each test
@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """
    Reset store module state and point it at a fresh temp SQLite file.

    Root cause of the tricky isolation problem this fixture works around:
    tests/context/test_drift.py deletes 'original.store' from sys.modules
    and re-imports it (to test counter persistence with a fresh DB path).
    After that manipulation, `sys.modules["original.store"]` points to a
    *new module object* (call it M2).  When this fixture does
    `import original.store as store_mod` it gets M2, but the module-level
    `store` binding in this file still refers to the *old* module object
    (M1, bound at collection time).  If we only patch M2._DB_PATH we leave
    M1._DB_PATH pointing at some expired temp path, and M1._get_conn()
    quietly creates (or opens) a DB we don't control.

    Fix: patch _DB_PATH on BOTH module objects.  We identify them by their
    Python identity so we never patch the same object twice (which would
    waste a monkeypatch undo slot but cause no other harm).
    """
    import original.store as store_mod  # whatever is in sys.modules right now

    db_file = tmp_path / "test_profiles.db"
    monkeypatch.setenv("ORIGINAL_DB", str(db_file))

    # Collect the distinct store module objects we need to patch.
    # `store` below is the module-level binding resolved at call time from
    # this file's global namespace — it may differ from store_mod when a
    # previous test has reloaded the module into sys.modules.
    _mods_seen: set = set()

    def _patch_mod(mod) -> None:
        if id(mod) in _mods_seen:
            return
        _mods_seen.add(id(mod))
        monkeypatch.setattr(mod, "_DB_PATH", db_file)
        mod._GENRE_STATS_CACHE.clear()
        mod._GENRE_STATS_CACHE.clear()

    _patch_mod(store_mod)
    _patch_mod(store)  # module-level `store` import at the bottom of this file

    yield

    # Teardown: wipe in-memory state on every store object we touched.
    # monkeypatch automatically restores _DB_PATH on teardown.
    for _obj in (store_mod, store):
        _obj._GENRE_STATS_CACHE.clear()
        _obj._GENRE_STATS_CACHE.clear()


def _make_state(student_id: str, n_samples: int = 1, genre: str | None = None) -> StudentState:
    """Create a StudentState with n_samples of random feature vectors."""
    state = StudentState(student_id=student_id)
    rng = np.random.default_rng(abs(hash(student_id)) % (2**31))
    for i in range(n_samples):
        vec = rng.random(FEATURE_DIM).astype(np.float64)
        sample = BaselineSample(
            text="Sample text for testing purposes.",
            vector=vec,
            provenance="instructor_verified",
            auth_weight=1.0,
            assignment=f"Assignment {i+1}",
            genre=genre,
        )
        state.add_sample(sample)  # mutates in-place, returns None
    return state


class TestGenreStatsCacheInternals:
    def test_genre_cache_busted_on_delete(self):
        for i in range(6):
            state = _make_state(f"student-del-cache-{i}", n_samples=1, genre="ethics_paper")
            store.put(state)
        # Prime cache — key is (tenant, genre); these ids are legacy-flat.
        store.get_genre_stats("ethics_paper", None)
        assert (None, "ethics_paper") in store._GENRE_STATS_CACHE

        # Delete a student → cache should be cleared
        store.delete_student("student-del-cache-0")
        assert len(store._GENRE_STATS_CACHE) == 0


class TestDeleteStudentRawSql:
    def test_corrections_with_null_student_id_purged(self):
        """
        Corrections whose student_id column is NULL (written before the
        manifest existed) must still be purged by delete_student().

        We simulate this by inserting a correction row with student_id=NULL
        directly via SQL, then confirming delete_student() removes it via
        the submission_id→manifest path.
        """
        from datetime import datetime

        state = _make_state("student-del-null-sid")
        store.put(state)

        # Write a fake manifest so delete_student() can look up submission_ids
        sub_id = "sub-null-sid-001"
        with store._get_conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO submission_manifests
                   (submission_id, student_id, created_at, manifest_json)
                   VALUES (?, ?, ?, ?)""",
                (sub_id, "student-del-null-sid", datetime.now(UTC).isoformat(), "{}"),
            )
            # Insert an orphaned correction with student_id=NULL
            conn.execute(
                """INSERT INTO corrections
                   (submission_id, student_id, is_correct, created_at)
                   VALUES (?, NULL, 1, ?)""",
                (sub_id, datetime.now(UTC).isoformat()),
            )
            conn.commit()

        # Confirm the orphaned row exists before deletion
        with store._get_conn() as conn:
            rows = conn.execute(
                "SELECT COUNT(*) FROM corrections WHERE submission_id = ?", (sub_id,)
            ).fetchone()
        assert rows[0] == 1, "Orphaned correction row should exist before delete"

        store.delete_student("student-del-null-sid")

        # Orphaned correction must be gone after FERPA erasure
        with store._get_conn() as conn:
            rows = conn.execute(
                "SELECT COUNT(*) FROM corrections WHERE submission_id = ?", (sub_id,)
            ).fetchone()
        assert rows[0] == 0, "Orphaned correction with NULL student_id must be purged"
