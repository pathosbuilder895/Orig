# ADR-008: Dormant v1 pruning follow-through

Status: Proposed — human confirmation required

## Context

The original proposal predated WS-6 P6. `original/main.py`, the `original/api/`
package, the old `/canvas/lti/*` surface, and the dead `frontend/`/`web/` trees
have since been deleted. `docs/ARCHITECTURE.md` records that decision. The
remaining `original/core/` and `original/db/` directories are not wholesale v1
debris: the live Postgres repository and FERPA/security CLIs import them.

## Options

1. Treat the pruning decision as completed and keep the proven live
   dependencies.
2. Quarantine the remaining CLI-only modules, after an importer-by-importer
   audit and migration plan.
3. Delete remaining directories by name, risking the live Postgres and FERPA
   paths.

## Recommendation

Record option 1 as accepted. Any further pruning should target individual
zero-import modules, never directory labels. This memo authorizes no deletion.
