# ADR-004: Persistence for the Pilot — Hardened SQLite now, Postgres path documented

**Status:** Accepted
**Date:** 2026-06-04
**Deciders:** Product owner (Andrew)
**Relates to:** ADR-002 (data-layer convergence), ADR-003 (multi-tenant without losing the demo)

## Context

There are two backends in this repo:

1. **Dashboard / demo app** (`original/api.py`, served on :8001) — the one the
   static dashboards talk to and the one hardened in ADR-003 (auth, tenant
   isolation, login). Persistence is **SQLite** (`original/store.py`,
   `ORIGINAL_DB`), with an in-memory cache.
2. **v1 API** (`original/main.py`, `original/api/v1/*`) — full JWT auth,
   SQLAlchemy with **`DATABASE_URL` (Postgres)**, connection pooling, rate
   limiting, a `create-admin` CLI. This is the long-term production surface.

The weeks-away pilot runs on **app #1**, because that is where the UI and the
ADR-003 security layer live. The ADR-003 action item "migrate SQLite → Postgres"
must be reconciled with that reality.

## Decision

**Run the pilot on hardened SQLite (app #1). Do not block the pilot on a Postgres
port.** A single-institution pilot has low write concurrency; SQLite in WAL mode
with a busy-timeout is durable and well within its operating envelope. Postgres
becomes necessary at multi-institution scale (Phase 2), at which point the
**repository seam (ADR-002)** is the place to add an adapter — or the pilot
graduates onto app #2 (which already speaks Postgres).

### Done in this change (Phase 1)
- **WAL + busy_timeout + synchronous=NORMAL** on every connection
  (`_get_conn`) — readers no longer block on writers; no spurious "database is
  locked" under parallel requests.
- **Configurable path** via `ORIGINAL_DB` (already supported).
- **Online backups**: `scripts/backup_db.sh` (uses SQLite `.backup`, safe under
  WAL) + a cron example; prunes to the most recent N.

### Postgres path (Phase 2, when multi-institution scale demands it)
Two viable routes — pick at the time:

**Route A — adapter behind the repository seam (keep app #1's UX).**
1. Implement a `PostgresRepository` mirroring `SqliteRepository` (ADR-002).
2. Port the direct `store.py` calls that bypass the repo to go through it
   (students, samples, manifests, corrections, formation, baseline_requests).
3. Translate the schema (the `CREATE TABLE` blocks in `store.py`) to SQL DDL +
   a migration tool (Alembic). JSON blob columns → `jsonb`.
4. Backfill: export SQLite rows → load into Postgres (one-off script).
5. Switch by setting `DATABASE_URL`; keep SQLite as the demo-tenant store.

**Route B — graduate the pilot onto app #2 (`original/main.py`).**
Already Postgres + JWT + rate limiting. Cost: re-point the dashboards at the v1
API surface and reconcile the ADR-003 `Principal`/tenant layer with v1 auth
(they already share the `{tenant}:{local}` id and HMAC signing, so this is
convergence, not a rewrite).

## Consequences
- **Easier:** pilot ships on a durable store now; backups are one cron line.
- **Harder later:** a real Postgres cutover needs a migration + backfill (Route
  A) or a surface reconciliation (Route B) — scoped above, deferred to Phase 2.
- **Guardrail:** because the v1 app owns `DATABASE_URL`, the dashboard app does
  **not** interpret it (avoids silently splitting data across two stores).

## Action items
1. [x] WAL/busy_timeout hardening in `store.py`.
2. [x] `scripts/backup_db.sh` + cron example.
3. [ ] (Phase 2) Choose Route A or B; implement `PostgresRepository` or surface reconciliation.
4. [ ] (Phase 2) Alembic migrations + SQLite→Postgres backfill script.
5. [ ] (Phase 2) Nightly backup retention + restore drill documented in a runbook.
