# ADR-009: Persisting “Mark Reviewed”

Status: Proposed — human decision required

## Context

Bluebook's “Mark Reviewed” state is currently UI-local and disappears after a
reload. A durable implementation needs an explicit link between a Bluebook
submission and its scoring record in both SQLite and Postgres; silently
overloading audit logs would make the read model fragile.

## Options

1. Add review fields to the scoring-result record: `reviewed_at`,
   `reviewed_by`, and an optional outcome/note, keyed by tenant and submission
   id.
2. Add an append-only review-events table and derive current state from its
   latest event. This preserves history but adds query and migration cost.
3. Keep the control session-local and relabel it so the UI does not promise
   persistence.

## Recommendation

Use option 2 if review history is an institutional audit requirement;
otherwise option 1 is the smallest honest model. Either requires matching
SQLite migration-on-open, Alembic/Postgres migration, repository-contract
methods, tenant-isolation tests, and FERPA deletion/inventory coverage. No
schema change is made by this ADR.
