# Counsel packet: Bluebook legal pages for independent teachers

*Prepared 2026-10-11 for counsel review (plan Task B2). Engineering does not edit
`demo/legal/**`; counsel's answers go back to Andrew, and engineering then applies
them. Wording marked "Proposal" is a starting point from engineering, not legal
advice.*

## Who the pages are for

Bluebook is in an **invitation-only pilot for independent teachers**: 1 to 3 to
start, possibly a few dozen. Each teacher gets a private workspace and has **no
school or institution contract behind them** (`docs/NORTH_STAR.md`). Teachers
invite their own students by email. Bluebook is a locked, in-browser writing and
exam app.

Original, the separate writing-consistency feature, is **off by default**. An
operator can switch it on for one workspace. If they do, it compares a student's
new writing with earlier writing the teacher has approved, and every result is
labelled as "testing phase, not validated on real student writing".

The three pages are served at `/legal/privacy.html`, `/legal/terms.html` and
`/legal/student-notice.html`. Invited teachers must tick acceptance of the terms
and privacy policy before setting a password. The server records the
`TERMS_VERSION` they accepted.

## 1. Blanks to fill

| Page and line | Blank | Notes for counsel |
|---|---|---|
| `privacy.html:18` | `[company legal name and address]` | The operating entity. |
| `privacy.html:37` | `[confirm region]` | Render, Oregon (US West), per `render.yaml`. Hosting is not yet signed off. |
| `privacy.html:40` | `[object-storage provider]` | Cloudflare R2 or Backblaze B2, whichever Andrew opens. Backups are encrypted before upload. |
| `privacy.html:45` | `[30]` (backup retention, days) | Must match the bucket's lifecycle rule once it is set. |
| `terms.html:15` | `[company legal name]` | Same entity as the privacy page. |
| `terms.html:42` | warranties, liability, indemnity | The placeholder says "a free educational service". Confirm the pilot is free; billing is not built. |
| `terms.html:45` | governing law and venue | |

`student-notice.html` has no blanks.

## 2. Sentences that become untrue when Original is on

1. **`student-notice.html:25`** (under "What Bluebook does not do"): "It does not analyse your writing style or compare it with your earlier work."
2. **`privacy.html:33`**: "...and Bluebook does not analyse a student's writing style or compare it with earlier work."

Both are true for a Bluebook-only workspace. Neither is true where Original is
on. There, a teacher can approve a student's sealed exams as reference writing,
including exams sat before Original was switched on. Original then compares
later writing with them. Teachers can undo an approval.

**Proposal for the student notice:**

> Bluebook itself does not analyse your writing style. If your teacher's
> workspace uses Original, a separate feature that is still in its testing
> phase, your teacher may choose some of your sealed work as reference writing
> and compare later work with it. Your teacher can undo that choice. A result
> is only ever a reason for a conversation with you, never evidence on its own.

**Proposal for the privacy page:** the same idea in third person. Also add
"reference writing approved by the teacher, and comparison results" as a data
category that exists only where Original is on.

## 3. Lines that assume a school

| Page and line | Text | Question |
|---|---|---|
| `privacy.html:21` | "When a teacher uses Bluebook for a school, we process student information on the school's and teacher's behalf..." | What is our role when there is no school, only an independent teacher? |
| `terms.html:24` | "...you confirm that you are authorised to do so (for example by your school)..." | What should an independent teacher confirm before adding students? |
| `student-notice.html:29` | "Only your teacher (and people your school authorises)." | Change to "Only your teacher" where there is no school? |

## 4. Age of students

`privacy.html:51` and `terms.html:24` set 13 as the minimum age, and make the
teacher responsible for any legally required consent for younger students.
**Andrew has not yet said what ages these teachers' students are**
(NORTH_STAR open question). Under-13 students would bring COPPA parental-consent
duties. Counsel should confirm the right floor and who obtains consent.

## 5. Other things counsel should know

- **Contact address.** `hello@originalvoice.io` appears on all three pages and on
  the Bluebook landing page. Confirm the mailbox exists and who answers it.
- **Processors.** SendGrid receives teacher and student email addresses and
  invitation links (no student writing). Sentry, if enabled, receives error
  reports scrubbed of request bodies. Both need data processing terms.
- **Data handling facts the pages rely on.** Engineering asserts these:
  - no keystroke data is collected;
  - no third-party analytics or fonts;
  - student writing stays in the deployment;
  - a teacher can delete a student and all their work.

  The supporting evidence is the 4 October exposure audit and rehearsal in
  `docs/release/VERIFICATION_AND_BLOCKERS.md`. These facts have not yet been
  re-checked on the live deployment (that is acceptance step B4).
- **Finalising.** Once the text is final, engineering removes the three draft
  banners and sets one final version string, for example `2026-11-01`. It must
  be the same in the pages, in `original/routers/auth.py` (`TERMS_VERSION`) and
  in `demo/bluebook/Account.jsx`. `tests/test_legal_release_guard.py` refuses a
  half-final release.
