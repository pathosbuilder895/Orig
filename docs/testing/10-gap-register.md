# 10 — Gap register and roadmap

The single prioritised list. Every other document in `docs/testing/` explains
one slice; this one ranks across slices. Update it in the PR that opens or
closes a gap.

**Severity:** P0 = pilot go-live blocker; P1 = must land before the flag or
surface it guards is enabled; P2 = quality debt with a known failure class;
P3 = hygiene.
**Effort:** S ≤ half a day; M ≤ 2 days; L ≤ a week.
**State:** `open` (no test), `red` (test exists and fails on `main`),
`green`, `n/a` (decided not to do; reason in the row).

---

## P0 — pilot go-live blockers

| ID | Gap | Blind spot | Doc | Effort | Acceptance | State |
|---|---|---|---|---|---|---|
| T-01 | Same-author FPR at N=3 baselines through the API (0.75–0.82 measured; `escalate`) | B1 | 06 §3, 02 §2.1 | M for the test; the fix is product work | `test_cold_start_fpr` green at N=3,5,10 on ≥8 committed authors — measured 2026-09-07: N=3 flagged 10/11 (0.909), N=5 0.909, N=10 uninformative — holdouts are a different section of the SAME work for 8 of 11 authors (`holdout_same_work_count`), so the cross-work claim is not yet measured; `tests/certification/test_cold_start_fpr.py` | red |
| T-02 | `GET /baseline-requests/pending` leaks cross-tenant emails and live magic links | B3 | 04 §1.1 | S | scoped test green — `tests/security/test_cross_tenant_read.py` | red |
| T-03 | Unauthenticated `POST /bluebook/submissions` | B3 | 04 §1.2 | S | route-table anonymous-write test green with allowlist — `tests/security/test_unauthenticated_writes.py` | red |
| T-04 | Turnitin import mints flat ids → unauthenticated essay reads | B3 | 04 §1.3 | S | every minted id tenant-prefixed; anonymous read refused — `tests/security/test_id_minting.py` | red |
| T-05 | SSRF via body-supplied Canvas URL | B3 | 04 §1.4 | S | private/loopback/metadata/file URLs refused pre-request — `tests/security/test_ssrf.py` (7 URLs) | red |
| T-06 | Demo static tree serves live `seed.db` under pilot | B3 | 04 §1.5 | S | glob-derived forbidden list all 404 under pilot — `tests/security/test_static_tree.py` — `/seed.db` already gated; the Bluebook sourcemap is the red case | red |
| T-07 | `REPO_BACKEND=postgres` on the pilot lockset bricks boot (`api.py:159` catches `NotImplementedError` only) | B2 | 08 §2 | M | `boot-matrix` postgres cells `up` — `tests/config/test_lockset_imports.py` — blocked on `sqlalchemy` for both `REPO_BACKEND=postgres` and `REPO_SHADOW=postgres` — boot half: `.github/workflows/boot-matrix.yml` boots each lockset the way Render does; the two Postgres cells are `today: down` (exit 3, unhandled `ModuleNotFoundError: sqlalchemy`) and flip red the day the product changes | closed on main (post-#203 rebase: pilot lockset ships sqlalchemy/psycopg2/alembic; `test_lockset_imports.py` blockers unmarked; boot-matrix Postgres cells now `up`) |
| T-08 | `delete_student` misses 4 tables while documented as complete | B5 | 03 §2, 04 §7 | S | metadata-derived completeness test green — `tests/test_repository_contract.py::TestDeleteStudentCompleteness` — leaks `baseline_requests`, `bluebook_submissions`, `formation_pathways` on both backends; `bluebook_sessions` keys on `student_key`, not `student_id`, so it needs its own row/test | red |
| T-09 | Bulk upload blocks the event loop; live exam heartbeats stall | B4 | 07 §2 | S test / S fix | heartbeat < 250 ms during upload, all 5 handlers — `tests/perf/test_event_loop_not_blocked.py` — upload-batch ~9 s late, turnitin-csv ~2.5 s, `.docx` upload ~1.2 s; `.txt` upload green; Canvas handlers deferred | red |
| T-66 | Anonymous flat-id `/students/{id}` writes and `DELETE` succeed on a real deploy (`assert_student_access` has no real-deploy branch for `tenant_of(id) is None`; `_is_staff_only_path` skips `/students/{id}/…`) | B3 | 04 §1.2 | S | `tests/security/test_unauthenticated_writes.py::test_flat_id_student_write_permitted` (8 routes) | red |

## P1 — before enabling the surface it guards

| ID | Gap | Blind spot | Doc | Effort | Acceptance | State |
|---|---|---|---|---|---|---|
| T-10 | Alembic has zero tests; schema built by `create_all` everywhere | B5 | 03 §1 | M | `compare_metadata` empty; round trip; single head | open |
| T-11 | Who provisions the pilot Postgres schema is undetermined | B2 | 08 §4 | S | one test encoding the answer | open |
| T-12 | G5/G6 machinery fix merged (`4de85b84`) but no post-fix committed `--strict` report; verdicts unconfirmed | — | 06 §2 | S (one manual run on the 12-core box) | committed report with G5/G6 verdicts — needs a 20+ CPU-hour manual run — not an agent task; Phase B skipped it | deferred |
| T-13 | G7 / G-P3 never returned a verdict (corpus uncommittable) | — | 06 §2 (plan 02) | L | first verdict, or `notes` says why not in CI | open |
| T-14 | `calibration-battery.yml` cannot finish (20+ CPU-h vs 30-min cap) and `continue-on-error` hides ERROR | — | 06 §7 | M | vector cache + per-gate matrix; step fails on ERROR; one completed weekly run — Phase B Task 7 (vector cache + per-gate matrix + fail-on-ERROR) was skipped by decision on 2026-09-09; `docs/superpowers/plans/2026-09-08-testing-phase-b.md` Task 7 carries the brief | open (deferred) |
| T-15 | No flag byte-identity matrix over all default-off flags | — | 08 §1 | M | snapshot + every table row covered — `tests/config/test_flag_byte_identity.py` + `tests/snapshots/score_default{,_api}.json` via `scripts/update_score_snapshot.py`; 122 arms green, 13 `uninformative` with measured reasons (topic distance 0.16 ≤ 0.25, genre covered, pooled calibration unreachable); tier-10 forced to the TF-IDF backend so the snapshot reproduces off Apple MPS | green |
| T-16 | `SECRET_KEY` does not touch `deviation_score`; docs imply otherwise | — | 08 §1 | S | pinned row in the matrix | open |
| T-17 | Per-score `all_states()` scan is linear in store size; no cross-request bound | B4 | 07 §3 | S test / M fix | scan-count and sub-linear scaling tests | open |
| T-18 | Single-worker constraint unasserted; `_ENV_CACHE`, throttle, genre caches all assume it | B4 | 07 §4, 03 §2 | S | `render.yaml` worker assertion + cross-instance coherence test | open |
| T-19 | `/students/{id}/score` has no rate limit; `SECURITY_AUDIT.md` claims one (dormant stack) | B9 | 04 §3 | S test / S fix | limit test green; audit doc corrected | open |
| T-20 | Login throttle keys on `request.client.host`; behind Render's proxy may be one shared IP (REAUDIT #1) | B4 | 04 §3 | S | `X-Forwarded-For` test, or a documented negative-space test | open |
| T-21 | LTI `_JWKS_CACHE` has no TTL; key rotation breaks launches until restart | B6 | 04 §4, 07 §6 | S | rotation test green | open |
| T-22 | LTI replay within state TTL untested / unimplemented | B6 | 04 §4 | S | replay refused, or negative-space test | open |
| T-23 | `GUARD_DESTRUCTIVE=1` with non-real env should refuse boot (REAUDIT #5) | — | 04 §1.6, 08 §2 | S | `boot-matrix` refuse cell | open |
| T-24 | Calibration-lab Apply is a no-op (scoring reads `constants.ACTION_THRESHOLDS`) | — | 05 §3 | S test / M fix | e2e: rescored tier changes after Apply | open |
| T-25 | `demo/app/` second frontend: no tests, no bundle staleness check, live/dormant unknown | B8 | 05 §2 | S decide / M | byte-check + smoke, or proven 404 under pilot | open |
| T-26 | Cross-tenant abuse suite and auth matrix absent | B3 | 04 §1, §2 | M | `pytest tests/security -m "not blocker"` measured 78 s / 146 passed on 2026-09-08 (target < 60 s not met; `two_tenants` is function-scoped), table-driven — `tests/security/` package + `test_auth_matrix.py` (96 cells observed and pinned) | partial |
| T-27 | Secrets-never-leak test absent | — | 04 §5 | S | sentinel test over all failure paths | open |
| T-63 | `GET /admin/audit` has no tenant filter; B staff read A's audit rows | B3 | 04 §1.1 | S | `tests/security/test_cross_tenant_read.py::test_admin_audit_scoped` | red |
| T-64 | Anonymous `POST /auth/register` accepted (`_require_guard` only) | B3 | 04 §1.2 | S | `tests/security/test_unauthenticated_writes.py` | red |
| T-65 | Anonymous `POST /bluebook/exams/{id}/session` accepted | B3 | 04 §1.2 | S | `tests/security/test_unauthenticated_writes.py` | red |

## P2 — quality debt with a known failure class

| ID | Gap | Blind spot | Doc | Effort | Acceptance | State |
|---|---|---|---|---|---|---|
| T-28 | `features/tier8.py` has no test file; math unpinned | — | 02 §1.1 | S | `test_tier8.py` with oracles | open |
| T-29 | No cross-tier invariant suite (bounds, keys, quotes, length) | — | 02 §1.2 | S | `test_tier_invariants.py` | open |
| T-30 | No property tests on scoring monotonicity, sigma floor, energy conservation, action-mode ordering, shadow≡on | B1, B7 | 02 §2 | M | `test_scoring_properties.py` | open |
| T-31 | No mutation score; 99.6 % coverage unmeasured for assertion strength | B7 | 02 §5 | S setup | weekly kill rate on 6 modules; ≥ 80 % target — `docs/testing/mutation-baseline.md`: principal.py 126 killed / 248 mutants (50.8 %; 126/262 = 48.1 % across both modules) with 119 segfaults (45 % of 262) under mutmut 3.7.0 fork model; tenancy_shim.py 0 % (no test reaches it — T-33) | measured |
| T-32 | `voice.py` redaction guarded by one leak test | — | 02 §3 | S | allowlist + forbidden-substring tests | open |
| T-33 | `tenancy_shim.py` untested | — | 02 §4 | S | round-trip + shape properties | open |
| T-34 | OpenAPI is determinism-checked, not snapshot-checked | — | 03 §4.1 | S | committed snapshot + update script — `tests/snapshots/openapi.json` + `tests/test_openapi_snapshot.py` + `scripts/update_openapi_snapshot.py`; version from pyproject, no per-commit churn | green |
| T-35 | Error envelope consistency unasserted across routes | — | 03 §4.2 | S | route-table malformed-body test | open |
| T-36 | ShadowRepository compares nothing at value level | — | 03 §3 | S | compare mode, or negative-space test | open |
| T-37 | No latency budgets anywhere | B4 | 07 §1 | S | `tests/perf/test_latency_budgets.py` | open |
| T-38 | SQLite WAL/busy_timeout asserted by PRAGMA read, never by contention | B4 | 07 §5 | S | 8-thread contention test both backends | open |
| T-39 | Bbook client tests use a hand-rolled fake; timeouts untestable | B6 | 07 §7 | S | `httpx.MockTransport` | open |
| T-40 | No recorded upstream fixtures for Canvas/Bbook/JWKS; no cross-process fake for e2e | B6 | 05 §7 | M | shared `tests/fixtures/canvas/*.json` + `fake-canvas.mjs` | open |
| T-41 | `imports`, `me`, `lti_routes` routers have no browser flow; `admin` lab journey untested | — | 05 §3 | M | ≥1 spec each | open |
| T-42 | Results-expanded and CorrectionPanel never axe-scanned | — | 05 §4 | S | extended `a11y.spec.mjs` | open |
| T-43 | `test_prototype_accessibility_contract.py` is a substring grep presented as a11y | B8 | 05 §4 | S | renamed + legacy pages under axe | open |
| T-44 | No Bluebook JSX unit tests | — | 05 §1 | M | vitest + axe, ratcheting threshold | open |
| T-45 | Fusion six ≈ 8 min of CI | — | 09 §1.2 | M | file < 60 s — 448 s → 32 s: `_LONG` extracted once per session, `feature_vector`/`analyze_tension_arc` patched as imported into the baseline route, determinism asserted in the fixture | green |
| T-46 | Serial pytest job 15–18 min, 30-min cap already hit once | — | 09 §1.1 | M | 3 shards + combine, ≤ 10 min critical path — `pytest-core`/`pytest-api`/`pytest-rest` + `coverage-combine` via `scripts/shard_paths.py --run`; partition proven by collection (`tests/test_shard_partition.py -q -s` prints the current per-shard triple — not pinned here, it grows with the suite); Postgres-marked files routed to `api`; first real CI run is the wall-time measurement | green (CI unmeasured) |
| T-47 | Committed reports contradict themselves (`passed: true` + UNINFORMATIVE); CLAUDE.md cites G8 from no report | — | 06 §4 | S | `test_report_consistency.py` | open |
| T-48 | Cross-genre corpus copyright fence is only `.gitignore` lines (present on `main`; reverted once on a branch) | — | 06 §5 | S | `git ls-files` fence test | open |
| T-49 | Restore drill is a weekly human hour with no automated twin | — | 08 §6 | S | weekly workflow step | open |
| T-50 | Container image never built in CI | B2 | 08 §7 | S | container-smoke job | open |

## P3 — hygiene

| ID | Gap | Doc | Effort | Acceptance | State |
|---|---|---|---|---|---|
| T-51 | Five copies of `_postgres_available()` | 09 §2 | S | one session fixture — `postgres_available` (session, reachability) + `postgres_schema` (function, `create_all`) in `tests/conftest.py`; five copies removed | green |
| T-52 | No `--strict-markers`; new markers unregistered | 09 §3 | S | registered + strict — done in Phase A: markers registered, `--strict-markers` | green |
| T-53 | `serial-lockout.yml` header claims the spec "ran nowhere"; stale since `7bb2c925` | 01 §2 | S | comment corrected | open |
| T-54 | `OPS_RUNBOOK.md` mentions 5 xfail'd v1 tests that no longer exist; `xfail` policy unenforced | 09 §4 | S | `test_no_xfail.py` + runbook line removed | open |
| T-55 | CLAUDE.md carries counts/timings that go stale monthly | 09 §7 | S | trimmed to commands + link | open |
| T-56 | `.env.example` vs code flag set unchecked | 08 §3 | S | consistency test | open |
| T-57 | `VERIFICATION_MIN_WORDS` looks like a rule, enforces nothing | 06 §5 | S | wired or docstring says unwired | open |
| T-58 | `changed_tests.py` never selects HTTP-driven tests for router changes | 09 §6 | S | router → security/perf mapping pinned | open |
| T-59 | No WebKit or mobile Playwright project | 05 §6 | S | smoke + exam-flow on WebKit; `parked.html` on mobile | open |
| T-60 | Visual regression absent (WS-9 gate now satisfied) | 05 §5 | S | 3 screens, non-blocking | open |
| T-61 | `professor_narrative.py` content obligations unasserted; `_FEATURE_PLAIN` key drift | 02 §6 | S | obligations + key-set test | open |
| T-62 | `scripts/reset_demo_data.py` (destructive, runbook-mandated) has no test | 01 §4 | S | dry-run + apply test on a tmp DB | open |

## Roadmap

Phases are ordered by dependency and by what unblocks the pilot. Each phase
is small enough for one worktree and one PR series.

**Phase A — executed 2026-09-07/08** on branch `claude/testing-phase-a-5add98`
(plan: `docs/superpowers/plans/2026-09-07-testing-phase-a.md`). Every P0
gap now has a red test; blocker tests are excluded from the blocking CI run
by `-m "not blocker and not certification"` and run by the `known-red` job
(`scripts/known_red.py`), which fails the day one of them unexpectedly
passes. Four new holes surfaced while writing the tests (T-63…T-66); one
was reclassified (T-08's `bluebook_sessions` is `student_key`-keyed). The
measured cold-start FPR is 10 of 11 genuine authors flagged at both three and
five baselines. The first mutation run found no surviving mutants but 45 %
segfaults (119 of 262) under mutmut's fork model, so the score is not yet trustworthy.

**Phase A (original plan) — make the blockers visible (1 week).** T-01 (test only), T-02 to
T-09 tests written red, T-26 skeleton, T-31 first mutation run. Output: a
`main` where the pilot blockers are red tests, not a private artifact.
Nothing here is a product fix.

**Phase B — executed 2026-09-08/09** on branch `claude/testing-phase-b-5add98`
(plan: `docs/superpowers/plans/2026-09-08-testing-phase-b.md`). Landed:
T-51 fixtures, T-45 fusion runtime (448 s → 32 s), T-34 OpenAPI snapshot,
T-15 flag byte-identity matrix with two committed score snapshots, T-46
three-shard CI with a coverage-combine job and a partition proof, T-07's
boot matrix (eight cells observed against real lockset venvs). Skipped by
decision: T-14 (battery vector cache + per-gate matrix) — its brief stays
in the plan file as Task 7; T-12 needs a manual multi-hour run. Two
findings surfaced on the way: the API score snapshot originally embedded a
sentence-transformers-on-MPS float that CI could never reproduce (fixed by
pinning the TF-IDF backend in the harness), and `POST /score`'s response
schema drops `quantum_fidelity`, so the amplitude flag cannot move any
API-visible field.

**Phase B (original plan) — infrastructure that Phase C needs (1 week).** T-46 shards, T-45
fusion, T-51/52 fixtures and markers, T-15 flag snapshot, T-07 boot matrix,
T-34 OpenAPI snapshot, T-14 battery vector cache + per-gate matrix, T-12 one
manual battery run committed.

**Phase C — close P0 (product work, 2–3 weeks, separate owners).** The
saturation fix (T-01) is scoring work with three candidate shapes; the five
security holes are router work; T-07 is a lockset/lifespan change; T-09 is a
`def`/threadpool change. Each closes by turning its Phase A test green.

**Phase D — P1 sweep (2 weeks).** Alembic, schema provisioning answer,
G5/G6 merge, security matrix completion, JWKS/replay, rate limit, single-
worker assertions, `demo/app/` decision.

**Phase E — P2/P3 continuous.** One or two items per PR alongside feature
work; the register row is updated in the same PR.

## How to read a row

- A row in `open` state with a P0 severity means a *known* product defect has
  no test. That is the worst state; Phase A exists to empty it.
- A row in `red` state is healthy: the suite knows about the defect and will
  notice the fix.
- A row moves to `n/a` only with a reason and a negative-space test where one
  makes sense (the `test_email_notification_noop.py` pattern).
