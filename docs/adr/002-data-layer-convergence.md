# ADR 002 — Converge the demo and v1 data layers behind a Repository seam

**Status:** Accepted
**Date:** 2026-06-02
**Deciders:** Product / Engineering owner

## Context

Two parallel backends have drifted apart:

- **Demo stack** — `original/api.py` + `original/store.py` (SQLite, open access). Carries all recent feature velocity: tenant registry, audit log, FERPA inventory, the corrections→fidelity loop, the student/operator dashboards, and the Formation Track UI.
- **v1 stack** — `original/api/v1/` (Postgres, JWT, SQLAlchemy models for Institution/Student/Submission/Baseline + Canvas/LTI 1.3). Carries auth and the "real" persistence, but **none** of the new features. It never imports `store.py`.

`run.py --demo` loads `original/api.py` → SQLite. A pilot today would therefore run on the *un-hardened* demo stack, while the hardened v1 stack lacks the features a pilot needs.

This contradicts the system's own stated model: the tenant registry already carries `environment ∈ {demo, pilot, production}` — i.e. **one system in three modes**, not two systems. Every feature currently has to be built twice or it can never reach a real school.

## Decision

Adopt **one application with a pluggable persistence layer, selected by `environment`** — not two apps. Introduce a `Repository` seam (`original/repository.py`) that every new feature routes through. The SQLite implementation backs the demo; a Postgres implementation plugs in for pilot/production once the v1 models are extended.

New features get exactly one home: the `Repository` interface, implemented once per backend.

## Options Considered

### Option A — Promote demo features into v1; demo becomes seeded v1
Single backend, but loses the zero-dependency SQLite demo that makes local/preview/pilot-in-a-box trivial.

### Option B — Keep both, formalize the split (status quo)
No migration now, but every feature is built twice and the divergence compounds. Path of slow failure.

### Option C — Repository seam: one endpoint set, pluggable store, auth gated by environment ✅
Keeps the frictionless SQLite demo *and* gives one feature implementation. `environment` chooses store + auth strictness. Matches the demo/pilot/production intent already shipped. Costs one upfront abstraction.

## Trade-off Analysis

B is the default-by-inertia and the most expensive over any horizon beyond a few weeks. A is the fastest route to one backend but sacrifices the SQLite demo. **C** preserves both modes for the cost of one interface and is the only option consistent with the `environment` field already in the schema.

## Consequences

- **Easier:** every new feature built once; a pilot runs Postgres + JWT without reimplementing demo features.
- **Harder (near-term):** must define the store interface and migrate `store.py` callers behind it, incrementally.
- **Revisit:** student authentication (the demo path has none today).

## Action Items

1. [x] Define `Repository` protocol + `SqliteRepository` (delegates to `store.py`) + `get_repository(environment)` factory. — `original/repository.py`
2. [x] First convergence slice: the **Formation backend** routed entirely through the seam (`formation_pathways` table, endpoints, frontend, tests).
3. [ ] Route tenant/audit reads through the same protocol.
4. [ ] Add the Postgres `Repository` implementation for pilot/production; retire the dual-app split.
5. [ ] Add student authentication on the converged path.

## Notes

The first slice (Formation) was chosen because it is simultaneously a **P0 product gap** (the Formation Track was localStorage-only — "completion clears the flag" was a client-side lie) and a clean demonstration of the seam: the API depends only on `Repository`, not on `store.py` directly.
