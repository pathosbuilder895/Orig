# Live Navy Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The teacher and student pages Andrew handed over (Claude Design "Navy Suite", 2026-10-08) become the live Original UI, looking the same as the mockups, on real data.

**Architecture:** Each page is a static HTML file under `demo/original/`, served at `/original/` by the existing static mount (`run.py:85`). Each page starts from the NORTH_STAR-cleaned copy of its mockup on branch `claude/frontend-ui-implementation-b3024b` (`demo/prototypes/navy/`, PR #237), keeps that markup and CSS (the look), restores the mockup's photograph, and replaces the inline fictional data with calls to existing API endpoints through one shared script, `demo/original/live.js`. Where no endpoint has the data, the card keeps its place and says so plainly.

**Tech Stack:** static HTML, CSS, plain JavaScript (no build step), FastAPI backend unchanged, pytest static contract tests, Playwright e2e.

## Global Constraints

- **Look:** layout, CSS, spacing, typography, photographs and decorative canvases match the handoff page (`/Users/andrew/Desktop/handoff/frontend/<page>.html`). Change markup only to remove fictional content, rename per the copy rules, or add data hooks.
- **Photos (owner decision 2026-10-10):** ship the handoff photographs as they are, copied from `/Users/andrew/Desktop/handoff/frontend/assets/`. No licence is on record; `demo/original/assets/CREDITS.md` says so ("shipped at the owner's direction on 2026-10-10 without a licence on record") and gives no invented source or credit line. PNGs over 1 MB are re-encoded to JPEG (`sips -s format jpeg -s formatOptions 80 -Z 2400`) with the same framing; the CSS references the re-encoded file.
- **Real data only (NORTH_STAR rule 9):** no fictional names, numbers, dates, courses or rows. A value with no real source is shown as an honest empty state in the card's own style ("No sealed exams yet", "Appears once Original keeps analysis results"), never as a placeholder number.
- **Testing label, exact text,** once at the top of every view that shows an Original score, recommended action or deviation: `Testing phase: Original is not yet validated on real student writing. Treat any result as a reason for a conversation, never as evidence.` It lives once, in `live.js`.
- **Copy rules:** no keystroke or typing-rhythm wording; no authorship, AI, misconduct or verdict framing (no "% authentic", "Authorship Probability", "AI-Typical"); "Your classes" replaces "Integrity Operations Center"; independent teachers, no seminary, department or institution framing; feature counts 109 total / 97 active; Tr(ρ²) only inside a details block that mentions the T-01 caveat; baselines are teacher-approved ("Only writing your teacher approves, such as sealed Bluebook work, joins your writing profile." on My Work, since a piece compared there is never stored; "Your teacher may choose to add this to your writing profile." stays for the Bluebook booklet, where a teacher can approve the sealed work); Original is not a corrector.
- **No fictional banner** on live pages (the #237 banner says the page is fictional; live pages are not).
- **No third-party requests:** no Google Fonts, no CDN, no `https://` script or stylesheet. Fonts come from `../bluebook/fonts.css` plus `demo/original/fonts.css` for any family it lacks (Caveat, from #237's `demo/prototypes/navy/fonts/`, OFL licence file alongside).
- **Do not touch:** `demo/bluebook/**` (Codex Task C), `demo/professor.html`, `demo/landing.html`, `demo/js/`, `demo/styles/original-landing.css`, `demo/assets/` (Task B), `demo/_components/**`, `demo/_tour/**`, `original/**`, `render.yaml`, `scripts/**`.
- **No em dash** characters (U+2014, U+2015) in new code, copy, comments or commit messages.
- **Python:** `/Users/andrew/Desktop/Original/.venv/bin/python` (the relative `.venv` does not exist in a worktree).
- **Commit trailer:** `Co-Authored-By: Claude <model name> <noreply@anthropic.com>`.

## Shared interface: `demo/original/live.js`

Loaded with `<script src="live.js"></script>` before each page's own script. Exposes `window.Live`:

```js
Live.TOKEN_KEYS          // ['original_principal_token','original_session_token','original_role','original_tenant','original_name']
Live.NOTICE              // the testing-label string, verbatim (the ONLY copy in the suite)
Live.STUDENT_NOTICE      // the testing-label string the student pages show (voice.html, my-work.html): the same
                         // warning, plus that a teacher may approve sealed Bluebook work as reference writing
                         // (NORTH_STAR rule 10). The only copy; a student never sees NOTICE
Live.esc(s)              // HTML-escape any value before it goes into innerHTML
Live.api(path, opts)     // same-origin fetch; adds `Authorization: Bearer <original_principal_token>` when present,
                         // else `<original_session_token>` (a student's, which the /me/* routes need);
                         // resolves {ok, status, data} (data = parsed JSON or null); never throws
Live.session()           // Promise<{mode:'demo'|'signed-in'|'signed-out', role, products:[], tenant, name}>
                         // demo  = GET /health -> environment === 'demo' (products ['original','bluebook'])
                         // signed-in = GET /auth/me 200 (role, products, tenant_id)
                         // signed-out = otherwise
Live.notices()           // replaces every [data-testing-notice] with the label markup and every
                         // [data-student-notice] with the student label (also runs on DOMContentLoaded)
Live.empty(el, text)     // renders an honest empty state inside el, styled like the card's body text
Live.gate(el, opts)      // Promise<session|null>: renders the sign-in panel (link to /index.html) or the
                         // "Original is off for this workspace" panel into el and resolves null when the page
                         // cannot load data; otherwise resolves the session
                         // opts.audience 'student' (voice.html, my-work.html): a student holding a session token
                         // is allowed; staff are sent to index.html; anyone else (signed out, the open demo, a
                         // launch-link student with an id but no session token) gets the sign-in panel with a
                         // link to /bluebook/
Live.signOut()           // removes TOKEN_KEYS and every kept paper, then location.replace('/index.html')
                         // ('/bluebook/' for a student, decided before the keys that say so are removed)
Live.VERDICT_WORDS       // the server's baseline verdict in the one set of words every page shows (frozen):
                         // ready -> 'Ready', developing -> 'Building', insufficient -> 'Needs more'
Live.verdictWord(v)      // that word, or 'Not available' for null or any other value. A page never keeps a
                         // map of its own and never prints the raw verdict
```

Pages wire the account menu's Sign out to `Live.signOut()`, and use only `Live.api` for data.

## Page map (filenames are final; nav links use them)

| Live page | From mockup | Task |
|---|---|---|
| `index.html` (Your classes) | `original-dashboard.html` | 1 |
| `students.html` | `original-students.html` | later |
| `submissions.html` | `original-review.html` | later |
| `writing-state.html` | `original-quantum.html` | later |
| `packet.html` | `original-flagged.html` | later |
| `baseline.html` | `original-baseline-voice.html` | later |
| `reports.html` | `original-reports.html` | later |
| `settings.html` | `original-settings.html` | later |
| `voice.html`, `my-work.html`, `library.html` | student mockups | later |
| `bluebook.html` (Bluebook Sessions) | `original-bluebook-teacher.html` | 13 |
| Bluebook pill | teacher pages: `bluebook.html` (Task 13, owner decision 2026-10-11); student pages: `/bluebook/` | 1, 13 |

A nav link to a page not built yet points at its final filename; the page is added by its own task before the PR opens.

---

### Task 1: Suite scaffold, `live.js`, and the live Overview ("Your classes")

**Files:**
- Create: `demo/original/index.html`, `demo/original/live.js`, `demo/original/suite.css` (only if #237's `demo.css` rules are needed; take them from there), `demo/original/fonts.css`, `demo/original/fonts/` (Caveat only, with its OFL file), `demo/original/js/fingerprint.js` (byte-identical to #237's), `demo/original/assets/radcliffe-night-stars.jpeg`, `demo/original/assets/CREDITS.md`
- Create: `tests/test_original_suite_static.py`

**Interfaces:**
- Produces: `window.Live` exactly as specified above; the CREDITS.md table later tasks append to; the contract test later tasks extend with their pages.

- [ ] **Step 1: Copy the base.** `git show claude/frontend-ui-implementation-b3024b:demo/prototypes/navy/original-dashboard.html > demo/original/index.html`, same for `js/fingerprint.js` and the Caveat font files. Diff the result against `/Users/andrew/Desktop/handoff/frontend/original-dashboard.html` to see every cleaning change #237 made; keep those, and put back anything #237 removed only because it was a demo (the photo).
- [ ] **Step 2: Photo.** Restore the hero photo per #237's `assets/CREDITS.md` row for `radcliffe-night-stars.jpeg` (in `.hero-photo`, replace the `radial-gradient(...)` background with `url('assets/radcliffe-night-stars.jpeg') center 62%/cover no-repeat`). Write `demo/original/assets/CREDITS.md` with one table: file, page, "No licence on record; shipped at the owner's direction on 2026-10-10".
- [ ] **Step 3: Shell.** Remove the fictional banner. Nav pills become links: Overview `index.html` (active), Students `students.html`, Submissions `submissions.html`, Bluebook `/bluebook/`, Reports `reports.html`. Account menu: Settings `settings.html`, Sign out calling `Live.signOut()`; remove "Notifications" and its count (no notification system exists). Title `Original · Your classes`; the page heading wording follows the copy rules.
- [ ] **Step 4: `live.js`** per the interface above. No dependencies. `Live.api` catches network errors and non-JSON bodies.
- [ ] **Step 5: Real data.** Remove every fictional array and string from the page script. Fill the existing cards from:
  - "Students monitored" stat: number of students in `GET /students` → `roster` (fall back to `students.length` when `roster` is null).
  - Second stat (relabel "Sealed exams to review"): count of `GET /bluebook/submissions` → `submissions` whose `graded_at` is empty. 403 or no Bluebook product: show "Bluebook is off" in the stat's sub-label and "0" is not shown.
  - Trend card (relabel "Sealed exams per week", "last 6 weeks"): weekly counts of those submissions by `created_at` (or the field the endpoint returns; read `original/routers/bluebook.py` `_shape`), same chart drawing as the mockup.
  - Gauge card (relabel "Baselines ready"): fraction of roster students with `authenticated_count >= 3`; sub-label "N of M students have 3 or more approved samples". Do not mention flag sensitivity (no such setting exists).
  - Hero table ("This term"): one row per roster student: name (`name` or id), courses (from `GET /bluebook/students` → `students[].courses`, matched by id; empty when unknown), approved baseline samples (`authenticated_count`), last sealed exam (`last_submitted_at`, formatted date, or "None yet"). The row's "stats" button opens the summary panel with only these real fields. No flags column: flags appear once Original keeps analysis results (state it in the table's empty-state line when the roster is empty).
  - Any card with no data: `Live.empty(...)`.
  - The page shows no Original score, so it carries no testing label unless a later change adds one.
- [ ] **Step 6: States.** On load, `Live.gate(document.querySelector('main') or the page's main container)`: signed-out shows the sign-in panel; a session without `original` in `products` shows "Original is off for this workspace" with a link to `/bluebook/`; students (role `student`) are sent to `/bluebook/`.
- [ ] **Step 7: Contract test** `tests/test_original_suite_static.py`, parametrized over every `demo/original/*.html` so later pages are covered automatically:
  - no `fonts.googleapis.com`, `fonts.gstatic.com`, `cdn.jsdelivr.net`, `unpkg.com`, or `<script src="https://` / `<link ... href="https://`
  - none of: `Integrity Operations`, `seminary`, `Seminary`, `department`, `keystroke`, `typing rhythm`, `Authorship Probability`, `AI-Typical`, `% authentic`, `103 `, `fictional`, `JetBrains`
  - the testing-label string appears exactly once in `live.js` and in no `.html` file
  - every relative `href`/`src` resolves to a file under `demo/` (links to `/bluebook/` and `/index.html` allowed)
  - every file in `demo/original/assets/` other than CREDITS.md has a row in CREDITS.md
  - no em dash in any `demo/original/` file
  Plus a served-path test using the existing `mounted_pilot_client` fixture (see `tests/security/test_static_tree.py`): `GET /original/` is 200 and contains `live.js`.
- [ ] **Step 8: Run** `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_original_suite_static.py tests/test_pilot_lockdown.py tests/security/test_static_tree.py -q -p no:cacheprovider`. Expected: all pass.
- [ ] **Step 9: Commit** `Add the live Your classes page from the navy design` (all new files).

---

### Task 2: Students page, and the shared roster loader

**Files:**
- Create: `demo/original/students.html` (from #237 `demo/prototypes/navy/original-students.html`), `demo/original/assets/st-andrews-quad.jpg` (re-encoded to fit the 700 KB pre-commit limit: `sips -s format jpeg -s formatOptions 75 -Z 2000`)
- Modify: `demo/original/live.js` (add `Live.roster`), `demo/original/index.html` (use `Live.roster` instead of its own loader), `demo/original/assets/CREDITS.md`, `tests/test_original_suite_static.py` (remove `students.html` from `PLANNED_PAGES`; fix the review Minors listed below)

**Interfaces:**
- Consumes: `window.Live` from Task 1.
- Produces: `Live.roster()` → `Promise<{ok, error, scoped, students:[{id, name, email, courses:[{code,name}], counted, samples, verdict, lastSealed}], sealedToReview, bluebookOff}>`, built from the logic now in `index.html`'s `load()`: `GET /students` (roster or ids), `GET /students/{id}/readiness` per student (first 60, at most 6 requests in flight at once), `GET /bluebook/students`, `GET /bluebook/submissions`. `verdict` is the server's word (`ready`, `developing`, `insufficient`) or `null`; `name` is only what the API returns, else the id; `lastSealed` is the latest `last_submitted_at`, else `null`. Every id-keyed lookup uses `Map`. Later pages use this, never their own copy.

- [ ] **Step 1: Shared loader.** Move the roster, readiness and Bluebook loading out of `index.html` into `Live.roster()` with the shape above and a concurrency limit of 6 for the readiness calls. `index.html` renders from it; its output must not change (check the seeded demo on :8011 and the empty demo on :8010 before and after).
- [ ] **Step 2: Page.** Copy #237's students page; restore its photo per #237's `assets/CREDITS.md` row (`st-andrews-quad.jpg`, rule A with `center 58%/cover`, tint `0.54`, saturate `.58`, brightness `.5`); same shell as `index.html` (nav pills as links with Students active, account menu with Settings and Sign out, no Notifications, no fictional banner). Title `Original · Students`.
- [ ] **Step 3: Real data** from `Live.roster()`:
  - Heading count: number of students. Sub-line: "N courses" (distinct course codes from Bluebook, omitted when Bluebook is off) and "sorted by baseline readiness" (sort: no baseline, building, ready; then name).
  - Strip: Enrolled = students; Baseline ready / Building baseline / No baseline yet = server verdicts `ready` / `developing` / `insufficient`; fifth cell "Sealed exams to review" = `sealedToReview` ("Bluebook is off" when off). Unknown verdicts are counted nowhere and stated in the sub-line ("readiness not available for N").
  - Filters: All, Ready, Building, No baseline yet, plus the search box (matches name, id, email). Remove "Flagged" and "Writing like themselves" (no stored results; verdict-like).
  - Rows: initials avatar, name, email (Bluebook roster email when present, else nothing; never invent a domain), course chips, baseline pill from the verdict (Ready / Building / None yet / "Not available"), the "Deviation from their voice" column shows "–" for everyone with the column header kept and one line under the table: "Deviation appears here once Original keeps analysis results." Last paper column = `lastSealed` date or "None yet". Row click goes to `baseline.html?student=<id>` (planned page).
  - "Add student" links to the Bluebook roster screen (find its route in `demo/bluebook/`; read, do not edit).
  - No testing label (the page shows no score).
- [ ] **Step 4: States** via `Live.gate` as in Task 1; empty roster shows the mockup's empty-state line reworded ("No students on your roster yet. Add them in Bluebook.").
- [ ] **Step 5: Test Minors from Task 1's review** in `tests/test_original_suite_static.py`: the magic-link tripwire asserts on the check itself (`"read('bluebook_student_id')"` or whatever expression line 101 of live.js uses), and the external-reference scan runs over every text file in `demo/original/` (html, js, css, md), not only `*.html` and top-level `*.css`. In `index.html`, "Readiness could not be read for N" says "was not checked" for students beyond the cap.
- [ ] **Step 6: Run** `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_original_suite_static.py tests/test_pilot_lockdown.py tests/security/test_static_tree.py -q -p no:cacheprovider` (all pass) and `curl -s -o /dev/null -w "%{http_code}" localhost:8011/original/students.html` (200).
- [ ] **Step 7: Commit** `Add the live Students page from the navy design`.

---

### Task 3: Teachers land on the new pages

Owner decision 2026-10-10: sign-in sends teachers to `/original/` now; the old page stays reachable as "Analysis (classic)" until the new pages cover it.

**Files:**
- Modify: `demo/index.html` (post-login redirect for professors at about line 933, and the "Professor" role pill at about line 737: both go to `original/`), `demo/original/live.js` or each page's account menu (add "Analysis (classic)" linking to `/professor.html`, placed after Settings), `demo/bluebook/Dashboard.jsx:95` and `demo/bluebook/TeacherWorkspace.jsx:17` (the "Original Analysis" / Original link goes to `../original/`), then `cd demo/bluebook && npm run build` and commit the rebuilt bundle, `demo/original/assets/CREDITS.md` (record the caption printed in the Radcliffe photo, verbatim as observed: "Sarah Savić Kallesøe | Oxford by Night", noting the owner is asking her for permission; no other credit text), `tests/test_original_suite_static.py`.
- Leave alone: `original/lti.py` and `original/routers/lti_routes.py` (LTI is deferred), admin, operator, lab and playground pages (staff tools).

- [ ] **Step 1:** Make the redirects and links above. Check `demo/bluebook/e2e/*.spec.mjs` and `tests/` for any assertion that a professor login lands on `professor.html`; update it to `/original/` only where it tests the landing itself (specs that open `professor.html` directly keep doing so).
- [ ] **Step 2:** Test: `demo/index.html` sends role `professor` to `original/` (static check of the redirect expression), and every suite page's account menu links to `/professor.html` with the text "Analysis (classic)".
- [ ] **Step 3: Run** the suite contract, pilot lockdown, static tree, LTI tests (`tests/test_lti.py tests/test_lti_branches.py`), the Bluebook build, and the e2e specs that touch login or the professor page (`baselines.spec.mjs`, `scoring.spec.mjs`, plus any login spec) against a pilot-mode server.
- [ ] **Step 4: Commit** `Send teachers to the new Original pages after sign-in`.

---

### Task 4: Writing State page (analyse a paper)

**Files:**
- Create: `demo/original/writing-state.html` (from #237 `original-quantum.html`), `demo/original/assets/radcliffe-observatory-watercolour.jpg`, `demo/original/js/feature-data.js` (from #237: the 97 active features with tier names; byte-identical except em dashes)
- Modify: `demo/original/assets/CREDITS.md`, `tests/test_original_suite_static.py` (remove from `PLANNED_PAGES`)

**What it does:** `writing-state.html?student=<id>` shows one student's Writing State in the mockup's layout. Before an analysis it shows the baseline (the "Baseline ρ" toggle state) and an "Analyse a paper" card in the mockup's card style: assignment label, a text area, and a file picker for .txt (and .docx/.pdf only if `demo/professor.html` already extracts them client-side with a library this repo serves locally; reuse that code path, do not add a dependency). "Analyse" calls `POST /students/{id}/score` with `{text, assignment}`. Without `?student=`, the card first asks which student (from `Live.roster()`).

**Data mapping:**
- Radar "Tier Profile": per-tier mean of `feature_vector` vs `baseline_vector` (dicts keyed by feature code) grouped by tier from `js/feature-data.js`; only the 97 active features; tiers 17 and 18 never appear.
- State vector heatmap: bars = baseline value, ticks = submission value, per feature, same drawing as the mockup.
- Readout: student name or id, "HABITS MEASURED · 97", purity Tr(ρ²) from `baseline_confidence.purity` moved inside a `<details>` that says what purity is and carries the T-01 caveat ("baselines of 3-5 samples produce false alarms; see docs/testing"), state word from `recommendation.action` mapped to plain words (no "flag", no verdict).
- Plain-English line: count of features in `authorship` contributions (read `AuthorshipSignalOut` and `FeatureContributionOut` in `original/schemas.py`) that differ, "worth a conversation, not a conclusion", and `human_explanation` text if present.
- Feature detail: from `FeatureContributionOut` (name, tier, baseline_value, submission_value, delta, direction).
- Evidence panel ("This submission" / "Their own past work" quotes): the backend returns no text positions, so replace the quote columns with the feature's numbers and one sentence per side; no invented quotes.
- Triage buttons: "Looks fine" / "Have a conversation" call the same correction endpoint and payload `demo/professor.html` uses (find `recordProfessorAction` and the `/submissions/{id}/correct` call); "Prepare conversation packet" stores the last result in `sessionStorage` (`original_last_result`) and opens `packet.html` (planned page).
- Testing label: `<div data-testing-notice></div>` at the top of the result, filled by `Live.notices()`.
- Never show `authorship_probability`, `ai_likelihood`, `style_authorship`, `fused_score`, or any "AI" wording.
- Photo per #237's CREDITS row for `radcliffe-observatory-watercolour.jpg`.

- [ ] Steps: copy and restore look; wire the analyse card; render from the real response; states via `Live.gate`; extend the contract test (the page has a `[data-testing-notice]` slot; `Tr(` appears only inside `<details>`); run the suite contract, pilot lockdown and static tree tests; check in the browser on :8011 with a seeded student (e.g. `whitfield_j`, 5 approved samples) by analysing a pasted paragraph; commit `Add the live Writing State page from the navy design`.

---

Every task below follows Task 1's pattern: start from the #237 cleaned copy (`git show claude/frontend-ui-implementation-b3024b:demo/prototypes/navy/<mockup>`), keep its markup and CSS, restore its photo per #237's `assets/CREDITS.md` row (re-encode anything over 700 KB), same shell (nav links, account menu with Settings, "Analysis (classic)" and Sign out), `Live.gate`, real data through `Live.api` / `Live.roster` only, honest empty states, remove the page from `PLANNED_PAGES`, run the suite contract + pilot lockdown + static tree tests, check in the browser on :8011 (seeded) and :8010 (empty), commit `Add the live <Page> page from the navy design`. Any card whose data has no source keeps its place and says what it will show once Original keeps analysis results (Task 12).

### Task 5: Conversation Packet (`packet.html`, from `original-flagged.html`)
Printable. Reads the last analysis from `sessionStorage.original_last_result` (written by Writing State) plus `GET /students/{id}` samples (assignment, provenance, date) for "what the baseline is made of". Shows: student, assignment, date, the plain-language summary, the top differing habits from `FeatureContributionOut` with baseline vs paper numbers, the baseline sample list, and blank outcome/signature lines for the teacher (form fields, not data). The testing label appears on screen and in the print footer (`@media print`). No side-by-side quotes (no text positions exist), no case numbers. Without a stored result: "Run an analysis on the Writing State page first" with a link.

### Task 6: Voice Baseline (`baseline.html?student=<id>`, from `original-baseline-voice.html`)
`GET /students/{id}` (samples: assignment, provenance, submitted_at, auth_weight; purity; effective_sample_count), `GET /students/{id}/readiness` (verdict and counts), `GET /students/{id}/samples/{i}/text` for a sample preview. "Where the baseline came from" = the samples table (effective weight = the API's `auth_weight`; do not compute recency yourself unless the API returns it). Add writing: single text (`POST /students/{id}/baseline`, same payload as professor.html), batch upload and Turnitin CSV import (reuse professor.html's exact endpoints and payloads). Sealed Bluebook exams awaiting approval for this student (bluebook_baselines.py approve/undo endpoints) replace professor.html's "pending baselines" (bbook_client, not used). "Signature habits" and "The short version": no narrative without a source; show the per-tier baseline profile from `baseline_vector` grouped by `js/feature-data.js`, and the readiness verdict in plain words. Purity only inside `<details>` with the T-01 caveat.

### Task 7: Submissions (`submissions.html`, from `original-review.html`)
Rows = sealed Bluebook exams from `GET /bluebook/submissions` (student, exam title if the shape carries it, date, late, reviewed = `graded_at` set, mark); click opens that submission in Bluebook (find its route; read-only in this task). Stats: "Awaiting review" = ungraded count, "Reviewed this week" = `graded_at` within 7 days; "Reads very differently" and "Worth a look" keep their place with "Appears once Original keeps analysis results". Never show `ai_score` or FLAGGED. "Analyse a paper" button goes to `writing-state.html`.

### Task 8: Reports (`reports.html`, from `original-reports.html`)
Real: students with a ready baseline (server verdicts via `Live.roster`), sealed exams per week, reviewed by teacher (graded count), roster size. Not stored yet (keep the card, say so): papers analysed, within their usual range, deviation by assignment. Never "% authentic" or a percentage of students "writing like themselves".

### Task 9: Settings (`settings.html`, from `original-settings.html`)
Account from `/auth/me` (role, products shown read-only: "Original is on/off for this workspace"), change password (`POST /auth/password`, read original/routers/auth.py for the payload), sign out. "Flag Sensitivity" is removed (no such setting); no Canvas/Blackboard (deferred). Demo mode: show that the demo has no account.

### Task 10: Student pages (`voice.html`, `my-work.html`) and `/me/work` compare-only
- `Live.gate(el, {audience:'student'})`: student sessions allowed, staff redirected to `index.html`; sign-in goes to `/bluebook/`. Student nav: My Voice, My Work, Bluebook.
- `voice.html` (from `original-voice.html`): `GET /me/voice` only (headline, fingerprint, milestones, voice notes; read original/routers/me.py and original/voice.py). No class averages, no habit counts the API does not return, no term timeline.
- `my-work.html` (from `original-my-work.html`): paste a piece, `POST /me/work`, show the redacted result in the mockup's layout; no phrase highlighting (no source). The line "Only writing your teacher approves, such as sealed Bluebook work, joins your writing profile." appears (a piece compared here is never stored, so "your teacher may choose to add this" would be false on this page).
- Backend (owner decision 2 of the 2026-10-09 plan): `original/routers/me.py` `my_work` stops calling `add_baseline`; its "Saved to your body of work" / "added to your formation record" copy becomes accurate ("Not added to your writing profile. Only writing your teacher approves, such as sealed Bluebook work, joins your writing profile."); remove "formation" wording from student-facing copy in `original/voice.py`. "Voice Affirmed" means a teacher-approved piece is on file: `original/routers/me.py` counts the samples whose provenance is in `_TRUSTED_PROVENANCE` (proctored, verified, canvas) and passes that to `project_milestones`, not `authenticated_count`, which also counts a student's own upload. Update the tests that pin the old behaviour; add one asserting `/me/work` leaves the baseline sample count unchanged. Run `tests/test_me*.py`, `tests/test_voice*.py` (whatever exists) and the full suite in the background before the PR.

### Task 11: Bluebook screens restyled (owner decision 2026-10-10: in this branch now)
Teacher Sessions (`demo/bluebook/TeacherWorkspace.jsx` session setup, live and results screens) to `original-bluebook-teacher.html`; student exam booklet (`demo/bluebook/Exam.jsx`) to `original-bluebook-student.html`. Keep every behaviour, route and e2e selector; change look and copy only. Remove the teacher-facing "Authenticity" `ai_score` display (`Results.jsx`, about line 262) and any "typing rhythm strengthens your baseline" wording. Rebuild and commit the bundle; run the Bluebook e2e suite.

### Task 12: Stored analysis results (backend) and the flag cards
Per the 2026-10-09 plan's PR 5 and PR 6: `score_results` table (SQLite + Postgres + alembic), tenant-scoped list/overview/review endpoints, deletion and inventory coverage, the corrections-bug fix; then the flag cards on Your classes, Submissions and Reports, and reopening a past result on Writing State. Own spec and plan before code.

### Task 13: Bluebook Sessions (`bluebook.html`, from `original-bluebook-teacher.html`) and deep links into Bluebook
Owner decision 2026-10-11 (ADR-012): the Bluebook pill on every teacher page opens this suite page; `/bluebook/` itself is the public sign-up and learn site; the Bluebook app opens one exam from a link. Student pages keep `/bluebook/`.
- **Deep links (Bluebook app):** `/bluebook/#exam/<id>` opens Manage examination and `/bluebook/#live/<id>` the live view, for a signed-in teacher only (`demo/bluebook/deep-link.jsx`, `app.jsx`). The app checks the exam with `GET /bluebook/exams/{id}` first; an unknown or other-workspace id lands on the normal dashboard with no error. A signed-out visitor gets the landing page and the exam after signing in; a student's screens ignore the hash. Covered by `unit/deep-link.test.mjs` and `e2e/deep-link.spec.mjs`.
- **Start a new session:** question boxes (1 to 4), class pills from `GET /bluebook/courses` (code, name, student count), the duration slider, the summary line, and "Open the booklets", which sends `POST /bluebook/exams` with exactly the payload Bluebook's `SessionSetup` sends (title "<code> · <date>", `status:'ACTIVE'`, `minWords:0`, `maxWords:0`, `conditions:{}`). After it opens: how students reach it (the class roster finds it under "My exams" in Bluebook; there is no join code), "Open the live room" (`#live/<id>`) and "Manage it in Bluebook" (`#exam/<id>`). The server's refusal is shown as text.
- **Past sessions:** `GET /bluebook/exams`, newest first, six rows then "Show all"; per row the sealed and awaiting-review counts from `Live.sealed()` and, for visible rows with a sealed booklet, how many are in baselines (`GET /bluebook/exams/{id}/baseline`, at most six in flight). Each row links to `#exam/<id>`. No "worth a look" count: it would need Bluebook's submission status, which `Live.sealed()` does not pass on.
- **States:** `Live.gate`; no Bluebook product or a 403 shows "Bluebook is off for this workspace" in the cards; no course shows "Add a course in Bluebook first" with a link to `/bluebook/`.
- Contract tests in `tests/test_original_suite_static.py` (pill targets, no integrity readings named, the create request pinned to `SessionSetup`'s, behaviour under node).
