# NORTH STAR: Original + Bluebook

*v0.3, 8 Oct 2026. Owner: Andrew Clark. This file wins over every other doc in the repo. If something here looks wrong, propose an edit. Don't work around it.*

## Mission

We are building a platform that makes sure a student's writing is really their own, and that helps them become a stronger writer by building their own skill, not by letting an AI correct everything for them. Bluebook gives teachers a trustworthy place for students to write. Original helps a teacher see whether a new piece fits the student's own established voice. Original supports the teacher's judgment and is a reason for a conversation, never an accusation or a verdict.

## The two products and how they relate

- **Bluebook** is a locked, in-browser writing and exam app. Teachers create classes, invite students, run timed writing sessions, and read, grade, release and export the sealed submissions. It works entirely on its own: a Bluebook-only workspace never builds a writing profile and never scores anyone.
- **Original** is the writing-consistency engine. It builds a profile from a student's approved earlier writing and reports how a new piece compares. It is optional and switched on per workspace by an operator.
- **The link between them:** Bluebook owns the writing sessions and the submissions. Original only reads samples that a teacher has explicitly approved as reference writing. Sealing an exam never adds it to a profile automatically. Approvals can be undone.
- Both run in one Python/FastAPI app (`original/api.py` + `original/routers/` + `demo/bluebook/`). `docs/ARCHITECTURE.md` is the map of what is live and what is dead.

## Who it's for

- **This phase: independent teachers.** A teacher can be invited and use Bluebook in their own private workspace, with no school or institution account behind them. Each invite creates a private workspace (`scripts/invite_professor.py`).
- **Later:** seminaries and small writing-intensive colleges, plus their deans and academic-integrity staff. Named seminaries in the planning notes are prospects, not customers.
- **Always served:** students, who need reliable submission, fair treatment, and a way to explain themselves. Also the IT and privacy staff of any school that adopts it.

## Current phase and goal

**Phase: invitation-only Bluebook pilot for independent teachers.** Start with 1–3 teachers, possibly growing to a few dozen. There is no public signup (`SELF_SERVE_SIGNUP=0`).

Original is off by default. It may be switched on for a teacher, but only with the testing-phase warning described in rule 10.

The engineering for this phase is merged (PRs #226 and #227, 5 Oct 2026). **The pilot and the fictional demo have been deployed on Render since 6 Oct 2026, but no teacher is invited yet.** The pilot (`original-pilot.onrender.com`) runs on Postgres with signup closed and no students. It runs a pre-merge build (`00247875`), not `main`, so the next deploy should come from `main`. `docs/STATUS.md` has the details.

What remains before the first invite is listed in `docs/release/VERIFICATION_AND_BLOCKERS.md` under "Still open" (its B3 and B5, creating the pilot and publishing the demo, are done):
- hosting plan and budget sign-off
- email
- encrypted off-box backups
- legal pages
- deployed acceptance testing (full journey, restart, restore and rollback on the live instance)
- inviting the first teachers

**The hosting plan and budget are still open.** The services run on Render today. The options are in `docs/research/2026-10-07-hosting-and-storage.md`. Nothing more is purchased until Andrew approves.

Milestones, in order:
1. A shareable fictional demo. *(Live since 6 Oct 2026 at `bluebook-teacher-demo.onrender.com`.)*
2. A usable Bluebook pilot.
3. Original reports in teacher workspaces, labelled as testing-phase.
4. A validated Original.

## Non-negotiables

1. **Decision support, not a verdict.** Original recommends; people decide. No automatic grade changes or misconduct referrals. Every result is framed as a consistency observation, never an accusation.
2. **Honest claims only.** No feature counts, accuracy figures, probabilities or "AI-written" labels that the code and measured evidence don't support. No invented demo numbers presented as real, and fictional data is always labelled as fictional. Passing tests prove the engineering works. They do not prove the science.
3. **"Inconclusive" is a valid answer.** With thin baselines, short texts or missing peers, the system should say it can't tell, not guess.
4. **Protect honest students first.** A false alarm on an honest student is the worst failure. Students may legitimately write differently because they learned, changed genre, revised heavily, used permitted help, or needed accommodations. Score-changing mechanisms ship off by default and are only enabled after their validation gate passes and a human approves.
5. **Build the student's own skill.** Features should help students write better themselves. No feature should rewrite or "fix" a student's work for them, and no result should push a student to imitate a baseline.
6. **No keystroke data.** No typing rhythm or keystroke biometrics are collected, stored or scored. Only the text and coarse session facts (duration, word count, paste attempts, focus losses). Session facts are context, not evidence of dishonesty.
7. **Student writing stays inside the deployment.** No external inference, analytics, third-party fonts or telemetry may carry student prose.
8. **Only teacher-approved writing becomes a baseline.** Workspaces are isolated from each other. Students can be deleted, and deletion actually works.
9. **Keep the stack. Consolidate, don't rewrite.** Stay on Python/FastAPI with the embedded Bluebook. New work goes into the live stack only. The selected Claude Design teacher dashboard is the visual reference: port its look, not its invented data.
10. **Original in testing is always labelled.** Whenever Original is on, every place a teacher sees an Original result must say plainly that it is in its testing phase and is not validated on real student writing. Students must be told their sealed work may be used as reference writing.

## Decisions on record

- **Repository visibility.** `pathosbuilder895/Orig` should become **private**. Claude (Claude Code, Claude Design) and ChatGPT/Codex must keep read access through their GitHub app authorizations. Visibility has not been changed yet; that is Andrew's action. Access steps are in `docs/research/2026-10-07-hosting-and-storage.md`.
- **Audience.** Independent teachers are in scope for this pilot. The pilot stays invitation-only.

- **Known conflicts with independent teachers** (fix in follow-up PRs; this file wins):
  - `docs/release/PROFESSOR_ACCESS_PLAN.md` step 6 sets operating terms "with the responsible institution".
  - `VERIFICATION_AND_BLOCKERS.md` items 6 and 9 and B2 require "institutional operating approval" and institution review.
  - The `render.yaml` comments describe an "institutional pilot".
  - The signup-refusal message tells people to ask "the person who runs Bluebook for your institution".
  - The draft student notice and privacy page say Bluebook "does not analyse your writing style". That stops being true for any workspace where Original is on.

## Not doing now (deferred or out of scope)

- Canvas/LTI integration. The code stays in the repo, but nothing links to it and it is not configured in the pilot.
- Keystroke or behavioural biometrics in any form. This means PR #160-style Tier 17 work is off the table.
- Turning on any research flag that changes scores. This includes the AI-likelihood detector, fused score, topic inflation and characteristic weights.
- Claims to detect cheating or AI authorship. Any "authorship probability" presentation.
- AI that rewrites or corrects student work.
- Billing automation; "My Voice" longitudinal graphics; writer-similarity percentages; class-wide unlocks or leaderboards.
- The older Next.js Bluebook and its `bbook_client.py` adapter.
- Public self-serve signup.

## What "done" looks like for this phase

- An invited independent teacher gets a stable HTTPS link and sets up their own workspace with no developer help.
- The full journey works on phone and laptop: class → student invites → writing session → confirmed submission → teacher review, grading and export.
- Every acknowledged submission survives a restart or deploy and can be recovered. An encrypted backup has been restored for real.
- Workspaces and tokens are proven isolated on the deployed configuration. Research flags are off.
- If Original is switched on for any teacher, the testing-phase warning (rule 10) is visible in the teacher-facing UI. Today the warning text exists only in operator scripts (`original/onboarding.py` `ORIGINAL_NOT_VALIDATED`), so this is still to build. The student notice must also be updated to cover Original.
- Legal pages, terms and the student notice are final (no draft placeholders) and fit teachers who sign up without a school agreement. A named support and incident owner exists.
- Pilot size: 1–3 invited teachers first. Stop intake if privacy boundaries fail or acknowledged work is lost.
- Every claim of progress names the exact commit, the commands run, what was excluded, and the hosting state.

## How the AI tools use this file

- **Read order:** this file → `docs/STATUS.md` → `docs/ARCHITECTURE.md` → the ADR for the area you're touching. `CLAUDE.md` / `AGENTS.md` cover mechanics only (environment, tests, commands).
- **On conflict, this file wins.** If another doc, plan or prompt contradicts it, follow this file and flag the conflict. **Propose** a change to this file rather than drifting from it. Only Andrew edits it.
- **Codex / Claude Code:** work on a pushed `codex/*` or `claude/*` branch and open a PR. Never leave work only on a local machine. Never push to main or flip flags without approval. Record what you did in STATUS.
- **Claude Design:** treat the rules above as design constraints. Every number on screen is either real API data or visibly labelled fictional. Use no unlicensed or AI-generated images credited as historical art.
- **Perplexity / research:** answer the specific question asked. Save results to `docs/research/` with the tool, date, question, sources and the decision it informs. Research informs decisions; it doesn't make them.

## Open questions

- **[ANDREW: what age are the students these teachers will have?]** The draft privacy page says "13 and over". Younger students bring in COPPA parental-consent duties. See the research doc.
- **[ANDREW: counsel needs to approve terms and a data agreement for teachers who use Bluebook without a school contract.]** See the research doc's privacy section.
