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
| T-01 | Same-author FPR at N=3 baselines through the API (0.75–0.82 measured; `escalate`) | B1 | 06 §3, 02 §2.1 | M for the test; the fix is product work | `test_cold_start_fpr` green at N=3,5,10 on ≥8 committed authors | open → red on landing |
| T-02 | `GET /baseline-requests/pending` leaks cross-tenant emails and live magic links | B3 | 04 §1.1 | S | scoped test green | open |
| T-03 | Unauthenticated `POST /bluebook/submissions` | B3 | 04 §1.2 | S | route-table anonymous-write test green with allowlist | open |
| T-04 | Turnitin import mints flat ids → unauthenticated essay reads | B3 | 04 §1.3 | S | every minted id tenant-prefixed; anonymous read refused | open |
| T-05 | SSRF via body-supplied Canvas URL | B3 | 04 §1.4 | S | private/loopback/metadata/file URLs refused pre-request | open |
| T-06 | Demo static tree serves live `seed.db` under pilot | B3 | 04 §1.5 | S | glob-derived forbidden list all 404 under pilot | open |
| T-07 | `REPO_BACKEND=postgres` on the pilot lockset bricks boot (`api.py:159` catches `NotImplementedError` only) | B2 | 08 §2 | M | `boot-matrix` postgres cells `up` | open |
| T-08 | `delete_student` misses 4 tables while documented as complete | B5 | 03 §2, 04 §7 | S | metadata-derived completeness test green | open |
| T-09 | Bulk upload blocks the event loop; live exam heartbeats stall | B4 | 07 §2 | S test / S fix | heartbeat < 250 ms during upload, all 5 handlers | open |

## P1 — before enabling the surface it guards

| ID | Gap | Blind spot | Doc | Effort | Acceptance | State |
|---|---|---|---|---|---|---|
| T-10 | Alembic has zero tests; schema built by `create_all` everywhere | B5 | 03 §1 | M | `compare_metadata` empty; round trip; single head | open |
| T-11 | Who provisions the pilot Postgres schema is undetermined | B2 | 08 §4 | S | one test encoding the answer | open |
| T-12 | G5/G6 machinery fix merged (`4de85b84`) but no post-fix committed `--strict` report; verdicts unconfirmed | — | 06 §2 | S (one manual run on the 12-core box) | committed report with G5/G6 verdicts | open |
| T-13 | G7 / G-P3 never returned a verdict (corpus uncommittable) | — | 06 §2 (plan 02) | L | first verdict, or `notes` says why not in CI | open |
| T-14 | `calibration-battery.yml` cannot finish (20+ CPU-h vs 30-min cap) and `continue-on-error` hides ERROR | — | 06 §7 | M | vector cache + per-gate matrix; step fails on ERROR; one completed weekly run | open |
| T-15 | No flag byte-identity matrix over all default-off flags | — | 08 §1 | M | snapshot + every table row covered | open |
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
| T-26 | Cross-tenant abuse suite and auth matrix absent | B3 | 04 §1, §2 | M | `pytest -m security` < 60 s, table-driven | open |
| T-27 | Secrets-never-leak test absent | — | 04 §5 | S | sentinel test over all failure paths | open |

## P2 — quality debt with a known failure class

| ID | Gap | Blind spot | Doc | Effort | Acceptance | State |
|---|---|---|---|---|---|---|
| T-28 | `features/tier8.py` has no test file; math unpinned | — | 02 §1.1 | S | `test_tier8.py` with oracles | open |
| T-29 | No cross-tier invariant suite (bounds, keys, quotes, length) | — | 02 §1.2 | S | `test_tier_invariants.py` | open |
| T-30 | No property tests on scoring monotonicity, sigma floor, energy conservation, action-mode ordering, shadow≡on | B1, B7 | 02 §2 | M | `test_scoring_properties.py` | open |
| T-31 | No mutation score; 99.6 % coverage unmeasured for assertion strength | B7 | 02 §5 | S setup | weekly kill rate on 6 modules; ≥ 80 % target | open |
| T-32 | `voice.py` redaction guarded by one leak test | — | 02 §3 | S | allowlist + forbidden-substring tests | open |
| T-33 | `tenancy_shim.py` untested | — | 02 §4 | S | round-trip + shape properties | open |
| T-34 | OpenAPI is determinism-checked, not snapshot-checked | — | 03 §4.1 | S | committed snapshot + update script | open |
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
| T-45 | Fusion six ≈ 8 min of CI | — | 09 §1.2 | M | file < 60 s | open |
| T-46 | Serial pytest job 15–18 min, 30-min cap already hit once | — | 09 §1.1 | M | 3 shards + combine, ≤ 10 min critical path | open |
| T-47 | Committed reports contradict themselves (`passed: true` + UNINFORMATIVE); CLAUDE.md cites G8 from no report | — | 06 §4 | S | `test_report_consistency.py` | open |
| T-48 | Cross-genre corpus copyright fence is only `.gitignore` lines (present on `main`; reverted once on a branch) | — | 06 §5 | S | `git ls-files` fence test | open |
| T-49 | Restore drill is a weekly human hour with no automated twin | — | 08 §6 | S | weekly workflow step | open |
| T-50 | Container image never built in CI | B2 | 08 §7 | S | container-smoke job | open |

## P3 — hygiene

| ID | Gap | Doc | Effort | Acceptance | State |
|---|---|---|---|---|---|
| T-51 | Five copies of `_postgres_available()` | 09 §2 | S | one session fixture | open |
| T-52 | No `--strict-markers`; new markers unregistered | 09 §3 | S | registered + strict | open |
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

**Phase A — make the blockers visible (1 week).** T-01 (test only), T-02 to
T-09 tests written red, T-26 skeleton, T-31 first mutation run. Output: a
`main` where the pilot blockers are red tests, not a private artifact.
Nothing here is a product fix.

**Phase B — infrastructure that Phase C needs (1 week).** T-46 shards, T-45
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
