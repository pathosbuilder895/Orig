# Testing Phase A — make the P0 blockers visible as red tests

Executes Phase A of `docs/testing/10-gap-register.md`. Every task writes
tests; **no task changes production code under `original/`**. A test that is
red on this branch is the deliverable, not a problem.

## Global Constraints (binding on every task)

- Python is `/Users/andrew/Desktop/Original/.venv/bin/python` (absolute; the
  worktree has no `.venv`). Never run the full suite — run the files you
  touch plus the ones named in the task. Full-suite is the controller's job.
- Work in `/Users/andrew/Desktop/Original/.claude/worktrees/original-testing-strategy-5add98`
  on branch `claude/testing-phase-a-5add98`. Confirm with `git branch --show-current`
  before the first edit.
- **Do not modify any file under `original/`, `run.py`, `demo/`, or
  `validation/` except where a task names one explicitly.** Phase A is
  tests only. If a test needs a seam that does not exist, report
  DONE_WITH_CONCERNS naming the seam; do not add it.
- **Known-red policy.** A test that fails on this branch because of a
  documented open gap is marked `@pytest.mark.blocker` and its docstring's
  first line names the gap id, e.g. `T-02: pending baseline requests leak
  cross-tenant.` Blocker tests are excluded from the blocking CI run by
  `-m "not blocker"` and run by the `known-red` job. **Never use `xfail`,
  `skip`, or a weakened assertion to make a red test green.** A test that
  is green on this branch is NOT marked `blocker`.
- Every test must be able to fail: where a task asks for a "witness", it is
  a second test proving the harness would detect the failure it guards.
- Markers used: `certification`, `security`, `perf`, `boot`, `blocker`
  (registered by Task 1; exact spellings).
- Three-valued honesty: a sample-size floor produces a recorded
  `uninformative` and a `pytest.skip` with that word in the reason, never a
  pass.
- Follow the existing style: `live_client` + `store_reset` fixtures from
  `tests/conftest.py`; principals via
  `original.principal.mint_principal_token(sub, role, tenant_id)` and a
  `{"Authorization": f"Bearer {token}"}` header (see
  `tests/test_tenant_isolation.py:39` `_auth`). Pilot mode is simulated the
  way `tests/test_pilot_lockdown.py` does it — read that file's setup before
  writing your own.
- Commit per task: `Add …` subject, body says which gap id and whether the
  test is red or green on this branch, trailer
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Test output must be pristine (no warnings from your own code).

---

## Task 1: Markers, shared fixtures, and the known-red CI lane

**Files:** `pytest.ini`, `tests/conftest.py`, `.github/workflows/test.yml`,
`scripts/known_red.py` (new), `tests/test_known_red_policy.py` (new),
`Makefile`.

1. `pytest.ini`: register markers `certification`, `security`, `perf`,
   `boot`, `blocker` with one-line descriptions. Add `addopts = --strict-markers`.
   Run `pytest --collect-only -q tests/ validation/test_tier10_optional.py`
   and confirm collection still succeeds (an unregistered marker anywhere
   will now error — fix by registering it, not by removing `--strict-markers`).
2. `tests/conftest.py`: add two fixtures.
   - `pilot_env(monkeypatch)`: puts the loaded live app into real-deploy
     mode exactly the way `tests/test_pilot_lockdown.py` does (read its
     fixture; reuse the same attribute/env names; do not invent new ones).
     Yields nothing; restores on teardown via monkeypatch.
   - `principal_headers()`: a factory fixture returning
     `make(sub: str, role: str, tenant_id: str) -> dict` that mints a token
     with `original.principal.mint_principal_token` and returns the
     `Authorization: Bearer` header dict.
   Do not migrate existing tests to them.
3. `.github/workflows/test.yml`:
   - In the `pytest` job's run step, add `-m "not blocker"` to the
     `python -m pytest …` command. Nothing else in that step changes.
   - Add a job `known-red` (runs-on ubuntu-latest, `needs: lint`,
     timeout 20, **no** Postgres service, same Python/pip/spaCy setup steps
     as `pytest`) whose single test step runs
     `python scripts/known_red.py`. The job is blocking; the script's exit
     code is the policy (below).
4. `scripts/known_red.py`: runs
   `python -m pytest tests/ -m blocker -q --junitxml=<tmp> -p no:cacheprovider`
   via `subprocess`, parses the junit XML, prints a table
   `gap-id | test id | outcome` (gap id parsed from the test docstring's
   first token matching `T-\d+`; use `--collect-only` output or the junit
   `name`/`classname` plus a second pass reading the source — pick the
   simplest that works), and exits:
   - `0` if every blocker test failed or errored (the expected state),
   - `1` if any blocker test **passed** — message: "these gaps appear closed;
     remove `@pytest.mark.blocker` and move the register row to green",
   - `0` with a notice if zero blocker tests were collected.
   Keep it under ~120 lines, stdlib only.
5. `tests/test_known_red_policy.py`: unit-tests the script's decision
   function on hand-built junit XML strings (all-fail → 0, one pass → 1,
   none → 0), and a collection-driven test that every test carrying the
   `blocker` marker has a docstring whose first line contains `T-\d+`
   (use `pytest`'s collection API or a `conftest` hook — the simplest is
   `subprocess` `--collect-only -q -m blocker` plus `inspect` on the
   imported module; either is fine).
6. `Makefile`: targets `test-security` (`-m security`), `test-cert`
   (`-m certification`), `test-known-red` (`python scripts/known_red.py`).
7. `docs/testing/09-test-infrastructure-ci.md` §3 marker table: add a
   `blocker` row with the policy sentence from Global Constraints.

Tests to run: `tests/test_known_red_policy.py`, `tests/test_changed_tests_mapping.py`,
and the collect-only command from step 1.

---

## Task 2: T-01 cold-start FPR certification test (expected red)

**Files:** `tests/certification/__init__.py`, `tests/certification/conftest.py`,
`tests/certification/test_cold_start_fpr.py`.

Spec: `docs/testing/06-scientific-validation.md` §3 — read it first; it is
the requirement. Concretely:

- **Corpus fixture** `corpus_authors` (session scope, in the package
  conftest): from `validation/public_authors/manifest.json` (`entries` with
  `author_id`, `filename`, `is_baseline`) and the files under
  `validation/public_authors/corpus/`. Use
  `validation.termsim.personas.chunk_text(text)` (defaults: min 300 /
  target 900 / max 1500 words) to chunk each document. For each author,
  baselines are chunks drawn from **one work** (the first baseline file),
  and the holdout is the first chunk of a **different** work by the same
  author; authors with only one work are excluded. Return a list of
  `Author(author_id, baseline_chunks: list[str], holdout: str)`.
- **Provisioning** through the API, not `score()`: for each author and each
  N, `POST /students/{sid}/baseline` N times with one chunk each (read the
  handler in `original/routers/students_baseline.py:48` for the body shape
  and provenance field), then `POST /students/{sid}/score` with
  `{"text": holdout, "assignment": "cert"}` and read `recommendation`.
  Use `live_client` + `store_reset`; demo environment (no pilot fixture);
  student ids `cert-<author>-<N>`. If the baseline handler holds a
  submission for drift (HTTP 202/409 — TermSim's runner hit this), count it
  and report; do not silently treat it as a score.
- **The test** `test_same_author_action_at_pilot_baseline_counts`,
  parametrised over `n_baselines in (3, 5, 10)`, marked `certification`
  and `blocker`, docstring first line `T-01: same-author action at pilot
  baseline counts.` Flag = `recommendation in {"schedule_conversation",
  "escalate"}`. Bar: flagged rate ≤ 0.10. Fewer than 8 usable authors →
  record `uninformative` and `pytest.skip("uninformative — …")`.
- **Reporting** helper `record_verdict(name, verdict, value, n, **extra)`
  appends to a JSON list at `CERT_REPORT_PATH` (env; default
  `certification-report.json` in the repo root; gitignore it) with fields
  `name, verdict, value, n, params, timestamp`.
- **Witness** `test_harness_flags_a_different_author` (plain, must be
  green): same harness at N=5 but each author's holdout is swapped with
  the *next* author's; assert flagged rate ≥ 0.5. This proves the
  certification cannot pass by construction.
- Runtime target: under 90 s for all four tests together on the committed
  corpus. If feature extraction dominates, cache chunk vectors in the
  session fixture — but the score must still go through the API.

Report the measured flagged rate per N in the report file; that number is
the finding. Tests to run: the new package only.

---

## Task 3: T-02 and T-06 — cross-tenant reads and the static tree

**Files:** `tests/security/__init__.py`, `tests/security/conftest.py`,
`tests/security/test_cross_tenant_read.py`, `tests/security/test_static_tree.py`.

Spec: `docs/testing/04-security-adversarial.md` §1.1 and §1.5. All tests
marked `security`.

`tests/security/conftest.py`: a `two_tenants` fixture that, under
`pilot_env`, provisions tenants `A` and `B` (`POST /tenants` — read
`original/routers/tenants.py:20` for the body; an operator principal may be
needed to create tenants) and returns staff headers for each via
`principal_headers`, plus one student id in each tenant with one baseline
sample. Keep it small; later tasks reuse it.

`test_cross_tenant_read.py` — the six rows of §1.1 as six tests. For the
pending-requests row: create a baseline request in tenant A via the
public route that creates one (`grep -n "baseline-requests\|request-baseline"
original/routers/students_baseline.py`), then `GET /baseline-requests/pending`
as B staff and assert (a) zero rows whose student belongs to A, (b) the
response text contains neither A's student email nor any token/link string
from A's request. Note `original/routers/students_baseline.py:309` takes no
`request` argument and calls `baseline_requests.list_pending()` unscoped —
this is the hole; expect red, mark `blocker`, docstring `T-02: …`.

`test_static_tree.py` — build the forbidden list from
`git ls-files` plus a filesystem glob for `*.db`, `*.sqlite*`, `.env*`
under the repo (exclude `tests/` fixtures). Under `pilot_env`, with the
demo frontend mounted (`run.create_demo_app(Path("demo"))` — check how
`tests/test_pilot_lockdown.py` gets a static-mounted app, and reuse), every
forbidden path returns 404. Second test: under demo env, `/seed.db` is
served (documents the policy). Also assert `/bluebook/bluebook.bundle.js.map`
is 404 under pilot. `original/api.py:313` already gates an explicit list —
the test is red only for paths that list misses; mark per-parametrised
case, not the whole test, if only some are red (use `pytest.param(...,
marks=pytest.mark.blocker)`).

Tests to run: `tests/security/`, `tests/test_pilot_lockdown.py`.

---

## Task 4: T-03 and T-04 — anonymous writes and flat-id minting

**Files:** `tests/security/test_unauthenticated_writes.py`,
`tests/security/test_id_minting.py`.

Spec: §1.2 and §1.3 of `docs/testing/04-security-adversarial.md`.

`test_unauthenticated_writes.py`: iterate `live_app.routes`; for every route
with a method in `{POST, PUT, PATCH, DELETE}` that is not in
`ANONYMOUS_ALLOWLIST` (a dict `path → reason`; seed it with `/auth/login`,
`/student-auth/login`, `/lti/login`, `/lti/launch`, `/auth/register` if the
code allows anonymous register — verify, and `/proctor/park/beat` if it is
attestation-authenticated rather than principal-authenticated — verify),
send a minimal syntactically valid body (empty JSON object, or an empty
multipart file for `UploadFile` routes; substitute `x` for every path
parameter) with **no** Authorization header under `pilot_env`, and assert
status in `{401, 403}`. Collect all failures and assert the failure list is
empty with the list in the message. `POST /bluebook/submissions` is a
documented hole; if the whole test is red because of it, split: one
parametrised test per route (so only the red routes carry `blocker`), plus
a route-completeness test that every write route is either allowlisted or
covered.

`test_id_minting.py`: as tenant-A staff under `pilot_env`, `POST
/import/courses/c1/turnitin-csv` with a two-row CSV (`Last Name, First
Name, Student ID, Assignment Title, Date Submitted, Similarity, File Name`).
Read the handler (`original/routers/imports.py:26`): it mints
`student_id = sid or name…` with no tenant prefix. Assert every created id
(the response lacks ids — enumerate via `GET /students` as A staff and via
`store`/repo `all_states()` if needed) is `A:`-prefixed, and that an
anonymous `GET /students/{id}` on each created id is refused. Expect red;
`blocker`; docstring `T-04: …`.

Tests to run: `tests/security/`.

---

## Task 5: T-05 — SSRF through Canvas import

**File:** `tests/security/test_ssrf.py`.

Spec: §1.4. Monkeypatch `original.canvas.live_import.make_client` to
return an `httpx.AsyncClient(transport=httpx.MockTransport(handler))`
whose handler records every request URL and returns an empty JSON list
(`tests/test_canvas_live.py` shows the seam — reuse its pattern). Under
`pilot_env` as tenant-A staff, `POST /canvas/baseline/{A-student}/list-canvas-submissions`
with body `{"canvas_url": <url>, "access_token": "t", "canvas_course_id":
"1", "canvas_user_id": "2"}` for each of: `http://localhost:8001`,
`http://127.0.0.1`, `http://169.254.169.254/latest/meta-data`,
`http://10.0.0.1`, `http://192.168.1.1`, `http://[::1]`, `file:///etc/passwd`.
Assert the response is 4xx **and** the recorded request list is empty (the
server must refuse before contacting the host). Parametrised; expect red;
`blocker`; docstring `T-05: …`. Add one green control: a public
`https://canvas.example.edu` URL *is* contacted.

Do not duplicate the existing credential-confusion tests in
`tests/test_canvas_live.py`; cross-reference them in a comment.

Tests to run: `tests/security/test_ssrf.py`, `tests/test_canvas_live.py`.

---

## Task 6: T-08 — delete_student completeness, both backends

**File:** `tests/test_repository_contract.py` (append one class) — or, if
that file's `repo` fixture cannot be reused without copying it, a new
`tests/test_delete_completeness.py` that imports `BACKENDS`,
`_postgres_available`, and builds the same fixture by calling into the
contract module's helpers. Prefer appending.

Spec: `docs/testing/03-api-persistence.md` §2 "Delete completeness".

1. Derive `STUDENT_TABLES` from `original.db.models.live.LiveBase.metadata`:
   every table with a column named `student_id`. Assert the derived set
   contains at least `student_profiles, fidelity_scores, submission_manifests,
   corrections, bluebook_submissions, baseline_requests, formation_pathways,
   audit_log` so the derivation cannot silently shrink.
2. For one student in one tenant, write a row into **every** derived table
   through the repository's public methods (find the writer for each:
   `grep -n "def " original/repository.py`; e.g. `add_baseline`,
   `record_fidelity`/`save_score`, `add_correction`, `record_bluebook_submission`,
   `create_baseline_request`, formation pathway create, audit log write).
   If a table has no public writer, list it in the report and insert via
   the backend's own connection with a comment saying why.
3. Call `repo.delete_student(sid)`; then, for each table, count rows with
   that `student_id` (for SQLite via `store._get_conn()`-style read; for
   Postgres via the engine — read-only inspection is acceptable here and
   must be commented as the one deliberate exception to the public-only
   rule). Assert every count is 0, reporting the full non-zero list.
4. Expect red on both backends (the review found four tables missed).
   Mark `blocker`, docstring `T-08: …`. Run on Postgres too: `make db-up`
   then `DATABASE_URL=$(bash scripts/local_postgres.sh url)` in the env.

Tests to run: the new class on both backends;
`tests/test_repository_contract.py -k "Delete"` at minimum.

---

## Task 7: T-09 — event-loop starvation during bulk upload

**Files:** `tests/perf/__init__.py`, `tests/perf/test_event_loop_not_blocked.py`.

Spec: `docs/testing/07-performance-reliability.md` §2. Use
`httpx.AsyncClient(transport=httpx.ASGITransport(app=live_app), base_url="http://t")`.
Probe route: `GET /health` (cheap, unauthenticated; the doc names the
proctor beat — `/health` is the same event-loop probe without session
setup; say so in a comment). Handlers under test, one parametrised case
each: `POST /students/{sid}/baseline/upload-batch` with ten 400-word
`.txt` files; `POST /students/{sid}/upload` with one file; `POST
/import/courses/c1/turnitin-csv` with a 2,000-row CSV. Skip the two Canvas
handlers (they need a slow fake upstream — note as follow-up).

Pattern: start the heavy request as a task, `await asyncio.sleep(0.05)`,
time the probe with `perf_counter`, assert the probe completed in < 250 ms
and returned 200, then await the heavy task and assert it did not error.
Also include a **control** that proves the probe itself is fast with no
load (< 50 ms) so a slow probe cannot be mistaken for starvation. Mark
`perf`; expected red for the `async def` handlers (`students_baseline.py:329`,
`students.py:341`, `imports.py:26`); `blocker`; docstring `T-09: …`.
Skip (with `uninformative` in the reason) when `os.cpu_count() < 2`.

Tests to run: `tests/perf/`.

---

## Task 8: T-07 — the pilot lockset cannot import the Postgres backend

**File:** `tests/config/__init__.py`, `tests/config/test_lockset_imports.py`.

Spec: `docs/testing/08-config-deploy-readiness.md` §2 "unit-level twin".
Approach: in a **subprocess** (so `sys.modules` is clean), install a
`sys.meta_path` finder that raises `ImportError` for any top-level module
that is neither in `sys.stdlib_module_names`, nor `original`, nor provided
by a distribution pinned in `requirements-pilot.lock.txt` (map
distribution → top-level modules with
`importlib.metadata.packages_distributions()` from the current venv, which
has everything installed). Then `import original.repository` and call
`original.repository.get_repository()` with `REPO_BACKEND=postgres` in the
subprocess env. Assert exit 0. Parametrise over
`REPO_BACKEND=sqlite` (expected green), `REPO_BACKEND=postgres` and
`REPO_SHADOW=postgres` (expected red — `sqlalchemy`, `psycopg2`, `alembic`
are absent from the lockset). Mark `boot`; red cases `blocker`; docstring
`T-07: …`. Print the blocked module name in the failure message.

Tests to run: `tests/config/`.

---

## Task 9: T-26 — auth matrix skeleton (green)

**Files:** `tests/security/test_auth_matrix.py`, `tests/security/auth_matrix.json`.

Spec: `docs/testing/04-security-adversarial.md` §2, **skeleton only**:
one representative route per router (12 routers: health, auth, lti_routes,
bluebook, students, students_baseline, students_scoring, tenants, me,
imports, admin, proctor) × roles `anonymous, student_own, student_other,
professor_own, professor_other, operator, tampered, expired`. The JSON
table maps `"<METHOD> <path>" → {role: expected_status}`. Fill it by
**observing** current behaviour under `pilot_env` and recording it — this
task pins the policy as it is, so the file is green. Where observed
behaviour is one of the T-02…T-06 holes, record the observed status and
add `"_note": "T-0N open"` on that entry rather than the desired status.
Add a completeness test: every router module in `original/routers/` has at
least one route in the table. Mark `security`. Use JSON, not YAML (no
new dependency).

Tests to run: `tests/security/test_auth_matrix.py`.

---

## Task 10: T-31 — first mutation run on two modules

**Files:** `requirements-dev.txt` (add `mutmut`, pinned to the current
release), `scripts/mutation_run.sh` (new), `docs/testing/mutation-baseline.md`
(new).

Install mutmut into the venv (`.venv/bin/pip install mutmut==<pin>`; report
the version). Configure via `setup.cfg` or `pyproject.toml` `[tool.mutmut]`
(whichever mutmut's version wants) with `paths_to_mutate` =
`original/db/tenancy_shim.py,original/principal.py` and `tests_dir` =
`tests/`, runner `python -m pytest -x -q tests/test_principal_branches.py
tests/test_tenant_isolation.py` (add `tests/test_tenancy_shim.py` only if
Task 2 of a later phase created it — it does not exist now; say so).
Run it. Record per-module: mutants total / killed / survived / timeout,
kill rate, and the list of surviving mutants (mutmut's `show` output) in
`docs/testing/mutation-baseline.md` with the date and command. Do **not**
write tests to kill survivors — that is Phase E. `scripts/mutation_run.sh`
reproduces the run. If mutmut cannot run in this environment within 30
minutes, report BLOCKED with the exact error.

Tests to run: none beyond mutmut's own runner.

---

## Task 11: Register and ledger update (controller)

Update `docs/testing/10-gap-register.md` state column for T-01…T-09, T-26,
T-31 to `red`/`green` as measured, add the measured numbers (FPR per N,
mutation kill rate) to the relevant rows, and append the Phase A outcome
paragraph under "Roadmap".
