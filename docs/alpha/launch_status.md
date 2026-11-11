# Alpha launch status (2026-10-19, ET)

> **Procedure change, 2026-10-30.** Volunteers now do **one** exam with two questions instead of timed Exams A and B: their own writing pasted into question 1, and an AI tool's piece on the same topic (given the topic only) pasted into question 2. Partner imitation and the optional Exam C are dropped. The exam needs Block copy & paste **off** and No AI assistants **off** (`setup_runbook.md` §5); the batch scorer exports each sealed exam as `<submission_id>-q1`/`-q2`. Students see the steps in the app under **Instructions**. The 2026-10-19 snapshot below is kept as it was.

## Live / done
- Pilot live on PR #291 (`d51f6e4`): 3-paper minimum enforced in code, batch scorer reports insufficient-baseline, invite links can be non-expiring. `/health` on 2026-10-19: commit `d51f6e4`, pilot, postgres, `signup_open=false` (full smoke had a transient disconnect — rerun on launch day).
- Prompts written (Exam A `night-market`, Exam B `letter-2076`, spare `island-rulebook`), 25 min, paste blocked, writing consistency OFF; scoring OFF for students, staff batch-score afterwards.
- Deletion tooling ready (`delete_alpha_tenant.py`, dry-run default, exact-name confirm) with per-person 14-day rule in `deletion_plan.md`.
- This PR: async/open-ended docs, contact `arclark555@gmail.com` everywhere, split-derived baseline tagging in the batch scorer (`baselines.csv` + report breakout), shadow metadata in `labels.csv` (evaluation-only), invite draft, Google Forms spec, calibration protocol with held-out guardrail.

## Pending — browser/Render steps for Meg, after Andrew merges this PR
- [ ] Re-confirm `INVITE_NO_EXPIRY=1` in the Render dashboard (not in `render.yaml`; cannot be verified from the repo).
- [ ] Create the alpha workspace: `invite_professor.py arclark555@gmail.com --name "Andrew (Alpha test)" --with-original --no-expiry` in Render Shell; Andrew sets password.
- [ ] Create course `ALPHA1` + both exams; verify conditions on saved summaries; publish.
- [ ] Build the consent + feedback Google Forms from `google_forms_spec.md`; dummy-test, then delete the dummy response.
- [ ] Launch-day smoke test in `dry_run_and_dayof.md`, incl. one split-derived test baseline, then delete test accounts.
- [ ] Send invites rollingly (consent first, private link each), import baselines as they arrive, batch-score as submissions arrive.

## Still needs Andrew (decisions/inputs — see final report list)
Confirm pass targets in writing; confirm prompts (incl. whether to adopt the same-prompt paired-shadow wording); how shadow partners are paired and whether staff tool-generated shadows are used (and which tool); baseline file-format handling; when to close the alpha; whether to merge #286 (not required for this alpha); ENGINE_V2 draft PR status (Deep Research, not in this PR).
