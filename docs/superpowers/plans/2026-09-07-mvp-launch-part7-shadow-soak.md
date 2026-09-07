# MVP Launch Part 7 — Shadow-Soak Program

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read `2026-09-07-mvp-launch-index.md` §Global Constraints first — they all apply here. **This part is NOT one session:** Task 1 is one maintenance-window sitting; Task 2 is a weekly ritual repeated for the soak's duration; Task 3 closes. Dashboard status runs `pending → flags live → soaking (week N) → done @ <summary doc>`.

**Goal:** All five score-neutral shadow instruments run against real pilot traffic long enough (≥4 weekly readings) for each to produce its ONE decisive number — genre-v2 abstention rate on real submissions; topic-distance mass above the 0.25 fire threshold; characteristic-weights applied-rate + dispersion; the fused score's hit rate + baseline-volume confound slope; AI-likelihood real-world FPR — and a close-out summary records a per-mechanism recommendation. **No flag goes `on` inside this part.**

**Architecture:** One start ritual (all five flags in a single restart, latency tripwire armed), then a weekly reading that is purely running the readers Part 3 built plus the three that already existed, one PILOT_LOG line and one results-table row per week. Every mechanism's enablement remains a separate, human-approved act with its own runbook.

**Tech Stack:** Render dashboard env vars; `scripts/pilot_report.py`, `scripts/shadow_report.py`, `scripts/tier17_report.py`, `scripts/fused_shadow_report.py` + `scripts/characteristic_soak_report.py` (Part 3), `validation/genre_2026-08/read_shadow_log.py`.

**Venue:** operator + assistant, recurring. **Depends on:** Part 4 (service) + Part 3 (readers); Part 5 (the DB readers need `$DATABASE_URL`); readings become *measurements* only once Part 6 produces real traffic — earlier runs are plumbing checks and are labeled as such in the log.

## Global Constraints (additional to the index's)

- `CHARACTERISTIC_WEIGHTS != off` makes every scoring request run a full `all_states()` peer-pool scan — a real per-request cost. The latency watch is armed from the flip and its tripwire is pre-committed (below); **returning this flag to `off` at soak end is a non-negotiable close-out step.**
- Genre reading discipline: `read_shadow_log.py` exit 1 means shadow was not running — that is a soak misconfiguration to fix, never a "0% abstention" to record. The first thing to look for in genre readings is **sermons** (v2's known taxonomy gap).
- Weekly artifacts carry no student ids (the log lines and readers already enforce this — keep it true in any hand-written notes too).

---

### Task 1: Start ritual (one maintenance window, ⛔ HUMAN on the dashboard)

- [ ] **Step 1: Latency baseline.** Before flipping anything, record scoring latency: 3 timed `POST /students/<seeded-id>/score` calls (or the Render metrics p50). Write the number down in the PILOT_LOG line — the tripwire is relative to it.
- [ ] **Step 2: Flip all five in one restart:** `GENRE_RESOLVER_V2=shadow`, `FUSED_SCORE_SHADOW=1`, `CHARACTERISTIC_WEIGHTS=shadow`, `TOPIC_VARIANCE_INFLATION=shadow`, `AI_LIKELIHOOD_SHADOW=1` → deploy once. Only `AI_LIKELIHOOD_SHADOW` is declared in `render.yaml`; the other four are hand-added dashboard vars (blueprint syncs ignore them — fine). Not during any scheduled exam.
- [ ] **Step 3: Verify each channel emits.** After the first scored submission: `render logs --tail 5000 | grep -c "genre_shadow\|topic_inflation\|characteristic_weights\|fused_score outcome"` — every family ≥1. A silent family means its flag didn't take — fix now, not at week 1.
- [ ] **Step 4: Arm the tripwire.** Pre-committed rule: if scoring p50 exceeds **2× the Step 1 baseline**, set `CHARACTERISTIC_WEIGHTS=off`, log it, and continue the rest of the soak — the other four instruments are cheap and unaffected. PILOT_LOG line for the flip (flags, date, baseline latency); index row → `flags live`; commit.

### Task 2: Weekly reading ritual (repeat each week; one sitting)

- [ ] **Step 1:** `render logs --tail 100000 > /tmp/week<N>.log` (one pull feeds both log readers).
- [ ] **Step 2:** Run the six readers; file artifacts as `docs/calibration/soak-week<N>/` (or the location the first sitting establishes — then stick to it):
  - `.venv/bin/python scripts/pilot_report.py --db "$DATABASE_URL" --since-days 7 --out week<N>.md`
  - `.venv/bin/python scripts/shadow_report.py --db "$DATABASE_URL" --out-md shadow_week<N>.md` — AI real-world FPR at `t_elevated` + labeled-join count (the §3 week-5 checklist's inputs: FPR ≤5%, ≥30 labeled, sane band distribution).
  - `.venv/bin/python -m scripts.fused_shadow_report --db "$DATABASE_URL" --log /tmp/week<N>.log` — hit/abstain rate + confound regression.
  - `cat /tmp/week<N>.log | .venv/bin/python validation/genre_2026-08/read_shadow_log.py` — abstention rate (reference: hold-out 33.3%, ceiling 50%; much higher = taxonomy doesn't fit seminary writing, much lower = overconfident on unseen genres; check label shifts for sermon-shaped errors).
  - `cat /tmp/week<N>.log | .venv/bin/python scripts/characteristic_soak_report.py` — applied% + median dispersion; topic d-distribution + mass above 0.25.
  - `python -m scripts.tier17_report --db "$DATABASE_URL"` — READY/NOT READY.
- [ ] **Step 3:** Latency check against the tripwire.
- [ ] **Step 4:** Append one row to the results table below (in this file), one PILOT_LOG line, commit: `git add docs/superpowers/plans/2026-09-07-mvp-launch-part7-shadow-soak.md docs/PILOT_LOG.md docs/calibration/ && git commit -m "Add soak week <N> reading"`. Index row → `soaking (week <N>)`.

**Results table** (one row per weekly reading; fill in place):

| Week | Traffic (scored subs) | Genre abstain % | Topic mass>0.25 | Char applied % / med. dispersion | Fused hit % / confound slope | AI FPR / labeled n | Tier 17 | Latency ok? |
|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | |
| 2 | | | | | | | | |
| 3 | | | | | | | | |
| 4 | | | | | | | | |

### Task 3: Soak close (after ≥4 weekly readings on real traffic)

- [ ] **Step 1 (⛔ HUMAN):** `CHARACTERISTIC_WEIGHTS=off` → deploy. Non-negotiable regardless of what the numbers say — the standing per-request cost ends with the soak.
- [ ] **Step 2:** Write the summary at `docs/calibration/soak_<YYYY-MM>.md`: per mechanism, the decisive number, its reference point, and one recommendation — `enable-candidate` (points at the mechanism's own enablement runbook/gate), `inert in production` (the GENRE_INVARIANT_WEIGHTS outcome — record it plainly), or `needs-work` (with what's missing). **Every enable is a separate human-approved act outside this effort**: Tier 17 via `docs/TIER17_ENABLEMENT_RUNBOOK.md`; AI-likelihood via `docs/PILOT_RUNBOOK.md` §3's week-5 checklist; genre/topic/characteristic/fused per their CLAUDE.md flag rows (G7 for topic explicitly cannot pass from shadow data — it needs an `on` re-measure on its own corpus).
- [ ] **Step 3:** PILOT_LOG line; index row Part 7 → `done @ docs/calibration/soak_<YYYY-MM>.md`; `git add … && git commit -m "Add shadow-soak close-out summary"`.

## Self-Review Notes

- Flag names, shadow semantics, the dispersion/abstention/confound framing, and the latency cost are from the CLAUDE.md flag table and `students_scoring.py` (verified 2026-09-07). The 2×-baseline tripwire and the ≥4-week duration are this plan's own operational choices — adjust at the first sitting if the operator prefers, but write the chosen values into the PILOT_LOG line so the soak has fixed rules before data arrives.
- If Part 3's readers are not yet merged when Task 1 runs, the flags may still flip (rows and log lines accumulate regardless); the week-1 reading then simply starts later — data is not lost, only unread.
