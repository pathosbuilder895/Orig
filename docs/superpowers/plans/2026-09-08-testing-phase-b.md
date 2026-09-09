# Testing Phase B — infrastructure that Phase C needs

Executes Phase B of `docs/testing/10-gap-register.md` after Phase A
(branch `claude/testing-phase-a-5add98`, PR #197). Items: T-51 fixture
consolidation, T-45 fusion runtime, T-34 OpenAPI snapshot, T-15 flag
byte-identity matrix, T-46 CI shards, T-07 boot matrix, T-14 battery
workflow repair. T-12 (a committed post-fix battery run) is **out of scope
for an agent session** — the full G-battery is 20+ CPU-hours — and is
recorded as such.

## Global Constraints (binding on every task)

- Python is `/Users/andrew/Desktop/Original/.venv/bin/python` (absolute).
  Never run the full suite; run the files you touch plus the ones the task
  names. Full-suite proof is the controller's job.
- Work in `/Users/andrew/Desktop/Original/.claude/worktrees/original-testing-strategy-5add98`
  on branch `claude/testing-phase-b-5add98`. Confirm with
  `git branch --show-current` before the first edit. Never touch
  `/Users/andrew/Desktop/Original`.
- **No production code changes under `original/`, `run.py`, `demo/`.**
  `validation/` may be edited ONLY by Task 7 and only as that task states.
- Known-red policy from Phase A stands: blocking selection is
  `-m "not blocker and not certification"`; never `xfail`; a skip must say
  `uninformative`. Do not touch any `blocker`-marked test.
- Byte-identity is the bar for anything that snapshots output: a change to
  a snapshot is a reviewed diff, produced by a named script, never by hand.
- Untracked macOS Finder duplicates exist in the worktree
  (`tests/test_persistence_error_arms 2.py`, `validation/termsim/* 2.py`).
  Do not delete them (needs the owner's permission) and do not let them
  affect your measurements — deselect with `--ignore` if they get in the
  way, and say so.
- Commit per task: `Add …`/`Refactor …`/`Fix …` subject, body with the
  measured before/after numbers where the task is about speed, trailer
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Test output must be pristine apart from the suite-wide
  `StarletteDeprecationWarning`.

---

## Task 1: T-51 — one `postgres_available` fixture

**Files:** `tests/conftest.py`, `tests/test_repository_contract.py`,
`tests/test_migration.py`, `tests/test_shadow_repository.py`,
`tests/test_cutover.py`, `tests/test_persistence_error_arms.py`.

Five files each define `_postgres_available()` / `_postgres_session_available()`
(lines: contract 52, migration 46, shadow 23, cutover 156, error_arms 293).
Add ONE session-scoped fixture `postgres_available` to `tests/conftest.py`
that returns a bool, evaluated lazily at first use (not import time — the
existing docstring at `tests/test_repository_contract.py:52-68` explains
why; keep that reasoning in the new fixture's docstring), using the same
two-stage check (`DATABASE_URL` startswith `postgresql`, then a real
connect via `original.db.postgres_session.reset_engine()` + `get_engine().connect()`
in `try/except Exception`). Preserve the error-arms variant's extra
behaviour (read its body — it also ensures the live schema exists via
`LiveBase.metadata.create_all`, the fix from the coverage effort) by
folding that into the shared fixture so every consumer gets it. Replace
the five local helpers with the fixture; keep every skip reason containing
`uninformative — no reachable Postgres` (the known-red script keys on the
word). Do not change any test's assertions.

Tests to run: the five files with `-m "not blocker"`, twice — once with
`DATABASE_URL` unset (all Postgres arms skip with `uninformative`) and once
with local Postgres (`make db-up`; `DATABASE_URL=$(bash scripts/local_postgres.sh url)`).
Report both counts.

---

## Task 2: T-45 — the fusion six under 60 s

**File:** `tests/fusion/test_wiring.py` (236 lines; six ~72–82 s tests).

Each test calls `_seed_cohort`, which POSTs the same `_LONG` text as three
baselines for each of 13 students (39 server-side extractions, ~2 s each).
Extraction of identical text is pure, so it need only happen once per
session. Preferred fix: a session-scoped fixture that computes
`original.features.pipeline.feature_vector(_LONG)` (and `extract_features`
if the route uses it) once, and a function-scoped monkeypatch on the
baseline route's extraction call (find the exact symbol the route imports —
`grep -n "feature_vector\|extract_features" original/routers/students_baseline.py`)
that returns the cached result when the text equals `_LONG` and falls
through otherwise. The score call must still go through the real API and
the real fused-score path. Alternative if the route's import shape makes
that fragile: seed states through the repository with the cached vector
and the raw text (fused score needs retained text). State which you chose.
Measure before (one test) and after (all six) with `--durations=0`.
Target: the file under 60 s total. Do not weaken any assertion; the
byte-identity assertions across the three flag states are the point of
the file.

Tests to run: `tests/fusion/` only.

---

## Task 3: T-34 — OpenAPI snapshot

**Files:** `tests/snapshots/openapi.json` (new, committed),
`tests/test_openapi_snapshot.py` (new), `scripts/update_openapi_snapshot.py` (new).

`tests/test_openapi_stability.py` proves determinism across
`PYTHONHASHSEED`; it does not catch a schema change. Add: the script dumps
`app.openapi()` with `json.dumps(sort_keys=True, indent=2)` + trailing
newline to `tests/snapshots/openapi.json` (app via `run.load_legacy_demo_app()`);
the test regenerates in-process and asserts byte-equality, with a failure
message that prints a unified diff of the first 40 differing lines and
says "intentional? run `python scripts/update_openapi_snapshot.py` and
review the diff". Add a second test that the snapshot's `info.version`
equals the app's resolved version (`_resolve_app_version` in `original/api.py`),
so the snapshot cannot silently pin a stale version string. Add a Makefile
target `openapi-snapshot`. Mention in `docs/testing/03-api-persistence.md`
§4.1 that this now exists (one sentence).

Tests to run: `tests/test_openapi_snapshot.py`, `tests/test_openapi_stability.py`.

---

## Task 4: T-15 — flag byte-identity matrix with a committed snapshot

**Files:** `tests/snapshots/score_default.json` (new, committed),
`tests/config/test_flag_byte_identity.py` (new),
`scripts/update_score_snapshot.py` (new).

Spec: `docs/testing/08-config-deploy-readiness.md` §1 (read the whole
section and its table). Build a deterministic profile: one student with 5
baseline texts and one submission text, all fixed literals (reuse
`tests/test_flag_matrix.py`'s `_mk_state` pattern and text generator if
suitable; `score()` does not read `os.environ` — drive it via
`ScoringConfig`), plus a peer pool of 4 for the `NULL_MODEL=impostor` and
`CHARACTERISTIC_WEIGHTS` arms via `build_impostor_stats`. The snapshot is
the full `Layer7Output` serialised with `sort_keys=True` under every flag
at its documented default. Tests: (a) default output equals the snapshot
byte-for-byte; (b) for each flag row in §1's table, setting it explicitly
to its off value equals the snapshot; (c) each shadow-capable flag in
`shadow` equals the snapshot on every field except the documented preview
fields, which must be present (assert the exact added-key set per flag);
(d) each `on` arm differs from the snapshot in at least one documented
field (inertness check) — EXCEPT where the flag legitimately abstains on
this profile (e.g. `CHARACTERISTIC_WEIGHTS` needs ≥ 2 baselines and a peer
pool; `TOPIC_VARIANCE_INFLATION` is a no-op below d ≤ 0.25 — if your
profile's topic distance is ≤ 0.25, the `on` arm equals off and the test
must record that as `uninformative` for that flag, not as a pass or fail);
(e) `SECRET_KEY` set does not change `deviation_score` or the action.
Flags that are wired through the API/env rather than `ScoringConfig`
(`GENRE_RESOLVER_V2`, `CONTEXT_MANIFEST_ENABLED`, `ADAPTIVE_WEIGHTS_ENABLED`,
`LLR_ACTION_MODE`, `FUSED_SCORE_*`, `AI_LIKELIHOOD_*`, `LONGITUDINAL_*`,
`STYLE_AUTHORSHIP_*`) go through `live_client` with `monkeypatch.setenv`
(follow `tests/test_flag_matrix.py`'s wiring pattern); use a second
snapshot `tests/snapshots/score_default_api.json` for the API-level
response. The update script regenerates both. Exactly which arms exist is
for you to enumerate from `original/quantum/scoring.py`'s `ScoringConfig`
and CLAUDE.md's flag table; list them in the file's docstring.

Tests to run: `tests/config/test_flag_byte_identity.py`, `tests/test_flag_matrix.py`.

---

## Task 5: T-46 — three pytest shards and a combine job

**Files:** `.github/workflows/test.yml`, `Makefile`,
`docs/testing/09-test-infrastructure-ci.md` §1.1 (update the shard table
to what you actually built).

Replace the single `pytest` job with three jobs `pytest-core`,
`pytest-api`, `pytest-rest` (all `needs: lint`, same setup steps, same
`-m "not blocker and not certification"`) and a `coverage-combine` job.
Shard by explicit path lists, not hashing:
- `core`: `tests/quantum tests/context tests/fusion tests/validation validation/test_tier10_optional.py`
- `api`: the `tests/` root files whose names match
  `test_*api*`, `test_*router*`, `test_bluebook*`, `test_pilot*`,
  `test_cutover*`, `test_repository_contract*`, `test_shadow*`,
  `test_migration*`, `test_persistence*`, `test_alembic*`, plus
  `tests/security tests/config tests/perf`
- `rest`: everything else under `tests/` — implement as `tests/` with
  `--ignore` for every path the other two shards own, so a new file is
  never silently un-run. Add a tiny script `scripts/shard_paths.py` that
  prints each shard's argument list from ONE source of truth (a dict in
  the script) and a test `tests/test_shard_partition.py` proving the
  three selections partition `pytest --collect-only` of the full blocking
  set (union == all, pairwise disjoint), run in the `rest` shard.
Only `pytest-api` gets the Postgres service. Each shard runs with
`--cov=original --cov-branch --cov-report= ` (no report) and
`COVERAGE_FILE=.coverage.<shard>`, uploads its `.coverage.*` as an
artifact, and adds `--durations=25`. `coverage-combine` downloads all
three, runs `coverage combine` then `coverage report --fail-under=98`
(and `coverage xml` + upload, keeping the existing `coverage-xml`
artifact name). Timeouts: 20 min per shard (cite the Phase A full-run
measurement: 21 min single-job local; shards should be ≤ 10 min each on
CI). Keep the `known-red` job untouched. Makefile: `test-fast` = the
`rest` shard minus `slow`, no Postgres.

You cannot run CI here: validate the YAML with `python -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml'))"`
and run `tests/test_shard_partition.py` locally (it needs only collection).

---

## Task 6: T-07 — boot matrix CI job

**Files:** `.github/workflows/boot-matrix.yml` (new), `scripts/boot_check.sh`
(new), `docs/testing/08-config-deploy-readiness.md` §2 (one paragraph:
what exists now).

Spec: `docs/testing/08-config-deploy-readiness.md` §2. Job `boot-matrix`
on every PR, `strategy.matrix.include` with the seven cells from the spec
table plus the seeding-safety cell from §8 (`ORIGINAL_ENV=pilot` WITHOUT
`--skip-seed` → refuse). Each cell: fresh venv from ONLY that cell's
lockset (`python -m venv v && v/bin/pip install -r <lockset>` plus the
spaCy model), then `scripts/boot_check.sh <expect> <today> -- <env…>`
which starts `python run.py --demo --frontend-dir demo --port 8001 --skip-seed`
(or without it for the seeding cell) in the background, polls `/health`
for 30 s, and decides. **Known-red semantics, same as Phase A:** each
cell carries `expect` (desired) and `today` (observed on this branch);
the step PASSES when the observed outcome equals `today` and FAILS when it
does not — so a cell flips red the day the product changes, and fixing
T-07 means editing `today` in the same PR. Print a `::warning::` when
`today != expect` naming the gap id (T-07 for the two Postgres cells,
T-23 for the `GUARD_DESTRUCTIVE` demo cell). For `refuse` outcomes assert
the process exited non-zero AND its log names the refusing check (grep a
short phrase per cell, e.g. `ALLOWED_ORIGINS` / `GUARD_DESTRUCTIVE` /
`seed` — read `run.py` and `original/api.py:210-234` for the exact
wording and use a stable fragment). Kill the server in `always()`.
Locally you can only smoke-test `boot_check.sh` against the dev venv for
the `sqlite up` and `ALLOWED_ORIGINS=* refuse` cells; do that and record
the output. Also add `tests/test_boot_matrix_yaml.py`: parses the
workflow, asserts every cell has `expect`, `today`, `reqs`, `env`, and
that `today != expect` only on cells whose `gap` field names a register
id that exists in `docs/testing/10-gap-register.md`.

---

## Task 7: T-14 — battery workflow that can finish

**Files:** `.github/workflows/calibration-battery.yml`,
`scripts/battery_gate.py` (new), `validation/vector_cache.py` (new, the
ONE allowed edit under `validation/` besides the two call-site edits in
`validation/calibration_gate.py` described below), `tests/validation/test_vector_cache.py`
(new), `docs/testing/06-scientific-validation.md` §7 (update to what
exists).

Spec: `docs/testing/06-scientific-validation.md` §7 items 1–4. Work in
this order and stop at the first that is infeasible, reporting why:

1. **Vector cache.** `validation/termsim/runner.py:15` already has
   `install_vector_cache(cache_dir)` keyed on `sha256(BASE_FEATURE_DIM + text)`.
   Generalise it into `validation/vector_cache.py` (`install(cache_dir)`
   wrapping `feature_vector` and `extract_features` with the same key,
   plus `pipeline_version` = a hash of `original/features/*.py` contents so
   a pipeline change invalidates the cache; JSON/npz files under
   `.benchmark_cache/gates/`), make termsim's runner call it (no behaviour
   change — its own test suite `tests/validation/test_termsim*.py` must stay
   green), and install it at the top of `validation/calibration_gate.py`'s
   `run_all()` (or its CLI `main`) guarded by `--vector-cache DIR`
   (default off, so `--strict` output is unchanged without the flag). The
   two direct extraction sites (`calibration_gate.py:1987` and `:3279`) and
   any baseline-building path through `StudentState` (`:3611` — check how
   samples get their vectors) must all go through the wrapped functions.
   Test: with the cache installed, a text's cached vector is byte-identical
   to a fresh `feature_vector(text)`; a changed `pipeline_version` misses.
2. **Per-gate matrix.** Rewrite the workflow as `strategy.matrix.gate:
   [G1, G2, G2b, G3, G4, G5, G6, G7, G8, T-1, T-2, T-3, T-4]` — check
   `python -m validation.calibration_gate --help` for a per-gate selector;
   if none exists, add `--only GATE` to its CLI (this is the third allowed
   `validation/calibration_gate.py` edit; keep it tiny). Each cell restores
   `.benchmark_cache/gates` via `actions/cache` (key on the pipeline
   version), runs `--strict --only <gate> --vector-cache .benchmark_cache/gates --out report-<gate>.json`
   with `timeout-minutes: 60`, uploads its JSON. A `combine` job downloads
   all, merges into `calibration-report.json`, uploads it.
3. **Fail on ERROR.** `scripts/battery_gate.py` reads the merged report,
   exits 1 if any verdict is `ERROR` (machinery), 0 otherwise, printing a
   table. Drop `continue-on-error`. Science `fail` stays non-blocking by
   virtue of the schedule-only trigger.
4. **Record runtime.** Each gate cell writes `wall_seconds` into its JSON
   (a wrapper in the cell's run step is fine); `battery_gate.py` also
   warns when any gate's wall time exceeds half its cap.

You cannot run the battery here (20+ CPU-hours uncached). Prove the cache
with its unit test, prove the CLI flag with `--help` and a `--only G2`
run if G2 completes in under 10 minutes locally (measure; if not, say
so), validate the YAML, and run `tests/validation/test_termsim*.py`,
`tests/test_calibration_gate.py`, `tests/test_gate_falsifiability.py`.

---

## Task 8: Register and ledger update (controller)

Update `docs/testing/10-gap-register.md` states for T-51, T-45, T-34,
T-15, T-46, T-07 (boot half), T-14, with measurements; note T-12 as
"needs a 20+ CPU-hour manual run — not an agent task"; append the Phase B
outcome paragraph.
