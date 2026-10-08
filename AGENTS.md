# Original + Bluebook — Agent Instructions

**All AI tools working on this repository should read this file first.**

This is the shared entry point for ChatGPT Codex, Claude Code, Claude Design, and Perplexity. It tells you what to read, what rules never bend, and how to record your work so other tools (and humans) can follow.

---

## Read Order

1. **`docs/NORTH_STAR.md`** — Mission, phase, non-negotiables, decisions on record. **This file wins on conflict.** If you see a contradiction between NORTH_STAR and any other doc, follow NORTH_STAR and flag the conflict. Only Andrew edits NORTH_STAR.

2. **`docs/STATUS.md`** — Current state: what's deployed, what's in flight, blockers, next steps. Check this before starting work so you don't duplicate or conflict. **Update STATUS.md before you finish every session** with a one-line log entry.

3. **`docs/ARCHITECTURE.md`** — Map of live vs dormant vs deleted stacks. This repo contains two backends and three frontend generations; only one path is live. Check which stack you're in before touching auth, LTI, or routes.

4. **ADRs for your area** — `docs/adr/` contains architecture decision records. Read the ones relevant to your task. If an ADR contradicts NORTH_STAR, NORTH_STAR wins.

5. **`CLAUDE.md`** (Claude Code only) — Tool-specific mechanics: venv, server management, test commands, environment flags. Other tools don't need this.

---

## Conflict Resolution Rule

**NORTH_STAR wins.** If you find a contradiction:
1. Follow NORTH_STAR's direction
2. Flag the conflict in your PR description or work summary
3. Propose an edit to NORTH_STAR if it looks wrong (but don't work around it)
4. Only Andrew edits NORTH_STAR

---

## Working Rules (All Tools)

### Branch and PR Conventions

- **Always work on a pushed branch.** Never leave work only on a local machine.
- **Branch naming:**
  - Codex: `codex/<descriptive-name>`
  - Claude Code: `claude/<descriptive-name>`
  - Claude Design work ported by Claude Code: `claude/<descriptive-name>`
- **Always open a PR**, even if draft. No work should exist only as an unpushed branch.
- **Never push directly to main** without explicit approval.
- **PR descriptions should include:**
  - Which tool did the work
  - Link to relevant ADR or plan
  - NORTH_STAR constraints checked
  - Tests run (with exclusions noted)
  - Whether STATUS.md was updated

### Commit Messages

- One focused commit per logical change
- Conventional format: `Fix ...`, `Add ...`, `Refactor ...` (not "update" for new features)
- **Co-author trailer:** `Co-Authored-By: <Tool> <Model> <noreply@anthropic.com>`
  - Examples: `Claude Sonnet 5.5`, `Claude Opus 5.5`, `Codex GPT-5`

### Hard Rules

These require explicit user permission or owner approval:
- **Never flip environment flags** that change scores or behavior in production
- **Never kill or restart the dev server** without asking
- **Never delete files** with `rm` (use `git rm` instead)
- **Never change `original/constants.py`** feature ordering or `NORM_BOUNDS`
- **Never add hard-coded paths** like `/Users/andrew/Desktop/Original` — use relative paths or cwd

### Update STATUS.md

Before you finish a session:
1. Add a one-line entry to the Session Log section
2. Update "In Flight" if you created/updated a PR or branch
3. Move items from "Blockers" or "Next Steps" if you resolved them
4. Commit and push STATUS.md with your other changes

---

## Environment and Commands

**Working directory:** Repository root (wherever you checked it out)

**Python environment:** Always use `.venv/bin/python` and `.venv/bin/pytest`, never system python3. The system python3 has broken dependencies.

**Note:** Each checkout or worktree needs its own venv at its root. Create with `python3.11 -m venv .venv` and install dependencies per README. Alternatively, activate an existing venv and use plain `python -m pytest` (without the `.venv/bin/` prefix).

**Run dev server:**
```bash
.venv/bin/python run.py --demo
# Or for pilot mode:
ORIGINAL_ENV=pilot SELF_SERVE_SIGNUP=0 .venv/bin/python run.py --demo --skip-seed
```

**Run tests:**
```bash
# Full suite (budget ~11-12 minutes)
.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -m "not blocker and not certification" -q

# With Postgres (after starting local container)
DATABASE_URL=$(bash scripts/local_postgres.sh url) .venv/bin/python -m pytest tests/ -m postgres -q

# Specific module
.venv/bin/python -m pytest tests/quantum/ -v
```

**Bluebook frontend:** After editing `demo/bluebook/*.jsx`:
```bash
cd demo/bluebook && npm run build
```
Then commit the bundle. Render has no Node — the committed `bluebook.bundle.js` is what production serves.

---

## Tool-Specific Notes

### ChatGPT Codex

- Read NORTH_STAR → STATUS → ARCHITECTURE before starting
- Work on a `codex/*` branch
- Open a PR (or update existing one)
- Log your session in STATUS.md
- Use conventional commit messages with `Co-Authored-By: Codex GPT-5 <noreply@anthropic.com>` (or current model)

### Claude Code

- Read NORTH_STAR → STATUS → ARCHITECTURE, then `CLAUDE.md` for tool-specific mechanics
- Work on a `claude/*` branch
- Open a PR (or update existing one)
- Log your session in STATUS.md
- See `CLAUDE.md` for venv quirks, server management, testing details, and environment flags

### Claude Design

- Read NORTH_STAR first — treat the non-negotiables as design constraints
- **Every number on screen must be either:**
  - Real data from the API, or
  - Visibly labelled as fictional (in the design itself)
- **Never use:**
  - AI-generated images credited as historical art
  - Unlicensed images or photos
  - Invented statistics presented as real
- The selected teacher dashboard (`claude.ai/design/p/019e2463...`) is the visual reference
- Design work is ported to code by Claude Code, which logs it in STATUS.md
- Design constraints:
  - No keystroke or "typing rhythm" displays
  - No "AI-written" probability labels
  - No paper scanning features
  - Student writing never goes to external services
  - "Inconclusive" is always a valid result

### Perplexity (or other research tools)

- Read NORTH_STAR to understand the question's context
- Answer the specific question asked
- Save results to `docs/research/YYYY-MM-DD-topic-name.md` with the standard header (see `docs/research/README.md`):
  ```markdown
  | | |
  |---|---|
  | **Tool** | Perplexity Pro |
  | **Date** | 2026-10-07 |
  | **Question** | The specific question |
  | **Decision it informs** | Which NORTH_STAR section, ADR, or doc this supports |
  ```
- Include sources and links
- Research informs decisions; it doesn't make them
- Log the research file in STATUS.md if you can (otherwise the engineer who uses it will log it)

---

## Key Facts About This Repo

**Two products:**
- **Bluebook**: Standalone locked writing/exam app for teachers and students
- **Original**: Optional writing-consistency engine, off by default

**Target users:**
- Current phase: independent teachers (invitation-only, 1–3 teachers to start)
- Later: seminaries and small colleges

**Current state:**
- Engineering merged (PRs #226, #227, 5 Oct 2026)
- Nothing deployed yet
- Render blueprint exists; awaiting owner approval
- Postgres 16 backend; SQLite for dev/demo

**Stack:**
- Python 3.11 + FastAPI + uvicorn
- React 19 bundled with esbuild (Bluebook frontend)
- spaCy, numpy, sklearn
- Postgres 16 (via SQLAlchemy + Alembic) or SQLite

**Live routes:** `original/api.py` + `original/routers/*.py`

**Dead code:** v1 backend (`original/api/`, `original/main.py`) was deleted in PR #90. Old frontends (`frontend/`, `web/`) removed in ADR-006.

**Feature dimensions:** 109 features across 18 tiers; 97 active in pilot (Tier 17 keystroke and Tier 18 uniformity disabled per ADR-010 and pending validation gates).

**Tests:** CI (`.github/workflows/test.yml`) is the source of truth for the exact test command and enforces combined coverage with `coverage report --fail-under=98`. A full run takes several minutes. Get the live count with `python -m pytest --collect-only -q tests/ | tail -1`.

---

## Where to Get Help

- **Architecture questions:** `docs/ARCHITECTURE.md`
- **Release progress:** `docs/release/VERIFICATION_AND_BLOCKERS.md`
- **Testing gaps:** `docs/testing/10-gap-register.md`
- **Environment flags:** `CLAUDE.md` (60-row table with validation notes)
- **Ops/security:** `docs/OPS_RUNBOOK.md`
- **Phase goals:** `docs/NORTH_STAR.md`

When in doubt, read NORTH_STAR first.
