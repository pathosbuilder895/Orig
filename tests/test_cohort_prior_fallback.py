"""
tests/test_cohort_prior_fallback.py — COHORT_PRIOR_FALLBACK.

Makes BAYESIAN_PRIOR_ENABLED usable at cold start: the router resolves
store.get_genre_stats(genre, tenant, exclude_student_id), which stays None
until enough same-genre, same-tenant, not-this-student data accumulates —
and, since the WS-7 tenant-scoping work, stays None considerably longer
than it used to. This flag adds a fallback to the genre-AGNOSTIC prior over
the same pool (store.get_cohort_stats(tenant, exclude_student_id)), which
fires only when BAYESIAN_PRIOR_ENABLED is on, the same-genre lookup came
back empty, and COHORT_PRIOR_FALLBACK=1 is set.

The fallback deliberately reuses the genre prior's own scan and arithmetic
with the genre filter dropped, so tenant isolation, the leave-one-out
exclusion, both cold-start floors and n_students are inherited rather than
re-implemented. The assertions here are about the ROUTER's branch decision
and the call shape it makes; the aggregation itself is asserted against
both backends in tests/test_repository_contract.py::TestGetCohortStats*.

Mirrors tests/test_null_model.py's split for the sibling feature living in
the same score_submission() function. Client/app setup (module-level
TestClient(run.load_legacy_demo_app())) and the tenant + professor-token +
POST /students/{id}/baseline fixture pattern are copied verbatim from
test_null_model.py's `cohort` fixture — the nearest existing router test
exercising this same function.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

import run  # repo-root launcher
from original import principal as pr
from original.constants import FEATURE_DIM
from original.principal import tenant_of
from original.repository import get_repository, reset_repository

app = run.load_legacy_demo_app()
client = TestClient(app)

# Real essay-length text so the rule-based genre resolver (resolve_genre,
# called unconditionally at baseline ingestion — original/routers/
# students_baseline.py) assigns a non-None primary genre. Content borrowed
# from test_null_model.py's BASE_TEXT for the same reason: realistic enough
# to classify, cheap enough to keep the suite fast.
BASE_TEXT = (
    "The doctrine of justification by faith stands at the center of the gospel. "
    "When Paul writes to the Romans, he labors to show that righteousness comes "
    "not by works of the law but through faith in Christ alone. This conviction "
    "shaped the Reformation and continues to shape pastoral practice today. "
    "A careful reader notices how the argument unfolds in stages, each building "
    "on the last, until the conclusion becomes unavoidable."
)

# n_students is part of the dict shape both priors now return — scoring.py
# damps the blend weight by it, and the router logs it. A fake prior without
# it would not exercise the same code path the real one does.
_FAKE_STATS = {
    "mean": np.zeros(FEATURE_DIM),
    "std": np.ones(FEATURE_DIM) * 0.1,
    "n_samples": 10,
    "n_students": 5,
}

# Deliberately a different subject/register than BASE_TEXT so resolve_genre
# classifies it into a different genre ("scholarly_essay" vs BASE_TEXT's
# "correspondence") — used only by the end-to-end tenant-isolation test, so
# seeding the "other tenant" doesn't also make get_genre_stats("correspondence")
# hit (which aggregates cross-tenant by design, unrelated to this fix) and
# mask what's actually being tested (get_cohort_stats's tenant scoping).
OTHER_TENANT_TEXT = (
    "Pursuant to Section 4.2 of the agreement, the parties hereby stipulate "
    "that all obligations shall be fulfilled within thirty days. See also "
    "Exhibit A, paragraph 3, as cited supra in note 12 of the record."
)


def _auth(token: str):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def cold_start_student(store_reset):
    """A single-sample student (sample_count < 10, the prior's cold-start
    gate) in a fresh pilot tenant — real genre metadata, no cross-student
    genre data, so store.get_genre_stats() and store.get_cohort_stats() are
    both guaranteed to come back None.

    Both aggregates are tenant-scoped, but this suite still needs a
    genuinely empty store, not just a fresh tenant id, because a fixed
    tenant id ("cohortfb") would
    otherwise accumulate samples of its own across repeated runs. Unlike
    test_null_model.py's module-scoped fixtures (which never call
    store_reset and so accumulate state across the whole pytest session —
    harmless there since none of its assertions depend on aggregate
    counts), this suite's assertions hinge on those two aggregates being
    exactly None at the cold start, which only an isolated on-disk SQLite
    file (tests/conftest.py's store_reset, also used by
    test_repository_contract.py's `repo` fixture) can guarantee.
    """
    reset_repository()
    tenant_id = "cohortfb"
    client.post(
        "/tenants",
        json={"tenant_id": tenant_id, "name": "Cohort Fallback Seminary", "environment": "pilot"},
    )
    prof = pr.mint_principal_token("prof_cohortfb", "professor", tenant_id)
    sid = f"{tenant_id}:only"
    r = client.post(
        f"/students/{sid}/baseline",
        json={"text": BASE_TEXT, "assignment": "a0"},
        headers=_auth(prof),
    )
    assert r.status_code == 200, r.text
    yield prof, sid
    reset_repository()


def _score(prof: str, sid: str):
    r = client.post(
        f"/students/{sid}/score",
        json={"text": BASE_TEXT + " A closing thought, offered plainly."},
        headers=_auth(prof),
    )
    assert r.status_code == 200, r.text
    return r.json()


def _patch_repo_stats(monkeypatch, *, genre_return="__real__", cohort_return="__real__"):
    """Wrap the live repository singleton's get_genre_stats/get_cohort_stats
    with call counters (and captured call args, for the cohort call-shape
    assertions below), leaving every other method untouched.

    get_repository() is a cached module singleton (original/repository.py),
    so patching the instance _repo() resolves to here is exactly what the
    router will call through — mirrors tests/test_shadow_repository.py's
    per-instance monkeypatch.setattr pattern rather than inventing a new
    fixture style. Passing an explicit return value overrides the real
    (SQLite-backed) aggregation so a test can force a hit/miss deterministically
    without depending on incidental cross-student data; "__real__" (default)
    leaves the underlying method's own behaviour untouched.
    """
    repo = get_repository()
    counts = {"genre_stats": 0, "cohort_stats": 0}
    cohort_calls: list[tuple] = []
    real_get_genre_stats = repo.get_genre_stats
    real_get_cohort_stats = repo.get_cohort_stats

    def _counting_genre_stats(*args, **kwargs):
        counts["genre_stats"] += 1
        if genre_return != "__real__":
            return genre_return
        return real_get_genre_stats(*args, **kwargs)

    def _counting_cohort_stats(*args, **kwargs):
        counts["cohort_stats"] += 1
        cohort_calls.append(args)
        if cohort_return != "__real__":
            return cohort_return
        return real_get_cohort_stats(*args, **kwargs)

    monkeypatch.setattr(repo, "get_genre_stats", _counting_genre_stats)
    monkeypatch.setattr(repo, "get_cohort_stats", _counting_cohort_stats)
    counts["cohort_calls"] = cohort_calls
    return counts


# ── (a) flag off → None reaches scoring, neither lookup is even attempted ──


def test_flag_off_no_prior_lookups_at_all(cold_start_student, monkeypatch):
    monkeypatch.delenv("BAYESIAN_PRIOR_ENABLED", raising=False)
    monkeypatch.delenv("COHORT_PRIOR_FALLBACK", raising=False)
    prof, sid = cold_start_student
    counts = _patch_repo_stats(monkeypatch)

    _score(prof, sid)  # must not raise; genre_stats stays None inside the router

    assert counts["genre_stats"] == 0
    assert counts["cohort_stats"] == 0


# ── (b) flag on + genre stats present → genre stats win, fallback NOT called ──


def test_flag_on_genre_stats_present_fallback_not_called(cold_start_student, monkeypatch):
    monkeypatch.setenv("BAYESIAN_PRIOR_ENABLED", "1")
    monkeypatch.setenv("COHORT_PRIOR_FALLBACK", "1")
    prof, sid = cold_start_student
    # Force a genre-stats hit regardless of the real (near-certainly cold)
    # cross-student genre data, isolating the router's branch decision from
    # store aggregation specifics.
    counts = _patch_repo_stats(monkeypatch, genre_return=_FAKE_STATS)

    _score(prof, sid)

    assert counts["genre_stats"] == 1
    assert counts["cohort_stats"] == 0, "cohort fallback must not run when genre stats already hit"


# ── (c) flag on + genre stats None → cohort stats used ─────────────────────


def test_flag_on_genre_stats_none_cohort_fallback_used(cold_start_student, monkeypatch):
    monkeypatch.setenv("BAYESIAN_PRIOR_ENABLED", "1")
    monkeypatch.setenv("COHORT_PRIOR_FALLBACK", "1")
    prof, sid = cold_start_student
    # A single-student cold-start tenant guarantees get_genre_stats() is
    # None for real (no cross-student genre data exists at all). Force
    # get_cohort_stats() to report a hit so the fallback's success path
    # (not just "was it called") is exercised end to end.
    counts = _patch_repo_stats(monkeypatch, cohort_return=_FAKE_STATS)

    _score(prof, sid)

    assert counts["genre_stats"] == 1
    assert counts["cohort_stats"] == 1, "cohort fallback must run when genre stats are cold"
    # Call-shape regression, and the reason this assertion is worth its
    # weight: the fallback must be called with BOTH the requesting student's
    # own tenant (principal.tenant_of — never None/absent, which would
    # re-introduce the cross-tenant leak) AND that student's id as the
    # leave-one-out exclusion. Dropping either argument would still "work"
    # — it would just silently hand the student a prior built from another
    # institution, or from their own writing.
    assert counts["cohort_calls"] == [(tenant_of(sid), sid)]
    assert tenant_of(sid) == "cohortfb"


def test_flag_on_cohort_fallback_disabled_by_default(cold_start_student, monkeypatch):
    """COHORT_PRIOR_FALLBACK unset (default OFF) — genre stats miss and the
    fallback must stay unreachable even with BAYESIAN_PRIOR_ENABLED=1."""
    monkeypatch.setenv("BAYESIAN_PRIOR_ENABLED", "1")
    monkeypatch.delenv("COHORT_PRIOR_FALLBACK", raising=False)
    prof, sid = cold_start_student
    counts = _patch_repo_stats(monkeypatch)

    _score(prof, sid)

    assert counts["genre_stats"] == 1
    assert counts["cohort_stats"] == 0


# ── end-to-end tenant isolation (no mocking — real aggregation) ────────────


def test_cohort_fallback_never_crosses_tenants_end_to_end(cold_start_student, monkeypatch):
    """The regression a reviewer caught against an earlier version of this
    fallback: get_cohort_stats used to aggregate across every tenant in the
    store, so a *different* tenant's cross-student data could silently
    blend into this student's Bayesian prior — a FERPA-relevant leak in a
    product explicitly positioned on tenant isolation.

    No repository methods are mocked here — this exercises the real,
    on-disk SQLite aggregation end to end. `cold_start_student` (tenant
    "cohortfb") has only 1 authenticated sample — below MIN_COHORT_STUDENTS
    (3) for ITS OWN tenant. A second tenant is seeded with 3 students × 2
    samples each — comfortably clearing both cold-start floors — so an
    aggregate-across-all-tenants bug would make the fallback fire (cohort
    stats non-None) for "cohortfb:only" too. A correctly tenant-scoped
    implementation must still treat "cohortfb" as cold.
    """
    monkeypatch.setenv("BAYESIAN_PRIOR_ENABLED", "1")
    monkeypatch.setenv("COHORT_PRIOR_FALLBACK", "1")
    prof, sid = cold_start_student

    other_tenant = "cohortfbother"
    client.post(
        "/tenants",
        json={"tenant_id": other_tenant, "name": "Other Seminary", "environment": "pilot"},
    )
    other_prof = pr.mint_principal_token("prof_other", "professor", other_tenant)
    for i in range(3):
        r = client.post(
            f"/students/{other_tenant}:student{i}/baseline",
            json={"text": OTHER_TENANT_TEXT, "assignment": "a0"},
            headers=_auth(other_prof),
        )
        assert r.status_code == 200, r.text
        r = client.post(
            f"/students/{other_tenant}:student{i}/baseline",
            json={"text": OTHER_TENANT_TEXT + " A second baseline sample.", "assignment": "a1"},
            headers=_auth(other_prof),
        )
        assert r.status_code == 200, r.text

    counts = _patch_repo_stats(monkeypatch)  # real aggregation, just counted

    _score(prof, sid)

    assert counts["genre_stats"] == 1
    assert counts["cohort_stats"] == 1  # fallback DID run (genre stats were cold)
    # scoped to the requester's own tenant, excluding the requester
    assert counts["cohort_calls"] == [("cohortfb", sid)]
    # The real get_cohort_stats("cohortfb", …) call, made above via _score(),
    # must have returned None — cohortfb alone has only 1 contributing
    # student, still below MIN_GENRE_STUDENTS regardless of what the
    # unrelated "cohortfbother" tenant's data looks like.
    assert get_repository().get_cohort_stats("cohortfb", sid) is None
    # sanity: the other tenant's pool is real, not just "always None"
    assert get_repository().get_cohort_stats(other_tenant, None) is not None
