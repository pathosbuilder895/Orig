# Bluebook Self-Serve Dashboards — Design

**Date:** 2026-09-28 · **Status:** specified · **Scope:** the Bluebook SPA (`demo/bluebook/`)
on top of the backend in `2026-09-17-bluebook-standalone-backend-design.md`.

## Problem

The backend now supports a public self-serve Bluebook: teacher signup, per-teacher
workspaces, course rosters with invite links, student accounts, exam windows, and a
student API. The SPA predates all of it:

- A teacher can only sign in. "Not yet registered?" is a `mailto:` link.
- There is no student dashboard. A student reaches an exam only through a
  launch link, and then sees Bluebook's built-in sample question, because the
  link carries the title and the SPA never loads the stored exam.
- The seal always calls Original's score and baseline routes. For a Bluebook-only
  workspace those now return 403, so every seal would fail.
- A failed submission record still shows "Sealed" and deletes the draft.
- Teacher tooling saves only the first question and reports success on a failed
  save. It has no edit, publish, delete, roster, or export, and shows hard-coded
  names and dates.
- Copy claims controls a web page cannot enforce.

## Decisions

1. **One SPA, three shells.** The router picks by what `localStorage` holds:
   an `?invite=` URL, a student launch, a student account, a staff account, or
   nobody. Students and teachers never see each other's screens.
2. **Products drive the seal.** The sign-in payload's `products` is stored. When it
   lacks `original`, the seal skips the score and baseline calls and records the
   submission with its text and warnings only. With `original`, the existing flow
   runs, plus text and warnings.
3. **The stored exam is the source of truth.** A student account starts an exam
   through `POST /bluebook/me/exams/{id}/start`, which returns the exam and the
   pinned deadline. A launch-link student with `?exam_id=` loads
   `GET /bluebook/me/exams/{id}`. The built-in sample question only appears in the
   anonymous demo.
4. **A seal succeeds only when the submission is recorded.** `recordSubmission`
   throws on failure, so the existing three-attempt retry covers it and the
   draft is kept on the device until it lands.
5. **Warnings reach the teacher.** Each lockdown warning is recorded with a type
   and time and sent with the seal. The teacher sees the count and the list.
6. **Honest copy.** Conditions describe what the page does ("leaving full-screen
   is recorded"), not what it cannot do ("AI tools are blocked"). The stylometric
   comparison line appears only for tenants with Original. Badges claiming
   encryption, FERPA compliance, or AI detection are removed.

## Screens

**Public**
- *Landing*: "Create a free workspace" and "Sign in". "Explore the demo" is
  shown only when `/health` reports `environment: demo`.
- *Sign up*: name, email, password; lands on the teacher dashboard.
- *Sign in*: unchanged, now routes students and teachers to their shells.
- *Set password* (`?invite=`): password twice; lands on the right shell.

**Teacher**
- *Dashboard*: real date; exam cards link to *Manage exam*.
- *New examination*: all questions are saved (numbered into the one prompt);
  course picker (`course_id`); optional opens/closes; failures shown in place.
- *Manage exam*: status (draft / active / closed), window, submission list with
  word count, time, late flag, warning count, and a text viewer; CSV export;
  delete when there are no submissions.
- *Courses → Roster*: add students (paste emails, one per line or comma
  separated), each result row shows its copyable invite link or its error;
  per-student reissue and remove; invited / active / link states.
- *Results*: score columns hidden when the workspace lacks Original.

**Student**
- *My exams*: open, upcoming, closed, submitted, with times in local time.
- *Briefing → Exam → Submitted*: the existing screens, fed by the stored exam.
- *My submissions*: list and a read-only text view.
- *Account*: change password; sign out.

## Out of scope

Grades and feedback, self-signup for students, email, billing, and any change to the
Original HTML dashboards beyond removing over-claims and the Canvas entry points.

## Testing

- Build the bundle and commit it (CI's byte-identity check rebuilds and compares).
- Drive the real flow in the browser against a local server in pilot mode:
  teacher signs up, creates a course and an exam, adds a student, the student
  redeems the invite, sits the teacher's exam (prompt matches), seals, and the
  teacher reads the text and exports the CSV.
- A new Playwright spec (`e2e/self-serve.spec.mjs`) pins that journey.
