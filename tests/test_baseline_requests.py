"""
tests/test_baseline_requests.py — durable proctored-baseline registry.

The registry was in-memory only; a restart dropped every pending request.
These tests confirm write-through persistence survives a simulated restart
(cache cleared → re-hydrated from SQLite) and that status transitions persist.
"""

from __future__ import annotations

import time

import pytest

import original.baseline_requests as br
import original.store as store


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    import original.store as store_mod

    db_file = tmp_path / "br.db"
    monkeypatch.setenv("ORIGINAL_DB", str(db_file))
    for mod in {id(store_mod): store_mod, id(store): store}.values():
        monkeypatch.setattr(mod, "_DB_PATH", db_file)
        mod._GENRE_STATS_CACHE.clear()
    br._reset_cache()
    yield
    br._reset_cache()


def _make(student_id="sem:marcus", status="pending", expires_in=72 * 3600):
    return br.BaselineRequest(
        external_request_id=br.make_external_id(),
        student_id=student_id,
        student_email="m@x.edu",
        student_name="Marcus",
        exam_title="Week 3 Baseline",
        bbook_exam_id="exam-1",
        magic_link="http://x/link",
        requested_at=time.time(),
        expires_at=time.time() + expires_in,
        status=status,
    )


class TestDurability:
    def test_pending_survives_restart(self):
        br.record(_make())
        assert len(br.list_pending()) == 1
        br._reset_cache()  # simulate process restart
        assert len(br._registry) == 0
        pending = br.list_pending()  # reading re-hydrates from SQLite
        assert len(pending) == 1
        assert pending[0].student_id == "sem:marcus"

    def test_completion_persists(self):
        br.record(_make())
        done = br.mark_completed_for_student("sem:marcus")
        assert len(done) == 1
        br._reset_cache()
        assert br.list_pending() == []  # not pending after restart
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
        br.record(_make(expires_in=-10))  # already expired
        assert br.list_pending() == []  # auto-expired on read
        br._reset_cache()
        allr = br.list_all()
        assert len(allr) == 1 and allr[0].status == "expired"

    def test_hydrate_is_idempotent(self):
        br.record(_make())
        # Multiple reads must not duplicate the by-student index
        br.list_pending()
        br.list_all()
        br.get("nope")
        assert len(br._by_student.get("sem:marcus", [])) == 1

    def test_persist_snapshot_failure_is_caught_and_counted(self):
        """A repo write failure (disk full, DB down, ...) inside
        ``_persist_snapshot`` must not propagate out of ``record`` — it's a
        best-effort mirror. The silent-failure counter is how ops notices."""

        class _FailingRepo:
            def put_baseline_request(self, **kwargs):
                raise RuntimeError("disk full")

        import original.baseline_requests as br_mod

        original_repo = br_mod._repo
        br_mod._repo = lambda: _FailingRepo()
        try:
            before = br.persist_failure_count()
            br.record(_make())
            assert br.persist_failure_count() == before + 1
        finally:
            br_mod._repo = original_repo

    def test_ensure_hydrated_exception_is_caught(self):
        """A load failure during first-use hydration must not raise — the
        cache is still marked hydrated (so we don't retry every call) and
        callers simply see an empty registry."""

        class _FailingRepo:
            def load_baseline_requests(self):
                raise RuntimeError("db unreachable")

        import original.baseline_requests as br_mod

        original_repo = br_mod._repo
        br_mod._repo = lambda: _FailingRepo()
        try:
            br._reset_cache()
            assert br.get("whatever-id") is None
            assert br_mod._hydrated is True
        finally:
            br_mod._repo = original_repo

    def test_mark_completed_skips_non_pending_requests_for_student(self):
        """A student can have a mix of pending and already-resolved
        requests — only the pending ones transition, and the loop must
        keep going past a non-pending entry to reach the next one."""
        req1 = _make(status="pending")
        req2 = _make(status="failed")  # must be skipped, not transitioned
        req3 = _make(status="pending")
        br.record(req1)
        br.record(req2)
        br.record(req3)
        done = br.mark_completed_for_student(req1.student_id)
        assert {r.external_request_id for r in done} == {
            req1.external_request_id,
            req3.external_request_id,
        }
        # The skipped one is untouched.
        assert br.get(req2.external_request_id).status == "failed"

    def test_mark_failed_on_absent_request_is_a_noop(self):
        """`mark_failed` for an id that was never recorded (or already
        purged) must not raise and must not persist anything."""
        br.mark_failed("no-such-external-request-id", "bbook exploded")
        assert br.get("no-such-external-request-id") is None

    def test_persist_snapshot_failure_only_logs_every_tenth(self):
        """The failure counter increments on every failure, but only every
        10th (including the first) actually logs a traceback — a steady
        tick of silent failures under a slow-disk incident shouldn't spam
        identical tracebacks. Pins the counter to 0 so both the logging
        (1 % 10 == 1) and skip-logging (2 % 10 != 1) arms are deterministic."""

        class _FailingRepo:
            def put_baseline_request(self, **kwargs):
                raise RuntimeError("disk full")

        import original.baseline_requests as br_mod

        original_repo = br_mod._repo
        original_count = br_mod._persist_failures
        br_mod._repo = lambda: _FailingRepo()
        br_mod._persist_failures = 0
        try:
            br.record(_make())  # failure #1 -> 1 % 10 == 1 -> logs
            br.record(_make())  # failure #2 -> 2 % 10 != 1 -> skip logging
            assert br_mod._persist_failures == 2
        finally:
            br_mod._repo = original_repo
            br_mod._persist_failures = original_count

    def test_record_duplicate_external_id_does_not_duplicate_index(self):
        """Calling record() twice with the SAME external_request_id (e.g.
        an idempotent client retry) must not append a second copy of the
        id to the by-student index."""
        req = _make()
        br.record(req)
        br.record(req)  # duplicate — same external_request_id
        assert br._by_student[req.student_id].count(req.external_request_id) == 1


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

    def test_postgres_repo_db_path_has_no_equivalent(self):
        """
        WS-6 P3-P6 (repository parity through decommission) landed 2026-07-17
        through 2026-07-22: ``PostgresRepository`` implements the full
        Protocol and is contract-tested against a real Postgres instance (see
        tests/test_repository_contract.py). ``db_path()`` is the one
        deliberate, permanent exception -- it exists only so SQLite's
        file-based backup tooling (``backup_mod.resolve_backup_dir``) has a
        path to copy, and Postgres backups use a completely different
        mechanism (pg_dump / WAL archiving / ``scripts/migrate_sqlite_to_pg.py``).

        ``get_repository()`` still defaults every environment to SQLite by
        design -- Postgres activates only via the ``REPO_BACKEND``/
        ``REPO_SHADOW`` env vars (the P5 cutover mechanism, shipped inert).
        The production cutover itself is now an operator action per
        OPS_RUNBOOK, not a pending code phase.
        """
        import original.repository as repository

        pg = repository.PostgresRepository()
        with pytest.raises(NotImplementedError):
            pg.db_path()

        repository.reset_repository()
        assert isinstance(repository.get_repository(), repository.SqliteRepository)
        repository.reset_repository()
