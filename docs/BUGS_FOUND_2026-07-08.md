# Bugs found while using the app — 2026-07-08

Live QA pass against the running preview (`original-demo` app, port 8002, commit `835b6557` = current `main` tip) — clicking through the actual professor/admin/operator/Bluebook surfaces as a user would, watching network/console/server logs, and reading source to confirm root cause rather than guessing. Each finding below was reproduced and traced to a specific line, not inferred from a screenshot alone.

Severity is about professor/student-facing trust and correctness, not code elegance.

---

## Confirmed bugs

### BUG-1 — History tab shows "No scored submissions yet" immediately after scoring a submission
**Severity: High.** A professor who scores a submission and then clicks the in-panel **History** tab (the single most natural next action) sees *"No scored submissions yet for this student"* — even though the score just completed successfully. This directly contradicts the professor's own recent action and could make them re-score, assume the system silently dropped their work, or lose trust in the record-keeping.

**Root cause, confirmed:** the data is *not* lost — `localStorage['original_portfolio_<student>']` correctly contains the new entry (verified directly). The bug is a missing re-render: `demo/professor.html:1140`'s History tab button only calls `switchTab('history')`, which just toggles CSS visibility (`demo/professor.html:2225-2231`) — it never calls `renderHistory()`. A *different* code path, `navSubmissions()` (triggered by the left-sidebar "Submissions" link, `demo/professor.html:3847`), does call `renderHistory()` before switching tabs, and that path shows the entry correctly. Ironically, a code comment at `demo/professor.html:2310-2312` says this exact bug ("History contradicted the professor seconds after they scored a paper") was already fixed once — the fix wired up the data write (`appendProfessorAnalysis`, line 2801) but missed wiring the read-path refresh for this specific button.

**Fix:** add `renderHistory()` to the History tab button's click handler (or, better, call it unconditionally inside `switchTab()` when `name === 'history'`, so this can't regress a third time via some other entry point).

**Repro:** Dashboard → Analyze Submission → Analyze Writing → click "History" tab. Compare with: Dashboard → click "Submissions" in left sidebar → History tab shows the same entry correctly.

---

### BUG-2 — Operator dashboard shows two different totals for the same numbers on the same screen
**Severity: Medium-High** (data-integrity signal for an "all schools healthy" operational view). The hero banner reads *"24 students across all institutions · 5 submissions scored,"* while the stat tiles directly below it — same page, same load — read **114 total students** and **12 submissions**. This isn't a loading-order flicker; it's still mismatched well after all network activity settles.

**Root cause, confirmed:** two independent server-side aggregates disagree, and the frontend paints them into two different DOM locations without reconciling them.
- `loadSystemStats()` (`demo/operator.html:~330-345`) fetches `/admin/health` and writes `health.student_count`/`health.total_submissions` into **both** the hero (`renderOperatorHero`) **and** the four `#ssTenants/#ssStudents/#ssSubmissions/#ssAudit` tiles (lines 331-334).
- `loadTenants()` (`demo/operator.html:351-381`) then fetches `/tenants`, fans out a `/tenants/{id}/stats` call per tenant, **sums those client-side**, and calls `renderOperatorHero()` **again** with the new sum — but nothing re-writes the four tile elements. The tiles are set exactly once, at initial load, and never revisited.

Net effect: the tiles permanently show `/admin/health`'s number (114/12), the hero permanently shows the sum-of-per-tenant-stats number (24/5), and the two never reconcile once `loadTenants()` finishes.

**This also exposes a real backend question**, not just a frontend one: why does `/admin/health`'s own counter (114 students) differ so much (~5×) from summing `student_count` across every `/tenants/{id}/stats` response (24)? Either `/admin/health` counts something broader than live tenants (e.g. orphaned/legacy profiles), or the per-tenant stats endpoint is undercounting for some tenants. Worth a dedicated look at `original/api.py`'s `/admin/health` handler vs. `/tenants/{id}/stats` before trusting either number operationally.

**Fix (frontend, minimum):** either stop calling `renderOperatorHero()` a second time with a different metric, or also refresh the four tiles from the same `totalStudents`/`totalSubs` values so the two summaries can't diverge on screen.

---

### BUG-3 — Admin Console silently 403s on exactly two tenants, with zero user-visible error
**Severity: Medium.** On the Admin Console, background per-row detail fetches (`GET /students/{id}`) for `northfield:alpha01`, `rosteru:alice`, and `rosteru:bob` return `403 {"detail":"Cross-tenant access denied."}` — while the *same* System Admin session successfully fetches cross-tenant detail for `preview-demo:*`, `live-demo:*`, `browser-demo:*`, and three separate `pilot-seminary:*` students in the identical loop, all 200 OK. This is asymmetric, not a blanket permissions gap.

**Two distinct things worth fixing regardless of cause:**
1. **The asymmetry itself.** Something about the `northfield` and `rosteru` tenants specifically denies a System Admin read that every other tenant allows. ⚠️ **Caveat before treating this as a regression:** another session in this repo is actively mid-edit on `original/api.py`/`original/store.py`/`original/repository.py` with new authz test files in progress (`tests/test_baseline_provenance_authz.py`, `tests/test_correction_authz.py`, `tests/test_magic_launch.py`, `tests/test_scoring_flags.py`), and `rosteru` matches that session's own `scripts/roster_links.py` work. This may be deliberate, not-yet-complete tenant-isolation hardening rather than a bug — **confirm with that work before "fixing" it**, since tightening this could be exactly the intent.
2. **The silence, independent of cause.** Whatever the right authz answer is, the Admin Console currently swallows the 403 completely — no error banner, nothing in the browser console, the affected rows just quietly show incomplete data. That failure-visibility gap is worth closing on its own; it's the same "swallowed exception, no operator visibility" pattern the earlier architecture audit flagged in `store.py`'s persistence layer (finding A1).

---

## Data hygiene found along the way (not a code bug, but actively misleading)

### HYGIENE-1 — 30+ leftover `e2e-tenant-*` tenants permanently polluting the local dev database
While on the Operator dashboard, the "43 institutions" list is padded with dozens of tenants named `e2e-tenant-29480-1783431614398-1`, `e2e-tenant-68100-...`, etc. — clearly Playwright test fixtures from earlier `demo/bluebook/e2e/` runs against this shared local dev DB, never cleaned up. They inflate every "N institutions / N students" figure on both the Admin Console and Operator dashboards, which makes the two-different-totals bug (BUG-2) harder to diagnose and makes the demo data generally unreliable for eyeballing. Any e2e run against the shared dev store (rather than a `--skip-seed` scratch DB, which is what I used for my own verification runs this session) leaves this residue permanently. Worth either a teardown step in the e2e fixtures or a documented "always point e2e at a scratch `ORIGINAL_DB`" rule.

---

## Investigated and ruled out (false alarms — recorded so they aren't re-investigated)

- **"The API's `recommendation.action: 'escalate'` never appears in the UI."** Initially looked like a missing verdict display. Confirmed false: `escalate` → "Needs Review" is a deliberate, correct label mapping (`demo/professor.html:1266`, `onclick="recordProfessorAction('escalate')"` on the button labeled "Needs Review"). The professor-facing UI does show the verdict — it's just relabeled, not raw.
- **Narrative text mismatch** — the plain-English "Grammar patterns and sentence structure shows the largest shift from baseline (score 0.12)" (frontend, tier-level: worst entry in `tier_breakdown`) versus the API's own `recommendation.rationale` string, "Primary anomaly: Dash Rate" (backend, feature-level: worst entry in `destructive_features`). These two explanations of the same scoring event use genuinely different "what's the biggest driver" algorithms and can disagree. **Not currently user-visible as a contradiction** (the API's own rationale text is never rendered anywhere in this UI), so it's not an active bug today — but it's a latent inconsistency worth reconciling before anyone surfaces the raw rationale text in a future UI change (e.g. an admin-facing "why did the API say this" view).

---

## Surfaces checked clean

- Bluebook landing (`/bluebook/`) — loads with zero console errors on the current ESM build, consistent with the 37/37 Playwright pass already verified against this exact commit earlier today.
- The scoring pipeline itself (`POST /students/{id}/score`) — returns a rich, internally coherent payload (tier breakdown, interference features, tension arc, recommendation) with no missing fields or malformed data across three separate calls made during this session (two on James Whitfield, one blend check).
- Dashboard → Students → Submissions nav — all funnel into the same single-page tabbed dashboard by design (not a bug, just the app's information architecture).

---

## Still open from earlier today's work (not rediscovered here, just tracked for continuity)

These were found and fixed or deliberately deferred earlier in today's session — listed here only so this is the one place to check "what's currently broken," not to duplicate their write-ups:

- **`original-pilot` on Render appears never to have been deployed** (`x-render-routing: no-server`, empty `docs/PILOT_LOG.md`) — separate from anything in this app-usage pass; see prior session notes.
- **"Mark Reviewed" (Bluebook Results.jsx) doesn't persist across reload**, and **there's no correction-filing UI in Bluebook** — both blocked on a `store.py`/`api.py` schema change (no link exists yet from a Bluebook submission to its scoring-engine record). Held pending the other session's in-flight `api.py`/`store.py` work landing.
- **10 open Dependabot PRs** (#41–50), untriaged; `sentence-transformers >=5.6.0,<6.0` (#47) is flagged as a possible tier-10 feature-determinism risk and should not be merged without checking `tests/test_tier10_st_backend.py` against it first.

---

*Methodology note: every finding above was verified by reading the actual source and/or checking `localStorage`/network responses directly — not inferred from how something looked on screen. Where I initially suspected a bug and it turned out to be correct behavior (the "escalate" mapping), that's recorded above rather than silently discarded, so the same false lead doesn't get re-investigated.*
