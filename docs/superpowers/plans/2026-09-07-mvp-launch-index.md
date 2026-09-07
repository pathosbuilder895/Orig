# MVP Launch — Index Plan

> **For agentic workers:** This is the umbrella document for a multi-part effort. Each part below is its own self-contained implementation plan; execute ONE part per session with superpowers:subagent-driven-development or superpowers:executing-plans. Do not attempt multiple parts in one session — a part is sized to a session. **Exception for the ops and soak parts (4–7):** those span calendar time and human gates; there, "one part per session" means one TASK's checklist per sitting, and the part stays `in progress` on this dashboard between sittings.

**Goal:** Take Original from **code-complete but undeployed** — `original-pilot.onrender.com` returning Render's `x-render-routing: no-server` (verified 2026-09-07), zero operator entries in `docs/PILOT_LOG.md`, the branch-coverage completion stranded off-origin, and ~25 open PRs — to **MVP done**: a live, monitored pilot passing `O1 go-live check: PASS` and then `smoke test: PASS` on Postgres; Canvas sandbox-verified; one tenant + 5 professors provisioned with the before-real-students gate signed; CI honest at `--cov-branch --cov-fail-under=98`; the PR queue emptied or dispositioned; and all five score-neutral shadow instruments soaking against real traffic with weekly readings.

**Why an operational effort, not more code:** every code-wave task of `2026-07-24-pilot-launch-master-plan.md` (T1–T9) is merged and the wire-by-wire live proof passed 2026-08-13 (`docs/BLUEBOOK_WIRE_PROOF_2026-08-13.md`). What separates the repo from a running pilot is no longer software — it is deploys, credentials, an email to a Canvas admin, a database cutover, and the validation numbers only live traffic can supply. This effort plans that work with the same rigor the code got.

## Global Constraints (inherited by every part plan)

- **Venue rule.** Parts state their venue. Mac-venue parts use `/Users/andrew/Desktop/Original/.venv/bin/python` (never system python3; inside a worktree the relative `.venv` does not exist). Cloud-venue parts use the checkout's `.venv/bin/python` and must never cite the Mac absolute path. Ops-venue parts operate through the Render dashboard and guarded `curl`s.
- **Never deploy or restart the pilot service during a scheduled examination.** Every env-var change on Render restarts the service, so every flag flip is a deploy and happens in a window.
- **`docs/PILOT_LOG.md` is the operational record.** Every operator action lands as one line (date, who, event, notes). An action done but unlogged counts as not done.
- **Ops checklist semantics.** An ops step is: one operator action + the verifying command + the exact expected output + what failure means. Human-only actions are marked `⛔ HUMAN`. Any unexpected output → STOP, report BLOCKED, append a PILOT_LOG line — never improvise around a failed gate.
- **Secrets** live in `~/Desktop/Original-secrets/` and the Render dashboard only — never in commits, PR bodies, or these plan files. Public key *identifiers* (e.g. the LTI kid `7939c6c8a6f9a736`) are fine.
- **No score-changing flag goes `on` inside this effort**, and Tier 17/18 stay in `DISABLED_FEATURE_GROUPS`. Shadow modes only. Every enablement is a separate, human-approved act with its own runbook (`docs/TIER17_ENABLEMENT_RUNBOOK.md`, `docs/PILOT_RUNBOOK.md` §3, the CLAUDE.md flag rows).
- **A clean suite run is 0 failed.** After Part 1 lands, CI's coverage gate is `--cov-branch --cov-fail-under=98` — never lowered to admit a regression.
- **Commit style:** `Add ...` / `Fix ...`, one focused commit per task; ops tasks commit their PILOT_LOG entry and doc/dashboard updates (the operational record IS the commit). Co-author line `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## The Parts

Numbering is by lane (code 1–3, ops 4–6, soak 7), **not** execution order — the dependency graph below is normative. Day-1 dispatch is three concurrent starts: Part 1 (Mac), Part 3 (cloud), Part 4 (operator); they are mutually file-disjoint.

| Part | Plan file | Scope | Venue | Depends on | Done when | Status |
|---|---|---|---|---|---|---|
| 1 | `2026-09-07-mvp-launch-part1-coverage-landing.md` | Land the completed branch-coverage effort; CI → `--cov-branch --cov-fail-under=98` | user's Mac | — | post-merge CI green on origin/main under the new gate | pending |
| 2 | `2026-09-07-mvp-launch-part2-pr-queue.md` | Decide #160; batch dependabot; majors individually; disposition #193/#194/#195 + sprint/* branches | Mac (cloud acceptable) | Part 1 | every 2026-09-07 open PR merged / closed-with-rationale / pinned-with-reason | pending |
| 3 | `2026-09-07-mvp-launch-part3-soak-readers.md` | Build `scripts/fused_shadow_report.py` + `scripts/characteristic_soak_report.py` with tests | cloud session | — | both readers green on fixtures; suite 0 failed; PILOT_RUNBOOK cites them | pending |
| 4 | `2026-09-07-mvp-launch-part4-deploy-monitor-canvas.md` | O1 deploy + go-live check; O3 monitoring; O2 Canvas ask (same day); release tag | operator + assistant | — | `O1 go-live check: PASS` + monitor live + dated canvas-sent PILOT_LOG line + tag pushed | pending |
| 5 | `2026-09-07-mvp-launch-part5-postgres-cutover.md` | O4 Postgres cutover ceremony; O5 restore drills; unblock `tier17_report` | operator + assistant | Part 4 | `smoke test: PASS` + `/health` backend `postgres` + both drills logged + rollback-floor date logged | pending |
| 6 | `2026-09-07-mvp-launch-part6-lti-provisioning.md` | O7 LTI bind; O8 sandbox §3 checks; O9 tenant + professors; §5 before-students gate (O6 DPA) | operator + assistant | Part 4 + Canvas admin reply (external); Part 5 strongly first | all §5 boxes dated; first-exam go decision recorded | pending |
| 7 | `2026-09-07-mvp-launch-part7-shadow-soak.md` | 5-flag shadow start ritual; weekly readings; close-out summary | operator + assistant, recurring | Parts 3+4 (readings need 5, measurements need 6) | ≥4 weekly readings on real traffic; `CHARACTERISTIC_WEIGHTS=off` again; summary committed | pending |

Status vocabulary: `pending` → `in progress` → `blocked (<reason>)` → `soaking (week N)` (Part 7 only) → `done @ <evidence>`. Update the row as parts land; this table is the effort's dashboard.

## Dependency graph (what runs when)

```
CODE LANE (git; file-disjoint from ops)
  P1 coverage landing (Mac) ─────────────→ P2 PR-queue triage
  P3 soak readers (cloud) ──────────────────────────────────────┐
                                                                │
OPS LANE (Render dashboard + guarded curls; serializes on       │
          service state and Canvas-admin latency)               │
  P4 deploy + monitoring + CANVAS ASK (ask goes out same day —  │
     the admin reply is the schedule's long pole)               │
      ├──────────→ P5 postgres cutover + restore drills ────────┤
      │              (unblocks tier17_report on the pilot DB)   │
      └─(admin reply, days–weeks)─→ P6 LTI bind + sandbox       │
                                     + tenant/professors        │
             P2's #160 decision must precede ──┘ first          │
             proctored sitting;                                 │
             O6 DPA signature hard-gates real students          │
                                                                │
SOAK LANE                                                       │
  P4 + P3 ─→ P7 flags live ──(P5: DB readers)──(P6: traffic)──→ ┴→ weekly
             readings → close-out summary

DAY-1 DISPATCH: P1, P3, P4 in parallel (three venues, mutually file-disjoint).
```

## Cross-cutting themes the parts must respect

1. **Shadow before on.** The soak is the experiment, not a formality. `GENRE_INVARIANT_WEIGHTS_ENABLED` is the named cautionary precedent: built, tested, and it fires on essentially nothing in practice. Each shadow instrument has ONE decisive number only live traffic can supply (genre abstention rate; topic-distance mass above 0.25; characteristic-weights dispersion; the fused score's baseline-volume confound slope; AI real-world FPR) — the weekly ritual exists to read those numbers, and no flag flips `on` here.
2. **The admin reply is the schedule.** Everything that can proceed without Canvas proceeds in parallel; that is why the ask is a same-day task inside Part 4 rather than its own later part.
3. **The zero-user window is an asset — spend it deliberately.** Cutover before students compresses the runbook's shadow soak and removes the freeze cost (Part 5 records this reconciliation explicitly, with a revert-to-full-soak conditional if users exist by then).
4. **Readers before data.** Every telemetry channel gets its reader built and fixture-tested (Part 3) before real rows exist, so week-1 pilot data is never wasted on "we'll analyze it later."
5. **No student PII** in any report, log excerpt, PR body, or plan artifact.

## Relationship to the 2026-07-24 master plan

`2026-07-24-pilot-launch-master-plan.md` remains the historical record of the shipped code waves (T1–T9, all merged). Its operational track is superseded by this effort — do not execute O-items from that file. Mapping: O1/O2/O3 → Part 4; O4/O5 → Part 5; O6/O7/O8/O9 → Part 6. Tier 17 data collection continues under the standing rule (collect and report, never enable) via Parts 5/7.

## Execution order and hand-off

1. Dispatch P1, P3, P4 on day 1 (three venues). P2 starts only after P1 merges (the whole queue rebases over that merge exactly once). P5 after P4. P6 waits on the admin reply; its Task 1 (tenant) can run any time after P4. P7's start ritual runs after P4+P3; its readings become measurements only once P6 produces traffic.
2. **First action of every part: re-verify its entry facts** — `/health` for service state, the live PR list for queue state, `git -C <worktree> status` for the coverage work. This effort's facts decay much faster than coverage percentages; the tables in each part are snapshots dated 2026-09-07.
3. **Last action of every part:** update this index's dashboard row, append the PILOT_LOG line(s), commit.
