# Subprocessors — Original Collections

*Status: DRAFT — pending counsel review. Last updated 2026-10-12 (student consent MVP).*

Vendors that host, transmit, or store data for Original Collections. Student
writing is never sent to any AI or analytics service. This list is the source
for the subprocessor section of `demo/legal/privacy.html` once counsel approves it.

| Vendor | Touches student data? | What | Region |
|---|---|---|---|
| Render | Yes | Application hosting and the Postgres database: all records (accounts, rosters, submissions, consent records) | Oregon, US |
| Cloudflare R2 | Yes (encrypted) | Daily database backups, Fernet-encrypted before upload | Cloudflare-managed |
| SendGrid (Twilio) | Yes, once configured | Student email address and name in invitation emails | US |
| Cloudflare DNS / Registrar | No | Domain name only | — |
| GitHub | No (to be confirmed) | Source code and CI with synthetic fixtures only; no production data | US |
| The school's own Canvas / LMS | School-controlled | Only when a teacher uses LTI launch or Canvas import | School-controlled |

## What is not collected

- No keystrokes or per-key timing.
- No IP address or browser user agent in application request logs or in the
  database (removed 2026-10-12). Render's and Cloudflare's own platform logs
  can still see connecting IP addresses under their terms; retention there is
  set by the provider's plan.

## Changes

Adding a subprocessor that touches student data requires updating this file,
the privacy page, and notifying each school with a pilot agreement on file.
