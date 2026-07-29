# Tenant-Scoped Genre Stats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `get_genre_stats` tenant-scoped so the `BAYESIAN_PRIOR_ENABLED` cold-start prior never pools baseline vectors across tenant boundaries.

**Architecture:** `get_genre_stats(genre)` becomes `get_genre_stats(genre, tenant)` across the `Repository` protocol and both backends. The in-memory/SQLite backend filters on `principal.tenant_of(state.student_id)`; the Postgres backend filters with an indexed equality match on the real `StudentProfile.tenant_id` column. The genre-stats cache is re-keyed from `genre` to `(tenant, genre)`. The single production caller resolves the tenant from the student id being scored. This mirrors, method for method, the `get_cohort_stats(tenant)` pattern already reviewed on branch `claude/serene-murdock-434bf6`.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x (Postgres backend), raw `sqlite3` (SQLite backend), NumPy, pytest.

## Global Constraints

- Python interpreter is **always** `/Users/andrew/Desktop/Original/.venv/bin/python` — never system `python3` (its `pydantic_settings` is broken and conftest import will fail).
- Full suite command: `.venv/bin/python -m pytest tests/ -q`. A clean run is **0 failed**. The 5 `TestAuthEndpoints` rate-limit tests are `xfail(strict=False)` and show as XFAIL/XPASS — never as failures.
- `original/constants.py` feature ordering and `NORM_BOUNDS` must not change. This plan does not touch that file.
- Commit style: `Fix ...` / `Add ...` / `Refactor ...`, one focused commit per logical change, with trailer `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Do not kill or restart any running dev server.
- Branch: `claude/musing-banach-b9eab3` (worktree at `.claude/worktrees/musing-banach-b9eab3`).

---

## Background: the defect

`get_genre_stats` aggregates every confirmed-authentic baseline vector matching a
genre across **every student in the store, in every tenant** — [original/store.py:1022](../../../original/store.py) and
[original/postgres_repository.py:889](../../../original/postgres_repository.py). It feeds the Hierarchical Bayesian cold-start
prior for any student with `sample_count < 10` ([original/routers/students_scoring.py:126-138](../../../original/routers/students_scoring.py)
→ [original/quantum/scoring.py:545-565](../../../original/quantum/scoring.py)).

Every other cross-student read in the codebase is tenant-scoped.
`null_pool.build_impostor_stats` resolves `tenant_of(claimed_student_id)` and
pools only same-tenant peers, and its module docstring states the rule
outright: cross-tenant vectors are never pooled, "same isolation rule as every
other tenant-scoped read." `get_genre_stats` is the one read that violates it.

What leaks is an aggregate (mean vector, std vector, sample count), not raw
text — but it is an aggregate over another institution's student writing, used
to shift a third institution's student's score. For a FERPA-positioned product
this is a defect, not a design choice.

**Prior art to mirror:** `get_cohort_stats(tenant)` on branch
`claude/serene-murdock-434bf6` — tenant parameter, tenant-keyed cache,
distinct-student floor, both backends, contract tests including a dedicated
tenant-isolation class. That branch is **not merged into this one**; this plan
is self-contained and does not depend on it.

## Background: the coverage tradeoff

Tenant-scoping **intersects** with the existing genre filter rather than
replacing it, so each `(tenant, genre)` pool is strictly a subset of today's
`(all-tenants, genre)` pool. Pools get sparser, and the prior returns `None`
more often — falling back to the student-only baseline, which is the documented
and already-exercised behavior, not an error path.

Task 1 measures exactly how much sparser against real data **before** any
production code changes. It is a gate: run it, read the numbers, and only then
proceed. If the measured prior-availability drop is unacceptable for pilot
launch, the fallback is Task 6's documentation-only outcome (record the
cross-tenant pooling as a deliberate, disclosed exception) rather than shipping
Tasks 2-5.

## Out of scope

**Self-exclusion from one's own prior.** `build_impostor_stats` excludes
`claimed_student_id` from its pool; `get_genre_stats` does not, so a student's
own baselines contribute to the prior they are scored against. Tenant-scoping
makes that self-contamination proportionally larger (a smaller pool means the
student is a bigger fraction of it). It is bounded — the prior only applies
below 10 samples and is blended at weight `1 - α` — and fixing it is a separate
semantic change to what "population prior" means. Not addressed here; worth a
follow-up issue.

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `scripts/measure_genre_prior_scope.py` | Create | One-off measurement: per-`(tenant, genre)` pool sizes and the prior-availability delta. Not imported by production code. |
| `original/store.py` | Modify (`:50`, `:42-49`, `:1022-1077`, `:556`, `:1163`) | In-memory/SQLite `get_genre_stats` — tenant filter, `(tenant, genre)` cache key, floor constants. |
| `original/postgres_repository.py` | Modify (`:54`, `:889-915`) | Postgres `get_genre_stats` — indexed `tenant_id` WHERE, `(tenant, genre)` cache key, floor constants. |
| `original/repository.py` | Modify (`:115`, `:417-418`) | `Repository` protocol signature + `SqliteRepository` delegation. |
| `original/routers/students_scoring.py` | Modify (`:126-134`) | Sole production caller — resolve and pass the tenant. |
| `tests/test_repository_contract.py` | Modify (`:315-369`) | Backend-agnostic contract tests: updated signature + new tenant-isolation class. |
| `tests/test_store_fidelity.py` | Modify (`:100-111`) | SQLite-internal cache test — tuple cache key. |
| `CLAUDE.md` | Modify (`:51`) | `BAYESIAN_PRIOR_ENABLED` row states the scoping explicitly. |

Tasks 2-4 change a shared protocol signature and therefore must land as one
commit — a reviewer cannot accept the SQLite half while rejecting the Postgres
half, because `Repository` forces both. Task 5 (the distinct-student floor) is
deliberately separate: it is the one piece a reviewer can reject while keeping
the isolation fix.

---

### Task 1: Measure the coverage impact (GATE — do not skip)

**Files:**
- Create: `scripts/measure_genre_prior_scope.py`

**Interfaces:**
- Consumes: `original.repository.get_repository()`, `original.principal.tenant_of`. No production code changes.
- Produces: printed report only. Nothing later depends on its code — only on a human reading its output.

This task changes no production behavior. Its output is the input to the
go/no-go decision on Tasks 2-6.

- [ ] **Step 1: Write the measurement script**

Create `scripts/measure_genre_prior_scope.py`:

```python
"""
scripts/measure_genre_prior_scope.py — one-off coverage measurement.

Answers: if get_genre_stats were tenant-scoped, how often would the
BAYESIAN_PRIOR_ENABLED cold-start prior resolve to None that it doesn't today?

Simulates the real gate at original/routers/students_scoring.py:126-134 —
a student is a "cold-start scoring event" when sample_count < 10 and their
most recent sample carries a genre label — then asks, for each such student,
whether a prior would exist under (a) today's cross-tenant pooling and
(b) tenant-scoped pooling.

Run against whichever database ORIGINAL_DB / DATABASE_URL points at:

    ORIGINAL_DB=profiles.db .venv/bin/python scripts/measure_genre_prior_scope.py
"""

from __future__ import annotations

import os
from collections import defaultdict

from original.principal import tenant_of
from original.repository import get_repository

# Floors under evaluation. MIN_VECTORS is today's hardcoded 5.
# MIN_STUDENTS models Task 5's proposed distinct-student floor; set it to 1
# to see the effect of tenant-scoping alone (Tasks 2-4 without Task 5).
MIN_VECTORS = 5
MIN_STUDENTS = 3


def main() -> None:
    repo = get_repository()
    states = repo.all_states()
    print(f"database: {os.environ.get('ORIGINAL_DB', 'profiles.db')}")
    print(f"students: {len(states)}")

    scoped_vectors: dict[tuple[str | None, str], int] = defaultdict(int)
    scoped_students: dict[tuple[str | None, str], set[str]] = defaultdict(set)
    global_vectors: dict[str, int] = defaultdict(int)

    for state in states:
        tenant = tenant_of(state.student_id)
        for sample in state.samples:
            if (getattr(sample, "auth_weight", 0) or 0) <= 0:
                continue
            genre = getattr(sample, "genre", None)
            if not genre:
                continue
            scoped_vectors[(tenant, genre)] += 1
            scoped_students[(tenant, genre)].add(state.student_id)
            global_vectors[genre] += 1

    eligible = 0
    have_global = 0
    have_scoped = 0
    have_scoped_floored = 0
    lost_by_tenant: dict[str | None, int] = defaultdict(int)

    for state in states:
        # Mirrors students_scoring.py's gate exactly.
        if state.sample_count >= 10 or not state.samples:
            continue
        genre = getattr(state.samples[-1], "genre", None)
        if not genre:
            continue
        eligible += 1
        tenant = tenant_of(state.student_id)
        key = (tenant, genre)

        global_ok = global_vectors[genre] >= MIN_VECTORS
        scoped_ok = scoped_vectors[key] >= MIN_VECTORS
        floored_ok = scoped_ok and len(scoped_students[key]) >= MIN_STUDENTS

        have_global += global_ok
        have_scoped += scoped_ok
        have_scoped_floored += floored_ok
        if global_ok and not scoped_ok:
            lost_by_tenant[tenant] += 1

    print()
    print(f"cold-start scoring events with a genre label: {eligible}")
    if eligible:
        print(f"  prior available today (cross-tenant):   {have_global:5d}  ({have_global / eligible:.0%})")
        print(f"  prior available tenant-scoped:          {have_scoped:5d}  ({have_scoped / eligible:.0%})")
        print(f"  ... and with a >={MIN_STUDENTS}-student floor:      {have_scoped_floored:5d}  ({have_scoped_floored / eligible:.0%})")
    else:
        print("  (no eligible events — this dataset cannot answer the question)")

    print()
    print("priors lost to tenant-scoping, by tenant:")
    if lost_by_tenant:
        for tenant, count in sorted(lost_by_tenant.items(), key=lambda kv: -kv[1]):
            print(f"  {tenant!r}: {count}")
    else:
        print("  none")

    print()
    print("(tenant, genre) pools — vectors / distinct students:")
    if scoped_vectors:
        for key in sorted(scoped_vectors, key=lambda k: -scoped_vectors[k]):
            tenant, genre = key
            print(
                f"  {str(tenant)!r:22} {genre:28} "
                f"{scoped_vectors[key]:4d} vec  {len(scoped_students[key]):3d} stu"
            )
    else:
        print("  none — no authenticated samples carry a genre label")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it against the demo seed database**

Run:

```bash
ORIGINAL_DB=demo/seed.db .venv/bin/python scripts/measure_genre_prior_scope.py
```

Expected: it runs without error. The demo seed has 5 students, no tenant
prefixes and no genre labels, so expect `cold-start scoring events with a genre
label: 0` and empty pool tables. **This confirms the script works; it does not
answer the question.**

- [ ] **Step 3: Run it against real pilot data**

Run against whichever database actually holds pilot profiles:

```bash
ORIGINAL_DB=profiles.db .venv/bin/python scripts/measure_genre_prior_scope.py
```

For the Postgres backend, set `DATABASE_URL` and `REPO_BACKEND` per
`docs/OPS_RUNBOOK.md` instead of `ORIGINAL_DB`.

**STOP HERE and report the numbers to the user before writing any production
code.** The decision to proceed is theirs. Record in the report:
- eligible cold-start events, and prior-availability under each of the three models
- which tenants lose the most priors
- whether any single `(tenant, genre)` pool is dominated by one student
  (`vec` high, `stu` = 1) — that is the evidence for or against Task 5

If no dataset in reach has genre-labelled authenticated samples, say so plainly
rather than reporting a zero as if it were a measurement. In that case the
honest recommendation is: proceed with Tasks 2-4 (the isolation fix stands on
its own) and defer Task 5 until real data exists.

- [ ] **Step 4: Commit the script**

```bash
git add scripts/measure_genre_prior_scope.py
git commit -m "Add genre-prior scope measurement script (pre-change baseline)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Tenant-scope get_genre_stats across both backends

**Files:**
- Modify: `original/store.py:42-50` (cache declaration + rationale comment), `original/store.py:1022-1077` (the function), `original/store.py:556` and `original/store.py:1163` (cache-bust comments)
- Modify: `original/postgres_repository.py:54` (import), `original/postgres_repository.py:889-915` (the method)
- Modify: `original/repository.py:115` (protocol), `original/repository.py:417-418` (delegation)
- Modify: `original/routers/students_scoring.py:126-134` (sole caller)
- Test: `tests/test_repository_contract.py:315-369`, `tests/test_store_fidelity.py:100-111`

**Interfaces:**
- Consumes: `original.principal.tenant_of(student_id: str) -> str | None`; `original.db.tenancy_shim._LEGACY_FLAT_TENANT` (the `"__legacy_flat__"` sentinel a colon-less id carries on the `tenant_id` column).
- Produces: `get_genre_stats(genre: str, tenant: str | None) -> dict | None` on the `Repository` protocol and both implementations. Returns `{"mean": np.ndarray, "std": np.ndarray, "n_samples": int}` or `None`. `tenant` is **required and positional** — no default — so no existing call site can silently retain cross-tenant pooling. `tenant=None` is the legacy-flat pool: its own distinct cohort, never mixed with a real tenant's.

- [ ] **Step 1: Write the failing tenant-isolation tests**

Append to `tests/test_repository_contract.py`, immediately after
`TestGetGenreStats` (which currently ends at line 369, just before the
`# ── delete_student ──` banner):

```python
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
        assert repo.get_genre_stats("sermon", "seminary-a") is not None
        assert repo.get_genre_stats("sermon", "seminary-b") is None

    def test_pools_are_disjoint_across_tenants(self, repo):
        # Each tenant clears the vector floor on its own. Neither tenant's
        # n_samples may include the other's.
        for i in range(6):
            repo.put(_make_state(f"seminary-a:student-{i}", n=1, genre="exegesis"))
        for i in range(7):
            repo.put(_make_state(f"seminary-b:student-{i}", n=1, genre="exegesis"))
        a = repo.get_genre_stats("exegesis", "seminary-a")
        b = repo.get_genre_stats("exegesis", "seminary-b")
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
        assert repo.get_genre_stats("lab_report", "seminary-a") is None
        assert repo.get_genre_stats("lab_report", "seminary-b") is None

    def test_legacy_flat_pool_is_separate_from_scoped_tenants(self, repo):
        # Colon-less (legacy-flat) ids are tenant_of(...) -> None. They form
        # their own cohort and must not feed a real tenant's prior.
        for i in range(6):
            repo.put(_make_state(f"legacy-student-{i}", n=1, genre="theology_paper"))
        assert repo.get_genre_stats("theology_paper", None) is not None
        assert repo.get_genre_stats("theology_paper", "seminary-a") is None

    def test_scoped_tenant_does_not_feed_the_legacy_flat_pool(self, repo):
        # The converse of the above — the sentinel must not act as a wildcard.
        for i in range(6):
            repo.put(_make_state(f"seminary-a:student-{i}", n=1, genre="rhetoric"))
        assert repo.get_genre_stats("rhetoric", None) is None

    def test_cache_is_keyed_per_tenant(self, repo):
        # A cache keyed on genre alone would serve seminary-a's stats to
        # seminary-b on the second call — the leak surviving the filter.
        for i in range(6):
            repo.put(_make_state(f"seminary-a:student-{i}", n=1, genre="homiletics"))
        assert repo.get_genre_stats("homiletics", "seminary-a") is not None
        assert repo.get_genre_stats("homiletics", "seminary-b") is None
        # ... and again, now that both keys are warm.
        assert repo.get_genre_stats("homiletics", "seminary-a") is not None
        assert repo.get_genre_stats("homiletics", "seminary-b") is None
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_repository_contract.py::TestGetGenreStatsTenantIsolation -v
```

Expected: every test FAILS with `TypeError: get_genre_stats() takes 2 positional arguments but 3 were given`.

- [ ] **Step 3: Re-key the genre-stats cache in store.py**

In `original/store.py`, replace the cache block at lines 41-50:

```python
# ── Bayesian genre-stats cache ────────────────────────────────────────────────
# get_genre_stats() is O(N×S) — iterates every student and every sample.
# Cache the result keyed on (tenant, genre); bust on every put() so newly-added
# baseline samples are reflected in the next call. The hot path reads from this
# dict in O(1). Dict clear is thread-safe in CPython (GIL-protected). This is
# the ONE process-local cache that survives WS-6 P6 (the _STORE profile cache
# is gone): it's a derived aggregate, invalidated on every write in THIS
# worker, and a cross-worker staleness window on a slow-moving population
# statistic is acceptable where stale student profiles were not.
#
# The key MUST stay a (tenant, genre) pair, not a bare genre: a genre-only key
# would hand one tenant's cached aggregate to the next tenant that asks for the
# same genre, reintroducing exactly the cross-tenant leak the filter removes.
_GENRE_STATS_CACHE: dict[tuple[str | None, str], dict | None] = {}
```

- [ ] **Step 4: Add the tenant_of import to store.py**

In `original/store.py`, after line 23 (`from .quantum.state import BaselineSample, StudentState`), add:

```python
from .principal import tenant_of
```

Note: no import cycle — `principal` imports only `student_auth`, which imports
only stdlib. `principal`'s one repository import is lazy, inside
`tenant_environment()`.

- [ ] **Step 5: Rewrite store.get_genre_stats**

In `original/store.py`, replace the whole function at lines 1022-1077 (from
`def get_genre_stats(` through `return result`):

```python
# Cold-start floor for the genre prior. Vector-count only: genre matching
# already limits how concentrated the pool can be, so unlike get_cohort_stats
# (and null_pool.py's MIN_IMPOSTOR_STUDENTS) no distinct-student floor is
# applied here. See Task 5 of docs/superpowers/plans/2026-07-29-tenant-scope-genre-stats.md
# for the argument that tenant-scoping weakens that reasoning.
MIN_GENRE_VECTORS = 5


def get_genre_stats(genre: str, tenant: str | None) -> dict | None:
    """
    Compute cross-student mean, std, and sample count for a writing genre,
    scoped to a single tenant.

    Aggregates feature vectors from confirmed-authentic baseline samples
    (auth_weight > 0) with matching ``sample.genre``, across students in
    ``tenant`` only.  Returns ``None`` when fewer than MIN_GENRE_VECTORS
    samples are found — the caller treats this as "no prior available" and
    falls back to the student-only baseline.

    This is the population-level reference distribution used by the
    Hierarchical Bayesian cold-start prior in ``scoring.score()``.

    Tenant scoping mirrors ``original/quantum/null_pool.py``'s
    ``build_impostor_stats``, which resolves ``tenant_of(claimed_student_id)``
    and pools only same-tenant peers: cross-tenant vectors are never pooled,
    the same isolation rule as every other cross-student read here.  Before
    WS-7 this function pooled across every tenant in the store — a
    FERPA-relevant leak of one institution's aggregate writing statistics
    into another institution's scoring.

    The DB read goes through ``all_states()``; the aggregate is memoised in
    ``_GENRE_STATS_CACHE`` keyed on ``(tenant, genre)`` and busted on every
    ``put()`` / ``delete_student()``.

    Parameters
    ----------
    genre : genre label (e.g. "argumentative_essay", "lab_report")
    tenant : the tenant slug to scope to — ``principal.tenant_of`` of the
        student being scored — or None for the legacy-flat (unscoped) pool,
        which is its own distinct cohort, never mixed with a real tenant's.

    Returns
    -------
    dict with keys "mean" (np.ndarray), "std" (np.ndarray), "n_samples" (int)
    or None if fewer than MIN_GENRE_VECTORS matching authentic samples are
    found in that tenant.
    """
    # O(1) fast path — return cached result if available.
    # Cache is busted by put() whenever a new baseline sample is stored.
    key = (tenant, genre)
    if key in _GENRE_STATS_CACHE:
        return _GENRE_STATS_CACHE[key]

    vectors: list[np.ndarray] = []
    # Full read-through scan (WS-6 P6): all_states() snapshots the table, so
    # concurrent writers can't perturb the iteration the way the old shared
    # _STORE dict could.
    for student_state in all_states():
        if tenant_of(student_state.student_id) != tenant:
            continue
        for sample in student_state.samples:
            if sample.auth_weight > 0 and getattr(sample, "genre", None) == genre:
                vectors.append(sample.vector)

    if len(vectors) < MIN_GENRE_VECTORS:
        _GENRE_STATS_CACHE[key] = None
        return None

    mat = np.stack(vectors, axis=0)  # shape (N, FEATURE_DIM)
    mean_vec = mat.mean(axis=0)  # shape (FEATURE_DIM,)
    # Use the same 0.005 floor as StudentState.baseline_std to keep the
    # prior std compatible with the per-student sigma floor.
    std_vec = np.maximum(mat.std(axis=0), 0.005)
    result = {
        "mean": mean_vec,
        "std": std_vec,
        "n_samples": len(vectors),
    }
    _GENRE_STATS_CACHE[key] = result
    return result
```

- [ ] **Step 6: Update the Postgres import line**

In `original/postgres_repository.py`, replace line 54:

```python
from .db.tenancy_shim import _LEGACY_FLAT_TENANT, join_scoped_id, split_scoped_id
```

- [ ] **Step 7: Rewrite PostgresRepository.get_genre_stats**

In `original/postgres_repository.py`, replace lines 889-915 (`def get_genre_stats(self, genre):` through its `return result`):

```python
    # Mirrors store.MIN_GENRE_VECTORS. Duplicated rather than imported
    # because postgres_repository is a peer backend to store, not a
    # consumer of it.
    MIN_GENRE_VECTORS = 5

    def get_genre_stats(self, genre, tenant):
        """Tenant-scoped genre prior — see store.get_genre_stats's docstring
        for the full contract.

        Filters with an indexed equality match on StudentProfile.tenant_id —
        the same "database constraint instead of a naming convention" the FK
        column exists for — rather than pulling every tenant's profile JSON
        and discarding non-matching rows in Python. A None `tenant` (the
        legacy-flat pool) maps to db.tenancy_shim._LEGACY_FLAT_TENANT exactly
        like split_scoped_id does, since that's the sentinel legacy-flat ids
        actually carry on this column (comparing the column to Python `None`
        would translate to SQL `IS NULL`, which no row would ever satisfy).
        """
        key = (tenant, genre)
        if key in self._genre_stats_cache:
            return self._genre_stats_cache[key]

        tenant_id_column_value = tenant if tenant is not None else _LEGACY_FLAT_TENANT
        try:
            with session_scope() as session:
                rows = (
                    session.execute(
                        select(StudentProfile.data).where(
                            StudentProfile.tenant_id == tenant_id_column_value
                        )
                    )
                    .scalars()
                    .all()
                )
        except Exception:
            log.exception(
                "get_genre_stats DB query failed for genre %s tenant %s", genre, tenant
            )
            return None

        vectors = []
        for data in rows:
            for sample in data.get("samples", []):
                if (sample.get("auth_weight") or 0) > 0 and sample.get("genre") == genre:
                    vectors.append(np.array(sample["vector"], dtype=np.float64))

        if len(vectors) < self.MIN_GENRE_VECTORS:
            self._genre_stats_cache[key] = None
            return None

        mat = np.stack(vectors, axis=0)
        mean_vec = mat.mean(axis=0)
        std_vec = np.maximum(mat.std(axis=0), 0.005)
        result = {"mean": mean_vec, "std": std_vec, "n_samples": len(vectors)}
        self._genre_stats_cache[key] = result
        return result
```

Also update the cache declaration at `original/postgres_repository.py:90`:

```python
        self._genre_stats_cache: dict[tuple[str | None, str], dict | None] = {}
```

- [ ] **Step 8: Update the Repository protocol and SqliteRepository delegation**

In `original/repository.py`, replace line 115:

```python
    def get_genre_stats(self, genre: str, tenant: str | None) -> dict | None: ...
```

and replace lines 417-418:

```python
    def get_genre_stats(self, genre: str, tenant: str | None) -> dict | None:
        return store.get_genre_stats(genre, tenant)
```

- [ ] **Step 9: Pass the tenant at the call site**

In `original/routers/students_scoring.py`, replace lines 126-134:

```python
    _genre_stats = None
    if _scoring_config_env.bayesian_prior_enabled and state.sample_count < 10:
        _genre = (
            state.samples[-1].genre
            if state.samples and getattr(state.samples[-1], "genre", None)
            else None
        )
        if _genre:
            # Tenant-scoped: the cold-start prior pools only same-tenant
            # baselines, mirroring build_impostor_stats above. Returns None
            # more often than the old cross-tenant pool did — that's the
            # documented fallback to the student-only baseline, not an error.
            _genre_stats = _repo().get_genre_stats(_genre, tenant_of(student_id))
```

Add the import near the top of the same file, alongside the other
`original.*` imports:

```python
from ..principal import tenant_of
```

If `tenant_of` is already imported in this module, skip the import line rather
than duplicating it — check with:

```bash
grep -n "tenant_of" original/routers/students_scoring.py
```

- [ ] **Step 10: Update the existing contract tests for the new signature**

In `tests/test_repository_contract.py`, every call in `TestGetGenreStats`
(lines 318-369) gains a second argument. All `_make_state` ids in that class
are colon-less, so `tenant_of(...)` is `None` for all of them — pass `None`:

```python
class TestGetGenreStats:
    def test_returns_none_with_no_students(self, repo):
        assert repo.get_genre_stats("argumentative_essay", None) is None

    def test_returns_none_with_fewer_than_5_samples(self, repo):
        for i in range(4):
            repo.put(_make_state(f"student-G{i}", n=1, genre="argumentative_essay"))
        assert repo.get_genre_stats("argumentative_essay", None) is None

    def test_returns_stats_with_enough_samples(self, repo):
        for i in range(6):
            repo.put(_make_state(f"student-H{i}", n=1, genre="lab_report"))
        result = repo.get_genre_stats("lab_report", None)
        assert result is not None
        assert "mean" in result and "std" in result and "n_samples" in result
        assert result["n_samples"] == 6
        assert result["mean"].shape == (FEATURE_DIM,)
        assert result["std"].shape == (FEATURE_DIM,)

    def test_std_floored_at_005(self, repo):
        for i in range(6):
            repo.put(_make_state(f"student-I{i}", n=1, genre="theology_paper"))
        result = repo.get_genre_stats("theology_paper", None)
        assert result is not None
        assert float(np.min(result["std"])) >= 0.005

    def test_cache_hit_on_second_call(self, repo):
        for i in range(6):
            repo.put(_make_state(f"student-J{i}", n=1, genre="sermon"))
        r1 = repo.get_genre_stats("sermon", None)
        r2 = repo.get_genre_stats("sermon", None)
        assert r1 is r2  # cached — same object reference

    def test_cache_busted_after_put(self, repo):
        for i in range(6):
            repo.put(_make_state(f"student-K{i}", n=1, genre="exegesis"))
        r1 = repo.get_genre_stats("exegesis", None)
        assert r1 is not None
        repo.put(_make_state("student-K6", n=1, genre="exegesis"))
        r2 = repo.get_genre_stats("exegesis", None)
        assert r2 is not None
        assert r2["n_samples"] == 7

    def test_none_genre_samples_not_counted_for_named_genre(self, repo):
        for i in range(6):
            repo.put(_make_state(f"student-L{i}", n=1, genre=None))
        assert repo.get_genre_stats("argumentative_essay", None) is None

    def test_wrong_genre_not_counted(self, repo):
        for i in range(6):
            repo.put(_make_state(f"student-M{i}", n=1, genre="rhetoric"))
        assert repo.get_genre_stats("different_genre", None) is None
```

Add a note above the class so the `None` argument isn't mistaken for a default:

```python
# Every _make_state id in this class is an unscoped/legacy-flat id (no ":"),
# so tenant_of(...) is None for all of them — hence the `None` tenant
# argument throughout. See TestGetGenreStatsTenantIsolation below for the
# scoped-id case.
```

- [ ] **Step 11: Update the SQLite-internal cache test**

In `tests/test_store_fidelity.py`, replace the body of
`TestGenreStatsCacheInternals.test_genre_cache_busted_on_delete` (lines 101-111):

```python
class TestGenreStatsCacheInternals:
    def test_genre_cache_busted_on_delete(self):
        for i in range(6):
            state = _make_state(f"student-del-cache-{i}", n_samples=1, genre="ethics_paper")
            store.put(state)
        # Prime cache — key is (tenant, genre); these ids are legacy-flat.
        store.get_genre_stats("ethics_paper", None)
        assert (None, "ethics_paper") in store._GENRE_STATS_CACHE

        # Delete a student → cache should be cleared
        store.delete_student("student-del-cache-0")
        assert len(store._GENRE_STATS_CACHE) == 0
```

- [ ] **Step 12: Run the tenant-isolation tests to verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/test_repository_contract.py::TestGetGenreStatsTenantIsolation -v
```

Expected: 6 passed (12 if a Postgres instance is reachable — the suite is
parametrized over both backends and self-skips Postgres without `DATABASE_URL`).

- [ ] **Step 13: Run the full suite**

Run:

```bash
.venv/bin/python -m pytest tests/ -q
```

Expected: **0 failed**. XFAIL/XPASS on the 5 `TestAuthEndpoints` rate-limit
tests is normal. If anything else fails, it is a real regression from this
change — most likely a caller or test still using the one-argument signature.
Find them with:

```bash
grep -rn "get_genre_stats" --include="*.py" original/ tests/ scripts/
```

- [ ] **Step 14: Commit**

```bash
git add original/store.py original/postgres_repository.py original/repository.py original/routers/students_scoring.py tests/test_repository_contract.py tests/test_store_fidelity.py
git commit -m "Fix cross-tenant pooling in the Bayesian genre prior

get_genre_stats aggregated authenticated baseline vectors across every
tenant, so one institution's aggregate writing statistics shifted another
institution's cold-start scores. Every other cross-student read is already
tenant-scoped (null_pool.build_impostor_stats); this was the exception.

Adds a required tenant argument to the Repository protocol and both
backends, re-keys the genre-stats cache on (tenant, genre) so a warm cache
can't leak what the filter blocks, and resolves the tenant at the single
production call site.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Document the scoping in CLAUDE.md

**Files:**
- Modify: `CLAUDE.md:51`

**Interfaces:**
- Consumes: the behavior shipped in Task 2.
- Produces: nothing code-level.

The user asked for this row to state the scoping explicitly **either way** —
so this task runs whether or not Tasks 2 and 5 ship. Use the first variant if
Task 2 landed, the second if the measurement in Task 1 killed it.

- [ ] **Step 1: Update the BAYESIAN_PRIOR_ENABLED row**

In `CLAUDE.md`, replace line 51:

```markdown
| `BAYESIAN_PRIOR_ENABLED` | `0` | Hierarchical Bayesian cold-start prior. **Tenant-scoped**: `get_genre_stats(genre, tenant)` pools same-tenant baselines only (`store.py`, `postgres_repository.py`), mirroring `null_pool.build_impostor_stats`. `tenant=None` (legacy-flat ids) is its own cohort. Genre pools are sparser per-tenant than the old cross-tenant pool, so the prior returns `None` more often and falls back to the student-only baseline. |
```

**If Task 2 did NOT ship** (the measurement showed an unacceptable coverage
loss), use this row instead — the exception must be disclosed, not silent:

```markdown
| `BAYESIAN_PRIOR_ENABLED` | `0` | Hierarchical Bayesian cold-start prior. ⚠️ **NOT tenant-scoped**: `get_genre_stats(genre)` pools authenticated baseline vectors across ALL tenants (`store.py`, `postgres_repository.py`) — the one cross-student read that is not tenant-isolated, unlike `null_pool.build_impostor_stats`. Only aggregates (mean/std/n) cross the boundary, never raw text. Deliberate, pending genre-pool density: see `docs/superpowers/plans/2026-07-29-tenant-scope-genre-stats.md`. |
```

- [ ] **Step 2: Verify the table still renders**

Run:

```bash
grep -n "BAYESIAN_PRIOR_ENABLED" CLAUDE.md
```

Expected: one line, starting with `|` and ending with `|`, with exactly 3
pipe-delimited cells. A stray unescaped `|` inside the description would break
the Markdown table.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "Document the genre-prior tenant scoping in CLAUDE.md

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Add a distinct-student floor (SEPARABLE — reject freely)

**Files:**
- Modify: `original/store.py` (`MIN_GENRE_VECTORS` block and the aggregation loop in `get_genre_stats`)
- Modify: `original/postgres_repository.py` (`MIN_GENRE_VECTORS` class attr and the aggregation loop)
- Test: `tests/test_repository_contract.py` (`TestGetGenreStatsTenantIsolation`)

**Interfaces:**
- Consumes: `get_genre_stats(genre, tenant)` as shipped in Task 2.
- Produces: no signature change. `MIN_GENRE_STUDENTS = 3` alongside the existing `MIN_GENRE_VECTORS = 5`, on both backends.

**Only do this task if Task 1's measurement showed `(tenant, genre)` pools
dominated by a single student** (high `vec`, `stu` = 1). Otherwise skip it and
say so — it raises the `None` rate for a problem the data doesn't show.

Rationale: today's vector-only floor rests on the argument that genre matching
already limits how concentrated a pool can be. Tenant-scoping weakens that. At a
small seminary, one prolific student with 5 lab reports becomes the entire
"population prior" for lab reports — and then that same student's cold-start
submissions get scored against a prior built from their own baselines. A
distinct-student floor of 3 mirrors `null_pool.MIN_IMPOSTOR_STUDENTS`.

- [ ] **Step 1: Write the failing tests**

Append to `TestGetGenreStatsTenantIsolation` in `tests/test_repository_contract.py`:

```python
    def test_single_student_cannot_form_a_population_prior(self, repo):
        # One student with 6 same-genre baselines is not a "population" —
        # and without a distinct-student floor that student's own vectors
        # would become the prior their next submission is scored against.
        repo.put(_make_state("seminary-c:prolific", n=6, genre="sermon"))
        assert repo.get_genre_stats("sermon", "seminary-c") is None

    def test_two_students_still_below_the_student_floor(self, repo):
        # 6 vectors, clears MIN_GENRE_VECTORS — but only 2 contributing
        # students, below MIN_GENRE_STUDENTS.
        repo.put(_make_state("seminary-c:student-0", n=3, genre="exegesis"))
        repo.put(_make_state("seminary-c:student-1", n=3, genre="exegesis"))
        assert repo.get_genre_stats("exegesis", "seminary-c") is None

    def test_three_students_clear_both_floors(self, repo):
        repo.put(_make_state("seminary-c:student-0", n=2, genre="homiletics"))
        repo.put(_make_state("seminary-c:student-1", n=2, genre="homiletics"))
        repo.put(_make_state("seminary-c:student-2", n=2, genre="homiletics"))
        result = repo.get_genre_stats("homiletics", "seminary-c")
        assert result is not None
        assert result["n_samples"] == 6

    def test_unverified_samples_count_toward_neither_floor(self, repo):
        # An auth_weight=0 sample must not make its student "contributing",
        # nor its vector count toward n_samples.
        for i in range(3):
            repo.put(_make_state(f"seminary-d:student-{i}", n=2, genre="rhetoric"))
        unverified = StudentState(student_id="seminary-d:unverified")
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
        result = repo.get_genre_stats("rhetoric", "seminary-d")
        assert result is not None
        assert result["n_samples"] == 6  # not 7
```

- [ ] **Step 2: Run them to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_repository_contract.py::TestGetGenreStatsTenantIsolation -v -k "floor or population or unverified"
```

Expected: `test_single_student_cannot_form_a_population_prior` and
`test_two_students_still_below_the_student_floor` FAIL (they currently return
stats, not `None`). The other two should already pass.

- [ ] **Step 3: Add the floor to store.py**

In `original/store.py`, replace the `MIN_GENRE_VECTORS = 5` block from Task 2
Step 5 with:

```python
# Cold-start floors for the genre prior. MIN_GENRE_VECTORS is the historical
# vector-count floor; MIN_GENRE_STUDENTS mirrors null_pool.py's
# MIN_IMPOSTOR_STUDENTS. The distinct-student floor exists because
# tenant-scoping undercut the old "genre matching already limits pool
# concentration" argument: within one small tenant, a single prolific
# student's samples could otherwise pose as a population-level prior — and
# then score that same student's cold-start submissions against their own
# baselines.
MIN_GENRE_VECTORS = 5
MIN_GENRE_STUDENTS = 3
```

Then replace the aggregation loop and floor check inside `get_genre_stats`:

```python
    vectors: list[np.ndarray] = []
    contributing_students = 0
    # Full read-through scan (WS-6 P6): all_states() snapshots the table, so
    # concurrent writers can't perturb the iteration the way the old shared
    # _STORE dict could.
    for student_state in all_states():
        if tenant_of(student_state.student_id) != tenant:
            continue
        student_vectors = [
            sample.vector
            for sample in student_state.samples
            if sample.auth_weight > 0 and getattr(sample, "genre", None) == genre
        ]
        if not student_vectors:
            continue
        contributing_students += 1
        vectors.extend(student_vectors)

    if contributing_students < MIN_GENRE_STUDENTS or len(vectors) < MIN_GENRE_VECTORS:
        _GENRE_STATS_CACHE[key] = None
        return None
```

Update the docstring's `Returns` section to match:

```
    Returns
    -------
    dict with keys "mean" (np.ndarray), "std" (np.ndarray), "n_samples" (int)
    or None if fewer than MIN_GENRE_STUDENTS contributing students, or fewer
    than MIN_GENRE_VECTORS matching authentic samples, are found in that
    tenant.
```

- [ ] **Step 4: Add the floor to postgres_repository.py**

In `original/postgres_repository.py`, replace the `MIN_GENRE_VECTORS = 5` class
attribute from Task 2 Step 7 with:

```python
    # Mirror store.MIN_GENRE_VECTORS / MIN_GENRE_STUDENTS. Duplicated rather
    # than imported because postgres_repository is a peer backend to store,
    # not a consumer of it.
    MIN_GENRE_VECTORS = 5
    MIN_GENRE_STUDENTS = 3
```

and replace the aggregation loop and floor check in the method body:

```python
        vectors = []
        contributing_students = 0
        for data in rows:
            student_vectors = [
                np.array(sample["vector"], dtype=np.float64)
                for sample in data.get("samples", [])
                if (sample.get("auth_weight") or 0) > 0 and sample.get("genre") == genre
            ]
            if not student_vectors:
                continue
            contributing_students += 1
            vectors.extend(student_vectors)

        if (
            contributing_students < self.MIN_GENRE_STUDENTS
            or len(vectors) < self.MIN_GENRE_VECTORS
        ):
            self._genre_stats_cache[key] = None
            return None
```

- [ ] **Step 5: Fix the pre-existing tests the new floor invalidates**

The floor changes what several Task 2 tests expect, because they seed one
sample per student across 6 students (fine — 6 students clears 3) but two of
them seed fewer. Re-run the genre classes and repair any that now fail:

```bash
.venv/bin/python -m pytest tests/test_repository_contract.py -v -k "GenreStats"
```

Expected breakages and their fixes:
- `TestGetGenreStats::test_returns_none_with_fewer_than_5_samples` — 4 students
  × 1 sample. Still `None`, now for two reasons. Passes unchanged.
- `TestGetGenreStatsTenantIsolation::test_cross_tenant_samples_do_not_lift_a_tenant_over_the_floor`
  — 4 students per tenant. Still `None`. Passes unchanged.
- Any test seeding fewer than 3 distinct students while expecting non-`None`
  must gain a third student. Fix by raising the `range(...)` bound, not by
  weakening the assertion.

- [ ] **Step 6: Run the full suite**

Run:

```bash
.venv/bin/python -m pytest tests/ -q
```

Expected: **0 failed**.

- [ ] **Step 7: Commit**

```bash
git add original/store.py original/postgres_repository.py tests/test_repository_contract.py
git commit -m "Add a distinct-student floor to the genre prior

Tenant-scoping undercut the argument that genre matching alone limits how
concentrated a prior pool can be: within one small tenant a single prolific
student could form the entire population prior, then be scored against it.
MIN_GENRE_STUDENTS=3 mirrors null_pool.MIN_IMPOSTOR_STUDENTS.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 8: Re-run the measurement and update CLAUDE.md if the floor shipped**

Run:

```bash
ORIGINAL_DB=profiles.db .venv/bin/python scripts/measure_genre_prior_scope.py
```

Report the post-change availability figure. If Task 4 shipped, append to the
`BAYESIAN_PRIOR_ENABLED` row from Task 3: `Floors: 5 vectors / 3 distinct
students.` Commit that one-line edit with the same message style.

---

## Verification

Before claiming this work is complete, run and paste the output of:

```bash
.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q
```

That is the exact CI command. Do not report success on a partial run, and do
not describe a failure as pre-existing without confirming it fails on
`origin/main` too — check out a clean copy rather than using `git stash`.

Confirm no caller was missed:

```bash
grep -rn "get_genre_stats" --include="*.py" original/ tests/ scripts/
```

Every hit in `original/` and `tests/` must pass two arguments; the protocol and
both backends must declare `(self, genre, tenant)`.
