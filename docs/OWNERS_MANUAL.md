# Owner's Manual — driving Original + Bluebook yourself

For the operator/founder. Professors get `PROFESSOR_QUICKSTART.md`; servers get
`OPS_RUNBOOK.md`; this is **how you personally use and present the product**.

---

## 1. Running it

**Locally:**
```bash
cd ~/Desktop/Original
.venv/bin/python run.py --demo --port 8001
```
Open `http://localhost:8001/` — it redirects to the professor dashboard,
pre-seeded with synthetic students. Stop with Ctrl-C. (Always `.venv/bin/python`,
never system python3.)

**Live:** the Render demo URL (once deployed). Free tier sleeps when idle —
**open it 10 minutes before any meeting** to warm it.

## 2. Every surface and what it's for

| URL | What | When you use it |
|---|---|---|
| `/professor.html` | THE dashboard — analyze, baselines, history | the core demo + daily use |
| `/bluebook/` | secure-exam app (Oxford blue-book) | second half of the demo |
| `/index.html` | sign-in page (email/password + demo role pills) | showing real auth |
| `/admin.html` | institution console (stats, activity, integrations) | dean-flavored overview |
| `/operator.html` | multi-school view (tenants, audit log) | showing multi-tenancy |
| `/student.html` | the student's own view (profile, growth, submit) | "what do students see?" |
| `/landing.html` | marketing page | link in follow-up emails |
| `/lab.html`, `/playground.html`, `/admin-context.html` | research/calibration surfaces | technical audiences only |

## 3. The 10-minute dean demo (click-by-click)

**Beat 1 — the hook (3 min), on `/professor.html`:**
1. The student row at top — click **James Whitfield** (or any pill). Point at the quantum profile panel: "we model each student's *voice*, not a plagiarism database."
2. Click **Load sample** → **Analyze Writing**. While it runs: "103 measurable habits — vocabulary, rhythm, punctuation, argument structure."
3. The result lands: deviation score, the plain-English explanation, and the recommendation. **Read the explanation out loud** — the explainability *is* the pitch.
4. Say the line: *"a recommendation is never a finding of misconduct — this opens a conversation with the student, it never decides one."* Deans lean in at this; it's the anti-Turnitin position.

**Beat 2 — provenance (2 min), still on professor:**
5. Click the **Baselines** tab — show the per-sample provenance (`proctored` beats `uploaded`). "Trust comes from *how* the baseline was collected."

**Beat 3 — Bluebook (4 min):**
6. Sidebar → **Bluebook ↗**. On the landing page: **Sign in → "Explore the demo →"**.
7. **Examinations → + New Examination** — flip through Sections I–V, pausing on **IV. Secure Lockdown** (AI / web / clipboard toggles). Publish it.
8. Open it from the list → **Begin Examination** — fullscreen engages, the gold "● Locked" strip shows. Type a few sentences; try **Cmd+C** (blocked, examiner's notice appears). Mention: "typing rhythm is being captured — it feeds the voice profile."
9. (If time) lower stakes: type past the minimum → **Seal & Surrender** → "Examination Sealed" → **Results** shows the sitting with its scores.

**Beat 4 — close (1 min):** `/admin.html` for the institution view, then the ask: "we run a one-department pilot — proctored baselines in week one, real scoring by week three."

**Pre-demo checklist:** URL warm · click *Reset Demo* (top bar of professor.html) if a previous session left junk · know your wifi fallback (laptop + localhost works offline except fonts).

## 4. Using it as yourself (authenticated, not demo)

The demo needs no login. To use it *as a real professor* (your own tenant, real persistence):

```bash
HOST=http://localhost:8001          # or the pilot URL
# one-time: register yourself (open in demo; add -H "X-Guard-Token: $MAINTENANCE_TOKEN" on the pilot)
curl -s -X POST $HOST/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"<pick-one>","role":"professor","tenant_id":"mytest","name":"Andrew"}'
```

Then sign in at `/index.html` (or `/bluebook/` → Sign in). What changes when authed:
- professor.html greets you by name, roster comes from **your tenant** (empty at first — use *Import Papers* or a Bluebook sitting to add students); the demo's seeded students disappear.
- Bluebook shows *your* exams/courses/results only; **Sign Out** (sidebar) returns everything to demo mode.
- Under the hood: a signed token in localStorage (`original_principal_token`); every API call is tenant-scoped server-side.

**Simulating a student taking your exam:** open
`/bluebook/?sid=mytest:demo01&candidate=Test%20Student` in a private window —
that's exactly what an LTI launch does (binds the student id, skips login).

## 5. Operator tasks (the 90% set)

| Task | How |
|---|---|
| Reset the public demo after a sales call | `.venv/bin/python scripts/reset_demo_data.py --apply` (dry-run without `--apply`; only touches the `demo` tenant) |
| See all tenants / students / exams | `curl $HOST/tenants` · `curl $HOST/students` · `curl $HOST/bluebook/exams` |
| Inspect the DB directly | `sqlite3 profiles.db ".tables"` then normal SQL; never edit while the server writes |
| Back up | `bash scripts/backup_db.sh` (see OPS_RUNBOOK for the live-service version) |
| Provision a real professor | `docs/PROVISIONING_CHECKLIST.md` |
| Reset someone's password | re-POST `/auth/register` with the same email/tenant + new password (guarded on pilot) |
| Score via API (no UI) | `curl -X POST $HOST/students/<id>/score -H 'Content-Type: application/json' -d '{"text":"...","assignment":"x"}'` |
| Rebuild Bluebook after editing its JSX | `cd demo/bluebook && npm run build` + commit the bundle |

## 6. Reading the numbers (so you never misspeak)

- **Deviation score** (professor dashboard): 0–1, higher = further from their voice. Thresholds (`ACTION_THRESHOLDS` in constants.py): <0.40 no action · 0.40–0.60 monitor · 0.60–0.75 conversation · >0.75 escalate.
- **Bluebook Results — Stylometric**: how this sitting's style/keystrokes match the profile (= 1 − drift).
- **Bluebook Results — AI Score**: authorship probability of the text against their baseline (higher = more authentically theirs). Shows **"—" on a first sitting** — that's honesty, not a bug: there's no baseline to compare against yet.
- Escalation is suppressed below 5 authenticated baselines. If a number surprises you, open the explanation panel before explaining it to anyone else.

## 7. When something misbehaves

| Symptom | First move |
|---|---|
| Dashboard shows wrong/stale data | hard-reload (Cmd+Shift+R); the demo caches aggressively |
| "Signed in" but seeing demo students | token didn't attach — Sign Out, sign in again |
| Bluebook blank page | check browser console; if you edited JSX, you forgot `npm run build` |
| Exam won't submit | word count below the exam's minimum — the Seal button stays disabled |
| Login says "Too many sign-in attempts" | the throttle (10/5min per IP) — wait 5 minutes |
| Server won't boot with `ORIGINAL_ENV=pilot` | missing `SECRET_KEY` — that's the fail-fast working |
| Anything LTI | `docs/CANVAS_RUNBOOK.md` §4 troubleshooting table |
