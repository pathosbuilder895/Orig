# Plan 05 — Merge queue, doc truth, and small debts

> **For agentic workers (Codex):** Goal-oriented brief. Every goal here is small and
> independent; this plan is safe to run in parallel with all others, EXCEPT that M1's
> first two items are already claimed by Plan 01 (G1/G2) — skip them if Plan 01 has
> landed. The theme: the repo's *documents* must tell the truth about the repo's
> *state*, and stranded one-commit fixes must stop being stranded.

**Goal:** Zero contradictions between docs and code; the verify-and-land queue of
unmerged branches emptied (landed or explicitly declined with a written reason); the
small named debts closed; every genuinely human decision packaged as a memo rather
than left as a TODO.

## Global constraints

Same base set as Plan 01 (venv absolute path; full-suite duration; postgres marker
tests when persistence is touched; coverage margin; `git rm` not `rm`; branch + PR,
no pushes to main; commit style). Plus:

- **Verify-before-merge, always:** most of the 33 branches with commits not on main
  are stale — their content reached main via squash. For every branch: check with
  `git cherry main <branch>` / a content diff whether the work is already present
  before proposing a merge. Re-merging a stale branch is the classic way to
  resurrect reverted code.
- **Branch deletion needs the human:** produce the audited stale list; do not delete
  branches yourself.
- After editing any `demo/bluebook/*.jsx`: `cd demo/bluebook && npm run build` and
  commit the bundle (Render has no Node; the committed `bluebook.bundle.js` is what
  production serves).

---

## M1. The verify-and-land queue

For each, verify still-unmerged, rebase/apply onto a fresh branch from main, run the
relevant tests, PR with the original commit's intent preserved:

1. ~~`claude/gates-all-evaluable`~~ → **Plan 01 G1.** Skip here.
2. ~~`claude/readme-capabilities-docs-1e63d4`~~ → **Plan 01 G2.** Skip here.
3. `claude/consent-retention-model` (2 commits, docs only): a fully-written spec
   (`docs/superpowers/specs/2026-08-17-consent-retention-design.md`, 271 lines) and
   plan (1,581 lines) for a FERPA-adjacent consent/retention workstream — neither
   file exists on main. Land the **documents** (they are specification work product;
   losing them to a stale branch is pure waste). Implementation is NOT authorized by
   landing the docs — put that sentence in the PR description.
4. `claude/admin-health-gate` (`cd8f9ee0`, 2026-08-02): gates `/admin/health` and
   enumerates admin routes from the app itself — security-adjacent, small. Verify it
   still applies to the current router layout, run the API tests, land.
5. `claude/loving-kare-aaebca` (`2e79b3b4`): shows the launch-bound student in the
   Bluebook exam room. Rebuild + commit the bundle per the constraint above; verify
   in the browser preview before declaring done.
6. PR #160 (`claude/typing-cadence-benchmarks-fdb276`): recalibrates Tier-17
   estimators/bounds against published keystroke benchmarks. Review it properly
   (Tier 17 is disabled, so this is low-risk calibration groundwork that should be
   in place *before* the Bbook keystroke pipeline goes live); if sound, approve-and-
   merge path per repo convention; if not, write the review and leave it open.
7. `claude/topic-sensitivity-derivation` → **Plan 02 C11.** Skip here.

**Acceptance:** each item is merged, or has a written decline note in the PR/branch
discussion; no silent skips.

## M2. Audit and propose pruning of the stale-branch pile

83 local branches, 33 with commits not on main, most stale-by-squash. Produce
`docs/superpowers/plans/2026-08-26-branch-audit.md`: a table of every branch —
last commit date, commits-not-on-main count, verdict (`landed-via-squash` /
`superseded-by <thing>` / `live, see Plan NN` / `unknown, human review`), with the
`git cherry`/diff evidence one line each. Recommend deletions; **do not perform
them**. Special rows: `backup-155-full` and `codex/pre-sync-backup` are backups —
mark "keep unless human says otherwise."

**Acceptance:** committed audit doc; zero branches left in `unknown` without a
stated reason.

## M3. Dependabot policy + the sklearn tripwire

22 open Dependabot PRs (12 npm across `app/` + `demo/bluebook`, 10 pip). Do not
mass-merge. Deliverables:

1. A written policy paragraph in `docs/OPS_RUNBOOK.md`: npm bumps for
   `demo/bluebook` require the bundle rebuild in the same PR; pip bumps touching the
   scoring stack (`pydantic` #173, `starlette` #169, `httpx` #163) merge only after a
   full local suite + postgres marker run; **any bump that moves scikit-learn or
   joblib triggers the AI-detector version-skew runbook — the loader smoke-predicts
   8 reference vectors at startup and disables itself on >0.02 drift; the remedy is
   retrain (`scripts/train_ai_detector.py`) and a new artifact, never pinning around
   it.** Same logic applies to `style_authorship_v1.joblib`.
2. Execute the policy on the current 22: batch what's safe, retrain where triggered,
   close-with-comment anything superseded.

**Acceptance:** policy committed; PR count at zero or each remainder carries a
comment saying what it's waiting on.

## M4. Rewrite `.env.example` to document the live surface

The current file (138 lines, 53 vars) documents **only the dormant v1 backend**
(`APP_NAME`, `REDIS_URL`, `_ALLOWED_ORIGINS_STR`…) and **zero** live scoring flags —
no `NULL_MODEL`, `LLR_ACTION_MODE`, `GENRE_RESOLVER_V2`, `TOPIC_*`,
`CHARACTERISTIC_WEIGHTS`, `FUSED_SCORE_*`, `AI_LIKELIHOOD_*`, `BAYESIAN_PRIOR_*`,
`TYPICALITY_*`. Rewrite it from CLAUDE.md's flag table (the authoritative source):
one line per live flag with default + one-clause description + the ⚠️ markers for
score-changing flags, a clearly-labeled "dormant v1 (do not configure)" section or
outright removal of the v1 block (removal preferred; check nothing in `original/cli/*`
docs references it), and the ops vars (`ORIGINAL_ENV`, `REPO_BACKEND`,
`ALLOWED_ORIGINS`, throttles) per `docs/OPS_RUNBOOK.md`.

**Acceptance:** every flag in CLAUDE.md's table appears; nothing dormant is presented
as live; a test or CI grep is NOT required (this is a doc), but the PR shows the
diff against the flag table.

## M5. Verification floor: wire it or label it

`VERIFICATION_MIN_WORDS=300` / `check_verification_pool()`
(`validation/corpus_policy.py`) is a declared constant with **no production caller**
— tests only. Decide by doing: the natural caller is wherever verification-style
scoring pools get assembled in the validation layer (mirror how
`validation/public_authors/run.py` calls `check_attribution_pool()` at load). If a
sensible call site exists, wire it with the same exclude-not-abort semantics and add
the test. If genuinely nothing consumes verification pools yet, change the docstring
and `validation/README.md` to say "declared for future verification runners;
enforced nowhere" so the docs stop implying otherwise.

**Acceptance:** either a caller + test, or corrected docs. No third state.

## M6. Close the last code TODO

`original/routers/students_scoring.py:54`:
`existing_result = None  # TODO: retrieve from cache by submission_id`. Two honest
options: implement a submission-id → result lookup against the existing persistence
(if `scoring_results`/equivalent rows are queryable by submission id — check the
repository layer), or delete the dead variable + comment and let re-scores recompute
(current de-facto behavior). Pick based on what the endpoint's callers actually need
(Bluebook re-polls?); document the choice in the commit message.

**Acceptance:** the TODO is gone; behavior covered by a test either way.

## M7. Small doc-truth fixes (one commit)

- `original/features/tier4.py:4` says "Eight features" — 7 exist. Fix to 7.
- `original/features/tier7.py:4` says "Seven features" — 6 exist. Fix to 6.
- `original/context/report.py:49` comment cites "the current `monitor` action
  threshold (0.55)" — `ACTION_THRESHOLDS` moved to 0.40/0.60. Fix the comment (and
  check the 0.30 "authentic" bound's justification sentence still holds).
- Grep for other stale threshold citations:
  `grep -rn "0\.55" original/ docs/ README.md MODEL_CARD.md` and judge each hit.

**Acceptance:** one commit, each fix cited against the constant it now matches.

## M8. Memos for the humans (write, don't act)

Three decisions are explicitly not an agent's to make. For each, write a one-page
memo in `docs/adr/` (proposed-status ADR format) laying out options + evidence +
a recommendation, and stop:

1. **`AUTH_WEIGHTS` dead arms.** Every provenance has weight > 0, so the
   `unverified`-skips-drift-check arms are dead — *contradicting the inline comment's
   stated intent*. Options: set `unverified: 0.0` (behavior change: unverified
   samples stop contributing entirely), change the comment to match reality, or keep
   the arms for a future provenance. Include the branch-coverage report's finding.
2. **Dormant v1 pruning (master-plan T3).** Inventory what `original/api/`,
   `original/main.py`, `original/core/`, `original/db/`, `/canvas/lti/*` still
   reference; the known absurdity (`Settings._ALLOWED_ORIGINS_STR` means v1's prod
   CORS check can never pass); the deletion-vs-quarantine options and test impact.
3. **"Mark Reviewed" persistence** (`docs/BUGS_FOUND_2026-07-08.md:73`) — blocked on
   a `store.py`/`api.py` schema change; sketch the minimal schema addition and its
   migration cost on both backends.

**Acceptance:** three proposed-status ADRs; no behavior changes in this goal.

## M9. Plan-file hygiene note

Add one paragraph to `docs/superpowers/plans/2026-07-24-pilot-launch-master-plan.md`'s
header (it already says checkbox state is stale) and to the campaign overview: plan
checkboxes in this repo are historically unmaintained; the convention going forward
is that **campaign plans (this series) get their checkboxes ticked in the PR that
completes each goal**, and completion reports (the 2026-08-20 branch-coverage one is
the model) are the durable record.

**Acceptance:** paragraph landed; this campaign's own plans follow it.
