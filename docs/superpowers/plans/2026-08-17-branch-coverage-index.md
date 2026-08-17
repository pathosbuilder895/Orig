# Branch Coverage Initiative — Index Plan

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
| 1 | `2026-08-17-branch-coverage-part1-persistence.md` | `store.py`, `repository.py`, `postgres_repository.py`, `db/` | 79.67% | 74 | pending |
| 2 | `2026-08-17-branch-coverage-part2-api-routers.md` | `api.py`, `routers/`, `lti.py`, `schemas.py` | 68.11% | 162 | pending |
| 3 | `2026-08-17-branch-coverage-part3-security-cli-support.md` | `cli/`, `core/`, `_env.py`, `student_auth.py`, `principal.py`, `voice.py`, `tension_arc.py`, `explainer.py`, `users.py`, `backup.py`, `baseline_requests.py` | 50.48% | 208 | pending |
| 4 | `2026-08-17-branch-coverage-part4-integrations.md` | `bbook_client.py`, `lab/`, `canvas/`, `fusion/`, `ai_likelihood.py`, `style_authorship.py` | 72.63% | 75 | pending |
| 5 | `2026-08-17-branch-coverage-part5-context.md` | `context/` | 84.18% | 56 | pending |
| 6 | `2026-08-17-branch-coverage-part6-features.md` | `features/` | 87.72% | 84 | pending |
| 7 | `2026-08-17-branch-coverage-part7-app-frontend.md` | `app/src` (vitest) | 91.32% | 17 | pending |
| 8 | `2026-08-17-branch-coverage-part8-quantum.md` | `quantum/` | 91.15% | 40 | pending |

Update the Status column (`pending` → `in progress` → `done @ <measured %>`) as parts land; this table is the effort's dashboard.

## Cross-cutting themes the parts must respect

1. **Flag-gated branches are the highest-value targets.** Many untaken branches are `on`/`shadow` arms of env flags (`RANK_REMEDIATION=shrinkage` → `_ledoit_wolf_shrink` 0/4 branches; `LLR_ACTION_MODE` arms in `_recommend`; loader fail-closed paths in `genre_v2`/`style_authorship`/`ai_likelihood`/`fusion.artifact`). Tests for these must assert BOTH the flag behavior AND that flag-off remains byte-identical where CLAUDE.md documents that guarantee.
2. **Error/degraded paths are product behavior here.** Fail-closed loaders, `degraded: True` topic-resolver sentinels, `uninformative` gate verdicts, and abstention paths are documented product decisions — a test that exercises them pins a promise, not an implementation detail.
3. **Dormant-v1 modules get tests where they are still load-bearing.** `original/cli/delete_student.py` (the documented manual FERPA-deletion path) and `original/cli/security_audit.py` are runnable tools at 0% coverage. Part 3 covers them. The rest of the dormant v1 surface (`core/config.py` etc.) gets thin reachability tests only — do not build out coverage for code whose deletion is already planned.
4. **Partial branches (359) count too.** After the missing branches close, the `num_partial_branches` figure in a re-measure shows conditions where only one arm ever ran; parts should drain their cluster's partials as they go rather than leaving a second pass.

## CI ratchet policy

CI (`.github/workflows/test.yml` pytest job) currently gates line-only coverage at `--cov-fail-under=78`. Because the combined statements+branches metric measured **82.05%** (branch instrumentation *raises* the combined figure here — line coverage with Postgres is 83.34%), CI can switch to the honest metric immediately without going red:

- **When Part 1 lands:** add `--cov-branch` to the CI pytest invocation, keep `--cov-fail-under=78` (measured headroom ≈4 points). CI's percent then means statements+branches.
- **As each further part lands:** raise the floor to `floor(measured combined percent) − 1`, never past what the part's final full-suite run actually printed. (The −1 absorbs runner-to-runner collection variance; CLAUDE.md's warning against raising the gate past locally-measured reality stands.)
- **Never lower the floor to admit a regression** — that is the one move this whole effort exists to prevent.

## Execution order and hand-off

1. Execute parts in numeric order (1 → 8); parts 5-8 are independent of each other and may be reordered if a session has reason to.
2. First action of every part: re-run the full measurement command above (the baseline JSON is not committed; numbers drift as other work merges) and reconcile the part's tables against fresh data. Gaps already closed by other work are marked done, new gaps are added as tasks.
3. Last action of every part: full-suite re-measure, update this index's dashboard row and the CI floor per the ratchet policy, commit.
