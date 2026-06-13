"""
tests/test_store_tenants.py — Unit tests for tenant registry, tenant-scoped
stats, and the SQL LIKE-escaping fix (code-review finding #4).

The key regression guarded here: tenant_stats() must scope submission counts
to an EXACT tenant prefix. A tenant_id containing a SQL LIKE wildcard ('_' or
'%') must not accidentally match a sibling tenant's rows — matching the
exact-prefix behaviour of the deletion path (list_ids_for_tenant).
"""

from __future__ import annotations

import numpy as np
import pytest

import original.store as store
from original.quantum.state import BaselineSample, StudentState
from original.constants import FEATURE_DIM


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Point the store at a fresh temp SQLite DB and reset in-memory state."""
    import original.store as store_mod
    db_file = tmp_path / "test_profiles.db"
    monkeypatch.setenv("ORIGINAL_DB", str(db_file))

    _seen: set = set()

    def _patch(mod) -> None:
        if id(mod) in _seen:
            return
        _seen.add(id(mod))
        monkeypatch.setattr(mod, "_DB_PATH", db_file)
        mod._STORE.clear()
        mod._GENRE_STATS_CACHE.clear()
        mod._loaded = False

    _patch(store_mod)
    _patch(store)

    yield

    for obj in (store_mod, store):
        obj._STORE.clear()
        obj._GENRE_STATS_CACHE.clear()
        obj._loaded = False


def _make_state(student_id: str, n: int = 1) -> StudentState:
    state = StudentState(student_id=student_id)
    rng = np.random.default_rng(abs(hash(student_id)) % (2**31))
    for i in range(n):
        state.add_sample(BaselineSample(
            text="Sample text for tenant testing.",
            vector=rng.random(FEATURE_DIM).astype(np.float64),
            provenance="instructor_verified",
            auth_weight=1.0,
            assignment=f"A{i}",
            genre=None,
        ))
    return state


def _seed_manifest(submission_id: str, student_id: str, action: str = "no_action"):
    store.put_manifest(
        submission_id=submission_id,
        student_id=student_id,
        manifest={"created_at": "2026-01-01T00:00:00Z"},
        divergence_score=0.2,
        action=action,
    )


# ── _escape_like ──────────────────────────────────────────────────────────────

class TestEscapeLike:
    def test_no_wildcards_unchanged(self):
        assert store._escape_like("seminary-dallas:") == "seminary-dallas:"

    def test_underscore_escaped(self):
        assert store._escape_like("sem_a:") == r"sem\_a:"

    def test_percent_escaped(self):
        assert store._escape_like("sem%a:") == r"sem\%a:"

    def test_backslash_escaped_first(self):
        # Backslash must be doubled before % / _ are escaped
        assert store._escape_like("a\\b") == "a\\\\b"

    def test_combined(self):
        assert store._escape_like("a_b%c") == r"a\_b\%c"


# ── Tenant registry CRUD ──────────────────────────────────────────────────────

class TestTenantRegistry:
    def test_put_and_get(self):
        store.put_tenant("sem-dallas", "Dallas Seminary", environment="pilot",
                         meta={"contact": "reg@dts.edu"})
        t = store.get_tenant("sem-dallas")
        assert t["name"] == "Dallas Seminary"
        assert t["environment"] == "pilot"
        assert t["meta"]["contact"] == "reg@dts.edu"

    def test_get_unknown_returns_none(self):
        assert store.get_tenant("nobody") is None

    def test_upsert_preserves_id_updates_fields(self):
        store.put_tenant("sem-x", "Old Name", environment="demo")
        store.put_tenant("sem-x", "New Name", environment="production")
        t = store.get_tenant("sem-x")
        assert t["name"] == "New Name"
        assert t["environment"] == "production"

    def test_list_filtered_by_environment(self):
        store.put_tenant("a", "A", environment="demo")
        store.put_tenant("b", "B", environment="pilot")
        store.put_tenant("c", "C", environment="pilot")
        assert len(store.list_tenants()) == 3
        assert {t["tenant_id"] for t in store.list_tenants(environment="pilot")} == {"b", "c"}


# ── list_ids_for_tenant ───────────────────────────────────────────────────────

class TestListIdsForTenant:
    def test_prefix_match_only(self):
        store.put(_make_state("sem:alice"))
        store.put(_make_state("sem:bob"))
        store.put(_make_state("other:carol"))
        assert set(store.list_ids_for_tenant("sem")) == {"sem:alice", "sem:bob"}

    def test_unscoped_ids_excluded(self):
        store.put(_make_state("sem:alice"))
        store.put(_make_state("plainid"))   # no tenant prefix
        assert store.list_ids_for_tenant("sem") == ["sem:alice"]


# ── tenant_stats: the LIKE-escaping regression ────────────────────────────────

class TestTenantStatsScoping:
    def test_basic_counts(self):
        store.put(_make_state("sem:alice", n=2))
        store.put(_make_state("sem:bob", n=1))
        _seed_manifest("sub1", "sem:alice")
        _seed_manifest("sub2", "sem:alice", action="schedule_conversation")
        _seed_manifest("sub3", "sem:bob")
        stats = store.tenant_stats("sem")
        assert stats["student_count"] == 2
        assert stats["sample_count"] == 3            # 2 + 1
        assert stats["submission_count"] == 3
        assert stats["action_counts"]["no_action"] == 2
        assert stats["action_counts"]["schedule_conversation"] == 1

    def test_underscore_tenant_does_not_overcount_sibling(self):
        """
        The core regression. Tenant 'sem_a' must not count rows belonging to
        'semXa' — an unescaped LIKE would treat '_' as 'any single char'.
        """
        store.put(_make_state("sem_a:alice"))
        store.put(_make_state("semXa:victor"))
        _seed_manifest("real",  "sem_a:alice")
        _seed_manifest("bleed", "semXa:victor")   # sibling — must NOT be counted

        stats = store.tenant_stats("sem_a")
        assert stats["student_count"] == 1, "startswith path already exact"
        # The bug: without ESCAPE, this would be 2 (matching 'semXa:victor' too)
        assert stats["submission_count"] == 1, "LIKE must be wildcard-escaped"

    def test_percent_tenant_does_not_match_everything(self):
        """A tenant_id of '%' must not match every manifest row."""
        store.put(_make_state("%:alice"))
        _seed_manifest("a", "%:alice")
        _seed_manifest("b", "completely:unrelated")
        stats = store.tenant_stats("%")
        # '%' escaped → matches only the literal '%:' prefix, not all rows
        assert stats["submission_count"] == 1

    def test_empty_tenant_zero_counts(self):
        stats = store.tenant_stats("ghost")
        assert stats["student_count"] == 0
        assert stats["submission_count"] == 0
        assert stats["action_counts"] == {}


# ── delete_tenant_students consistency ────────────────────────────────────────

class TestDeleteTenantStudents:
    def test_bulk_delete_exact_prefix(self):
        store.put(_make_state("sem:alice"))
        store.put(_make_state("sem:bob"))
        store.put(_make_state("other:carol"))
        result = store.delete_tenant_students("sem")
        assert result["deleted_count"] == 2
        assert result["failed_ids"] == []
        assert store.list_ids_for_tenant("sem") == []
        assert store.get("other:carol") is not None   # untouched

    def test_underscore_tenant_does_not_delete_sibling(self):
        store.put(_make_state("sem_a:alice"))
        store.put(_make_state("semXa:victor"))
        result = store.delete_tenant_students("sem_a")
        assert result["deleted_count"] == 1
        assert store.get("semXa:victor") is not None   # sibling survives
