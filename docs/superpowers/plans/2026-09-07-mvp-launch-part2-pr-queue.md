# MVP Launch Part 2 — PR-Queue Triage

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read `2026-09-07-mvp-launch-index.md` §Global Constraints first — they all apply here.

**Goal:** Every PR open on 2026-09-07 (~25: #160, #193, #194, #195, ~20 dependabot) is merged, closed-with-rationale, or pinned-with-reason, and the #160 decision is logged — so the queue stops accumulating rebase debt and nothing pilot-relevant sits undecided when students arrive.

**Architecture:** One pass, ordered by blast radius: the substantive PRs first (#160 because it has a hard deadline against Part 6; #195/#194/#193 because they decide which September work lands), then the mechanical dependabot batch, then the majors one at a time with an escape hatch. Every disposition gets a written rationale on the PR — "closed" without a reason is not a disposition.

**Tech Stack:** GitHub PR review, `@dependabot rebase`, full local suite for majors.

**Venue:** Mac preferred (majors want the full local suite + Postgres); cloud acceptable with CI as the arbiter.

**Depends on:** Part 1 merged (rebase the queue over that large merge exactly once).

## Global Constraints (additional to the index's)

- **Hard sequencing edge: #160 must be dispositioned (merged or closed-with-rationale) before the first proctored Bluebook sitting** (Part 6). It recalibrates the six Tier 17 estimators; changing what the features mean after real keystroke baselines accumulate invalidates those baselines. Tier 17 is in `DISABLED_FEATURE_GROUPS`, so no production score moves either way — the deadline is about data continuity, not scores.
- Dependabot merges are sequential, not parallel — they contend on the same lockfiles.
- A major bump that balloons into a refactor gets pinned-and-deferred with a written note, not absorbed. Timebox each major to one sitting.

## Entry facts (snapshot 2026-09-07 — re-verify the live PR list first)

#160 (Tier 17 recalibration, open since 08-11) · #193 (docs/testing/, 11 docs, references sha `0d35d486`) · #194 (codex campaign plans + a self-described diverged copy of the coverage effort) · #195 (TermSim harness @ `0d35d486` — apparently the carrier of the September Mac work, including the architecture review's claimed scoring-defect fix) · ~20 dependabot (majors: ruff 0.6.9→0.16.2, pydantic 2.9.2→2.13.4, eslint 9→10.x) · unreviewed branches without PRs: `sprint/lane-b-codex`, `sprint/lane-c-research`.

---

### Task 1: Decide #160 — Tier 17 recalibration (worked example)

**Files:**
- None in this repo directly; the PR's own diff (estimator/bounds changes + tests).

**Interfaces:**
- Consumes: post-Part-1 main (coverage tests now exercise `tier17` branches — expect test-file conflicts on rebase).
- Produces: the decision Part 6's first-sitting gate checks.

- [ ] **Step 1: Rebase and re-verify.** `@dependabot` doesn't manage this one: check out the branch, `git rebase origin/main`, resolve (coverage tests are the likely conflict surface), run `make db-up && DATABASE_URL=$(bash scripts/local_postgres.sh url) /Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q`. Expected: 0 failed. A tier17-test failure means the recalibration and the new coverage tests disagree about the estimators' contract — surface the diff to the human with both sides, do not pick silently.
- [ ] **Step 2 (⛔ HUMAN): Merge or close.** Decision inputs, pre-gathered: the PR's rationale (align estimators with published keystroke benchmarks), the flag table's standing rule (Tier 17 disabled → zero score impact today), and the deadline above. Either outcome is fine; an outcome with no written rationale is not.
- [ ] **Step 3: Log it.** PILOT_LOG line `| <date> | <who> | #160 <merged|closed>: <one-line rationale> | |`; `git add docs/PILOT_LOG.md && git commit -m "Add #160 disposition to the pilot log"`.

### Task 2: Disposition the September trio — #195, then #194, then #193 (in that order)

- [ ] **Step 1: #195 (the substance).** It carries the TermSim/G5-G6/September work — including, per #193's review summary, a fix for a **pilot-blocking scoring defect** ("genuine authors score `escalate` at the pilot's modal three baselines"). Review it as a real change: rebase over post-Part-1 main, full suite, read the scoring diff with the score-integrity lens (flag-off byte-identity). ⛔ HUMAN merges, splits, or closes. Whatever happens here feeds Part 4's pre-deploy gate — record the defect-fix status explicitly in the PILOT_LOG line.
- [ ] **Step 2: #194 (the duplicate).** Post-Part-1 its coverage payload is redundant by construction. Close with a comment linking Part 1's inventory; ⛔ HUMAN may opt to salvage its six codex-campaign plan docs onto a fresh branch from new main — noting campaign-03's proposed `shadow_soak_report.py` must reconcile with Part 3's shipped readers rather than duplicate them.
- [ ] **Step 3: #193 (the docs).** Doc-only. Verify its internal references resolve against main *after* the #195 decision (it was written against `0d35d486`); if references dangle, request amendment rather than merging broken links. ⛔ HUMAN decides.
- [ ] **Step 4:** Ask the human what `sprint/lane-b-codex` / `sprint/lane-c-research` are; branches with no PR and no owner note get a PILOT_LOG line and are left alone. Commit the PILOT_LOG lines: `git commit -m "Add September-PR dispositions to the pilot log"`.

### Task 3: Dependabot batch — patch/minor (~16 PRs)

- [ ] **Step 1:** For each, oldest first: comment `@dependabot rebase`, wait for CI green, ⛔ HUMAN merge. Sequential. The `demo/bluebook` esbuild/axe bumps do not by themselves require a bundle rebuild (the committed bundle only changes when JSX changes).
- [ ] **Step 2:** Any patch/minor PR whose CI fails after rebase gets one look — if the failure is the dependency's, close with the failure linked; if ours, it graduates to Task 4 treatment.

### Task 4: Majors, individually

- [ ] **Step 1: ruff 0.6.9 → 0.16.2.** Run the new ruff locally first: `ruff check original/ && ruff format --check original/` under the bumped version. Clean → merge. A large mechanical diff → pin the old version in the PR's stead with a `# ruff pinned: see PR #174 note` rationale and defer; do not run `ruff --fix` across the tree inside a dependency bump.
- [ ] **Step 2: pydantic 2.9.2 → 2.13.4.** Full suite; watch `schemas.py` and deprecation warnings. Same merge-or-pin rule.
- [ ] **Step 3: eslint 9 → 10.x.** `cd app && npm run lint` — config migration expected; small → do it in the PR, large → pin-and-defer.

### Task 5: Close out

- [ ] **Step 1:** Verify the queue: every PR open on 2026-09-07 is merged / closed-with-rationale / pinned-with-reason. List survivors and their reasons in one PILOT_LOG line.
- [ ] **Step 2:** Update the index dashboard row for Part 2 → `done @ queue=<n> kept-on-purpose`; `git add docs/PILOT_LOG.md docs/superpowers/plans/2026-09-07-mvp-launch-index.md && git commit -m "Add Part 2 completion: PR queue dispositioned"`.

## Self-Review Notes

- The "#195 carries the scoring-defect fix" claim is inferred from #193's body text, not from reading #195's diff — Task 2 Step 1 verifies it directly; if the fix is NOT there, the defect is still stranded on the Mac's local main and must be raised to the human immediately (it gates Part 4's real-scoring decision).
- PR numbers/counts are a 2026-09-07 snapshot; the first action is re-listing the live queue.
