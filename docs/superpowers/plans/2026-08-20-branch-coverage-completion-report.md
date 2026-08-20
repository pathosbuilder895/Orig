# Branch Coverage Initiative — Completion Report

**Status:** Complete. 2026-08-18 to 2026-08-20.

**Method:** superpowers:subagent-driven-development — a fresh implementer subagent per task, followed by an independent reviewer subagent instructed to distrust the implementer's report and re-verify claims against source, with fix-and-re-review loops on every finding before a task was marked done.

## Headline numbers

| Metric | Baseline (2026-08-17) | Final (2026-08-20) |
|---|---|---|
| `original/` branch coverage (combined stmts+branches) | 77.13% branch / 82.05% combined | **99.61% combined** (11,601 stmts, 45 missing; 3,024 branches, 12 missing + 10 partial) |
| `app/src` branch coverage | 91.32% (179/196) | **100%** (185/185), enforced by `app/vite.config.ts` thresholds |
| Full suite | 2334 passed / 5 skipped (no Postgres) | **3263 passed / 5 skipped / 0 failed** (Postgres up) |
| CI coverage gate | `--cov-fail-under=78` (line-only) | `--cov-branch --cov-fail-under=98` |
| New tests added | — | ~950 across 8 parts + sweeps |

## Per-part results

See the dashboard table in `docs/superpowers/plans/2026-08-17-branch-coverage-index.md` for exact per-cluster percentages. All 8 parts reached 98.8%+ branch coverage on their target clusters; 5 of 8 (integrations, context, features, app-frontend, quantum) reached exactly 100%.

Two clusters gained scope beyond their original plan file lists, discovered by whole-cluster measurements after the individually-planned files closed:
- **Part 5 (context):** `original/context/pipeline.py` (the adaptive-scoring orchestrator) — not in the original plan, found at 75%/81%, closed to 100% (6 tests covering all four exception-fallback arms of a `ThreadPoolExecutor`-based orchestration function).
- **Part 8 (quantum):** `original/quantum/pooled_source.py` — not in the original plan, found at 92%, closed to 100% (1 test for a malformed-input except-guard).

A final cross-cluster sweep closed 12 residual branches spread across four files that no single part's plan had targeted precisely enough (`admin.py`, `students_scoring.py`, `store.py`, `upload_utils.py`) — see the index doc's dashboard notes for the full list.

## Production bugs found and fixed (7)

Independent, adversarial review — not just running the new tests — surfaced seven real defects in production code, all fixed and verified within the same task's review loop:

1. **Sqlite calibration-run timestamps at whole-second resolution** (Part 1 Task 2). `store.py`'s `start_calibration_run` stored `started_at` at whole-second precision while Postgres stored microseconds, so `list_calibration_runs`' newest-first ordering was undefined on same-second sqlite rows. Fixed to microsecond resolution.
2. **`PostgresRepository.delete_student` never purged `audit_log`** (Part 1 Task 3). A FERPA erasure divergence: sqlite's `delete_student` explicitly deleted audit rows, Postgres's did not. Reproduced failing, fixed with the correct tenant/local-id keying (`_split_for_audit`, not `split_scoped_id`), both backends verified green.
3. **`PostgresRepository.get_genre_stats` missing the genre-unknown abstention guard** (Part 1 Task 5). Latent — only reachable under `BAYESIAN_PRIOR_ENABLED=1` — but would have let Postgres pool `genre="unknown"` samples into a prior, unlike sqlite's twin. Fixed to match.
4. **`upload_baseline_batch` cross-request duplicate detection never worked** (Part 2 Task 1). Checked a dynamic `.text_hash` attribute that neither storage backend ever persisted, so every request after the first re-derived samples with `text_hash=None` and could never detect a re-upload. Fixed to seed from `_existing_text_hashes()`, the same correct path `add_baseline`/`imports.py` already used.
5. **The documented FERPA `delete_student` CLI could never delete anyone** (Part 3 Task 1). `original/cli/delete_student.py`'s two `.join().delete()` calls raise `sqlalchemy.exc.InvalidRequestError` unconditionally — a 100%-reproducible, input-independent bug in the CLI CLAUDE.md names as *the* documented manual FERPA-deletion path. Fixed with subquery-based deletes.
6. **`tests/test_persistence_error_arms.py`'s Postgres tests checked reachability, not schema existence** (found via a full-suite checkpoint after Part 6). Not a production bug, but a real test-isolation defect: `test_cutover.py`/`test_migration.py` both call `LiveBase.metadata.drop_all()` in teardown and run alphabetically before these tests in a full-suite pass, so the schema was gone by the time they ran — hard `UndefinedTable` failures instead of a clean pass. Fixed by centralizing `LiveBase.metadata.create_all()` (idempotent) into the shared availability-check helper.
7. **A pre-existing `test_professor_narrative.py` test used a mismatched dict key** (Part 8 Task 4). `_FEATURE_PLAIN["avg_sentence_length"]` was never a real key (the real one is `mean_sentence_length`), so the test's target branch silently no-op'd every run while the test still passed (its assertion was weak enough to be satisfied by the fallback path too). Fixed — a test bug, not a production bug, but caught by the same "do the math yourself" discipline applied to new tests.

Three additional **test-construction defects** (not production bugs — new tests whose own math didn't match their claimed scenario) were self-caught and fixed by implementers before finalizing, in the math-critical quantum cluster (Part 8 Tasks 1, 2, 4), each independently re-verified by the reviewer via hand computation:
- A shrinkage-clamp test claimed `alpha` hit its `min(1.0, ...)` clamp; the actual math for its chosen inputs gave `alpha=0.75` (unclamped), masked by a vacuous if/else. Fixed with inputs that genuinely clamp (`alpha_raw=1.5 → 1.0`).
- A `CHARACTERISTIC_WEIGHTS` bit-identical abstain proof covered one of two documented abstain conditions (no `impostor_stats`) but not the other (thin baseline) at the full `score()` level — closed with a matching test, isolation proven via an empirical A/B toggle.
- A "regressive trajectory" test fixture accidentally produced a zero trajectory vector because `_compute_trajectory` unit-normalizes each sample before the slope fit, collapsing a uniform-magnitude decreasing sequence to nothing. Fixed with a genuine two-feature swing.

## Process notes for future SDD efforts

**Plan arm-counts were stale almost everywhere.** Nearly every task found the plan's guessed missing-branch counts and line numbers didn't match a fresh measurement — sometimes wildly (a "5/16 missing" turned out to be 7; a "4/10" turned out to be 6; a suggested `-k` measurement filter both false-positived on unrelated files and missed the actual primary test file for seven target modules). The pattern held up throughout: **trust a fresh `--cov-branch` measurement over the plan's numbers, every time.**

**A wrong-checkout incident** (Part 5 Task 4): a fix subagent operated in the primary repo checkout (`/Users/andrew/Desktop/Original`, branch `main`) instead of the assigned worktree, and its report's commit SHA was real but on the wrong branch, with coverage numbers that didn't reconcile. Caught by a sanity mismatch, verified via `git log`/`git branch --contains`, confirmed with the user, and cleanly reverted (`git reset --hard origin/main` on the stray local-only commit — never pushed, so no shared-branch risk). One incidental miss: the reset also discarded an uncommitted change to a scratch/regenerated diagnostics file in that checkout without stashing first — assessed low-risk after verification (the file was restored to its last-committed state, and identical copies existed untouched in two other worktrees) but disclosed rather than silently absorbed. From that point on, every implementer dispatch required an explicit working-directory/branch confirmation as its first step, and the controller verified every reported commit SHA landed on the correct branch (`git merge-base --is-ancestor <sha> HEAD`) before trusting any fix report's numbers.

**A store.py fix initially closed the wrong branch arm** (final sweep): a fix for a flagged False-arm branch instead exercised the True arm, with a report that included a plausible-sounding but factually wrong causal theory ("ambient import-order pollution") for why the fix looked like it worked. Caught by the reviewer re-running the new test in complete isolation and reading the coverage JSON's `missing_branches` directly rather than trusting a percentage. Fixed with a `monkeypatch.delitem` that deterministically forces the correct arm.

**Full-suite checkpoints matter, not just scoped verification.** Every individual task verified its own narrow scope correctly, but several defects (the Postgres schema-drop ordering bug, several undercounted arm-count residues in `admin.py`/`students_scoring.py`) were invisible to any scoped run and only surfaced when the entire test suite ran together. Two full-suite checkpoints were run during this effort (after Part 6, and at the very end); doing this once per part rather than only at milestones would likely have caught the schema-drop bug and the arm-count undercounts earlier.

**"Do the math yourself" caught real defects.** In the math-critical quantum cluster, reviewers were explicitly instructed to independently hand-derive or empirically re-execute every numeric and directional claim rather than trust a test's own comments. This caught three test-construction defects and one pre-existing test bug that ordinary "does it pass" review would have missed — all of them passed their own assertions while testing something other than what they claimed to test.

## What remains open (by design, not oversight)

- **`students_baseline.py`, `imports.py` accepted-dead `AUTH_WEIGHTS` arms** (4 branches): dead under the current `AUTH_WEIGHTS` table where every provenance has weight > 0, contradicting an inline comment's stated intent that `unverified` samples should skip the drift check. This is a product decision (should `unverified` carry weight 0?), not a testing gap — flagged for the humans, not resolved here.
- **`students_scoring.py`'s cache stub** (1 branch): `existing_result = None  # TODO: retrieve from cache by submission_id` — genuinely dead code pending a real caching implementation that doesn't exist yet.
- **`tenants.py`'s `meta`-type guard** (1 branch): pydantic already rejects non-dict `meta` at the schema layer before the guard can fire — defense-in-depth, not reachable through the API.
- **Four `if __name__ == "__main__":` CLI self-test blocks** (`tension_arc.py`, `delete_student.py`, `security_audit.py`, and one more): no repo convention exists for subprocess-testing these blocks; genuinely unreachable via a `pytest` import.
- **`Settings._ALLOWED_ORIGINS_STR`** (Part 3, dormant v1 surface, disclosed not fixed): a private pydantic attribute that means the dormant `core/config.py`'s production CORS check can never legitimately pass via any real configuration path. Flagged for whoever eventually decides to fix or delete that dormant surface — out of scope for a coverage effort to silently patch.
