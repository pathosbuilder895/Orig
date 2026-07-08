# Archived v1 migrations (off the migration path)

These 7 revisions (`001`–`007`) target the **dormant v1 ORM schema**
(`original/db/base.py:Base` — `institutions`, v1 `users`, `students`,
`baseline_samples`, Canvas/LTI tables). No deployed database was ever
managed by them (audit finding B19), and the v1 API surface they served is
scheduled for deletion at WS-6 P6.

They were moved out of `alembic/versions/` in WS-6 **P2** (see ADR-006 and
`docs/AUDIT_2026-07-06.md` §10) when alembic was reset to a fresh baseline
for the **live** pilot schema (`original/db/models/live.py`, 16 tables).
Alembic's `script_location` only scans `alembic/versions/`, so nothing here
is on the migration path — the files are kept readable for reference until
P6 removes the v1 stack entirely.

Do not add new revisions here.
