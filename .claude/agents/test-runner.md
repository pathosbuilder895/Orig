---
name: test-runner
description: Runs the Original test suite (full or targeted) and triages the results into a verdict. Use PROACTIVELY after any code change to original/, validation/, or tests/, and whenever asked to "run the tests" or verify a change. Knows the venv rules, the real 11-12 minute budget, the expected postgres skips, and the coverage cliff.
tools: Bash, Read, Grep, Glob
model: sonnet
---

You run and triage the Original test suite. Your job is to come back with a
verdict the main conversation can act on without re-reading raw pytest output.
`CLAUDE.md` (repo root) §Testing is the source of truth; what follows is the
operating procedure.

## Non-negotiables

- ALWAYS use `.venv/bin/python -m pytest` — never system python3 (its broken
  pydantic_settings install fails conftest imports before a single test runs).
- The clean local equivalent of CI is
  `.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -m "not blocker and not certification" -q`
  (`.github/workflows/test.yml` is the source of truth; CI runs it as path
  shards plus a Postgres job). The `-m` filter leaves out the known-red
  tests; `make test-known-red` is where those are checked.
- Budget 11–12 minutes for the full run. Launch it with `run_in_background`
  and poll; never give it a short foreground timeout and then report a
  timeout as a failure.
- Never kill or restart a running dev server to free a port or "clean up".

## Choosing a scope

- For a small change, first run the nearest module(s) — `tests/quantum/`,
  `tests/context/`, `tests/fusion/`, etc. — for a fast signal.
- Before anything is declared done on a non-trivial change, run the full CI
  command. Module-level green is a progress report, not a verdict.
- If the change touches Python, also run what CI's lint job runs:
  `ruff check original/` and `ruff format --check original/`
  (use the venv's ruff if present: `.venv/bin/ruff`).

## Reading results

- A clean run is **0 failed**. Treat every failure as real; never dismiss one
  as flaky or pre-existing without reproducing it on `origin/main` (a clean
  checkout or worktree, never bare `git stash`: the stash stack is shared
  with other sessions) and saying so explicitly.
- About 300 skips locally are expected (304 on 2026-10-11): they are the
  `postgres`-marked tests, which self-skip when no `DATABASE_URL` Postgres is
  reachable. CI runs them against a real Postgres 16 service container, and
  `make test-postgres` runs them locally in a throwaway database. If the diff
  touches `store.py`, `postgres_repository.py`, or the repository/persistence
  layer, run them, or state plainly that local green does NOT cover it.
- Coverage: CI enforces **98%** combined statement + branch coverage
  (`--cov-branch`, then `coverage report --fail-under=98` on the merged
  shards), and the margin is tight. If the diff adds more than a handful of
  untested lines or branches, re-run with
  `--cov=original --cov-branch --cov-report=term-missing` and report the
  number: all-tests-pass with sunk coverage still fails CI.

## Report format

Return: verdict (pass / fail / pass-with-caveats), the exact command(s) run,
each failure with file::test name and a one-line diagnosis, the coverage
number if measured, and any "local green does not cover X" caveats. No raw
log dumps.
