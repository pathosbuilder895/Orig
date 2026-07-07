# ADR-006: Converge on Postgres as the live persistence layer

**Status:** Accepted — not yet implemented
**Date:** 2026-07-07
**Deciders:** Product owner (Andrew)
**Relates to:** ADR-002 (data-layer convergence, the `Repository` seam),
ADR-004 (hardened SQLite for the pilot), `docs/AUDIT_2026-07-06.md` §10
(Postgres convergence plan)

## Context

ADR-004 decided, correctly, that the pilot should not be blocked on a
Postgres port: a single-institution pilot has low write concurrency, and
hardened SQLite (WAL + busy_timeout + online `.backup`) is well within its
operating envelope. That decision stands for the pilot phase and is not
reopened here.

But ADR-004 also named the two ways the project eventually leaves SQLite —
"Route A: adapter behind the repository seam" or "Route B: graduate onto the
dormant v1 app" — without picking one. `docs/AUDIT_2026-07-06.md` §10 did the
scoping work since: it measured the actual gap (the `Repository` protocol
covers 9 of the store's 67 public functions across 16 tables; `api.py`
bypasses the seam 68:26; `quantum/scoring.py` calls the store directly), and
concluded that a wholesale cutover to the v1 app (`original/main.py`) would
**regress the pilot** — v1 has no Bluebook, no live LTI (`/lti/*`), no
calibration lab, no null model, no voice/formation surface, and a different
auth model (JWT + SQLAlchemy `User`/`Student` ORM models vs. the live
principal-token system in `original/principal.py`).

This ADR exists because "converge on Postgres" is a real, made decision that
needs a record — not because the migration is happening now. The **decision
itself** (timing, phasing, execution order) belongs to a separate workstream
(WS-6); this ADR records *why Postgres over the current hardened-SQLite pilot
setup*, at the scope level, and defers the how/when to that workstream and to
`docs/AUDIT_2026-07-06.md` §10, which already contains a six-phase (P0–P6)
execution plan.

## Decision

**Converge the live stack onto Postgres, reached by widening the existing
`Repository` seam (ADR-002) rather than by adopting the dormant v1 backend
wholesale.** Concretely, per audit §10's scope framing:

- The live API (`original/api.py`, routes, business logic, auth model)
  **stays**. Its persistence moves from SQLite to Postgres through
  `PostgresRepository`, implementing the same `Repository` protocol
  `SqliteRepository` implements today.
- The dormant v1 stack's *infrastructure* — SQLAlchemy models
  (`original/db/models/`), Alembic migration tooling, pydantic `Settings`
  (`original/core/config.py`) — is promoted and adapted for the live app's
  actual schema (16 tables, not v1's ~7 model files' partial coverage).
- The dormant v1 **API surface** (`original/api/`, `original/main.py`,
  `original/canvas/`, `original/middleware/`, `original/auth/`,
  `original/schemas_v1/`) is retired, not merged. Its routes, JWT auth, and
  ORM models do not become the live surface; only its Postgres/Alembic/
  Settings machinery is reused.

### Why Postgres over continuing on hardened SQLite

- **Multi-institution scale is the trigger, not a fixed date.** ADR-004
  already named this: SQLite's operating envelope is a single-institution
  pilot with low write concurrency. Multiple institutions on one process
  raises both write contention and the blast radius of the single-file
  failure mode.
- **Process-local state stops scaling past one worker.** `docs/AUDIT_2026-07-06.md`
  §1 (A4) notes the live stack's correctness currently assumes exactly one
  process — the in-memory `_STORE` cache and the in-memory login throttle
  are both process-local. SQLite's single-writer model is compatible with
  that today; it becomes the blocker to `--workers N` and any horizontal
  scaling once traffic grows. A real `tenant_id` column + FK + unique
  constraint (audit §10, Phase P2) also converts tenant isolation from a
  string-prefix *convention* (`"{tenant_id}:{local_id}"`,
  `original/store.py`) into a database *constraint* — audit §10 calls this
  "the single biggest correctness upgrade of the whole migration,"
  independent of the SQLite-vs-Postgres question but only practical to do
  as part of a schema migration.
- **Connection/DDL churn.** Audit §10 / §1 (A8) notes every store operation
  today opens a fresh SQLite connection and replays ~13 `CREATE TABLE IF NOT
  EXISTS` statements. A session-per-request Postgres pattern removes that
  overhead as a byproduct of the migration.
- **The dormant v1 stack already paid for Postgres tooling once.** Alembic,
  SQLAlchemy models, and pooled `DATABASE_URL` connections exist in
  `original/db/` and `original/core/config.py` today, unused by the live
  app. Reusing that investment (adapted to the live schema) is cheaper than
  building Postgres support from nothing, and retiring the v1 *API* surface
  around it (audit §10 Phase P6) resolves the long-standing dead-code and
  test-maintenance cost documented in audit §2 (F1) and §3 (T4/T6) as a
  side effect.

### What this ADR does not decide

- **Timing.** When Postgres convergence actually starts is a WS-6 call,
  weighed against pilot stability, teaching-calendar constraints (no deploys
  during exams, per `docs/OPS_RUNBOOK.md`), and whatever institution count
  the pilot has grown to.
- **The migration plan's execution detail.** `docs/AUDIT_2026-07-06.md` §10
  already lays out six phases (P0 decision/infra → P1 widen the seam → P2
  schema/models → P3 `PostgresRepository` + parity → P4 data migration/shadow
  validation → P5 cutover → P6 decommission the v1 surface). This ADR does
  not restate or re-derive that plan; it only records that the destination
  (Postgres, via the repository seam) has been chosen.
- **Whether Route A/B from ADR-004 is fully resolved.** It is — this ADR is
  the answer: Route A (adapter behind the repository seam), not Route B
  (graduate onto v1 wholesale).

### Current status: not yet implemented

As of this writing, `PostgresRepository` raises on every method call and
`get_repository()` always returns the SQLite-backed repository — the
decision is made, the plan is written (audit §10), and no execution phase
has started. This ADR's "Accepted" status reflects the decision, not
completed work; do not read it as claiming the migration has happened.

## Options considered

### Option A: Widen the `Repository` seam to a `PostgresRepository` — CHOSEN
Keeps the live API, auth model, and every pilot-specific feature (Bluebook,
LTI, calibration lab, null model, voice/formation) untouched; persistence
becomes swappable behind the seam ADR-002 already built for this purpose.
**Cost:** the seam is only 9/67 functions wide today; most of the migration
work (audit §10 Phase P1) is *widening the seam*, not writing Postgres code.

### Option B: Graduate the pilot onto the dormant v1 app (`original/main.py`)
Already speaks Postgres, JWT auth, SQLAlchemy. **Rejected** — as ADR-004
already noted and audit §10 confirms with more detail: v1 lacks Bluebook, live
LTI, the calibration lab, the null model, and the voice/formation surface, and
uses a materially different auth model. Adopting it wholesale would be a
product regression disguised as an infrastructure migration.

### Option C: Stay on hardened SQLite indefinitely
Defers all migration cost. **Rejected as a permanent stance** (though it
remains correct for the pilot phase per ADR-004) — the process-local-state and
single-writer constraints in audit §1 (A4/A8) do not resolve themselves as
institution count grows, and the cost of migrating only increases with more
stored data and more institutions to shadow-validate against.

## Consequences

**Now (immediate, from this ADR alone):**
- No code changes. This is a documentation/record-keeping artifact.
- Future infrastructure decisions (e.g., whether to invest further in SQLite
  tooling, whether to expand the `Repository` protocol opportunistically)
  should be made with this destination in mind rather than as if SQLite were
  permanent.

**Later (when WS-6 executes, per audit §10's phase plan):**
- **Easier:** tenant isolation becomes a real constraint, not a convention;
  `--workers N` and horizontal scaling become available (audit §1 A4/A8);
  the dormant v1 stack's dead-code and test-maintenance burden (audit §2 F1,
  §3 T4/T6) is resolved by retirement rather than left to rot.
- **Harder:** a genuine data migration with checksums and a shadow-validation
  soak period (audit §10 Phase P4) is required before cutover; Render
  Postgres has a real ongoing cost (audit §10 estimates ~$7–20/mo pilot
  tier); the migration touches 16 tables and must preserve subtle existing
  semantics (e.g., `tuned_thresholds_v` versioning, audit-log pagination).

## Action items

1. [ ] WS-6 to schedule Phase P0 (decision infra: provision Render Postgres
   staging, promote `core/config.py` Settings) — not started.
2. [ ] WS-6 to execute Phases P1–P6 per `docs/AUDIT_2026-07-06.md` §10 — not
   started.
3. [x] Record the scope decision (this ADR).

## Related documents

- [ADR-002](002-data-layer-convergence.md) — the `Repository` seam this
  migration widens.
- [ADR-004](004-postgres-migration.md) — the pilot's decision to stay on
  hardened SQLite for now; this ADR is its planned successor, not its
  reversal.
- [`docs/AUDIT_2026-07-06.md`](../AUDIT_2026-07-06.md) §10 — the six-phase
  execution plan this ADR references but does not restate.
