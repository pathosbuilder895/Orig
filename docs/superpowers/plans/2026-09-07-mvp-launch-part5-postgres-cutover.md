# MVP Launch Part 5 — Postgres Cutover and Restore Drills (O4 + O5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read `2026-09-07-mvp-launch-index.md` §Global Constraints first — they all apply here. Ops part: step = action + verifying command + expected output; `⛔ HUMAN` = operator-only; unexpected output → STOP, BLOCKED, PILOT_LOG.

**Goal:** `/health` reports `"backend":"postgres"` and `python -m scripts.pilot_smoke_test … --expect-count <n>` prints `smoke test: PASS`; both restore drills (SQLite and Postgres) have passed and are logged; the SQLite rollback floor is dated; `tier17_report --db "$DATABASE_URL"` runs against the pilot DB for the first time (clearing the 2026-08-13 BLOCKED entry with a real reading).

**Architecture:** The OPS_RUNBOOK:183-231 ceremony, executed in the zero-user window. **Recorded reconciliation:** the runbook demands a 1–2-week `REPO_SHADOW=postgres` soak *against real traffic*; with zero users there is no real traffic and the soak's information saturates fast — so this plan compresses it to **24–48h of shadow with scripted synthetic traffic and zero divergences**. Conditional: if real users exist by execution time, revert to the runbook's full soak and schedule the window outside the exam calendar.

**Tech Stack:** Render managed Postgres, alembic, `scripts/migrate_sqlite_to_pg.py`, `scripts/restore_drill.py`, `scripts/pilot_smoke_test.py`, `scripts/tier17_report.py`.

**Venue:** operator + assistant. **Depends on:** Part 4. **Should complete before Part 6's real students** (post-launch, this ceremony needs a freeze window; pre-launch it needs none).

## Global Constraints (additional to the index's)

- All four cutover controls (`DATABASE_URL`, `REPO_SHADOW`, `REPO_BACKEND`, `MAINTENANCE_MODE`) are dashboard-managed `sync: false` vars; every change deploys. Rollback at ANY failure = unset `REPO_BACKEND` (and `MAINTENANCE_MODE`) → deploy.
- The entry gate is real: **no window opens until the restore drill has passed** (the runbook's P4 acceptance bar) and shadow shows zero divergences.
- Writes made on Postgres after the flip are lost on rollback — with zero users that cost is zero, which is exactly why this part runs now.

---

### Task 1: Provision (⛔ HUMAN)

- [ ] **Step 1:** Render → New → Postgres, smallest tier, same region as the service → set `DATABASE_URL` (internal URL) on `original-pilot`. Verify boot stays healthy (`/health` 200, still `"backend":"sqlite"` — DATABASE_URL alone flips nothing).
- [ ] **Step 2:** Record the tier's backup-retention window in `docs/OPS_RUNBOOK.md` §Backups (closes that doc's standing "record it here" TODO). `git add docs/OPS_RUNBOOK.md && git commit -m "Add the managed-Postgres backup retention window to the ops runbook"`.

### Task 2: Schema

- [ ] **Step 1:** `render ssh original-pilot -- python -m alembic upgrade head` → completes without error; `render ssh original-pilot -- python -m alembic current` shows the head revision. Failure = migration bug against managed PG — STOP, it must be fixed in code before any data moves.

### Task 3: Restore drills — BEFORE the window (O5 closes here)

- [ ] **Step 1 (SQLite side):** `python scripts/restore_drill.py` → exactly `PASS: backup opens and sanity tables are queryable.` + exit 0. An empty-backup failure is a real finding about the backup scheduler — STOP.
- [ ] **Step 2 (Postgres rehearsal):** `pg_dump "$DATABASE_URL" --format=custom --file /tmp/drill.dump && createdb orig_restore_drill && pg_restore --dbname orig_restore_drill --clean --if-exists /tmp/drill.dump && psql orig_restore_drill -c "SELECT count(*) FROM student_profiles;"` → restores cleanly (count may be 0 pre-migration; the drill proves the pipeline, not the data).
- [ ] **Step 3:** Two PILOT_LOG lines (both drills, dates, outcomes); commit: `git commit -m "Add restore-drill records (SQLite and Postgres) to the pilot log"`.

### Task 4: Shadow + synthetic exercise

- [ ] **Step 1 (⛔ HUMAN):** Dashboard → `REPO_SHADOW=postgres` → deploy.
- [ ] **Step 2:** Drive writes through the real API with a throwaway tenant: PROVISIONING_CHECKLIST §1–2 guarded curls (`X-Guard-Token`) to create tenant `cutover-drill`, one professor, a few students/baselines; then delete via the guarded delete. This exercises the dual-write path end to end.
- [ ] **Step 3:** Over 24–48h: `render logs --tail 100000 | grep "REPO_SHADOW divergence"` → **zero lines**. Any divergence is a real repository-parity bug — STOP, BLOCKED, fix in code, restart the soak clock.

### Task 5: The window

- [ ] **Step 1 (⛔ HUMAN):** `MAINTENANCE_MODE=1` → deploy. Verify: `GET /health` still 200; any write returns 503 with `Retry-After`.
- [ ] **Step 2:** `render ssh original-pilot -- env ORIGINAL_DB=/data/profiles.db DATABASE_URL=<pg-url> python -m scripts.migrate_sqlite_to_pg --dry-run --report /tmp/cutover-report.json` → **abort the window unless it prints `overall parity: OK`**. Record the report's `student_profiles` count `<n>`.
- [ ] **Step 3 (⛔ HUMAN):** `REPO_BACKEND=postgres` → deploy.
- [ ] **Step 4:** `python -m scripts.pilot_smoke_test --base-url https://original-pilot.onrender.com --expect-count <n>` → exactly `smoke test: PASS`. A `backend: sqlite` failure means the flip didn't apply — roll back per the constraint above.
- [ ] **Step 5 (⛔ HUMAN):** Unset `MAINTENANCE_MODE` → deploy. Verify one real write succeeds and `/health` shows `"backend":"postgres"`.

### Task 6: Close out

- [ ] **Step 1:** `/data/profiles.db` stays read-only on disk **≥4 weeks**; log the earliest-forfeit date (= cutover + 28d) in PILOT_LOG. From now on the post-deploy verifier is `pilot_smoke_test`, not `o1_golive_check`.
- [ ] **Step 2:** Start the nightly off-box habit: `pg_dump "$DATABASE_URL" --format=custom --file ~/orig-backups/orig-$(date +%Y%m%d).dump`.
- [ ] **Step 3:** `python -m scripts.tier17_report --db "$DATABASE_URL"` → expect `## Verdict: **NOT READY**` (no keystroke samples exist yet — that is the correct reading; record it, don't fake it). This clears the 2026-08-13 `BLOCKED` PILOT_LOG entry with a measurement.
- [ ] **Step 4:** PILOT_LOG lines (cutover date+sha, smoke PASS, rollback-floor date, tier17 first reading); index row Part 5 → `done @ smoke PASS <date>`; `git add docs/PILOT_LOG.md docs/superpowers/plans/2026-09-07-mvp-launch-index.md && git commit -m "Add Postgres cutover and drill records to the pilot log"`.

## Self-Review Notes

- The ceremony sequence, parity line, and smoke contract are verbatim from OPS_RUNBOOK:183-231 and the two scripts' docstrings (verified 2026-09-07). The compressed-soak decision is this plan's own reconciliation of the runbook against the master plan's "with zero users, no freeze window is needed" — it is recorded here deliberately so a future reader sees a decision, not an oversight.
- `render ssh` syntax for env-prefixed commands may need adjusting on the day (the runbook shows both forms); the invariant is the command, not the transport.
