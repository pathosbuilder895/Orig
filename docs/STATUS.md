# Original + Bluebook: Current Status

*Last updated: 2026-10-08*

**Quick ref:** This file tracks what's deployed, what's in flight, what's blocked, and what's next. Every AI tool should update this at the end of a session.

---

## Current Phase

**Invitation-only Bluebook pilot for independent teachers.** Start with 1–3 teachers, possibly growing to a few dozen. No public signup (`SELF_SERVE_SIGNUP=0`).

Original is off by default. It may be switched on per workspace with testing-phase warnings.

Engineering for this phase is merged (PRs #226, #227, 5 Oct 2026). The pilot and the fictional demo are deployed (since 6 Oct 2026); no teacher is invited yet. See Deployed.

See `docs/NORTH_STAR.md` for phase goals and non-negotiables.

---

## Deployed

**The pilot and the fictional demo are live on Render (since 6 Oct 2026). No teacher has been invited yet.**

| Service | URL | State (checked 2026-10-08) |
|---------|-----|----------------------------|
| `original-pilot` | https://original-pilot.onrender.com | `/health` ok; backend `postgres`; environment `pilot`; `signup_open: false`; 0 students; commit `00247875` |
| `bluebook-teacher-demo` | https://bluebook-teacher-demo.onrender.com | Serves the fictional teacher demo; Codex reported it at commit `2c2d62d2` |

- **The pilot runs a pre-merge build, not `main`.** `00247875` sits on `codex/bluebook-pilot-c962a917`. That work reached `main` as the squash-merged #235, so `main` has the same code plus everything merged since, including the T-01 scoring fix and the Canvas SSRF fixes. Neither has an effect while Original and Canvas are off. Redeploy from `main` before the first teacher is invited.
- **Render probably deploys from `codex/bluebook-pilot-c962a917`**: both live commits are on it (and on `codex/pilot-secrets`). Unconfirmed, because the Render CLI on the dev machine is not logged in. Point the services at `main` in the Render dashboard before deleting either branch, or future deploys lose their source.
- Codex reported on 6 Oct that the managed Postgres migrations succeeded and 12 public smoke checks passed. The full deployed acceptance run (B4) has not happened.
- The old free service `Originall` (`https://originall.onrender.com`) did not respond within 70 s on 2026-10-08. Its fate is part of B1.
- Intended hosting: Render Hobby following the `render.yaml` blueprint, Postgres 16, Oregon region. The plan and budget are not yet signed off.

---

## In Flight

### Open PRs

| PR | Branch | Owner | Status | Notes |
|----|--------|-------|--------|-------|
| [#228](https://github.com/pathosbuilder895/Orig/pull/228) | `claude/original-landing-integration-d19b53` | Claude Code (Task B) | Open; CI green; **merge conflicts with main** | Landing page, reworked 7 Oct to NORTH_STAR: removed the invented-data dashboard mock and the unlicensed and AI-generated images. Includes ADR-011. Needs a rebase, then Andrew's call on hosting claims, final images and footer. |

**Closed 2026-10-08:** [#160](https://github.com/pathosbuilder895/Orig/pull/160) and [#225](https://github.com/pathosbuilder895/Orig/pull/225), keystroke work ruled out by NORTH_STAR rule 6 and ADR-010. Their branches are kept. `sprint/lane-a-claude` (#225) holds `62f2152e`, the LTI key rotation made after the key leak. `main` has not picked it up: `scripts/o1_golive_check.py` and its test still expect `7939c6c8a6f9a736`, the leaked key's id. Port the rotation when Canvas/LTI comes back; never go back to the old key.

### Branches Without PRs

| Branch | Owner | Status | Notes |
|--------|-------|--------|-------|
| `codex/bluebook-pilot-c962a917` | Codex | Superseded by #235 (merged 2026-10-08) | Its only difference from `main` is an older `render.yaml` comment. Both live deploys came from it, so delete it (and the merged `codex/pilot-secrets`) only after the Render services point at `main`. |

### Dependabot PRs

24 open dependabot PRs for dependencies. Several are major version bumps (vitest 5, eslint 10, ruff 0.16, pydantic 2.13). 10 target `/app` directory (re-scoped legacy tree per ADR-008-ws8) — decide whether to merge these or configure dependabot to ignore `/app`.

---

## Blockers

From `docs/release/VERIFICATION_AND_BLOCKERS.md` "Still open":

### Owner/Operator Tasks (B1–B6)

1. **Hosting and budget sign-off:** the services already run on Render, but the plan, instance size and Postgres plan are not signed off. Research is in `docs/research/2026-10-07-hosting-and-storage.md`. Awaiting Andrew's approval.
2. **Email provider** — SendGrid Essentials ~$19.95/mo. Sending domain must be verified. Awaiting Andrew's setup.
3. **Encrypted off-box backups** — R2 or B2 bucket in separate account, Fernet key stored offline. Awaiting Andrew's setup.
4. **Legal pages final** — Privacy policy, terms, student notice. Draft placeholders exist with `[ENTITY]`, `[CONTACT]`, `[PROVIDER]` blanks. Counsel needs to approve terms and data agreement for teachers without school contracts. See NORTH_STAR open questions.
5. **Deployed acceptance testing:** the full B4 run on the live instance (journey on phone and laptop, restart persistence, encrypted restore drill, rollback, uptime monitor). Only Codex's 12 public smoke checks have run (6 Oct).
6. **Publishing fictional demo:** done, live since 6 Oct at `bluebook-teacher-demo.onrender.com`. `VERIFICATION_AND_BLOCKERS.md` still lists B3 (create the hosted pilot) and B5 (publish the demo) as not done; that file belongs to Task C, which marks them done on `claude/independent-teacher-wording`.
7. **First teacher invites** — 1–3 teachers. Use `scripts/invite_professor.py`. Pilot stays invitation-only.

### Technical Open Items

From `docs/testing/10-gap-register.md` (rows re-checked 2026-10-11):
- **T-10** (green): `tests/test_alembic.py` holds the model to the migrations (single head, `compare_metadata` empty, round trip). It found one real drift on `bluebook_submissions.submission_uuid` (partial unique index in the migration, UNIQUE constraint in the model), fixed in the model.
- **T-13**: G7 (cross-topic false-positive gate) has never returned a verdict.
- **T-14** (partial): the weekly calibration battery now finishes every leg, but `continue-on-error` still hides failing gates.
- **T-17** (partial): the per-score `all_states()` scan is tenant-scoped and runs once per request; no scan-count or scaling test.
- **T-18** (partial): one worker on one instance is now asserted against `render.yaml`; no cross-instance cache test.
- **T-23** (red): `GUARD_DESTRUCTIVE=1` outside a real deploy still boots; a boot-matrix cell tracks it.
- **T-24** (partial): calibration-lab Apply reaches scoring; no test drives the Apply route or a browser.
- Verified closed: T-11 (schema provisioned by `alembic upgrade head` before each deploy), T-12 (committed G5/G6 report: G5 pass, G6 uninformative), T-16, T-20, T-74.

### Known Conflicts

From NORTH_STAR "Known conflicts with independent teachers":
- `docs/release/PROFESSOR_ACCESS_PLAN.md` step 6: assumes institution contract
- `VERIFICATION_AND_BLOCKERS.md` items 6, 9, B2: require institutional approval
- `render.yaml` comments: describe "institutional pilot"
- Signup refusal message: tells users to contact "institution"
- Draft legal pages: say Bluebook "does not analyse writing style" (stops being true when Original is on)

### Repository Visibility

`pathosbuilder895/Orig` should become **private** (NORTH_STAR decision). Access steps documented in hosting research. GitHub app authorizations needed for Claude, Codex before switch. **Andrew's action.**

---

## Next up (assigned 2026-10-07)

Work in this order. Each task owns its files; nobody touches another task's files while it is open.

| # | Task | Owner | Branch → PR | Starts | May touch | Must not touch |
|---|------|-------|-------------|--------|-----------|----------------|
| A | Render-generated pilot secrets + matching docs | Codex | `codex/pilot-secrets` (from `codex/bluebook-pilot-c962a917`) | Now | `render.yaml` (secret entries + teacher-demo envVars), `tests/test_render_blueprint.py`, secret lines in `docs/BLUEBOOK_LAUNCH_CHECKLIST.md`, `docs/OPS_RUNBOOK.md`, `docs/superpowers/plans/2026-10-04-professor-release-finish.md`, `docs/DAY_ONE_CLASS.md` | Institution/LTI wording (task C), `original/**`, `demo/**`, `docs/release/**`, `docs/adr/**` |
| B | Rework [#228](https://github.com/pathosbuilder895/Orig/pull/228) landing to NORTH_STAR | Claude Code | `claude/original-landing-integration-d19b53` → #228 | Now (parallel with A) | Files #228 already touches: `demo/landing.html`, `demo/original-quantum.html` (remove), `demo/js/cursor.js`, `demo/js/live-demo.js`, `demo/styles/original-landing.css`, `demo/assets/` (its images), `docs/adr/011-*` | `demo/bluebook/**`, `original/**`, `render.yaml`, `scripts/**`, `docs/release/**`, ops docs and checklists |
| C | Independent-teacher + T-01 wording, testing-phase label in teacher screens | Claude Code (taken over from Codex 2026-10-11, Andrew's decision) | `claude/independent-teacher-wording` (non-screen part); screen part after #240 merges | Now | `original/onboarding.py` (`ORIGINAL_NOT_VALIDATED`), signup 403 text in `original/routers/auth.py` + its tests, `docs/release/*`, launch/provisioning checklists, 10-04 plan B2, `docs/DAY_ONE_CLASS.md`, `docs/OPS_RUNBOOK.md`, `render.yaml` comments only, `demo/bluebook/*.jsx` + rebuilt bundles | Task B files, `demo/legal/**` (counsel), scoring code, constants and flags |

**Shared label text (B and C):** "Testing phase: Original is not yet validated on real student writing. Treat any result as a reason for a conversation, never as evidence." *(proposed; Andrew may edit)*

**Rules for every task:** read AGENTS.md → NORTH_STAR → STATUS first. Work on a pushed `codex/*` or `claude/*` branch with a PR. CI must be green. Never push to main, never merge, never flip feature flags. Append one line to Log Entries and edit nothing else here.

**Andrew decides:** merging A, then B and C. Hosting for the landing page (B). Final images (B). Legal-page wording (counsel). Closing #160 and #225.

**Progress (2026-10-08):** A is merged as #235, so C may start. #160 and #225 are closed. B (#228) needs a rebase onto `main`.

---

## Next Steps

1. **Andrew: sign off the hosting plan.** The services already run on Render; confirm the plan and instance sizes.
2. **Andrew: make the repo private** after confirming the Claude and Codex GitHub app grants.
3. **Andrew: point the Render services at `main`**, then delete `codex/bluebook-pilot-c962a917` and `codex/pilot-secrets`.
4. **Legal pages:** counsel reviews the terms, privacy policy and student notice for independent teachers.
5. **Finish hosting setup:** SendGrid, plus the encrypted backup bucket and its key.
6. **Redeploy from `main` and test:** measure RSS, then run the B4 acceptance checks on the live instance.
7. **Invite the first teachers:** 1 to 3, via `scripts/invite_professor.py`.

---

## Session Log

Track what was done, when, by which tool. One line per session.

**Format:** append one list item per session as the last line of the file,
with no blank line before it: `- *YYYY-MM-DD | Tool | Branch/PR | Summary*`

`.gitattributes` merges this file with `merge=union`, so two branches that
both append an entry merge without a conflict. List items stay separate when
they land next to each other; plain lines would run together into one
paragraph. Don't reformat older entries: an open branch that still has the old
text would get both copies kept, with no conflict to flag it.

### Log Entries

*2026-10-07 | Cursor Cloud Agent (Claude Sonnet 5.5) | cursor/docs-north-star-and-status-05fa | Created NORTH_STAR.md, research/2026-10-07-hosting-and-storage.md, research/README.md, STATUS.md (this file), rewrote AGENTS.md, added pointer to CLAUDE.md. Single docs-only PR to establish shared source of truth.*

*2026-10-07 | Cursor Cloud Agent (Claude Sonnet 5.5) | cursor/readme-accuracy-docs-5374 | README.md rewrite for accuracy and NORTH_STAR alignment: fixed 109 features (was 103), AUTH_WEIGHTS mismatch, removed keystroke biometrics claims, removed v1 "dormant" backend references, removed stale Canvas import tab and original-demo service mentions. Aligned framing with NORTH_STAR (independent teachers, testing-phase warnings, consistency not verdicts). Fixed quick-start venv to specify python3.11, corrected test install to match CI (requirements.txt + requirements-dev.txt), updated test numbers from Andrew's macOS run (4,356 collected, 4,065 passed, 7m36s). Coverage: ≥98% enforced in CI (not 99%+).*

*2026-10-07 | Cursor Cloud Agent (Claude Sonnet 5.5) | cursor/assign-next-tasks-eba4 | Added Next up assignments for tasks A (Codex pilot secrets), B (Claude Code #228 rework), and C (Codex independent-teacher wording) to establish file ownership and prevent tool collision.*

*2026-10-08 | Codex GPT-6 | codex/pilot-secrets (Task A) | Packaged Render-generated signing/guard secrets, static-demo dependency skip and matching setup/custody/rotation docs; 15 targeted Blueprint/demo checks passed (`python -m pytest tests/test_render_blueprint.py tests/test_teacher_demo_site.py -q` using the existing project venv); `git diff --check` passed. Full suite and live rehearsal not rerun; CI pending. Historical correction: on 2026-10-06 the pilot at original-pilot.onrender.com (00247875) and separate fictional demo at bluebook-teacher-demo.onrender.com (2c2d62d2) were live, managed Postgres migrations succeeded, and 12 public smoke checks passed. Earlier “nothing deployed” statements are stale; NORTH_STAR is owner-only and unchanged. Email, encrypted backup/restore, legal approval and full acceptance remain open. No deployment, flag changes or added purchases in this session; Task C waits for Andrew to merge A.*

*2026-10-08 | Cursor Cloud Agent (Claude Sonnet 4.5) | cursor/docs-reconcile-d12e | Docs-only PR to reconcile CLAUDE.md and AGENTS.md with NORTH_STAR.md: (1) reframed CLAUDE.md Project Overview from seminary/authorship to pilot/writing-consistency; (2) corrected "Two backends" section noting v1 (original/api/, original/main.py) deleted in PR #90; (3) fixed Commit Style branch convention to claude/<name>; (4) removed hard-coded ~/Desktop/Original paths; (5) added venv/worktree note to AGENTS.md and CLAUDE.md; (6) removed test count hard numbers in CLAUDE.md lines ~25-40 and AGENTS.md line 194, pointed to CI for source of truth (coverage report --fail-under=98).*

*2026-10-08 | Claude Code (Claude Opus 5.5) | claude/original-bluebook-status-80e1e1 | On Andrew's instruction: closed #160 and #225 (no-keystroke rule; branches kept, #225's LTI key rotation 62f2152e noted for later), squash-merged #234 (7f3f4962), and corrected NORTH_STAR (v0.3), STATUS, README and AGENTS.md from "nothing deployed" to the live state checked via `/health`. Held deletion of `codex/bluebook-pilot-c962a917`: Render probably deploys from it (unconfirmed, CLI not logged in). Docs only; no deploys, flag changes or purchases.*

*2026-10-08 | Claude Code (Claude Opus 5.5) | claude/frontend-ui-implementation-b3024b | Navy demo suite: the 13-page Claude Design handoff, cleaned to NORTH_STAR, at demo/prototypes/navy/ (404 on real deploys) and published by the static teacher-demo build. Fictional ribbon, testing-phase notices, self-hosted fonts, no keystroke/AI/accuracy claims, no API calls, real feature counts (97 active). No images ship until Andrew supplies licences (assets/CREDITS.md). Targeted tests: 191 passed (demo site, blueprint, pilot lockdown, static tree, prototypes); full suite not run. Live-app port not started. Spec: docs/superpowers/specs/2026-10-08-navy-demo-suite-design.md.*

*2026-10-09 | Claude Code (Claude Opus 5.5) | claude/bluebook-disk-write-audit-cffe7e (#238) | Read-only audit of every Bluebook route (bluebook.py, bluebook_accounts.py, bluebook_baselines.py, proctor.py) and their callees for student text stored outside Postgres in pilot mode: no temp files, upload dirs, file log handlers or SQLite writes on those paths, and drafts never leave the student's browser. Two log leaks found and fixed: (1) SQLAlchemy put bound parameters (essay text, answers, baseline samples) into DB exception messages, which PostgresRepository logs, so a failed write copied student text into stdout logs; the live engine now sets hide_parameters=True (original/db/postgres_session.py; tests/test_db_errors_hide_student_text.py, red before and green after on SQLite and Postgres 16). (2) uvicorn's access log printed launch, invite, reset and phone-park tokens from query strings; run.py now passes access_log=False, since RequestLoggingMiddleware already logs every request by path (tests/test_access_log_no_tokens.py). Full CI command with local Postgres after both fixes: 4335 passed, 1 failed, 25 skipped, 4 deselected; the failure was the timing test tests/perf/test_event_loop_not_blocked.py[turnitin-csv] while another session's full suite ran in the same worktree, and that file passed 5/5 on three quiet reruns; `-m postgres`: 303 passed, 0 skipped. Reported, not fixed: Original-only upload routes spool files over 1 MB to a local temp file (Starlette). No flags, render.yaml or backup scripts touched.*
- *2026-10-11 | Claude Code (Claude Opus 5.5) | claude/housekeeping-gap-register | Re-checked stale gap-register rows by re-running their tests (local Postgres 16) and updated them and Technical Open Items: T-11, T-12, T-16, T-20, T-74 green; T-23 red (boot-matrix cell); T-14, T-17, T-24 partial. Added `tests/test_alembic.py` (T-10: single head, compare_metadata, downgrade/upgrade round trip; 3 passed against Postgres). It found real drift on `bluebook_submissions.submission_uuid` (partial unique index in migration 7c4d1e88a3b5, UNIQUE constraint in the model), pinned in the test and not fixed, so T-10 is red. Added a one-worker/one-instance `render.yaml` assertion (T-18 partial) and an alembic lockset check (T-11). No product code, migrations, flags or render.yaml changed.*
- 2026-10-11 | Claude Code (Claude Opus 5.5) | claude/housekeeping-gap-register | Fixed the T-10 drift in the model (`original/db/models/live.py` declares the partial unique index on `submission_uuid`, matching migration 7c4d1e88a3b5); `KNOWN_DRIFT_T10` emptied; new contract test pins the uniqueness on both backends. `-m postgres`: 305 passed.

- 2026-10-11 | Claude Code (Claude Opus 5.5) | claude/independent-teacher-wording | Took over Task C from Codex on Andrew's decision, split in two because #240 rewrites the same Bluebook screens. This part: signup refusal no longer mentions an institution; ORIGINAL_NOT_VALIDATED uses the shared testing-phase wording and asks for the teacher's consent; the professor invite email labels Original as testing-phase when the workspace has it; render.yaml comments, PROFESSOR_ACCESS_PLAN, VERIFICATION_AND_BLOCKERS (B3/B5 marked done), CONTINUE_RELEASE, the 10-04 plan B2/B6 and ARCHITECTURE reworded; DAY_ONE_CLASS, PROVISIONING_CHECKLIST and PILOT_RUNBOOK marked as later-phase (school) docs; new docs/release/COUNSEL_PACKET.md lists every legal-page decision for counsel. OPS_RUNBOOK and BLUEBOOK_LAUNCH_CHECKLIST wording moved to claude/pilot-ops-tools. Still to do after #240 merges: testing label and wording on professor.html, student briefing line in Exam.jsx. No legal pages, flags or deploys touched.
*2026-10-10 | Claude Code (Claude Opus 5.5) | claude/ui-design-port | On Andrew's instruction, the 2026-10-08 Claude Design navy suite becomes the live Original UI: static pages under demo/original/ (Your classes, Students, Submissions, Writing State, Conversation Packet, Voice Baseline, Reports, Settings, student My Voice and My Work) on real data only, shared demo/original/live.js, teachers land on /original/ after sign-in (professor.html kept as "Analysis (classic)"), Bluebook teacher sessions and exam booklet restyled (Authenticity score display removed), POST /me/work is compare-only (no longer adds to the baseline), handoff photos shipped without licences on record at Andrew's direction, raw mockups under docs/design/2026-10-mocks/, decisions and open owner items in docs/adr/012-ui-design-port.md. Every task reviewed plus a whole-branch review (ready to merge); full CI suite 4599 passed with the one OpenAPI snapshot failure fixed after; Bluebook e2e 108/108 plus the throttle test on a default-throttle server. Bluebook's correction form is hidden while no verdict is shown, and its worth-a-look mark carries the testing label. Overlaps Codex Task C in demo/bluebook/*.jsx by Andrew's choice. Stored analysis results (flag cards) are the next backend step.*
*2026-10-10 | Claude Code (Claude Opus 5.5) | claude/upload-spool-in-memory | Fixed the audit's reported-not-fixed item: Starlette's MultiPartParser rolled uploaded files over 1 MB to a temp file on local disk before the handler ran, so 1-10 MB student papers on the Original upload routes (/students/{id}/upload, bulk baseline upload, Turnitin CSV import) hit disk. original/api.py now sets MultiPartParser.spool_max_size = MAX_REQUEST_BYTES, so every upload the body cap admits stays in memory (measured cost: about one extra copy of the upload per upload in flight). Two new tests in tests/test_launch_hardening.py, red before and green after (a 2 MB upload creates no temp file). Full CI command without Postgres: 4097 passed, 0 failed, 261 skipped, 4 deselected. No flags, render.yaml or backup scripts touched.*
- *2026-10-07 | Claude Code (Claude Opus 5.5) | claude/original-landing-integration-d19b53 → #228 | Task B: reworked the landing to NORTH_STAR v0.2. Removed the dashboard mock (`original-quantum.html`) and its preview, the unlicensed St Andrews photo, and both AI "engravings" (they print 1822/1834 engraver credits inside the image). Teacher audience, teacher-approved baselines, no AI or precision claims, fictional labels, testing-phase notice, self-hosted fonts. ADR-011 revised. Andrew decides: final images, hosting, merge.*
- 2026-10-11 | Claude Code (Claude Opus 5.5) | claude/pilot-ops-tools | Pilot ops tools and docs: `scripts/pg_backup_offbox.py --download-latest DEST_DIR` fetches the newest encrypted dump for the restore drill (and an empty `--restore` now fails instead of falling through to a backup run); ported the LTI key rotation `62f2152e` (new kid `aae43f60dabc7388`; the leaked `7939c6c8a6f9a736` is no longer presented as expected anywhere, so the In Flight note about it is done once this merges); `pilot_preflight.py` refuses `REPO_BACKEND=postgres` with pointers; rewrote OPS_RUNBOOK for Postgres (backups, restore drill, Render Shell rollback, one worker only); fixed BLUEBOOK_LAUNCH_CHECKLIST (SendGrid is paid, confirm services deploy from `main`, `PUBLIC_BASE_URL` needed for invite emails, Shell-only `alembic downgrade`, independent-teacher wording); added `docs/release/PROFESSOR_QUICKSTART.md` (B6, support contact left as a placeholder). Targeted tests only; no PR opened (coordinating session reviews).
- 2026-10-11 | Claude Code (Claude Opus 5.5) | claude/original-screens-label-inconclusive | Task C part 2 (screens, after #240) plus the thin-baseline safety fix. Exam.jsx records a sealed exam INCONCLUSIVE (no score, never worth a look) unless baseline_integrity.readiness is "ready" (3+ approved samples), NORTH_STAR rule 3; Results shows it as inconclusive with a "Not enough reference writing yet" note. professor.html (Analysis classic) gains the testing label, drops "Authorship Probability", and hides operator/institution links from teachers. render.yaml pins NULL_MODEL=none. Unit 34 passed; Playwright 110 passed against a pilot-mode server; 1015 Python tests that read the bundle and pages passed. No scoring code, flags or legal pages touched.
