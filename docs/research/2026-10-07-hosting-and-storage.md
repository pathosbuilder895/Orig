# Hosting and data storage for the Original + Bluebook pilot

| | |
|---|---|
| **Tool** | Grok Bot (web research plus a read-only review of `pathosbuilder895/Orig` main @ `6459582`) |
| **Date** | 2026-10-07 |
| **Question** | What does Original + Bluebook need to host and store data for a small independent-teacher pilot (1–3 teachers, maybe dozens later)? Which host fits best on cost, managed Postgres and backups, encrypted off-box backups, US region, privacy fit (FERPA/COPPA, DPA) and ease for a solo developer driven by AI tools? Where should the data live so it stays usable? Also: how do Codex and Claude read a private repo? |
| **Decision it informs** | NORTH_STAR "Current phase": hosting and budget. `docs/release/VERIFICATION_AND_BLOCKERS.md` items B1 (hosting), B3 (off-box backups) and B2 (legal provider blanks). The decision to make the repo private. |

Prices were read from the vendors' public pages on 2026-10-07, in USD, before tax. **[UNVERIFIED]** marks anything I could not confirm from a primary source. None of this has been purchased or configured.

---

## 1. What the repo actually needs (facts from the code)

| Need | What the repo has today | Source in repo |
|---|---|---|
| App runtime | One Python 3.11 FastAPI process (`python run.py --demo --port $PORT --skip-seed`), with Bluebook served from a committed bundle. No Node build at deploy time. | `render.yaml`, `run.py` |
| Dependency weight | Uses `requirements-pilot.lock.txt` plus spaCy `en_core_web_sm`. The full `requirements.txt` pulls in PyTorch and "won't fit Starter". | `render.yaml` comment |
| Memory | Starter is about 512 MB. spaCy loads about 150 MB at boot. RSS with Original turned on has not been measured. | `docs/OPS_RUNBOOK.md:247` |
| Instances | Must be a **single instance / single worker**. There is in-process state, so do not autoscale. | gap register T-18, `CLAUDE.md` |
| Database | **Postgres 16** through `REPO_BACKEND=postgres` (SQLAlchemy plus 8 Alembic migrations, run by `preDeploy: alembic upgrade head`). SQLite is used only in dev and the demo. | `render.yaml`, `original/postgres_repository.py`, `alembic/` |
| File/blob storage | **None needed for submissions.** Submissions are text and JSON columns. `.txt`/`.docx`/`.pdf` uploads are converted to text in memory, and I found no code that saves the original file. | `original/routers/students.py:348`, `original/db/models/live.py` |
| Background jobs | One daily cron: `scripts/pg_backup_offbox.py --require-upload` at 08:30 UTC, encrypted with Fernet and uploaded to any S3-compatible bucket. No queue or worker. | `render.yaml` `original-pg-backup` |
| Email | SendGrid (`SENDGRID_API_KEY`, `MAIL_FROM`) for invites and resets. | `render.yaml`, mailer |
| Monitoring | Optional Sentry DSN (PII scrubbing in code). | `render.yaml` |
| Static demo | A static, fictional teacher demo site (`bluebook-teacher-demo`). | `render.yaml` |
| Container | `Dockerfile.demo` (SQLite, port 8000) is **demo-only**. There is no production Dockerfile. Any non-Render host either uses buildpacks or needs a small pilot Dockerfile written. | `Dockerfile.demo` |

**Size estimate [estimate, not measured]:** prose is about 6 KB per 1,000 words. 3 teachers × 30 students × 20 submissions is about 1,800 rows, a few tens of MB including profiles and audit log. Dozens of teachers stay well under 1 GB. Storage is not the cost driver; RAM and the managed database are.

## 2. Options compared

Assumptions: one small web service, managed Postgres 16, a daily backup cron, a US region, and pilot scale.

| | **Render** (already blueprinted) | **DigitalOcean** App Platform + Managed PG | **Railway** | **Fly.io** + Managed Postgres | **AWS Lightsail** | **Hetzner US VPS** |
|---|---|---|---|---|---|---|
| Web | Starter 0.5 CPU / 512 MB **$7**; Standard 1 CPU / 2 GB **$25** | 1 GB app about **$10–12** | Hobby **$5**/mo including $5 usage, then metered | shared-cpu machine about **$3–6** | container nano 512 MB **$7** | CPX11 about **$20.49** after the June 2026 price change |
| Postgres | basic-256mb **$6**; basic-1gb **$19**; storage billed per GB | single node 1 GB **$15.15** | runs as a service on a volume, billed by usage | Managed Postgres "Basic" **$38** | managed DB from **$15** | none; you run it yourself |
| Backups | **PITR 3 days on Hobby, 7 days on Pro**, plus logical exports | free daily backups, PITR **[UNVERIFIED window]** | volume backups (daily/weekly/monthly), restore within the same project | daily snapshots; MPG has backups | automatic backups **[UNVERIFIED retention]** | DIY |
| Encrypted off-box | repo cron already does it → R2/B2 | same script, would need to be ported to a job | same script, cron service | same script | same script | DIY |
| US region | Oregon, Ohio, Virginia | NYC, SFO and others | US regions | many US | US regions | Ashburn, Hillsboro |
| DPA / compliance | GDPR DPA listed on all plans; SOC 2 Type II, ISO 27001 | DPA available | self-service DPA at railway.com/legal/dpa | DPA **[UNVERIFIED]** | AWS DPA (GDPR addendum) | DPA available |
| Fit for a solo dev using AI tools | **Best**: `render.yaml` exists, preDeploy migrations, cron and static site all in one file | Good: needs an app spec, Dockerfile or buildpack | Good: needs config, no blueprint | Medium: `fly.toml` plus Dockerfile; MPG price is high | Low–medium: more AWS plumbing | Low: you run the OS, Postgres, TLS, patching and backups |
| **Pilot total (hosting only)** | **≈ $13/mo** (7+6); **≈ $26–44** with 1 GB DB and/or 2 GB web | ≈ $25–27 | ≈ $10–20 **[estimate]** | ≈ $41–45 | ≈ $22+ | ≈ $21 + your time |

Sources:
- Render: https://render.com/pricing · https://render.com/docs/postgresql-backups
- DigitalOcean: https://www.digitalocean.com/pricing/app-platform · https://www.digitalocean.com/pricing/managed-databases
- Railway: https://railway.com/pricing · https://docs.railway.com/volumes/backups · https://railway.com/legal/dpa
- Fly.io: https://fly.io/pricing · https://fly.io/docs/mpg/
- AWS Lightsail: https://aws.amazon.com/lightsail/pricing/
- Hetzner: https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/

**Shared add-ons, whatever the host:**
- **Email (SendGrid):** the free plan has been retired. Essentials is about **$19.95/mo**. (https://www.twilio.com/en-us/changelog/sendgrid-free-plan · https://www.twilio.com/en-us/products/email-api/pricing) Cheaper transactional providers exist, but the code only supports SendGrid today.
- **Off-box backup bucket:**
  - Cloudflare R2: 10 GB-month free, then $0.015/GB, no egress fees. https://developers.cloudflare.com/r2/pricing/
  - Backblaze B2: first 10 GB free. https://www.backblaze.com/cloud-storage/pricing
  - At pilot size either costs **about $0**.
- **Sentry:** optional; free developer tier **[UNVERIFIED current limits]**.
- **Domain:** about $10–20 per year.

## 3. Privacy fit (FERPA, COPPA, DPA). Not legal advice; counsel should confirm.

- **FERPA.** A vendor can receive education records under the "school official" exception only when it is under the school's direct control, uses the records only for authorized purposes and does not re-disclose them. See the US Department of Education PTAC Vendor FAQ: https://studentprivacy.ed.gov/sites/default/files/resource_document/file/Vendor%20FAQ.pdf
  - An **independent teacher with no school contract** doesn't set up that relationship. FERPA probably doesn't attach the same way for private tutoring, but if the teacher works for a school and uses Bluebook for school classes, the school's FERPA obligations and policies apply. **[Needs counsel]**
  - Practical answer: terms and a short DPA template that a teacher or school can sign, data used only to provide the service, deletion on request, and US hosting.
- **COPPA.** The amended rule took effect 2025-06-23, with compliance required by **2026-04-22**. https://www.federalregister.gov/documents/2025/04/22/2025-05904/childrens-online-privacy-protection-rule
  - The draft privacy page says Bluebook is for students **13 and over**. Keep that boundary for independent teachers. Collecting data from under-13s means verifiable parental consent, unless a school authorizes it, and an independent teacher is not a school.
- **Host DPAs.** The DPA covers Andrew's company and the host, not students. Render, Railway, DigitalOcean, AWS and Hetzner all publish DPAs. Fly's was not checked **[UNVERIFIED]**.
- The repo's own rules already help: no keystrokes, no third-party inference on prose, Sentry scrubbing, tenant isolation, and deletion.

## 4. Where to store the data so it's usable

1. **Keep the system of record in Postgres. Don't add object storage for submissions.** Submissions are text plus small JSON (`bluebook_submissions.text`, `answers_json`, `warnings_json`, mark, feedback). Postgres gives transactions, tenant-scoped queries, cascading deletion, and backups that cover everything. Object storage would only add a second store to keep in sync, a second place to delete from, and more privacy surface.
2. **Use object storage only for encrypted backups.** The existing `pg_backup_offbox.py` (a Fernet-encrypted `pg_dump`) goes to R2 or B2 in a **different provider and account** from the host. Keep the Fernet key outside both, in a password manager. Restore one backup before inviting the first teacher, as the repo's own "done" criteria require.
3. **Exportability:**
   - teacher-facing CSV/JSON export (Bluebook export already exists)
   - per-workspace export on request
   - full logical dumps (portable to any Postgres 16, so no lock-in to one host)
4. **Original baselines:**
   - Keep them in the same database, scoped to the workspace: `student_profiles.data` JSON holds the approved samples; `rho_bytes` is recomputed.
   - Rules:
     - Only teacher-approved samples are stored.
     - Each sample keeps its provenance: source submission id, who approved it and when, and the feature/schema version, so baselines can be re-extracted when the feature set changes (`scripts/reextract_baselines.py`).
     - Removal and deletion actually delete.
     - No keystroke or timing biometrics.
   - **[Suggestion, not current code]** If baselines grow, move samples from the JSON blob into their own table with a foreign key to the submission. That makes provenance and deletion auditable with SQL.

## 5. Recommendation

**Recommended: Render, following the existing `render.yaml`.**
- The blueprint already defines the web service, preDeploy migrations, Postgres 16 in Oregon, the encrypted backup cron and the static demo. An AI-driven solo developer gets the fewest new moving parts.
- Start with **Starter web $7 + Postgres basic-256mb $6 ≈ $13/mo**, plus SendGrid Essentials **$19.95** and an R2/B2 bucket at about **$0**: **≈ $33/mo all-in**.
- Move to basic-1gb ($19) and/or a 2 GB web instance ($25) when Original is switched on or teachers reach the dozens: **≈ $45–65/mo**.
- Hobby includes 3-day PITR. Render Pro ($25/mo) extends this to 7 days, but isn't needed for 1–3 teachers.

**Runner-up: DigitalOcean (App Platform about $12 + Managed Postgres $15.15 ≈ $27/mo + email).**
- Comparable price, a managed database with daily backups, and US regions.
- Needs `render.yaml` translated into an app spec plus a pilot Dockerfile or buildpack.

**Not recommended for now:**
- Fly.io: managed Postgres at $38 is the costliest database at this scale.
- Hetzner: no managed database, so you'd be running the operating system and Postgres yourself.
- Lightsail: more AWS plumbing than it's worth here.
- Railway: viable and cheap, but there is no blueprint for it in the repo.

**Next steps (all need Andrew's approval):**
1. Choose the Render workspace (Hobby) and confirm the GitHub connection can see the repo after it goes private.
2. Create an R2 or B2 bucket in a separate account; generate the Fernet key and store it offline.
3. Buy SendGrid Essentials and verify the sending domain (or decide to send invites manually at first).
4. Merge or resolve the pending `codex/bluebook-pilot-c962a917` render.yaml change (`generateValue: true` for `SECRET_KEY`/`MAINTENANCE_TOKEN`), then apply the blueprint.
5. After the first deploy, measure RSS with Original on and off. Upgrade the web plan only if needed.
6. Restore-drill one encrypted backup, run the deployed acceptance checks (VERIFICATION B1–B6), and only then invite teacher #1.

## 6. Private-repo access: Codex, Claude, and side effects

- **ChatGPT Codex (cloud):**
  - Connect GitHub in ChatGPT/Codex settings and install the **ChatGPT Codex Connector** GitHub app with access to `pathosbuilder895/Orig`, either all repos or selected ones.
  - Private repos appear only once the app is installed on the right account and granted that repo. If it's missing, adjust the app's repository access in GitHub settings.
  - Sources: https://help.openai.com/en/articles/11145903 · https://help.openai.com/en/articles/20001545-using-codex-cloud
  - Codex CLI or IDE on Andrew's machine uses his local git credentials and is unaffected.
- **Claude Code:**
  - On Andrew's machine it uses local git/`gh` credentials and is unaffected.
  - **Claude Code on the web** needs the **Claude GitHub App** installed with access to the repo, or a token set up via `/web-setup`.
  - The GitHub Actions integration (`/install-github-app`) also installs the Claude app on the repo.
  - Sources: https://code.claude.com/docs/en/web-quickstart · https://code.claude.com/docs/en/github-actions
- **Claude.ai / Claude Design:**
  - Claude.ai's GitHub integration lets you add private repos to chats and projects after authorizing the Claude GitHub app for them. https://support.claude.com/en/articles/10167454-use-the-github-integration
  - Claude Design can link a code repository as design-system context. https://support.claude.com/en/articles/14604416-get-started-with-claude-design
  - **[UNVERIFIED]** whether Claude Design uses the same GitHub app grant for private repos. Test it after the switch.
- **Perplexity:** needs no repo access. Give it the question plus pasted repo facts.
- **Side effects of going private:**
  - **GitHub Actions minutes.** Public repos get free standard runners. Private repos use the account quota: **2,000 min/month on Free, 3,000 on Pro**, then about $0.006/min for Linux. The repo's CI (sharded pytest, boot matrix, browser tests, weekly calibration battery) could exceed 2,000 minutes in a busy month **[estimate]**. https://docs.github.com/en/billing/concepts/product-billing/github-actions · https://docs.github.com/en/billing/reference/actions-runner-pricing
  - **Hosting deploy access.** Render (or any host) must have its GitHub app authorized for the private repo, or deploys will fail. **[Standard behaviour; confirm in the Render dashboard]**
  - **Old links.** Any public links to files (README badges, shared GitHub links) stop working for logged-out viewers.
  - **Timing.** Visibility is a GitHub settings change for Andrew to make. Do it after confirming each tool's app grant is in place.
