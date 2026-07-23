# Bluebook Exam-Day Robustness — Design

**Date:** 2026-07-22 · **Status:** implemented 2026-07-22 (plan: `docs/superpowers/plans/2026-07-22-bluebook-exam-robustness.md`; backend 836/0, e2e 54/0) · **Sub-project 1 of 4** in the Bluebook improvement track (2: corrections UI, 3: keystroke→Tier-17, 4: WS-8 component adoption).

## Problem

`demo/bluebook/Exam.jsx` already has localStorage drafts, keystroke capture, and timer live-announcements, but four exam-day failure modes remain:

1. **Pausable timer (cheat vector):** `timeLeft` is stored as a countdown remainder in the draft; closing the tab stops the clock. No server-side deadline exists.
2. **Fragile sealing:** the seal flow (`bbScoreWithOriginal` → `bbSubmitToOriginal` → `BB_API.recordSubmission`) has no try/catch, no retry, no idempotency. A network blip mid-seal strands the student on "Sealing…" (`submitting` never clears), and a re-attempt double-writes the sitting into the student's voice profile (double-weighting it in ρ).
3. **No offline awareness:** network loss is invisible until the seal fails.
4. **A11y (audit items):** unnamed writing textarea; timer/offline states not fully announced.

**Architecture decision (user-selected): hybrid.** Deadline is pinned server-side; drafts stay local (localStorage) with a client retry queue. Device-loss risk is accepted for this slice.

## §1 — Server-pinned deadline

**New endpoint:** `POST /bluebook/exams/{exam_id}/session` in `original/api.py`, auth/tenant pattern identical to `recordSubmission` (works for authenticated students and demo/anonymous candidates).

- **Student key:** resolved student id when available, else candidate email (demo flow), namespaced by tenant.
- **First call:** inserts `(exam_id, student_key, tenant_id, started_at, deadline_at = started_at + exam.duration)` into a new `bluebook_sessions` table (store.py + Repository seam + PostgresRepository `_todo` stub, same as every other aggregate). Returns `{started_at, deadline_at, server_now}`.
- **Subsequent calls:** return the **same row** — reopening the exam never restarts or extends the clock.
- **Client:** `Exam.jsx` calls it on mount; computes `timeLeft = deadline_at − (now + server_offset)` where `server_offset = server_now − Date.now()` captured once. `timeLeft` is **removed from the draft**.
- **Degrade open:** if the session call fails (offline start, demo without backend), fall back to the current local countdown. Never strand a student because the network was down at start.

## §2 — Idempotent, retryable sealing

- **`submission_uuid`:** generated client-side at first seal attempt, persisted in the draft so a refresh-and-reseal reuses it.
- Both the baseline POST (`/students/{id}/baseline`) and `recordSubmission` (`/bluebook/submissions`) carry `submission_uuid`. Server-side: unique key; on replay, return the prior result instead of writing again. **This is the fix for double-weighted baseline sittings.**
- **Retry loop:** the whole seal flow wrapped in try/catch; up to 3 attempts with backoff (2s/5s/10s); if `navigator.onLine === false`, wait for the `online` event instead of burning attempts.
- **Final failure:** keep the draft, clear `submitting`, show "Your work is saved on this device — tell your proctor." The draft is only removed after a confirmed successful seal.
- **Late seals:** server accepts seals after `deadline_at` up to a 5-minute grace, tagging the submission `late: true`; beyond grace still accepted but tagged (never destroy student work — lateness is the professor's call, surfaced in Results). If no session row exists for this student (degrade-open start, §1), no late tag is applied — the server can't judge lateness against a deadline it never issued.

## §3 — Offline awareness

- `window` `online`/`offline` listeners drive a persistent polite banner: "Connection lost — your writing is safe on this device." Cleared on reconnect with a matching announcement.
- Seal button while offline reads "Will submit when reconnected" and the retry loop parks until `online`.

## §4 — Exam-page a11y patches (local only)

- `aria-label="Exam answer"`-style name on the writing textarea.
- Timer display gets `role="timer"`; existing `liveMsg` live-region extended to announce offline/reconnect/retry states.
- Warning-log entries continue via the existing polite region.
- **No `app/` component imports in this slice** — WS-8 adoption is sub-project 4.

## §5 — Testing

- **Store/API tests** (`tests/test_bluebook_api.py` + a store-level suite): session create; same `deadline_at` on repeat call; late tagging at/beyond grace; `submission_uuid` dedup on both endpoints, including the replayed-baseline case asserting the profile gains exactly one sitting.
- **Playwright e2e** (`demo/bluebook/e2e/`): refresh mid-exam → deadline unchanged; seal with the API briefly failing → succeeds on retry, draft cleared; seal fails all retries → draft retained + proctor message shown.
- Full suite remains 0 failed; `cd demo/bluebook && npm run build` and commit the bundle (Render has no Node).

## Out of scope (later sub-projects / accepted risks)

- Server-side draft checkpointing (device loss still loses unsealed work — accepted with hybrid).
- Corrections UI (sub-project 2), keystroke→Tier-17 enablement (3), WS-8 component adoption (4).
- Proctoring hardening beyond the existing focus/fullscreen warnings.
