# 01 — Current state: what exists, what is strong, where the suite is blind

Audit snapshot taken 2026-09-07; counts re-measured on local `main@0d35d486`
(worktree `claude/original-testing-strategy-5add98`, rebased onto it). Numbers are measured, not copied
from CLAUDE.md; where they differ from CLAUDE.md, trust these and update that.

---

## 1. Scale

| Thing | Count |
|---|---|
| Tests collected (`pytest --collect-only tests/ validation/test_tier10_optional.py`) | 3,334 |
| `def test_` functions | ~2,816 |
| Test files | 193 (`tests/` root ~120, `tests/validation/` 30 incl. two TermSim files, `tests/context/` 20, `tests/quantum/` 16, `tests/fusion/` 7) |
| Test LOC | ~50,000 (source under `original/` is ~35,400) |
| Playwright specs / tests | 14 files / ~72 tests, chromium only |
| Vitest tests (`app/`) | 11 files (`App.test.tsx` + 10 components), jest-axe |
| `original/` combined stmt+branch coverage (2026-08-20) | 99.61 % (45 missing stmts, 12 missing + 10 partial branches, all documented as accepted) |
| CI floor | `--cov-branch --cov-fail-under=98` |
| Custom markers | `slow` (7 sites, 2 files), `postgres` (6 files, 270 tests) |
| `xfail` / unconditional `skip` | 0 / 0 |
| Conditional skips | 15 `pytest.skip`, 2 `skipif`, 2 `importorskip` — all with a stated reason, all data- or service-availability |

## 2. Test infrastructure

**Fixtures.** One `tests/conftest.py`, 66 lines, three fixtures:
`live_app` (session; `run.load_legacy_demo_app()`), `live_client` (per-test
`TestClient`, 715 usages in 15 files), `store_reset` (per-test SQLite under
`tmp_path` + cache clear, 295 usages). Everything else is local fixtures and
raw `monkeypatch` (1,427 references) — the suite is fixture-poor and
monkeypatch-rich.

**Postgres detection** is *not* in conftest. Five files each carry their own
`_postgres_available()` (`test_repository_contract.py:52`,
`test_shadow_repository.py:23`, `test_migration.py:46`, `test_cutover.py:156`,
`test_persistence_error_arms.py:293`). It is evaluated at fixture-setup time on
purpose so a late `DATABASE_URL` still works. Duplicated five times; §09
consolidates it.

**Selection.** `scripts/changed_tests.py` (pre-push hook) maps a diff to tests
by filename stem plus a full-text import scan. Documented blind spot: tests that
reach a module only through `live_client` HTTP carry no textual reference and
are never selected. CI's full run is the real gate.

**CI shape** (`.github/workflows/test.yml`): `lint` → `pytest` (postgres:16
service, 30-minute cap, measured 15–18 min), `app` (vite lint/typecheck/
coverage/build), `bundle-e2e` (bundle byte-identity, pilot-mode server,
Playwright, then a *second* default-throttle server for the lockout spec),
`security` (pip-audit on the pilot lockset, gitleaks). `serial-lockout.yml`
runs the lockout spec weekly; its header comment is stale — the spec now also
runs on every PR. `calibration-battery.yml` (weekly Monday, `workflow_dispatch`)
runs `python -m validation.calibration_gate --strict --out` under a 30-minute
cap with `continue-on-error: true` and uploads the JSON. Two problems: the
2026-09-07 merge session measured the full G-battery at 20+ CPU-hours (spaCy
re-parse of every corpus document), so the job as written cannot complete; and
`continue-on-error` makes a machinery `ERROR` indistinguishable from a science
`fail` in the Actions UI. No run artifact was available offline to confirm
either way — treat the job as unproven until one is.

**Timing.** No committed `--durations`. Known hot spots from the CI comment:
`tests/fusion/test_wiring.py` six cases at 72–82 s each (~8 min of one job),
`test_dirichlet_multinomial_drift` ~32 s, `test_calibration_scoring_config`
~31 s, `test_feature_pipeline_determinism` ~40 s (six subprocesses). The CI
file itself says the serial job is "at the end of its useful life".

## 3. Styles present, and what each pins

| Style | Examples | Invariant |
|---|---|---|
| Property-based (hypothesis, 3 files) | `test_gate_properties.py`, `test_quantum.py`, `test_repository_contract.py::TestDensityMatrixRoundtrip` | gate verdict logic over all inputs; CRUD parity across backends |
| Cross-process determinism | `test_feature_pipeline_determinism.py`, `test_openapi_stability.py` | byte-identical under `PYTHONHASHSEED` 0–5 |
| Flag byte-identity | `test_flag_matrix.py`, `tests/fusion/test_wiring.py`, `tests/context/test_blend.py::TestWindowAiShadow` | default-off flags do not move `deviation_score` or the action |
| Contract | `test_repository_contract.py` (2,504 LOC, ×2 backends), `test_gate_falsifiability.py` | one interface, N implementations; no gate passes by construction |
| Route-table-driven negative | `test_pilot_lockdown.py::test_no_admin_route_answers_a_student_principal` | a new admin route cannot escape the lockdown |
| Negative-space | `test_email_notification_noop.py` | a no-op stays a no-op |
| Transport-seam fake | `test_canvas_live.py` (`httpx.MockTransport`) | real client code, fake wire |
| Corpus/empirical | `tests/validation/*` (28 files) | committed artifacts match |

These are good patterns. The strategy reuses them rather than inventing new ones.

## 4. Source-to-test map — the only real holes

Direct-import counts undercount routers (driven by URL) and ORM models (imported
from the package), so the list below is filtered to modules that are
*genuinely* unreferenced or single-referenced *and* high-consequence.

| Module | Lines | Direct tests | Why it matters |
|---|---|---|---|
| `original/features/tier8.py` | 144 | **0** | the only feature tier without a `test_tier8.py`; 100 % covered only transitively via `pipeline.py`; nothing pins the stress-entropy math |
| `original/db/tenancy_shim.py` | 63 | **0** | scoped `"tenant:local"` id ↔ composite-key translation with a documented `demo:foo` vs legacy-flat subtlety — pure, small, tenant-safety-critical |
| `original/voice.py` | 435 | 1 (`test_voice_leak.py`) | the ADR-005 redaction choke point that keeps raw scores away from students |
| `original/postgres_repository.py` | 2,316 | 3 | reads ~0 % covered without `make db-up`; contract suite is its real coverage |
| `original/quantum/professor_narrative.py` | 806 | 3 | professor-facing prose; content assertions are thin |
| `original/features/prosodic.py` | 670 | 1 | tiers 13–15 |
| `original/routers/admin.py` | 660 | 1 direct (+ path-driven) | calibration lab apply path — which the architecture review found to be a no-op |
| `original/routers/students_scoring.py` | 591 | 2 direct | the money path |

Everything else is either well-referenced or dormant v1
(`core/config.py`, `core/logging.py`, `core/security.py`, `cli/*`).

## 5. Validation layer (summary; detail in §06)

Nine `evaluate_g*` functions plus the four TermSim gates T-1…T-4 (merged
2026-09-07, registered in `validation/gate_contracts.py`), three-valued
verdicts, `--strict` folds `uninformative` into `fail`. Every gate has a
registered failure witness and `test_gate_falsifiability.py` proves each
witness fails *for the right leg*. The G5/G6 machinery fix (drift-gate holds
carved out of leg-health checks, `4de85b84`) is on `main`. The copyright fence
for the cross-genre corpus is in `.gitignore`. Newest committed **G-battery**
report is still 2026-07-31 and stale: it predates G7/G8 and the G5/G6 fix,
and its G1 `passed: true` contradicts its own uninformative text. The only
newer evidence is TermSim's first-light report
(`validation/termsim/reports/2026-08-27-first-light.md`, 3 seeds, 18–34 min
wall per seed on a 12-core box), which corroborates the saturation finding.
G7 and G-P3 have never produced a verdict (corpus uncommittable).

## 6. Where the suite is structurally blind

These are not missing lines. They are classes of failure that the current suite
*cannot* see no matter how many tests are added in the current style.

**B1 — Pilot-shaped inputs.** G1's LOO harness gives authors 10–60 baseline
docs; the pilot's modal profile has 3. At N=3, 63–83 % of features sit on the
`0.15/sqrt(N)` sigma floor (`quantum/state.py:271`) and same-author deviation
lands at 0.75–0.82 — `escalate` under `ACTION_THRESHOLDS`
(`constants.py:706`). G1's actions go through the typicality band, which is off
in production; production uses the fixed thresholds. No test scores a genuine
author at N=3 through the production path and asserts the action.
(Source: 2026-09-02 architecture review probe; corroborated by TermSim's first
matrix run — honest-term flag probability 100 % at monitor+.)

**B2 — Deployment configuration.** Every test boots via
`run.load_legacy_demo_app()` in a venv that has `sqlalchemy`, `psycopg2`, and
`alembic`. The pilot lockset (`requirements-pilot.txt`, 15 lines) has none of
them, so `REPO_BACKEND=postgres` on the pilot bricks boot — `api.py:159`
catches only `NotImplementedError`. No test installs the lockset.

**B3 — Adversarial callers.** The tenant-isolation tests are positive/negative
over *well-formed* principals. Nobody plays the attacker: cross-tenant read of
`/baseline-requests/pending`, unauthenticated `POST /bluebook/submissions`,
Turnitin import minting flat ids, SSRF through Canvas import, the demo tree
serving a live `seed.db`. Five holes, zero failing tests.

**B4 — Time and concurrency.** One `threading.Thread` test in the whole suite.
Four `async def` handlers do CPU-bound work on the event loop
(`routers/imports.py:26,147,235`, `students_baseline.py:342`, `students.py:341`);
a bulk upload freezes live exams. `NULL_MODEL=impostor` (the demo default and
`students_scoring.py`'s peer pool) does a full `all_states()` scan per score.
Nothing measures either.

**B5 — Schema drift.** Alembic has zero tests. Every test and
`init_live_schema()` build the schema with `create_all`, so the four-revision
chain can drift from `LiveBase.metadata` and nothing notices until a deploy.

**B6 — Upstream shape drift.** Canvas, Bbook, and platform JWKS responses are
hand-written literals in test files. No recorded fixture, no schema check.
The LTI `_JWKS_CACHE` (`lti.py:182`) has no TTL; key rotation is untested.

**B7 — Assertion strength.** 99.61 % coverage says the lines ran. The
coverage effort's own report found a test whose target branch "silently
no-op'd every run while the test still passed". No mutation score exists, so
there is no measurement of how many tests would notice a wrong answer.

**B8 — The second frontend.** `demo/app/` (13 React entry points, committed
bundles) has no test script, no spec, and — unlike `demo/bluebook/` — no CI
staleness check on its bundles. `demo/{admin,admin-context,lab,onboard,
playground}.html` have no browser coverage. `test_prototype_accessibility_contract.py`
greps source for substrings; it is not an accessibility test.

**B9 — Stale security documentation.** `docs/SECURITY_AUDIT.md` §3 reports
rate limiting PASS for `slowapi` on `/api/v1/*` — the dormant stack. The live
stack has no rate limit except the login throttle; `/students/{id}/score` is
unlimited. `docs/phase3-httpOnly-cookie-auth.md` describes a removed design.

Each of B1–B9 maps to one or more gap IDs in `10-gap-register.md`.

## 7. What not to touch

- The coverage floor. It is a tripwire at the right level. Raising it buys
  nothing; lowering it invites rot.
- `test_gate_falsifiability.py` and `test_flag_matrix.py`. They are the
  suite's best ideas. Extend them; do not refactor them.
- `test_repository_contract.py`'s public-interface-only rule. It is what makes
  dual-backend possible.
- The two-server lockout dance in `bundle-e2e`. The comment explains why a
  single process cannot host both throttle limits. It looks redundant; it is
  not.
