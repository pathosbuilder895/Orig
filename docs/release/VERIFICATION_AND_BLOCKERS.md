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
- Full CI command with local Postgres (`original_test` on port 55432) at `3fe507b2`: **3,923 passed, 10 skipped, 4 deselected, 163 setup errors**, coverage **99.35%** (floor 98), 14m35s. All 163 errors came from one cause: the `tests/security` `two_tenants` fixture created tenants without products, which the new Bluebook-only default rejects for Original routes. Fixed in `934082a2`; the security, lockdown, cutover and tenant suites then gave **360 passed** with Postgres. A full re-run at `934082a2` did **not** complete: the machine was saturated by unrelated processes (load average ~74) and the run was stopped at its 40-minute limit. Re-run the full command before merging.
- Known-red lane (`scripts/known_red.py`): exit 0; only T-01 cold-start FPR remains (2 expected failures, 1 accepted uninformative skip).

### Open decisions surfaced by this pass

- **Public signup is open.** `POST /auth/signup` lets anyone create a Bluebook workspace; the plan calls for an invitation-only pilot. Needs an owner decision (and, if invitation-only, a `SELF_SERVE_SIGNUP` flag plus an operator onboarding path).
- **Seal has no confirmation.** One tap on "Seal & Submit" ends the exam, which is risky on phones. Adding a confirm step touches six Playwright specs.
- **Off-box backups are unencrypted** by the script; rely on bucket-side encryption or add client-side encryption, and disclose the destination.
- Anonymous principals keep an operator role exempt from the product gate; harmless unless an operator registers a `demo`-environment tenant on a real deploy. Consider exempting only non-demo super roles.
- Bluebook request models ignore (not reject) unknown fields such as `keystroke_data`; nothing is stored, but `extra="forbid"` would surface misbehaving clients.

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
