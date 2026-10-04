# Continue toward the first usable release

## Scope

Finish the plan, starting with a standalone Bluebook classroom release and a separate fictional professor demo. Original comparisons follow their own evidence gates. This handoff is not a launch certificate.

## Working commands

On Andrew’s computer use `/Users/andrew/Desktop/Original/.venv/bin/python`, as required by CLAUDE.md. Read AGENTS.md and CLAUDE.md before editing. Never restart existing dev servers without permission.

```sh
cd demo/bluebook
npm ci
npm run build
node --test unit/api-client.test.mjs
```

Commit built JS/CSS/maps and local fonts: the hosted Python service has no Node build step. Run Python tests using the interpreter above. For Postgres tests, provide a dedicated disposable database; never point tests at production.

## Next execution order

1. Checkout the handoff branch and review its full diff against main. It consolidates local work; avoid merging unrelated open PRs (especially old keystroke work) automatically.
2. Finish mobile/keyboard checks and fix remaining loading/error states. Preserve actual server receipts and the draft-recovery path.
3. Audit excluded security cases and unused Canvas/LTI/legacy API exposure; either fix exposed defects or disable the unused surface without claiming the whole suite is green.
4. Choose hosting with the owner’s spending limit and region requirements. Inspect existing Render state before changing it. The inspected old Docker service is failed and free; do not assume the blueprint exists live.
5. Prepare a dedicated pilot service, stable secrets, production auth, managed persistent database, migrations, backups and mail. Use a separate static origin for the fictional demo. Keep research flags and third-party tracing off.
6. Resolve legal-page placeholders and support contact with the owner. Establish retention/deletion and institutional operating boundaries before accepting classroom data.
7. Publish the reviewable branch/PR, verify CI and deploy the exact approved commit. Avoid automatic deployments during writing sessions. No direct main push is necessary.
8. Run `python -m scripts.pilot_smoke_test --base-url https://<actual-host> --bluebook`, then teacher/student UI flows using fictional accounts, actual mail, submission/reload, grading and released results. Confirm deployed data survives restart and exercise backup restore separately.
9. Provide professors a stable HTTPS link and short instructions only after these gates pass. Start with a small invited pilot; no outreach has been authorized by this handoff.
10. Complete the Original baseline/report integration and research/institutional gates from the plan without narrowing the claim to a demo score.

## Local rehearsal resources

Docker container `codex-bluebook-release-postgres` listens only on localhost port 55432. Test-only role/database credentials are the repository’s standard `original` fixture values. Databases: `original_test` (test suite), `bluebook_release_preview` (fictional UI rehearsal), `bluebook_release_restore` (restore drill). These are not production credentials or assets.

Preview server port 8752 was launched against the rehearsal database in pilot mode. It has a process-random signing key and is intentionally not a durable deployment configuration. Existing older previews on other ports must not be mistaken for this release.

## Completion standard

A public link alone is insufficient. Prove professor onboarding, invitations, student access, saved work, review/export, recovery, tenant isolation and operation on persistent hosting. Keep demo fiction separate from classroom records. Record exact commits, tests, exclusions and hosting state. If external prerequisites remain, state them explicitly rather than calling the release finished.
