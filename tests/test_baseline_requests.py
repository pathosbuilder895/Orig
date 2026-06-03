"""
tests/test_baseline_requests.py — durable proctored-baseline registry.

The registry was in-memory only; a restart dropped every pending request.
These tests confirm write-through persistence survives a simulated restart
(cache cleared → re-hydrated from SQLite) and that status transitions persist.
"""

from __future__ import annotations

import time

import pytest

import original.store as store
import original.baseline_requests as br


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    import original.store as store_mod
    db_file = tmp_path / "br.db"
    monkeypatch.setenv("ORIGINAL_DB", str(db_file))
    for mod in {id(store_mod): store_mod, id(store): store}.values():
        monkeypatch.setattr(mod, "_DB_PATH", db_file)
        mod._STORE.clear()
        mod._loaded = False
    br._reset_cache()
    yield
    br._reset_cache()


def _make(student_id="sem:marcus", status="pending", expires_in=72 * 3600):
    return br.BaselineRequest(
        external_request_id=br.make_external_id(),
        student_id=student_id, student_email="m@x.edu", student_name="Marcus",
        exam_title="Week 3 Baseline", bbook_exam_id="exam-1",
        magic_link="http://x/link", requested_at=time.time(),
        expires_at=time.time() + expires_in, status=status,
    )


class TestDurability:
    def test_pending_survives_restart(self):
        br.record(_make())
        assert len(br.list_pending()) == 1
        br._reset_cache()                      # simulate process restart
        assert len(br._registry) == 0
        pending = br.list_pending()            # reading re-hydrates from SQLite
        assert len(pending) == 1
        assert pending[0].student_id == "sem:marcus"

    def test_completion_persists(self):
        br.record(_make())
        done = br.mark_completed_for_student("sem:marcus")
        assert len(done) == 1
        br._reset_cache()
        assert br.list_pending() == []          # not pending after restart
        allr = br.list_all()
        assert len(allr) == 1 and allr[0].status == "completed"

    def test_failure_persists(self):
        req = _make()
        br.record(req)
        br.mark_failed(req.external_request_id, "bbook exploded")
        br._reset_cache()
        got = br.get(req.external_request_id)
        assert got.status == "failed"
        assert got.error == "bbook exploded"

    def test_expiry_persists(self):
        br.record(_make(expires_in=-10))        # already expired
        assert br.list_pending() == []          # auto-expired on read
        br._reset_cache()
        allr = br.list_all()
        assert len(allr) == 1 and allr[0].status == "expired"

    def test_hydrate_is_idempotent(self):
        br.record(_make())
        # Multiple reads must not duplicate the by-student index
        br.list_pending(); br.list_all(); br.get("nope")
        assert len(br._by_student.get("sem:marcus", [])) == 1


class TestRepositorySeamWidened:
    """The Repository now also covers tenants + audit (ADR-002 action 3)."""

    def test_tenant_ops_through_repo(self):
        import original.repository as repository
        repository.reset_repository()
        repo = repository.get_repository()
        repo.put_tenant("sem-x", "Seminary X", environment="pilot")
        assert repo.get_tenant("sem-x")["environment"] == "pilot"
        assert any(t["tenant_id"] == "sem-x" for t in repo.list_tenants(environment="pilot"))
        stats = repo.tenant_stats("sem-x")
        assert stats["tenant_id"] == "sem-x"

    def test_audit_through_repo(self):
        import original.repository as repository
        repository.reset_repository()
        repo = repository.get_repository()
        repo.log_audit("formation_open", student_id="sem:alice", details={"x": 1})
        res = repo.list_audit(student_id="sem:alice")
        assert res["total"] >= 1
        assert res["items"][0]["action"] == "formation_open"

    def test_postgres_repo_is_explicit_skeleton(self):
        import original.repository as repository
        pg = repository.PostgresRepository()
        with pytest.raises(NotImplementedError):
            pg.get_formation_pathway("x")
        with pytest.raises(NotImplementedError):
            pg.list_tenants()
