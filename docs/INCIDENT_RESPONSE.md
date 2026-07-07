# Incident Response Runbook

> **Scope note.** This backs the 48-hour breach-notification commitment in
> [`docs/dpa_template.md`](dpa_template.md) (§8.2). It describes the process as
> it actually exists today: a small pilot project with no dedicated security
> team, one operator, SQLite on Render, and no automated incident-management
> tooling. It does not describe controls, roles, or tooling that don't exist —
> `dpa_template.md`'s own banner forbids aspirational claims, and this document
> holds itself to the same bar.

## 1. What counts as an incident

Per `dpa_template.md` §8.1, a **Breach** is "the unauthorized access, use, or
disclosure of student data where reasonable belief exists that the breach
compromises the security or privacy of the information." That's the trigger
for the 48-hour clock. Not every security-relevant event meets that bar, so
triage starts by classifying the report into one of three severities:

| Severity | Definition | Examples |
|---|---|---|
| **Confirmed breach** | Unauthorized party demonstrably accessed, exfiltrated, or disclosed student data. | Leaked `SECRET_KEY`/`MAINTENANCE_TOKEN` observed in use by someone outside the operator; a database/backup file found exposed publicly; credentials for a staff account confirmed compromised and used. |
| **Suspected incident** | Evidence of a security failure exists, but unauthorized access to student data is not yet confirmed. | Anomalous entries in the audit log (`/admin/audit`) with no known explanation; a dependency CVE affecting a component that touches student data; a lost laptop that had `.venv`/repo access; unexpected spike in `denied`/`403`/`429` responses in Render logs. |
| **False alarm** | Investigation finds no unauthorized access occurred. | A monitoring alert traced to a legitimate backup job or the weekly restore drill; an audit-log anomaly traced to the operator's own testing. |

Anything that starts as "suspected" and cannot be ruled out within the triage
window (below) is treated as a confirmed breach for notification-timeline
purposes — the DPA commitment is to notify on *suspicion*, not proof (§8.2:
"notify … of any **suspected** Breach").

## 2. Detection

There is no dedicated security-monitoring stack. Detection realistically comes
from one of these sources (see `docs/OPS_RUNBOOK.md` "Monitoring" and
"Routine maintenance"):

- **UptimeRobot/BetterStack** alerting on `/health` — an unexpected downtime
  or a student-count anomaly (a sudden drop to 0 with a 200 status) can be the
  first sign of data loss or tampering.
- **Weekly log scan** (`Render → Logs → filter 5xx, denied, 429`) — the
  operator's own routine maintenance is the main proactive detection
  mechanism for this project's size.
- **The audit log** (`/admin/audit`, backed by `_repo().log_audit(...)` calls
  throughout `original/api.py`) — every login, registration, deletion, and
  data-affecting action is logged with actor, timestamp, and result. A review
  of this log is the primary forensic source if an incident is suspected.
- **External report** — an institution's admin contact, a professor, or a
  student reports something wrong (e.g., they see another student's data, or
  a login they didn't initiate).
- **Vendor/dependency notice** — a CVE disclosure or an email from Render
  about the hosting environment.

There is no SIEM, no intrusion-detection system, and no 24/7 on-call. This is
a proportionate posture for a single-institution pilot; it is not proportionate
for a project handling multiple institutions at scale, which is part of why
`docs/adr/006-postgres-convergence.md` and the wider Postgres-convergence plan
treat infrastructure hardening as a scale-driven decision, not a pilot one.

## 3. Roles

The project runs with one operator (the same person who holds Render
dashboard access, the `SECRET_KEY`/`MAINTENANCE_TOKEN` secrets, and the
password-manager copies described in `docs/OPS_RUNBOOK.md` "Secrets"). There
is no separate security team, so the roles below are responsibilities, not
separate people:

| Role | Who | Responsibility |
|---|---|---|
| **Triager** | The operator, first responder to any detection signal | Confirms the report is real, gathers initial facts, classifies severity (§1) |
| **Decider** | The operator (product owner) | Decides whether the 48-hour notification clock has started (i.e., whether "reasonable belief" of a breach exists), decides containment actions |
| **Notifier** | The operator | Sends the actual notification to each affected institution's admin contact |
| **Postmortem owner** | The operator | Writes the postmortem (§6) after resolution |

If the pilot grows to the point where these are genuinely different people,
this table is the first thing to update — don't invent a bigger process before
that's true.

## 4. Timeline against the 48-hour DPA commitment

`dpa_template.md` §8.2 commits to notifying the School within 48 hours of
**discovery** of a suspected breach — not 48 hours from confirmation. The
timeline below is written to keep that promise achievable at this project's
scale:

```
Detection ──► Triage ──► Containment ──► Notification decision ──► Notification
  (T+0)      (target:      (as needed,        (no later than           (no later
              within 2h      can run in         T+24h)                  than T+48h
              of detection)  parallel with                              from T+0)
                             triage)
```

1. **Detection (T+0).** The clock starts the moment the operator has reason to
   suspect unauthorized access — not when it's confirmed. If a monitoring
   alert or report comes in, log the time it was received; that's T+0.
2. **Triage (target: within 2 hours of detection).** Pull the relevant audit
   log entries (`/admin/audit`, filterable by student/action/actor), check
   Render logs for the affected window, and classify severity per §1. If
   triage genuinely cannot resolve severity within a few hours (e.g., waiting
   on a third party like Render support), proceed to notification anyway once
   "suspected" status is reached — don't let an open investigation blow the
   48-hour window.
3. **Containment (as needed, in parallel with triage).** Proportionate to the
   incident. Realistic containment actions available today:
   - Rotate `SECRET_KEY` (invalidates every issued session/principal token —
     see `docs/OPS_RUNBOOK.md` "Secrets"; this requires taking the pilot down
     briefly and is a server restart, which per `CLAUDE.md` needs explicit
     sign-off outside a live incident, but an active breach is exactly the
     kind of exception that justifies it).
     ```
     Rotate <SECRET_KEY> outside teaching hours where possible; during an
     active suspected breach, rotate immediately and notify professors after.
     ```
   - Rotate `MAINTENANCE_TOKEN` if the guard/destructive-endpoint token or the
     demo admin-login backdoor password (see `docs/OPS_RUNBOOK.md`
     "Destructive-endpoint guard") is suspected compromised.
   - Revoke/rotate any compromised staff password via
     `python -m original.cli.delete_student` is unrelated — for a compromised
     *account*, disable it by resetting the password through the existing
     `/auth/register` re-provisioning path or, if urgent, by direct database
     edit (`store.py`'s `users` table) — there is no self-service
     "force password reset" endpoint today.
   - Restore from the most recent verified backup (`docs/OPS_RUNBOOK.md`
     "Disk-loss / corruption recovery") if data was corrupted or deleted.
   - Take the affected Render service down if containment requires it (this
     is the one case where the "never restart the dev server without
     permission" policy in `CLAUDE.md` is explicitly overridden by an active
     incident — restart, then document why in the postmortem).
4. **Notification decision (no later than T+24h).** The Decider makes the
   call: does this meet the "reasonable belief" bar in §8.1? When in doubt,
   decide yes — the DPA's own framing is that suspicion, not certainty,
   triggers notification.
5. **Notification (no later than T+48h from detection).** See §5.

## 5. What notification actually looks like

There is no dedicated incident-management or status-page tooling in this
codebase. "Notification" is a direct email to the institution's admin contact
— the same contact channel the project already relies on elsewhere:

- `docs/OPS_RUNBOOK.md` and `docs/PILOT_RUNBOOK.md` describe a single-operator
  relationship with each pilot institution's admin/professor contacts (no
  in-app admin-contact directory or ticketing system exists in the live
  stack — `original/api.py`'s only email-adjacent code is
  `_send_notification_email()`, an explicit stub that logs and does not send
  ("Stub for SendGrid email notification. Replace with real implementation."),
  used for per-submission escalation notices, not institutional breach
  notices. There is no automated breach-notification dispatch; this is a
  manual email sent by the operator).
- The DPA template's own contact block (§13.1 "School Contact — Data
  Protection Officer / Administrator") is the address of record: whatever
  email/name/phone the signed DPA lists for that institution is who gets
  notified. Keep those current per institution (the operator maintains this
  list outside the codebase — there is no `admin_contacts` table).
- The email itself should cover the content `dpa_template.md` §8.3 already
  commits to: description of the breach and data affected, date/time,
  likely cause and scope, mitigation steps taken, recommendations, and a
  point of contact (§13.2 lists `privacy@originalverification.com` as the
  standing contact).
- Record that notification occurred: add one audit-log entry
  (`_repo().log_audit(action="breach_notification", ...)` — the same
  mechanism used for `login`, `student_login`, and other lifecycle events in
  `original/api.py`) noting the institution notified and the timestamp. This
  keeps a record inside the same system used for every other accountability
  trail in the product, without inventing new tooling.

Per §8.4/§8.5 of the DPA, the *institution* is responsible for notifying its
own affected students and any regulators; the operator's job is to notify the
institution promptly and assist as reasonably requested.

## 6. Postmortem

After containment and notification, write a short postmortem (a markdown file
is enough — there is no incident-tracking system to file this in). Cover:

- Timeline: detection time, triage time, containment actions and when taken,
  notification time — check this against the 48-hour commitment explicitly.
- Root cause, to the extent known.
- What data (if any) was actually exposed, and to whom.
- What was changed as a direct result (rotated secret, patched dependency,
  revoked credential, restored backup).
- Whether this runbook itself needs an update — if the real incident revealed
  a gap in detection, roles, or the notification path, fix this document.

There is no fixed postmortem template beyond this list; don't build one bigger
than the project needs. Keep the postmortem file with the rest of the pilot's
operational history (alongside `PILOT_LOG.md`, referenced in
`docs/OPS_RUNBOOK.md` "Routine maintenance").

## 7. Related documents

- [`docs/dpa_template.md`](dpa_template.md) — the 48-hour notification
  commitment this runbook backs (§8), plus breach definition (§8.1) and
  notification content requirements (§8.3).
- [`docs/OPS_RUNBOOK.md`](OPS_RUNBOOK.md) — secrets, backups, restore
  procedure, and the destructive-endpoint guard referenced in containment
  (§4 above).
- [`docs/PILOT_RUNBOOK.md`](PILOT_RUNBOOK.md) — the institutional
  relationship this runbook's notification step relies on.
