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
