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

| Blocker | Owner | Affects | Status |
|---------|-------|---------|--------|
| Hosting decision | Andrew | All deployment | Open. Render blueprint, instance sizes, backup bucket setup. |
| Repo visibility | Andrew | All AI tools | Open. Make repo private, confirm Claude/Codex GitHub app grants still work. |
| Legal pages finalization | Andrew | Pilot launch | Open. Counsel review of terms, privacy policy, student notice for independent teachers. |

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

*2026-10-07 | Cursor Cloud Agent (Claude Sonnet 5.5) | cursor/readme-accuracy-docs-5374 | README.md rewrite for accuracy and NORTH_STAR alignment: fixed 109 features (was 103), AUTH_WEIGHTS mismatch, removed keystroke biometrics claims, removed v1 "dormant" backend references, removed stale Canvas import tab and original-demo service mentions. Aligned framing with NORTH_STAR (independent teachers, testing-phase warnings, consistency not verdicts). Fixed quick-start venv to specify python3.11, corrected test install to match CI (requirements.txt + requirements-dev.txt), updated test numbers from Andrew's macOS run (4,356 collected, 4,065 passed, 7m36s). Coverage: ≥98% enforced in CI (not 99%+).*

*2026-10-07 | Cursor Cloud Agent (Claude Sonnet 5.5) | cursor/assign-next-tasks-eba4 | Added Next up assignments for tasks A (Codex pilot secrets), B (Claude Code #228 rework), and C (Codex independent-teacher wording) to establish file ownership and prevent tool collision.*

*2026-10-08 | Codex GPT-6 | codex/pilot-secrets (Task A) | Packaged Render-generated signing/guard secrets, static-demo dependency skip and matching setup/custody/rotation docs; 15 targeted Blueprint/demo checks passed (`python -m pytest tests/test_render_blueprint.py tests/test_teacher_demo_site.py -q` using the existing project venv); `git diff --check` passed. Full suite and live rehearsal not rerun; CI pending. Historical correction: on 2026-10-06 the pilot at original-pilot.onrender.com (00247875) and separate fictional demo at bluebook-teacher-demo.onrender.com (2c2d62d2) were live, managed Postgres migrations succeeded, and 12 public smoke checks passed. Earlier "nothing deployed" statements are stale; NORTH_STAR is owner-only and unchanged. Email, encrypted backup/restore, legal approval and full acceptance remain open. No deployment, flag changes or added purchases in this session; Task C waits for Andrew to merge A.*

*2026-10-08 | Cursor Cloud Agent (Claude Sonnet 4.5) | cursor/docs-reconcile-d12e | Docs-only PR to reconcile CLAUDE.md and AGENTS.md with NORTH_STAR.md: (1) reframed CLAUDE.md Project Overview from seminary/authorship to pilot/writing-consistency; (2) corrected "Two backends" section noting v1 (original/api/, original/main.py) deleted in PR #90; (3) fixed Commit Style branch convention to claude/<name>; (4) removed hard-coded ~/Desktop/Original paths; (5) added venv/worktree note to AGENTS.md and CLAUDE.md; (6) removed test count hard numbers in CLAUDE.md lines ~25-40 and AGENTS.md line 194, pointed to CI for source of truth (coverage report --fail-under=98).*
