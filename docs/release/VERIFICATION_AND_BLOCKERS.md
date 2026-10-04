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
