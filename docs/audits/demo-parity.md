# Demo parity audit: navy prototypes vs the real Original staff pages

Date: 2026-11-13. Scope: `demo/prototypes/navy/original-*.html` (the demo) against
`demo/original/*.html` (the live staff pages). Presentation only: no engine, score or
threshold changes (plan Global Constraints). Statuses were checked by reading the page
code and by running the real pages against a local pilot-mode server with both evidence
flags on (see "How the screenshots were made").

Status words: `works` (does the same thing as the demo), `looks clickable, does nothing`,
`missing` (no counterpart), `numbers only` (counterpart exists but shows only figures
where the demo shows text). The "Closed by" column names the plan task that fixes it.

## Facts established before the audit

1. Writing State's `makeEvidence` (`writing-state.html`, about lines 890-946) is numbers
   only and says in a comment that the server returns no text positions. That is stale:
   with `EVIDENCE_PASSAGES_ENABLED=1` the server sends located passages in
   `evidence.all_features[].this_paper.examples` and `.past_papers.examples`
   (`passage, match_start, match_end, ...`), and `evidence.baseline_papers[]` names each
   past paper. The page never reads them.
2. `.hero-evi` is `position:absolute; inset:0; z-index:6` over `.hero-inner`
   (`writing-state.html:136`). When a habit panel is open it covers the triage row
   ("Prepare conversation packet", "See it side by side", "Looks fine", "Have a
   conversation"), so those buttons cannot be reached until the panel is closed. The demo
   puts the panel in the same place but its triage buttons are not needed while reading.
3. The pilot's root `/` redirects to `/bluebook/` (`run.py` `demo_root`) and the SPA picks
   the `dashboard` screen for staff (`demo/bluebook/app.jsx` `autoScreen`). A teacher
   whose workspace has Original therefore lands in Collections, not Original.
4. The real pages already carry the frame photos (`demo/original/assets/`, credited in
   `assets/CREDITS.md`): Overview and Voice baseline use `radcliffe-night-stars.jpeg`,
   Students `st-andrews-quad.jpg`, Writing State `radcliffe-observatory-watercolour.jpg`.
   Photo presence is not the gap; the gaps are listed under "Visual tuning".
5. In the "before" run the sample analysis (3 past papers) is flagged thin by the server,
   so the Side by side page's preliminary chip reads "Not enough writing on file to
   compare yet." (real behaviour, kept).
6. Screenshots of the real pages are the 1440x1000 viewport: the real pages scroll inside
   a framed container (`#right-scroll`), so a full-page capture is the same size. The demo
   packet (`original-flagged.html`) scrolls the page, so it is much taller than the
   real packet's viewport capture.

## 1. Writing State: `original-quantum.html` -> `writing-state.html`

| Demo element | Demo behaviour | Real counterpart | Status | Closed by |
|---|---|---|---|---|
| Habit bar in State Vector (`#heatmap` column) | Opens that habit's evidence panel (`__evi.open(code)`): this-paper passages with highlights beside past-work passages; hover lifts the baseline bar | Same column, `EVI.open(code)` once `S.base` exists (else pins the tier) | `numbers only`: panel shows a big number each side, no text, no highlights | 2 |
| Tier band label under the bars (`.hbnd`, e.g. "T1 · Wording") | Click pins/unpins the tier (filters bars, highlights radar, fills Feature Detail) | `.hbnd` click `CHIPS.toggle(tier)`, keyboard accessible | `works` | none (2 adds "opens most different habit" only for chips) |
| Tier chip (T1 Wording ... T16, `.tchip`) | Hover previews, click pins; when the panel is open, click opens that tier's most different habit | Same code (`makeChips`) | `works` for pinning; the follow-on habit opens a numbers-only panel | 2 |
| Family header Surface / Discourse / Rhetorical (`.tgrp-h`) | Hover previews, click pins the whole family and lists it in Feature Detail | Same code | `works` | none |
| Radar (`#radar-canvas`) | Hover shows tier tip; the card subtitle says "click to pin" | Hover tip only; clicking the radar does nothing (same as demo) | `looks clickable, does nothing` (subtitle misleads in both) | 2 (reword to "tier chips: click to pin") |
| Feature Detail row (`.fd-row`) | Opens the same habit panel | Row click `EVI.open(code)` when a baseline exists; tabbable button | `numbers only` | 2 |
| "Largest differences" rows (same list after analysis) | Opens habit panel | Same, server's own ordering | `numbers only` | 2 |
| Particle-pattern toggle ("Baseline p" / "This submission", `.fpq-btn`; the demo's own label for it uses a banned word) | Recolours the particle pattern | `setView` recolours, reseeds | `works` | none |
| Particle-pattern canvas (`#fpq-canvas`) | Decorative, mouse repel | Same (code identifier `Fingerprint` only) | `works` (decorative) | none |
| "Prepare conversation packet" (`.tri-btn.packet`) | Link to `original-flagged.html` | Link to `packet.html` after `storeForPacket()` | `works` when no panel is open; **covered by the open panel** | 2 |
| "See it side by side" | Not in the demo (demo packet has quotes inline) | `#tri-evidence`, shown only when the response has `evidence` | `works` when no panel is open; **covered by the open panel** | 2 |
| "Looks fine" / "Have a conversation" (`.tri-btn`) | Marks the choice, shows a message | `triage()` stores `professorAction`, shows "Recorded: ..." | `works`; covered by open panel | 2 |
| Demo close button, "Back to <banned word>" (`#evi-close`) | Closes panel | "Back to the pattern" `#evi-close`; Escape also closes | `works` (wording differs) | 2 |
| "Where it appears" tabs (`.evi-tab`, one per paragraph) | Pages through passages (one tab per place the habit shows) | none | `missing` | 2 |
| Panel "This submission" / "Their own past work" columns with `<mark>` highlights and source footer ("15 Jan, in-class essay") | Quoted sentences | Big number and one sentence; source line shows assignment, word count and counted-sample phrase | `numbers only` | 2 |
| "What to notice" line | Demo packet only | none on Writing State | `missing` | 2, 3 |
| In-panel link to Side by side | none in demo | none | `missing` | 2 |
| "Voice baseline: how James writes" (`.feat-link`) | Link to `original-baseline-voice.html` | `#voice-link` to `baseline.html?student=<id>`, hidden until a student loads | `works` | none |
| "Change student" / "Analyse another" | n/a (demo has one fixed student) | Real controls | `works` | none |
| Avatar menu, nav pills (Overview, Students, Submissions, Collections, Reports) | `location.href` to demo pages | Links to real pages; "Collections" opens `bluebook.html` | `works` | 6 (Collections intent) |

Observed in the "before" run: the first heatmap bar's panel reads "baseline 0.00 / this
paper 0.00" with two large `0.00` numbers and large empty space beneath: that is the
"numbers only" state to replace.

## 2. Packet: `original-flagged.html` -> `packet.html`

| Demo element | Demo behaviour | Real counterpart | Status | Closed by |
|---|---|---|---|---|
| "Back to analysis" (`a.back`) | Link back to quantum | `#back`, keeps `?student=` | `works` | none |
| "Print packet" | `window.print()` | `#print-btn` | `works` | none |
| "What the analysis found" paragraph | Plain English with tier colours | Present, built from the real habit list | `works` (wording differs by design: real data) | 4 (check wording) |
| "Side by side" `.ex` cards: this-paper sentences and past-paper sentences, highlights, "What to notice" | Three example cards | "Furthest from their usual range" cards with numbers only; no quotes | `numbers only` | 4 |
| "Where his baseline comes from" table (sample, date, how written, length) | Table + thin-baseline note | "Where their baseline comes from" section (`#p-baseline`, `.prov` table, `packet.html` ~248, JS `baselineTable`): columns Sample, Date, How it was written, Length, built from `GET /students/{id}` samples and per-sample word counts | `works` (same four columns; reads the student record, not `evidence.baseline_papers`, so titles/dates/provenance are already real). Optional: check the thin-baseline sentence under it matches the demo | 4 (check only) |
| "Having the conversation" worth doing / avoiding | Two lists | Present (verify in Task 4) | `works` | none |
| Signature / outcome lines, footer | Print footer | Present | `works` | none |

## 3. Overview: `original-dashboard.html` -> `index.html`

| Demo element | Demo behaviour | Real counterpart | Status | Closed by |
|---|---|---|---|---|
| Student/flag row (`.flag-row`, whole row) | Navigates to that student's analysis (`data-href`) | Whole row click calls `openStudent(id)`: swaps the left rail to that student's counts; never leaves the page | `works`, but differently: it opens an in-page summary, not the student | 5 |
| "stats" button on a row (`.stats-btn`) | Opens the in-page student summary, `stopPropagation` | Same (`openStudent`) | `works` | none |
| "Back to term view" (`#back-term`) | Returns left rail to term summary | Same | `works` | none |
| Sensitivity options (`.sens-opt`) | Choose threshold wording, demo-only | Not on the real page (settings is separate) | `missing` (by design, no engine controls) | none |
| "Adjust in Settings" / "Open Students" link | Link | "Open Students" link | `works` | none |
| Notifications menu item | Does nothing (`return false`) | Not present | `missing` (demo itself is a dead end) | none |
| Hover state on rows (gold left edge, tint) | Present | CSS present (`.flag-row:hover`) | `works` | 5 (verify after) |

## 4. Students: `original-students.html` -> `students.html`

| Demo element | Demo behaviour | Real counterpart | Status | Closed by |
|---|---|---|---|---|
| Student row (`.r-row`) | Goes to that student's analysis page (`original-quantum.html?student=`) | Whole row is an `<a>` to `baseline.html?student=<id>` (Voice baseline) | `works` (different destination: baseline, not Writing State) | 5 |
| Filter chips All / Flagged / No baseline / Writing like themselves | Filter rows | Chips All / Ready / Building / Needs more | `works` (real chips are baseline-readiness only: honest) | none |
| "Find a student" search | Filters | `#q` input filter | `works` | none |
| "Add student" | Demo no-op | Link to `/bluebook/#students` | `works` (leaves Original; needs the "stay in Collections" hash, Task 6) | 6 |
| Stat strip (Enrolled, Baseline ready ...) | Static | Real counts | `works` | none |
| Deviation column | Bar and number | `-` with "Deviation appears here once Original keeps analysis results." | `numbers only` / empty by design (no stored analyses) | none |

## 5. Voice baseline: `original-baseline-voice.html` -> `baseline.html`

| Demo element | Demo behaviour | Real counterpart | Status | Closed by |
|---|---|---|---|---|
| "The short version", "Signature habits", "Where the baseline came from" cards | Static text | Same three sections plus real add-writing and shared-paper panels | `works` | none |
| Tier rows in Signature habits (`details.tier>summary`) | Expand/collapse | Same | `works` | 5 (check back/cross links) |
| Back to students / analysis | Nav pill "Students" | `All students` side link, `#analyse-link` to `writing-state.html?student=` | `works` | none |
| "Add a fourth sample" CTA to Collections | Link to demo Collections | `#bb-cta` to `/bluebook/#students` | `works` (needs the Collections-stay hash, Task 6) | 6 |

## 6. Pages with no requested screenshot but in scope of the brief

| Demo page | Real page | Notes | Closed by |
|---|---|---|---|
| `original-review.html` (Submissions queue; chips All / Reads differently / Worth a look / Cleared; `.q-row` rows to the paper) | `submissions.html` | Real page lists sealed Collections exams; no deviation-severity chips (honest: no stored analyses). Rows `works`. | none |
| `original-reports.html` (course tabs `.ctab`, weekly columns to `original-review.html?week=`, Print) | `reports.html` | Print and course tabs `works`; week column links lead to Submissions with a week filter in the demo, check real equivalent in Task 5 | 5 |
| `original-voice.html` (student voice: family tabs `.fam`, `.w-row` links, "See what makes it yours" anchor) | `voice.html` | Student-facing: shows no scores, intentionally unchanged (constraint 3) | none |
| Navy pages "Collections" pill | `bluebook.html` | Opens the Collections sessions page, not the SPA | 6 |

## Wording gaps

- Demo close button uses a banned word; real: "Back to the pattern". Banned words must not
  appear in visible text (constraint 4), so the real wording stays; keep them out of new strings.
- Demo header copy "Original analysis / Writing State" and "Tier Profile" are the same.
- Demo panel sub-line "How many different words you use vs. your total word count.:" has a stray
  full stop-colon; the real page's description line is cleaner and stays.
- Demo uses first-person/male pronouns ("his own past work", "James"): real pages use the
  student's name and `poss()`; keep that.
- Real panel text for a habit with a baseline: "This paper's value for this habit, on a scale from
  0 to 1" and "The average across N counted samples ..." : keep as the numbers line, add the
  passage columns and a plain "what to notice" sentence (Tasks 2, 3).
- Demo packet "Side by side" intro and "What to notice" use invented reasons. Real text must be
  generated from real numbers only (Task 3 `noticeFor`).

## Layout gaps

- Writing State: open habit panel overlays and hides the triage buttons (fact 2). Panel should
  sit in normal flow below the triage row (Task 2).
- Writing State habit panel has two big-number columns with large empty height; the demo
  columns are filled with quoted sentences and a "Where it appears" tab row above them.
- Overview rows navigate nowhere; the demo opens the student (Task 5).
- Packet: real packet is narrower (940px) and lacks the case/prepared-for header block that the demo has (case number stays out, it is
  invented). The baseline table already exists in the real packet.
- Students: the real list is a single `<a>` per row (good); no "attention" sorting or flagged
  column because there are no stored analyses.

## Visual tuning gaps

- Frame photo and gradient: present on real pages (fact 4). The Writing State photo is much
  dimmer than the demo's (the demo overlays a lighter `.frame::after` gradient); check the
  overlay strengths after Task 2 changes the layout.
- Demo shows a gold "Fictional demonstration" ribbon: intentionally not on real pages.
- Hover transitions: demo `.tl-row`, `.fd-row`, `.tchip` use `.13s`-`.18s` transitions and a gold
  left-edge on row hover; real CSS has the same for `.flag-row`, `.r-row`, `.fd-row`; verify
  `.ex` cards on evidence.html/packet.html get the same hover/focus polish (Tasks 3, 5).
- Focus rings: real pages add `:focus-visible` outlines; keep.
- Spacing and typography use the same variables (`--display`, `--body`, `--mono`): the
  difference is the larger top header block on the demo students page (title 2.4rem plus
  stat strip); real header is slightly more compact. Low priority (Task 5).

## Fix list (by task)

1. Task 1 (this): audit, screenshot script, before/demo PNGs.
2. Task 2: Writing State habit panel with real passages and "Where it appears" tabs; plain note for
   whole-text/off/not-compared habits; every entry point (bars, Largest differences rows, chips,
   band labels, family headers) opens or pins something; panel no longer covers the triage
   buttons; "See it side by side" link inside the panel; call `noticeFor`; reword the radar
   subtitle so nothing looks clickable and is not.
3. Task 3: `EvidenceView.noticeFor`, use it on Side by side, past-paper labels from
   `baseline_papers`, `#m-<code>` hash opens and scrolls to the row, card polish.
4. Task 4: Packet "Side by side" section with real first quotes (the baseline table already
   exists; only verify it).
5. Task 5: Overview row click opens the student (Writing State), hover states; Students /
   Voice baseline cross links; tuning of decorative pieces and overlays.
6. Task 6: Pilot root opens into Original for staff with Original; Collections links carry a
   "stay" hash; `render.yaml` flags; startup log line; student-never-sees-evidence test.
7. Task 7: E2E coverage for all of the above.
8. Task 8: "After" screenshots with the same script, "Status after" column here, STATUS.md.

## How the screenshots were made

Server (own port, never touching other servers), from the repo root:

```
ORIGINAL_ENV=pilot SELF_SERVE_SIGNUP=0 SECRET_KEY=ci-test-only-secret-do-not-deploy \
MAINTENANCE_TOKEN=ci-test-only LOGIN_THROTTLE_MAX_ATTEMPTS=500 \
EVIDENCE_PASSAGES_ENABLED=1 PRELIMINARY_SCORE_ENABLED=1 ORIGINAL_DB=$TMPDIR/parity.db \
/Users/andrew/Code/Orig/.venv/bin/python run.py --demo --frontend-dir demo --port 8017 --skip-seed
(cd demo/prototypes/navy && /Users/andrew/Code/Orig/.venv/bin/python -m http.server 8018)
MAINTENANCE_TOKEN=ci-test-only PARITY_BASE_URL=http://localhost:8017 \
PARITY_OUT=docs/audits/demo-parity/before PARITY_DEMO_URL=http://localhost:8018 \
PARITY_DEMO_OUT=docs/audits/demo-parity/demo node demo/bluebook/e2e/tools/parity-screenshots.mjs
```

Output: `docs/audits/demo-parity/before/01-overview ... 07-voice-baseline.jpg` (real pages) and
`docs/audits/demo-parity/demo/original-*.jpg` (navy prototypes, including
`original-quantum-habit-open.jpg`).
