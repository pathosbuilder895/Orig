# 08 — Configuration, flags, and deploy-readiness tests

Scope: the ~50 environment flags in CLAUDE.md, `run.py` boot, the three
requirements sets (`requirements.txt`, `requirements-pilot.txt` lockset,
`requirements-demo.txt`), `render.yaml` / `start.sh`, `scripts/pilot_preflight.py`,
`scripts/o1_golive_check.py`, `scripts/pilot_smoke_test.py`, `/health`,
backup and restore.

Strong today: `test_flag_matrix.py` (four flags, real wiring), byte-identity
tests for fused/AI/blend shadow modes, `test_pilot_lockdown.py`,
`test_pilot_preflight.py`, `test_o1_golive_check.py` with an injectable `get`,
backup scheduler and off-box restore-drill tests.

Blind today: every test runs in a venv that has every dependency; the pilot
lockset does not, and `REPO_BACKEND=postgres` bricks boot there. No test
proves byte-identity for most default-off flags together. `render.yaml`
and `pilot_preflight` can disagree. The restore drill is a weekly human
action.

---

## 1. Flag byte-identity matrix

Principle 4 in the README: with a flag off, output is bit-for-bit what it was
before the flag existed. Today this is proved flag-by-flag in scattered files.
Make it one matrix, `tests/config/test_flag_byte_identity.py`:

- **Reference vector.** Score a fixed synthetic profile + submission with
  *every* score-affecting flag at its documented default; serialise the full
  response with `sort_keys=True`; commit it as
  `tests/snapshots/score_default.json`. A change to the default output is a
  reviewed diff (same policy as the OpenAPI snapshot, §03 §4).
- **One-flag-off arms.** For each flag in the table below, set it explicitly
  to its off value and assert the response equals the snapshot. This catches
  "off" that is not actually off (a parsing bug, `"0"` vs `""`).
- **Shadow arms.** For each shadow-capable flag, `shadow` must equal the
  snapshot on every field *except* the documented preview/diagnostic fields,
  which must be present.
- **On arms, existence only.** `on` must differ from the snapshot in at least
  one documented field, or the flag is inert — the trap
  `GENRE_INVARIANT_WEIGHTS_ENABLED` fell into.

| Flag | Off | Shadow | On changes |
|---|---|---|---|
| `CONTEXT_MANIFEST_ENABLED` | `0` | — | manifest fields |
| `ADAPTIVE_WEIGHTS_ENABLED` | `0` | — | `deviation_score` |
| `GENRE_INVARIANT_WEIGHTS_ENABLED` | `0` | — | `deviation_score` on confident mismatch only |
| `GENRE_RESOLVER_V2` | `off` | `shadow` | genre label → tier-16 mute, anchors, prior key |
| `AMPLITUDE_SCORING_ENABLED` | `0` | — | `quantum_fidelity` |
| `BAYESIAN_PRIOR_ENABLED` (+`COHORT_PRIOR_FALLBACK`) | `0` | — | cold-start `deviation_score` |
| `NULL_MODEL` / `LLR_ACTION_MODE` | `none` / — | `shadow` | `llr_deviation_score`, one-step action |
| `LENGTH_ADAPTIVE_WEIGHTS` | `0` | — | `deviation_score` |
| `TOPIC_VARIANCE_INFLATION` | `off` | `shadow` | `deviation_score` when d > 0.25 |
| `CHARACTERISTIC_WEIGHTS` | `off` | `shadow` | `deviation_score` when peers ≥ floors |
| `RANK_REMEDIATION` | unset | — | density estimator |
| `AI_LIKELIHOOD_ENABLED` / `_SHADOW` | `0` | `_SHADOW=1` | `ai_probability` |
| `FUSED_SCORE_ENABLED` / `_SHADOW` | `0` | `_SHADOW=1` | `fused_score` |
| `LONGITUDINAL_DRIFT_ENABLED` | `0` | — | report fields only |
| `STYLE_AUTHORSHIP_ENABLED` | `0` | — | report fields only |
| `SECRET_KEY` | `""` | — | amplitude path only, never `deviation_score` |

The last row encodes a finding from TermSim: `SECRET_KEY` does not touch
`deviation_score`. Pin it, because the docs imply otherwise.

`score()` does not read `os.environ`; drive these through `ScoringConfig` for
the unit arm *and* through `live_client` with `monkeypatch.setenv` for the
wiring arm. `test_flag_matrix.py` already shows the second pattern.

## 2. Lockset boot matrix (the bricked-boot bug)

`requirements-pilot.txt` (15 lines) lacks `sqlalchemy`, `psycopg2-binary`,
and `alembic`. `REPO_BACKEND=postgres` on that install raises an
`ImportError` that `api.py:159` (which catches `NotImplementedError` only)
does not handle. No test installs the lockset.

Add a CI job `boot-matrix` (≈ 2 min):

```yaml
strategy:
  matrix:
    include:
      - {reqs: requirements-pilot.lock.txt, env: "ORIGINAL_ENV=pilot REPO_BACKEND=sqlite",   expect: up}
      - {reqs: requirements-pilot.lock.txt, env: "ORIGINAL_ENV=pilot REPO_BACKEND=postgres", expect: up}   # red today
      - {reqs: requirements-pilot.lock.txt, env: "ORIGINAL_ENV=pilot REPO_SHADOW=postgres",  expect: up}   # red today
      - {reqs: requirements-demo.lock.txt,  env: "",                                          expect: up}
      - {reqs: requirements-pilot.lock.txt, env: "ORIGINAL_ENV=pilot ALLOWED_ORIGINS=*",      expect: refuse}
      - {reqs: requirements-pilot.lock.txt, env: "ORIGINAL_ENV=pilot GUARD_DESTRUCTIVE=1",    expect: up}
      - {reqs: requirements-pilot.lock.txt, env: "ORIGINAL_ENV=demo  GUARD_DESTRUCTIVE=1",    expect: refuse}  # REAUDIT #5, red
```

Each cell: fresh venv from *that* lockset only, `python run.py --demo
--skip-seed --port 8001 &`, poll `/health` 30 s, assert `expect`. For
`expect: refuse`, assert the process exits non-zero *and* the log names the
refusing check. This is the only test in the repo that runs the product the
way Render runs it.

Also a unit-level twin: `tests/config/test_lockset_imports.py` parses
`requirements-pilot.lock.txt`, builds the set of top-level importable names,
and asserts every module `run.load_legacy_demo_app()` imports under
`REPO_BACKEND=postgres` is covered. Faster than the matrix; catches the next
missing dependency at PR time.

**What exists now.** `.github/workflows/boot-matrix.yml` runs the eight cells
above (the seven from the table plus §8's seeding-safety cell) on every PR and
every push to `main`, one job each, `fail-fast: false`. A cell builds a venv
from *only* its lockset (`python -m venv v && v/bin/pip install -r <lockset>`
plus the spaCy model — nothing installs `requirements.txt`, which would defeat
the point), then calls `scripts/boot_check.sh <expect> <today> [gap]
[--log-fragment TEXT] -- <KEY=VAL…> [--no-skip-seed]`. The script starts
`python run.py --demo --frontend-dir demo --port 8001 --skip-seed` in the
background, polls `/health` for 30 s, kills the server from an `EXIT` trap, and
classifies the run as `up` (200), `refuse` (exited non-zero **and** the log
contains the cell's fragment) or `down` (anything else). Each cell points
`ORIGINAL_DB` at a scratch file, so the seeding cell meets a genuinely empty
store rather than whatever `profiles.db` the checkout carries.

The cells carry Phase A's known-red semantics: `expect` is the outcome a fixed
product would give, `today` is the outcome observed on this branch, and the
step **passes when observed == `today`** — failing in either direction, so the
matrix flips red the day boot behaviour changes rather than the day someone
remembers to look. Where `today != expect` the script emits a `::warning::`
naming the gap-register row, and fixing the gap means editing `today` in the
same PR. `tests/test_boot_matrix_yaml.py` closes the obvious escape hatch:
`today` may only differ from `expect` on a cell whose `gap` field names a row
that actually exists in `10-gap-register.md`, so a red cell cannot be quieted
by re-baselining it. Observed on 2026-09-08: `pilot-sqlite`,
`pilot-guard-destructive` and `demo-lockset-default` **up**;
`pilot-origins-wildcard` and `pilot-no-skip-seed` **refuse**; `demo-guard-destructive` **up** where it
should refuse (T-23); and both Postgres cells **down** — note *down*, not
*refuse*: the process exits 3 on an unhandled `ModuleNotFoundError:
sqlalchemy` raised inside the `api.py` lifespan, which is precisely the
unhandled-import shape T-07 names.

## 3. Requirements drift

- Every package in `requirements-pilot.txt` is in `requirements.txt` at the
  same pin (`test_requirements_consistency.py`). A pilot-only version is a
  deploy surprise.
- Lockfiles regenerate to byte-identity (`pip-compile` in CI, `git diff
  --exit-code`) — the same gate `bundle-e2e` applies to the JS bundle.
- `.env.example` names every flag in CLAUDE.md's table and no flag that does
  not exist in the code (`grep -r` of `os.environ` / `getenv` under
  `original/` + `run.py`). The termsim branch's `.env.example` rewrite dropped
  four `DB_POOL_*` vars this test would have caught.

## 4. Deploy descriptor vs preflight

`scripts/pilot_preflight.py` requires a set of env vars; `render.yaml`
declares a set. Parse both, assert preflight's required set ⊆ render's
declared set (values may be secrets; only names are compared). Add the
worker-count assertion from `07-performance-reliability.md` §4 here too.

Answer the open question from the audit in a test: *who provisions the pilot
Postgres schema?* If it is `init_live_schema()` (`create_all`), assert
`start.sh` calls it and that `alembic` is not required; if it is Alembic,
assert `start.sh` runs `upgrade head` and the lockset contains `alembic`.
Either answer is fine. Not knowing is not.

## 5. `/health` as a contract

`/health` is polled by CI, UptimeRobot, `o1_golive_check`, and the smoke
test. Pin its shape with a schema test: required keys
`status, feature_dim, students_in_store, environment, commit, backend`;
`feature_dim == FEATURE_DIM`; `commit` is a 7–40 char hex string or the
documented `unknown`; no other keys unless added to the schema in the same PR.
Assert it is served in < 50 ms with no DB round trip beyond the count.

## 6. Backup and restore

- Scheduler: already tested (consistency, pruning, age). Keep.
- Off-box: already tested with an in-memory S3. Keep.
- **Restore drill automation.** `docs/OPS_RUNBOOK.md` makes it a weekly
  human hour. Add it to the weekly workflow: pull the newest backup from the
  fake S3 (or a CI-seeded one), run `restore_drill --verify`, boot the app on
  the restored file, assert `/health.students_in_store` matches the backup
  manifest count. The human drill continues against real S3; the automated
  one proves the *procedure* still works.

## 7. Container smoke

`scripts/docker-smoke-test.sh` and `Dockerfile.demo` exist and are in no
workflow. Add a 3-minute job: build the demo image, run it, poll `/health`,
run `smoke.spec.mjs` against it. Catches the class of bug where the venv
works and the image does not (system packages, spaCy model download, file
permissions on `/data`).

## 8. Seeding safety

`--skip-seed` is mandatory under `ORIGINAL_ENV=pilot` and the seeder "hard-
refuses". Assert it: boot with `ORIGINAL_ENV=pilot` *without* `--skip-seed`;
the process must exit non-zero before writing a row. Belongs in the boot
matrix as an `expect: refuse` cell.

## 9. Acceptance for this slice

- `tests/snapshots/score_default.json` committed; the byte-identity matrix
  covers every row in §1's table.
- `boot-matrix` CI job exists; the two Postgres-on-lockset cells are red with
  register entries.
- Requirements-consistency, `.env.example`, and preflight-vs-render tests
  pass.
- The schema-provisioning question has a test that encodes the answer.
- Container smoke job green.
