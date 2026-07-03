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
| YYYY-MM-DD | (operator) | Example: deployed `<sha>` in maintenance window | preflight exit 0 |
| YYYY-MM-DD | (operator) | Example: re-issued password for prof@inst.edu | delivered in person |
| YYYY-MM-DD | (operator) | Example: restore drill — backup from HH:MM restored to scratch, preflight passed | |
