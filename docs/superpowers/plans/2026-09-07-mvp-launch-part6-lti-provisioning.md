# MVP Launch Part 6 — LTI Bind, Sandbox Verification, Provisioning (O7 + O8 + O9, gated by O6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read `2026-09-07-mvp-launch-index.md` §Global Constraints first — they all apply here. Ops part: step = action + verifying command + expected output; `⛔ HUMAN` = operator-only; unexpected output → STOP, BLOCKED, PILOT_LOG.

**Goal:** Canvas launches work end-to-end in a sandbox course (all five CANVAS_RUNBOOK §3 checks); the institution tenant and 5 professor accounts are provisioned and individually verified; the PROVISIONING_CHECKLIST §5 before-real-students gate is fully checked and dated — the last gate between the pilot and its first real exam.

**Architecture:** Tenant first (the LTI binding's `tenant_id` must reference an existing slug), then the bind on the admin's reply, then the sandbox table, then people. This part legitimately sits `blocked (waiting on Canvas admin)` on the dashboard between Task 1 and Task 2 — that status is information, not failure.

**Tech Stack:** guarded `curl`s (`X-Guard-Token`), `~/Desktop/Original-secrets/LTI_PLATFORMS.template.json`, `docs/CANVAS_RUNBOOK.md`, `docs/PROVISIONING_CHECKLIST.md`, `docs/PILOT_SMOKE_TEST.md`, `scripts/pilot_preflight.py`.

**Venue:** operator + assistant. **Depends on:** Part 4 (service + the ask sent) + the admin reply (external, days–weeks). Part 5 first is strongly recommended so the §5 smoke run happens on the final backend. **O6 (signed DPA) gates Task 5 only** — sandbox work needs no DPA.

## Global Constraints (additional to the index's)

- The tenant slug is **final** the moment it is created — it prefixes every student id; never rename. It must equal `slugify(institution name)` exactly as students would type it.
- Credentials are delivered in person/directly; there is no email flow and no self-serve reset (re-issue via the guarded `/auth/register` upsert, logged in PILOT_LOG).
- **Cross-part gate, restated from Part 2: PR #160 must be dispositioned before the first proctored sitting.** Also re-check Part 4 Task 1 Step 3's scoring-defect line — real scoring must not start with that finding unresolved.

---

### Task 1: Tenant (runs any time after Part 4 — don't wait for the admin)

- [ ] **Step 1:** `curl -s -X POST $HOST/tenants -H 'Content-Type: application/json' -H "X-Guard-Token: $MAINTENANCE_TOKEN" -d '{"tenant_id":"<slug>","name":"<Institution Name>","environment":"pilot"}'` → 200/201. Slug checklist: lowercase-kebab; `slugify(name)` exact (a mismatch strands self-service logins in a second, demo-labeled tenant); final forever.
- [ ] **Step 2 (negative checks):** anonymous `POST $HOST/tenants` → **403**; re-POST the same tenant with `"environment":"demo"` → **409** (downgrade refused). If either passes, **STOP — the deploy is not running this build.**
- [ ] **Step 3:** PILOT_LOG line (tenant created, slug, date); `git add docs/PILOT_LOG.md && git commit -m "Add tenant-provisioning record to the pilot log"`.

### Task 2: LTI bind (on the admin's reply)

- [ ] **Step 1:** Fill `~/Desktop/Original-secrets/LTI_PLATFORMS.template.json`: `issuer` = `https://canvas.instructure.com` for Canvas cloud (**never** the institution's vanity domain; self-hosted uses its own domain — Part 4 Task 4 asked which); `client_id` and `deployment_ids` from the reply (ask for ALL deployment ids if the admin created both account- and course-level deployments — a missing one is the `unrecognised deployment_id` 401); `auth_login_url`/`jwks_url` on the institution's hostname (`jwks_url` must be the **institution's**, not the tool's); `tenant_id` = Task 1's slug, double-checked — a typo silently creates a new namespace.
- [ ] **Step 2 (⛔ HUMAN):** Paste as `LTI_PLATFORMS` on the service → deploy. Verify: boot log shows the platform parsed (a JSON error logs at boot); `curl $HOST/lti/jwks` still returns the non-empty key set.

### Task 3: Sandbox verification (CANVAS_RUNBOOK §3 — before any professor)

- [ ] **Step 1:** Instructor clicks the course-nav placement → lands signed-in on the Bluebook dashboard, tenant-scoped.
- [ ] **Step 2:** Student clicks an exam link (target `…/bluebook/`) → lands on the examination briefing, no login prompt, candidate bound (`bluebook_student_id` in localStorage).
- [ ] **Step 3:** Same student submits → proctored sample appears: `GET $HOST/students/<id>` shows `sample_count` +1 with provenance `proctored`.
- [ ] **Step 4:** Launch with a bogus `deployment_id` → **401 "unrecognised deployment_id"**.
- [ ] **Step 5:** Replayed/stale launch → **401 "invalid or expired state"**.

Any failure: decode via the §4 troubleshooting table (`docs/CANVAS_RUNBOOK.md:54-65`) — issuer mismatch, wrong jwks_url, nonce replay, >10-min login→launch gap, second deployment, `requirements-demo` deployed instead of `requirements-pilot`, tenant mismatch. Fix, redeploy, rerun all five. PILOT_LOG line when the table passes; `git add docs/PILOT_LOG.md && git commit -m "Add Canvas sandbox-verification record to the pilot log"`.

### Task 4: Professors ×5

- [ ] **Step 1:** Per professor: `curl -s -X POST $HOST/auth/register -H 'Content-Type: application/json' -H "X-Guard-Token: $MAINTENANCE_TOKEN" -d '{"email":"<prof@inst.edu>","password":"<generated>","role":"professor","tenant_id":"<slug>","name":"<Dr. Full Name>"}'` (passwords via `python -c "import secrets; print(secrets.token_urlsafe(12))"`; record in the password manager). Optional one `admin` account for the chair/registrar.
- [ ] **Step 2 (⛔ HUMAN, per professor):** The watch-them-login ritual — professor signs in at `$HOST/bluebook/`; sidebar shows their name + `professor · <slug>` (not "Demo Session"); Examinations/Courses/Students/Results all **empty** (demo data visible = STOP: wrong host or the auth bridge isn't attaching); they create one throwaway course + draft exam from the quickstart.
- [ ] **Step 3:** §4 isolation spot-checks (six checks: staff `GET /students` only `<slug>:*`; anon student fetch 403; anon `/students`, `/admin/audit`, `/tenants` 401; `/seed.db` + `/lab.html` 404) — `o1_golive_check` automates the anonymous six; run it once more against the live host.
- [ ] **Step 4:** PILOT_LOG lines (credentials issued, per-professor verification dates); `git add docs/PILOT_LOG.md && git commit -m "Add professor-provisioning records to the pilot log"`.

### Task 5: Before-real-students gate (⛔ HUMAN sign-off; O6 lands here)

- [ ] **Step 1:** DPA signed and dated (`docs/dpa_template.md` counterpart back from the institution) — the hard gate.
- [ ] **Step 2:** Syllabus disclosure distributed (`docs/STUDENT_DISCLOSURE.md`).
- [ ] **Step 3:** The **full `docs/PILOT_SMOKE_TEST.md` run, 100%, within 48h of the first exam** — now possible end-to-end (§C needs Canvas launches). Any B-item failure blocks everything; any C-item failure blocks scheduled exams.
- [ ] **Step 4:** `render ssh original-pilot -- python -m scripts.pilot_preflight --profile pilot` → verdict `READY` (or `READY (with warnings)` with each warning dispositioned), exit 0.
- [ ] **Step 5:** Re-verify the two cross-part gates: #160 dispositioned; scoring-defect line resolved (fix landed) — not merely accepted-for-zero-students, since students are no longer zero.
- [ ] **Step 6:** PILOT_LOG line: gate passed, all dates; first-exam go decision recorded as a human calendar event. Index row Part 6 → `done @ §5 gate <date>`; `git add docs/PILOT_LOG.md docs/superpowers/plans/2026-09-07-mvp-launch-index.md && git commit -m "Add before-real-students gate record; Part 6 done"`.

## Self-Review Notes

- All curl bodies, expected codes, and the five §3 checks are verbatim from PROVISIONING_CHECKLIST §1–5 and CANVAS_RUNBOOK §3 (verified 2026-09-07). `$HOST` = `https://original-pilot.onrender.com`; `$MAINTENANCE_TOKEN` from the env sheet — never echoed into logs or this file.
- `pilot_preflight.py`'s exact flag spelling (`--profile pilot` vs `--env pilot`) should be reconciled against the script's `--help` on the day; the verdict contract (`READY`/exit 0) is the invariant.
