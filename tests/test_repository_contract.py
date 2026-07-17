"""
tests/test_repository_contract.py — Repository contract suite (ADR-002 / WS-6 P1).

These assertions exercise the ``Repository`` protocol (original/repository.py)
purely through its public interface — no reaching into ``store._get_conn()``,
``store._escape_like()``, or other SQLite-only internals. That's what makes
this suite backend-agnostic: the same assertions run unchanged against
``SqliteRepository`` today and, once WS-6 P3 lands, ``PostgresRepository`` —
see the ``BACKENDS`` list below. The postgres parametrization is marked
``@pytest.mark.postgres`` and skips cleanly when no Postgres instance is
reachable (``_postgres_available()``), so this file is safe to run in any
sandbox: `pytest -m "not postgres"` to skip it explicitly, or just run
normally and let it self-skip.

Formerly two hand-maintained files (test_store_tenants.py's tenant/roster
classes, test_store_fidelity.py's fidelity/genre-stats/delete classes) that
called ``store.*`` directly. Folded into one parametrizable suite per WS-6 P1
deliverable #3, so a dialect bug shows up once instead of drifting between
two copies of the same assertion. Tests that inherently poke SQLite
internals (LIKE-escaping, raw SQL row manipulation) stayed behind in
test_store_tenants.py / test_store_fidelity.py — they test an implementation
detail, not something a Repository contract can promise.
"""

from __future__ import annotations

import json
import os

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState
from original.repository import PostgresRepository, get_repository, reset_repository

# WS-6 P3 has NOT landed: PostgresRepository is still an all-``_todo()``
# skeleton, so the "postgres" parametrization is staged ahead of P3. It only
# runs when a Postgres instance is actually reachable (see
# `_postgres_available()` below) and will fail until P3 ships — CI has no
# postgres service container yet, so it self-skips everywhere today.
# `pytest -m "not postgres"` deselects this parametrization entirely.
BACKENDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)]


def _postgres_available() -> bool:
    """True iff DATABASE_URL points at Postgres and it's actually reachable.

    Deliberately checked at fixture-setup time (not import time) so
    monkeypatching DATABASE_URL mid-session (or CI wiring up the service
    container after collection) both work.
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url.startswith("postgresql"):
        return False
    from original.db import postgres_session

    try:
        postgres_session.reset_engine()
        with postgres_session.get_engine().connect():
            return True
    except Exception:
        return False


@pytest.fixture(params=BACKENDS)
def repo(request, store_reset):
    """A Repository instance, isolated per test. Parametrized over backends."""
    reset_repository()
    if request.param == "sqlite":
        yield get_repository("demo")
    elif request.param == "postgres":
        if not _postgres_available():
            pytest.skip(
                "no reachable Postgres — set DATABASE_URL to a postgresql:// "
                "instance to run the WS-6 P3 contract tests against it"
            )
        from original.db import postgres_session
        from original.db.models.live import LiveBase

        engine = postgres_session.get_engine()
        LiveBase.metadata.create_all(bind=engine)
        # Isolate this test: wipe every table (children before parents, per
        # LiveBase.metadata.sorted_tables' dependency order reversed) rather
        # than dropping/recreating the schema on every test for speed.
        with engine.begin() as conn:
            for table in reversed(LiveBase.metadata.sorted_tables):
                conn.execute(table.delete())
        yield PostgresRepository()
    else:
        pytest.skip(f"backend {request.param!r} not implemented yet")
    reset_repository()


def _make_state(student_id: str, n: int = 1, genre: str | None = None) -> StudentState:
    state = StudentState(student_id=student_id)
    rng = np.random.default_rng(abs(hash(student_id)) % (2**31))
    for i in range(n):
        state.add_sample(
            BaselineSample(
                text="Sample text for repository contract testing.",
                vector=rng.random(FEATURE_DIM).astype(np.float64),
                provenance="instructor_verified",
                auth_weight=1.0,
                assignment=f"A{i}",
                genre=genre,
            )
        )
    return state


def _seed_manifest(repo, submission_id: str, student_id: str, action: str = "no_action"):
    repo.put_manifest(
        submission_id=submission_id,
        student_id=student_id,
        manifest={"created_at": "2026-01-01T00:00:00Z"},
        divergence_score=0.2,
        action=action,
    )


# ── Tenant registry CRUD ──────────────────────────────────────────────────────


class TestTenantRegistry:
    def test_put_and_get(self, repo):
        repo.put_tenant(
            "sem-dallas", "Dallas Seminary", environment="pilot", meta={"contact": "reg@dts.edu"}
        )
        t = repo.get_tenant("sem-dallas")
        assert t["name"] == "Dallas Seminary"
        assert t["environment"] == "pilot"
        assert t["meta"]["contact"] == "reg@dts.edu"

    def test_get_unknown_returns_none(self, repo):
        assert repo.get_tenant("nobody") is None

    def test_upsert_preserves_id_updates_fields(self, repo):
        repo.put_tenant("sem-x", "Old Name", environment="demo")
        repo.put_tenant("sem-x", "New Name", environment="production")
        t = repo.get_tenant("sem-x")
        assert t["name"] == "New Name"
        assert t["environment"] == "production"

    def test_list_filtered_by_environment(self, repo):
        repo.put_tenant("a", "A", environment="demo")
        repo.put_tenant("b", "B", environment="pilot")
        repo.put_tenant("c", "C", environment="pilot")
        assert len(repo.list_tenants()) == 3
        assert {t["tenant_id"] for t in repo.list_tenants(environment="pilot")} == {"b", "c"}


# ── list_ids_for_tenant ───────────────────────────────────────────────────────


class TestListIdsForTenant:
    def test_prefix_match_only(self, repo):
        repo.put(_make_state("sem:alice"))
        repo.put(_make_state("sem:bob"))
        repo.put(_make_state("other:carol"))
        assert set(repo.list_ids_for_tenant("sem")) == {"sem:alice", "sem:bob"}

    def test_unscoped_ids_excluded(self, repo):
        repo.put(_make_state("sem:alice"))
        repo.put(_make_state("plainid"))  # no tenant prefix
        assert repo.list_ids_for_tenant("sem") == ["sem:alice"]


# ── tenant_stats scoping ──────────────────────────────────────────────────────


class TestTenantStatsScoping:
    def test_basic_counts(self, repo):
        repo.put(_make_state("sem:alice", n=2))
        repo.put(_make_state("sem:bob", n=1))
        _seed_manifest(repo, "sub1", "sem:alice")
        _seed_manifest(repo, "sub2", "sem:alice", action="schedule_conversation")
        _seed_manifest(repo, "sub3", "sem:bob")
        stats = repo.tenant_stats("sem")
        assert stats["student_count"] == 2
        assert stats["sample_count"] == 3  # 2 + 1
        assert stats["submission_count"] == 3
        assert stats["action_counts"]["no_action"] == 2
        assert stats["action_counts"]["schedule_conversation"] == 1

    def test_underscore_tenant_does_not_overcount_sibling(self, repo):
        """
        The core regression this contract must hold on every backend: tenant
        'sem_a' must not count rows belonging to 'semXa' — an unescaped LIKE
        (or equivalent prefix scan) would treat '_' as 'any single char'.
        """
        repo.put(_make_state("sem_a:alice"))
        repo.put(_make_state("semXa:victor"))
        _seed_manifest(repo, "real", "sem_a:alice")
        _seed_manifest(repo, "bleed", "semXa:victor")  # sibling — must NOT be counted

        stats = repo.tenant_stats("sem_a")
        assert stats["student_count"] == 1, "startswith path already exact"
        assert stats["submission_count"] == 1, "prefix scan must be wildcard-safe"

    def test_percent_tenant_does_not_match_everything(self, repo):
        """A tenant_id of '%' must not match every manifest row."""
        repo.put(_make_state("%:alice"))
        _seed_manifest(repo, "a", "%:alice")
        _seed_manifest(repo, "b", "completely:unrelated")
        stats = repo.tenant_stats("%")
        assert stats["submission_count"] == 1

    def test_empty_tenant_zero_counts(self, repo):
        stats = repo.tenant_stats("ghost")
        assert stats["student_count"] == 0
        assert stats["submission_count"] == 0
        assert stats["action_counts"] == {}


# ── delete_tenant_students consistency ────────────────────────────────────────


class TestDeleteTenantStudents:
    def test_bulk_delete_exact_prefix(self, repo):
        repo.put(_make_state("sem:alice"))
        repo.put(_make_state("sem:bob"))
        repo.put(_make_state("other:carol"))
        result = repo.delete_tenant_students("sem")
        assert result["deleted_count"] == 2
        assert result["failed_ids"] == []
        assert repo.list_ids_for_tenant("sem") == []
        assert repo.get("other:carol") is not None  # untouched

    def test_underscore_tenant_does_not_delete_sibling(self, repo):
        repo.put(_make_state("sem_a:alice"))
        repo.put(_make_state("semXa:victor"))
        result = repo.delete_tenant_students("sem_a")
        assert result["deleted_count"] == 1
        assert repo.get("semXa:victor") is not None  # sibling survives


# ── put_fidelity_score / get_authentic_fidelities ────────────────────────────


class TestFidelityScoreRoundtrip:
    def test_empty_returns_empty_list(self, repo):
        assert repo.get_authentic_fidelities("nobody") == []

    def test_stored_authentic_score_returned(self, repo):
        repo.put_fidelity_score("sub-001", "student-A", 0.85, is_authentic=True)
        result = repo.get_authentic_fidelities("student-A")
        assert len(result) == 1
        assert abs(result[0] - 0.85) < 1e-6

    def test_non_authentic_score_not_returned(self, repo):
        repo.put_fidelity_score("sub-002", "student-A", 0.30, is_authentic=False)
        assert repo.get_authentic_fidelities("student-A") == []

    def test_mixed_authenticity_only_authentic_returned(self, repo):
        repo.put_fidelity_score("sub-A1", "student-B", 0.90, is_authentic=True)
        repo.put_fidelity_score("sub-A2", "student-B", 0.25, is_authentic=False)
        repo.put_fidelity_score("sub-A3", "student-B", 0.80, is_authentic=True)
        result = repo.get_authentic_fidelities("student-B")
        assert len(result) == 2
        assert all(f > 0.5 for f in result)

    def test_scores_isolated_by_student(self, repo):
        repo.put_fidelity_score("sub-X1", "student-X", 0.70, is_authentic=True)
        repo.put_fidelity_score("sub-Y1", "student-Y", 0.60, is_authentic=True)
        assert len(repo.get_authentic_fidelities("student-X")) == 1
        assert len(repo.get_authentic_fidelities("student-Y")) == 1

    def test_insert_or_replace_deduplicates_by_submission_id(self, repo):
        repo.put_fidelity_score("sub-DUP", "student-C", 0.50, is_authentic=True)
        repo.put_fidelity_score("sub-DUP", "student-C", 0.75, is_authentic=True)
        result = repo.get_authentic_fidelities("student-C")
        assert len(result) == 1
        assert abs(result[0] - 0.75) < 1e-6

    def test_limit_respected(self, repo):
        for i in range(10):
            repo.put_fidelity_score(f"sub-L{i}", "student-D", 0.5 + i * 0.02, is_authentic=True)
        result = repo.get_authentic_fidelities("student-D", limit=5)
        assert len(result) == 5


# ── update_fidelity_authenticity ─────────────────────────────────────────────


class TestUpdateFidelityAuthenticity:
    def test_flip_authentic_to_non_authentic(self, repo):
        repo.put_fidelity_score("sub-F1", "student-E", 0.80, is_authentic=True)
        assert len(repo.get_authentic_fidelities("student-E")) == 1
        repo.update_fidelity_authenticity("sub-F1", False)
        assert repo.get_authentic_fidelities("student-E") == []

    def test_flip_non_authentic_to_authentic(self, repo):
        repo.put_fidelity_score("sub-F2", "student-F", 0.40, is_authentic=False)
        assert repo.get_authentic_fidelities("student-F") == []
        repo.update_fidelity_authenticity("sub-F2", True)
        result = repo.get_authentic_fidelities("student-F")
        assert len(result) == 1
        assert abs(result[0] - 0.40) < 1e-6

    def test_no_op_when_submission_not_found(self, repo):
        repo.update_fidelity_authenticity("sub-GHOST", False)  # no row — must not raise

    def test_confirm_authentic_stays_authentic(self, repo):
        repo.put_fidelity_score("sub-F3", "student-G", 0.88, is_authentic=True)
        repo.update_fidelity_authenticity("sub-F3", True)
        assert len(repo.get_authentic_fidelities("student-G")) == 1


# ── get_genre_stats ───────────────────────────────────────────────────────────


class TestGetGenreStats:
    def test_returns_none_with_no_students(self, repo):
        assert repo.get_genre_stats("argumentative_essay") is None

    def test_returns_none_with_fewer_than_5_samples(self, repo):
        for i in range(4):
            repo.put(_make_state(f"student-G{i}", n=1, genre="argumentative_essay"))
        assert repo.get_genre_stats("argumentative_essay") is None

    def test_returns_stats_with_enough_samples(self, repo):
        for i in range(6):
            repo.put(_make_state(f"student-H{i}", n=1, genre="lab_report"))
        result = repo.get_genre_stats("lab_report")
        assert result is not None
        assert "mean" in result and "std" in result and "n_samples" in result
        assert result["n_samples"] == 6
        assert result["mean"].shape == (FEATURE_DIM,)
        assert result["std"].shape == (FEATURE_DIM,)

    def test_std_floored_at_005(self, repo):
        for i in range(6):
            repo.put(_make_state(f"student-I{i}", n=1, genre="theology_paper"))
        result = repo.get_genre_stats("theology_paper")
        assert result is not None
        assert float(np.min(result["std"])) >= 0.005

    def test_cache_hit_on_second_call(self, repo):
        for i in range(6):
            repo.put(_make_state(f"student-J{i}", n=1, genre="sermon"))
        r1 = repo.get_genre_stats("sermon")
        r2 = repo.get_genre_stats("sermon")
        assert r1 is r2  # cached — same object reference

    def test_cache_busted_after_put(self, repo):
        for i in range(6):
            repo.put(_make_state(f"student-K{i}", n=1, genre="exegesis"))
        r1 = repo.get_genre_stats("exegesis")
        assert r1 is not None
        repo.put(_make_state("student-K6", n=1, genre="exegesis"))
        r2 = repo.get_genre_stats("exegesis")
        assert r2 is not None
        assert r2["n_samples"] == 7

    def test_none_genre_samples_not_counted_for_named_genre(self, repo):
        for i in range(6):
            repo.put(_make_state(f"student-L{i}", n=1, genre=None))
        assert repo.get_genre_stats("argumentative_essay") is None

    def test_wrong_genre_not_counted(self, repo):
        for i in range(6):
            repo.put(_make_state(f"student-M{i}", n=1, genre="rhetoric"))
        assert repo.get_genre_stats("different_genre") is None


# ── delete_student ────────────────────────────────────────────────────────────


class TestDeleteStudent:
    def test_returns_false_for_unknown_student(self, repo):
        assert repo.delete_student("nobody") is False

    def test_returns_true_for_known_student(self, repo):
        repo.put(_make_state("student-del-1"))
        assert repo.delete_student("student-del-1") is True

    def test_deleted_student_not_in_store(self, repo):
        repo.put(_make_state("student-del-2"))
        repo.delete_student("student-del-2")
        assert repo.get("student-del-2") is None

    def test_deleted_student_not_in_list(self, repo):
        repo.put(_make_state("student-del-3"))
        assert "student-del-3" in repo.list_ids()
        repo.delete_student("student-del-3")
        assert "student-del-3" not in repo.list_ids()

    def test_fidelity_scores_purged(self, repo):
        repo.put(_make_state("student-del-4"))
        repo.put_fidelity_score("sub-del-4", "student-del-4", 0.75, is_authentic=True)
        assert len(repo.get_authentic_fidelities("student-del-4")) == 1
        repo.delete_student("student-del-4")
        assert repo.get_authentic_fidelities("student-del-4") == []

    def test_double_delete_is_safe(self, repo):
        repo.put(_make_state("student-del-5"))
        assert repo.delete_student("student-del-5") is True
        assert repo.delete_student("student-del-5") is False  # already gone, not an error

    def test_other_students_unaffected(self, repo):
        repo.put(_make_state("student-del-A"))
        repo.put(_make_state("student-del-B"))
        repo.delete_student("student-del-A")
        assert repo.get("student-del-A") is None
        assert repo.get("student-del-B") is not None


# ── Student state basics (get/get_or_create/put/list_ids/all_states/count) ───
# WS-6 P3: these were previously only exercised indirectly by the classes
# above; added explicitly so the get_or_create "doesn't persist until put()"
# contract (shared by both backends — see PostgresRepository.get_or_create's
# docstring) has a direct assertion.


class TestGetOrCreateAndBasics:
    def test_get_unknown_returns_none(self, repo):
        assert repo.get("nobody-at-all") is None

    def test_get_or_create_then_get_sees_the_same_empty_state(self, repo):
        # store.get_or_create() inserts straight into the same in-memory
        # `_STORE` dict `get()` reads from, so a follow-up `get()` in the
        # same process sees the just-created empty state immediately — that
        # observable contract is what's asserted here (see
        # PostgresRepository.get_or_create's docstring for how the Postgres
        # backend achieves the same contract without a shared cache).
        state = repo.get_or_create("sem:fresh-goc")
        assert state.student_id == "sem:fresh-goc"
        assert state.sample_count == 0
        again = repo.get("sem:fresh-goc")
        assert again is not None
        assert again.sample_count == 0

    def test_get_or_create_returns_existing_after_put(self, repo):
        repo.put(_make_state("sem:goc-existing", n=1))
        state = repo.get_or_create("sem:goc-existing")
        assert state.sample_count == 1

    def test_put_then_get_roundtrip(self, repo):
        repo.put(_make_state("sem:roundtrip", n=3, genre="sermon"))
        state = repo.get("sem:roundtrip")
        assert state is not None
        assert state.student_id == "sem:roundtrip"
        assert state.sample_count == 3
        assert state.density_matrix.shape == (FEATURE_DIM, FEATURE_DIM)
        assert all(s.genre == "sermon" for s in state.samples)

    def test_list_ids_and_count(self, repo):
        repo.put(_make_state("sem:count-a"))
        repo.put(_make_state("sem:count-b"))
        ids = repo.list_ids()
        assert "sem:count-a" in ids
        assert "sem:count-b" in ids
        assert repo.count() >= 2

    def test_all_states(self, repo):
        repo.put(_make_state("sem:all-a", n=2))
        states = repo.all_states()
        matching = [s for s in states if s.student_id == "sem:all-a"]
        assert len(matching) == 1
        assert matching[0].sample_count == 2

    def test_put_replaces_whole_sample_set(self, repo):
        """put() is a full-state overwrite, not an incremental append —
        matches store.py's whole-JSON-blob replace semantics."""
        repo.put(_make_state("sem:replace", n=3))
        assert repo.get("sem:replace").sample_count == 3
        repo.put(_make_state("sem:replace", n=1))
        assert repo.get("sem:replace").sample_count == 1


# ── Manifests ──────────────────────────────────────────────────────────────


class TestManifests:
    def test_put_and_get_manifest(self, repo):
        repo.put_manifest(
            "sub-m1",
            "sem:alice",
            {"created_at": "2026-01-01T00:00:00Z", "flags": ["length_short"]},
            divergence_score=0.4,
            action="monitor",
        )
        m = repo.get_manifest("sub-m1")
        assert m["student_id"] == "sem:alice"
        assert m["action"] == "monitor"
        assert m["divergence_score"] == 0.4
        assert m["manifest"]["flags"] == ["length_short"]

    def test_get_manifest_unknown_returns_none(self, repo):
        assert repo.get_manifest("no-such-submission") is None

    def test_submission_student_id_from_manifest(self, repo):
        repo.put_manifest("sub-m2", "sem:bob", {"created_at": "2026-01-01T00:00:00Z"})
        assert repo.submission_student_id("sub-m2") == "sem:bob"

    def test_submission_student_id_falls_back_to_audit(self, repo):
        repo.log_audit(action="score", student_id="sem:carol", details={"submission_id": "sub-noManifest"})
        assert repo.submission_student_id("sub-noManifest") == "sem:carol"

    def test_submission_student_id_unknown_returns_none(self, repo):
        assert repo.submission_student_id("totally-unknown-sub") is None

    def test_submission_student_id_treats_wildcards_as_literal(self, repo):
        # '_' in an unescaped LIKE pattern matches any single character, so
        # looking up "sub_1" would mis-attribute this "subX1" audit row.
        repo.log_audit(action="score", student_id="sem:eve", details={"submission_id": "subX1"})
        assert repo.submission_student_id("sub_1") is None
        repo.log_audit(action="score", student_id="sem:dan", details={"submission_id": "sub_1"})
        assert repo.submission_student_id("sub_1") == "sem:dan"

    def test_list_manifests_filters_by_student(self, repo):
        repo.put_manifest("sub-l1", "sem:dave", {"created_at": "2026-01-01T00:00:00Z"}, action="no_action")
        repo.put_manifest("sub-l2", "sem:erin", {"created_at": "2026-01-02T00:00:00Z"}, action="monitor")
        result = repo.list_manifests(student_id="sem:dave")
        assert result["total"] == 1
        assert result["items"][0]["submission_id"] == "sub-l1"

    def test_list_manifests_filters_by_action(self, repo):
        repo.put_manifest("sub-l3", "sem:frank", {"created_at": "2026-01-01T00:00:00Z"}, action="escalate")
        result = repo.list_manifests(action="escalate")
        assert result["total"] >= 1
        assert all(i["action"] == "escalate" for i in result["items"])

    def test_list_manifests_filters_by_flag(self, repo):
        repo.put_manifest(
            "sub-l4", "sem:gwen", {"created_at": "2026-01-01T00:00:00Z", "flags": ["outlier"]}, action="monitor"
        )
        repo.put_manifest(
            "sub-l5", "sem:hank", {"created_at": "2026-01-01T00:00:00Z", "flags": []}, action="monitor"
        )
        result = repo.list_manifests(flag="outlier")
        assert result["total"] == 1
        assert result["items"][0]["submission_id"] == "sub-l4"

    def test_manifest_stats_aggregates(self, repo):
        repo.put_manifest(
            "sub-s1",
            "sem:ian",
            {"created_at": "2026-01-01T00:00:00Z", "flags": ["a"], "length_regime": "short"},
            divergence_score=0.3,
            action="no_action",
        )
        repo.put_manifest(
            "sub-s2",
            "sem:jill",
            {"created_at": "2026-01-01T00:00:00Z", "flags": ["a", "b"], "length_regime": "short"},
            divergence_score=0.5,
            action="monitor",
        )
        stats = repo.manifest_stats()
        assert stats["total"] >= 2
        assert stats["by_action"]["no_action"] >= 1
        assert stats["by_flag"]["a"] >= 2


# ── Corrections ───────────────────────────────────────────────────────────


class TestCorrections:
    def test_put_and_list_correction(self, repo):
        cid = repo.put_correction(
            "sub-c1",
            True,
            student_id="sem:alice",
            original_verdict="authentic",
            original_action="no_action",
            original_divergence_score=0.1,
            reviewer="prof@x.edu",
            notes="fine",
        )
        assert cid is not None
        result = repo.list_corrections(student_id="sem:alice")
        assert result["total"] == 1
        assert result["items"][0]["is_correct"] is True
        assert result["items"][0]["reviewer"] == "prof@x.edu"

    def test_put_correction_autofills_from_manifest(self, repo):
        repo.put_manifest(
            "sub-c2", "sem:bob", {"created_at": "2026-01-01T00:00:00Z"}, divergence_score=0.6, action="escalate"
        )
        cid = repo.put_correction("sub-c2", False)
        assert cid is not None
        result = repo.list_corrections(submission_id="sub-c2")
        item = result["items"][0]
        assert item["student_id"] == "sem:bob"
        assert item["original_action"] == "escalate"
        assert item["original_divergence_score"] == 0.6

    def test_list_corrections_filters_by_is_correct(self, repo):
        repo.put_correction("sub-c3", True, student_id="sem:carol")
        repo.put_correction("sub-c4", False, student_id="sem:carol")
        result = repo.list_corrections(student_id="sem:carol", is_correct=False)
        assert result["total"] == 1
        assert result["items"][0]["submission_id"] == "sub-c4"


# ── Calibration runs ──────────────────────────────────────────────────────


class TestCalibrationRuns:
    def test_full_lifecycle(self, repo):
        run_id = repo.start_calibration_run("dataset-A", run_label="nightly")
        assert run_id is not None
        run = repo.get_calibration_run(run_id)
        assert run["status"] == "running"
        ok = repo.complete_calibration_run(
            run_id, auc=0.93, n_essays_scored=42, n_authors=7, report={"roc": [0.1, 0.2]}
        )
        assert ok is True
        run = repo.get_calibration_run(run_id)
        assert run["status"] == "completed"
        assert run["auc"] == 0.93
        assert run["report"]["roc"] == [0.1, 0.2]

    def test_fail_calibration_run(self, repo):
        run_id = repo.start_calibration_run("dataset-B")
        ok = repo.fail_calibration_run(run_id, "boom")
        assert ok is True
        run = repo.get_calibration_run(run_id)
        assert run["status"] == "failed"
        assert run["error"] == "boom"

    def test_complete_unknown_run_returns_true_store_quirk(self, repo):
        # store.complete_calibration_run() never checks rowcount — an
        # UPDATE matching zero rows isn't an error, so it returns True
        # unconditionally unless the query itself raises. This is arguably
        # a quirk, but faithfully porting existing behavior (not silently
        # "fixing" it) is this phase's job — see PostgresRepository's
        # matching comment.
        assert repo.complete_calibration_run(999999, auc=0.5, n_essays_scored=1, n_authors=1, report={}) is True

    def test_list_calibration_runs_filters_by_status(self, repo):
        repo.start_calibration_run("dataset-C")
        r2 = repo.start_calibration_run("dataset-C")
        result = repo.list_calibration_runs(status="running")
        assert any(item["id"] == r2 for item in result["items"])
        assert all(item["status"] == "running" for item in result["items"])

    def test_get_calibration_run_include_report_false_omits_report(self, repo):
        run_id = repo.start_calibration_run("dataset-D")
        repo.complete_calibration_run(run_id, auc=0.5, n_essays_scored=1, n_authors=1, report={"x": 1})
        run = repo.get_calibration_run(run_id, include_report=False)
        assert "report" not in run


# ── Tuned thresholds ──────────────────────────────────────────────────────


class TestTunedThresholds:
    def test_put_and_get_active(self, repo):
        repo.put_tuned_thresholds(no_action=0.1, monitor=0.4, escalate=0.7, source="manual")
        tid = repo.put_tuned_thresholds(no_action=0.15, monitor=0.45, escalate=0.75, source="calibration_run")
        active = repo.get_active_tuned_thresholds()
        assert active["id"] == tid
        assert active["source"] == "calibration_run"

    def test_get_active_none_when_empty(self, repo):
        assert repo.get_active_tuned_thresholds() is None

    def test_list_tuned_thresholds_newest_first(self, repo):
        repo.put_tuned_thresholds(no_action=0.1, monitor=0.4, escalate=0.7, source="manual")
        repo.put_tuned_thresholds(no_action=0.2, monitor=0.5, escalate=0.8, source="manual")
        result = repo.list_tuned_thresholds()
        assert result["total"] == 2
        assert result["items"][0]["no_action"] == 0.2


# ── Bluebook (exams, submissions, courses) ───────────────────────────────


class TestBluebook:
    def test_exam_put_get_list(self, repo):
        repo.put_bluebook_exam(
            {"id": "exam-A", "tenant_id": "sem", "title": "Final", "course": "THEO101", "minWords": 300, "maxWords": 900}
        )
        exam = repo.get_bluebook_exam("exam-A")
        assert exam["title"] == "Final"
        assert exam["tenant_id"] == "sem"
        assert exam["minWords"] == 300
        listed = repo.list_bluebook_exams("sem")
        assert any(e["id"] == "exam-A" for e in listed)

    def test_exam_upsert(self, repo):
        repo.put_bluebook_exam({"id": "exam-B", "tenant_id": "sem", "title": "Draft"})
        repo.put_bluebook_exam({"id": "exam-B", "tenant_id": "sem", "title": "Final", "status": "PUBLISHED"})
        exam = repo.get_bluebook_exam("exam-B")
        assert exam["title"] == "Final"
        assert exam["status"] == "PUBLISHED"

    def test_get_exam_unknown_returns_none(self, repo):
        assert repo.get_bluebook_exam("no-such-exam") is None

    def test_submission_put_and_list(self, repo):
        repo.put_bluebook_exam({"id": "exam-C", "tenant_id": "sem", "title": "Midterm"})
        repo.put_bluebook_submission(
            {
                "id": "bbsub-A",
                "tenant_id": "sem",
                "exam_id": "exam-C",
                "student_id": "sem:alice",
                "candidate": "Alice",
                "word_count": 500,
            }
        )
        subs = repo.list_bluebook_submissions("sem")
        assert len(subs) == 1
        assert subs[0]["candidate"] == "Alice"
        assert subs[0]["words"] == 500

    def test_course_put_get_list(self, repo):
        repo.put_bluebook_course({"id": "course-A", "tenant_id": "sem", "name": "Theology 101", "code": "THEO101"})
        courses = repo.list_bluebook_courses("sem")
        assert len(courses) == 1
        assert courses[0]["name"] == "Theology 101"

    def test_exams_scoped_by_tenant(self, repo):
        repo.put_bluebook_exam({"id": "exam-D", "tenant_id": "sem-x", "title": "X"})
        repo.put_bluebook_exam({"id": "exam-E", "tenant_id": "sem-y", "title": "Y"})
        assert {e["id"] for e in repo.list_bluebook_exams("sem-x")} == {"exam-D"}
        assert {e["id"] for e in repo.list_bluebook_exams(None)} >= {"exam-D", "exam-E"}


# ── Users ─────────────────────────────────────────────────────────────────


class TestUsers:
    def test_put_and_get_user(self, repo):
        repo.put_user("user-A", "Prof.X@Example.com", "hashed-pw", "professor", "sem", name="Prof X")
        u = repo.get_user_by_email("prof.x@example.com")
        assert u is not None
        assert u["role"] == "professor"
        assert u["tenant_id"] == "sem"
        assert u["name"] == "Prof X"

    def test_get_user_unknown_returns_none(self, repo):
        assert repo.get_user_by_email("nobody@example.com") is None

    def test_put_user_upsert_updates_fields(self, repo):
        repo.put_user("user-B", "b@example.com", "old-hash", "professor", "sem")
        repo.put_user("user-B", "b@example.com", "new-hash", "admin", "sem")
        u = repo.get_user_by_email("b@example.com")
        assert u["password_hash"] == "new-hash"
        assert u["role"] == "admin"


# ── Audit log ─────────────────────────────────────────────────────────────


class TestAuditLog:
    def test_log_and_list(self, repo):
        repo.log_audit(action="baseline_add", student_id="sem:alice", result="ok", details={"n": 1})
        result = repo.list_audit(student_id="sem:alice")
        assert result["total"] == 1
        assert result["items"][0]["action"] == "baseline_add"
        assert result["items"][0]["tenant_id"] == "sem"
        assert result["items"][0]["details"]["n"] == 1

    def test_list_audit_filters_by_action(self, repo):
        repo.log_audit(action="score", student_id="sem:bob")
        repo.log_audit(action="correction", student_id="sem:bob")
        result = repo.list_audit(action="score")
        assert result["total"] >= 1
        assert all(i["action"] == "score" for i in result["items"])

    def test_log_audit_derives_tenant_from_student_prefix(self, repo):
        repo.log_audit(action="score", student_id="sem-z:carol", details={})
        result = repo.list_audit(student_id="sem-z:carol")
        assert result["items"][0]["tenant_id"] == "sem-z"


# ── Formation pathways ────────────────────────────────────────────────────


class TestFormationPathway:
    def test_open_and_get(self, repo):
        p = repo.open_formation_pathway("sem:alice", submission_id="sub-f1", reason="divergence")
        assert p["status"] == "open"
        assert p["current_step"] == 0
        got = repo.get_formation_pathway("sem:alice")
        assert got["id"] == p["id"]

    def test_open_idempotent_when_already_open(self, repo):
        p1 = repo.open_formation_pathway("sem:bob")
        p2 = repo.open_formation_pathway("sem:bob")
        assert p1["id"] == p2["id"]

    def test_advance_to_completion_clears_manifest_action(self, repo):
        repo.put_manifest("sub-f2", "sem:carol", {"created_at": "2026-01-01T00:00:00Z"}, action="escalate")
        repo.open_formation_pathway("sem:carol", submission_id="sub-f2")
        repo.advance_formation_pathway("sem:carol")
        repo.advance_formation_pathway("sem:carol")
        p = repo.advance_formation_pathway("sem:carol")
        assert p["status"] == "completed"
        assert p["current_step"] == 3
        m = repo.get_manifest("sub-f2")
        assert m["action"] == "no_action"

    def test_advance_with_no_open_pathway_returns_none(self, repo):
        assert repo.advance_formation_pathway("sem:nobody-formation") is None

    def test_get_unknown_student_returns_none(self, repo):
        assert repo.get_formation_pathway("sem:ghost-formation") is None


# ── Baseline requests ─────────────────────────────────────────────────────


class TestBaselineRequests:
    def test_put_and_load(self, repo):
        repo.put_baseline_request("req-A", "sem:alice", "pending", 1000.0, json.dumps({"foo": "bar"}))
        loaded = repo.load_baseline_requests()
        assert any(d.get("foo") == "bar" for d in loaded)

    def test_upsert_keeps_one_row_per_request_id(self, repo):
        repo.put_baseline_request("req-B", "sem:bob", "pending", 1000.0, json.dumps({"tag": "req-B", "status": "pending"}))
        repo.put_baseline_request(
            "req-B", "sem:bob", "completed", 1000.0, json.dumps({"tag": "req-B", "status": "completed"})
        )
        loaded = repo.load_baseline_requests()
        matches = [d for d in loaded if d.get("tag") == "req-B"]
        assert len(matches) == 1
        assert matches[0]["status"] == "completed"

    def test_ordered_by_requested_at(self, repo):
        repo.put_baseline_request("req-C", "sem:x", "pending", 200.0, json.dumps({"tag": "second"}))
        repo.put_baseline_request("req-D", "sem:x", "pending", 100.0, json.dumps({"tag": "first"}))
        loaded = repo.load_baseline_requests()
        tags = [d.get("tag") for d in loaded if d.get("tag") in ("first", "second")]
        assert tags.index("first") < tags.index("second")


# ── Student data inventory (FERPA) ────────────────────────────────────────


class TestStudentDataInventory:
    def test_returns_none_for_unknown(self, repo):
        assert repo.student_data_inventory("nobody-inventory") is None

    def test_returns_summary_for_known_student(self, repo):
        repo.put(_make_state("sem:inv", n=2))
        repo.put_fidelity_score("sub-inv1", "sem:inv", 0.9, is_authentic=True)
        inv = repo.student_data_inventory("sem:inv")
        assert inv["student_id"] == "sem:inv"
        assert inv["data_categories"]["baseline_samples"]["count"] == 2
        assert inv["data_categories"]["fidelity_scores"]["count"] == 1
