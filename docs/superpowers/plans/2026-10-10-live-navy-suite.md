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
- **Copy rules:** no keystroke or typing-rhythm wording; no authorship, AI, misconduct or verdict framing (no "% authentic", "Authorship Probability", "AI-Typical"); "Your classes" replaces "Integrity Operations Center"; independent teachers, no seminary, department or institution framing; feature counts 109 total / 97 active; Tr(ρ²) only inside a details block that mentions the T-01 caveat; baselines are teacher-approved ("Your teacher may choose to add this to your writing profile." on student pages); Original is not a corrector.
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
Live.esc(s)              // HTML-escape any value before it goes into innerHTML
Live.api(path, opts)     // same-origin fetch; adds `Authorization: Bearer <original_principal_token>` when present;
                         // resolves {ok, status, data} (data = parsed JSON or null); never throws
Live.session()           // Promise<{mode:'demo'|'signed-in'|'signed-out', role, products:[], tenant, name}>
                         // demo  = GET /health -> environment === 'demo' (products ['original','bluebook'])
                         // signed-in = GET /auth/me 200 (role, products, tenant_id)
                         // signed-out = otherwise
Live.notices()           // replaces every [data-testing-notice] with the label markup (also runs on DOMContentLoaded)
Live.empty(el, text)     // renders an honest empty state inside el, styled like the card's body text
Live.gate(el)            // Promise<session|null>: renders the sign-in panel (link to /index.html) or the
                         // "Original is off for this workspace" panel into el and resolves null when the page
                         // cannot load data; otherwise resolves the session
Live.signOut()           // removes TOKEN_KEYS, then location.replace('/index.html')
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
| Bluebook pill | links to `/bluebook/` (React, Task C) | 1 |

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
