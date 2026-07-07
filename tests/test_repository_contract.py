"""
tests/test_repository_contract.py — Repository contract suite (ADR-002 / WS-6 P1).

These assertions exercise the ``Repository`` protocol (original/repository.py)
purely through its public interface — no reaching into ``store._get_conn()``,
``store._escape_like()``, or other SQLite-only internals. That's what makes
this suite backend-agnostic: the same assertions run unchanged against
``SqliteRepository`` today and against ``PostgresRepository`` once WS-6 P3
implements it (see the ``BACKENDS`` list below — add "postgres" there when
that lands, nothing else in this file needs to change).

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

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState
from original.repository import get_repository, reset_repository

BACKENDS = ["sqlite"]  # "postgres" joins once PostgresRepository lands (WS-6 P3)


@pytest.fixture(params=BACKENDS)
def repo(request, store_reset):
    """A Repository instance, isolated per test. Parametrized over backends."""
    reset_repository()
    if request.param == "sqlite":
        yield get_repository("demo")
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
