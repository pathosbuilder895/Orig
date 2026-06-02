"""
tests/test_formation.py — Formation pathways + the Repository seam (ADR-002).

Covers the three-session pathway lifecycle, idempotent open, flag-clearing on
completion (manifest action → no_action, fidelity → authentic), the audit
trail, and that the SqliteRepository delegates correctly.
"""

from __future__ import annotations

import pytest

import original.store as store
import original.repository as repository


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    import original.store as store_mod
    db_file = tmp_path / "test_profiles.db"
    monkeypatch.setenv("ORIGINAL_DB", str(db_file))
    _seen: set = set()

    def _patch(mod):
        if id(mod) in _seen:
            return
        _seen.add(id(mod))
        monkeypatch.setattr(mod, "_DB_PATH", db_file)
        mod._STORE.clear()
        mod._GENRE_STATS_CACHE.clear()
        mod._loaded = False

    _patch(store_mod)
    _patch(store)
    repository.reset_repository()
    yield
    for obj in (store_mod, store):
        obj._STORE.clear()
        obj._GENRE_STATS_CACHE.clear()
        obj._loaded = False
    repository.reset_repository()


def _seed_divergent(student_id="sem:alice", sub="sub-1"):
    store.put_manifest(sub, student_id, {"created_at": "2026-01-01T00:00:00Z"},
                       divergence_score=0.61, action="schedule_conversation")
    return sub


# ── store-level lifecycle ─────────────────────────────────────────────────────

class TestFormationLifecycle:
    def test_none_initially(self):
        assert store.get_formation_pathway("sem:alice") is None

    def test_open_creates_pathway(self):
        sub = _seed_divergent()
        p = store.open_formation_pathway("sem:alice", submission_id=sub, reason="divergence")
        assert p["status"] == "open"
        assert p["current_step"] == 0
        assert p["submission_id"] == sub
        assert p["total_steps"] == 3

    def test_open_is_idempotent(self):
        p1 = store.open_formation_pathway("sem:alice", submission_id="s")
        p2 = store.open_formation_pathway("sem:alice", submission_id="s")
        assert p1["id"] == p2["id"]

    def test_advance_steps(self):
        store.open_formation_pathway("sem:alice", submission_id="s")
        assert store.advance_formation_pathway("sem:alice")["current_step"] == 1
        assert store.advance_formation_pathway("sem:alice")["current_step"] == 2
        done = store.advance_formation_pathway("sem:alice")
        assert done["current_step"] == 3
        assert done["status"] == "completed"

    def test_advance_without_open_returns_none(self):
        assert store.advance_formation_pathway("nobody") is None

    def test_advance_after_complete_returns_none(self):
        store.open_formation_pathway("sem:alice", submission_id="s")
        for _ in range(3):
            store.advance_formation_pathway("sem:alice")
        # Pathway is completed; no open pathway remains
        assert store.advance_formation_pathway("sem:alice") is None


# ── flag clearing on completion ───────────────────────────────────────────────

class TestFlagClearing:
    def test_completion_clears_manifest_flag(self):
        sub = _seed_divergent()
        store.open_formation_pathway("sem:alice", submission_id=sub)
        for _ in range(3):
            store.advance_formation_pathway("sem:alice")
        with store._get_conn() as conn:
            action = conn.execute(
                "SELECT action FROM submission_manifests WHERE submission_id=?", (sub,)
            ).fetchone()[0]
        assert action == "no_action", "review flag must be cleared on completion"

    def test_completion_marks_fidelity_authentic(self):
        sub = _seed_divergent()
        store.put_fidelity_score(sub, "sem:alice", 0.4, is_authentic=False)
        assert store.get_authentic_fidelities("sem:alice") == []
        store.open_formation_pathway("sem:alice", submission_id=sub)
        for _ in range(3):
            store.advance_formation_pathway("sem:alice")
        # Completed formation flips the conformal label to authentic
        assert len(store.get_authentic_fidelities("sem:alice")) == 1

    def test_partial_pathway_does_not_clear_flag(self):
        sub = _seed_divergent()
        store.open_formation_pathway("sem:alice", submission_id=sub)
        store.advance_formation_pathway("sem:alice")  # step 1 only
        with store._get_conn() as conn:
            action = conn.execute(
                "SELECT action FROM submission_manifests WHERE submission_id=?", (sub,)
            ).fetchone()[0]
        assert action == "schedule_conversation", "flag must persist until completion"


# ── audit trail ───────────────────────────────────────────────────────────────

class TestFormationAudit:
    def test_open_advance_complete_audited(self):
        store.open_formation_pathway("sem:alice", submission_id="s")
        for _ in range(3):
            store.advance_formation_pathway("sem:alice")
        actions = [a["action"] for a in store.list_audit(student_id="sem:alice")["items"]]
        assert "formation_open" in actions
        assert "formation_advance" in actions
        assert "formation_complete" in actions


# ── Repository seam ───────────────────────────────────────────────────────────

class TestRepositorySeam:
    def test_factory_returns_sqlite_repo(self):
        repo = repository.get_repository("demo")
        assert isinstance(repo, repository.SqliteRepository)

    def test_factory_is_singleton(self):
        assert repository.get_repository() is repository.get_repository()

    def test_repo_satisfies_protocol(self):
        repo = repository.get_repository()
        assert isinstance(repo, repository.Repository)

    def test_repo_delegates_full_lifecycle(self):
        repo = repository.get_repository()
        assert repo.get_formation_pathway("sem:bob") is None
        p = repo.open_formation_pathway("sem:bob", submission_id="x")
        assert p["current_step"] == 0
        assert repo.advance_formation_pathway("sem:bob")["current_step"] == 1
        # Reflected through the store directly too
        assert store.get_formation_pathway("sem:bob")["current_step"] == 1
