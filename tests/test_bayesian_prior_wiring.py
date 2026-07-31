"""
Bayesian genre-prior production wiring test (BAYESIAN_PRIOR_ENABLED).

original/routers/students_scoring.py:139 is the single place the tenant
argument to Repository.get_genre_stats(genre, tenant) is derived — from
tenant_of(student_id), i.e. the SCORED student's id, not (say) the
requesting principal's tenant. Before the tenant-scoping fix this call was
get_genre_stats(genre) (no tenant arg) and pooled every tenant's baseline
vectors together — a FERPA-relevant cross-institution leak. No test
anywhere exercised this call site with the flag on, so a future edit could
reintroduce the leak (e.g. by passing the principal's tenant instead of the
scored student's) with a fully green suite.

This test seeds a student's stored baseline directly via the repository
(bypassing the baseline endpoint's own best-effort genre auto-detection,
which can't be forced to a specific label through submitted text) so the
last stored sample carries a known genre and the student is still a cold
start (sample_count < 10) — the two conditions students_scoring.py checks
before calling get_genre_stats at all. It then spies on the live
repository's get_genre_stats (delegating to the real implementation, so the
scoring math still runs unmodified) and asserts the call reaching it
through the real HTTP endpoint carries the genre and the *scored student's*
tenant — not merely that some call happened.
"""

import logging

import numpy as np
import pytest
from fastapi.testclient import TestClient

import run  # repo-root launcher
from original import principal as pr
from original.constants import FEATURE_DIM
from original.principal import tenant_of
from original.quantum.state import BaselineSample, StudentState
from original.repository import get_repository

app = run.load_legacy_demo_app()
client = TestClient(app)


def _auth(token: str):
    return {"Authorization": f"Bearer {token}"}


def _seed_cold_start_student(student_id: str, genre: str, n: int = 3) -> None:
    """Directly persist a genre-labelled, sub-floor baseline for student_id.

    Goes through the repository, not the /baseline endpoint — genre labels
    are resolved best-effort from submitted text there, which can't be
    relied on to produce a specific label deterministically in a test.
    """
    rng = np.random.default_rng(abs(hash(student_id)) % (2**31))
    state = StudentState(student_id=student_id)
    for i in range(n):
        state.add_sample(
            BaselineSample(
                text=f"seed sample {i} for {student_id}",
                vector=rng.random(FEATURE_DIM).astype(np.float64),
                provenance="instructor_verified",
                auth_weight=1.0,
                assignment=f"a{i}",
                genre=genre,
            )
        )
    get_repository().put(state)


@pytest.fixture
def genre_tenant():
    """A fresh pilot tenant, and a professor token scoped to it."""
    client.post(
        "/tenants",
        json={"tenant_id": "genreprior", "name": "Genre Prior Seminary", "environment": "pilot"},
    )
    return pr.mint_principal_token("prof_genreprior", "professor", "genreprior")


def test_get_genre_stats_called_with_scored_students_tenant(genre_tenant, monkeypatch):
    monkeypatch.setenv("BAYESIAN_PRIOR_ENABLED", "1")

    sid = "genreprior:cold_start_student"
    genre = "lab_report"
    _seed_cold_start_student(sid, genre)

    repo = get_repository()
    real_get_genre_stats = repo.get_genre_stats
    calls = []

    def _spy(genre_arg, tenant_arg):
        calls.append((genre_arg, tenant_arg))
        return real_get_genre_stats(genre_arg, tenant_arg)

    monkeypatch.setattr(repo, "get_genre_stats", _spy)

    r = client.post(
        f"/students/{sid}/score",
        json={"text": "A short new submission for the cold-start scoring check."},
        headers=_auth(genre_tenant),
    )
    assert r.status_code == 200, r.text

    assert calls, "get_genre_stats was never called — the flag-on cold-start path did not run"
    # Assert on the tenant argument specifically: a regression that passes
    # the requesting principal's tenant (or None, or the wrong student's
    # tenant) instead of tenant_of(sid) must fail this even if some call
    # happens to reach get_genre_stats.
    assert calls[-1] == (genre, tenant_of(sid)) == (genre, "genreprior")


def test_get_genre_stats_uses_scored_students_tenant_not_principals_tenant(monkeypatch):
    """Regression guard for a divergence the tenant-fixture test above can't see.

    In test_get_genre_stats_called_with_scored_students_tenant, the requesting
    principal's tenant ("genreprior") and tenant_of(scored student id)
    ("genreprior") are the same string, so that test passes whether
    students_scoring.py:139 reads tenant_of(student_id) or
    principal.tenant_id — it can't discriminate the two implementations.

    Here they genuinely diverge: an anonymous demo principal always has
    tenant_id == "demo" (principal.py resolve_principal's fallback branch),
    but assert_student_access permits a demo principal to score a colon-less
    (legacy-flat) student id, for which tenant_of(student_id) is None. So a
    regression that passes principal.tenant_id instead of tenant_of(sid)
    would call get_genre_stats(genre, "demo") here, not (genre, None).
    """
    monkeypatch.setenv("BAYESIAN_PRIOR_ENABLED", "1")

    sid = "gap1_flat_cold_start_student"
    genre = "lab_report"
    _seed_cold_start_student(sid, genre)
    assert tenant_of(sid) is None  # colon-less id: no tenant prefix

    repo = get_repository()
    real_get_genre_stats = repo.get_genre_stats
    calls = []

    def _spy(genre_arg, tenant_arg):
        calls.append((genre_arg, tenant_arg))
        return real_get_genre_stats(genre_arg, tenant_arg)

    monkeypatch.setattr(repo, "get_genre_stats", _spy)

    # No Authorization header at all -> resolve_principal falls through to
    # the anonymous demo principal (tenant_id="demo", is_demo=True).
    r = client.post(
        f"/students/{sid}/score",
        json={"text": "A short new submission for the cold-start scoring check."},
    )
    assert r.status_code == 200, r.text

    assert calls, "get_genre_stats was never called — the flag-on cold-start path did not run"
    assert calls[-1] == (genre, None), (
        "get_genre_stats must be called with tenant_of(student_id) (None for a "
        "flat id), not the requesting principal's tenant_id ('demo')"
    )


def test_flag_off_never_calls_get_genre_stats(genre_tenant, monkeypatch):
    monkeypatch.delenv("BAYESIAN_PRIOR_ENABLED", raising=False)

    sid = "genreprior:flag_off_student"
    _seed_cold_start_student(sid, "lab_report")

    repo = get_repository()
    calls = []
    monkeypatch.setattr(
        repo, "get_genre_stats", lambda genre_arg, tenant_arg: calls.append((genre_arg, tenant_arg))
    )

    r = client.post(
        f"/students/{sid}/score",
        json={"text": "A short new submission with the flag off."},
        headers=_auth(genre_tenant),
    )
    assert r.status_code == 200, r.text
    assert calls == []


# ── Coverage measurement hook ────────────────────────────────────────────────
#
# The coverage cost of tenant-scoping the prior was never measured against
# real pilot data: scripts/measure_genre_prior_scope.py found no reachable
# dataset with genre-labelled authenticated samples (2026-07-29), and real
# pilot data lives in Postgres on Render. The INFO line these tests pin makes
# the first tenant to enable BAYESIAN_PRIOR_ENABLED measure it in situ —
# `outcome=miss` vs `outcome=hit` counts give the per-(tenant, genre) None
# rate that could not be computed ahead of time.
#
# It must log no student identifiers: tenant slug and genre label are not
# personal data, a student id is.


def test_prior_miss_is_logged_with_genre_and_tenant(genre_tenant, monkeypatch, caplog):
    """Below the 5-vector floor -> prior is None -> an INFO miss is recorded."""
    monkeypatch.setenv("BAYESIAN_PRIOR_ENABLED", "1")

    sid = "genreprior:miss_logging_student"
    genre = "canon_law"  # genre unique to this test: pool is only this student
    _seed_cold_start_student(sid, genre, n=3)  # 3 vectors < MIN_GENRE_VECTORS (5)

    caplog.set_level(logging.INFO, logger="original.routers.students_scoring")
    r = client.post(
        f"/students/{sid}/score",
        json={"text": "A short new submission below the genre-prior floor."},
        headers=_auth(genre_tenant),
    )
    assert r.status_code == 200, r.text

    hits = [m for m in caplog.messages if "bayesian_prior" in m]
    assert hits, "no bayesian_prior line was logged on the cold-start path"
    assert "outcome=miss" in hits[-1], hits[-1]
    assert f"genre={genre}" in hits[-1], hits[-1]
    assert "tenant=genreprior" in hits[-1], hits[-1]
    assert sid not in hits[-1], "the measurement line must not log student identifiers"


def test_prior_hit_is_logged_with_sample_count(genre_tenant, monkeypatch, caplog):
    """At/above the floor -> prior resolves -> an INFO hit records its size."""
    monkeypatch.setenv("BAYESIAN_PRIOR_ENABLED", "1")

    # Genre string unique to this test AND to this revision of it: this file
    # writes to the shared dev profiles.db without store_reset, so a genre
    # reused from an earlier revision would still carry that revision's
    # students and inflate the pool.
    genre = "homiletics_floor"
    # 3 peers x 2 vectors = 6, plus the scored student's own 3 = 9 across 4
    # students — clears MIN_GENRE_VECTORS (5) and MIN_GENRE_STUDENTS (3).
    for i in range(3):
        _seed_cold_start_student(f"genreprior:hit_logging_peer{i}", genre, n=2)
    sid = "genreprior:hit_logging_student"
    _seed_cold_start_student(sid, genre, n=3)

    caplog.set_level(logging.INFO, logger="original.routers.students_scoring")
    r = client.post(
        f"/students/{sid}/score",
        json={"text": "A short new submission above the genre-prior floor."},
        headers=_auth(genre_tenant),
    )
    assert r.status_code == 200, r.text

    hits = [m for m in caplog.messages if "bayesian_prior" in m]
    assert hits, "no bayesian_prior line was logged on the cold-start path"
    assert "outcome=hit" in hits[-1], hits[-1]
    # The logged size must be the pool the scorer actually used, not a
    # plausible-looking constant — derive it from the repository rather than
    # hardcoding, so leftover rows in the shared dev DB can't make this lie.
    live = get_repository().get_genre_stats(genre, "genreprior")
    assert live is not None
    assert live["n_samples"] >= 9  # the 9 this test seeded, at minimum
    assert f"n_prior={live['n_samples']}" in hits[-1], hits[-1]


def test_flag_off_logs_nothing(genre_tenant, monkeypatch, caplog):
    """The hook must not fire when the feature is off — no log noise by default."""
    monkeypatch.delenv("BAYESIAN_PRIOR_ENABLED", raising=False)

    sid = "genreprior:no_log_student"
    _seed_cold_start_student(sid, "lab_report")

    caplog.set_level(logging.INFO, logger="original.routers.students_scoring")
    r = client.post(
        f"/students/{sid}/score",
        json={"text": "A short new submission with the flag off."},
        headers=_auth(genre_tenant),
    )
    assert r.status_code == 200, r.text
    assert [m for m in caplog.messages if "bayesian_prior" in m] == []
