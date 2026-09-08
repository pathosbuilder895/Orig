# Branch Coverage Initiative — Index Plan

> **STATUS: COMPLETE (2026-08-20).** All 8 parts landed via superpowers:subagent-driven-development, plus a final cross-cluster sweep. Full-suite branch coverage: **77.13% → 99.61% combined** (45 missing statements, 12 missing + 10 partial branches, out of 11,601 stmts / 3,024 branches). `app/src` branch coverage: **91.32% → 100%**, enforced by CI thresholds (`app/vite.config.ts`). CI's coverage gate now runs `--cov-branch --cov-fail-under=98` (`.github/workflows/test.yml`). This document is kept as the historical record and reference for anyone auditing what shipped — see each part's Status row below and `docs/superpowers/plans/2026-08-20-branch-coverage-completion-report.md` for the full retrospective (bugs found, process incidents, lessons).

> **For agentic workers:** This is the umbrella document for a multi-part effort. Each part below is its own self-contained implementation plan; execute ONE part per session with superpowers:subagent-driven-development or superpowers:executing-plans. Do not attempt multiple parts in one session — a part is sized to a session.

**Goal:** Take `original/` from the measured **77.13% branch coverage (699 missing branches, plus 359 partially-taken)** and `app/src` from 91.32% to a state where every *reachable* logical branch is exercised by a test and every *unreachable* one carries a justified annotation — so behavior on error paths, flag combinations, and degraded fallbacks is verified rather than assumed.

**Why branch, not line:** the prior coverage push ratcheted CI's line gate to 78. Line coverage counts a `if cond: X` as covered when `X` ran; it says nothing about the `not cond` path — which in this codebase is where the score-changing decisions live (flag gates, fail-closed loaders, three-valued gate verdicts, degraded-path sentinels). The measured gap between line (83.34%) and branch (77.13%) is exactly that untested conditional surface.

**Baseline (authoritative, 2026-08-17):** `docs/superpowers/plans/2026-08-17-branch-coverage-baseline.md` — run metadata, cluster tables, and the per-function gap digest every part plan's tables are drawn from.

## Global Constraints (inherited by every part plan)

- **Python:** always `/Users/andrew/Desktop/Original/.venv/bin/python` — never system `python3`. Inside a git worktree the relative `.venv/bin/python` does not exist; use the absolute path.
- **Measurement requires local Postgres:** `make db-up` first (Docker; `scripts/local_postgres.sh`). Without it the 166 postgres-marked tests self-skip and `original/postgres_repository.py` reads ~0%.
- **The full-suite measurement command** (~14 min — never run it on a short tool budget):

  ```bash
  DATABASE_URL=$(bash scripts/local_postgres.sh url) \
    .venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q \
    --cov=original --cov-branch --cov-report=json:coverage.json --cov-report=term-missing
  ```

  Then rank with `.venv/bin/python scripts/branch_coverage_report.py coverage.json --cluster <part-cluster>`.
- **Per-module gap extraction** (which exact branches are untaken):

  ```bash
  .venv/bin/python - <<'EOF'
  import json
  path = "original/store.py"   # ← module under work
  f = json.load(open("coverage.json"))["files"][path]
  print("missing branches (source line -> untaken destination; negative = function exit):")
  for src, dst in f["missing_branches"]:
      print(f"  {src} -> {dst}")
  for name, fn in sorted(f["functions"].items()):
      s = fn["summary"]
      if s["missing_branches"]:
          print(f"{name}: {s['covered_branches']}/{s['num_branches']} branches covered")
  EOF
  ```
- **Never weaken an existing assertion** or an existing flag-off byte-identical guarantee to make a new test pass. The flag table in `CLAUDE.md` is the contract: tests for a flag's `on`/`shadow` behavior must leave the default-off tests untouched.
- **Unreachable branches get annotations, not contortions:** `# pragma: no cover` on genuinely unreachable defensive arms, `# pragma: no branch` on loops/conditions that structurally cannot take the other path — each with a one-line justification comment. An annotation without an argument is a plan violation; when in doubt, the branch is reachable and needs a test.
- **New test files follow the mapper convention** (`tests/**/test_<module-stem>*.py`) so the `changed-tests` pre-push hook associates them; postgres-dependent tests carry `@pytest.mark.postgres` and self-skip cleanly.
- **A clean run is 0 failed.** Suite baseline: 2334 passed / 5 skipped with Postgres up.
- **Commit style:** `Add ...` / `Fix ...`, one focused commit per task, co-author line `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## The Parts

Ordered by risk-weighted priority, not raw gap count: persistence guards student data (FERPA), the API surface is what the pilot actually exercises, and the "other" cluster hides two fully-untested security/compliance tools.

| Part | Plan file | Scope (cluster) | Baseline branch % | Missing | Status |
|---|---|---|---|---|---|
| 1 | `2026-08-17-branch-coverage-part1-persistence.md` | `store.py`, `repository.py`, `postgres_repository.py`, `db/` | 79.67% | 74 | **done @ 99.73%** (367/368, 1 missing) |
| 2 | `2026-08-17-branch-coverage-part2-api-routers.md` | `api.py`, `routers/`, `lti.py`, `schemas.py` | 68.11% | 162 | **done @ 98.82%** (502/508, 6 missing — cluster `api`) |
| 3 | `2026-08-17-branch-coverage-part3-security-cli-support.md` | `cli/`, `core/`, `_env.py`, `student_auth.py`, `principal.py`, `voice.py`, `tension_arc.py`, `explainer.py`, `users.py`, `backup.py`, `baseline_requests.py` | 50.48% | 208 | **done @ 98.81%** (415/420, 5 missing — cluster `other`) |
| 4 | `2026-08-17-branch-coverage-part4-integrations.md` | `bbook_client.py`, `lab/`, `canvas/`, `fusion/`, `ai_likelihood.py`, `style_authorship.py` | 72.63% | 75 | **done @ 100%** (274/274) |
| 5 | `2026-08-17-branch-coverage-part5-context.md` | `context/` | 84.18% | 56 | **done @ 100%** (354/354, incl. `context/pipeline.py` — discovered mid-effort, not in original plan file list) |
| 6 | `2026-08-17-branch-coverage-part6-features.md` | `features/` | 87.72% | 84 | **done @ 100%** (652/652) |
| 7 | `2026-08-17-branch-coverage-part7-app-frontend.md` | `app/src` (vitest) | 91.32% | 17 | **done @ 100%** (185/185, enforced by CI threshold) |
| 8 | `2026-08-17-branch-coverage-part8-quantum.md` | `quantum/` | 91.15% | 40 | **done @ 100%** (448/448) |

**Residual 12 missing branches** (the gap between 99.60% cluster-average and 100%) live in files whose plan-guessed arm counts undercounted their real residue and were closed by a final cross-cluster sweep task, not by any single part above: `original/routers/students_baseline.py` (3, all `AUTH_WEIGHTS`-dead — accepted, pending a product decision on the `unverified` provenance weight), `original/tension_arc.py` (3, the `if __name__ == "__main__":` CLI self-test block — genuinely unreachable via pytest import), `original/cli/delete_student.py` (1, `if __name__`), `original/cli/security_audit.py` (1, `if __name__`), `original/postgres_repository.py` (1), `original/routers/imports.py` (1, `AUTH_WEIGHTS`-dead), `original/routers/students_scoring.py` (1, a hardcoded-`None` cache stub awaiting a real caching implementation), `original/routers/tenants.py` (1, pydantic rejects the offending input before the guard can fire). None are pragma'd — each is either a `__main__` guard (no repo convention for subprocess-testing those) or an accepted-dead arm pending a named product decision; see `docs/superpowers/plans/2026-08-20-branch-coverage-completion-report.md` for the full list with reasoning.

Status column values are final; this table is the effort's completed dashboard, kept for audit/reference.

## Cross-cutting themes the parts must respect

1. **Flag-gated branches are the highest-value targets.** Many untaken branches are `on`/`shadow` arms of env flags (`RANK_REMEDIATION=shrinkage` → `_ledoit_wolf_shrink` 0/4 branches; `LLR_ACTION_MODE` arms in `_recommend`; loader fail-closed paths in `genre_v2`/`style_authorship`/`ai_likelihood`/`fusion.artifact`). Tests for these must assert BOTH the flag behavior AND that flag-off remains byte-identical where CLAUDE.md documents that guarantee.
2. **Error/degraded paths are product behavior here.** Fail-closed loaders, `degraded: True` topic-resolver sentinels, `uninformative` gate verdicts, and abstention paths are documented product decisions — a test that exercises them pins a promise, not an implementation detail.
3. **Dormant-v1 modules get tests where they are still load-bearing.** `original/cli/delete_student.py` (the documented manual FERPA-deletion path) and `original/cli/security_audit.py` are runnable tools at 0% coverage. Part 3 covers them. The rest of the dormant v1 surface (`core/config.py` etc.) gets thin reachability tests only — do not build out coverage for code whose deletion is already planned.
4. **Partial branches (359) count too.** After the missing branches close, the `num_partial_branches` figure in a re-measure shows conditions where only one arm ever ran; parts should drain their cluster's partials as they go rather than leaving a second pass.

## CI ratchet policy — APPLIED (2026-08-20)

CI (`.github/workflows/test.yml` pytest job) now runs `--cov-branch --cov-fail-under=98`, up from the prior line-only `--cov-fail-under=78`. Final measured combined (statements+branches) coverage was **99.61%**; per the policy below (`floor(measured) − 1`), the floor landed at **98**, leaving ~1.6 points of headroom for runner-to-runner variance. `app/src`'s equivalent gate lives in `app/vite.config.ts`'s `coverage.thresholds` (`branches: 100`, `statements: 99`, `functions: 96`, `lines: 98`) and runs via `npm run test:coverage` in the `app` CI job.

Policy as applied throughout the effort, kept here for reference:
- **When Part 1 landed:** added `--cov-branch` to the CI pytest invocation, kept `--cov-fail-under=78` (measured headroom ≈4 points at the time). CI's percent then meant statements+branches.
- **As each further part landed:** the floor was intended to ratchet up part-by-part, but was instead raised ONCE at the very end (after the final cross-cluster sweep) rather than incrementally — see the completion report's "process deviations" section for why (each part's own full-suite re-measure was skipped in favor of per-part scoped verification, with one whole-suite checkpoint after Part 6 and the final measurement after the sweep). The final jump (78 → 98) was measured directly off the last full-suite run before applying it, so the "never past what was actually measured" invariant held even without the intermediate steps.
- **Never lower the floor to admit a regression** — held throughout; the floor only ever moved up.

## Execution order and hand-off — COMPLETE

All 8 parts executed in numeric order via superpowers:subagent-driven-development (implementer + independent reviewer per task, fix-and-re-review loops on every finding). See `docs/superpowers/plans/2026-08-20-branch-coverage-completion-report.md` for: the full task-by-task ledger, seven production bugs found and fixed along the way, one test-isolation bug (Postgres schema-drop ordering) that only a full-suite run surfaced, and one process incident (a subagent operating in the wrong git checkout) that was caught, disclosed, and cleanly reverted.
