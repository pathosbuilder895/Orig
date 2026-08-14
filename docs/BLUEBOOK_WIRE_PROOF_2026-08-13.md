# Bluebook wire-by-wire live proof — 2026-08-13

Walked against a local server running this branch (`python run.py --demo
--frontend-dir demo --skip-seed --port 8010`, worktree `profiles.db`
pre-seeded with the 5 synthetic students). Every wire below was driven
through the real UI in a browser and verified against the network log
and the database, in one continuous session. Evidence quoted inline;
exam id for the sitting was `c60e0a31bb5a44e8`.

| Wire | Verdict | Evidence |
|---|---|---|
| Bundle → exam room | **PASS** | `/bluebook/` served the committed `bluebook.bundle.js`; landing, dashboard, and exam room all rendered from it. |
| Magic link → exam room | **PASS** | `scripts/roster_links.py -t demo -e "Sprint Wire Proof — Parables Essay"` link redeemed: `GET /bluebook/launch?t=…` → audit row `bluebook_magic_launch` for `demo:094ac802e2debf28` (result ok) → browser landed on that exam's instructions page. |
| Exam create → backend | **PASS** | "+ New Examination" → `POST /bluebook/exams` → 201; exam listed from the server afterwards. |
| Server-pinned deadline | **PASS** | First `POST /bluebook/exams/{id}/session` → 200 `{started_at: 14:09:04, deadline_at: 14:39:04, duration_seconds: 1800}`. Second call three minutes later returned the **identical** row (`server_now` advanced to 14:12:01) — reopening cannot restart the clock. |
| Degrade-open on session failure | **PASS** (found live) | The demo's canned exams are client-side fixtures; sitting one produced `POST /bluebook/exams/1/session` → 404 and the exam room **opened anyway** on the local countdown, per robustness spec §1 ("never strand a student"). |
| Keystroke record → database | **PASS with caveat** | Sealed sitting persisted `keystroke_data` on a `provenance=proctored` sample (`wordCount=126`). Caveat: the browser-automation `type` action inserts text without per-key events, so `keystrokes=[]` in this walk — the capture handler is exercised with real key events by the Playwright e2e suite; a human sitting will fill the arrays. |
| Seal → exactly once | **PASS** | Both seals: `POST /students/{id}/baseline` → 200, `POST /bluebook/submissions` → 201, one `bluebook_submissions` row per sitting with `submission_uuid`, `late=0`. |
| Cold-start correction state | **PASS** | Sitting 1 (no prior baseline): score → 404, panel rendered disabled with "This submission wasn't scored — no verdict to correct." |
| Score → verdict | **PASS** | Sitting 2 (1-sample baseline): `POST /students/{id}/score` → 200; deviation 0.618, action `schedule_conversation`, rationale correctly caveats the 1-sample baseline and 115-word length as provisional. |
| Correction → audit | **PASS** | Panel: Correct + notes → `POST /submissions/{uuid}/correct` → 200; history rendered "✓ Verdict correct · just now" without refetch; DB: `corrections` row (is_correct=1, notes intact, original action/score preserved) + `audit_log` action=`correction`. |
| Phone park loop | **PASS** | Proctor page → `POST /proctor/park/open` → 200 `{park_token, qr_url}`; `parked.html?t=…` on a second (mobile-sized) tab → `POST /proctor/park/beat` → 200; proctor tile read "W.P. — Parked, last seen 6s ago". |
| Late tagging | **not walked** | Would require sitting out a 30-min deadline; covered by `tests/test_bluebook_api.py` late-tagging tests. |
| Offline banner / retry | **not walked** | Browser tooling lacks offline emulation here; covered by `exam-robustness.spec.mjs` e2e. |
| Original → external Bbook | **blocked** | No Bbook instance/secret configured anywhere (by design until provisioned) — see OPS_RUNBOOK Bbook rows. |

## Observations filed (not failures)

1. **Automation typing produces empty keystroke arrays** — noted above;
   worth one human proctored sitting before trusting live keystroke
   volume counts in `tier17_report`. Note the report counts a sample as
   "with keystroke data" if the blob is non-empty (`wordCount` suffices)
   — the non-degeneracy gate is what protects READY from empty-array
   samples.
2. **Magic-link sitting still displays "Candidate No. 00042"** in the
   exam header (the demo's stock label) even when a bound `sid` is
   present. The *binding* is correct (audit row + localStorage session);
   links are name-free by default, so this is cosmetic — but a proctor
   comparing screens to a roster may want the bound initials once
   `--include-name` links are used.
3. **`genre: "correspondence"` on every baseline_add audit row** — the
   broken `resolve_genre` terminal-else visible in live data;
   corroborates `docs/research/2026-08-13-genre-resolver-fix-scoping.md`.
