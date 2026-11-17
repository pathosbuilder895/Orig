# Original alpha workflow: honest approval counts, any paper analysed against a baseline, add a writer

Spec: the user's requests of 2026-11-13 (after PR #340), restated in "Spec" below. Stacked on branch
`claude/original-demo-parity-fe7f3a` (PR #340); this branch is `claude/original-alpha-workflow`,
checked out in the worktree `/Users/andrew/Code/Orig/.claude/worktrees/original-demo-parity-fe7f3a`.

## Spec (binding)

1. Fix "0 teacher-approved" on the real pilot. Owner decision: **wording only, no score change**.
   Approved sealed take-home Collections exams (`original/routers/bluebook_baselines.py:197`) and
   accepted student-shared past papers (`original/routers/past_papers.py:264`) are stored with
   provenance `unverified` (weight 0.5) on purpose. They stay that way. The pages must stop calling
   them "not teacher-approved": they were approved by the teacher, and count at a lower weight.
2. A teacher can analyse any paper against a student's baseline, not only inside Collections:
   - Writing State accepts .docx and .pdf (plus paste and .txt).
   - A sealed Collections exam can be sent to Writing State and analysed against that student's
     baseline without copy-pasting.
3. Alpha phase: people email the owner four papers; the owner makes a baseline from three and
   analyses the fourth. Other writers come through Collections rosters. Both must work. Owner
   decision: an **"Add a writer" form in Original** creates a writer by name, with no course, no
   email, no invite and no account.

### Global Constraints (copy verbatim to every implementer and reviewer)

1. No change to any score, threshold, weight, provenance, `auth_weight`, feature, or what the engine
   computes. Do not edit `original/quantum/`, `original/features/`, `original/context/`,
   `original/constants.py`, `original/store.py` scoring paths, or the scoring logic of
   `original/routers/students_scoring.py`. Sample provenance values and weights are unchanged.
2. No persistence schema change and no Alembic migration. Where the server must say how a sample got
   in, derive it at read time from data already stored.
3. New work must not change existing behaviour for paths it does not target. Collections student
   flows, join/invite links, the landing rule from PR #340 and flags-off pages stay as they are.
4. Students never see scores, evidence, passages, the preliminary label, or other students. Every new
   route is staff-only and tenant-scoped (follow how `original/routers/students.py` and
   `original/routers/bluebook.py` check principals, and the `tenant_isolation` middleware in
   `original/api.py`). Test that a student principal and another tenant's staff are refused.
5. Only teacher-approved writing becomes a baseline (NORTH_STAR rule 8). Analysing a paper never adds
   it to a baseline.
6. Never write "AI detection", "cheating", "authorship verification", "fingerprint", "proves",
   "verifies" in user-facing text; no accuracy claims. Keep the testing-phase notice. Real data only.
7. Escape every user-visible string (`Live.esc`) before innerHTML. No U+2014/U+2015 dashes anywhere.
8. Python: `/Users/andrew/Code/Orig/.venv/bin/python` (no venv in this worktree). Node:
   `cd demo/bluebook && npm ci` if `node_modules` is missing; after any `.jsx` edit run `npm run build`
   and commit the bundles. If any shared script (`demo/original/live.js`, `demo/original/js/*.js`)
   changes, bump the shared `?v=` tag on every `demo/original` page from `2026-11-13.1` to
   `2026-11-13.2` once, keeping `tests/test_original_suite_static.py`'s version test green.
9. Work only in `/Users/andrew/Code/Orig/.claude/worktrees/original-demo-parity-fe7f3a` on branch
   `claude/original-alpha-workflow`; never switch branches. Never kill or restart a server you did not
   start; start your own on a free port (8041+) exactly like CI's (`.github/workflows/test.yml`), and
   stop it when done.
10. Conventional commits, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.
11. Any change under `original/` that uses the repository/persistence layer needs tests against
    Postgres too: write `postgres`-marked tests where the SQLite and Postgres repositories differ.
    Docker is not running on this Mac, so say in the report which postgres tests exist and were not
    run locally.

## Tasks

### Task 1: The server says how each baseline sample got in

`GET /students/{id}` (`original/routers/students.py:get_student`) adds a read-only `source` to each
`SampleSummary` (`original/schemas.py`), derived at read time with no schema change:

- `staff_or_supervised`: provenance `verified`, `proctored` or `canvas`.
- `take_home`: provenance `unverified` and sha256 of the sample text equals the approved baseline
  text of one of that student's sealed Collections submissions (same text form as
  `bluebook_baselines.py` `_baseline_text`/`_fingerprints`).
- `shared_paper`: provenance `unverified` and the text hash equals one of that student's approved
  past papers (`past_papers.py`).
- `student_upload`: any other `unverified` sample.
- `unknown`: anything else (future provenances).

See the appendix for file:line pointers. Keep it cheap: one query for the student's submissions and
one for their past papers per call, hashing only `unverified` samples. Unit and API tests for each
value on SQLite; `postgres`-marked tests if the repository methods used differ on Postgres. If the
repo pins an OpenAPI snapshot (`tests/` `test_openapi_snapshot`, already failing locally on clean
main), update it the way the repo documents. Do not expose the field to student principals in any
other route.

### Task 2: Honest approval wording on every page

One shared helper in `demo/original/live.js`, e.g. `Live.approvals(samples)`, returning
`{counted, byYou, supervised, takeHome, shared, uploads, unknown}` from `samples[].source` (fall
back to today's provenance rule when `source` is missing, so an old server keeps working). Use it on
`writing-state.html` (`teacherApproved`/`countedPhrase`/`thinResultLine`), `packet.html` (its
teacher-approved split and baseline table), `evidence.html` (past-paper table "How it was added"),
and `baseline.html` (`approvedN`/`uploadsN` and the split at ~line 748). Wording, for example:
"3 counted samples, all approved by you (2 take-home exams and 1 shared paper count at a lower
weight)" or "3 counted samples: 1 approved by you, 2 student uploads". Update
`tests/test_original_suite_static.py` cases that pin the old wording (they run the pages' JS in
node); keep their intent. Readiness wording (`ready needs 5 or more counted samples...`) unchanged.

### Task 3: Writing State reads .docx and .pdf

The "or open a .txt file" control on `writing-state.html` becomes "or open a .docx, .pdf or .txt
file". .txt stays client-side. .docx/.pdf go to the existing `POST /students/{id}/upload`
(`original/routers/students.py:358`, text extraction: confirm it stores nothing and adds nothing to
a baseline; if it does store, use or add an extraction-only path instead). Show the extracted word
count and an honest error on failure (unsupported type, empty text, scanned PDF with no text layer).
Size limit matches the server's. Assignment prefilled with the file name without extension when
empty.

### Task 4: Analyse a sealed Collections exam against the baseline

- Writing State accepts `?student=<id>&submission=<sealed submission id>`: it loads
  `GET /bluebook/submissions/{id}` (staff-only, tenant-scoped), checks the submission's
  `student_id` equals `student`, fills the paper with the answers joined by a blank line (the same
  text form the baseline approval uses, never the "Question N." headings), fills Assignment with the
  exam title and sealed date, and shows "Loaded from Collections: <exam>, sealed <date>". The
  teacher still presses Analyse. Errors (404, 403, mismatch) show a plain message and leave the
  form empty.
- Entry points: an "Analyse against baseline" action on each row of `demo/original/submissions.html`
  (only when the student has a baseline; otherwise a link to add writing), and in the Collections
  teacher reader (`demo/bluebook/Teacher.jsx`, where the sealed submission is shown) an "Analyse in
  Original" link when `BB_API.hasOriginal()`, opening the same URL. Rebuild bundles.
- Students never see either control.

### Task 5: Add a writer by name

- New staff-only route `POST /students` with body `{name}` (1-120 chars, trimmed): mints a new id for
  the caller's tenant the way existing ids are formed (`"{tenant}:{local}"`, see
  `original/principal.py` tenant_of), calls the repository's get_or_create and set_display_name,
  writes an audit row, returns `{student_id, name}`. Refuse students (403), unauthenticated callers on
  a real deploy, and empty names (422). Works on SQLite and Postgres repositories (postgres-marked
  test).
- `demo/original/students.html`: an "Add a writer" button opening a small form (name, Add). On
  success go to `baseline.html?student=<id>#add-writing` so the teacher adds the three papers.
  Keep the existing "Add student" link to Collections, relabelled "Add to a Collections course" if
  that reads clearer. The new writer appears in the roster with readiness "Needs more" until papers
  exist.
- Deleting a writer uses the existing `DELETE /students/{id}`; check it works for a writer with no
  Collections account.

### Task 6: End-to-end alpha journey and checks

New Playwright spec `demo/bluebook/e2e/alpha-writer.spec.mjs` (main run, flags off) plus one
`@evidence-on` test:
- Staff adds a writer by name on Students; lands on Voice baseline; uploads three papers as
  "Verified by me" (fixtures from `demo/bluebook/e2e/fixtures/evidence/`, at least one as `.docx`
  built by a tiny fixture helper, no new dependency if avoidable); Writing State says 3 counted
  samples approved by you; analyses the fourth from a `.docx` file; the result renders (with evidence
  on, quotes render).
- A take-home sealed exam approved as reference writing shows as approved by you at lower weight,
  not "0 teacher-approved".
- Analyse a sealed exam from Submissions: the paper is prefilled and analysis runs.
- A student session cannot call `POST /students`, cannot open Writing State, and sees no new controls.
Then: ruff on `original/`, the full pytest CI command (32 failures identical to clean main are known
on this Mac: `test_flag_byte_identity` x30, `test_openapi_snapshot`, `test_zero_shot_origin`), unit
tests, bundle byte-identity, both Playwright runs. STATUS.md session-log line.

## Appendix: scout notes (2026-11-13)

- Samples: `BaselineSample` (`original/quantum/state.py:42`) keeps text, provenance, auth_weight,
  assignment, submitted_at; stored inside JSON `student_profiles.data`; no source or
  submission_uuid on the sample. Take-home approval audit `baseline_approve` carries
  `details.submission_id` (`bluebook_baselines.py:251-258`); past paper approval
  `past_paper_approve` carries `details.paper_id` (`past_papers.py:279-286`). Text hash join is the
  reliable derivation; residual risk: split sections (`baseline_source = split`).
- Names: `student_names` table; `set_display_name` used by LTI, auth, magic link, roster add. No
  `POST /students`. `get_or_create` exists. Ids `"{tenant}:{local}"`; Postgres splits to
  (tenant_id, student_id).
- Sealed text: `GET /bluebook/submissions/{id}` (`original/routers/bluebook.py:743`), staff-only:
  `text` (with "Question N." headings), `answers`, `questions`, `student_id`, `student`, `exam`,
  `course`, `exam_id`, `created_at`. Scoring it via `POST /students/{id}/score` is allowed for staff
  and stores no result (except a manifest when CONTEXT_MANIFEST_ENABLED).
