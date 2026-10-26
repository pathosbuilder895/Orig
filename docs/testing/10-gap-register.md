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

**Reconciliation 2026-09-16:** T-02/03/04/06/07/08/63/64/65/66 were closed **upstream** (post-#203 rebase base; blocker markers removed in `49af109d`) but this register was never updated — the rows read `red` while the code and tests were already green. Flipped to `green` here after verifying directly: `tests/security/{test_cross_tenant_read,test_id_minting,test_static_tree,test_unauthenticated_writes}.py` 52 passed, `test_lockset_imports.py` (T-07) 4 passed, `test_repository_contract.py` delete-completeness (T-08) 19 passed (postgres variants skip locally, run on CI). Only T-09 remains a genuine open blocker.

**Reconciliation 2026-10-11:** rows re-checked against the code and by re-running each cited test (local Postgres 16, commands and counts in the rows). T-11, T-12, T-16, T-20 and T-74 were already met on `main` and are now `green`; T-17 and T-24 are `partial`. Later the same day T-19 (#261), T-23 (#263) and T-14 (#264) were fixed and are `green`; T-75 is `partial` (#247). T-10's new `tests/test_alembic.py` found one real model/migration drift, fixed in the model the same day, so T-10 is `green`. T-18's deployment half landed with this update.

**Reconciliation 2026-10-26** (`claude/polish-sweep-2026-10-26`): T-25, T-53, T-54, T-56 and T-57 closed (rows say how). T-77 to T-80 are new, found by a read-only audit of the Collections routes and reported here rather than fixed; the same audit's findings that were fixed on that branch (students sitting or sealing exams the dashboard refuses, exam deletion leaving drafts behind, static gates bypassed by `//` paths) carry their tests in the commits.

---

## P0 — pilot go-live blockers

| ID | Gap | Blind spot | Doc | Effort | Acceptance | State |
|---|---|---|---|---|---|---|
| T-01 | Same-author FPR at N=3 baselines through the API (0.75–0.82 measured; `escalate`) | B1 | 06 §3, 02 §2.1 | M for the test; the fix is product work | `test_cold_start_fpr` green at N=3,5,10 on ≥8 committed authors — FIXED 2026-09-15 by de-saturating the deviation tanh (`scoring._DEVIATION_TANH_DIVISOR` 1.5→2.35): N=3 flagged 0/11 (0.000), N=5 0/11, N=10 uninformative (n=6<8); witness green (7/11 impostors flagged, impostor median dev 0.606 > genuine 0.477). Holdouts are a different section of the SAME work for 8 of 11 authors (`holdout_same_work_count`), so the cross-work claim is only partially measured, and the ABSOLUTE FPR is not validated on real student writing (shadow soak still owed); `tests/certification/test_cold_start_fpr.py` | green |
| T-02 | `GET /baseline-requests/pending` leaks cross-tenant emails and live magic links | B3 | 04 §1.1 | S | scoped test green — `tests/security/test_cross_tenant_read.py` | green |
| T-03 | Unauthenticated `POST /bluebook/submissions` | B3 | 04 §1.2 | S | route-table anonymous-write test green with allowlist — `tests/security/test_unauthenticated_writes.py` | green |
| T-04 | Turnitin import mints flat ids → unauthenticated essay reads | B3 | 04 §1.3 | S | every minted id tenant-prefixed; anonymous read refused — `tests/security/test_id_minting.py` | green |
| T-05 | SSRF via body-supplied Canvas URL | B3 | 04 §1.4 | S | private/loopback/metadata/file URLs refused pre-request — `tests/security/test_ssrf.py` (7 URLs) | fixed 2026-10-04 (`live_import.ensure_public_url`; also guards pagination + attachment URLs) |
| T-06 | Demo static tree serves live `seed.db` under pilot | B3 | 04 §1.5 | S | glob-derived forbidden list all 404 under pilot — `tests/security/test_static_tree.py` — `/seed.db` already gated; the Bluebook sourcemap is the red case | green |
| T-07 | `REPO_BACKEND=postgres` on the pilot lockset bricks boot (`api.py:159` catches `NotImplementedError` only) | B2 | 08 §2 | M | `boot-matrix` postgres cells `up` — `tests/config/test_lockset_imports.py` — blocked on `sqlalchemy` for both `REPO_BACKEND=postgres` and `REPO_SHADOW=postgres` | green |
| T-08 | `delete_student` misses 4 tables while documented as complete | B5 | 03 §2, 04 §7 | S | metadata-derived completeness test green — `tests/test_repository_contract.py::TestDeleteStudentCompleteness` — leaks `baseline_requests`, `bluebook_submissions`, `formation_pathways` on both backends; `bluebook_sessions` keys on `student_key`, not `student_id`, so it needs its own row/test | green |
| T-09 | Bulk upload blocks the event loop; live exam heartbeats stall | B4 | 07 §2 | S test / S fix | heartbeat dispatch < 250 ms during upload, all handlers: `tests/perf/test_event_loop_not_blocked.py` (unmarked regression guard; skips as uninformative on shared CI runners via `CI_RUNNER_SLOW`). Before the fix: upload-batch ~9 s late, turnitin-csv ~2.5 s, `.docx` upload ~1.2 s; `.txt` upload green; Canvas handlers deferred | fixed 2026-10-04 (all three upload handlers are threadpooled `def`; `/students/{id}/upload` runs in the threadpool) |
| T-66 | Anonymous flat-id `/students/{id}` writes and `DELETE` succeed on a real deploy (`assert_student_access` has no real-deploy branch for `tenant_of(id) is None`; `_is_staff_only_path` skips `/students/{id}/…`) | B3 | 04 §1.2 | S | `tests/security/test_unauthenticated_writes.py::test_flat_id_student_write_permitted` (8 routes) | green |
| T-67 | Batch upload (`POST /students/{id}/baseline/upload-batch`) accepted trusted provenance without auth — never called `_authorize_provenance` | B3 | threat-model §1, §6 | S | fixed 93dda512 (+ deep-review fixes): student `verified` request **stored** at `unverified`/0.5, staff not downgraded, downgrade audit-logged — `tests/test_students_baseline_batch.py::TestUploadBatchBranches`, `tests/security/test_unauthenticated_writes.py::test_batch_upload_trusted_provenance_not_self_assertable_on_real_deploy` | green |
| T-68 | `POST /students/{id}/request-baseline` was callable by a student session (no `_require_staff`) | B3 | threat-model §1, §6 | S | fixed 0f618fcf: student 403 before the Bbook-config check, staff passes — `tests/test_students_baseline_batch.py::TestRequestProctoredBaseline::test_student_token_refused`, `tests/security/test_unauthenticated_writes.py::test_request_baseline_requires_staff_on_real_deploy` | green |
| T-69 | Proctor attestation replayable — binds student+expiry only, 6 h any-text window | B3 | threat-model §1, §6 | M | fixed: single-use ledger (`consumed_attestations`) consumed on first successful admit only, per file in a batch too; `verify_proctor_attestation` gained an optional `exam` check (not yet wired to a call site — no route carries an exam id today) — `tests/test_student_auth.py`, `tests/test_baseline_provenance_authz.py` (replay, drift-hold-not-consumed, batch), `tests/test_repository_contract.py::TestDeleteStudentCompleteness` | green |

## P1 — before enabling the surface it guards

| ID | Gap | Blind spot | Doc | Effort | Acceptance | State |
|---|---|---|---|---|---|---|
| T-10 | Alembic has zero tests; schema built by `create_all` everywhere | B5 | 03 §1 | M | `compare_metadata` empty; round trip; single head: `tests/test_alembic.py` (2026-10-11, local Postgres 16: 3 passed; the two database tests skip as uninformative without Postgres). When it landed it found one real drift: migration `7c4d1e88a3b5` makes `bluebook_submissions.submission_uuid` unique with a partial unique index, the model declared a UNIQUE constraint, so every `create_all`-built Postgres test ran on a schema the pilot does not have. Fixed the same day in the model (`original/db/models/live.py` now declares the partial index; no migration needed); `KNOWN_DRIFT_T10` is empty, and `tests/test_repository_contract.py::TestBluebook::test_submission_uuid_is_unique_but_nulls_are_not` pins the uniqueness the seal-replay guard relies on, on both backends | green |
| T-11 | Who provisions the pilot Postgres schema is undetermined | B2 | 08 §4 | S | one test encoding the answer: Alembic. `render.yaml` runs `preDeployCommand: alembic upgrade head` before each deploy, and `requirements-pilot.lock.txt` (all the build installs) pins `alembic`: `tests/test_render_blueprint.py::test_pilot_runs_on_managed_postgres_and_migrates_before_each_deploy` (file: 14 passed 2026-10-11). `postgres_session.init_db()` (`create_all`) is tests and local dev only | green |
| T-12 | G5/G6 machinery fix merged (`4de85b84`) but no post-fix committed `--strict` report; verdicts unconfirmed | - | 06 §2 | S (one manual run on the 12-core box) | committed report with G5/G6 verdicts: `validation/calibration_report_2026-09-07.json` (commit `10b1de64`, measured at `642b1d08`, which contains `4de85b84`). G5 **pass**; G6 **uninformative**, not a pass (p_central floor 1/(n+1) = 0.200 at n=4, and the 0.02 threshold needs n>=49), so fairness parity is still unmeasured. The weekly CI battery on `main` agrees (run 37346489159, 2026-10-05: G5 PASS, G6 UNINFORMATIVE) | green |
| T-13 | G7 / G-P3 never returned a verdict (corpus uncommittable) | — | 06 §2 (plan 02) | L | first verdict, or `notes` says why not in CI | open |
| T-14 | `calibration-battery.yml` cannot finish (20+ CPU-h vs 30-min cap) and `continue-on-error` hides ERROR | - | 06 §7 | M | vector cache + per-gate matrix; step fails on ERROR; one completed weekly run. Done: `.github/workflows/calibration-battery.yml` restores and saves a feature-vector cache and splits the battery into six `--only` legs, merged by `scripts/merge_calibration_reports.py`; first complete run 34226363871 (2026-09-08), and every weekly run on `main` since has finished all legs (latest 37346489159, 2026-10-05, 3h09m, "missing legs: none"). Fail on ERROR (2026-10-11, `claude/battery-fail-on-error`): neither job is `continue-on-error` and the merge step lost its `|| true`. `--strict` exits 1 both for a fail/uninformative gate and on an uncaught exception, so each leg hands its report and the battery's exit status to `scripts/battery_gate.py`, which fails the leg only on ERROR: exit status other than 0/1 (124 = step `timeout`), no or unparseable report, a requested gate missing, a gate whose `detail` carries `machinery_error` (`_machinery_error_result`), or exit 1 with every gate passing. The merge job runs `merge_calibration_reports.py --fail-on-error-only` (missing leg or errored gate). A fail/uninformative verdict is a measurement: listed in the leg log, merged report and job summary, exit 0, so the 2026-10-05 run, where the g1, g3g4 and g6g7g8t legs exited 1 (G1, G1p, G3, G6, G7, T-1, T-3 not passing) and none crashed, would now be green on the same verdicts. `tests/test_battery_gate.py` 42 passed (fake reports, incl. one carrying the 2026-10-05 verdicts; pins the workflow wiring). Not yet proven on CI: no weekly run has happened since, so the first scheduled run after merge is the proof | green |
| T-15 | No flag byte-identity matrix over all default-off flags | — | 08 §1 | M | snapshot + every table row covered — `tests/config/test_flag_byte_identity.py` + `tests/snapshots/score_default{,_api}.json` via `scripts/update_score_snapshot.py`; 122 arms green, 13 `uninformative` with measured reasons (topic distance 0.16 ≤ 0.25, genre covered, pooled calibration unreachable); tier-10 forced to the TF-IDF backend so the snapshot reproduces off Apple MPS | green |
| T-16 | `SECRET_KEY` does not touch `deviation_score`; docs imply otherwise | - | 08 §1 | S | pinned row in the matrix: `tests/config/test_flag_byte_identity.py::test_api_secret_key_changes_nothing` (no API field moves, amplitude off or on) and `::test_unit_secret_key_touches_only_the_amplitude_path` (asserts `deviation_score` and the action unchanged, then skips as uninformative because the key moves `quantum_fidelity` by only 5.55e-16 on the fixed profile); `-k secret_key` 2026-10-11: 3 passed, 1 skipped | green |
| T-17 | Per-score `all_states()` scan is linear in store size; no cross-request bound | B4 | 07 §3 | S test / M fix | scan-count and sub-linear scaling tests. Partly fixed: the scan is tenant-scoped and run at most once per request (`original/routers/students_scoring.py` `_all_states()`, ~:110-125), and the tenant filter is contract-tested on both backends (`tests/test_repository_contract.py::TestGetOrCreateAndBasics::test_all_states_tenant_filter_excludes_other_tenants`, ~:996). Still linear in the tenant's size, no cross-request bound, and no scan-count or scaling test | partial |
| T-18 | Single-worker constraint unasserted; `_ENV_CACHE`, throttle, genre caches all assume it | B4 | 07 §4, 03 §2 | S | `render.yaml` worker assertion + cross-instance coherence test. Deployment half done: `tests/test_render_blueprint.py::test_pilot_runs_one_worker_on_one_instance` (no workers flag in the pilot start command, no `numInstances` or `scaling` on any service, no `WEB_CONCURRENCY`). The cross-instance coherence test (two `PostgresRepository` instances, 03 §2) is still absent | partial |
| T-19 | `/students/{id}/score` has no rate limit; `SECURITY_AUDIT.md` claims one (dormant stack) | B9 | 04 §3 | S test / S fix | limit test green; audit doc corrected: on a real deploy `POST /students/{id}/score` and `POST /me/work` share a per-caller budget (`SCORE_RATE_LIMIT_PER_MINUTE`, default 30 per rolling minute, keyed tenant:user, IP when anonymous) and answer 429 past it; `/me/work` checks it before its no-baseline fallback so a 429 is not reported as "no writing on file". `tests/test_score_rate_limit.py` (9 passed, 2026-10-11); `docs/SECURITY_AUDIT.md` §3 corrected. Single-worker memory, like the login throttle (T-18) | green |
| T-20 | Login throttle keys on `request.client.host`; behind Render's proxy may be one shared IP (REAUDIT #1) | B4 | 04 §3 | S | `X-Forwarded-For` test. Fixed in `e75a911c`: on a real deploy `_client_ip` reads the first `X-Forwarded-For` hop, and failures are also bucketed per email, so a spoofed header buys no extra guesses (`original/routers/_shared.py:275-290`): `tests/test_launch_hardening.py::test_distinct_forwarded_clients_have_separate_buckets`, `::test_rotating_forwarded_ip_cannot_bypass_per_email_bucket`, `::test_forwarded_header_ignored_off_real_deploy`, `::test_real_deploy_without_forwarded_header_uses_socket_peer` (file: 24 passed 2026-10-11) | green |
| T-21 | LTI `_JWKS_CACHE` has no TTL; key rotation breaks launches until restart | B6 | 04 §4, 07 §6 | S | rotation test green | open |
| T-22 | LTI replay within state TTL untested / unimplemented | B6 | 04 §4 | S | replay refused, or negative-space test | open |
| T-23 | `GUARD_DESTRUCTIVE=1` with non-real env should refuse boot (REAUDIT #5) | - | 04 §1.6, 08 §2 | S | Fixed 2026-10-11 (after that day's reconciliation above), branch `claude/guard-destructive-refuse-boot`: the `original/api.py` lifespan raises `RuntimeError` naming `GUARD_DESTRUCTIVE` when it is `1` and `ORIGINAL_ENV` is not pilot/staging/production (unset means demo), next to the SECRET_KEY refusal. `boot-matrix` cell `demo-guard-destructive` (`.github/workflows/boot-matrix.yml` ~:127-143) is now `today: refuse`, equal to `expect`. Local `scripts/boot_check.sh refuse refuse T-23 --log-fragment GUARD_DESTRUCTIVE -- ORIGINAL_ENV=demo GUARD_DESTRUCTIVE=1` observed `refuse (exit 3)`, the same with ORIGINAL_ENV unset, and `ORIGINAL_ENV=pilot GUARD_DESTRUCTIVE=1` still `up` (dev venv, not the pilot lockset; CI's cell runs the lockset). `tests/config/test_guard_destructive_boot.py`, 10 passed 2026-10-11: in-process lifespan refusal for demo/prod/dev, pilot/staging/production boot, and a subprocess check that ORIGINAL_ENV unset or demo refuses and pilot boots | green |
| T-24 | Calibration-lab Apply is a no-op (scoring reads `constants.ACTION_THRESHOLDS`) | - | 05 §3 | S test / M fix | e2e: rescored tier changes after Apply. Fixed in `69448fb2`: `original/routers/students_scoring.py` reads `_repo().get_active_tuned_thresholds()` (~:197) into `ScoringConfig`; `tests/test_scoring_router_branches.py::test_tuned_thresholds_absent_matches_the_static_action_thresholds` and `::test_tuned_thresholds_from_store_change_the_recommended_action` (~:197, ~:225; 2 passed 2026-10-11) write thresholds through `put_tuned_thresholds()`, the call the admin Apply route makes. No test drives the Apply route itself, and there is no browser e2e | partial |
| T-25 | `demo/app/` second frontend: no tests, no bundle staleness check, live/dormant unknown | B8 | 05 §2 | S decide / M | byte-check + smoke, or proven 404 under pilot. Decided: dormant, blocked on every deploy including the demo (`original/api.py` `_ALWAYS_BLOCKED_STATIC_PREFIXES`). 2026-10-26: `tests/security/test_static_tree.py::test_dormant_app_tree_404_in_{demo,pilot}` asserts every git-tracked file under `demo/app` (plus `/app`, `/app/`) 404s on both; the same branch fixed the static gates so `//app/index.html` and similar spellings no longer walk past them (`_static_lookup_path`) | green |
| T-26 | Cross-tenant abuse suite and auth matrix absent | B3 | 04 §1, §2 | M | `pytest tests/security -m "not blocker"` measured 78 s / 146 passed on 2026-09-08 (target < 60 s not met; `two_tenants` is function-scoped), table-driven — `tests/security/` package + `test_auth_matrix.py` (96 cells observed and pinned) | partial |
| T-27 | Secrets-never-leak test absent | — | 04 §5 | S | sentinel test over all failure paths | open |
| T-77 | The seal stores the integrity reading the student's browser sends (`stylometric`, `ai_score`, `status` on `POST /bluebook/submissions`, `original/routers/bluebook.py`): the SPA scores client-side through `/students/{id}/score` and posts the result, so a hand-made seal can set its own reading. Inert while every pilot workspace is Bluebook-only (`has_original` drops the scores), live once Original is on for a teacher | B1 | threat-model §1 | M | the seal computes or verifies the reading server-side and ignores the client's; test that a student-supplied reading is not stored | open |
| T-63 | `GET /admin/audit` has no tenant filter; B staff read A's audit rows | B3 | 04 §1.1 | S | `tests/security/test_cross_tenant_read.py::test_admin_audit_scoped` | green |
| T-64 | Anonymous `POST /auth/register` accepted (`_require_guard` only) | B3 | 04 §1.2 | S | `tests/security/test_unauthenticated_writes.py` | green |
| T-65 | Anonymous `POST /bluebook/exams/{id}/session` accepted | B3 | 04 §1.2 | S | `tests/security/test_unauthenticated_writes.py` | green |
| T-70 | No baseline-consistency / σ-inflation surfacing (obfuscated, outsourced, or poisoned baselines pass unremarked) | B1 | threat-model §1, §5.4 | M | `baseline_integrity` attached report-only; G-A5/G-A6 measured — `tests/test_baseline_integrity.py` | open |
| T-71 | Imitation of own baselines undetected (too-central band shipped off, paraphrase-defeatable) | B1 | threat-model §1 | L | G-A2 measured on committed corpus | open |
| T-72 | Paraphrase / round-trip laundering of AI or purchased text undetected (32% paraphrased-AI recall) | B1 | threat-model §1 | L | G-A3 measured on cached LLM corpus | open |
| T-73 | Peer-imitation / collusion undetectable — null pool is aggregate, no nearest-peer attribution | B1 | threat-model §1, §8 | L | G-A4 measured | open |
| T-74 | Raw per-key keystroke timing stored at rest, uninventoried (inside the `keystroke_data` blob, persisted at `original/store.py:788` and `original/postgres_repository.py:183`); capture should be macro-only | B3 | threat-model §5.3, ADR-010 | M | purge script run; inventory row; capture macro-only. Done: `keystrokes`/`pauses` arrays are stripped before persisting (`original/routers/students_baseline.py::_strip_raw_keystroke_arrays`, ~:30, applied ~:177); inventory row and retirement note in `docs/data_inventory.md` (~:240-255); `scripts/purge_keystroke_blobs.py` with `tests/test_purge_keystroke_blobs.py` (18 passed 2026-10-11, local Postgres 16). Caveat: the purge script has never been run against pilot data, and the pilot holds none (0 students, `/health` 2026-10-08) | green |
| T-75 | No minimum-baseline policy before the primary score (cold-start FPR ~0.9 at N=3) | B1 | threat-model §1, T-01 | M | `baseline_readiness` reported; G-A1 measured at N∈{3,5,10}. Partial (2026-10-11): every score response carries `baseline_integrity.readiness` (`thin` below 3 contributing samples), and Bluebook's seal records such a sitting INCONCLUSIVE with no score, never "worth a look" (#247; `demo/bluebook/unit/thin-baseline.test.mjs`, `e2e/thin-baseline.spec.mjs`). Still open: the score route itself returns a recommendation at N=1-2 and the classic analysis page shows it; G-A1 not measured. T-01's fix measured 0/11 at N=3, so the ~0.9 in the title is the pre-fix figure | partial |

## P2 — quality debt with a known failure class

| ID | Gap | Blind spot | Doc | Effort | Acceptance | State |
|---|---|---|---|---|---|---|
| T-76 | `PostgresRepository.all_states()` fails closed-but-silent (returns `[]`) on any scan error, indistinguishable from a genuinely empty/clean result — surfaced by `scripts/purge_keystroke_blobs.py`'s dry-run report, but the underlying gap is in the repository layer, not the script | B1 | threat-model §1 (T-74 review) | S | a scan failure raises or is otherwise distinguishable from zero rows in a maintenance-tooling read path | open |
| T-78 | Adding an invited (not yet activated) student to a second course voids the first course's set-password link: `invites.issue` voids every unredeemed invite for the user (`original/invites.py`) and `roster_add` issues one per course; `roster_remove` and an anonymous password-reset request void pending links the same way. The first link then fails as "invalid, expired, or already used" while that roster still shows the student invited | B5 | — | S | decide the policy (one live link per account, shown on every roster that holds the student, or one per course); test redeeming the first link after a second course add | open |
| T-79 | A password reset or change does not end existing sessions (student sessions last 7 days, `original/student_auth.py`; staff tokens are not re-checked), and a reset link lives as long as an invite (14 days, or forever with `INVITE_NO_EXPIRY=1`, `original/invites.py`) | B3 | 04 §3 | M | sessions issued before a reset are refused after it; reset links have their own short expiry | open |
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
| T-53 | `serial-lockout.yml` header claims the spec "ran nowhere"; stale since `7bb2c925` | 01 §2 | S | comment corrected. Corrected 2026-10-26: the header now says `test.yml`'s bundle-e2e also runs the spec on every push and PR. The same change fixed why every weekly run since 2026-09-14 failed: the Playwright step did not pass `MAINTENANCE_TOKEN`, so `registerStaff()` got 403 from `/auth/register` in fixture setup (reproduced locally, then green) | green |
| T-54 | `OPS_RUNBOOK.md` mentions 5 xfail'd v1 tests that no longer exist; `xfail` policy unenforced | 09 §4 | S | `test_no_xfail.py` + runbook line removed. Done 2026-10-26: `tests/test_no_xfail.py` (AST scan of `tests/` and `validation/`, with self-checks for each form) and the runbook line removed | green |
| T-55 | CLAUDE.md carries counts/timings that go stale monthly | 09 §7 | S | trimmed to commands + link | open |
| T-56 | `.env.example` vs code flag set unchecked | 08 §3 | S | consistency test. Done 2026-10-26: `tests/test_env_example.py` (every CLAUDE.md flag row in `.env.example`, two pinned exemptions; every `.env.example` name a string literal under `original/`, `scripts/` or `run.py`). It found 10 missing rows and 5 names nothing reads (`ADMIN_EMAIL`, `ADMIN_PASSWORD`, `LTI_PRIVATE_KEY_PEM`, `TOPIC_INFLATE_GAIN`, `SENTRY_TRACES_SAMPLE_RATE`), all fixed | green |
| T-57 | `VERIFICATION_MIN_WORDS` looks like a rule, enforces nothing | 06 §5 | S | wired or docstring says unwired. The docstring route: `validation/corpus_policy.py` says no runner calls `check_verification_pool()` yet, and CLAUDE.md's Validation Layer section says the floor is declared with no production caller (checked 2026-10-26) | green |
| T-58 | `changed_tests.py` never selects HTTP-driven tests for router changes | 09 §6 | S | router → security/perf mapping pinned | open |
| T-59 | No WebKit or mobile Playwright project | 05 §6 | S | smoke + exam-flow on WebKit; `parked.html` on mobile | open |
| T-60 | Visual regression absent (WS-9 gate now satisfied) | 05 §5 | S | 3 screens, non-blocking | open |
| T-61 | `professor_narrative.py` content obligations unasserted; `_FEATURE_PLAIN` key drift | 02 §6 | S | obligations + key-set test | open |
| T-62 | `scripts/reset_demo_data.py` (destructive, runbook-mandated) has no test | 01 §4 | S | dry-run + apply test on a tmp DB | open |
| T-80 | An integer beyond the column type 500s instead of a 4xx: `word_count` on the seal or `client_saved_at` on a draft PUT above 2^63 raises `OverflowError` on SQLite; `word_count`, `time_min`, `duration`, `min_words`, `max_words` are int4 on Postgres, so above 2^31-1 they should raise `DataError` (reasoned from `original/db/models/live.py`, not run) | 03 §4.2 | S | bounded `Field(le=...)` on those request fields; route-table malformed-body test (T-35) covers it | open |

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
