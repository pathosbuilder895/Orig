# Original + Bluebook: professor-access release plan

Planning snapshot: 3 October 2026. This is a proposed execution plan, not a deployment or readiness claim.

## Outcome and scope

A professor receives one HTTPS address, signs into a private workspace, creates a class, invites students, runs a writing session, and reads or exports confirmed submissions. The selected Claude Design teacher interface becomes the primary frontend. Original later adds optional, report-only writing comparisons within that same experience.

Deliver three distinct milestones: a shareable fictional demonstration; an invitation-only Bluebook classroom pilot; an independently gated Original comparison pilot. Do not make classroom writing depend on research readiness.

Preserve text plus coarse session timing only, no keystroke biometrics, no external student-text inference, feature flags off by default, and consistency-not-accusation language. Canvas/LTI, billing automation, longitudinal voice graphics, and a second Next.js deployment are out of scope for this release.

## Starting evidence

- Teacher interface and portable fictional demo implemented on `codex/teacher-dashboard-demo-live`, commit `1ef85a2206205394456d69656bcbf5f35aaa3660`, based on `150316c1`.
- Local course/session loading and two-question session creation verified. September 30 verification: 147 selected tests passed; blocker/certification suites were excluded. Mobile visual verification is outstanding.
- Existing embedded Bluebook has account, course, invitation, exam, submission, and export flows. These are candidates for reuse, not proof of deployed correctness.
- Original analysis exists in backend/older screens. Selected design is not yet a complete frontend for its real results.
- Local preview uses disposable storage. No new professor-accessible release has been verified or deployed by this work.
- Existing Render configuration is a starting artifact only. It includes adaptive flags enabled, deferred LTI configuration, and an ephemeral demo service. It must be reconciled with this release policy before reuse. Source comments do not prove current hosting state.

## Target structure

Separate demo and live origins. Demo holds only clearly fictional, resettable records and never receives credentials or classroom data. The live origin serves the teacher/student frontend and authenticated FastAPI APIs together. Use the newer embedded Bluebook as the release candidate; keep `bbook_client.py` optional and inactive unless an explicit external integration is needed.

The live deployment owns account/session services, workspace-scoped courses, exams and submissions, persistent storage, backups, and later the optional Original service. No third-party analytics, fonts, logging, or inference may transmit student prose; self-host frontend assets for the live release. Hosting region, institutional requirements, and actual data flows define the deployment boundary.

Choose one supported production storage path after checking repository parity and existing hosting: provisionally persistent SQLite for a small single-instance pilot if concurrency, backup/restore and restart tests pass; otherwise complete PostgreSQL parity first. Do not add a database migration purely for appearance, or assume an ephemeral filesystem is durable.

## Dependency-ordered work packages

| Phase | Work | Exit evidence |
|---|---|---|
| 1. Establish the release baseline | Refresh GitHub/local branch inventory; preserve unique Claude work; compare current main with the implementation commit; assemble one reviewable release branch. Inspect actual hosting without changing it. Record routes, dependencies, flags and storage choice. | Fresh checkout builds and boots; commit identified; no overwritten work; a route-to-API map and documented deployment configuration. |
| 2. Make the demo shareable | Publish the portable demo to a separate static origin when hosting is selected. Check professor walkthrough, reset, accessibility and phone layout. Label reports as examples. | A link opens on a separate device without login or local servers; no live API calls or saved student records. This can proceed alongside phases 3–4 after phase 1. |
| 3. Close account and data-boundary gaps | Verify workspace/role isolation, invitation expiry/reuse, recovery, student session revocation, Bluebook-only erasure and mixed-account deletion. Trace browser/schema/log/storage/export fields; reject legacy raw-key payloads. Review known failing security cases against exposed routes; disable unused routes or fix them. | Cross-workspace reads/writes denied; deleted/revoked users cannot write using old tokens; no keystroke payloads persist; relevant security failures resolved rather than hidden by test exclusions. |
| 4. Finish the classroom workflow | Unify course, roster, invitation, exam, writing, submission reader and export screens under the chosen design. Finish empty/error/loading states, keyboard navigation and mobile layout. Verify time windows, approved extra time, reconnect/retry and clear save receipts. Keep the existing single-prompt representation unless multi-question answers truly require a schema change. | Two separate users/devices complete teacher → invitation → student writing → confirmed submission → teacher review/export. Reload/network interruption, expiry and duplicate submit scenarios preserve correct work and ownership. |
| 5. Deploy a durable staging release | Configure stable secrets, HTTPS, restricted origins, production auth, flags off, migrations, persistent storage and safe logs. Keep synthetic fixtures out of the live service. Establish backup/restore, rollback and maintenance procedures; prevent mid-exam automatic deployments. | Accounts and submissions survive restart/deploy; backup restored into an isolated environment; rollback rehearsed; route exposure and flag behavior verified on deployed configuration. |
| 6. Admit a small Bluebook pilot | Prepare professor quick-start and support contact; define retention, allowed use and institution-specific operating terms with the responsible institution. Begin with 1–3 invited professors and synthetic rehearsal, then approved classroom use. | Professors complete the workflow without developer intervention; every acknowledged submission is recoverable and visible only to authorized people; support/incident owner assigned. Stop intake if privacy boundaries fail or acknowledged work is lost. |
| 7. Connect Original to real evidence | Define submission → eligible sample → teacher-approved baseline transitions and versioning. Reconcile existing consistency API work. Wire real profile, comparison and report views to authenticated APIs with reason codes, uncertainty and insufficient-evidence states. Keep baseline updates separate from comparison execution. | Bluebook works with Original disabled. Only approved samples enter baselines; duplicate/replayed samples rejected; reports preserve source/model/policy versions and do not alter recommendations or accuse students. |
| 8. Gate the Original pilot separately | Define and evaluate the narrow writing-consistency claim with appropriately authorized student data, held-out evaluation and subgroup/context checks. Review relevant model licenses and IP questions against the actual implementation. Establish human review and student explanation/correction procedures. | A written research and institutional go/no-go identifies supported claims, limitations and stop rules. Demonstration scores and selected engineering tests are never substituted for model validity. |

Phases 3 and 4 may overlap after baseline selection, but neither is optional before live classroom use. Phase 5 staging work can begin with synthetic data while remaining release blockers are fixed. Original research may proceed independently, but student-facing analysis stays disabled until its own gates pass.

## Professor-facing navigation

Overview: actual courses, sessions and submissions, with clear next actions.

Courses: class setup, roster and student invitations.

Bluebook: session setup, published status, student entry and writing window.

Submissions: confirmed text, course/student/session context, review and export.

Original reports: visible only when enabled and supported; approved baselines, comparison evidence and inconclusive results. No invented confidence percentages, typing rhythm, automatic misconduct verdicts, or demo/live fallback mixing.

## Release decisions and owners

Engineering owns baseline integration, APIs, tests and release artifacts. A named operator owns hosting, recovery and support. The product owner chooses domain, hosting budget, pilot professors and interface acceptance. The institution and its responsible privacy/legal staff determine classroom data terms and allowed use. Research owns comparison validity; UI completion cannot approve that claim.

Use existing hosting if inspection shows it is suitable; do not purchase a plan or commit to a region before requirements are known. Keep legal/IP conclusions as open reviews, not inferred clearance. Do not ask professors to operate a developer laptop, terminal or disposable preview database.

## Scheduling and delivery cadence

Start with phase 1, then provide a measured engineering estimate based on integration conflicts, actual deployment access, and the severity of known failing tests. A launch date now would be unsupported. Track progress through the three visible milestones instead: shareable demo, usable Bluebook pilot, optional Original pilot.

At each phase handoff deliver the exact commit, working preview or staging link, tested journeys, unresolved blockers and next decision. Keep production changes separate from planning. This document authorizes no new expenditure, external outreach or deployment by itself.

## First execution batch

1. Compare current GitHub main and Claude branches against the teacher-dashboard commit; preserve changes and select the integration base.
2. Inventory actual hosting and its current deployed revision, storage, routes and flags without exposing secrets.
3. Build the screen/API checklist and run teacher/student journeys on a fresh isolated database.
4. Turn confirmed failures into a short ordered backlog, prioritizing account isolation, stale tokens, erasure and save reliability.
5. Complete phone/keyboard checks and prepare the fictional demo for its own shareable address.

## Sources and uncertainty

- [Teacher dashboard implementation](Teacher-Dashboard-Implementation.md): exact implementation and verification scope.
- [Project knowledge base](Original-Bluebook-Knowledge-Base.md): architecture, branch reconciliation, risks and historical evidence; September 29 snapshot requiring refresh before integration.
- `work/teacher-dashboard/render.yaml`: inspected deployment blueprint, not evidence that its described services are currently deployed.

Unknown until execution: current remote changes, live hosting access/configuration, which historical defects remain present, production storage parity, institutional deployment requirements, and valid student-population comparison performance.
