# Day-One Class — operator one-sheet

*Work this top-to-bottom when a professor says yes. It fuses the four detailed
runbooks; each step links to the full version. Goal: a professor signs into
Original, his dashboard is blank until his class writes, and the first proctored
baselines land on his roster **that day**.*

The day runs on **two clocks**. The slow clock is other people's queues
(compliance, IT) — it must be cleared *before* the yes, or day-one can only be a
no-real-data dry run. The fast clock is ~20–30 min of provisioning you do once
the slow clock is green.

---

## Slow clock — must already be true (gate; can't be compressed on the day)

If any of these is missing, you cannot collect **real** student writing today.

- [ ] **`original-pilot` Render service is live** with all secrets set —
  `SECRET_KEY`, `MAINTENANCE_TOKEN`, `LTI_PLATFORMS`, backups, `/health` green.
  → [OPS_RUNBOOK.md](OPS_RUNBOOK.md). *(Never point a professor at
  `original-demo`.)*
- [ ] **Signed DPA** on file. No real student writing without it.
  → [dpa_template.md](dpa_template.md).
- [ ] **Canvas decision made** — one of:
  - **Canvas-ready (preferred):** developer key registered and the platform is
    in `LTI_PLATFORMS`, `tenant_id` = the slug below.
    → [CANVAS_RUNBOOK.md](CANVAS_RUNBOOK.md) §1–2,
    [canvas_developer_key.md](canvas_developer_key.md).
  - **No-Canvas fallback:** you'll hand out per-student magic links instead
    (Path B below). Nothing to pre-register, but you distribute 1 link/student.

---

## Fast clock — the day-of runbook (~20–30 min)

### Step 1 — Operator: provision the tenant and the professor

Set `HOST=https://original-pilot.onrender.com` and export `MAINTENANCE_TOKEN`.
Full version: [PROVISIONING_CHECKLIST.md](PROVISIONING_CHECKLIST.md).

- [ ] **Create the tenant as `environment=pilot`** (NOT demo — a `demo` tenant is
  readable by anonymous callers; this is the single step that keeps real writing
  isolated). Slug is lowercase-kebab and **permanent** — it prefixes every
  student id.
  - [ ] `GET $HOST/tenants` shows it with `environment: pilot`.
- [ ] **Register the professor** (guarded upsert):
  ```bash
  curl -s -X POST $HOST/auth/register \
    -H 'Content-Type: application/json' -H "X-Guard-Token: $MAINTENANCE_TOKEN" \
    -d '{"email":"prof@school.edu","password":"<gen>","role":"professor","tenant_id":"<slug>"}'
  ```
  Generate the password: `python -c "import secrets; print(secrets.token_urlsafe(12))"`.
- [ ] **Watch them log in once** at `$HOST/bluebook/`: sidebar reads
  `professor · <slug>`, and **Examinations / Courses / Students / Results are
  EMPTY**. If they see demo data, STOP — wrong host or the auth bridge isn't
  attaching ([PROVISIONING_CHECKLIST.md](PROVISIONING_CHECKLIST.md) §3).

> **Blank-until-connected is the intended behavior**, not a bug to fix. A fresh
> tenant's roster is `[]` until students write.

### Step 2 — Professor: create the baseline exam

→ [PROFESSOR_QUICKSTART.md](PROFESSOR_QUICKSTART.md) §Week 1.

- [ ] Create a course → create the **"Week 1 Writing Sample"** Bluebook exam:
  lockdown on, low minimum words, a prompt students can answer cold.

### Step 3 — Get the class into the exam (pick one path)

**Path A — Canvas-ready (preferred).** Each student is auto-bound on launch; no
links to hand out.
- [ ] In Canvas, add an External Tool / module item for the exam pointing at
  `…/bluebook/`. Verify per [CANVAS_RUNBOOK.md](CANVAS_RUNBOOK.md) §3.

**Path B — No-Canvas fallback.** Generate one bound, disclosure-minimized link
per student from the class roster:
```bash
.venv/bin/python scripts/roster_links.py \
  --roster roster.csv --tenant <slug> \
  --base-url $HOST --exam "Week 1 Writing Sample" \
  --out links.csv --expected-out expected_roster.json
```
- [ ] Links carry only the opaque `sid` (no name/email) — send **each link to its
  own student privately**; one link == one bound profile.
- [ ] Keep `links.csv` (maps sid→student, for you) and `expected_roster.json`
  (the "N of M submitted" spine) in the password manager / course folder.
- [ ] The `sid` a link produces is **identical** to what a Canvas launch would
  derive, so a class can start on links today and move to Canvas later with no
  profile split.

### Step 4 — Disclosure + smoke test

- [ ] Drop the syllabus paragraph into the course (the script prints it; source:
  [STUDENT_DISCLOSURE.md](STUDENT_DISCLOSURE.md)).
- [ ] One volunteer runs the loop end-to-end:
  [PILOT_SMOKE_TEST.md](PILOT_SMOKE_TEST.md) §C — launches, lands in the briefing
  as themselves, types past the minimum, Seal & Surrender → appears on the
  professor's roster with provenance `proctored`.

### Step 5 — Run it

- [ ] Announce; students sit the baseline in or after class. As each student
  submits, they appear on the professor's roster — blank → populated, live.

---

## Set this expectation or it looks broken

**Day one captures baselines; it does not yet score.** The *first* sitting has no
prior baseline to compare against, so the **AI/authorship score is blank** and
the stylometric bar reads ~100% (drift vs an empty profile). A row with scores
*does* appear that day — but the meaningful integrity signal starts at the
**second** sitting, and escalation stays suppressed until the profile is built
(~3+ authenticated samples). Tell the professor: **week 1 = enrollment by
writing; the payoff is week 2–3.** → [PROFESSOR_QUICKSTART.md](PROFESSOR_QUICKSTART.md).

---

## One-line failure triage

| Symptom | Cause | Where |
|---|---|---|
| Professor sees demo data on login | wrong host, or tenant not `pilot` | [PROVISIONING_CHECKLIST.md](PROVISIONING_CHECKLIST.md) §3 |
| Canvas launch lands in wrong data | `LTI_PLATFORMS` `tenant_id` ≠ slug | [CANVAS_RUNBOOK.md](CANVAS_RUNBOOK.md) §4 |
| Anonymous can read student | tenant is `demo`, not `pilot` | recreate tenant `environment=pilot` |
| Magic link 404 / not clickable | `--base-url` omitted when generating | rerun `roster_links.py` with `$HOST` |
| Student appears twice | link `sid` ≠ Canvas `sid` | shouldn't happen — same derivation; check the slug matches the tenant |
