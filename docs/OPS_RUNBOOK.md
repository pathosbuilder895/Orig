# Original Pilot — Operations Runbook

Written for a stranger: if the regular operator is unavailable, this is enough
to keep the pilot alive. The pilot is the `render.yaml` blueprint on Render: one
web service (`original-pilot`) running the dashboard app
(`python run.py --demo --port $PORT --skip-seed`) hardened by `ORIGINAL_ENV=pilot`,
backed by a managed Postgres 16 database (`original-db`, `REPO_BACKEND=postgres`).
The web service has no disk. Every deploy runs `alembic upgrade head` before the
new code takes traffic. `docs/BLUEBOOK_LAUNCH_CHECKLIST.md` is the setup, step by
step; `docs/STATUS.md` records what is deployed right now.

## The pilot service

| Resource | Plan | Purpose | Data |
|---|---|---|---|
| `original-pilot` | web, starter, no disk | the invitation-only Bluebook pilot: each invited independent teacher gets a private workspace | none on the instance; everything is in `original-db` |
| `original-db` | Postgres 16, basic-256mb | the pilot's database; internal-only (`ipAllowList: []`), so only Render services and the Render Shell reach it | every account, class, writing session and submission |
| `original-pg-backup` | cron, starter, 08:30 UTC daily | encrypted off-box backup (`scripts/pg_backup_offbox.py --require-upload`), see [Backups](#backups) | writes one encrypted dump a day to a bucket outside Render |
| `bluebook-teacher-demo` | static site | the fictional teacher walkthrough, on its own address | none: no API, no accounts, no student data |

**One worker, one instance:** the pilot runs a single uvicorn worker (`run.py`) on one instance, and the login throttle (`original/routers/_shared.py`), the tenant environment and product caches (`original/principal.py`) and the genre-stats cache (`original/store.py`) live in that process's memory and assume it, so do not add instances or workers.

The `original-demo` sales-demo service has been removed from the blueprint. If one
still exists in the Render dashboard, the owner suspends it. Never run sales demos on
`original-pilot`.

## Secrets (Render dashboard → original-pilot → Environment)

| Var | What | Provision |
|---|---|---|
| `SECRET_KEY` | signs every session token; service REFUSES to boot without it | Render Blueprint `generateValue: true` (256-bit); existing value retained |
| `MAINTENANCE_TOKEN` | `X-Guard-Token` header for provisioning/destructive endpoints; also the demo-only break-glass admin password — see [Destructive-endpoint guard](#destructive-endpoint-guard-maintenance_token--guard_destructive) | Independently Render-generated via `generateValue: true` (256-bit); existing value retained |
| `LTI_PRIVATE_KEY` | tool RSA key for LTI | `openssl genrsa 2048` (paste PEM, `\n`-escaped) |
| `LTI_PLATFORMS` | JSON array binding the Canvas issuer/client_id → tenant | see docs/CANVAS_RUNBOOK.md |
| `BBOOK_API_URL` | base URL of the external Bbook exam app; unset = `/students/{id}/request-baseline` returns 503 with manual-upload guidance | from the Bbook deployment |
| `BBOOK_EXTERNAL_SECRET` | shared secret sent as the `x-external-secret` header to Bbook; must EQUAL the value configured on the Bbook side — generate once, paste into both dashboards | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |

Blueprint syncs ignore `sync: false` vars, so adding `BBOOK_*` to
`render.yaml` did not prompt anyone for values — both stay unset (and the
endpoint stays 503) until an operator sets them here by hand. The in-repo
`/bluebook/` exam room does not use them.

For a new Blueprint, Render generates `SECRET_KEY` and `MAINTENANCE_TOKEN`
independently. Routine
Blueprint syncs and deploys retain existing values; they do not rotate exposed
credentials. All other provider and backup credentials remain operator-managed.
Never reuse a known-exposed value. For a deliberate rotation, generate a fresh
value (for example `python -c "import secrets; print(secrets.token_urlsafe(48))"`)
and replace only the intended dashboard variable outside teaching hours.
Never commit, log, screenshot or paste credentials into chat.

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
   door. `render.yaml` sets `GUARD_DESTRUCTIVE=1` on `original-pilot`. (The
   old `original-demo` service, removed from the blueprint, left it unset so
   the sales demo stayed click-through.) Set it only on a real deploy: with
   `ORIGINAL_ENV` anything but `pilot`/`staging`/`production` (unset means
   `demo`) the app refuses to boot with a `RuntimeError` naming
   `GUARD_DESTRUCTIVE` (T-23), because the demo surfaces, including the
   backdoor in item 2, stay open there.
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

**Rotated 2026-08-07 — this action item is closed.** `SECRET_KEY`,
`MAINTENANCE_TOKEN` and the LTI RSA key were all regenerated before the first
deploy, so nothing was invalidated (there were no live sessions yet). The
`MAINTENANCE_TOKEN` in use since then is a full `token_urlsafe(48)`; the
retired one was 43 chars. The superseded 2026-07-18 values are in
`~/Desktop/Original-secrets/rotated-out-2026-08-07/` and must not be reused —
they leaked into an assistant session transcript, which is what prompted the
rotation.

**Rotated 2026-08-11: LTI RSA key only, third occurrence of the same failure
class.** The 2026-08-07 LTI private key leaked into another assistant session
transcript (a secrets-file parsing attempt echoed line content; see
`~/.claude/projects/-Users-andrew-Desktop-Original/memory/feedback_never_print_secrets_files.md`
for the hardened handling rule going forward). Regenerated before any deploy
exists, so this rotation is zero-risk: the tool key signs nothing today, and
Canvas's developer key uses the `Public JWK URL` method
(`docs/canvas_developer_key.md`), so no re-registration is needed regardless.
New kid `aae43f60dabc7388` (was `7939c6c8a6f9a736`). `SECRET_KEY` and
`MAINTENANCE_TOKEN` were **not** affected this time and were not rotated. The
2026-08-07 LTI key is superseded in
`~/Desktop/Original-secrets/rotated-out-2026-08-11/` and must not be reused.

## Backups

The pilot's data lives only in `original-db`. There are two independent copies
of it:

- **Render's own (automatic).** `original-db` is on a paid plan, so it does not
  expire and Render takes daily snapshots of it (`render.yaml`). Retention and
  any point-in-time recovery depend on the plan: **confirm them in the Render
  dashboard** and record them here once known. These copies live with the same
  provider as the database.
- **Off-box (automatic, daily).** The `original-pg-backup` cron job runs
  `python scripts/pg_backup_offbox.py --require-upload` at 08:30 UTC. It reads
  every live table into one gzipped JSON-lines dump, encrypts it with
  `BACKUP_ENCRYPTION_KEY` (Fernet) and uploads only the encrypted file, as
  `original-pg-backups/original-pg-YYYYmmddTHHMMSSZ.jsonl.gz.fernet`, to the
  S3-compatible bucket set by the job's `BACKUP_OFFBOX_*` variables. Because of
  `--require-upload`, a missing bucket setting is a failed run in the
  dashboard rather than a silent no-op; a missing or malformed key fails the
  run before the database is read, so the job never uploads a readable dump.
  Check it: Render → `original-pg-backup` → the last run succeeded, and the
  bucket gains one object a day. The bucket's lifecycle rule (the launch
  checklist suggests deleting objects after 35 days) decides how far back you
  can go.
- **The key.** `BACKUP_ENCRYPTION_KEY` is set only on `original-pg-backup`, with
  a copy in the owner's password manager. Without it no backup can be restored.

The in-app SQLite backup scheduler (`original/backup.py`, `BACKUP_DIR`,
`BACKUP_INTERVAL_MINUTES`, `BACKUP_KEEP`) does not run on the pilot: with the
Postgres backend the boot log says
`Backups: in-app SQLite scheduler off (Postgres backend; backups managed externally).`

### Restore drill (once before the first teacher is invited, then each term)

A backup that has never been restored is a wish. Restore into a scratch
database, never the live one, from a checkout of the deployed commit with the
pilot requirements installed (`pip install -r requirements-pilot.lock.txt`),
on a machine you trust with student writing:

```bash
# In this shell only, export original-pg-backup's bucket settings from the
# password manager: BACKUP_OFFBOX_BUCKET, _ENDPOINT, _REGION, _ACCESS_KEY_ID
# and _SECRET_ACCESS_KEY. Not BACKUP_OFFBOX_ENABLED: a drill never uploads.
export BACKUP_OFFBOX_PREFIX=original-pg-backups/

createdb restore_drill   # any empty Postgres you control
BACKUP_ENCRYPTION_KEY=<from the password manager> \
  python scripts/restore_drill.py --database-url 'postgresql://localhost/restore_drill'
# Or pass an already-downloaded encrypted backup as the final argument:
BACKUP_ENCRYPTION_KEY=<from the password manager> \
  python scripts/restore_drill.py --database-url 'postgresql://localhost/restore_drill' \
  ~/restore-drill/original-pg-YYYYmmddTHHMMSSZ.jsonl.gz.fernet
```

With no file argument, the drill lists the bucket under the configured prefix
and restores the newest encrypted `original-pg-*.jsonl.gz.fernet` directly. It
requires the bucket settings and `BACKUP_ENCRYPTION_KEY`; it decrypts only to a
private temporary file and deletes that plaintext after the run. The report
lists every table's restored and expected row counts and checksums, ending in
`restore parity: OK`. It creates the schema in the explicit scratch database,
refuses a non-empty target, and refuses a URL matching the shell's configured
`DATABASE_URL`. Do not set the scratch URL as `DATABASE_URL` for this command.
Afterwards drop the scratch database and add a line to `docs/PILOT_LOG.md`.

## Database loss or corruption

1. If the service is still up, freeze writes: `MAINTENANCE_MODE=1` → deploy.
2. Prefer Render's own recovery for `original-db` (dashboard) when the damage
   falls inside what the plan retains: it loses the least data.
3. Otherwise restore the newest off-box dump into a fresh, empty Render
   Postgres in the same region, created like `original-db` with no outside
   access (`ipAllowList: []`). It accepts connections only from inside
   Render, so run the restore from Render →
   `original-pilot` → Shell. In that shell session only, export `DATABASE_URL`
   as the new database's internal URL, plus the bucket settings (as in the
   drill) and `BACKUP_ENCRYPTION_KEY`:
   ```bash
   alembic upgrade head
   FILE=$(python scripts/pg_backup_offbox.py --download-latest /tmp/restore) &&
     python scripts/pg_backup_offbox.py --restore "$FILE"
   rm -r /tmp/restore
   ```
   It must end `restore parity: OK`. Then point `DATABASE_URL` on
   `original-pilot` and `original-pg-backup` at the new database, and make
   `render.yaml` match before the next Blueprint sync.
4. Unset `MAINTENANCE_MODE` → deploy. Hit `/health`, sign in as a teacher and
   open one sealed submission.
5. Anything written after the restored backup is gone. Tell each affected
   teacher which window was lost (the restored audit log shows the last
   captured action).

## Deploys

- Flow: branch → PR → CI green → merge to `main` → **manual deploy from the
  Render dashboard** (`autoDeploy: false` on `original-pilot`). Confirm in the
  dashboard that the services deploy from `main`; `docs/STATUS.md` records
  what is live. Each deploy first runs `alembic upgrade head` (the pre-deploy
  step): a failed migration fails the deploy and the old version keeps
  serving. With no disk attached, deploys are zero-downtime.
- **Never deploy during a writing session a teacher has told you about.**
- **After every deploy, verify it:**
  `python -m scripts.pilot_smoke_test --base-url https://original-pilot.onrender.com --bluebook`
  must end `smoke test: PASS` (backend `postgres`, environment `pilot`, site and
  legal pages up, API docs hidden, anonymous calls refused).
  `scripts/o1_golive_check.py` targets the deferred LTI/SQLite configuration
  (it asserts `backend == "sqlite"`) and does not apply to this pilot.
- **Rollback (code):** Render dashboard → `original-pilot` → previous deploy →
  "Rollback". The schema changes are additive, so older code runs against the
  newer schema; a code rollback alone is the normal case.
- **Rollback (schema), only when a migration itself must be undone:** the
  database is internal-only, so run it from Render → `original-pilot` → Shell,
  where `DATABASE_URL` is already set: `alembic downgrade -1`. Do it **before**
  the code rollback, while the newer build is still deployed: the older build
  does not contain the newer migration file, and alembic cannot step down
  from a revision it cannot find (a deploy of the older commit would fail its
  pre-deploy `alembic upgrade head` for the same reason). A downgrade drops
  the tables and columns its upgrade added, with their data, so first trigger
  an `original-pg-backup` run and confirm it succeeded.
- After editing any `demo/bluebook/*.jsx`: `cd demo/bluebook && npm run build`
  and commit the regenerated `bluebook.bundle.js`: Render does not run Node.
- **Tag every production deploy** as `pilot-YYYY-MM-DD`, on the sha you deployed:
  `git tag pilot-2026-07-24 <sha> && git push origin --tags`. If more than one
  deploy lands on the same date, suffix `-2`, `-3`, ... The tag is what
  "roll back to last Friday" resolves to: find the tag nearest that date
  (`git log --tags --simplify-by-decoration --oneline`) and use its sha with
  the Render rollback in the section above.

## Postgres cutover (WS-6 P5 — the one user-visible migration)

> **2026-10 — not needed for a fresh launch.** `render.yaml` now starts
> `original-pilot` on managed Postgres from its first deploy (`REPO_BACKEND=postgres`,
> `alembic upgrade head` as the pre-deploy step, no disk), because the pilot
> never served production traffic on SQLite. Follow
> `docs/BLUEBOOK_LAUNCH_CHECKLIST.md` instead. This section applies only to a
> deployment that already holds real data in SQLite.

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

- Render's service health check should remain `/health`: it runs a bounded
  `SELECT 1` against the active database and returns 503 when the database is
  unavailable. `/livez` is a fast process-only liveness probe for systems that
  specifically need to distinguish a running process from database readiness.
  Do not use `/livez` as the pilot availability alert because it intentionally
  stays 200 during a database outage. The Render dashboard setting is not
  changed by this code; Andrew can confirm the path there after deployment.
- UptimeRobot (or BetterStack) on `https://original-pilot.onrender.com/health`,
  1–5 min interval, alert → operator email. `/health` returns student count —
  a sudden drop to 0 with a 200 status also means trouble.
- Weekly: Render → Logs → filter `5xx`, `denied`, `429`; Render → Metrics →
  memory (Starter has ~512 MB; spacy loads ~150 MB at boot), and the storage
  use of `original-db`.

## Routine maintenance

### Dependency-update policy

Do not mass-merge Dependabot changes. Any npm update under `demo/bluebook/`
must rebuild and commit `bluebook.bundle.js` in the same PR. Python updates
touching the scoring/runtime stack (including pydantic, Starlette, and httpx)
require the full local suite and Postgres marker suite before merge. Any
scikit-learn or joblib movement additionally triggers the AI-detector and
style-authorship artifact self-tests: both loaders compare stored reference
predictions and fail closed on drift. If AI reference predictions move by
more than 0.02, retrain with `scripts/train_ai_detector.py` and commit a new
artifact; never hide version drift by pinning around it. Apply the equivalent
retrain/self-test discipline to `style_authorship_v1.joblib`.

| Cadence | Action |
|---|---|
| daily | `original-pg-backup` and the uptime monitor run themselves; glance that the backup's last run succeeded |
| weekly (~1 h) | log scan; database storage use; teacher office hour; update `PILOT_LOG.md` |
| each term | restore drill (see [Backups](#backups)) |
| after sales demos | `python scripts/reset_demo_data.py --apply` **on the demo service** (touches only the `demo` tenant — verified safe, but never run against the pilot DB casually) |
| per release | suite green locally (`.venv/bin/python -m pytest tests/ -q`), bundle rebuilt if JSX changed |

## Known limits (don't get paged for these)

- Render free tier (demo service) sleeps after idle — first demo hit takes ~30 s. Warm it before a sales call.
- The login throttle (10 attempts / 5 min / IP) is in-memory: a restart clears it. That's acceptable for a pilot.
- 5 `TestAuthEndpoints` tests are marked xfail for rate-limit exhaustion when the full suite runs — pre-existing, not a regression signal.
