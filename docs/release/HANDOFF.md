# Original + Bluebook release handoff

Updated 4 October 2026. **Not deployed; not yet approved for classroom data.**

## Start here

- [Release plan](PROFESSOR_ACCESS_PLAN.md): scope, dependency order, acceptance gates.
- [Verified progress and blockers](VERIFICATION_AND_BLOCKERS.md): what was actually tested and what remains.
- [Continuation instructions](CONTINUE_RELEASE.md): exact starting point and next steps.
- [Deployment checklist](../BLUEBOOK_LAUNCH_CHECKLIST.md): inherited setup instructions; verify provider prices and replace its unsupported “everything in code is done” claim with the evidence register here.

The selected Claude Design teacher dashboard is now React code wired to the embedded FastAPI Bluebook APIs. The separate professor demo contains fictional records. The newer Claude launch work adds student invitations, per-question answers, grading/release, Postgres schema migrations and backup tooling.

The release branch is a consolidated candidate, not a minimal patch: it includes earlier local Claude work absent from GitHub main. Review the full comparison, especially research code. Research features stay off in the classroom configuration. Do not enable Original comparisons merely because application tests pass.

## User requirements

Use the selected scholarly teacher design for Original/Bluebook. Ship a professor-accessible standalone workflow. No typing rhythm or keystroke biometrics; text and coarse session information only. No student prose to external inference or telemetry. Report-only, consistency-not-accusation posture. Canvas/LTI implementation deferred. Keep the Python/FastAPI stack and embedded Bluebook; optional older Next.js adapter is not a release dependency.

## Current local workspace

`/Users/andrew/Documents/Codex/2026-09-29/referenced-chatgpt-conversation-this-is-an/work/teacher-dashboard`

Branch: `codex/teacher-dashboard-demo-live`. The GitHub handoff snapshot, if created, is named `codex/professor-release-handoff` and contains the same file tree with consolidated history. Preserve other Claude worktrees.

Local rehearsal: `http://127.0.0.1:8752/bluebook/`. This is fictional test data, not a public deployment. Do not distribute its address as the professor release.
