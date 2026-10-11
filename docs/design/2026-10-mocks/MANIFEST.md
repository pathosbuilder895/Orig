# Original — Navy Suite Handoff

**Target:** `Original-ws7/frontend/`
**Rule:** copy ONLY the files listed below. Overwrite same-named files. Do not add, delete, rename, or edit any other file in `frontend/` or anywhere else in the repo.

## Allowlist (24 files)

Pages (13) → `frontend/`
- original-dashboard.html — Overview (Canvas LTI lands here)
- original-students.html — roster
- original-quantum.html — Writing State (opened from a student)
- original-review.html — Submissions queue
- original-bluebook-teacher.html — Bluebook session setup + review
- original-reports.html — term report, per-course tabs
- original-settings.html — flag sensitivity, connections, courses (NEW)
- original-flagged.html — conversation packet (replaces existing)
- original-baseline-voice.html — voice baseline (NEW)
- original-voice.html — student: My Voice (NEW)
- original-my-work.html — student: My Work (NEW)
- original-library.html — student: Library (NEW)
- original-bluebook-student.html — student: exam booklet (NEW)

Scripts (2) → `frontend/js/`
- js/feature-data.js
- js/fingerprint.js

Images (9) → `frontend/assets/`
- all-souls-engraving-wide.png, codrington-library.jpeg, gonville-caius-facade.png, long-room-library.png, radcliffe-interior.avif, radcliffe-night-stars.jpeg, radcliffe-observatory-watercolour.jpg, st-andrews-quad.jpg, white-stag.png

## Never ship (exist in the design project, superseded)
Anything containing `-old`, `-classic`, `copy`, `-detailed`, `-twin`, plus `Product Dashboard - Student.html`, `Temporal Intelligence.html`, `Canvas*.dc.html`. None are in this package. If you see one, stop.

## Verify after copying
1. `git status` / `git diff --stat` — only the 24 paths above may appear.
2. `grep -rlE "old|classic|copy|detailed" frontend/*.html` against the new files → must be empty of new additions.
3. Open `frontend/original-dashboard.html` via the running app; click every top tab — each must render the navy design.

## Known open items (do not "fix" by editing these files — report back)
- `original-quantum.html` links "Open full Feature Profile →" to `original-features.html`, which is NOT in this suite. The deployed one is the old light design. Either leave as-is or remove the link in a separate change.
- Overview calls `GET /api/v1/overview` (JSON shape documented in a comment in original-dashboard.html). Until it exists, the page shows its built-in sample data.
- Backend redirects still point at `professor.html`, `student.html`, `admin.html` (not in this suite). Student-side entry should become `original-voice.html`.
