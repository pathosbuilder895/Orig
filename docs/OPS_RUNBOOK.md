# Original Pilot — Operations Runbook

Written for a stranger: if the regular operator is unavailable, this is enough
to keep the pilot alive. The pilot is one Render web service (`original-pilot`)
running the dashboard app (`python run.py --demo`) hardened by `ORIGINAL_ENV=pilot`,
with SQLite on a persistent disk at `/data/profiles.db`.

## The two services

| Service | Plan | Purpose | Data |
|---|---|---|---|
| `original-demo` | free | zero-login sales demo | ephemeral, reseeds from `demo/seed.db` |
| `original-pilot` | starter + 1 GB disk | the real institution | persistent SQLite at `/data/profiles.db` |

Never point a professor at `original-demo`. Never run sales demos on `original-pilot`.

## Secrets (Render dashboard → original-pilot → Environment)

| Var | What | Generate |
|---|---|---|
| `SECRET_KEY` | signs every session token; service REFUSES to boot without it | `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `MAINTENANCE_TOKEN` | `X-Guard-Token` header for provisioning/destructive endpoints; also the demo-only break-glass admin password — see [Destructive-endpoint guard](#destructive-endpoint-guard-maintenance_token--guard_destructive) | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `LTI_PRIVATE_KEY` | tool RSA key for LTI | `openssl genrsa 2048` (paste PEM, `\n`-escaped) |
| `LTI_PLATFORMS` | JSON array binding the Canvas issuer/client_id → tenant | see docs/CANVAS_RUNBOOK.md |

Keep copies in the password manager. **Rotating `SECRET_KEY` logs everyone out**
(tokens are stateless); do it outside teaching hours and tell the professors.

## Destructive-endpoint guard (MAINTENANCE_TOKEN + GUARD_DESTRUCTIVE)

`MAINTENANCE_TOKEN` has two distinct effects — both keyed off the same env
var, only one of which is live on the pilot:

1. **Destructive-endpoint guard (live on the pilot).** `GUARD_DESTRUCTIVE=1`
   makes `_require_guard` (`original/api.py`) require an `X-Guard-Token`
   header equal to `MAINTENANCE_TOKEN` on every guarded endpoint: student
   deletion, tenant writes, calibration-threshold apply, baseline-request
   list, admin corrections. Requests without a matching header get **403**.
   If `GUARD_DESTRUCTIVE=1` is set but `MAINTENANCE_TOKEN` is empty, those
   endpoints return **503** instead — a misconfiguration signal, not an open
   door. `render.yaml` sets `GUARD_DESTRUCTIVE=1` on `original-pilot`; the
   free `original-demo` service leaves it unset so the sales demo stays
   click-through.
2. **Demo-only admin-login backdoor (not live on the pilot).** The same
   `MAINTENANCE_TOKEN` value, presented as the password to
   `POST /api/v1/auth/login`, grants the **admin** role and writes a WARNING
   audit log entry. This path is 404'd on real deploys (`_IS_REAL_DEPLOY` in
   `original/api.py`), so it has no effect on `original-pilot` — but it does
   mean the token is a live admin password on any demo/dev deployment where
   `_IS_REAL_DEPLOY` is false. Treat the value as sensitive everywhere, not
   just where the guard is active: never put it in a demo config, README, or
   commit.

**Rotation:** change the env var in the Render dashboard and restart the
service — no code deploy needed. Unlike `SECRET_KEY`, rotating
`MAINTENANCE_TOKEN` does **not** log anyone out (it isn't used to sign
sessions). Rotation is a scheduled action — do not restart the pilot to
rotate it without operator sign-off (server restarts require explicit
permission per project policy).

**Action item:** rotate the pilot's `MAINTENANCE_TOKEN` if the current value
predates this documentation — it may have been set before its dual role
(guard token + demo admin password) was understood.

## Backups

The pilot's backup story changes at the WS-6 P5 cutover (SQLite → Postgres).
Both procedures are documented here; **follow the one matching where the
pilot currently runs** (check `GET /health` → `environment`, and whether
`DATABASE_URL` is set in the Render dashboard — a live `DATABASE_URL` with
`get_repository()` flipped to Postgres means you are post-cutover).

### While on SQLite (current — pre-P5)

- **On-disk (automatic, in-app):** the web process itself runs a backup
  scheduler (`original/backup.py`, started by the API lifespan) — a
  **consistent online** SQLite `.backup` to `BACKUP_DIR` (render.yaml pins
  `/data/backups`) every `BACKUP_INTERVAL_MINUTES` (30), pruned to
  `BACKUP_KEEP` (48). No cron required — Render web services have no crontab,
  and a Render cron job cannot mount this service's disk, which is why this
  runs in-process. Verify anytime: `GET /admin/health` (staff login) →
  `last_backup_age_seconds` should stay under ~3600.
- `scripts/backup_db.sh [dest] [keep]` is the same backup for manual/local
  use (safe while serving; uses `.backup`, never `cp` a WAL database).
- **Off-box (manual, daily):** the disk and its on-disk backups die together —
  pull a copy daily from the operator's machine:
  `render ssh original-pilot -- cat /data/backups/$(date +profiles-%Y%m%d)*.db > ~/orig-backups/...`
  (or scp). The off-box copy is the real backup.
- **Weekly restore drill:** copy the newest backup locally,
  `sqlite3 backup.db "SELECT COUNT(*) FROM student_profiles;"` and compare with
  `/students` on the live service. A backup that's never been restored is a wish.

### After the Postgres cutover (P5+)

Once the pilot runs on Render managed Postgres, the in-app SQLite scheduler
(`original/backup.py`) no longer backs up the authoritative store — Postgres
does. `BACKUP_DIR`/`BACKUP_INTERVAL_MINUTES`/`BACKUP_KEEP` become no-ops for
the live data (the SQLite file, kept read-only for ≥4 weeks as the P5
rollback, still exists but is frozen).

- **Managed (automatic):** Render's managed Postgres takes automatic daily
  backups; retention and point-in-time-recovery depth depend on the instance
  plan tier — **confirm the pilot tier's retention window in the Render
  dashboard** and record it here once known. This is the primary backup.
- **Off-box (nightly `pg_dump`):** the managed backups live inside Render, so
  keep an independent off-box copy the same way the SQLite off-box copy
  worked. From the operator's machine (or a scheduled job with the Render
  external connection string):
  `pg_dump "$DATABASE_URL" --format=custom --file ~/orig-backups/orig-$(date +%Y%m%d).dump`
  The custom format restores with `pg_restore` and is compressed. FERPA: run
  over the Render-provided TLS connection string; never leave the dump on a
  shared machine.
- **Restore drill (rehearse BEFORE cutover, then monthly):** restore the
  newest dump into a **scratch** database (never the live one) and compare row
  counts against the live service:
  `createdb orig_restore_drill && pg_restore --dbname orig_restore_drill --clean --if-exists ~/orig-backups/orig-YYYYMMDD.dump`
  then `psql orig_restore_drill -c "SELECT count(*) FROM student_profiles;"`
  and compare with `/students` on the live service. The P4 acceptance bar
  requires one successful restore drill on staging before the P5 window opens.

## Disk-loss / corruption recovery

**On SQLite (pre-P5):**

1. Create a fresh disk (Render dashboard) or redeploy the service.
2. Upload the newest off-box backup to `/data/profiles.db`
   (`render ssh` + scp, service suspended while copying).
3. Resume, hit `/health`, then spot-check one professor login and one student profile.
4. Anything written after the last backup is gone — tell the professors which
   window was lost (audit log in the backup shows the last captured action).

**On Postgres (post-P5):**

1. Prefer Render's point-in-time recovery (dashboard) if the corruption window
   is inside the retention tier — it loses the least data.
2. Otherwise provision a fresh managed Postgres, `pg_restore` the newest
   off-box dump into it, and point `DATABASE_URL` at it (redeploy).
3. Hit `/health`, spot-check a professor login and a student profile.
4. Data written after the restored dump/PITR point is gone — same disclosure
   to professors as the SQLite case (the audit log in the restore shows the
   last captured action).
5. The frozen read-only SQLite file from the P5 cutover is the last-resort
   floor if Postgres backups are also lost within the ≥4-week rollback window.

## Deploys

- Flow: branch → PR → CI green → merge to `main` → **manual deploy from the
  Render dashboard** (`autoDeploy: false` on original-pilot; disk-backed
  services deploy stop-then-start, so a merge must never take the service
  down on its own). The demo service may keep auto-deploy.
- **Never deploy during a scheduled exam** (shared exam calendar with professors).
- Rollback = Render dashboard → previous deploy → "Rollback". SQLite schema is
  additive (`CREATE TABLE IF NOT EXISTS`), so rolling back code is safe.
- After editing any `demo/bluebook/*.jsx`: `cd demo/bluebook && npm run build`
  and commit the regenerated `bluebook.bundle.js` — Render does not run Node.
- **Tag every production deploy** — `pilot-YYYY-MM-DD`, on the sha you deployed:
  `git tag pilot-2026-07-24 <sha> && git push origin --tags`. If more than one
  deploy lands on the same date, suffix `-2`, `-3`, ... The tag is what
  "roll back to last Friday" resolves to — find the tag nearest that date
  (`git log --tags --simplify-by-decoration --oneline`) and use its sha with
  the Render rollback in the section above.

## Postgres cutover (WS-6 P5 — the one user-visible migration)

This is the SQLite → Postgres cutover. It is a **single scheduled maintenance
window**. The code ships inert: the app runs on SQLite until an operator sets
`REPO_BACKEND=postgres`, and rolling back is unsetting that one variable. All
four controls are `sync: false` in `render.yaml` (dashboard-managed, unset by
default).

**Do not start the window until all prerequisites are met** (WS-6 P5 entry gate):
- The managed Render Postgres exists and `alembic upgrade head` has provisioned
  its schema (`DATABASE_URL` set in the dashboard).
- **Shadow soak passed:** `REPO_SHADOW=postgres` ran against real pilot traffic
  for 1–2 weeks with **zero unexplained divergences** in the logs
  (grep `REPO_SHADOW divergence`).
- **Restore drill passed** on staging (see Backups → restore drill).
- Owner sign-off; window scheduled outside any exam (shared calendar).

**The window (writes are frozen for its duration — keep it short):**

1. **Freeze writes.** Dashboard → `MAINTENANCE_MODE=1` → deploy. Verify:
   `GET /health` still 200; any write (`POST …`) returns 503 with `Retry-After`.
2. **Final parity check.** With the shadow soak, Postgres is already current, so
   this is a *verification*, not a re-migration. On the Render host / over the
   TLS tunnel:
   `ORIGINAL_DB=/data/profiles.db DATABASE_URL=<pg-url> python -m scripts.migrate_sqlite_to_pg --dry-run --report /tmp/cutover-report.json`
   — **abort if it does not print `overall parity: OK`.** Record the
   `student_profiles` row count for step 5. (Cutting over *without* a prior
   shadow soak instead: drop `--dry-run` to run the full one-shot migration into
   an empty Postgres.)
3. **Flip the backend.** Dashboard → `REPO_BACKEND=postgres` → deploy.
4. **Keep the SQLite file as the rollback floor.** Do **not** delete
   `/data/profiles.db`; it stays read-only on disk for **≥4 weeks**. (The app no
   longer writes to it once `REPO_BACKEND=postgres`.)
5. **Smoke test.**
   `python -m scripts.pilot_smoke_test --base-url https://original-pilot.onrender.com --expect-count <count-from-step-2>`
   Must print `smoke test: PASS` — it confirms `/health.backend == "postgres"`
   and the student count matches. Abort → rollback (below) if it fails.
6. **Unfreeze.** Dashboard → unset `MAINTENANCE_MODE` → deploy. Confirm a real
   write succeeds and `GET /health` shows `"backend":"postgres"`.
7. Tell professors the window is closed.

**Rollback (instant, for ≥4 weeks after cutover):**
- Dashboard → **unset `REPO_BACKEND`** (and unset `MAINTENANCE_MODE` if still
  set) → deploy. The app is back on the read-only SQLite file exactly as before
  the window. This is the whole reason the file is kept — writes made on
  Postgres after cutover are lost on rollback, so only roll back for a genuine
  cutover failure, and tell professors which window was lost.
- After the ≥4-week soak with no issues, WS-6 P6 removes the SQLite path and the
  dormant v1 stack; the rollback floor is intentionally forfeited then.

## Monitoring

- UptimeRobot (or BetterStack) on `https://original-pilot.onrender.com/health`,
  1–5 min interval, alert → operator email. `/health` returns student count —
  a sudden drop to 0 with a 200 status also means trouble.
- Weekly: Render → Logs → filter `5xx`, `denied`, `429`; Render → Metrics →
  memory (Starter has ~512 MB; spacy loads ~150 MB at boot) and `/data` usage.

## Routine maintenance

| Cadence | Action |
|---|---|
| daily | off-box backup pull (manual); uptime monitor + in-app backups run themselves |
| weekly (~1 h) | restore drill; log scan; disk usage; professor office hour; update `PILOT_LOG.md` |
| after sales demos | `python scripts/reset_demo_data.py --apply` **on the demo service** (touches only the `demo` tenant — verified safe, but never run against the pilot DB casually) |
| per release | suite green locally (`.venv/bin/python -m pytest tests/ -q`), bundle rebuilt if JSX changed |

## Known limits (don't get paged for these)

- Render free tier (demo service) sleeps after idle — first demo hit takes ~30 s. Warm it before a sales call.
- The login throttle (10 attempts / 5 min / IP) is in-memory: a restart clears it. That's acceptable for a pilot.
- 5 `TestAuthEndpoints` tests are marked xfail for rate-limit exhaustion when the full suite runs — pre-existing, not a regression signal.
