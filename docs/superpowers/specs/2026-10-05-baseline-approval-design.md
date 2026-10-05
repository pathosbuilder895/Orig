# Professor-approved writing baselines (plan Phase 7) and Bluebook-only tenant default

Date: 2026-10-05. Branch `claude/professor-release-continuation` (PR pathosbuilder895/Orig#227).
Status: design approved by the owner in conversation; implementation plan to follow.

## Purpose

Bluebook must work on its own, and the writing it captures must be usable by Original. Today:

- With Original on for a workspace, every sealed exam joins the student's Original baseline automatically. The release
  plan (Phase 7) and the handoff require that only professor-approved samples enter baselines.
- With Original off, sealed exams are stored (full text, answers, timing, coarse lockdown events) but there is no path
  to turn them into Original baseline samples later, so switching Original on starts every student from nothing.
- On Postgres, a workspace row created implicitly (`_ensure_tenant_exists`, e.g. a staff account registered before its
  workspace) defaults to both products, so it can hold Original without an operator switching it on.

## Owner decisions (2026-10-05)

| Question | Decision |
|---|---|
| What happens at seal when Original is on | **Compare only.** The seal runs the report-only comparison against the existing baseline and adds nothing to it. |
| Which sealed exams can become baselines | **Any sealed exam** in the professor's own workspace, including ones sat while the workspace was Bluebook-only. No per-exam consent check. The student notice (legal page, plan task B2) should tell students that sealed exams may be used as reference writing if the instructor's workspace uses Original. That is a counsel item, not code. |
| Can an approval be undone | **Yes.** Each approved exam can be removed; the profile is recomputed. |
| Where professors approve | **Per exam** in the submission reader, **plus bulk** per examination. |
| How "in baseline" is recorded | **Derived from the baseline itself** (approach A): no approval columns or tables; the audit log records who and when. |

## Design

### 1. Server

New routes in the live stack (`original/routers/`), all requiring a staff principal of the submission's or exam's own
workspace, and a workspace that holds Original:

| Route | Behaviour |
|---|---|
| `POST /bluebook/submissions/{submission_id}/baseline` | Add the sealed exam to the student's baseline. |
| `DELETE /bluebook/submissions/{submission_id}/baseline` | Remove it from the baseline; the profile is recomputed. |
| `POST /bluebook/exams/{exam_id}/baseline` | Bulk: add every sealed submission of the exam. |
| `GET /bluebook/exams/{exam_id}/baseline` | In-baseline status for each submission of the exam. |

Rules:

- **Reuse, don't copy.** "Add" calls the existing baseline-write handler (`POST /students/{id}/baseline`'s function in
  `original/routers/students_baseline.py`) internally, with the professor's request, so validation, the seal-replay
  fingerprint guard, the drift gate, the audit entry and provenance rules apply unchanged.
- **Sample content.** Provenance `proctored` (a timed Bluebook sitting, approved by staff, which the provenance rules
  already trust). `assignment` = the exam title. `submitted_at` = the submission's `created_at`. `submission_uuid` =
  the submission's seal id, so a retried add is a no-op.
- **Text.** The student's answers joined with a blank line, without the "Question N." headings that the stored `text`
  carries for multi-question exams. A single-answer exam uses its answer. The same derived text is used for the
  fingerprint when checking status or removing.
- **"In baseline"** means: the SHA-256 of the derived text equals the SHA-256 of a sample's text in the student's
  profile. No new columns.
- **Outcomes for add:** `added`; `already_in_baseline` (same fingerprint already present; no-op); `held` (the drift gate
  returned flag-for-review or reject; the sample is not admitted and the professor sees the gate's reason; approval
  does not override the gate).
- **Remove.** Find the sample with the matching fingerprint, delete it, persist, and recompute. Needs
  `StudentState.remove_sample(...)` in `original/quantum/state.py` that invalidates exactly the cached values
  `add_sample` invalidates. Outcomes: `removed`, `not_in_baseline`.
- **Bulk** applies "add" to each sealed submission of the exam; a submission with no answer text is counted as
  `nothing_written` instead of failing the batch. It returns
  `{"added": n, "already_in_baseline": n, "held": n, "nothing_written": n, "errors": n, "results": [{submission_id, student, status, detail}]}`;
  any other failure for a submission is reported as status `error` without stopping the batch.
- **Audit.** `baseline_approve`, `baseline_remove` and `baseline_approve_bulk` audit entries with tenant, actor and
  submission/exam ids (the bulk entry also carries the per-status counts and id lists). No student text in audit details.

Errors:

| Case | Response |
|---|---|
| Workspace lacks Original | 403 `This workspace's plan does not include Original.` |
| Submission or exam not found, or in another workspace | 404 |
| Caller is a student or anonymous | 403 / 401 (existing staff rules) |
| Submission has no answer text | 422 `Nothing written to add.` |
| Drift gate holds it | 200 with `status: "held"` and the gate's reason |
| Remove when not in the baseline | 200 with `status: "not_in_baseline"` |

### 2. Seal and professor screens

- **Seal, Original on** (`demo/bluebook/Exam.jsx`): remove the baseline write (`bbSubmitToOriginal`). Keep the
  report-only comparison call (`bbScoreWithOriginal`), which returns no result on any failure including a 403. The
  `stylometric` figure (computed from the write's drift) is no longer computed at seal and is recorded as null. The
  submission's status keeps its rule on the comparison result alone. The Task 12 403-downgrade branch, which was
  attached to the write, goes with it. The student's notice ("After you submit, your writing is compared with your own
  past work") remains true. Bluebook-only workspaces are unchanged.
- **Submission reader** (`demo/bluebook/Teacher.jsx`, the panel with "Save mark and feedback"), only when the workspace
  holds Original: a "Writing baseline" line showing **In baseline** / **Not in baseline**, with **Add to baseline** /
  **Remove from baseline** (removal confirms first). Result messages: "Added to <student>'s baseline." / "Already in
  the baseline." / "Not added: this exam differs strongly from the student's existing samples, so it was held for
  review."
- **Examination management page** (next to Release results and Export CSV), only with Original: **Add all sealed
  submissions to baselines** (confirms first), then a summary such as "12 added · 3 already in baseline · 1 held for
  review" naming the held ones.
- Wording follows "consistency, not accusation": the baseline is the student's own reference writing; a held exam is
  "held for review", never "suspicious".

### 3. Bluebook-only default for implicit workspace rows

- New Alembic revision (down revision `f4c9a2d71b30`) changing the Postgres `server_default` of `tenants.products_json`
  from `["original", "bluebook"]` to `["bluebook"]`; downgrade restores it. Existing rows keep their products.
- `original/db/models/live.py` `products_json` `server_default` changes to match, and its comment explains why.
- SQLite is unchanged: it never creates implicit workspace rows, and the demo sandbox relies on both products.
- `docs/BLUEBOOK_LAUNCH_CHECKLIST.md`'s expected `Running upgrade … -> f4c9a2d71b30` line names the new revision.

## Testing

- **Server routes (TDD):** add; add twice; held by drift; remove then re-add; bulk counts; multi-question text without
  headings; Bluebook-only workspace → 403; another workspace → 404; student → 403; empty text → 422; audit entries for
  each action.
- **Score integrity:** after `remove_sample`, the profile (density matrix, baseline mean/std, counts) equals one built
  from the remaining samples from scratch; the `score-integrity-reviewer` agent reviews the `quantum/state.py` change.
- **Migration (local Postgres test database):** after upgrade, a tenant row inserted without products has
  `["bluebook"]`; downgrade restores the old default; existing rows are unchanged.
- **Browser (Playwright):** in an Original workspace a seal makes no `POST /students/{id}/baseline`; the professor adds
  an exam from the reader, sees "In baseline", removes it, and runs the bulk action and sees the summary; a Bluebook-only
  workspace shows none of these controls.
- **Finally:** the full CI command with Postgres and the known-red lane.

## Docs

- `docs/BLUEBOOK_LAUNCH_CHECKLIST.md`: a short "Approving exams as writing baselines" item.
- `docs/data_inventory.md`: sealed exams enter Original baselines only by professor approval.
- `docs/release/VERIFICATION_AND_BLOCKERS.md`: counsel item for B2, student-notice wording on sealed exams used as
  reference writing.

## Out of scope

Original's validity gates (T-01 false alarms with few samples) are unchanged; Original stays off unless an operator
switches it on. No change to scoring, thresholds or research flags. No consent tracking per submission.
