"""
tests/test_store_fidelity.py — Unit tests for store.py fidelity and deletion functions.

Tests cover:
- put_fidelity_score / get_authentic_fidelities
- update_fidelity_authenticity
- get_genre_stats (caching + thread-safety no-op)
- delete_student (in-memory purge + FERPA completeness)
"""

from __future__ import annotations

import os
import tempfile

import numpy as np
import pytest

# These imports must appear ABOVE the fixture definition so that `store`
# is already in the module namespace when _isolated_store is called.
# (Python resolves names in fixture bodies at call time, not at definition
# time — but keeping the import before the fixture makes the dependency
# explicit and avoids surprising future maintainers.)
import original.store as store
from original.quantum.state import BaselineSample, StudentState
from original.constants import FEATURE_DIM


# Point the store at an isolated temp DB for each test
@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """
    Reset store module state and point it at a fresh temp SQLite file.

    Root cause of the tricky isolation problem this fixture works around:
    tests/context/test_drift 2.py deletes 'original.store' from sys.modules
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
    import original.store as store_mod   # whatever is in sys.modules right now

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
        mod._STORE.clear()
        mod._GENRE_STATS_CACHE.clear()
        mod._loaded = False

    _patch_mod(store_mod)
    _patch_mod(store)   # module-level `store` import at the bottom of this file

    yield

    # Teardown: wipe in-memory state on every store object we touched.
    # monkeypatch automatically restores _DB_PATH on teardown.
    for _obj in (store_mod, store):
        _obj._STORE.clear()
        _obj._GENRE_STATS_CACHE.clear()
        _obj._loaded = False


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
        state.add_sample(sample)   # mutates in-place, returns None
    return state


# ── put_fidelity_score / get_authentic_fidelities ────────────────────────────

class TestFidelityScoreRoundtrip:
    def test_empty_returns_empty_list(self):
        result = store.get_authentic_fidelities("nobody")
        assert result == []

    def test_stored_authentic_score_returned(self):
        store.put_fidelity_score("sub-001", "student-A", 0.85, is_authentic=True)
        result = store.get_authentic_fidelities("student-A")
        assert len(result) == 1
        assert abs(result[0] - 0.85) < 1e-6

    def test_non_authentic_score_not_returned(self):
        store.put_fidelity_score("sub-002", "student-A", 0.30, is_authentic=False)
        result = store.get_authentic_fidelities("student-A")
        assert result == []

    def test_mixed_authenticity_only_authentic_returned(self):
        store.put_fidelity_score("sub-A1", "student-B", 0.90, is_authentic=True)
        store.put_fidelity_score("sub-A2", "student-B", 0.25, is_authentic=False)
        store.put_fidelity_score("sub-A3", "student-B", 0.80, is_authentic=True)
        result = store.get_authentic_fidelities("student-B")
        assert len(result) == 2
        assert all(f > 0.5 for f in result)

    def test_scores_isolated_by_student(self):
        store.put_fidelity_score("sub-X1", "student-X", 0.70, is_authentic=True)
        store.put_fidelity_score("sub-Y1", "student-Y", 0.60, is_authentic=True)
        assert len(store.get_authentic_fidelities("student-X")) == 1
        assert len(store.get_authentic_fidelities("student-Y")) == 1

    def test_insert_or_replace_deduplicates_by_submission_id(self):
        store.put_fidelity_score("sub-DUP", "student-C", 0.50, is_authentic=True)
        store.put_fidelity_score("sub-DUP", "student-C", 0.75, is_authentic=True)
        result = store.get_authentic_fidelities("student-C")
        # INSERT OR REPLACE → only one row; value is the most recent
        assert len(result) == 1
        assert abs(result[0] - 0.75) < 1e-6

    def test_limit_respected(self):
        for i in range(10):
            store.put_fidelity_score(f"sub-L{i}", "student-D", 0.5 + i * 0.02, is_authentic=True)
        result = store.get_authentic_fidelities("student-D", limit=5)
        assert len(result) == 5


# ── update_fidelity_authenticity ─────────────────────────────────────────────

class TestUpdateFidelityAuthenticity:
    def test_flip_authentic_to_non_authentic(self):
        store.put_fidelity_score("sub-F1", "student-E", 0.80, is_authentic=True)
        assert len(store.get_authentic_fidelities("student-E")) == 1

        store.update_fidelity_authenticity("sub-F1", False)
        assert store.get_authentic_fidelities("student-E") == []

    def test_flip_non_authentic_to_authentic(self):
        store.put_fidelity_score("sub-F2", "student-F", 0.40, is_authentic=False)
        assert store.get_authentic_fidelities("student-F") == []

        store.update_fidelity_authenticity("sub-F2", True)
        result = store.get_authentic_fidelities("student-F")
        assert len(result) == 1
        assert abs(result[0] - 0.40) < 1e-6

    def test_no_op_when_submission_not_found(self):
        """Silently ignores missing submission_id — should not raise."""
        store.update_fidelity_authenticity("sub-GHOST", False)  # no row in DB
        # No exception raised

    def test_confirm_authentic_stays_authentic(self):
        store.put_fidelity_score("sub-F3", "student-G", 0.88, is_authentic=True)
        store.update_fidelity_authenticity("sub-F3", True)
        result = store.get_authentic_fidelities("student-G")
        assert len(result) == 1


# ── get_genre_stats ───────────────────────────────────────────────────────────

class TestGetGenreStats:
    def test_returns_none_with_no_students(self):
        result = store.get_genre_stats("argumentative_essay")
        assert result is None

    def test_returns_none_with_fewer_than_5_samples(self):
        for i in range(4):
            state = _make_state(f"student-G{i}", n_samples=1, genre="argumentative_essay")
            store.put(state)
        result = store.get_genre_stats("argumentative_essay")
        assert result is None

    def test_returns_stats_with_enough_samples(self):
        for i in range(6):
            state = _make_state(f"student-H{i}", n_samples=1, genre="lab_report")
            store.put(state)
        result = store.get_genre_stats("lab_report")
        assert result is not None
        assert "mean" in result
        assert "std" in result
        assert "n_samples" in result
        assert result["n_samples"] == 6
        assert result["mean"].shape == (FEATURE_DIM,)
        assert result["std"].shape == (FEATURE_DIM,)

    def test_std_floored_at_005(self):
        """std should never be below 0.005 (matches StudentState floor)."""
        for i in range(6):
            state = _make_state(f"student-I{i}", n_samples=1, genre="theology_paper")
            store.put(state)
        result = store.get_genre_stats("theology_paper")
        assert result is not None
        assert float(np.min(result["std"])) >= 0.005

    def test_cache_hit_on_second_call(self):
        for i in range(6):
            state = _make_state(f"student-J{i}", n_samples=1, genre="sermon")
            store.put(state)
        # Prime the cache
        r1 = store.get_genre_stats("sermon")
        # Second call should be a cache hit (same object reference for dict)
        r2 = store.get_genre_stats("sermon")
        assert r1 is r2  # same dict object from cache

    def test_cache_busted_after_put(self):
        for i in range(6):
            state = _make_state(f"student-K{i}", n_samples=1, genre="exegesis")
            store.put(state)
        r1 = store.get_genre_stats("exegesis")
        assert r1 is not None

        # Add another student → put() clears cache
        new_state = _make_state("student-K6", n_samples=1, genre="exegesis")
        store.put(new_state)
        assert "exegesis" not in store._GENRE_STATS_CACHE

        r2 = store.get_genre_stats("exegesis")
        assert r2 is not None
        assert r2["n_samples"] == 7

    def test_none_genre_samples_not_counted_for_named_genre(self):
        """Samples without a genre label don't appear in a named genre bucket."""
        for i in range(6):
            state = _make_state(f"student-L{i}", n_samples=1, genre=None)
            store.put(state)
        # Querying a specific genre → should find nothing (all samples have genre=None)
        result = store.get_genre_stats("argumentative_essay")
        assert result is None

    def test_wrong_genre_not_counted(self):
        for i in range(6):
            state = _make_state(f"student-M{i}", n_samples=1, genre="rhetoric")
            store.put(state)
        result = store.get_genre_stats("different_genre")
        assert result is None


# ── delete_student ────────────────────────────────────────────────────────────

class TestDeleteStudent:
    def test_returns_false_for_unknown_student(self):
        assert store.delete_student("nobody") is False

    def test_returns_true_for_known_student(self):
        state = _make_state("student-del-1")
        store.put(state)
        assert store.delete_student("student-del-1") is True

    def test_deleted_student_not_in_store(self):
        state = _make_state("student-del-2")
        store.put(state)
        store.delete_student("student-del-2")
        assert store.get("student-del-2") is None

    def test_deleted_student_not_in_list(self):
        state = _make_state("student-del-3")
        store.put(state)
        assert "student-del-3" in store.list_ids()
        store.delete_student("student-del-3")
        assert "student-del-3" not in store.list_ids()

    def test_fidelity_scores_purged(self):
        state = _make_state("student-del-4")
        store.put(state)
        store.put_fidelity_score("sub-del-4", "student-del-4", 0.75, is_authentic=True)
        assert len(store.get_authentic_fidelities("student-del-4")) == 1

        store.delete_student("student-del-4")
        assert store.get_authentic_fidelities("student-del-4") == []

    def test_genre_cache_busted_on_delete(self):
        for i in range(6):
            state = _make_state(f"student-del-cache-{i}", n_samples=1, genre="ethics_paper")
            store.put(state)
        # Prime cache
        store.get_genre_stats("ethics_paper")
        assert "ethics_paper" in store._GENRE_STATS_CACHE

        # Delete a student → cache should be cleared
        store.delete_student("student-del-cache-0")
        assert len(store._GENRE_STATS_CACHE) == 0

    def test_double_delete_is_safe(self):
        state = _make_state("student-del-5")
        store.put(state)
        assert store.delete_student("student-del-5") is True
        assert store.delete_student("student-del-5") is False  # already gone, not an error

    def test_other_students_unaffected(self):
        state_a = _make_state("student-del-A")
        state_b = _make_state("student-del-B")
        store.put(state_a)
        store.put(state_b)

        store.delete_student("student-del-A")
        assert store.get("student-del-A") is None
        assert store.get("student-del-B") is not None

    def test_corrections_with_null_student_id_purged(self):
        """
        Corrections whose student_id column is NULL (written before the
        manifest existed) must still be purged by delete_student().

        We simulate this by inserting a correction row with student_id=NULL
        directly via SQL, then confirming delete_student() removes it via
        the submission_id→manifest path.
        """
        import sqlite3
        from datetime import datetime, timezone

        state = _make_state("student-del-null-sid")
        store.put(state)

        # Write a fake manifest so delete_student() can look up submission_ids
        sub_id = "sub-null-sid-001"
        with store._get_conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO submission_manifests
                   (submission_id, student_id, created_at, manifest_json)
                   VALUES (?, ?, ?, ?)""",
                (sub_id, "student-del-null-sid",
                 datetime.now(timezone.utc).isoformat(), "{}"),
            )
            # Insert an orphaned correction with student_id=NULL
            conn.execute(
                """INSERT INTO corrections
                   (submission_id, student_id, is_correct, created_at)
                   VALUES (?, NULL, 1, ?)""",
                (sub_id, datetime.now(timezone.utc).isoformat()),
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
