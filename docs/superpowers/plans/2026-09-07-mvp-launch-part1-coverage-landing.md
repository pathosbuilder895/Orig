# MVP Launch Part 1 — Land the Branch-Coverage Completion

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read `2026-09-07-mvp-launch-index.md` §Global Constraints first — they all apply here.

**Goal:** origin/main carries the completed 8-part branch-coverage effort (the 2026-08-20 completion report's end state: combined statements+branches ≈99.6%, up from the 82.05% baseline); every row of `2026-08-17-branch-coverage-index.md`'s dashboard reads `done @ <measured %>`; CI's pytest job runs `--cov-branch --cov-fail-under=98`; and a post-merge CI run on origin/main is green under that gate.

**Architecture:** The finished work lives in the Mac worktree `~/Desktop/Original/.claude/worktrees/test-coverage-postgres-setup-b16499` (its branch's PR #179 merged only the *tooling*; the part executions that followed were never pushed). Land it as one rebased branch → one PR → one merge. Two other branches now claim overlapping content (PR #194's body says it embeds a diverged copy of the coverage effort; PR #195 carries the TermSim/September work) — so this part starts with an inventory that decides what is canonical before anything moves.

**Tech Stack:** git (worktree, rebase), pytest + coverage with the local Postgres container (`make db-up`), GitHub PR + CI.

**Venue:** the user's Mac. Python is always `/Users/andrew/Desktop/Original/.venv/bin/python`.

## Global Constraints (additional to the index's)

- **The worktree is canonical** for the coverage work unless Task 1's inventory proves PR #194's (or #195's) commits are the *identical* commits — in which case this part collapses to the cheaper path: rebase that PR's branch, split out its non-coverage payload (the six codex-campaign docs), and merge the coverage half. Do not hand-reconcile two diverged copies of 8 parts of test code; pick one lineage and close the other with a rationale comment.
- Never weaken an assertion or lower a threshold to survive the rebase. A test broken by the rebase means the rebase is wrong or upstream changed behavior — root-cause it.
- The CI floor lands at **98** = `floor(99.61) − 1`, per the coverage index's ratchet policy (never past what the final full-suite run actually printed; re-derive from the measured number if the completion report's figure differs).

## Entry facts (snapshot 2026-09-07 — re-verify first, they decay)

- origin/main = `0bb8e97`; CI pytest gate = `--cov=original --cov-report=xml --cov-fail-under=78`, **no `--cov-branch`** (`.github/workflows/test.yml:119`).
- All 8 rows of the coverage index dashboard: `pending`.
- Open collisions: PR #194 (`claude/architecture-testing-strategy-b13c77`, +16k lines, self-described as carrying the coverage effort + campaign docs), PR #195 (`claude/termsim-validation-harness-b04ef3` @ `0d35d486`).

---

### Task 1: Four-way inventory — establish what is where (worked example)

**Files:**
- None modified. Output is an inventory pasted into the eventual PR description and a one-line PILOT_LOG entry.

**Interfaces:**
- Consumes: the Mac worktree, `origin/main`, `origin/claude/architecture-testing-strategy-b13c77` (PR #194), `origin/claude/termsim-validation-harness-b04ef3` (PR #195).
- Produces: the canonical-lineage decision every later task depends on.

The coverage work exists in up to three places with unknown overlap. Landing the wrong copy — or both — burns days in conflict resolution and can silently drop tests. Ten minutes of `git log` prevents that.

- [ ] **Step 1: Inventory the worktree's unpushed commits**

```bash
cd ~/Desktop/Original/.claude/worktrees/test-coverage-postgres-setup-b16499
git fetch origin
git status --short                 # expect clean; stash-and-note anything dirty
git log --oneline origin/main..HEAD | tee /tmp/p1-worktree-commits.txt
wc -l /tmp/p1-worktree-commits.txt
```

Expected: a nonzero count of `Add …` coverage commits (the 8 part executions + the 2026-08-20 completion report). Zero commits means the work was already pushed under another ref — go straight to Step 2 to find it.

- [ ] **Step 2: Compare against the two claimant branches**

```bash
git fetch origin claude/architecture-testing-strategy-b13c77 claude/termsim-validation-harness-b04ef3
git log --left-right --oneline HEAD...origin/claude/architecture-testing-strategy-b13c77 | head -50
git cherry origin/claude/architecture-testing-strategy-b13c77 HEAD | grep -c '^+' || true
```

Expected: `git cherry` shows how many worktree commits are NOT patch-equivalent in #194. All `-` (everything equivalent) → #194 embeds this work: record "collapse path" and treat #194's branch as the landing vehicle (still split out its campaign docs into Part 2's disposition). Mostly `+` → the copies diverged: worktree stays canonical, #194's coverage payload is superseded (Part 2 closes it with this inventory as the rationale). Repeat the comparison against #195's branch.

- [ ] **Step 3: Record the decision**

Write the inventory (commit counts, cherry results, chosen lineage, one-sentence rationale) into a scratch file for the PR description, and append one PILOT_LOG line: `| <date> | <who> | Coverage-landing inventory: <chosen lineage> | see PR #<n> |`. Commit the PILOT_LOG line: `git add docs/PILOT_LOG.md && git commit -m "Add coverage-landing inventory decision to the pilot log"`.

### Task 2: Rebase onto origin/main and full-suite verify

- [ ] **Step 1:** On the chosen lineage: `git rebase origin/main`. Expected conflict surface (small): the `.github/workflows/test.yml` comment block, the coverage index dashboard, `CLAUDE.md` test-count prose. Resolve keeping the coverage branch's side for coverage artifacts and origin/main's side for everything it doesn't touch.
- [ ] **Step 2:** Full suite with Postgres up — budget ~15 min, never a short tool budget:

```bash
make db-up
DATABASE_URL=$(bash scripts/local_postgres.sh url) \
  /Users/andrew/Desktop/Original/.venv/bin/python -m pytest \
  tests/ validation/test_tier10_optional.py -q \
  --cov=original --cov-branch --cov-report=term
```

Expected: **0 failed**; pass count at or above the completion report's figure; combined coverage ≥ 99%. A failure here is a rebase casualty or a real upstream conflict — fix the cause, never the assertion or the floor.

### Task 3: Ratchet-artifact audit

- [ ] **Step 1:** Assert in-branch, fixing anything missing: `grep -n "cov-branch\|cov-fail-under" .github/workflows/test.yml` shows `--cov-branch --cov-fail-under=98`; all 8 rows of `2026-08-17-branch-coverage-index.md` read `done @ <measured %>`; `docs/superpowers/plans/2026-08-20-branch-coverage-completion-report.md` is present; any frontend threshold changes the worktree carries (`app/vite.config.ts`) are intact.
- [ ] **Step 2:** Commit any reconciliation: `git commit -m "Fix coverage-landing rebase artifacts: CI gate, dashboard, report"` (skip if clean).

### Task 4: Push, PR, CI green, merge

- [ ] **Step 1:** `git push -u origin <branch>` (retry with backoff on network errors). Open the PR with the Task 1 inventory in its body; title `Land the 2026-08 branch-coverage effort; ratchet CI to branch coverage at 98`.
- [ ] **Step 2:** Watch CI: the pytest job must go green under the NEW gate on the runner — that run is the proof the ratchet holds off-Mac. A coverage failure on the runner but not locally means runner-variance ate the 1-point margin: re-measure, set the floor to the runner's `floor(measured) − 1`, never below.
- [ ] **Step 3 (⛔ HUMAN):** Merge.

### Task 5: Close out

- [ ] **Step 1:** Update this effort's index row for Part 1 → `done @ CI green, floor 98`; add a hand-off note in the PR thread: every open dependabot PR now needs `@dependabot rebase` (Part 2 begins there).
- [ ] **Step 2:** `git add docs/superpowers/plans/2026-09-07-mvp-launch-index.md && git commit -m "Add Part 1 completion to the MVP-launch dashboard"` and push (via a follow-up PR or with the Part 2 batch, per repo convention — never direct to main).

## Self-Review Notes

- The 99.61%/98-floor figures come from PR #194's self-description of the completion report; the report itself was not readable from the planning session (it exists only off-origin). Task 2's measured number is authoritative — reconcile the floor against it, not against this plan.
- The exact commit count in the worktree and the #194/#195 overlap were unverifiable from the cloud planning session; Task 1 exists precisely to establish them. If the worktree is dirty or gone, STOP and report BLOCKED with `git status` output — do not reconstruct coverage work from memory.
