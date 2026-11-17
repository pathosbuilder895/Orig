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

## Status after (2026-11-13)

Re-checked against the current code of branch `claude/original-demo-parity-fe7f3a`
(commits `6ac92ea4..c3e127ba`) and a local pilot-mode server with both evidence flags on.
Words: `works` (does what the demo does, from real data), `unchanged by design` (a
deliberate difference, see the reason), `not done` (with the reason). Image pairs: the
same script (`demo/bluebook/e2e/tools/parity-screenshots.mjs`) produced both sets, at
1440x1000. Before: `docs/audits/demo-parity/before/`; after: `docs/audits/demo-parity/after/`;
navy demo: `docs/audits/demo-parity/demo/`. In the after run the three past papers carry
submitted dates (14 Jan, 11 Feb, 10 Mar 2026), so source lines show dated labels.

Image pairs:

| Page | Before | After |
|---|---|---|
| Overview | [before/01-overview.jpg](demo-parity/before/01-overview.jpg) | [after/01-overview.jpg](demo-parity/after/01-overview.jpg) |
| Students | [before/02-students.jpg](demo-parity/before/02-students.jpg) | [after/02-students.jpg](demo-parity/after/02-students.jpg) |
| Writing State, result | [before/03-writing-state-result.jpg](demo-parity/before/03-writing-state-result.jpg) | [after/03-writing-state-result.jpg](demo-parity/after/03-writing-state-result.jpg) |
| Writing State, habit open | [before/04-writing-state-habit-open.jpg](demo-parity/before/04-writing-state-habit-open.jpg) | [after/04-writing-state-habit-open.jpg](demo-parity/after/04-writing-state-habit-open.jpg) |
| Side by side | [before/05-side-by-side.jpg](demo-parity/before/05-side-by-side.jpg) | [after/05-side-by-side.jpg](demo-parity/after/05-side-by-side.jpg) |
| Conversation packet | [before/06-packet.jpg](demo-parity/before/06-packet.jpg) | [after/06-packet.jpg](demo-parity/after/06-packet.jpg) |
| Packet, Side by side section (new) | none | [after/06b-packet-side-by-side.jpg](demo-parity/after/06b-packet-side-by-side.jpg) |
| Voice baseline | [before/07-voice-baseline.jpg](demo-parity/before/07-voice-baseline.jpg) | [after/07-voice-baseline.jpg](demo-parity/after/07-voice-baseline.jpg) |

The after set was re-shot in the final fix wave. What each new shot shows:

- `after/04-writing-state-habit-open.jpg`: the script opens heatmap bars in order and stops
  at the first whose panel marks words on both sides (it fails if none does). Here that is
  Mean Sentence Length: this paper's marked sentence beside a marked sentence from "On
  Liberty, part 1" (dated 14 Jan 2026), "Where it appears" tabs 1 to 3, the header numbers
  in the same words-per-sentence units as the line under it, the "What to notice" line, and
  the in-panel "See it side by side" link.
- `after/05-side-by-side.jpg`: scrolled to the first quote card under "Biggest differences"
  (Comma Rate): marked commas in this paper beside marked commas in two dated past papers,
  each with its source line.
- `after/06b-packet-side-by-side.jpg`: the packet's Side by side section with the Comma Rate
  and First-Person Ratio cards, marked words on both sides, each card's "What to notice" and
  numbers lines, and the note naming the top habits left out for lack of quotable text.

### 1. Writing State (status after)

| Demo element | Status after | Note |
|---|---|---|
| Habit bar in State Vector | `works` | Opens the habit panel with real passages (this paper beside past work, marked words), a plain "What to notice" line, and a plain note for whole-text, off and not-compared habits (Task 2). Without evidence in the response it keeps today's numbers-only panel. |
| Tier band label (`.hbnd`) | `works` | Unchanged. |
| Tier chip | `works` | Pins as before; with evidence present a click also opens that tier's most different habit. Flags off: pin only, as today (Global Constraint 2). |
| Family header | `works` | Unchanged. |
| Radar | `works` | Subtitle reworded to "tier chips: click to pin", so nothing looks clickable that is not. |
| Feature Detail row | `works` | Opens the panel (passages when present). |
| "Largest differences" rows | `works` | Same. |
| Particle-pattern toggle and canvas | `works` | Unchanged. |
| "Prepare conversation packet" | `works` | Panel now sits in normal flow below the triage row; the buttons are no longer covered. |
| "See it side by side" | `works` | Reachable with a panel open; also linked inside the panel. |
| "Looks fine" / "Have a conversation" | `works` | No longer covered. |
| Close ("Back to the pattern") | `unchanged by design` | Demo wording uses a banned word; real wording stays. |
| "Where it appears" tabs | `works` | One tab per located passage, keyboard reachable. Only shown when the habit has more than one passage. |
| This submission / past work columns with highlights and dated source | `works` | Real sentences at recorded offsets; short matches stay visible; source lines show paper title and date with no raw offsets. Habits with no located sentence show numbers and a plain reason. |
| "What to notice" line | `works` | From `EvidenceView.noticeFor`, built from real numbers only, no invented reasons. |
| In-panel link to Side by side | `works` | Added. |
| Voice baseline link, Change student, Analyse another | `works` | Unchanged. |
| Avatar menu, nav pills | `works` | The avatar menu on every staff page now starts with "Open Collections" (`/bluebook/#dashboard`), since bare `/bluebook/` sends a teacher to Original. Collections pill still opens the Collections sessions page. |

### 2. Packet (status after)

| Demo element | Status after | Note |
|---|---|---|
| Back, Print | `works` | Unchanged. |
| "What the analysis found" | `works` | Wording differs by design (real data). |
| "Side by side" example cards | `works` | New "Side by side" section with the first real quote from this paper and from past work for the habits furthest from usual, plus the "What to notice" line. Absent when the response has no evidence (page identical to before). |
| Baseline provenance table | `works` | Already present; checked, unchanged. |
| Worth doing / avoiding, signature, footer | `works` | Unchanged. |
| Case number, "prepared for" block | `unchanged by design` | The demo's case number is invented; not copied. |

### 3. Overview (status after)

| Demo element | Status after | Note |
|---|---|---|
| Student/flag row | `works` | Clicking a row opens that student's Writing State (`writing-state.html?student=`). |
| "stats" button | `works` | Keeps the in-page student summary (ruling: the row click goes to Writing State, the button keeps the old behaviour). |
| "Back to term view" | `works` | Unchanged. |
| Sensitivity options | `unchanged by design` | No engine controls on a real page. |
| Notifications menu item | `unchanged by design` | The demo's is a dead end; none added. |
| Row hover | `works` | Gold edge and tint present. |
| Dragging to select row text | `works` | A row click with text selected no longer navigates (`getSelection` guard, final fix wave). |

### 4. Students (status after)

| Demo element | Status after | Note |
|---|---|---|
| Student row | `works` | Still opens Voice baseline (existing destination kept); each row gains a "Writing State" link beside it. Deviation: the demo row goes to analysis. |
| Filter chips | `unchanged by design` | Baseline-readiness chips are the honest set (no stored analyses). |
| Find a student, stat strip | `works` | Unchanged. |
| "Add student" | `works` | Opens the Collections roster; Collections links carry a hash so a teacher with Original stays in Collections instead of bouncing back. |
| Deviation column | `unchanged by design` | Empty until Original keeps analysis results. |

### 5. Voice baseline (status after)

| Demo element | Status after | Note |
|---|---|---|
| Three cards, tier rows, back and cross links | `works` | Unchanged. |
| "Add a fourth sample" | `works` | Links into Collections with the stay hash. |

### 6. Other pages (status after)

| Page | Status after | Note |
|---|---|---|
| Submissions (`submissions.html`) | `unchanged by design` | No stored analyses, so no severity chips. |
| Reports (`reports.html`) | `unchanged by design` | Week columns unchanged: there is no week filter on Submissions to send them to. |
| Voice (`voice.html`) | `unchanged by design` | Student-facing, shows no scores (constraint 3). |
| Collections pill (`bluebook.html`) | `works` | Still the Collections sessions page; its head now carries an "Open Collections" link to the Collections dashboard (`/bluebook/#dashboard`). |

### Landing (Task 6, not a table row above)

A signed-in teacher whose workspace has Original now lands in Original (`/original/index.html`)
from the bare pilot address `/bluebook/`, once per tab; Collections is reached by its own
links (`#dashboard`, `#collections`) without a bounce. A workspace without Original still
opens Collections. The admin and operator sign-ins mirror the main sign-in (ruling).
`render.yaml` turns on the two staff-only evidence flags; a startup log line names them.

### Still open

- Minor review item deferred by the ledger: `.r-ws` has no `title`. (The drag-select
  guard, `habitName` keeping acronyms and proper nouns, one shared quote rule in
  `EvidenceView`, and the not-compared line built from `EvidenceView` were fixed in the
  final fix wave.)
- Not validated against real student submissions: the sentences quoted are real engine
  output on public-domain test papers only.

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
8. Task 8: "After" screenshots with the same script, "Status after" section here (see below), STATUS.md.

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
