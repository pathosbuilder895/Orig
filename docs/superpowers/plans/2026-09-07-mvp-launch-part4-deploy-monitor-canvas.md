# MVP Launch Part 4 — Deploy, Monitoring, and the Canvas Ask (O1 + O3 + O2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read `2026-09-07-mvp-launch-index.md` §Global Constraints first — they all apply here. This is an **ops part**: each step is one operator action + the verifying command + the exact expected output; `⛔ HUMAN` marks actions only the operator can take; any unexpected output → STOP, report BLOCKED, log it in `docs/PILOT_LOG.md`.

**Goal:** `original-pilot` live at its final host and verified on SQLite (`O1 go-live check: PASS`); an uptime monitor watching `/health`; the Canvas developer-key ask sent the **same calendar day** as the deploy (the admin reply is the schedule's long pole); the deploy release-tagged.

**Architecture:** Render blueprint deploy from `main` (`render.yaml`; `autoDeploy: false`, so deploys are manual dashboard acts), three hand-set secrets, then the read-only acceptance script. Everything here is reversible except the Canvas key's host binding — the key bakes in the tool URL, so the host must be final before the ask goes out.

**Tech Stack:** Render dashboard, `scripts/o1_golive_check.py`, UptimeRobot/BetterStack, `docs/canvas_developer_key.md` + `docs/dpa_template.md`.

**Venue:** operator + assistant. Secrets come from `~/Desktop/Original-secrets/render-env-sheet.txt` (rotated 2026-08-07) and are typed into the dashboard only.

**Depends on:** nothing — dispatch day 1. **Blocks:** Parts 5, 6, 7.

## Global Constraints (additional to the index's)

- Deploy verification pre-cutover is `scripts/o1_golive_check.py`, **never** `scripts/pilot_smoke_test.py` — the smoke test asserts `backend == "postgres"` and fails by design until Part 5.
- `CANVAS_API_TOKEN` stays **off** Render this round: the LTI launch path never uses it, the `/canvas/baseline/*` endpoints degrade to manual-upload guidance without it, and a request-body `access_token` overrides it per call.
- `BBOOK_API_URL`/`BBOOK_EXTERNAL_SECRET` are optional (external Bbook app only; the in-repo `/bluebook/` exam room does not need them) — leave unset unless the human says otherwise.

---

### Task 1: Pre-deploy gate

**Files:** none; produces the go/no-go and the deploy sha.

- [ ] **Step 1:** Pick the sha: `git fetch origin && git rev-parse origin/main`. Record it — the go-live check and release tag both take it.
- [ ] **Step 2 (⛔ HUMAN):** Confirm the env sheet exists and the LTI key is the post-rotation one: compute `python3 -c "import hashlib;print(hashlib.sha256(open('<pem-path>','rb').read()).hexdigest()[:16])"` → must print `7939c6c8a6f9a736`. Mismatch = wrong/stale key — STOP; a new key means re-issuing any Canvas developer key later, so never "just generate a fresh one."
- [ ] **Step 3 (⛔ HUMAN):** Disposition the 2026-09-02 architecture-review finding ("genuine authors score `escalate` at the pilot's modal three baselines", per PR #193/#195): confirm the fix is in the deploy sha (Part 2 Task 2's PILOT_LOG line says), or record explicit acceptance that the zero-student window may run without it — **it must be resolved before any real student is scored (Part 6 Task 5 re-checks).** One PILOT_LOG line either way; commit it.

### Task 2: Blueprint deploy (⛔ HUMAN, Render dashboard)

- [ ] **Step 1:** Delete any failed prior service on the `original-pilot` name → New → Blueprint → repo `pathosbuilder895/Orig`, branch `main` → paste `SECRET_KEY`, `MAINTENANCE_TOKEN`, `LTI_PRIVATE_KEY` (PEM with newlines escaped as `\n`) from the env sheet → leave `LTI_PLATFORMS`, `DATABASE_URL`, `REPO_BACKEND`, `REPO_SHADOW`, `MAINTENANCE_MODE` unset → Apply.
- [ ] **Step 2:** Watch the boot log: no `SECRET_KEY` refusal (the service refuses to boot without it — a crash-loop here is that). Then `curl -sD- https://original-pilot.onrender.com/health` → HTTP 200 with `"environment":"pilot"`, `"backend":"sqlite"`, and no `x-render-routing: no-server` header. Failure means the blueprint didn't bind the expected host — STOP before the Canvas ask, the key bakes the host in.

### Task 3: O1 acceptance

- [ ] **Step 1:** `python -m scripts.o1_golive_check --base-url https://original-pilot.onrender.com --expect-kid 7939c6c8a6f9a736 --expect-commit <sha-from-Task-1>` → per-check `[PASS]` lines then exactly `O1 go-live check: PASS`. Failure decode: kid mismatch = the PEM paste gained/lost a trailing newline (kid is `sha256(pem)[:16]`); any lockdown endpoint reachable anonymously = the deploy is not running this build — STOP.

### Task 4: The Canvas ask — same calendar day (⛔ HUMAN)

- [ ] **Step 1:** Render `docs/canvas_developer_key.md` to PDF. Send with `~/Desktop/Original-secrets/canvas-admin-email.md` to the Canvas admin, and `docs/dpa_template.md` to their compliance office **in parallel** (the DPA is the O6 hard gate for real students, not for sandbox work — its clock must start now). Ask the admin to also add the app to a sandbox course so the reply carries **both** values in one round-trip: **Client ID** and **Deployment ID** (the deployment id only exists after the app is added somewhere). Also confirm their Canvas hostname and cloud-vs-self-hosted (it decides the issuer in Part 6).
- [ ] **Step 2:** PILOT_LOG line with the send date — this dated line is the schedule's anchor; commit it.

### Task 5: Monitoring (⛔ HUMAN)

- [ ] **Step 1:** UptimeRobot or BetterStack monitor on `https://original-pilot.onrender.com/health`, 1–5 min interval, alert → operator email. Verify the monitor shows "up." Note for the weekly ritual: `/health` returns the student count — a 200 with a count of 0 (once students exist) is also an alarm.

### Task 6: Tag and record

- [ ] **Step 1:** `git tag pilot-<YYYY-MM-DD> <sha> && git push origin --tags` (collision → `-2` suffix per OPS_RUNBOOK).
- [ ] **Step 2:** PILOT_LOG lines: deploy (sha, `O1 go-live check: PASS`), canvas-ask sent (date), monitor live. Update the index dashboard row for Part 4 → `done @ O1 PASS <date>`. `git add docs/PILOT_LOG.md docs/superpowers/plans/2026-09-07-mvp-launch-index.md && git commit -m "Add O1 deploy, monitoring, and Canvas-ask records to the pilot log"` (via branch + PR, never direct to main).

## Self-Review Notes

- The `no-server` probe, the kid, the o1_golive_check contract, and the secrets list were verified 2026-09-07 against the live host, `original/lti.py:134-149`, `scripts/o1_golive_check.py`, and `render.yaml`. Re-probe `/health` first — if someone deployed in the interim, Tasks 2–3 collapse to verification only.
- The scoring-defect gate (Task 1 Step 3) is deliberately a *gate with an acceptance path*, not a fix: landing the fix is Part 2's job (#195). Deploying with zero students while it's open is safe; scoring real students with it open is not.
