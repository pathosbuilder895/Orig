# 2026-10 navy design mockups (reference only)

These are the thirteen page mockups, two scripts and the manifest that came out of the Claude Design "Navy Suite" handoff of 8 October 2026. They are kept here, byte for byte as received, so anyone can see what the live pages in `demo/original/` were built from and what was changed on the way. `docs/adr/012-ui-design-port.md` is the record of every change.

## Read this before opening one

- **Reference only. Nothing here is served.** `run.py` mounts the `demo/` directory as the static site (`run.py:85`, `app.mount("/", StaticFiles(directory=str(frontend_dir), html=True))`, with `--frontend-dir` defaulting to `<project>/demo` at `run.py:103`). `docs/` is outside that tree, so none of these files is reachable from a running server. Do not move them under `demo/`.
- **The files are unchanged.** They still contain the design's fictional names, numbers and dates (James Whitfield, THEO 301, "Dr. Hendricks", case AI-2026-014, "94% of papers read like the students who wrote them", "19 of 103 writing habits"), the Google Fonts links, and the design's own wording about keystrokes, authenticity and AI. Do not copy markup or copy from here into a live page without checking it against `docs/NORTH_STAR.md`.
- **The live pages deliberately do not make these claims.** The design showed flag counts, flag rates, percentages of authentic papers, side-by-side quotes, a 103-habit fingerprint, typing rhythm, case numbers, a flag-sensitivity dial, Canvas and Blackboard connections, and a department. Original has no stored results, no text positions, no keystroke data and no such integrations, and NORTH_STAR rules 1, 2, 3, 6 and 9 forbid presenting them as real. The claim table in ADR-012 lists each one, what the code says, and what the live page says instead.
- **No images.** The handoff's `assets/` folder (nine photographs and drawings) is not copied here. None has a licence on record, and one is a signed 1953 watercolour. The live pages ship the images the owner chose, with a row for each in `demo/original/assets/CREDITS.md`. The mockups below still point at `assets/...` files that are not in this folder, so they open without their photographs.
- **Opening them.** They load fonts from Google, so open them only if you accept that request. The live suite makes no third-party request.
- **MANIFEST.md** is the handoff's own file list. It sat one level above `frontend/` in the handoff folder and is copied here for the record. Its instructions (copy these 24 files into `Original-ws7/frontend/`, then wire `GET /api/v1/overview`) were not followed: the work went into `demo/original/` as static pages on the existing API, and no `/api/v1/overview` exists.

## Where each mockup went

| Mockup | Live page | Notes |
|---|---|---|
| `original-dashboard.html` | `demo/original/index.html` ("Your classes") | "Integrity Operations Center" is now "Your classes". Flag cards become roster, readiness and sealed-exam counts. |
| `original-students.html` | `demo/original/students.html` | Roster with server readiness verdicts. Flag filters and deviation bars removed. |
| `original-review.html` | `demo/original/submissions.html` | Rows are sealed Bluebook exams. Verdict chips removed. |
| `original-quantum.html` | `demo/original/writing-state.html` | "Analyse a paper" card added. Habits are listed by name, with no count. Uses `js/feature-data.js`. |
| `original-flagged.html` | `demo/original/packet.html` | Conversation packet from the last Writing State analysis. No quotes, no case number. |
| `original-baseline-voice.html` | `demo/original/baseline.html` | Where the baseline came from, add writing, approve and undo sealed exams. |
| `original-reports.html` | `demo/original/reports.html` | Counts only. No percentages of authentic papers. |
| `original-settings.html` | `demo/original/settings.html` | Change password, account, courses. Flag Sensitivity, Canvas and Blackboard removed. |
| `original-voice.html` | `demo/original/voice.html` | Student "My Voice" from `GET /me/voice`. |
| `original-my-work.html` | `demo/original/my-work.html` | Student compare-only check from `POST /me/work`. Nothing it receives is added to the baseline. |
| `original-bluebook-teacher.html` | Restyle of the Bluebook teacher React screens (`demo/bluebook/TeacherWorkspace.jsx` and the screens it opens) | Separate branch, `ui-design-port-bluebook`, not part of the `demo/original/` pages. |
| `original-bluebook-student.html` | Restyle of the Bluebook exam booklet (`demo/bluebook/Exam.jsx`) | Same branch. |
| `original-library.html` | None | Skipped by owner decision, 2026-10-10. |
| `js/feature-data.js` | `demo/original/js/feature-data.js` | Names and descriptions only: the invented values are removed and Tier 7 is renamed "Natural Unevenness". |
| `js/fingerprint.js` | `demo/original/js/fingerprint.js` | Same file; four em dashes in comments replaced with colons. |
