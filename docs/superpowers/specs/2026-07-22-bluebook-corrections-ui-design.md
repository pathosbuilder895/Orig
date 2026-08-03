# Bluebook Corrections UI — Design

**Date:** 2026-07-22 · **Status:** approved (user, this date) · **Sub-project 2 of 4** in the Bluebook improvement track (1: exam-day robustness — done; 3: keystroke→Tier-17; 4: WS-8 component adoption).

## Problem

The correction endpoint (`POST /submissions/{id}/correct`) and its audit trail (`GET /admin/audit`, `GET /admin/corrections`) are fully implemented and tested server-side, but no page calls them. `demo/bluebook/components.jsx`'s `BB_API.fileCorrection()` is defined and never invoked. `Results.jsx`'s `ExpandedRow` has a "Mark Reviewed" button that is pure local component state — no network call, doesn't persist, resets on reload, and doesn't correspond to what a correction actually is (a specific `is_correct` judgment on the AI verdict, not a generic "I looked at this" flag). `professor-journey.spec.mjs`'s correction test exercises the API directly, with a comment explicitly flagging the missing UI.

**User decisions (this session):** replace "Mark Reviewed" entirely rather than keep it alongside a real correction action; give the full override picker (corrected_verdict + corrected_action, both optional) rather than a bare correct/incorrect flag; show correction history on row-expand, not just a bare form.

## §1 — Thread the seal uuid through scoring

**File:** `demo/bluebook/Exam.jsx`

`bbScoreWithOriginal(studentId, text, assignment)` gains a fourth parameter, `submissionId`, forwarded as `submission_id` in the `POST /students/{id}/score` request body. The seal flow (already rewritten in sub-project 1) calls it as `bbScoreWithOriginal(studentId, content, cfg.title, seal.uuid)`.

This is additive on the backend: `ScoreSubmissionRequest.submission_id` is already optional (`original/schemas.py`), and `score_submission` already prefers a client-supplied id over its auto-generated fallback (`original/api.py`, `submission_id = req.submission_id or f"{student_id}_submission_{state.sample_count}"`). No backend change in this section.

**Effect:** the same `submission_uuid` now identifies one sitting across the score call, the baseline write, and the Bluebook submission record (`bluebook_submissions.submission_uuid`, added in sub-project 1). `submit_correction`'s owner-resolution (`_repo().submission_student_id`, which checks the manifest then the score audit log) finds this id without any new lookup — a Results row already carries everything `/submissions/{id}/correct` needs.

**Cold-start case:** `POST /students/{id}/score` 422s when the student has zero authenticated baseline samples yet (documented in `professor-journey.spec.mjs`). No score audit row is written when this happens, so `submission_uuid` exists on the Bluebook submission record (sub-project 1 always sets it) but resolves to nothing correctable. §2 handles this by disabling the form with an explanation rather than erroring.

## §2 — `CorrectionPanel` replaces the fake "Mark Reviewed"

**File:** `demo/bluebook/Results.jsx` (the `ExpandedRow` component, right-column "Examiner's Notes" section)

New sub-component, `CorrectionPanel({ result })`, replacing the existing notes-textarea-plus-`Mark Reviewed`-button block:

- **On mount (row expand):** `GET /admin/corrections?submission_id={result.submission_uuid}` via a new `BB_API.listCorrections(submissionId)` method (mirrors the existing `listSubmissions`/`listExams` fetch-and-return-array-or-null pattern in `components.jsx`). Renders returned corrections as read-only history, most recent first: reviewer, relative timestamp, `is_correct` (✓/✗), `corrected_verdict`/`corrected_action` if present, notes.
- **The form**, below the history:
  - Correct / Incorrect toggle (required to submit).
  - When Incorrect is selected: two optional `<select>`s — `corrected_verdict` (`authentic` | `uncertain` | `anomalous`, plus a blank "no change" option) and `corrected_action` (`no_action` | `monitor` | `schedule_conversation` | `escalate`, plus blank). Hidden entirely when Correct is selected (nothing to override).
  - Notes `<textarea>` — same visual styling as today's, always present.
  - Submit button, calls `BB_API.fileCorrection(result.submission_uuid, { isCorrect, correctedVerdict, correctedAction, notes, reviewer })`.
- **`BB_API.fileCorrection` signature change** (`components.jsx`): add `correctedAction` and `reviewer` to the options object, both forwarded as `corrected_action`/`reviewer` in the POST body (currently only sends `is_correct`/`corrected_verdict`). `reviewer` is populated from the logged-in staff principal's email/name, read the same way other staff-identity displays in this codebase already resolve it — verify the exact source at implementation time (likely a decoded principal token field or a value already threaded into `BB_API`'s auth context).
- **After a successful file:** prepend the new correction (from the POST response, which echoes the full `CorrectionResponse`) to the visible history without a re-fetch; reset the form (toggle back to unset, dropdowns cleared, notes cleared) so a follow-up correction can be filed — the backend explicitly supports multiple corrections per submission, most-recent-wins.
- **No `result.submission_uuid`** (a row sealed before sub-project 1 landed, or a cold-start sitting per §1): render the form area disabled with the message "This submission wasn't scored — no verdict to correct." History fetch is skipped entirely in this case (nothing to key it on).
- **Network/validation failure:** surface `fileCorrection`'s thrown error message inline above the form (it already extracts `detail` from a non-ok response — see `components.jsx`); the form stays populated so the professor doesn't lose their input.

## §3 — Results row list

No changes needed. `list_bluebook_submissions` already returns `submission_uuid` per row (sub-project 1); `Results.jsx`'s row-building code already passes the full submission object through to `ExpandedRow` (`result` prop), so `result.submission_uuid` is already available without touching the row-fetch path.

## §4 — Testing

No JS unit-test harness exists in `demo/bluebook/` (`package.json`'s `test` script is `playwright test` — confirmed, no vitest/jest config present), so this is e2e-only, consistent with the rest of the Bluebook test suite.

**`professor-journey.spec.mjs`:** rewrite the existing "a correction filed against the scored submission lands in corrections and the audit trail" test to drive the actual panel — expand the sealed submission's row in Results, fill the Correct/Incorrect toggle + optional dropdowns + notes, submit, and assert the correction appears in the visible history — instead of calling `POST /submissions/{id}/correct` directly via `request`. Delete the test's header comment about "No frontend affordance exists for this" (no longer true) and the file-level docstring's matching note (`e2e/professor-journey.spec.mjs`'s "one honest gap remains" section). Keep the underlying assertions (`GET /admin/corrections`, `GET /admin/audit` action=correction) as API-level verification alongside the UI-level ones, not a replacement for them — proving the pipeline end-to-end from click to audit row is more valuable than either alone.

**New test:** cold-start disabled-state case — a submission with no `submission_uuid` (or one whose score 422'd) shows the disabled explanation, not a broken form.

## Out of scope

- Bulk correction / multi-select across rows.
- Editing or retracting a previously-filed correction (the backend's "most recent wins" model doesn't support deletion; out of scope here).
- Any change to `submit_correction`'s authorization, validation, or persistence — this sub-project is UI-only plus the additive `submission_id` threading in §1.
