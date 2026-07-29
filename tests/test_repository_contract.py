"""
tests/test_repository_contract.py — Repository contract suite (ADR-002 / WS-6 P1).

These assertions exercise the ``Repository`` protocol (original/repository.py)
purely through its public interface — no reaching into ``store._get_conn()``,
``store._escape_like()``, or other SQLite-only internals. That's what makes
this suite backend-agnostic: the same assertions run unchanged against
``SqliteRepository`` and ``PostgresRepository`` (WS-6 P3) — see the
``BACKENDS`` list below. The postgres parametrization is marked
``@pytest.mark.postgres`` and skips cleanly when no Postgres instance is
reachable (``_postgres_available()``), so this file is safe to run in any
sandbox: `pytest -m "not postgres"` to skip it explicitly, or just run
normally and let it self-skip when ``DATABASE_URL`` isn't set.

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
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from original.constants import FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState
from original.repository import PostgresRepository, get_repository, reset_repository

# WS-6 P3: PostgresRepository implements every method except db_path()
# (SQLite-file-specific backup tooling with no Postgres equivalent — see
# test_baseline_requests.py's test_postgres_repo_db_path_has_no_equivalent).
# This parametrization only runs when a Postgres instance is actually
# reachable (see `_postgres_available()` below); it self-skips when
# DATABASE_URL isn't set to a postgresql:// instance, so this file stays
# safe to run in any sandbox. `pytest -m "not postgres"` deselects it
# entirely.
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
        yield get_repository()
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


# Every _make_state id in this class is an unscoped/legacy-flat id (no ":"),
# so tenant_of(...) is None for all of them — hence the `None` tenant
# argument throughout. See TestGetGenreStatsTenantIsolation below for the
# scoped-id case.
class TestGetGenreStats:
    def test_returns_none_with_no_students(self, repo):
        assert repo.get_genre_stats("argumentative_essay", None, None) is None

    def test_returns_none_with_fewer_than_5_samples(self, repo):
        for i in range(4):
            repo.put(_make_state(f"student-G{i}", n=1, genre="argumentative_essay"))
        assert repo.get_genre_stats("argumentative_essay", None, None) is None

    def test_returns_stats_with_enough_samples(self, repo):
        for i in range(6):
            repo.put(_make_state(f"student-H{i}", n=1, genre="lab_report"))
        result = repo.get_genre_stats("lab_report", None, None)
        assert result is not None
        assert "mean" in result and "std" in result and "n_samples" in result
        assert result["n_samples"] == 6
        assert result["mean"].shape == (FEATURE_DIM,)
        assert result["std"].shape == (FEATURE_DIM,)

    def test_std_floored_at_005(self, repo):
        for i in range(6):
            repo.put(_make_state(f"student-I{i}", n=1, genre="theology_paper"))
        result = repo.get_genre_stats("theology_paper", None, None)
        assert result is not None
        assert float(np.min(result["std"])) >= 0.005

    def test_repeated_calls_are_stable(self, repo):
        # Identity (`r1 is r2`) is deliberately NOT asserted: the cache holds
        # the pool grouped by student, not the finished stats, so that one
        # scan serves every student's leave-one-out view. Each call therefore
        # builds a fresh dict. That the scan itself is cached is a store-level
        # detail, asserted in test_store_fidelity.py against
        # store._GENRE_STATS_CACHE; what the Repository contract promises is
        # that repeated calls agree.
        for i in range(6):
            repo.put(_make_state(f"student-J{i}", n=1, genre="sermon"))
        r1 = repo.get_genre_stats("sermon", None, None)
        r2 = repo.get_genre_stats("sermon", None, None)
        assert r1 is not None and r2 is not None
        assert r1["n_samples"] == r2["n_samples"]
        assert np.array_equal(r1["mean"], r2["mean"])
        assert np.array_equal(r1["std"], r2["std"])

    def test_cache_busted_after_put(self, repo):
        for i in range(6):
            repo.put(_make_state(f"student-K{i}", n=1, genre="exegesis"))
        r1 = repo.get_genre_stats("exegesis", None, None)
        assert r1 is not None
        repo.put(_make_state("student-K6", n=1, genre="exegesis"))
        r2 = repo.get_genre_stats("exegesis", None, None)
        assert r2 is not None
        assert r2["n_samples"] == 7

    def test_none_genre_samples_not_counted_for_named_genre(self, repo):
        for i in range(6):
            repo.put(_make_state(f"student-L{i}", n=1, genre=None))
        assert repo.get_genre_stats("argumentative_essay", None, None) is None

    def test_wrong_genre_not_counted(self, repo):
        for i in range(6):
            repo.put(_make_state(f"student-M{i}", n=1, genre="rhetoric"))
        assert repo.get_genre_stats("different_genre", None, None) is None


# ── get_genre_stats distinct-student floor ───────────────────────────────────
#
# MIN_GENRE_VECTORS alone bounds how MANY vectors a prior rests on, not how
# many PEOPLE. Tenant-scoping shrank each pool enough that genre matching no
# longer bounds concentration on its own, so one prolific student's samples
# could stand in for a whole tenant's "population" prior — and then that same
# student's cold-start submissions would be scored against a distribution
# built from their own writing. MIN_GENRE_STUDENTS mirrors null_pool.py's
# MIN_IMPOSTOR_STUDENTS (3) for exactly the same reason.


class TestGetGenreStatsStudentFloor:
    def test_single_prolific_student_cannot_form_a_prior(self, repo):
        # 6 vectors — clears MIN_GENRE_VECTORS — but from one person.
        repo.put(_make_state("student-SF0", n=6, genre="sermon"))
        assert repo.get_genre_stats("sermon", None, None) is None

    def test_two_students_still_below_the_student_floor(self, repo):
        # 6 vectors, 2 contributing students: vector floor met, student floor not.
        repo.put(_make_state("student-SF1", n=3, genre="exegesis"))
        repo.put(_make_state("student-SF2", n=3, genre="exegesis"))
        assert repo.get_genre_stats("exegesis", None, None) is None

    def test_three_students_clear_both_floors(self, repo):
        repo.put(_make_state("student-SF3", n=2, genre="homiletics"))
        repo.put(_make_state("student-SF4", n=2, genre="homiletics"))
        repo.put(_make_state("student-SF5", n=2, genre="homiletics"))
        result = repo.get_genre_stats("homiletics", None, None)
        assert result is not None
        assert result["n_samples"] == 6

    def test_students_are_counted_per_genre_not_overall(self, repo):
        # 3 students exist, but only one wrote in this genre. The other two
        # must not lift it over the student floor.
        repo.put(_make_state("student-SF6", n=6, genre="canon_law"))
        repo.put(_make_state("student-SF7", n=2, genre="something_else"))
        repo.put(_make_state("student-SF8", n=2, genre="another_thing"))
        assert repo.get_genre_stats("canon_law", None, None) is None

    def test_unverified_samples_count_toward_neither_floor(self, repo):
        # An auth_weight=0 sample must not make its owner a contributing
        # student, nor its vector count toward n_samples.
        for i in range(3):
            repo.put(_make_state(f"student-SF9{i}", n=2, genre="rhetoric"))
        unverified = StudentState(student_id="student-SF-unverified")
        unverified.add_sample(
            BaselineSample(
                text="unverified",
                vector=np.random.default_rng(1).random(FEATURE_DIM).astype(np.float64),
                provenance="unverified",
                auth_weight=0.0,
                genre="rhetoric",
            )
        )
        repo.put(unverified)
        result = repo.get_genre_stats("rhetoric", None, None)
        assert result is not None
        assert result["n_samples"] == 6  # not 7


# ── get_genre_stats self-exclusion ───────────────────────────────────────────
#
# The prior is meant to be the POPULATION distribution a student is compared
# against. Including the student's own baselines in it double-counts them:
# scoring.score() blends the student's own mean toward the prior, so a prior
# containing that student is partly a blend toward themselves, which damps the
# very correction the prior exists to make. null_pool.build_impostor_stats
# already excludes claimed_student_id for the same reason. Tenant-scoping made
# this sharper — in a small same-tenant pool the student can be a large
# fraction of "their own" prior.
#
# Both floors are re-checked against what REMAINS after the exclusion.


class TestGetGenreStatsSelfExclusion:
    def test_scored_students_own_samples_are_excluded(self, repo):
        # 4 students x 2 = 8 vectors. Excluding one leaves 6 across 3 students.
        for i in range(4):
            repo.put(_make_state(f"student-SX{i}", n=2, genre="sermon"))
        result = repo.get_genre_stats("sermon", None, "student-SX0")
        assert result is not None
        assert result["n_samples"] == 6

    def test_exclude_none_pools_everyone(self, repo):
        for i in range(4):
            repo.put(_make_state(f"student-SY{i}", n=2, genre="sermon"))
        result = repo.get_genre_stats("sermon", None, None)
        assert result is not None
        assert result["n_samples"] == 8

    def test_exclusion_can_drop_the_pool_below_the_vector_floor(self, repo):
        # 3 students x 2 = 6 vectors; removing one leaves 4 < MIN_GENRE_VECTORS.
        for i in range(3):
            repo.put(_make_state(f"student-SZ{i}", n=2, genre="exegesis"))
        assert repo.get_genre_stats("exegesis", None, None) is not None
        assert repo.get_genre_stats("exegesis", None, "student-SZ0") is None

    def test_exclusion_can_drop_the_pool_below_the_student_floor(self, repo):
        # 2 peers x 3 = 6 vectors, plus the scored student's 1 = 7 across 3
        # students. Excluding the scored student leaves 6 vectors (clears the
        # vector floor) but only 2 students — so the STUDENT floor is what
        # rejects it. Isolates that floor from the vector floor.
        repo.put(_make_state("student-TA0", n=3, genre="homiletics"))
        repo.put(_make_state("student-TA1", n=3, genre="homiletics"))
        repo.put(_make_state("student-TA2", n=1, genre="homiletics"))
        assert repo.get_genre_stats("homiletics", None, None) is not None
        assert repo.get_genre_stats("homiletics", None, "student-TA2") is None

    def test_a_prolific_student_cannot_drag_their_own_prior(self, repo):
        # The statistical point of the change: student-TB0's 20 samples must
        # not shape the distribution TB0 is then scored against.
        repo.put(_make_state("student-TB0", n=20, genre="canon_law"))
        for i in range(1, 4):
            repo.put(_make_state(f"student-TB{i}", n=2, genre="canon_law"))
        with_self = repo.get_genre_stats("canon_law", None, None)
        without_self = repo.get_genre_stats("canon_law", None, "student-TB0")
        assert with_self is not None and without_self is not None
        assert with_self["n_samples"] == 26
        assert without_self["n_samples"] == 6
        # The excluded pool is a genuinely different distribution, not the
        # same numbers with a smaller count.
        assert not np.allclose(with_self["mean"], without_self["mean"])

    def test_cache_is_keyed_per_excluded_student(self, repo):
        # A cache keyed only on (tenant, genre) would serve the first
        # caller's pool to the next student asking — handing a student a
        # prior that still contains their own writing.
        for i in range(4):
            repo.put(_make_state(f"student-TC{i}", n=2, genre="rhetoric"))
        a = repo.get_genre_stats("rhetoric", None, "student-TC0")
        b = repo.get_genre_stats("rhetoric", None, "student-TC1")
        full = repo.get_genre_stats("rhetoric", None, None)
        assert a is not None and b is not None and full is not None
        assert full["n_samples"] == 8
        assert a["n_samples"] == b["n_samples"] == 6
        assert not np.allclose(a["mean"], b["mean"])
        # ... and again now that all three keys are warm.
        assert repo.get_genre_stats("rhetoric", None, "student-TC0")["n_samples"] == 6
        assert repo.get_genre_stats("rhetoric", None, None)["n_samples"] == 8

    def test_excluding_an_unknown_student_is_a_no_op(self, repo):
        for i in range(3):
            repo.put(_make_state(f"student-TD{i}", n=2, genre="sermon"))
        assert repo.get_genre_stats("sermon", None, "nobody")["n_samples"] == 6

    def test_exclusion_is_scoped_to_the_tenant_too(self, repo):
        # A same-local-name student in another tenant must be unaffected —
        # exclusion matches the full scoped id, not a bare local name.
        for i in range(4):
            repo.put(_make_state(f"seminary-a:student-{i}", n=2, genre="sermon"))
        for i in range(4):
            repo.put(_make_state(f"seminary-b:student-{i}", n=2, genre="sermon"))
        a = repo.get_genre_stats("sermon", "seminary-a", "seminary-a:student-0")
        b = repo.get_genre_stats("sermon", "seminary-b", "seminary-a:student-0")
        assert a is not None and b is not None
        assert a["n_samples"] == 6  # one of its own removed
        assert b["n_samples"] == 8  # untouched: different tenant


# ── get_genre_stats tenant isolation ─────────────────────────────────────────
#
# get_genre_stats takes a required `tenant` argument and scopes the
# aggregation to it — mirroring null_pool.py's build_impostor_stats, which
# resolves tenant_of(claimed_student_id) and pools only same-tenant peers,
# never cross-tenant (FERPA isolation, the same rule as every other
# tenant-scoped read in this codebase). tenant=None is the legacy-flat pool
# (ids with no ":"), which is its own distinct cohort — never merged into a
# real tenant's, and never fed by one.


class TestGetGenreStatsTenantIsolation:
    def test_other_tenants_samples_never_pooled(self, repo):
        # 6 authenticated "sermon" samples at seminary-a, zero at seminary-b.
        # seminary-b must see no prior at all — not a prior built from
        # seminary-a's students.
        for i in range(6):
            repo.put(_make_state(f"seminary-a:student-{i}", n=1, genre="sermon"))
        assert repo.get_genre_stats("sermon", "seminary-a", None) is not None
        assert repo.get_genre_stats("sermon", "seminary-b", None) is None

    def test_pools_are_disjoint_across_tenants(self, repo):
        # Each tenant clears the vector floor on its own. Neither tenant's
        # n_samples may include the other's.
        for i in range(6):
            repo.put(_make_state(f"seminary-a:student-{i}", n=1, genre="exegesis"))
        for i in range(7):
            repo.put(_make_state(f"seminary-b:student-{i}", n=1, genre="exegesis"))
        a = repo.get_genre_stats("exegesis", "seminary-a", None)
        b = repo.get_genre_stats("exegesis", "seminary-b", None)
        assert a is not None and b is not None
        assert a["n_samples"] == 6
        assert b["n_samples"] == 7
        assert not np.allclose(a["mean"], b["mean"])

    def test_cross_tenant_samples_do_not_lift_a_tenant_over_the_floor(self, repo):
        # THE regression this whole change exists to prevent: 4 samples at
        # seminary-a (below the floor of 5) plus 4 at seminary-b must NOT
        # combine into an 8-sample prior for either tenant.
        for i in range(4):
            repo.put(_make_state(f"seminary-a:student-{i}", n=1, genre="lab_report"))
        for i in range(4):
            repo.put(_make_state(f"seminary-b:student-{i}", n=1, genre="lab_report"))
        assert repo.get_genre_stats("lab_report", "seminary-a", None) is None
        assert repo.get_genre_stats("lab_report", "seminary-b", None) is None

    def test_legacy_flat_pool_is_separate_from_scoped_tenants(self, repo):
        # Colon-less (legacy-flat) ids are tenant_of(...) -> None. They form
        # their own cohort and must not feed a real tenant's prior.
        for i in range(6):
            repo.put(_make_state(f"legacy-student-{i}", n=1, genre="theology_paper"))
        assert repo.get_genre_stats("theology_paper", None, None) is not None
        assert repo.get_genre_stats("theology_paper", "seminary-a", None) is None

    def test_scoped_tenant_does_not_feed_the_legacy_flat_pool(self, repo):
        # The converse of the above — the sentinel must not act as a wildcard.
        for i in range(6):
            repo.put(_make_state(f"seminary-a:student-{i}", n=1, genre="rhetoric"))
        assert repo.get_genre_stats("rhetoric", None, None) is None

    def test_cache_is_keyed_per_tenant(self, repo):
        # A cache keyed on genre alone would serve seminary-a's stats to
        # seminary-b on the second call — the leak surviving the filter.
        for i in range(6):
            repo.put(_make_state(f"seminary-a:student-{i}", n=1, genre="homiletics"))
        assert repo.get_genre_stats("homiletics", "seminary-a", None) is not None
        assert repo.get_genre_stats("homiletics", "seminary-b", None) is None
        # ... and again, now that both keys are warm.
        assert repo.get_genre_stats("homiletics", "seminary-a", None) is not None
        assert repo.get_genre_stats("homiletics", "seminary-b", None) is None


# ── get_cohort_stats ─────────────────────────────────────────────────────────
#
# get_genre_stats's genre-agnostic sibling (COHORT_PRIOR_FALLBACK): the SAME
# pool scan and the SAME genre_stats_from_groups arithmetic with the genre
# filter dropped. It therefore takes the same (tenant, exclude_student_id)
# pair and inherits — rather than re-states — tenant isolation, the
# leave-one-out exclusion, both cold-start floors, and n_students. The
# classes below assert that inheritance holds on every backend: a
# hand-rolled second aggregation that quietly skipped any of them is exactly
# the regression this file exists to catch.
#
# Every _make_state id here is unscoped/legacy-flat (no ":"), so tenant_of()
# is None for all of them — hence `get_cohort_stats(None, ...)`; see
# TestGetCohortStatsTenantIsolation for the scoped-id case.


class TestGetCohortStats:
    def test_returns_none_with_no_students(self, repo):
        assert repo.get_cohort_stats(None, None) is None

    def test_returns_none_below_student_floor(self, repo):
        # 2 contributing students, 6 vectors total — still None: student
        # floor (3) not met even though the vector floor (5) is.
        repo.put(_make_state("student-N0", n=3, genre="argumentative_essay"))
        repo.put(_make_state("student-N1", n=3, genre="lab_report"))
        assert repo.get_cohort_stats(None, None) is None

    def test_returns_none_below_vector_floor(self, repo):
        # 3 contributing students but only 3 vectors total — below the
        # vector floor (5) even though the student floor (3) is met.
        repo.put(_make_state("student-O0", n=1, genre="argumentative_essay"))
        repo.put(_make_state("student-O1", n=1, genre="lab_report"))
        repo.put(_make_state("student-O2", n=1, genre=None))
        assert repo.get_cohort_stats(None, None) is None

    def test_returns_stats_with_enough_students_and_vectors(self, repo):
        repo.put(_make_state("student-P0", n=2, genre="argumentative_essay"))
        repo.put(_make_state("student-P1", n=2, genre="lab_report"))
        repo.put(_make_state("student-P2", n=2, genre=None))
        result = repo.get_cohort_stats(None, None)
        assert result is not None
        assert result["n_samples"] == 6
        assert result["mean"].shape == (FEATURE_DIM,)
        assert result["std"].shape == (FEATURE_DIM,)

    def test_reports_n_students_for_the_blend_damping(self, repo):
        # scoring.score() damps the prior's blend weight by n_students. A
        # cohort dict without it would silently take the UNDAMPED path — i.e.
        # a genre-MISmatched fallback prior would be trusted more than the
        # genre-matched prior it stands in for. Exactly backwards.
        for i in range(4):
            repo.put(_make_state(f"student-PN{i}", n=2, genre="a"))
        result = repo.get_cohort_stats(None, None)
        assert result is not None
        assert result["n_students"] == 4

    def test_genre_is_not_filtered(self, repo):
        # Mixed genres (including None) all count toward the cohort — this
        # is exactly what distinguishes get_cohort_stats from get_genre_stats.
        repo.put(_make_state("student-Q0", n=2, genre="sermon"))
        repo.put(_make_state("student-Q1", n=2, genre="exegesis"))
        repo.put(_make_state("student-Q2", n=2, genre=None))
        result = repo.get_cohort_stats(None, None)
        assert result is not None
        assert result["n_samples"] == 6

    def test_cohort_pool_is_not_the_genre_pool(self, repo):
        # Same students, all in DIFFERENT genres: no single genre clears the
        # floors, but the cohort — which ignores genre — does. This is the
        # whole point of the fallback, and it also proves the two share a
        # cache without colliding (genre=None is its own key).
        for i, genre in enumerate(["sermon", "exegesis", "homiletics"]):
            repo.put(_make_state(f"student-QC{i}", n=2, genre=genre))
        assert repo.get_genre_stats("sermon", None, None) is None
        assert repo.get_genre_stats("exegesis", None, None) is None
        cohort = repo.get_cohort_stats(None, None)
        assert cohort is not None
        assert cohort["n_samples"] == 6

    def test_std_floored_at_005(self, repo):
        repo.put(_make_state("student-R0", n=2, genre="a"))
        repo.put(_make_state("student-R1", n=2, genre="b"))
        repo.put(_make_state("student-R2", n=2, genre="c"))
        result = repo.get_cohort_stats(None, None)
        assert result is not None
        assert float(np.min(result["std"])) >= 0.005

    def test_cache_busted_after_put(self, repo):
        repo.put(_make_state("student-T0", n=2, genre="a"))
        repo.put(_make_state("student-T1", n=2, genre="b"))
        repo.put(_make_state("student-T2", n=2, genre="c"))
        r1 = repo.get_cohort_stats(None, None)
        assert r1 is not None
        repo.put(_make_state("student-T3", n=1, genre="d"))
        r2 = repo.get_cohort_stats(None, None)
        assert r2 is not None
        assert r2["n_samples"] == 7

    def test_unverified_samples_never_pooled(self, repo):
        # student-U0 has only an unverified (auth_weight=0) sample — it must
        # not count as a contributing student, nor its vector toward n_samples.
        state = StudentState(student_id="student-U0")
        state.add_sample(
            BaselineSample(
                text="unverified",
                vector=np.random.default_rng(1).random(FEATURE_DIM).astype(np.float64),
                provenance="unverified",
                auth_weight=0.0,
                genre="a",
            )
        )
        repo.put(state)
        repo.put(_make_state("student-U1", n=2, genre="b"))
        repo.put(_make_state("student-U2", n=2, genre="c"))
        repo.put(_make_state("student-U3", n=2, genre="d"))
        result = repo.get_cohort_stats(None, None)
        assert result is not None
        assert result["n_samples"] == 6  # 2+2+2 authenticated only; U0's sample excluded


class TestGetCohortStatsSelfExclusion:
    """Leave-one-out matters MORE for the cohort prior than for the genre
    prior, not less: a tenant-wide pool in a small tenant is precisely where
    one student is a large fraction of "their own" population statistic."""

    def test_scored_students_own_samples_are_excluded(self, repo):
        for i in range(4):
            repo.put(_make_state(f"student-CX{i}", n=2, genre="a"))
        result = repo.get_cohort_stats(None, "student-CX0")
        assert result is not None
        assert result["n_samples"] == 6
        assert result["n_students"] == 3

    def test_a_prolific_student_cannot_drag_their_own_cohort_prior(self, repo):
        repo.put(_make_state("student-CY0", n=20, genre="a"))
        for i in range(1, 4):
            repo.put(_make_state(f"student-CY{i}", n=2, genre="b"))
        with_self = repo.get_cohort_stats(None, None)
        without_self = repo.get_cohort_stats(None, "student-CY0")
        assert with_self is not None and without_self is not None
        assert with_self["n_samples"] == 26
        assert without_self["n_samples"] == 6
        assert not np.allclose(with_self["mean"], without_self["mean"])

    def test_exclusion_can_drop_the_pool_below_a_floor(self, repo):
        # 3 students x 2 = 6 vectors; removing one leaves 4 < the vector floor.
        for i in range(3):
            repo.put(_make_state(f"student-CZ{i}", n=2, genre="a"))
        assert repo.get_cohort_stats(None, None) is not None
        assert repo.get_cohort_stats(None, "student-CZ0") is None

    def test_cache_is_keyed_per_excluded_student(self, repo):
        # A pool cached without regard to the exclusion would hand the next
        # student a prior that still contains their own writing.
        for i in range(4):
            repo.put(_make_state(f"student-CC{i}", n=2, genre="a"))
        a = repo.get_cohort_stats(None, "student-CC0")
        b = repo.get_cohort_stats(None, "student-CC1")
        full = repo.get_cohort_stats(None, None)
        assert a is not None and b is not None and full is not None
        assert full["n_samples"] == 8
        assert a["n_samples"] == b["n_samples"] == 6
        assert not np.allclose(a["mean"], b["mean"])
        # ... and again now that all three keys are warm.
        assert repo.get_cohort_stats(None, "student-CC0")["n_samples"] == 6
        assert repo.get_cohort_stats(None, None)["n_samples"] == 8


class TestGetCohortStatsTenantIsolation:
    """The core regression this contract must hold on every backend: a
    student in tenant B must never contribute to tenant A's cohort prior.
    Mirrors null_pool.py's test_pool_excludes_claimed_student_and_other_tenants
    (tests/test_null_model.py) for the sibling tenant-scoping guarantee."""

    def test_other_tenant_students_excluded(self, repo):
        for i in range(3):
            repo.put(_make_state(f"tenantA:student{i}", n=2, genre="a"))
        for i in range(3):
            repo.put(_make_state(f"tenantB:student{i}", n=2, genre="b"))

        result_a = repo.get_cohort_stats("tenantA", None)
        assert result_a is not None
        assert result_a["n_samples"] == 6  # only tenant A's 3×2 vectors

        result_b = repo.get_cohort_stats("tenantB", None)
        assert result_b is not None
        assert result_b["n_samples"] == 6  # only tenant B's 3×2 vectors

    def test_below_floor_in_isolation_even_if_global_pool_is_not(self, repo):
        # Enough students/vectors GLOBALLY to clear both floors, but only 1
        # in tenant A — must still be None for tenant A specifically.
        repo.put(_make_state("tenantA:solo", n=2, genre="a"))
        for i in range(3):
            repo.put(_make_state(f"tenantB:student{i}", n=2, genre="b"))

        assert repo.get_cohort_stats("tenantA", None) is None
        assert repo.get_cohort_stats("tenantB", None) is not None

    def test_legacy_flat_and_real_tenant_are_distinct_pools(self, repo):
        # An unscoped (legacy-flat) id's tenant_of() is None — a real
        # tenant's cohort must not absorb it, and vice versa.
        for i in range(3):
            repo.put(_make_state(f"flat-student-{i}", n=2, genre="a"))
        for i in range(3):
            repo.put(_make_state(f"tenantC:student{i}", n=2, genre="b"))

        flat_result = repo.get_cohort_stats(None, None)
        assert flat_result is not None
        assert flat_result["n_samples"] == 6

        tenant_result = repo.get_cohort_stats("tenantC", None)
        assert tenant_result is not None
        assert tenant_result["n_samples"] == 6

    def test_exclusion_is_scoped_to_the_tenant_too(self, repo):
        # Exclusion matches the full scoped id, not a bare local name.
        for i in range(4):
            repo.put(_make_state(f"tenantD:student{i}", n=2, genre="a"))
        for i in range(4):
            repo.put(_make_state(f"tenantE:student{i}", n=2, genre="a"))
        d = repo.get_cohort_stats("tenantD", "tenantD:student0")
        e = repo.get_cohort_stats("tenantE", "tenantD:student0")
        assert d is not None and e is not None
        assert d["n_samples"] == 6  # one of its own removed
        assert e["n_samples"] == 8  # untouched: different tenant


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

    def test_genre_stats_cache_busted_after_delete(self, repo):
        # Regression for a Postgres-only divergence: delete_student() must
        # clear the genre-stats cache like store.py's does, or an erased
        # student's vectors keep contributing to their tenant's warm
        # Bayesian-prior pool until an unrelated put() or process restart.
        # Public-interface only (no _genre_stats_cache / _GENRE_STATS_CACHE
        # reach-in) so this runs against both backends — see
        # tests/test_store_fidelity.py for the SQLite-internals version this
        # supplements.
        for i in range(5):  # exactly the floor, so one deletion drops it out
            repo.put(_make_state(f"tenant-del:student-{i}", n=1, genre="lab_report"))
        warm = repo.get_genre_stats("lab_report", "tenant-del", None)
        assert warm is not None
        assert warm["n_samples"] == 5

        assert repo.delete_student("tenant-del:student-0") is True

        after = repo.get_genre_stats("lab_report", "tenant-del", None)
        assert after is None  # below the floor once the deleted student's vector is gone


# ── Student state basics (get/get_or_create/put/list_ids/all_states/count) ───
# WS-6 P3: these were previously only exercised indirectly by the classes
# above; added explicitly so the get_or_create "doesn't persist until put()"
# contract (shared by both backends — see PostgresRepository.get_or_create's
# docstring) has a direct assertion.


class TestGetOrCreateAndBasics:
    def test_get_unknown_returns_none(self, repo):
        assert repo.get("nobody-at-all") is None

    def test_get_or_create_then_get_sees_the_same_empty_state(self, repo):
        # Both backends persist the empty state at get_or_create() time
        # (WS-6 P6: no in-memory cache on either side), so a follow-up
        # get() — from this process or any other worker — sees the
        # just-created empty state immediately.
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


class TestDensityMatrixRoundtrip:
    """WS-6 P3's own named acceptance bar: "Property-test the round-trip:
    fidelity(rho_in, rho_out) ~= 1.0 for random density matrices through the
    Postgres path" -- the model docstring in db/models/live.py calls this
    "the highest-stakes round-trip" (BYTEA/JSONB must reproduce numpy bytes
    exactly). Genuine Hypothesis property test, parametrized over both
    backends (see tests/test_quantum.py for the project's other `@given`
    property and its conventions, matched here)."""

    @staticmethod
    def _sqrt_psd(rho: np.ndarray) -> np.ndarray:
        """Matrix square root of a real symmetric PSD matrix via
        eigendecomposition. scipy.linalg.sqrtm's general Schur-based
        algorithm is not built for this case -- CI hit both a hard
        `LinAlgError: Internal error in scipy.linalg.sqrtm: -102` and a
        silent NaN result on rank-1 rho (a single-sample state's density
        matrix is legitimately rank-1 -- a pure state, not a bug). ``rho``
        here is always real and symmetric by construction, so eigh (which
        exploits that structure) is both the numerically correct tool and
        immune to the failure mode: negative eigenvalues (floating-point
        noise on a true PSD matrix, never a real negative eigenvalue) are
        clipped to zero before the square root, so degenerate/near-singular
        rho can never produce NaN or raise.
        """
        eigenvalues, eigenvectors = np.linalg.eigh(rho)
        sqrt_eigenvalues = np.sqrt(np.clip(eigenvalues, 0.0, None))
        return eigenvectors @ np.diag(sqrt_eigenvalues) @ eigenvectors.T

    @classmethod
    def _fidelity(cls, rho_a: np.ndarray, rho_b: np.ndarray) -> float:
        """Uhlmann fidelity F(rho, sigma) = [tr(sqrt(sqrt(rho) sigma sqrt(rho)))]^2
        for two density matrices. 1.0 iff rho_a == rho_b (up to floating
        point); this is the literal metric the P3 acceptance bar names."""
        sqrt_a = cls._sqrt_psd(rho_a)
        inner = sqrt_a @ rho_b @ sqrt_a
        sqrt_inner = cls._sqrt_psd(inner)
        return float(np.clip(np.trace(sqrt_inner) ** 2, 0.0, 1.0))

    # deadline=None: a Postgres round-trip per example is a real network
    # round-trip, not just numpy math -- a wall-clock deadline here would
    # flake on slower CI runners for reasons unrelated to the invariant.
    # Each example writes a distinct student_id (case_id-suffixed), so
    # sharing the function-scoped `repo` fixture across examples is safe
    # (no cross-example state leakage) -- suppressing Hypothesis's default
    # health check for that pattern deliberately.
    @settings(
        deadline=None, max_examples=15, suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    @given(
        vectors=st.lists(
            st.lists(
                st.floats(min_value=1e-3, max_value=1.0, allow_nan=False, allow_infinity=False),
                min_size=FEATURE_DIM,
                max_size=FEATURE_DIM,
            ),
            min_size=1,
            max_size=5,
        ),
        case_id=st.integers(min_value=0, max_value=1_000_000),
    )
    def test_density_matrix_survives_roundtrip(self, repo, vectors, case_id):
        student_id = f"sem:dm-roundtrip-{case_id}"
        state = StudentState(student_id=student_id)
        for i, v in enumerate(vectors):
            state.add_sample(
                BaselineSample(
                    text="",
                    vector=np.array(v, dtype=np.float64),
                    provenance="proctored",
                    auth_weight=1.0,
                    assignment=f"A{i}",
                )
            )
        rho_in = state.density_matrix.copy()

        repo.put(state)
        retrieved = repo.get(student_id)
        assert retrieved is not None
        rho_out = retrieved.density_matrix

        assert np.allclose(
            rho_in, rho_out, atol=1e-9
        ), "rho drifted across the repository round-trip"
        fidelity = self._fidelity(rho_in, rho_out)
        assert abs(fidelity - 1.0) < 1e-6, f"round-trip fidelity {fidelity} != 1.0"


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
        repo.log_audit(
            action="score", student_id="sem:carol", details={"submission_id": "sub-noManifest"}
        )
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
        repo.put_manifest(
            "sub-l1", "sem:dave", {"created_at": "2026-01-01T00:00:00Z"}, action="no_action"
        )
        repo.put_manifest(
            "sub-l2", "sem:erin", {"created_at": "2026-01-02T00:00:00Z"}, action="monitor"
        )
        result = repo.list_manifests(student_id="sem:dave")
        assert result["total"] == 1
        assert result["items"][0]["submission_id"] == "sub-l1"

    def test_list_manifests_filters_by_action(self, repo):
        repo.put_manifest(
            "sub-l3", "sem:frank", {"created_at": "2026-01-01T00:00:00Z"}, action="escalate"
        )
        result = repo.list_manifests(action="escalate")
        assert result["total"] >= 1
        assert all(i["action"] == "escalate" for i in result["items"])

    def test_list_manifests_filters_by_flag(self, repo):
        repo.put_manifest(
            "sub-l4",
            "sem:gwen",
            {"created_at": "2026-01-01T00:00:00Z", "flags": ["outlier"]},
            action="monitor",
        )
        repo.put_manifest(
            "sub-l5",
            "sem:hank",
            {"created_at": "2026-01-01T00:00:00Z", "flags": []},
            action="monitor",
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
            "sub-c2",
            "sem:bob",
            {"created_at": "2026-01-01T00:00:00Z"},
            divergence_score=0.6,
            action="escalate",
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
        assert (
            repo.complete_calibration_run(
                999999, auc=0.5, n_essays_scored=1, n_authors=1, report={}
            )
            is True
        )

    def test_list_calibration_runs_filters_by_status(self, repo):
        repo.start_calibration_run("dataset-C")
        r2 = repo.start_calibration_run("dataset-C")
        result = repo.list_calibration_runs(status="running")
        assert any(item["id"] == r2 for item in result["items"])
        assert all(item["status"] == "running" for item in result["items"])

    def test_get_calibration_run_include_report_false_omits_report(self, repo):
        run_id = repo.start_calibration_run("dataset-D")
        repo.complete_calibration_run(
            run_id, auc=0.5, n_essays_scored=1, n_authors=1, report={"x": 1}
        )
        run = repo.get_calibration_run(run_id, include_report=False)
        assert "report" not in run


# ── Tuned thresholds ──────────────────────────────────────────────────────


class TestTunedThresholds:
    def test_put_and_get_active(self, repo):
        repo.put_tuned_thresholds(no_action=0.1, monitor=0.4, escalate=0.7, source="manual")
        tid = repo.put_tuned_thresholds(
            no_action=0.15, monitor=0.45, escalate=0.75, source="calibration_run"
        )
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
            {
                "id": "exam-A",
                "tenant_id": "sem",
                "title": "Final",
                "course": "THEO101",
                "minWords": 300,
                "maxWords": 900,
            }
        )
        exam = repo.get_bluebook_exam("exam-A")
        assert exam["title"] == "Final"
        assert exam["tenant_id"] == "sem"
        assert exam["minWords"] == 300
        listed = repo.list_bluebook_exams("sem")
        assert any(e["id"] == "exam-A" for e in listed)

    def test_exam_upsert(self, repo):
        repo.put_bluebook_exam({"id": "exam-B", "tenant_id": "sem", "title": "Draft"})
        repo.put_bluebook_exam(
            {"id": "exam-B", "tenant_id": "sem", "title": "Final", "status": "PUBLISHED"}
        )
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
        repo.put_bluebook_course(
            {"id": "course-A", "tenant_id": "sem", "name": "Theology 101", "code": "THEO101"}
        )
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
        repo.put_user(
            "user-A", "Prof.X@Example.com", "hashed-pw", "professor", "sem", name="Prof X"
        )
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
        repo.put_manifest(
            "sub-f2", "sem:carol", {"created_at": "2026-01-01T00:00:00Z"}, action="escalate"
        )
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
        repo.put_baseline_request(
            "req-A", "sem:alice", "pending", 1000.0, json.dumps({"foo": "bar"})
        )
        loaded = repo.load_baseline_requests()
        assert any(d.get("foo") == "bar" for d in loaded)

    def test_upsert_keeps_one_row_per_request_id(self, repo):
        repo.put_baseline_request(
            "req-B", "sem:bob", "pending", 1000.0, json.dumps({"tag": "req-B", "status": "pending"})
        )
        repo.put_baseline_request(
            "req-B",
            "sem:bob",
            "completed",
            1000.0,
            json.dumps({"tag": "req-B", "status": "completed"}),
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


# ── QR phone-park (proctoring deterrence) ─────────────────────────────────


class TestPhonePark:
    """The T8 phone-park surface, against both backends.

    Every timestamp is passed in explicitly rather than read from the wall
    clock, so the TTL/staleness behaviour is exercised deterministically —
    no test here sleeps.
    """

    T0 = datetime(2026, 7, 20, 9, 0, 0, tzinfo=UTC)

    def test_open_then_get_by_token_and_by_exam(self, repo):
        repo.park_open("exam-1", "sem-dallas", "tok-1", self.T0)

        by_token = repo.park_get_session("tok-1")
        by_exam = repo.park_get_session_by_exam("exam-1")
        assert by_token == by_exam
        assert by_token["exam_session_id"] == "exam-1"
        assert by_token["tenant_id"] == "sem-dallas"
        assert by_token["park_token"] == "tok-1"
        # Both backends must agree on the timestamp shape, not just the value.
        assert by_token["created_at"] == "2026-07-20T09:00:00.000000+00:00"

    def test_unknown_lookups_return_none(self, repo):
        assert repo.park_get_session("no-such-token") is None
        assert repo.park_get_session_by_exam("no-such-exam") is None

    def test_reopen_same_exam_keeps_one_row(self, repo):
        repo.park_open("exam-2", "sem-dallas", "tok-2", self.T0)
        repo.park_open("exam-2", "sem-dallas", "tok-2", self.T0)
        assert repo.park_get_session_by_exam("exam-2")["park_token"] == "tok-2"

    def test_rotating_the_token_drops_the_old_tokens_beats(self, repo):
        """An expired session's phones must not haunt the new one's tiles."""
        repo.park_open("exam-3", "sem-dallas", "old-tok", self.T0)
        repo.park_beat("old-tok", "AB", "parked", self.T0)
        assert len(repo.park_tiles("exam-3")) == 1

        repo.park_open("exam-3", "sem-dallas", "new-tok", self.T0)
        assert repo.park_tiles("exam-3") == []
        assert repo.park_get_session("old-tok") is None

    def test_first_beat_creates_a_tile_with_one_transition(self, repo):
        repo.park_open("exam-4", "sem-dallas", "tok-4", self.T0)
        repo.park_beat("tok-4", "MR", "parked", self.T0)

        tiles = repo.park_tiles("exam-4")
        assert len(tiles) == 1
        assert tiles[0]["student_hint"] == "MR"
        assert tiles[0]["state"] == "parked"
        assert tiles[0]["transitions"] == [
            {"state": "parked", "at": "2026-07-20T09:00:00.000000+00:00"}
        ]

    def test_repeated_identical_beats_do_not_grow_the_transition_log(self, repo):
        """The whole point of the dedupe: a 10s heartbeat is not a log source."""
        repo.park_open("exam-5", "sem-dallas", "tok-5", self.T0)
        for i in range(10):
            repo.park_beat("tok-5", "JT", "parked", self.T0 + timedelta(seconds=10 * i))

        (tile,) = repo.park_tiles("exam-5")
        assert len(tile["transitions"]) == 1
        # …but liveness still advanced.
        assert tile["last_seen_at"] == "2026-07-20T09:01:30.000000+00:00"

    def test_state_change_appends_a_transition(self, repo):
        repo.park_open("exam-6", "sem-dallas", "tok-6", self.T0)
        repo.park_beat("tok-6", "KL", "parked", self.T0)
        repo.park_beat("tok-6", "KL", "foreground_lost", self.T0 + timedelta(seconds=10))
        repo.park_beat("tok-6", "KL", "foreground_lost", self.T0 + timedelta(seconds=20))
        repo.park_beat("tok-6", "KL", "resumed", self.T0 + timedelta(seconds=30))

        (tile,) = repo.park_tiles("exam-6")
        assert [t["state"] for t in tile["transitions"]] == [
            "parked",
            "foreground_lost",
            "resumed",
        ]
        assert tile["state"] == "resumed"

    def test_beats_are_keyed_by_token_and_hint(self, repo):
        repo.park_open("exam-7", "sem-dallas", "tok-7", self.T0)
        repo.park_beat("tok-7", "AA", "parked", self.T0)
        repo.park_beat("tok-7", "BB", "parked", self.T0 + timedelta(seconds=1))

        tiles = repo.park_tiles("exam-7")
        assert [t["student_hint"] for t in tiles] == ["AA", "BB"]

    def test_transition_log_is_bounded(self, repo):
        """Anonymous input must not be able to grow one row without limit."""
        from original.store import PARK_MAX_TRANSITIONS

        repo.park_open("exam-8", "sem-dallas", "tok-8", self.T0)
        flips = PARK_MAX_TRANSITIONS + 25
        for i in range(flips):
            state = "parked" if i % 2 == 0 else "foreground_lost"
            repo.park_beat("tok-8", "ZZ", state, self.T0 + timedelta(seconds=i))

        (tile,) = repo.park_tiles("exam-8")
        assert len(tile["transitions"]) == PARK_MAX_TRANSITIONS

    def test_tiles_for_unknown_session_is_empty(self, repo):
        assert repo.park_tiles("never-opened") == []

    def test_delete_removes_session_and_beats(self, repo):
        repo.park_open("exam-9", "sem-dallas", "tok-9", self.T0)
        repo.park_beat("tok-9", "AA", "parked", self.T0)
        repo.park_beat("tok-9", "BB", "parked", self.T0)

        # 2 beats + 1 session row.
        assert repo.park_delete("exam-9") == 3
        assert repo.park_get_session_by_exam("exam-9") is None
        assert repo.park_tiles("exam-9") == []

    def test_delete_unknown_session_is_zero(self, repo):
        assert repo.park_delete("never-opened") == 0

    def test_purge_removes_only_rows_older_than_the_cutoff(self, repo):
        repo.park_open("exam-old", "sem-dallas", "tok-old", self.T0)
        repo.park_beat("tok-old", "AA", "parked", self.T0)
        repo.park_open("exam-new", "sem-dallas", "tok-new", self.T0 + timedelta(hours=25))

        # 24h retention, evaluated one hour after the newer session opened.
        cutoff = self.T0 + timedelta(hours=26) - timedelta(hours=24)
        assert repo.park_purge(cutoff) == 2  # 1 beat + 1 session

        assert repo.park_get_session_by_exam("exam-old") is None
        assert repo.park_get_session_by_exam("exam-new") is not None

    def test_purge_with_nothing_to_do_is_zero(self, repo):
        repo.park_open("exam-fresh", "sem-dallas", "tok-fresh", self.T0)
        assert repo.park_purge(self.T0 - timedelta(days=1)) == 0
        assert repo.park_get_session_by_exam("exam-fresh") is not None

    def test_naive_datetimes_are_treated_as_utc(self, repo):
        """A naive timestamp must not be silently shifted by the server's offset."""
        repo.park_open("exam-naive", "sem-dallas", "tok-naive", datetime(2026, 7, 20, 9, 0, 0))
        assert (
            repo.park_get_session("tok-naive")["created_at"] == "2026-07-20T09:00:00.000000+00:00"
        )

    def test_stores_no_identifying_columns(self, repo):
        """The privacy contract, asserted rather than merely documented.

        Whatever a park row round-trips, it is not an IP, a user-agent, a
        location, a device fingerprint, or a roster id — the columns simply do
        not exist. This guards against a future 'just add a column' change.
        """
        repo.park_open("exam-priv", "sem-dallas", "tok-priv", self.T0)
        repo.park_beat("tok-priv", "AB", "parked", self.T0)

        session_keys = set(repo.park_get_session("tok-priv"))
        tile_keys = set(repo.park_tiles("exam-priv")[0])
        assert session_keys == {"exam_session_id", "tenant_id", "park_token", "created_at"}
        assert tile_keys == {
            "student_hint",
            "state",
            "first_seen_at",
            "last_seen_at",
            "transitions",
        }
        forbidden = {"ip", "ip_address", "user_agent", "location", "device", "student_id", "email"}
        assert not (session_keys | tile_keys) & forbidden
