# MVP Launch Part 3 — Shadow-Soak Readers

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read `2026-09-07-mvp-launch-index.md` §Global Constraints first — they all apply here.

**Goal:** The two soak instruments that currently have no reader get one, with tests: `scripts/fused_shadow_report.py` (nothing reads the `fused_scores` rows `FUSED_SCORE_SHADOW=1` persists — and the baseline-volume confound analysis those rows exist for is the explicit gate on `FUSED_SCORE_ENABLED`) and `scripts/characteristic_soak_report.py` (nothing parses the `characteristic_weights … dispersion=…` INFO lines, and dispersion is CLAUDE.md's named decisive number for that soak). With these, Part 7's week-1 reading is a command, not a research project.

**Architecture:** Mirror the two existing reader idioms rather than inventing a third: DB-report scripts follow `scripts/shadow_report.py` (sections, `--out-md/--out-json`) with `scripts/tier17_report.py`'s dual `--db` (SQLite path or `postgres://` URL, read-only in both modes — mandatory because post-cutover the rows live in Postgres); log-line readers follow `validation/genre_2026-08/read_shadow_log.py` (stdin-or-file, regex not anchored to line start so Render prefixes parse, and **exit 1 distinguishing "shadow never ran" from "ran, zero events"**).

**Tech Stack:** stdlib + the repo's existing store API (`original.store.put_fused_score` / `get_fused_scores`); pytest; ruff. No new dependencies.

**Venue:** cloud session (or any checkout). Python is the checkout's `.venv/bin/python`. New scripts live outside `--cov=original`, so the CI coverage floor is unaffected; their tests must simply pass.

## Global Constraints (additional to the index's)

- Readers are **read-only** against any real database: SQLite opened `?mode=ro`, Postgres sessions opened with `default_transaction_read_only=on` (both idioms are in `scripts/tier17_report.py` — copy them).
- **No student ids** in any output; per-student sections use opaque ordinal labels (`student 1…n` by row count), same rule as the log lines themselves.
- New test files follow the mapper convention (`tests/test_<module-stem>*.py`) so the changed-tests pre-push hook associates them.
- Verdict thresholds printed by the readers are *reporting* heuristics, not enablement authority — every verdict line must say which human-owned gate it feeds.

## Verified interfaces (2026-09-07 — reconcile at execution)

- Log lines (`original/routers/students_scoring.py`): `topic_inflation mode=%s d=%s mean_inflation=%s deviation=%.4f deviation_inflated=%s` (:256-265) · `characteristic_weights mode=%s outcome=%s dispersion=%s deviation=%.4f deviation_preview=%s`, outcome ∈ {applied, abstain}, `dispersion` prints `None` on abstain (:278-287) · `fused_score outcome=%s reason=%s n_peers=%d n_baselines=%d` (:406-412).
- Store API: `put_fused_score(submission_id, student_id, fused_log_odds, probability, band, channels: dict, model_version="", baseline_samples=None, reference_profiles=None)` (`original/store.py:1290`); `get_fused_scores(student_id=None, limit=500)` (`:1341`).

---

### Task 0: Collision check

- [ ] **Step 1:** `ls scripts/ | grep -i "soak\|fused"` and `git log --oneline -5 -- scripts/` — PR #194's campaign-03 proposed a `scripts/shadow_soak_report.py` covering similar ground. If a reader for either channel already landed, STOP: extend it in place instead of shipping a duplicate, and report the changed scope in the PR.

### Task 1: `scripts/fused_shadow_report.py` (worked example, TDD)

**Files:**
- Create: `scripts/fused_shadow_report.py`, `tests/test_fused_shadow_report.py`

**Interfaces:**
- Consumes: `fused_scores` rows via a read-only connection (columns per `original/db/models/live.py` / `store.py:1290`); optionally the `fused_score outcome=…` INFO lines via `--log FILE` (the DB cannot see abstains — rows are only written on hit — so abstain rate, half the soak signal, is log-only).
- Produces: the weekly fused reading Part 7 Task 2 cites by exact command.

The C1 confound is the whole point: the compression channel's distance falls as a student's baseline grows (measured 0.799 @ 3 baselines → 0.730 @ 48), so `threshold_fa5/fa1` — selected on a corpus where every author has exactly 3 baselines — are not yet meaningful on real students. `baseline_samples`/`reference_profiles` are persisted per row precisely so this report can regress the confound out; `FUSED_SCORE_ENABLED` stays off until that analysis lands (CLAUDE.md flag row).

- [ ] **Step 1: Write the failing tests.** In `tests/test_fused_shadow_report.py`, build two synthetic corpora through `original.store.put_fused_score` against a tmp `ORIGINAL_DB`: a *confounded* corpus (log-odds decreasing in `baseline_samples` across 10 students, 60 rows, baseline counts 3–30) and a *flat* one. Assert: report totals/date-range; band counts; per-student concentration uses ordinals, no ids; the confound section reports a negative Spearman rho and binned means (3–5 / 6–10 / 11–20 / 21+) trending down for the confounded corpus and `confound regression: INSUFFICIENT DATA` for a corpus under the floor (≥50 rows across ≥8 students with baseline-count spread ≥5); empty-DB and missing-table cases print the `shadow_report.py`-style guidance instead of a traceback; `--log` fixture (a dozen `fused_score outcome=…` lines with Render-style prefixes) yields hit/abstain counts and dominant abstain reason.
- [ ] **Step 2: Implement.** Sections in `shadow_report.py`'s order: header (db, row count, date range) → band counts → probability and log-odds deciles (`_dist` idiom) → per-student concentration → **C1 confound**: Spearman rho of `fused_log_odds` vs `baseline_samples` (stdlib rank implementation — no scipy), the binned means table, the compression-channel value parsed from `channels_json` regressed the same way, a one-sentence plain-English slope statement, and the verdict line `confound regression: <OK to analyze | INSUFFICIENT DATA (need ≥50 rows, ≥8 students, spread ≥5)> — feeds the human FUSED_SCORE_ENABLED decision, not a gate by itself`. Dual `--db` per tier17_report; `--out-md/--out-json` per shadow_report; `--log` optional.
- [ ] **Step 3: Run.** `.venv/bin/python -m pytest tests/test_fused_shadow_report.py -v` → all green; then a smoke run `.venv/bin/python -m scripts.fused_shadow_report --db /tmp/does-not-exist.db` → the guidance message, exit 1, no traceback.
- [ ] **Step 4: Commit.** `git add scripts/fused_shadow_report.py tests/test_fused_shadow_report.py && git commit -m "Add fused-score shadow reader with the C1 baseline-volume confound regression"`

### Task 2: `scripts/characteristic_soak_report.py` (log reader)

- [ ] **Step 1: Tests first**, in the idiom of Task 1 Step 1 (`tests/test_characteristic_soak_report.py`): fixtures of real-format lines with Render timestamp prefixes covering applied/abstain/`dispersion=None`, plus `topic_inflation` lines; assert the outputs in Step 2 and both exit-code behaviors.
- [ ] **Step 2: Implement**, mirroring `read_shadow_log.py`: stdin or file arg; regex anchored on `characteristic_weights ` matching `mode=(\S+) outcome=(applied|abstain) dispersion=(\S+) deviation=([0-9.]+) deviation_preview=(\S+)` with `None` handled; report n, mode split, applied-vs-abstain rate, dispersion distribution over applied rows (median/p90/max — the decisive number), |preview − deviation| distribution, and an explicit inertness verdict (abstain-dominant or median dispersion ≈ 0 → print the GENRE_INVARIANT_WEIGHTS cautionary sentence and "mechanism inert in production — corpus results do not transfer"). Second section: `topic_inflation` lines → d-distribution, mass above the 0.25 fire threshold (below it the mechanism is structurally off), degraded share. Per-signal absence reported independently; **exit 1 with the "this is NOT a zero rate — shadow was not running" message only when *neither* signal appears**.
- [ ] **Step 3: Verify + commit.** Tests green; `printf '' | .venv/bin/python scripts/characteristic_soak_report.py` → not-running message, exit 1. `git add scripts/characteristic_soak_report.py tests/test_characteristic_soak_report.py && git commit -m "Add characteristic-weights and topic-inflation soak log reader"`

### Task 3: Docs wiring

- [ ] **Step 1:** Add both commands to `docs/PILOT_RUNBOOK.md` (extend §5's weekly block or a new §3d "Soak readers"): `.venv/bin/python -m scripts.fused_shadow_report --db "$DATABASE_URL"` and `render logs --tail 100000 | .venv/bin/python scripts/characteristic_soak_report.py`. One sentence each on the decisive number.
- [ ] **Step 2:** `git add docs/PILOT_RUNBOOK.md && git commit -m "Add the two new soak readers to the pilot runbook's weekly cadence"`

### Task 4: Part completion

- [ ] **Step 1:** Full suite (0 failed) and `ruff check`/`ruff format --check` clean on the new files; budget the suite's real runtime.
- [ ] **Step 2:** Update the index dashboard row for Part 3 → `done @ both readers green on fixtures`; commit `git add docs/superpowers/plans/2026-09-07-mvp-launch-index.md && git commit -m "Add Part 3 completion to the MVP-launch dashboard"`. Push branch, one PR.

## Self-Review Notes

- Log formats and `put_fused_score`'s signature were verified against `students_scoring.py`/`store.py` on 2026-09-07 (line refs above); re-grep before coding — Part 2 may land #195, which touches scoring.
- The confound-floor numbers (≥50/≥8/spread ≥5) are reporting heuristics chosen for this plan, not derived constants — the implementer sanity-checks them against `original/fusion/` docs and adjusts with a comment; the enablement judgment stays human either way.
- The `topic_inflation` section and the `--log` option are deliberate small scope-adds beyond the two named gaps (rationale: Part 7 needs weekly topic readings and abstain counts, and neither has any other reader); drop them only if a collision from Task 0 already covers them.
