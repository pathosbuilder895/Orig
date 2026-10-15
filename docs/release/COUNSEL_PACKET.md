# Counsel packet: Original Collections legal pages for independent teachers

*Prepared 2026-10-11 for counsel review (plan Task B2). Engineering does not edit
`demo/legal/**`; counsel's answers go back to Andrew, and engineering then applies
them. Wording marked "Proposal" is a starting point from engineering, not legal
advice.*

## Who the pages are for

Original Collections (in the app: Collections; formerly Bluebook) is in an **invitation-only pilot for independent teachers**: 1 to 3 to
start, possibly a few dozen. Each teacher gets a private workspace and has **no
school or institution contract behind them** (`docs/NORTH_STAR.md`). Teachers
invite their own students by email. Collections is a locked, in-browser writing and
exam app.

Original, the separate writing-consistency feature, is **off by default**. An
operator can switch it on for one workspace. If they do, it compares a student's
new writing with earlier writing the teacher has approved, and every result is
labelled as "testing phase, not validated on real student writing".

The three pages are served at `/legal/privacy.html`, `/legal/terms.html` and
`/legal/student-notice.html`. Invited teachers must tick acceptance of the terms
and privacy policy before setting a password. The server records the
`TERMS_VERSION` they accepted.

## 0. Update, 2026-10-13: pages rewritten to match the code

On Andrew's instruction (overnight task, PR #273) engineering rewrote all three
pages so every statement matches what the code does, with a code citation for
each in that PR's description, and marked each page "DRAFT, pending counsel
review" at the top. The version string is unchanged (`2026-10-01-draft`), so no
teacher's recorded acceptance changes meaning. `tests/test_legal_pages_match_code.py`
now fails if a page drops one of those statements or the code stops matching it.
The sections below are updated to the new text.

Things counsel should know that the code does **not** do yet, and that the pages
now say plainly:

- **Retention.** The pages state the defaults Andrew set (365 days for submitted
  work, 35 days for backups), and say that automatic deletion at 365 days is
  not switched on yet: nothing in the live stack deletes work on a schedule.
  Either it is built before launch, or the default changes.
- **Backups expire by a bucket rule**, not by code. The 35 days holds only once
  that lifecycle rule is set on the bucket (owner step B1).
- **Request logs record an IP address and user agent** for each request (the
  app's request log, kept by Render, not in the database). No IP address is
  stored in the database; one operator route that used to write the caller's
  address into the audit log was changed in PR #273.
- **Deletion leaves sign-in records** (they hold the email address used), one
  receipt of the deletion, and backup copies until they expire.
- **No age check** exists in the product.

## 1. Blanks to fill

| Page and section | Blank | Notes for counsel |
|---|---|---|
| privacy, "Who we are" | `[company legal name and address]` | The operating entity. |
| privacy, "Request logs" | Render's log retention | Plan-dependent; Andrew reads it from the Render dashboard. |
| privacy, "Who processes it for us" | confirm R2 and its location | Cloudflare R2 is the intended backup store; the code works with any S3-compatible store. Backups are Fernet-encrypted before upload. |
| privacy, "Who processes it for us" | is error reporting on? | `SENTRY_DSN` is set in the dashboard, not in `render.yaml`. |
| privacy, "How long we keep it" | build 365-day deletion, or change the default | See section 0. |
| privacy, "How long we keep it" | 35-day bucket rule; Render snapshot period | Owner confirmations. |
| privacy, "Children" | student age range | See section 4. |
| terms, header | `[company legal name]` | Same entity as the privacy page. |
| terms, section 3 | terms for a teacher with no school agreement | See section 3. |
| terms, section 10 | warranties, liability, indemnity | The placeholder says "a free educational service". Confirm the pilot is free; billing is not built. |
| terms, section 11 | governing law and venue | |

`student-notice.html` has no blanks.

## 2. Sentences that were untrue when Original is on: resolved

The two "does not analyse your writing style" sentences are gone. Both the
privacy page and the student notice now have a section on Original: off by
default, in its testing phase, a reason for a conversation and never proof,
sealed work joins a writing profile only when the teacher approves it (and the
teacher can undo that), and no score is shown to students in Collections. The
terms have a matching section 5. Counsel should check that wording.

## 3. Lines that assume a school

| Page and section | Text now | Question |
|---|---|---|
| privacy, "What the service is for" | "...on the teacher's behalf (and, where there is one, the school's)..." | What is our role when there is no school, only an independent teacher? |
| terms, section 3 | "...you confirm that you are allowed to do so..." | What should an independent teacher confirm before adding students? |
| student notice, "Who sees your work" | "Your teacher, and anyone your school authorises." | Drop the school where there is none? |

## 4. Age of students

`privacy.html:51` and `terms.html:24` set 13 as the minimum age, and make the
teacher responsible for any legally required consent for younger students.
**Andrew has not yet said what ages these teachers' students are**
(NORTH_STAR open question). Under-13 students would bring COPPA parental-consent
duties. Counsel should confirm the right floor and who obtains consent.

## 5. Product name

The product was renamed from "Bluebook" to **Original Collections** (in the app,
**Collections**) on 2026-10-11 because of trademark risk; the legal pages, emails and
screens now use the new name. Counsel should confirm that "Original Collections" is
clear to use before the pages are made final.

## 6. Other things counsel should know

- **Contact address.** `hello@originalvoice.io` appears on all three pages and on
  the Collections landing page. Confirm the mailbox exists and who answers it.
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
