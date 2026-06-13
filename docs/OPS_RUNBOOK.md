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
| `MAINTENANCE_TOKEN` | `X-Guard-Token` header for provisioning/destructive endpoints | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `LTI_PRIVATE_KEY` | tool RSA key for LTI | `openssl genrsa 2048` (paste PEM, `\n`-escaped) |
| `LTI_PLATFORMS` | JSON array binding the Canvas issuer/client_id → tenant | see docs/CANVAS_RUNBOOK.md |

Keep copies in the password manager. **Rotating `SECRET_KEY` logs everyone out**
(tokens are stateless); do it outside teaching hours and tell the professors.

## Backups

- `scripts/backup_db.sh [dest] [keep]` does a **consistent online** SQLite backup
  (safe while serving; uses `.backup`, never `cp` a WAL database).
- Schedule: Render Cron Job (same repo) →
  `bash scripts/backup_db.sh /data/backups 48` every 30 min, AND a daily
  **off-box pull** from the operator's machine:
  `render ssh original-pilot -- cat /data/backups/$(date +profiles-%Y%m%d)*.db > ~/orig-backups/...`
  (or scp). The disk and its on-disk backups die together — the off-box copy is
  the real backup.
- **Weekly restore drill:** copy the newest backup locally,
  `sqlite3 backup.db "SELECT COUNT(*) FROM student_profiles;"` and compare with
  `/students` on the live service. A backup that's never been restored is a wish.

## Disk-loss / corruption recovery

1. Create a fresh disk (Render dashboard) or redeploy the service.
2. Upload the newest off-box backup to `/data/profiles.db`
   (`render ssh` + scp, service suspended while copying).
3. Resume, hit `/health`, then spot-check one professor login and one student profile.
4. Anything written after the last backup is gone — tell the professors which
   window was lost (audit log in the backup shows the last captured action).

## Deploys

- Flow: branch → PR → CI green → merge to `main` → Render auto-deploy.
- **Never deploy during a scheduled exam** (shared exam calendar with professors).
- Rollback = Render dashboard → previous deploy → "Rollback". SQLite schema is
  additive (`CREATE TABLE IF NOT EXISTS`), so rolling back code is safe.
- After editing any `demo/bluebook/*.jsx`: `cd demo/bluebook && npm run build`
  and commit the regenerated `bluebook.bundle.js` — Render does not run Node.

## Monitoring

- UptimeRobot (or BetterStack) on `https://original-pilot.onrender.com/health`,
  1–5 min interval, alert → operator email. `/health` returns student count —
  a sudden drop to 0 with a 200 status also means trouble.
- Weekly: Render → Logs → filter `5xx`, `denied`, `429`; Render → Metrics →
  memory (Starter has ~512 MB; spacy loads ~150 MB at boot) and `/data` usage.

## Routine maintenance

| Cadence | Action |
|---|---|
| daily (automated) | backup cron + off-box pull; uptime monitor |
| weekly (~1 h) | restore drill; log scan; disk usage; professor office hour; update `PILOT_LOG.md` |
| after sales demos | `python scripts/reset_demo_data.py --apply` **on the demo service** (touches only the `demo` tenant — verified safe, but never run against the pilot DB casually) |
| per release | suite green locally (`.venv/bin/python -m pytest tests/ -q`), bundle rebuilt if JSX changed |

## Known limits (don't get paged for these)

- Render free tier (demo service) sleeps after idle — first demo hit takes ~30 s. Warm it before a sales call.
- The login throttle (10 attempts / 5 min / IP) is in-memory: a restart clears it. That's acceptable for a pilot.
- 5 `TestAuthEndpoints` tests are marked xfail for rate-limit exhaustion when the full suite runs — pre-existing, not a regression signal.
