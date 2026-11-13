# Original staff pages: demo parity with real engine output

Spec: the user's request of 2026-11-13 (restated in "Spec" below). No separate spec file.

## Spec (binding)

Make the real staff screens of Original on the pilot look and work like the navy demo
prototypes, using real engine output instead of invented data, and make the pilot open
into Original for staff.

Reference (target look and behaviour): `demo/prototypes/navy/original-flagged.html`,
`demo/prototypes/navy/original-quantum.html`, and the other `demo/prototypes/navy/` pages
they link to (dashboard, students, baseline-voice, review, reports, voice). Live copy:
https://bluebook-teacher-demo.onrender.com.

Real pages: `demo/original/writing-state.html` (Writing State), `demo/original/evidence.html`
+ `demo/original/js/evidence-view.js` (Side by side), `demo/original/packet.html`
(Conversation packet), `demo/original/baseline.html` (Voice baseline),
`demo/original/index.html` (Overview), `demo/original/students.html`. Server:
`original/evidence.py`, `original/routers/students_scoring.py`
(`_attach_staff_explainability`), `original/schemas.py`.

### Global Constraints (copy verbatim to every implementer and reviewer)

1. Presentation only. Do not change any score, threshold, weight, feature, or what the
   engine computes. The only server changes allowed: a startup log line for the two
   evidence flags, and `render.yaml` env vars. No edits to `original/quantum/`,
   `original/features/`, `original/context/`, `original/constants.py`, `original/store.py`.
2. New work must not change existing behaviour. When `evidence` (or `preliminary`) is
   missing from the score response, every page falls back to exactly what it shows today.
3. Students never see scores, evidence, passages or the preliminary label. Everything new
   is staff-only.
4. Keep the exact wording `Preliminary · unvalidated · not a judgment`. Never write
   "AI detection", "cheating", "authorship verification", "fingerprint", "proves" or
   "verifies" in any user-facing string, and make no accuracy claims. (Code identifiers
   such as `fingerprint.js` / `window.Fingerprint` already exist and stay; never put the
   word in visible text, titles, aria labels or alt text.) Use `EvidenceView.clean()` /
   `isClean()` for every templated sentence.
5. Real pages show only real data from the API. The demo's invented examples stay in
   `demo/prototypes/`. Never copy demo prose, names or numbers into real pages.
6. No dash characters U+2014 or U+2015 anywhere (code, comments, docs, commits). Use comma,
   colon, parentheses or hyphen. (Existing `–` U+2013 usage in code may stay.)
7. Every user-visible string HTML-escaped (`Live.esc`) before innerHTML.
8. Python: use `/Users/andrew/Code/Orig/.venv/bin/python` (this worktree has no venv).
   Node: `cd demo/bluebook && npm ci` once if `node_modules` is missing. After editing
   any `demo/bluebook/*.jsx`, run `npm run build` and commit the rebuilt bundles.
9. Never kill or restart a dev server you did not start. Start your own on a free port
   (e.g. 8017+), e.g.
   `ORIGINAL_ENV=pilot SELF_SERVE_SIGNUP=0 EVIDENCE_PASSAGES_ENABLED=1 PRELIMINARY_SCORE_ENABLED=1 /Users/andrew/Code/Orig/.venv/bin/python run.py --demo --frontend-dir demo --port 8017 --skip-seed`
   (check `.github/workflows/test.yml` "Start Original demo server" steps for the exact
   env CI uses, including MAINTENANCE_TOKEN and the e2e base URL variable), and stop it
   when done.
10. Commits: conventional (`Add ...`, `Fix ...`), one focused commit per logical change,
    trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.
11. `evidence.all_features` entry shape (built by `original/evidence.py:build_all_features`):
    `code, name, group, rank, kind` (`located` | `whole_text` | `off` | `not_compared`),
    `engine_scale{this_paper, past_papers[{paper,value}], past_range, difference,
    outside_past_range}`, optional `plain{unit, this_paper, past_papers, past_range}`,
    `this_paper{count, examples[]}`, `past_papers{per_paper[], examples[]}`, `note`,
    `what_is_marked`, `in_top_list`. Each example quote: `paper` ("this paper" |
    "past paper N"), `passage, passage_start, match, match_start, match_end, start, end,
    words, clipped_start, clipped_end, crosses_set_aside`. `evidence.baseline_papers[]`:
    `{paper, assignment, submitted_at, provenance, word_count}`. Read the real code to
    confirm; do not trust this summary over it. Use `EvidenceView.markParts` for
    highlighting (it only marks when the slice exactly equals `match`).

## Tasks

### Task 1: Audit and "before" screenshots

Write `docs/audits/demo-parity.md` before any code changes.

- List every clickable element in the navy demo pages (original-quantum, original-flagged,
  original-dashboard, original-students, original-baseline-voice, original-review,
  original-reports, original-voice): habit bars in the state vector, tier chips (T1
  Wording ...), family headers Surface / Discourse / Rhetorical, band labels, "Largest
  differences" / Feature Detail rows, radar, fingerprint toggle, triage buttons, links
  between pages, back buttons, tabs ("Where it appears"), expanders, student rows on the
  dashboard.
- For each: what it does in the demo, the matching element on the real page, and its real
  status: `works`, `looks clickable, does nothing`, `missing`, `numbers only`. Use a table
  per page pair (demo page -> real page).
- Then a section each for wording, layout, and visual tuning (spacing, typography,
  colours, hover states, transitions, decorative pieces such as the frame photo, ribbon,
  gradients) with the gaps.
- End with a "Fix list" numbered by the task below that will close each gap.
- Capture "before" screenshots with a reusable Playwright script
  `demo/bluebook/e2e/tools/parity-screenshots.mjs` (not a spec, not run by CI): it starts
  from a running server URL (env `PARITY_BASE_URL`), provisions a tenant/staff/student via
  the existing helpers in `demo/bluebook/e2e/fixtures/` (read `tenancy.mjs` and
  `api-setup.mjs`), seeds the three `fixtures/evidence/mill-*.txt` past papers, analyses
  `chesterton.txt` on Writing State, and screenshots at 1440x1000: Overview, Students,
  Writing State (result), Writing State with the first habit panel open, Side by side,
  Packet, Voice baseline; output dir from env `PARITY_OUT`. Run it against a server with
  both evidence flags on and save into `docs/audits/demo-parity/before/`. Also screenshot
  the matching navy demo pages (served locally from `demo/prototypes/navy/`) into
  `docs/audits/demo-parity/demo/`. Commit audit, script and PNGs.

### Task 2: Writing State habit panel with real passages

In `demo/original/writing-state.html`:

- Replace `makeEvidence` (numbers-only panel, comment "The server returns no text
  positions") with a panel that, when `S.result.evidence.all_features` has the habit:
  shows the habit name, numbers line (`EvidenceView.oneLine`), and two columns like the
  demo: "This paper" with up to 3 quoted passages from `this_paper.examples` and "Their
  own past work" with up to 3 from `past_papers.examples`, each with the match highlighted
  via `<mark>` (use `EvidenceView.markParts`) and a source label (this paper: assignment or
  "This paper"; past: `baseline_papers` assignment and formatted date, else "Past paper N").
  Demo-style "Where it appears" tabs may page through passages when there are more than one.
- When the entry's kind is not `located` or has no examples on a side: show its `note`
  in plain language, e.g. "This habit is measured across the whole paper, so there is no
  single sentence to quote", plus the numbers. `not_compared` / `off` get their own plain
  sentence (reuse evidence-view wording).
- When `evidence` is absent: the panel behaves exactly as today (numbers only).
- Every habit entry point opens it: heatmap bars, Feature Detail / "Largest differences"
  rows, tier chips (first click pins the tier AND, once a result exists, opens that tier's
  most different habit, as the demo does when the panel is open), band labels pin the tier.
  Family headers pin the family. Nothing that looks clickable is a dead end.
- Layout: the panel must not cover the triage buttons ("Prepare conversation packet",
  "See it side by side"). Change `.hero-evi` so it is not `position:absolute; inset:0`
  over `.hero-inner` (e.g. render it in normal flow below the triage row, or make the
  triage row sit above it with higher z-index), and add a "See it side by side" link inside
  the panel (shown only when evidence exists) that goes to
  `evidence.html?student=<id>#m-<code>` after `storeForPacket()`.
- Add a "What to notice" line per habit (Task 3 builds the helper; this task calls
  `EvidenceView.noticeFor` if present, else `noteFor`).
- Load `js/evidence-view.js` on this page.

### Task 3: "What to notice" helper and Side by side polish

In `demo/original/js/evidence-view.js` add `noticeFor(f, papers)`: one or two short
plain-language sentences built only from the entry's real numbers, direction and counts,
that say what the difference is and what it might and might not mean (for example: a
higher or lower rate can come from a new topic, genre, length, revision or permitted
help; on its own it does not say who wrote the paper). Templates keyed on kind
(located / whole_text / not_compared / off) and position (above / below / within /
none). No invented reasons, no banned words, passes `clean()`. Unit tests in
`demo/bluebook/unit/evidence-view.test.mjs` (read the existing tests first).

In `demo/original/evidence.html`: use `noticeFor` in each card's "What to notice"
(keep the existing numeric `noteFor` text too, after it); label past quotes with the
past paper's title and date from `baseline_papers`; honour a `#m-<code>` hash by
opening and scrolling to that row; card and spacing polish to match the demo packet.

### Task 4: Conversation packet with real quotes

In `demo/original/packet.html`: when the stored result carries `evidence`, add a
"Side by side" section like the demo packet (`.ex` cards): for each entry in
`evidence.features` (the top list, in order, at most 5) with located examples, show
the first this-paper quote and the first past-paper quote, highlighted, with source
labels and the `noticeFor` line; a "Where the baseline comes from" table from
`baseline_papers` (title, date, how it was added, length) if not already present.
Without evidence the packet is unchanged. Print styles must keep cards unbroken.

### Task 5: Overview, Students, Voice baseline parity and decorative pieces

Close the audit's gaps for `index.html`, `students.html`, `baseline.html` and the shared
chrome: clicking a student anywhere on Overview opens that student
(`writing-state.html?student=<id>`), whole rows clickable with hover states as the demo;
Voice baseline back link and cross links work; decorative pieces from the demo (frame
photo from `assets/` if already credited in `assets/CREDITS.md` and present in
`demo/original/assets/`, gradients, hover/transition tuning) are present on the real
pages. Real data only; no demo numbers.

### Task 6: Pilot opens into Original; evidence flags on

- `demo/bluebook/app.jsx` (+ `deep-link.jsx` if needed): a signed-in staff user (not a
  student account, not a student launch) whose workspace has Original
  (`BB_API.hasOriginal()`) and who arrives at the SPA with no deep link, no `?join=`,
  `?invite=`, `?reset=`, and no explicit Collections intent, is sent with
  `location.replace('/original/index.html')`. After a successful staff sign-in the same
  rule applies (unless a deep link is pending). Explicit Collections intent: Original's
  own links into Collections (the "Collections" pill page `demo/original/bluebook.html`
  and any `/bluebook/` links from Original pages) must carry a hash or query the SPA
  treats as "stay" (e.g. `#dashboard` added to the screen-link aliases, or `?home=collections`),
  so a teacher can still reach Collections. Workspaces without Original and students:
  unchanged. Rebuild and commit bundles. Unit-test the decision function in
  `demo/bluebook/unit/`.
- `render.yaml` original-pilot envVars: `EVIDENCE_PASSAGES_ENABLED: "1"` and
  `PRELIMINARY_SCORE_ENABLED: "1"` with a comment (staff-only, ADR-013, never changes
  scores).
- Startup log line: one INFO line at app startup naming both flags and whether each is
  on (exact "1" rule from `original/evidence.py`), e.g.
  `staff_explainability evidence_passages=on preliminary_score=off`. Put it where other
  startup config is logged (find it in `original/api.py` / `run.py`). pytest covering both
  states with `caplog`.
- A pytest proving a student principal never gets `evidence` or `preliminary` from
  `POST /students/{id}/score` with both flags on, and that `/me/work` never carries them
  (check whether one already exists in `tests/`; extend rather than duplicate).

### Task 7: E2E coverage

Extend `demo/bluebook/e2e/teacher-evidence.spec.mjs` (@evidence-on block) using
`fixtures/evidence/`: on Writing State click every habit that has an entry (iterate all
heatmap bars, or at minimum every `evidence.features` code plus one per tier via chips,
plus each Largest differences row) and assert passages render on both sides when both
sides have examples, or the plain note otherwise; assert `#tri-packet` and `#tri-evidence`
stay visible and clickable (not covered: use `elementFromPoint` or Playwright click
without force) with the panel open; the in-panel "See it side by side" link works; the
packet shows `.ex` quotes with marks equal to API slices; a staff sign-in / root visit
lands on `/original/index.html`; a student's pages show no evidence. Keep the flags-off
test meaningful (panel numbers only, no quotes, packet unchanged). Add a landing test in
the non-evidence run for: staff with Original -> Original; `?join=` link -> join screen;
student -> unchanged. Run the specs locally against your own servers.

### Task 8: After screenshots, STATUS, full checks

Run the Task 1 screenshot script into `docs/audits/demo-parity/after/`; update
`docs/audits/demo-parity.md` with a "Status after" column; add a one-line STATUS.md
session-log entry; run ruff, the full pytest CI command, the Bluebook unit tests,
the bundle byte-identity check and both Playwright runs locally.
