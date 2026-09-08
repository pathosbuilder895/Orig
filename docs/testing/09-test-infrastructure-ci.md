# 09 — Test infrastructure, speed, and CI shape

Scope: `tests/conftest.py`, markers, fixtures, `pytest.ini`,
`.github/workflows/*.yml`, `scripts/changed_tests.py`, `Makefile`, timing,
flake policy, and ownership.

The single serial `pytest` job measured 15–18 minutes on shared runners with
a 30-minute cap that has already been hit once. The CI file's own comment
says the next multi-minute test should trigger a split. This document is that
split, plus the fixture and marker changes the other documents assume.

---

## 1. Speed

### 1.1 Shard the pytest job

**Shipped 2026-09-08 (T-46).** Three shards by *path*, not by `pytest-xdist`
hashing — path shards are reproducible and let a failure be re-run locally
with the same command. Membership is defined ONCE, in
`scripts/shard_paths.py`'s `SHARDS` dict; the three workflow jobs and the
Makefile targets both ask that script for a shard's pytest arguments.

| Shard | Job | Selection | Collected | Postgres |
|---|---|---|---|---|
| `core` | `pytest-core` | `tests/quantum tests/context tests/fusion tests/validation validation/test_tier10_optional.py` | 1012 | no |
| `api` | `pytest-api` | `tests/` root files matching `test_*api*.py`, `test_*router*.py`, `test_bluebook*.py`, `test_pilot*.py`, `test_cutover*.py`, `test_repository_contract*.py`, `test_shadow*.py`, `test_migration*.py`, `test_persistence*.py`, `test_alembic*.py` (no matches yet), plus `tests/security tests/config tests/perf` | 1061 | **yes** |
| `rest` | `pytest-rest` | `tests/` **minus** `--ignore` for every path the other two shards own | 1531 | no |

Collected counts are `-m "not blocker and not certification"` as of the split;
union 3604 == the full blocking set's 3604. Estimated wall: `core` ~7 min (the
fusion six dominate — §1.2), `api` ~6 min, `rest` ~5 min, against a 20-minute
cap each. The serial job this replaced measured 15–21 min with a 30-minute cap
it had already hit once.

Two properties are load-bearing, and `tests/test_shard_partition.py` (itself
in the `rest` shard) pins both by running `pytest --collect-only` four times
and comparing nodeid sets:

- **Nothing is un-run.** `rest` is subtractive — `tests/` with `--ignore` for
  the other shards' paths — so a new file added to `tests/` root is collected
  by `rest` by default. Under an explicit-list `rest`, forgetting to add a new
  file means no shard collects it and CI stays green on a test nobody runs.
- **Nothing runs twice.** The three selections are pairwise disjoint. The
  `api` globs are expanded at run time, so a new `tests/test_bluebook_x.py`
  moves from `rest` to `api` automatically rather than being collected by both.

Coverage: each shard runs `--cov=original --cov-branch --cov-report=` (no
report) with a distinct `COVERAGE_FILE=.coverage.<shard>` and uploads that
data file as `coverage-data-<shard>`. A fourth `coverage-combine` job
downloads all three and runs `coverage combine && coverage report
--fail-under=98 && coverage xml`, re-uploading the unchanged `coverage-xml`
artifact name. **`--cov-fail-under` is set on no shard** — one shard's
coverage of `original/` is meaningless; the ≥98 floor is enforced exactly once,
on the combined number. All three shards run from the repo root on the same
runner image, so the recorded source paths already match and `coverage
combine` needs no `[paths]` remapping.

Only the `api` shard gets the Postgres service (it owns
`tests/test_repository_contract.py`, which parametrizes over a `postgres`
backend). The other two drop it and start faster.

Local equivalents: `make test-shard-core|test-shard-api|test-shard-rest`, and
`make test-fast` = the `rest` shard minus `slow` (§8). The script's output is
shell-quoted, so callers `eval` it — the only paths containing spaces are the
gitignored macOS Finder duplicates (`test_tier1 2.py`), which the script
deselects with `--ignore` and which do not exist on a CI checkout.

### 1.2 The fusion six

`tests/fusion/test_wiring.py` — six cases at 72–82 s each, ~8 minutes of one
job. Each boots the full app and scores through the pipeline with 8 peers.
Fix, in order of payoff:

1. Session-scope the peer-profile construction (the eight peer states are
   identical across the six tests; build once, copy the SQLite file per test).
2. Pre-extract feature vectors for the fixture texts into a committed `.npy`
   under `tests/fixtures/fusion/` with a test that regenerating them is
   byte-identical (the determinism suite's pattern). Extraction is the cost;
   scoring is milliseconds.
3. Mark the three "shadow persists a row" cases `slow` and run only the
   byte-identity three per PR.

Target: the file under 60 s total.

### 1.3 Subprocess determinism tests

`test_feature_pipeline_determinism.py` and `test_openapi_stability.py` each
spawn six interpreters. Run the six seeds in a `ProcessPoolExecutor`; wall
drops from ~40 s to ~10 s each with no loss of meaning.

### 1.4 spaCy

Six files load `en_core_web_sm`. A session-scoped `nlp` fixture in
`conftest.py`, and `tension_arc._nlp` set from it, avoids five reloads.

### 1.5 Measure, then keep measuring

Add `--durations=25` to every shard and post the top 25 into the job summary.
Commit nothing; the summary is the record. A test crossing 30 s gets a
register entry.

## 2. Fixtures and conftest

`tests/conftest.py` is 66 lines with three fixtures and 1,427 raw
`monkeypatch` references across the suite. Consolidate the patterns the other
documents rely on:

| Fixture | Scope | Replaces |
|---|---|---|
| `postgres_available` | session | the five copies of `_postgres_available()`; still evaluated lazily at first use |
| `pilot_env` | function | the recurring `monkeypatch.setattr(api, "_IS_REAL_DEPLOY", True)` + `ORIGINAL_ENV=pilot` pair |
| `principal_headers(role, tenant)` | factory | hand-built tokens in ~20 files |
| `seeded_tenant(n_students, n_baselines)` | function | the per-file student provisioning loops |
| `canvas_transport` | function | the `httpx.MockTransport` builder from `test_canvas_live.py`, so §04 and §07 can reuse it |
| `nlp` | session | six spaCy loads |
| `score_snapshot` | session | loads `tests/snapshots/score_default.json` for §08 §1 |

Rule: a helper used in three or more files moves to conftest. A helper used
in one file stays local.

## 3. Markers

`pytest.ini` today: `slow`, `postgres`. Add:

| Marker | Meaning | Where it runs |
|---|---|---|
| `certification` | three-valued behavioural gate (§06 §3, §02 §2.1); writes a verdict to `certification-report.json`, written locally by the certification tests — not yet uploaded by CI | every PR, and the weekly battery; the whole group runs inside the `known-red` job rather than the blocking `pytest` run (which deselects it with `-m "not blocker and not certification"`) — witnesses as a must-pass step, `blocker`-marked certifications via `scripts/known_red.py` |
| `security` | abuse-case suite (§04) | every PR; also `pytest -m security` before go-live |
| `perf` | latency/concurrency budgets (§07) | every PR, `uninformative`-aware |
| `boot` | tests that spawn the server as a subprocess (§08 §2, §8) | `boot-matrix` job only |
| `blocker` | a test that fails on this branch because of a documented open gap, its docstring's first line naming the gap id (e.g. `T-02: pending baseline requests leak cross-tenant.`); never use `xfail`, `skip`, or a weakened assertion to make a red test green, and a test that is green on this branch is NOT marked `blocker` | excluded from the blocking `pytest` run via `-m "not blocker and not certification"`; run separately by the `known-red` job (`scripts/known_red.py`), which fails the day one of these tests unexpectedly passes, or is skipped without `uninformative` in its skip reason (a sample-size floor is the only legitimate skip) |
| `mutation_target` | *not a selector* — documents which modules the weekly mutation run covers; a test asserts the list matches the workflow |

`--strict-markers` on, so a typo cannot create a silently-unselected marker.

## 4. Flake policy

The suite has zero retries, zero `flaky`, and zero `xfail` today. Keep it that
way:

- No `pytest-rerunfailures`. A flaky test is quarantined by moving it to
  `tests/quarantine/` (collected, run weekly, excluded from the PR shards)
  with an issue link in its docstring. Two weeks in quarantine without a fix
  and it is deleted.
- `xfail` is banned by a test: `tests/test_no_xfail.py` greps for the
  decorator. A known-red certification test is *red*, and the register says
  so. (The OPS runbook mentions "5 xfail'd `TestAuthEndpoints`" — those were
  the dormant v1 suite, deleted; the runbook line is stale.)
- Time budgets in `perf` follow §07 §9.
- Playwright keeps `retries: 1` in CI only, and `--retries=0` for the lockout
  spec. A spec that retries more than twice a week is quarantined the same
  way.

## 5. CI shape after this plan

```
lint ─┬─ pytest-core ────┐
      ├─ pytest-api ─────┼─ coverage-combine (≥98)
      ├─ pytest-rest ────┘
      ├─ certification (fast; fails on `fail`, reports `uninformative`)
      ├─ boot-matrix
      ├─ app (vite)
      ├─ bundle-e2e (bluebook + demo/app if live)
      ├─ container-smoke
      └─ security (pip-audit, gitleaks, npm audit)

weekly (extend the existing calibration-battery.yml; see 06 §7 for why it cannot finish today):
        certification ▸ per-gate battery matrix --strict ▸ TermSim ▸ mutation ▸ load_smoke ▸ restore drill ▸ serial-lockout ▸ visual regression
```

Per-PR critical path target: ≤ 10 minutes. Weekly: ≤ 60 minutes, non-blocking
except that the certification step's `fail` is a blocker once it has been
green on `main`.

## 6. `changed_tests.py`

Its blind spot — tests that reach a module only via `live_client` — grows as
§04/§07 add HTTP-driven tests. Two cheap improvements:

- Map `original/routers/<name>.py` → `tests/**/test_*<name>*.py` *and*
  `tests/security/`, `tests/perf/` (always run both packages on any router
  change; they are fast).
- Map `original/constants.py` → the certification package (any threshold
  change must re-run cold-start FPR).

Pin both in `tests/test_changed_tests_mapping.py`, which already exists for
this purpose.

## 7. Ownership and cadence

| Area | Owner file | Cadence |
|---|---|---|
| Certification + battery reports | `06-scientific-validation.md` | weekly review, Monday |
| Security suite | `04-security-adversarial.md` | every PR; full `-m security` before each pilot deploy |
| Perf budgets + load trend | `07-performance-reliability.md` | weekly; budgets reviewed quarterly |
| Flag matrix + boot matrix | `08-config-deploy-readiness.md` | every PR; re-baseline snapshot on any deliberate scoring change |
| Mutation score | `02-unit-property-math.md` | weekly; module list reviewed when a new score-driving module lands |
| Gap register | `10-gap-register.md` | updated in the PR that closes or opens a gap |

CLAUDE.md's "Testing" section should shrink to the run commands and a link
to `docs/testing/00-README.md`; the counts and timings it carries today go
stale monthly and this set replaces them.

## 8. Local developer loop

- `make test-fast`: the `rest` shard minus `slow`, ~2 min, no Postgres.
- `make test-security`: `pytest -m security`, < 1 min.
- `make test-cert`: `pytest -m certification`, < 1 min, prints verdicts.
- `make test`: unchanged, the full CI command.

Document in `CONTRIBUTING.md` that the pre-push hook runs `changed_tests`,
and that `SKIP=changed-tests` is for emergencies only.

## 9. Acceptance for this slice

- Three pytest shards + combine job; per-PR critical path ≤ 10 min measured
  over five runs.
- `tests/fusion/test_wiring.py` under 60 s.
- Five `_postgres_available` copies replaced by one fixture.
- New markers registered with `--strict-markers`.
- `tests/test_no_xfail.py` exists.
- CLAUDE.md testing section trimmed and linking here.
