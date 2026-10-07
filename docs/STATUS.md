# Original + Bluebook: Current Status

*Last updated: 2026-10-07*

**Quick ref:** This file tracks what's deployed, what's in flight, what's blocked, and what's next. Every AI tool should update this at the end of a session.

---

## Current Phase

**Invitation-only Bluebook pilot for independent teachers.** Start with 1–3 teachers, possibly growing to a few dozen. No public signup (`SELF_SERVE_SIGNUP=0`).

Original is off by default. It may be switched on per workspace with testing-phase warnings.

Engineering for this phase is merged (PRs #226, #227, 5 Oct 2026). Nothing is deployed yet.

See `docs/NORTH_STAR.md` for phase goals and non-negotiables.

---

## Deployed

**Nothing is deployed yet.**

Previous free Render service (`Originall`) at `https://originall.onrender.com` is stale and failed on most recent deploy attempt. No production database exists.

Target: Render Hobby following `render.yaml` blueprint, Postgres 16, Oregon region.

---

## In Flight

### Open PRs

| PR | Branch | Owner | Status | Notes |
|----|--------|-------|--------|-------|
| [#228](https://github.com/pathosbuilder895/Orig/pull/228) | `claude/original-landing-integration-d19b53` | Claude Code + Claude Design | Open | Landing page plus dashboard mock. Includes ADR-011. **Conflicts:** Found two AI-generated images credited to historical engravers and one unlicensed photo. Needs Andrew decision on hosting claims, image licensing, and footer. |
| [#225](https://github.com/pathosbuilder895/Orig/pull/225) | `sprint/lane-a-claude` | Claude | Open | **CONFLICTS WITH NO-KEYSTROKE RULE** (ADR-010, NORTH_STAR rule 6). Contains LTI key rotation and Postgres mode for tier17_report.py. 441 commits behind main. Stale under ADR-010 and LTI deferral. Should be closed or superseded. |
| [#160](https://github.com/pathosbuilder895/Orig/pull/160) | `claude/typing-cadence-benchmarks-fdb276` | Claude | Open | **CONFLICTS WITH NO-KEYSTROKE RULE** (ADR-010, NORTH_STAR rule 6). Tier 17 keystroke recalibration. KB D04 says ADR-010 supersedes this. Codex review exists at `docs/reviews/PR-160-tier17-review-2026-08-26.md`. 173 commits behind main. Should be closed or superseded. |

### Branches Without PRs

| Branch | Owner | Status | Notes |
|--------|-------|--------|-------|
| `codex/bluebook-pilot-c962a917` | Codex | Pushed to origin, no PR | 4 commits (6 Oct). Switches render.yaml `SECRET_KEY`/`MAINTENANCE_TOKEN` from `sync:false` to `generateValue:true`, adds `SKIP_INSTALL_DEPS` to static demo. Overlaps with PR #227 plan B3 ("owner creates fresh secrets"). Needs decision: open PR or drop. |

### Dependabot PRs

24 open dependabot PRs for dependencies. Several are major version bumps (vitest 5, eslint 10, ruff 0.16, pydantic 2.13). 10 target `/app` directory (re-scoped legacy tree per ADR-008-ws8) — decide whether to merge these or configure dependabot to ignore `/app`.

---

## Blockers

From `docs/release/VERIFICATION_AND_BLOCKERS.md` "Still open":

### Owner/Operator Tasks (B1–B6)

1. **Hosting and budget decision** — Render vs alternatives, instance size, Postgres plan. Research complete in `docs/research/2026-10-07-hosting-and-storage.md`. Awaiting Andrew's approval.
2. **Email provider** — SendGrid Essentials ~$19.95/mo. Sending domain must be verified. Awaiting Andrew's setup.
3. **Encrypted off-box backups** — R2 or B2 bucket in separate account, Fernet key stored offline. Awaiting Andrew's setup.
4. **Legal pages final** — Privacy policy, terms, student notice. Draft placeholders exist with `[ENTITY]`, `[CONTACT]`, `[PROVIDER]` blanks. Counsel needs to approve terms and data agreement for teachers without school contracts. See NORTH_STAR open questions.
5. **Deployed acceptance testing** — B1–B6 checks on real deployed instance, not local rehearsal.
6. **Publishing fictional demo** — Static demo site at separate origin (`bluebook-teacher-demo` in render.yaml).
7. **First teacher invites** — 1–3 teachers. Use `scripts/invite_professor.py`. Pilot stays invitation-only.

### Technical Open Items

From `docs/testing/10-gap-register.md`:
- **T-10**: No Alembic migration tests
- **T-11**: Who provisions pilot Postgres schema
- **T-13**: G7 (cross-topic false-positive gate) never returned verdict
- **T-14**: Weekly calibration battery can't finish (deferred)
- **T-16, T-17**: (deferred or informational)
- **T-18**: Single-worker assumption not enforced in deployment config

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

## Next Steps

1. **Andrew: approve hosting plan** — Render blueprint, instance sizes, backup bucket setup
2. **Andrew: make repo private** — After confirming Claude/Codex GitHub app grants
3. **Resolve conflicting PRs** — Close or supersede #160 and #225 per ADR-010 and no-keystroke rule
4. **Decide on codex/bluebook-pilot branch** — Open PR or drop
5. **Legal pages finalization** — Counsel review of terms, privacy policy, student notice for independent teachers
6. **Configure hosting** — Apply render.yaml blueprint, set up SendGrid, create backup bucket
7. **Deploy and test** — First deploy, measure RSS, run B1–B6 acceptance checks
8. **Invite first teachers** — 1–3 teachers via `scripts/invite_professor.py`

---

## Session Log

Track what was done, when, by which tool. One line per session.

**Format:** `YYYY-MM-DD | Tool | Branch/PR | Summary`

### Log Entries

*2026-10-07 | Cursor Cloud Agent (Claude Sonnet 5.5) | cursor/docs-north-star-and-status-05fa | Created NORTH_STAR.md, research/2026-10-07-hosting-and-storage.md, research/README.md, STATUS.md (this file), rewrote AGENTS.md, added pointer to CLAUDE.md. Single docs-only PR to establish shared source of truth.*

*2026-10-07 | Cursor Cloud Agent (Claude Sonnet 5.5) | cursor/readme-accuracy-docs-5374 | README.md rewrite for accuracy: fixed 109 features (was 103), AUTH_WEIGHTS mismatch, removed keystroke biometrics claims, removed v1 "dormant" backend references, removed stale Canvas import tab and original-demo service mentions. Aligned framing with NORTH_STAR (independent teachers, testing-phase warnings, consistency not verdicts). Verified quick-start commands and reported real test counts.*
