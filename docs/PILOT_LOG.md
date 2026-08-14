# Pilot Log

The running operational record for the pilot. Referenced by
`OPS_RUNBOOK.md` (weekly cadence) and `PROVISIONING_CHECKLIST.md`
(credential re-issues). One line per event, newest first. Keep it boring —
this is the file you'll be glad exists when reconstructing "what changed
on the 14th?"

Log at minimum: deploys, credential issues/re-issues, tenant changes,
restore drills, incidents (with resolution), weekly report runs, and any
manual database intervention.

| Date (UTC) | Who | Event | Notes |
|---|---|---|---|
| 2026-08-13 | Claude (sprint) | Wire-by-wire live proof PASSED on a local pilot-shaped server | 11 wires walked through the real UI: magic link, server deadline (+idempotent replay), degrade-open, seal, score, corrections, audit, phone park. Evidence: `docs/BLUEBOOK_WIRE_PROOF_2026-08-13.md`. |
| 2026-08-13 | Claude (sprint) | Tier 17 readiness run BLOCKED: no pilot Postgres provisioned yet | `tier17_report` now accepts `--db "$DATABASE_URL"`; run it once the managed Postgres exists. Gap to READY unknown until then. |
| 2026-08-13 | Claude (sprint) | Bluebook finish sprint: suite baseline 1685 passed / 0 failed @ `3d6b173d` | `BBOOK_*` declared in blueprint (values still unset — see OPS_RUNBOOK); API reference caught up to live routes. |
| YYYY-MM-DD | (operator) | Example: deployed `<sha>` in maintenance window | preflight exit 0 |
| YYYY-MM-DD | (operator) | Example: re-issued password for prof@inst.edu | delivered in person |
| YYYY-MM-DD | (operator) | Example: restore drill — backup from HH:MM restored to scratch, preflight passed | |
