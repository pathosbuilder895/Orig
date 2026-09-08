# Mutation testing baseline — T-31

**Status:** first run, 2026-09-08. Establishes the baseline this task set out
to establish (`docs/testing/02-unit-property-math.md` §5,
`docs/testing/10-gap-register.md` T-31). Per the task scope, this does **not**
add tests to kill anything found here — that is a later phase.

## Setup

- Tool: [mutmut](https://mutmut.readthedocs.io/) `3.7.0` (pinned in
  `requirements-dev.txt`; was the current release on the index at run time —
  `pip index versions mutmut` showed `3.7.0` as latest). This is the only
  environment change this task made, per the task brief.
- Config: `[tool.mutmut]` in `pyproject.toml`.
- Reproduce with `bash scripts/mutation_run.sh` (always starts from a clean
  `mutants/` — see "A sandbox-specific setup snag" below for why).

### Config shape, and why it isn't a literal 2-file `source_paths`

The task brief describes `paths_to_mutate` = the two target files. mutmut
3.7.0 deprecates that key in favor of `source_paths`, but more importantly
its execution model is different from what that name suggests: mutmut 3.x
copies exactly `source_paths` into a `mutants/` directory and runs pytest
against that copy with `mutants/` prepended to `sys.path` (and the real
project root removed) — see `setup_source_paths()` in
`mutmut/__main__.py`. If `source_paths` were literally the two target files,
`mutants/original/` would contain only `db/tenancy_shim.py` and
`principal.py` — no `original/__init__.py`, no `original/api.py`, none of
the ~100 other modules the package needs. That breaks immediately:
`tests/test_tenant_isolation.py` does `import run` and
`app = run.load_legacy_demo_app()` **at module scope**, which imports
`original.api`, which (via internal `from . import ...`) pulls in most of
the package.

The config actually used:

```toml
[tool.mutmut]
source_paths = ["original/"]
only_mutate = ["original/db/tenancy_shim.py", "original/principal.py"]
also_copy = ["run.py"]
pytest_add_cli_args_test_selection = [
    "tests/test_principal_branches.py",
    "tests/test_tenant_isolation.py",
]
pytest_add_cli_args = ["-p", "no:cacheprovider"]
```

`source_paths` is the whole package (copied verbatim, ~103 of 105 files
untouched — needed only so imports resolve); `only_mutate` is what actually
restricts *mutation* to the two target files (confirmed by the run log:
"2 files mutated, 103 ignored, 0 unmodified"). `run.py` needs its own
`also_copy` entry since it lives at the repo root, outside `original/`.
mutmut's `PytestRunner` already prepends `-x -q -p no:randomly
-p no:random-order` to every test invocation
(`_pytest_args_regular_run` in `mutmut/__main__.py`); `pytest_add_cli_args`
appends `-p no:cacheprovider` on top, matching the runner the brief
specifies. The effective runner is therefore
`python -m pytest -x -q -p no:randomly -p no:random-order <selected tests>
-p no:cacheprovider`, which is the required
`-x -q -p no:cacheprovider tests/test_principal_branches.py
tests/test_tenant_isolation.py` plus two harmless extra plugin-disable
flags mutmut always adds.

There is no `tests/test_tenancy_shim.py` yet, as the brief warned — the shim
is exercised only indirectly (or, as it turned out, not exercised at all by
this runner — see Results).

This worked end to end on mutmut 3.7.0; no fallback to the 2.x CLI shape or
to `mutmut==2.5.1` was needed.

### A sandbox-specific setup snag

The first full run (after an initial smoke-test-scoped run had already
populated `mutants/`) crashed during `copy_also_copy_files()`:

```
shutil.Error: [('tests/test_tier17 2.py', 'mutants/tests/test_tier17 2.py',
  "[Errno 1] Operation not permitted: 'mutants/tests/test_tier17 2.py'")]
```

`tests/test_tier17 2.py` is one of ~39 macOS Finder-duplicate files under
`tests/` (gitignored via the `* 2.*` pattern in `.gitignore`, matching the
"Historical note" in CLAUDE.md about these). mutmut's `also_copy` step uses
`shutil.copy2`, which calls `chflags` to mirror the source file's flags onto
the destination. Retrying `shutil.copy2` on that same pair manually
reproduced it: the *destination* file left over from the smoke-test run had
picked up `hidden,compressed` flags (visible via `ls -lO`), and re-running
`chflags` against an already-flagged file raised `PermissionError` in this
sandboxed/APFS environment, even though the same file could be freshly
created without issue. **Fix: always start from a clean `mutants/`
directory** (`scripts/mutation_run.sh` does `rm -rf mutants` before every
run) — a fresh copy never hits the overwrite-an-already-flagged-file path.
This is unrelated to the mutation content and shouldn't recur outside this
kind of sandboxed filesystem.

## Results

Run: 2026-09-08, `bash scripts/mutation_run.sh` (mutmut 3.7.0), from a clean
`mutants/`. Mutant generation: 262 total (2 files mutated, 103 ignored, 0
unmodified) — 14 for `tenancy_shim.py`, 248 for `principal.py`. Wall time for
mutant generation + full test-matrix run: ~4 minutes (262/262 at up to ~36
mutations/second once past the one-time "Running stats" / "Running clean
tests" / "forced fail test" warm-up, which itself takes a couple of minutes
because it imports the full live app — spaCy, sklearn, scipy).

| Module | Total | Killed | Survived | No tests | Segfault | Timeout | Suspicious | Kill rate |
|---|---|---|---|---|---|---|---|---|
| `original/db/tenancy_shim.py` | 14 | 0 | 0 | 14 | 0 | 0 | 0 | **undefined — 0 % coverage from this runner** |
| `original/principal.py` | 248 | 126 | 0 | 3 | 119 | 0 | 0 | **126/248 = 50.8 % of all mutants; 126/126 = 100 % of the mutants that got a clean verdict** |
| **Total** | 262 | 126 | 0 | 17 | 119 | 0 | 0 | 126/262 = 48.1 % of all mutants |

Both "kill rate" figures for `principal.py` are mutmut's own totals (from
`mutmut results --all true`, cross-checked against
`calculate_summary_stats`'s emoji summary line at run completion), just
divided two different ways: against everything mutated, and against
everything mutmut was able to reach a killed/survived verdict on. Neither
number should be read alone — see "Reading the segfault bucket" below for
why the second one overstates confidence.

### No survivors — but read this against the "no tests" and "segfault" rows, not in isolation

**Zero mutants were classified `survived`** anywhere in this run. Per
`docs/testing/02-unit-property-math.md` §5's own framing ("the first run
will be lower and *that number is the finding*"), a 0-survivor first run on
a security-critical pair of modules is unusual enough to be suspicious
rather than reassuring on its own — the CLAUDE.md changelog has a standing
example of exactly this trap (`GENRE_INVARIANT_WEIGHTS_ENABLED`: "built,
tested, and fires in 1 of 6 folds — that once being noise"). Two real
findings sit underneath the flattering top-line number:

1. **17 mutants (14/14 of `tenancy_shim.py`, plus 3 of `principal.py`'s
   `assert_tenant_access`) got zero test coverage from this runner** — not
   "weakly tested," literally never executed by
   `tests/test_principal_branches.py` or `tests/test_tenant_isolation.py`.
   mutmut correctly reports these as `no tests` rather than `killed`, so
   they don't inflate the kill rate, but they're the actual finding: an
   entire module used for the live-schema tenant-scoping split
   (`split_scoped_id`/`join_scoped_id`/`resolve_tenant_id`) and one whole
   authorization function (`assert_tenant_access`, gating cross-tenant reads
   of a *tenant record*) have no test in scope here that would notice a
   flipped `==`/`!=` or an inverted `in SUPER_ROLES` check. See the diffs
   below.
2. **119 of 248 `principal.py` mutants (48 %) came back `segfault`** — not
   killed, not survived, not "no tests." These are unclassified, not clean
   passes. See the next section; the honest kill-rate denominator for
   `principal.py` is contested between 248 (all mutants) and 126 (only the
   ones mutmut could actually classify), and the true position of the 119
   segfault mutants on "would a real test have killed this" is unknown.

### Reading the segfault bucket

mutmut maps a child test-run's exit code `-11` (SIGSEGV) or `-9` (SIGKILL)
to a `segfault` verdict (`status_by_exit_code` in `mutmut/__main__.py`).
119/248 `principal.py` mutants landed here, concentrated in
`resolve_principal` (57/76), `assert_student_access` (13/18),
`tenant_environment` (8/10), `_bearer` (11/21), `_secret` (5/6), and smaller
counts elsewhere — i.e. the functions most entangled with the live app's
request path (`resolve_principal` calls into `student_auth`;
`assert_student_access` and `tenant_environment` are hit through the real
FastAPI `TestClient` calls in `tests/test_tenant_isolation.py`, which
imports and boots the full `original.api` app, including the
numpy/scipy/scikit-learn/spaCy-backed feature and scoring pipeline, at
module import time).

This was investigated rather than shrugged off, because 48% unclassified
is too large to bury in a summary table:

1. **Not flaky / not a parallelism artifact.** Re-running the exact same 119
   mutant names with `--max-children 1` (fully sequential, no worker pool)
   reproduced the identical 119-mutant segfault set. Ruled out simple
   memory pressure from parallel forked children (this machine: 12 cores,
   24 GB RAM — not obviously constrained either way, but the determinism
   across two different concurrency settings is the stronger evidence).
2. **Not (solely) an Accelerate/BLAS fork-safety issue**, the next most
   likely mechanism (mutmut's parent process imports numpy/scipy/spaCy,
   then `os.fork()`s a child per mutant — a well-known macOS crash class
   when native BLAS thread pools survive a fork). Re-running a 6-mutant
   sample with `VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1
   OPENBLAS_NUM_THREADS=1` (the standard mitigation) still reproduced all 6
   segfaults unchanged.
3. **Does not reproduce under a plain, direct pytest invocation.** Manually
   setting `MUTANT_UNDER_TEST=original.principal.x_verify_principal_token__mutmut_9`
   and running `python -m pytest -x -q -p no:cacheprovider
   tests/test_principal_branches.py tests/test_tenant_isolation.py` directly
   from `mutants/` — the same env var mutmut's trampoline mechanism reads,
   the same test files, the same runner flags — passed cleanly (16 passed,
   exit 0), no crash. This means the crash is specific to mutmut's own
   execution path for that mutant (most likely its narrower
   per-mutant test selection via `tests_by_mangled_function_name`, combined
   with `os.fork()` at a point some cached/instrumented state
   `coverage`/`pytest-cov` or mutmut's own dependency tracking has already
   touched) — not a property of the mutation itself, and not reproducible
   by hand with the tools available in this session.

**Conclusion recorded, not resolved:** in this sandboxed macOS environment,
mutmut 3.7.0 cannot reliably classify roughly half of `principal.py`'s
mutants for functions reachable only through the live-app `TestClient`
path. The 119 segfault mutants are neither evidence of a passing nor a
failing assertion; they are evidence that this measurement is incomplete.
Whoever next touches T-31 should either try this on a non-sandboxed runner
(e.g. plain CI, or a bare local shell) to see if the segfaults disappear —
which would confirm the sandbox-specific-execution-path theory — or dig into
mutmut's coverage/dependency-tracking + fork interaction directly.

### The 17 "no tests" mutants — full list and diffs

`original/db/tenancy_shim.py` — all 14 mutants across all 3 functions, 0
covered:

```
original.db.tenancy_shim.x_split_scoped_id__mutmut_1  (and _2 through _11, 11 total)
original.db.tenancy_shim.x_join_scoped_id__mutmut_1
original.db.tenancy_shim.x_resolve_tenant_id__mutmut_1
original.db.tenancy_shim.x_resolve_tenant_id__mutmut_2
```

Representative diffs (`mutmut show <name>`):

```diff
# original.db.tenancy_shim.x_split_scoped_id__mutmut_1: no tests
--- original/db/tenancy_shim.py
+++ original/db/tenancy_shim.py
@@ -12,7 +12,7 @@
     Mirrors principal.tenant_of()'s exact parsing (split on the FIRST ':'
     only, local id may itself contain colons).
     """
-    tenant = tenant_of(student_id)
+    tenant = None
     if tenant is None:
         return _LEGACY_FLAT_TENANT, student_id
     return tenant, student_id.split(":", 1)[1]
```

```diff
# original.db.tenancy_shim.x_join_scoped_id__mutmut_1: no tests
--- original/db/tenancy_shim.py
+++ original/db/tenancy_shim.py
@@ -2,6 +2,6 @@
     """Inverse of split_scoped_id. NOT the inverse of "always prepend
     tenant_id:" — the legacy-flat sentinel must round-trip back to the
     original colon-less id, not to "__legacy_flat__:{local_id}"."""
-    if tenant_id == _LEGACY_FLAT_TENANT:
+    if tenant_id != _LEGACY_FLAT_TENANT:
         return local_id
     return f"{tenant_id}:{local_id}"
```

```diff
# original.db.tenancy_shim.x_resolve_tenant_id__mutmut_2: no tests
--- original/db/tenancy_shim.py
+++ original/db/tenancy_shim.py
@@ -2,4 +2,4 @@
     """The composite-key tenant_id a scoped/flat student_id resolves to —
     convenience wrapper for callers that only need the tenant half (e.g. to
     ensure the parent tenants row exists before an insert)."""
-    return split_scoped_id(student_id)[0]
+    return split_scoped_id(student_id)[1]
```

`original/principal.py`'s `assert_tenant_access` — all 3 mutants, 0 covered
(this is a live authorization check gating cross-tenant reads of a *tenant
record*; `SUPER_ROLES` and `==` are both inverted below with nothing to
catch it):

```diff
# original.principal.x_assert_tenant_access__mutmut_1: no tests
--- original/principal.py
+++ original/principal.py
@@ -6,7 +6,7 @@
     registry view — see ``SUPER_ROLES``). Callers are expected to have
     already rejected non-staff principals (e.g. via ``_require_staff``).
     """
-    if principal.role in SUPER_ROLES:
+    if principal.role not in SUPER_ROLES:
         return  # operator / super-admin: cross-tenant by design
     if tenant_id == principal.tenant_id:
         return
```

```diff
# original.principal.x_assert_tenant_access__mutmut_2: no tests
--- original/principal.py
+++ original/principal.py
@@ -8,7 +8,7 @@
     """
     if principal.role in SUPER_ROLES:
         return  # operator / super-admin: cross-tenant by design
-    if tenant_id == principal.tenant_id:
+    if tenant_id != principal.tenant_id:
         return
     raise TenantAccessError(
         f"{principal.role}@{principal.tenant_id} cannot access tenant '{tenant_id}'"
```

```diff
# original.principal.x_assert_tenant_access__mutmut_3: no tests
--- original/principal.py
+++ original/principal.py
@@ -11,5 +11,5 @@
     if tenant_id == principal.tenant_id:
         return
     raise TenantAccessError(
-        f"{principal.role}@{principal.tenant_id} cannot access tenant '{tenant_id}'"
+        None
     )
```

### No survivors to list

Per the task scope, surviving mutants are what a later phase would write
tests to kill. There were none in this run — every mutant mutmut could
reach a verdict on was `killed`. (See above for why that headline number
needs the `no tests` / `segfault` context next to it, not instead of it.)

## Reading: what this says about assertion strength

Where these two files' behavior actually gets exercised by
`tests/test_principal_branches.py` and `tests/test_tenant_isolation.py`, the
assertions are strong: 126/126 classifiable mutants died, including several
that only change constants or comparison operators deep inside token
verification and access-control branches (`verify_principal_token`,
`extract_scoped_id`, `mint_principal_token`) — exactly the kind of survivor
the spec warned to expect on a first run, and none of them survived. But
"strong where exercised" is doing real work in that sentence: the two files
were picked *because* they're security-critical, and this run found one
entire module (`tenancy_shim.py`) and one entire authorization function
(`assert_tenant_access`) with no coverage at all from the configured runner,
plus a structural gap in the tooling itself — this environment cannot
currently get a verdict on roughly half of `principal.py`, concentrated
exactly in the functions that mediate real HTTP requests
(`resolve_principal`, `assert_student_access`, `tenant_environment`). A
"100% kill rate" read off the classifiable subset alone would be reporting
confidence the run didn't actually earn. The honest summary is: assertion
quality looks good on the ~half of `principal.py` this run could see, coverage
has a real hole in `tenancy_shim.py` and `assert_tenant_access`, and roughly
half of `principal.py` is simply unmeasured pending a fix to the segfault
issue above (not to be confused with the coverage gaps — the segfault
mutants have covering tests; the *tooling* couldn't run them here). This
is what a first mutation-baseline run is for.

## Files touched by this task

- `requirements-dev.txt` — `mutmut==3.7.0`, pinned.
- `pyproject.toml` — new `[tool.mutmut]` section.
- `.gitignore` — `mutants/` and `.mutmut-cache/`.
- `scripts/mutation_run.sh` — new; reproduces the run end-to-end from a
  clean checkout.
- `docs/testing/mutation-baseline.md` — this file.

No test files were added or modified, and nothing under `original/`,
`run.py`, `demo/`, or `validation/` was touched.
