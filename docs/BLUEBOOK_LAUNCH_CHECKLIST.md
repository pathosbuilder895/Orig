# Bluebook public launch — checklist

The steps to take Bluebook from a merged `main` to a live, invitation-only
website: professors do not sign up, the operator invites each one with
`scripts/invite_professor.py`. Everything in code is done; what remains is
accounts, secrets, DNS and clicks only the owner can make. Work top to bottom.
Each step says what "done" looks like.

The deployment is `render.yaml`:

| Render resource | What it is |
|---|---|
| `original-db` | Managed Postgres 16 (paid plan, so it never expires; Render snapshots it daily). |
| `original-pilot` | The web service: the public Bluebook site at `/bluebook/` plus the Original pilot. Runs `alembic upgrade head` before every deploy. No disk. |
| `original-pg-backup` | Daily cron: a logical backup of the database to a bucket **outside** Render (`scripts/pg_backup_offbox.py`). |
| `bluebook-teacher-demo` | Static site (free, no environment variables): publishes the fictional professor walkthrough on its own address, with no API, accounts or student data (`scripts/build_teacher_demo_site.sh`). |

The blueprint no longer contains `original-demo` (Original's public demo on
`demo/seed.db`). If that Render service already exists, the owner suspends it
in the Render dashboard; the blueprint does not touch it.

The pilot is invitation-only (`SELF_SERVE_SIGNUP=0`): there is no signup on
the website. The operator invites each professor with
`scripts/invite_professor.py` (see *Operating it*), which creates a private,
Bluebook-only workspace (never profiled by Original) and emails a one-time
link to set a password. Use `docs/PROVISIONING_CHECKLIST.md` only for
institutions buying Original.

---

## 1. Merge

- [ ] Merge the launch PR into `main` once CI is green.

## 2. Accounts you need first (≈ 1 hour, mostly waiting on DNS)

- [ ] **Domain** (optional but recommended), e.g. `bluebook.example.org`. Without
  one, the site is `https://original-pilot.onrender.com/bluebook/`.
- [ ] **SendGrid** account (free tier covers 100 emails/day).
  - Settings → Sender Authentication → **Authenticate your domain**, add the
    CNAME records it gives you, wait until it shows *Verified*.
  - Settings → API Keys → create a key with **Restricted Access → Mail Send** only.
  - Done when: the domain shows *Verified* and you have the key (`SG.…`).
- [ ] **Backup bucket** on an S3-compatible store that is *not* Render — Cloudflare
  R2, Backblaze B2 or AWS S3.
  - Create a private bucket (e.g. `bluebook-backups`) and an access key limited
    to that bucket. Turn on a lifecycle rule to delete objects after, say, 35 days.
  - Note the endpoint (R2: `https://<account-id>.r2.cloudflarestorage.com`,
    region `auto`; B2: `https://s3.<region>.backblazeb2.com`).
- [ ] **Sentry** (optional; free tier is enough): new project, platform *FastAPI*,
  copy the DSN. The app sends no request bodies, no PII and no local variables
  (`original/monitoring.py`).
- [ ] **Uptime monitor** (UptimeRobot or BetterStack, free): you will point it at
  `/health` in step 6.

## 3. Create the Render resources

- [ ] Render → **New → Blueprint** → this repo, branch `main`. Render reads
  `render.yaml` and proposes exactly `original-db`, `original-pilot`,
  `original-pg-backup` and `bluebook-teacher-demo`. Approve. (An existing
  `original-demo` service is not part of the blueprint: suspend it yourself in
  the dashboard.)
- [ ] It then asks for every `sync: false` value. Fill them in (below). Values
  marked *generate* come from:
  `python -c "import secrets; print(secrets.token_urlsafe(64))"`

**`original-pilot`**

| Key | Value |
|---|---|
| `SECRET_KEY` | *generate*. Never reuse one that has appeared anywhere else. |
| `MAINTENANCE_TOKEN` | *generate* (a different one). |
| `SENDGRID_API_KEY` | the `SG.…` key |
| `MAIL_FROM` | `Bluebook <no-reply@your-domain>` — the address must be on the authenticated domain |
| `PUBLIC_BASE_URL` | `https://bluebook.example.org` (or `https://original-pilot.onrender.com`), no trailing slash |
| `SENTRY_DSN` | the DSN, or leave empty |
| `MAINTENANCE_MODE` | leave empty |
| `BBOOK_API_URL`, `BBOOK_EXTERNAL_SECRET`, `AI_LIKELIHOOD_SHADOW` | leave empty (Canvas and Original-only features; not needed for Bluebook) |

**`original-pg-backup`**

| Key | Value |
|---|---|
| `BACKUP_OFFBOX_BUCKET` | the bucket name |
| `BACKUP_OFFBOX_ENDPOINT` | the endpoint URL |
| `BACKUP_OFFBOX_REGION` | `auto` (R2) or the bucket's region |
| `BACKUP_OFFBOX_ACCESS_KEY_ID` / `BACKUP_OFFBOX_SECRET_ACCESS_KEY` | the bucket key |
| `BACKUP_ENCRYPTION_KEY` | generate with the command in render.yaml; store a copy in your password manager — losing it makes every backup unrecoverable |

- [ ] Done when: the first deploy of `original-pilot` is **Live**. Its deploy log
  shows `Running upgrade … -> a7d3c9e1b5f2` from the pre-deploy step, then the
  server starting.

## 4. Custom domain (skip if using the onrender.com address)

- [ ] `original-pilot` → Settings → Custom Domains → add the domain; add the DNS
  record Render shows; wait for the certificate.
- [ ] Environment → `ALLOWED_ORIGINS` = `https://bluebook.example.org,https://original-pilot.onrender.com`
  and `PUBLIC_BASE_URL` = `https://bluebook.example.org` → **Save, then Manual Deploy**.
- [ ] Optional: a redirect from the bare domain to `/bluebook/` at your DNS host.

## 5. Legal pages (before sending the link to anyone)

The pages in `demo/legal/` are drafts written to match what the software
actually does, with a DRAFT banner and bracketed blanks.

- [ ] Counsel reviews `privacy.html`, `terms.html`, `student-notice.html` and fills
  every `[bracketed]` item (legal entity, governing law, backup provider and
  region, contact address).
- [ ] When final: remove the DRAFT banner, set the `Version …` line under each
  page's title (the permanent line directly after the `<h1>`, not the one inside
  the banner), and set the same version string in `TERMS_VERSION` in **both**
  `original/routers/auth.py` and `demo/bluebook/Account.jsx`; rebuild the bundle
  (`cd demo/bluebook && npm run build`), commit, deploy. Signups and professor
  invitations record which version each teacher accepted in the audit log (an
  invited professor ticks the terms box when setting their first password).

## 6. Verify

- [ ] From a checkout:
  ```bash
  python -m scripts.pilot_smoke_test --base-url https://<host> --bluebook
  ```
  Must end `smoke test: PASS` (backend postgres, environment pilot, site and
  legal pages up, API docs hidden, anonymous calls refused).
- [ ] Walk it once by hand at `https://<host>/bluebook/`:
  1. Invite yourself: Render → `original-pilot` → Shell →
     `python scripts/invite_professor.py you@your-domain --name "Your Name"`.
     Open the link from the email (or the one the command printed), tick the
     terms box and set a password. You land in your own empty workspace.
  2. Courses → New course → add a second email address you own as a student,
     with **Email each student their invitation** ticked. The invitation
     arrives within a minute (check spam the first time).
  3. Examinations → New examination with two questions. As the student, set a
     password from the email link, sit it, seal it.
  4. As the teacher: Read & mark → give a mark and a comment → Release results.
     As the student, the mark and comment now show.
  5. Sign out → "Forgot your password?" → the reset email arrives.
- [ ] `original-pg-backup` → **Trigger Run**. Done when the run succeeds and an
  `original-pg-backups/original-pg-….jsonl.gz.fernet` object is in the bucket. A run
  that fails with "upload required but not configured" means a bucket setting
  is missing.
- [ ] Restore drill (once now, then each term): download that object, then
  against a scratch database (never the live one):
  ```bash
  createdb restore_drill   # or any empty Postgres
  DATABASE_URL=postgresql://…/restore_drill alembic upgrade head
  BACKUP_ENCRYPTION_KEY=<the key> DATABASE_URL=postgresql://…/restore_drill python scripts/pg_backup_offbox.py --restore original-pg-….jsonl.gz.fernet
  ```
  Must end `restore parity: OK`. It refuses a database that already has rows.
  The backup job refuses to upload when `BACKUP_ENCRYPTION_KEY` is unset. A file
  written with `--out` is an unencrypted local copy: keep it off shared disks and
  delete it when you are done.
- [ ] Uptime monitor → `https://<host>/health`, 5-minute interval, alert to your
  email. Done when its first check is green.
- [ ] Sentry (if set): the deploy log shows `Sentry error reporting is on`.

## 7. Launch

- [ ] Invite each professor (*Operating it* → Inviting a professor). They set a
  password from the link, then sign in at `https://<host>/bluebook/`.
- [ ] Tell Claude the URL: it will re-run the smoke test and walk the professor
  invite → student invite → exam → mark → release journey against the live
  site.

---

## Operating it

- **Inviting a professor** (the pilot is invitation-only, `SELF_SERVE_SIGNUP=0`):
  Render → `original-pilot` → Shell →
  `python scripts/invite_professor.py prof@school.edu --name "Dr Name"`.
  It prints the database backend it wrote to (`postgres` on the pilot),
  whether the email was sent, and always prints the single-use link (14 days).
  If the link expires or is lost before the professor has set a password, run
  the same command again: it issues a new link to the same workspace and the
  earlier links stop working. Once the professor has set a password the
  command refuses the address (as it does any address that belongs to a
  student); they use "Forgot your password?" on the sign-in page instead.
  Without `PUBLIC_BASE_URL` (or `--base-url`) the link is relative: it is not
  emailed and the command prints a warning.
- **Switching Original for a professor** (off by default; Bluebook stays on):
  invite with Original from the start with
  `python scripts/invite_professor.py prof@school.edu --with-original`, or
  switch an existing professor's workspace with
  `python scripts/set_products.py prof@school.edu --original on` (or `off`).
  The server applies the change within 30 seconds, with no restart; open pages
  pick it up the next time the professor or student loads their home page or
  signs in. A student mid-exam when Original is switched off still seals
  normally; that submission simply has no Original reading. If the script
  warns that this is an institution workspace, the switch applies to every
  professor and student in it. Original's comparisons are not validated for
  real student work yet (gap T-01), so turn it on only with the owner's
  agreement and the institution's consent.
- **Deploys** are manual (`autoDeploy: false`): Render → `original-pilot` →
  Manual Deploy. Each one migrates the database first; a failed migration
  fails the deploy and the old version keeps serving. Never deploy during an
  exam window teachers have told you about.
- **Rollback:** Render → Deploys → previous deploy → Rollback. The schema
  changes are additive, so older code runs against the newer schema. If a
  rollback must also undo a migration, run
  `DATABASE_URL=… alembic downgrade -1` from a checkout first.
- **Freeze writes** for maintenance: `MAINTENANCE_MODE=1` → deploy. Writes return
  503; reads keep working. Unset → deploy to unfreeze.
- **Erasure requests:** a teacher deletes a student from the roster or the
  Students screen (`DELETE /bluebook/students/{id}`). Erasing every student
  in a workspace is `DELETE /tenants/{tenant_id}/students` (staff of that
  workspace or an operator, plus `X-Guard-Token: $MAINTENANCE_TOKEN`; see
  `docs/API_REFERENCE.md`). There is no automatic retention sweep yet: data
  stays until deleted.
- **Free-tier limits** per workspace (`original/bluebook_rules.py`): 200 enrolled
  students, 50 examinations, 500 submissions a month.
- **Email is off** if `SENDGRID_API_KEY` or `MAIL_FROM` is unset or wrong: the
  roster then offers *Copy all links* and *Download links (CSV)*, and the
  password-reset page tells people to ask their teacher. `/auth/me` reports
  `"mail": true|false`.
