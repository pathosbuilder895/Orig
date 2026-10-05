# Verification and remaining release gates

## Verified locally

- Refreshed GitHub main: `b29ae2a3`; integrated clean Claude launch branch `159d24ca`, which already included teacher dashboard `1ef85a22`, bulk deletion, student session revocation and static product-gate fixes.
- Research defaults corrected in `793e4506`: adaptive, style-authorship, fused and longitudinal features explicitly off for the classroom release.
- Selected full Python suite: **3,831 passed, 243 skipped, 12 deselected**, 595.82 seconds. Command: `python -m pytest tests/ validation/test_tier10_optional.py -m 'not blocker and not certification' -q`. This run predates final telemetry/frontend edits; focused tests cover those. Skips/exclusions are not passes.
- Separate real Postgres suite: **299 passed**, 3,784 deselected; local isolated Postgres 16 at port 55432. Command: `DATABASE_URL=<isolated-test-db> python -m pytest tests/ -m postgres -q`.
- Focused launch tests: 210 passed, 1 skipped. Later telemetry/static/deployment checks: 27 passed. API-client regression tests: 3 passed (401, server/network failure, genuine empty list).
- Frontend build succeeds; selected typefaces now served locally with their licenses instead of Google Fonts requests.
- Optional error reporting now removes exception values, breadcrumbs, arbitrary context and request URLs; tracing disabled. Regression tests place private prose in all those fields and confirm its removal.
- Browser rehearsal on fresh migrated Postgres: teacher sign-in → course → student invite → published two-question session → student login → two separate answers → reload → resume after deadline → confirmed submission → teacher reads both answers → saves fictional feedback → releases results → student sees the released mark. Invitation redemption was exercised through the API; new-password UI was not automated.
- Rehearsal discovered expired professor sign-in being shown as an empty submission list. Fixed: explicit load/sign-in error, retry control, no fake zero-submission state. Verified with the actually expired session, then signed in and retrieved the intact submission.
- Backup/restore drill: 21 fictional rows across 23 tables dumped and restored into a fresh migrated database, **restore parity: OK**. External bucket upload was not configured and is not claimed.

## Continuation pass, 4 October 2026 (branch `claude/professor-release-continuation`)

Six commits on top of handoff `e75a911c`; not yet pushed (local git/gh credentials invalid).

- **Known-red audit.** Of the four `blocker`/`certification` tests: T-05 Canvas SSRF was a live defect: staff-supplied Canvas URLs, Link-header pagination and attachment URLs (all carrying the bearer token) could target localhost, RFC-1918 or cloud-metadata hosts. Fixed: `live_import.ensure_public_url` requires https to a public host (`3db02679`). T-09 `.docx` upload was already fixed by `f09bb9c61` but still marked red, which would fail the known-red lane (`8047cde9`). The two remaining are cold-start FPR certification for Original scoring, which stays off for Bluebook tenants.
- **Lost-submission bug.** Launch-link (and LTI) pages never stored `original_products`, so the SPA assumed Original, posted the essay to product-gated `/students` routes, got 403 on all three seal attempts and left the submission unsealed. Fixed (`18ad123b`).
- **Pilot defaults.** New tenants registered on a real deploy without a product list now get Bluebook only (an unset list meant every product). Deferred `LTI_*` keys removed from the pilot blueprint and pinned by a test (`3fe507b2`).
- **Phone width (375×812), keyboard.** Landing page was 493px wide (fixed); exam briefing card squeezed to ~260px beside its back button (fixed); sealed receipt showed the sample course "Philosophy 301A" when a real exam's course label was blank (fixed) (`45bd112b`, `01b1d9b6`). Measured no horizontal overflow on: landing, sign-in, signup, invite/set-password, student home, briefing, exam, sealed receipt, all seven teacher tabs, submission reader, exam management. Inputs have associated labels; Tab order reaches the briefing and save controls with visible focus.
- **Browser rehearsal (local SQLite, fictional accounts, this worktree's code).** Invite link → new-password UI (mismatch rejected, then accepted) → student home → briefing → begin by keyboard → write → reload → resume with draft and server clock intact → seal → teacher reads, marks and saves feedback → releases → student API shows the mark. Network trace during the student session: only same-origin Bluebook routes and self-hosted fonts; no `/students` calls, no third-party hosts. Stored row holds text, word count, coarse timing and a warnings list: no keystroke data. A second professor workspace got 403/404 on every cross-tenant read/write; a student token got 403 on the staff list.
- **Exposure audit (read-only).** No keystroke data persisted for Bluebook-only tenants; Bluebook pages load no external hosts; Sentry scrubbed; SendGrid receives student email addresses and invite links only (needs a DPA). Docs/OpenAPI, legacy logins, `/auth/register` and LTI are closed or inert in pilot mode.
- Full CI command with local Postgres (`original_test` on port 55432) at `3fe507b2`: **3,923 passed, 10 skipped, 4 deselected, 163 setup errors**, coverage **99.35%** (floor 98), 14m35s. All 163 errors came from one cause: the `tests/security` `two_tenants` fixture created tenants without products, which the new Bluebook-only default rejects for Original routes. Fixed in `934082a2`; the security, lockdown, cutover and tenant suites then gave **360 passed** with Postgres. A full re-run at `934082a2` did **not** complete: the machine was saturated by unrelated processes (load average ~74) and the run was stopped at its 40-minute limit. Superseded: the full command was re-run at `e723a426` and is green (see "Finish pass, 2026-10-05").
- Known-red lane (`scripts/known_red.py`): exit 0; only T-01 cold-start FPR remains (2 expected failures, 1 accepted uninformative skip).

### Open decisions surfaced by this pass

- **Closed 2026-10-05: public signup is now invitation-only.** Was: `POST /auth/signup` lets anyone create a Bluebook workspace. Now: `SELF_SERVE_SIGNUP=0` refuses it with 403 and `/health` reports `signup_open`; operators invite professors with `scripts/invite_professor.py`. See "Finish pass, 2026-10-05".
- **Closed 2026-10-05: seal confirmation.** A manual "Seal & Submit" now asks for confirmation (`1eb9c194`); the confirm no longer records a false focus-loss warning (`700cfdac`). Whether the native dialog and fullscreen check behave in real Chrome is still a Part B4 check.
- **Closed 2026-10-05: backup encryption.** Off-box dumps are Fernet-encrypted client-side with `BACKUP_ENCRYPTION_KEY`, and the script refuses any configured upload without the key (`61127bdb`, `ccd86cf2`). Restore drill with the key ended `restore parity: OK` (23 tables, 21 rows). The destination still has to be disclosed in `privacy.html` (Part B2).
- **Closed 2026-10-05: anonymous gate.** Anonymous callers no longer reach Original routes on a real deploy via `demo`-environment tenants (`e6e8dc3e`); three pinned tests moved from 403 to 401 or were split, none weakened.
- **Closed 2026-10-05: keystroke fields.** Keystroke-derived data is now discarded at the API boundary while behavioral features are off (`ad2e1789`); the `revision_count` field is dropped from stored composition summaries.

## Not finished / not proved

1. Public deployment of this version, hosted migration and deployed end-to-end acceptance.
2. Phone-width visual verification and complete keyboard/accessibility audit of all rebuilt screens.
3. Production configuration and security exposure review, including excluded blocker/certification cases. Selected green tests do not clear those cases.
4. Real mail provider setup, verified sender, actual invitation/reset delivery, and professor support ownership.
5. Independent backup destination, credentials, retention and scheduled upload/restore verification.
6. Draft legal pages still contain entity/contact/provider placeholders. Do not invent these or remove the draft warning without owner/institution review.
7. End-to-end no-raw-keystroke verification across every remaining legacy endpoint, persisted rows, exports and backups.
8. Original baseline-policy/API reconciliation, real report-screen integration, licensed-model/IP review and student-population validity evidence. These remain separately gated; do not turn them on for first Bluebook use.
9. External professor pilot and institutional operating approval. No professors were contacted and no real student records were used.

## Hosting actually inspected, 4 October

Render browser is signed in. Workspace `tea-d816qvgg4nts7398dcr0` has:
- `original-demo`, service `srv-d8madcernols73ccbsn0`, deployed Python service in Ohio; current release not installed.
- `Originall`, service `srv-d826vjmk1jcs73e4rk70`, URL `https://originall.onrender.com`, free Docker service in Ohio; most recent deployment of main `b29ae2a3` failed. Settings still point at `./Dockerfile`, whereas the current stack is different. No database appeared in the inspected project/resource listing.

The existing free service is not the persistent Postgres pilot described by the repository blueprint. Its compute screen offers $7/month for 0.5 CPU/512 MB and $25/month for 1 CPU/2 GB, excluding database, storage and backup costs. No purchase or service change was made. Verify prices and resource requirements before approving new billing.

CLI publishing state: Render CLI unauthenticated; GitHub CLI token invalid; ordinary git push lacks credentials; SSH authentication unavailable. GitHub connector has repository admin/push access and can publish a snapshot branch. Do not expose secrets in this document.

## Finish pass, 2026-10-05

Branch `claude/professor-release-continuation`, HEAD `e723a426`, 20 commits on top of `c58dc0cb` (53 files, +1,591/-209). Not pushed: `gh` and `git push` are unauthenticated on this machine and need the owner's sign-in (plan Task 11 step 5).

### Owner decisions, 2026-10-05

1. **Terms checkbox on professor invites.** An invited professor must tick agreement to the terms when setting a password; the server refuses the first redemption without it (before the link is consumed) and records `terms_version` in the audit entry (`db603d49`).
2. **Reissue for unactivated professors.** `invite_professor.py` issues a fresh link (earlier links voided) to an existing professor who has not yet set a password, instead of refusing; activated accounts and other roles are still refused (`06a6bb0b`).
3. **Remove `original-demo` from the blueprint.** The pilot blueprint no longer creates the public Original demo (`5e9b9b15`); the fictional teacher walkthrough lives on its own static origin instead.

### Commits `c58dc0cb..e723a426`, by plan task

- **Task 1, signup switch:** `31ac5389` Add SELF_SERVE_SIGNUP switch and make the pilot invitation-only
- **Task 2, hide signup links:** `f88daf46` Hide signup links on invitation-only deploys and run unit tests in CI
- **Task 3, professor invitations:** `77708e39` Add operator invitation for professors on an invitation-only pilot
- **Task 4, seal confirmation:** `1eb9c194` Add a confirmation before a manual seal; `700cfdac` Fix the seal confirmation recording a false focus-loss warning
- **Out of plan:** `c95770d0` Fix e2e fixtures to request Original explicitly on pilot tenants
- **Task 5, Resume label:** `183c1d74` Fix the briefing button to say Resume when a sitting is running
- **Task 6, keystroke boundary:** `ad2e1789` Fix keystroke-derived data being accepted while behavioral features are off
- **Task 7, anonymous gate:** `e6e8dc3e` Fix anonymous access to Original routes via demo tenants on real deploys
- **Task 8, backup encryption:** `61127bdb` Add client-side encryption to off-box Postgres backups; `ccd86cf2` Fix backups uploading plaintext when the encryption key is unset
- **Task 9, fictional demo origin:** `e614d8c3` Add a separate static origin for the fictional professor demo
- **Task 10, legal guard:** `4bab58a3` Add a guard so legal pages cannot ship half-final; `2d1bab7b` Fix the legal release guard so a final version can pass
- **Final-review fixes:** `db603d49` Fix invited professors never accepting the terms; `06a6bb0b` Fix professor invitations so an expired link can be reissued; `5e9b9b15` Remove the Original public demo from the pilot blueprint; `53dc3116` Fix operator docs for the invitation-only pilot; `e659d396` Fix resume label after submission and pin backup dependencies; `e723a426` Fix fragile terms-error matching and pin invite edge cases

### Results at `e723a426`

Machine: 12 CPUs, shared with other sessions (1-minute load average 9 to 32 during the runs).

1. **Full CI command with Postgres 16** (`DATABASE_URL=postgresql://original:original@localhost:55432/original_test`, `pytest tests/ validation/test_tier10_optional.py -m "not blocker and not certification" -q --cov=original --cov-branch --cov-report=term:skip-covered --cov-fail-under=98`): **4,136 passed, 10 skipped, 4 deselected, 0 failed, 0 errors**, 133 warnings, 707.05 s (11m47s). Coverage **99.34%** (statement + branch; floor 98%). This replaces the unfinished re-run recorded under the 4 October pass.
2. **Known-red lane** (`scripts/known_red.py`): exit 0. Only T-01 (`tests/certification/test_cold_start_fpr.py`) is listed: `[3]` and `[5]` fail as expected, `[10]` is the accepted uninformative result.
3. **Playwright against a pilot-mode server** (`ORIGINAL_ENV=pilot`, `SELF_SERVE_SIGNUP` unset, `--skip-seed`, scratch SQLite database, `LOGIN_THROTTLE_MAX_ATTEMPTS=500`, port 8771; `npx playwright test --grep-invert "@serial-lockout"`, as CI runs it): **98 passed, 0 failed, 0 retried** (58.6 s). The `@serial-lockout` spec, which CI runs separately against a default-throttle server, was also run that way: **1 passed**. Bluebook node unit tests (`node --test unit/`): **8 passed**.
4. **Signup closed** (second server, `SELF_SERVE_SIGNUP=0`, otherwise the same environment):
   - `GET /health` returns `"environment":"pilot"` and `"signup_open":false`.
   - `POST /auth/signup` with a fictional body returns **403**: "Bluebook is invitation-only here. Ask the person who runs Bluebook for your institution to invite you."
   - `GET /bluebook/` returns 200 `text/html`.

All servers were stopped afterwards; the scratch databases live outside the repository.

### Open decisions from the continuation pass: status

Closed 2026-10-05: public signup (now invitation-only), seal confirmation, backup encryption, anonymous gate, keystroke fields. Each is marked in place above.

### Still open (owner/operator, Part B)

Plan: `docs/superpowers/plans/2026-10-04-professor-release-finish.md`, Part B. None of these is done, and none can be done from this checkout.

- **B1 Owner decisions and accounts:** hosting budget and region, fate of the old services (`Originall`, `original-demo`), SendGrid and its DPA, off-box backup bucket and `BACKUP_ENCRYPTION_KEY`, support contact and operator.
- **B2 Legal pages and institutional terms:** counsel fills the entity, region, storage-provider, retention, warranty and governing-law blanks; the institution's operating note; then the draft banner and version string are finalised (the guard from Task 10 enforces that).
- **B2 (counsel):** the student notice should say that sealed exams may be used as reference writing if the instructor's workspace uses Original (professor-approved baselines, 2026-10-05). The sentence to change is in `demo/legal/student-notice.html` (line 25, under "What Bluebook does not do"): "It does not analyse your writing style or compare it with your earlier work." That sentence becomes untrue for any workspace where Original is switched on, because its sealed exams, including ones sat before Original was switched on, can then be approved as reference writing and compared with later work. Counsel must make that passage conditional on Original; the code does not edit the legal page.
- **B3 Create the hosted pilot** from the merged commit, with fresh `SECRET_KEY` and `MAINTENANCE_TOKEN`, and confirm `/health` shows `signup_open:false` and the merged commit.
- **B4 Deployed acceptance** with fictional accounts: smoke test, full journey on phone and laptop, restart persistence, backup and encrypted restore drill, rollback rehearsal, uptime monitor. Includes the native confirm dialog and fullscreen check in real Chrome.
- **B5 Publish the fictional demo** (`bluebook-teacher-demo`): first blueprint sync also proves the static-site blueprint shape, which was written from knowledge only.
- **B6 Admit the first invited professors:** quickstart page, 1 to 3 invitations, watched first sessions.
- **Step 5 of this task:** push the branch and open the draft PR once the owner has run `gh auth login -h github.com`. Merge is the owner's action.

Deferred from review (minor, not blocking this pass):
- Relative-link warning wording when `PUBLIC_BASE_URL` lacks a scheme; reissue ignores `--name`.
- `docs/ARCHITECTURE.md:36`, `README.md:278` and `docs/DAY_ONE_CLASS.md:26` still mention `original-demo`.
- `NULL_MODEL=impostor` via `run.py --demo` on a pilot: no effect while Original is off; consider pinning it to none.
- SSRF DNS-rebinding hardening before Canvas is enabled.
- `composition_summary` should become an allowlist before Original is enabled.
- Pre-existing, order-dependent `tests/test_scoring_router_branches.py::test_tuned_thresholds_*` (also fails on the parent commit); it did not fail in this run.
