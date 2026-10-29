# Product bar: why a teacher would choose this

*Started 29 Oct 2026 by Claude Code at Andrew's request. `docs/NORTH_STAR.md` wins over this page. This page does not add rules. It sets the quality bar for meeting them, so a teacher picks Original Collections because it is better to use, not only because it is principled.*

The comparison we hold ourselves to: Turnitin is what an institution buys and a teacher puts up with. Original Collections should be what a teacher would pick for themselves.

## Five things that make the difference

### 1. We own the whole loop
Turnitin receives a file and guesses about how it was made. Collections is where the writing happens. The server keeps the clock, the booklet is sealed, and the student gets a receipt. A teacher can then approve that sealed writing as reference writing (`original/routers/bluebook_baselines.py`), and later work is compared with the student's own writing that the teacher watched happen.

*In a PR:* every step of that loop (write, seal, read, approve, undo) must work on its own without a workaround. A lost or unsealed submission is the one failure a teacher will not forgive.

### 2. The teacher is the customer
One invite gives a teacher a private workspace, with no IT department, no LMS and no procurement. The first ten minutes (set a password, create a course, add students, publish a collection) are the product. Most teachers will judge it on those ten minutes.

*In a PR:* walk that path on a laptop and on a phone at 375 px. If a step needs the quickstart to explain it, the screen is wrong, not the teacher.

### 3. Show, don't score
No percentage beside a name, no AI label, no verdict. Original shows what is different, with real sentences from this paper next to sentences from past papers (ADR-013). When the evidence is thin it says "inconclusive". Every result is a reason for a conversation (NORTH_STAR rules 1 to 3).

*In a PR:* a number that a teacher could read as a probability needs a reason to exist. Leave out anything a teacher could screenshot and send to a dean as proof.

### 4. Students are users, not suspects
Students see which conditions are on before they begin, see neutral notes for their teacher, and are told their sealed work may become reference writing that the teacher can take back out. Students keep their work if something goes wrong: drafts autosave, and the seal retries.

*In a PR:* read every new student-facing sentence as an anxious student would. If it sounds like an accusation, rewrite it.

### 5. Privacy you can say in one sentence
"Your writing never leaves this site, nobody records your keystrokes, and your teacher can delete you." A teacher should be able to tell a parent that sentence without checking anything first (NORTH_STAR rules 6 to 8).

*In a PR:* no new third-party host, font, script or analytics, ever, on any page a student or teacher loads.

## The junk test
Run this on any PR that changes a screen a teacher or student sees. Each "no" is a bug, not a nice-to-have.

- [ ] **One word per thing.** The thing a student sits is a **collection** on every screen, teacher and student alike. The document they write in is the **booklet**. See the word list below.
- [ ] **Server and screen agree.** Every rule the screen enforces (limits, open and close times, who may sit) is also enforced by the server, with the same numbers. Most bugs found in the October sweeps were cases where they disagreed.
- [ ] **Loading, empty and error are three different states.** A failed load never shows as "nothing here", and nothing says "Welcome back" to someone who has never been here.
- [ ] **Phone width.** No horizontal scroll at 375 px, and tap targets are big enough for a thumb.
- [ ] **Keyboard and screen reader.** Focus is visible and moves somewhere sensible after each action; the axe checks in `demo/bluebook/e2e/` pass.
- [ ] **No sample data leaks.** No fictional name, course or number can reach a real account.
- [ ] **No banned words** (list below), in the UI, in emails and in the docs a teacher or student reads.
- [ ] **Docs match the screen.** If a button's name changes, `docs/release/PROFESSOR_QUICKSTART.md` changes in the same PR.
- [ ] **Built and committed.** After a JSX edit, `bluebook.bundle.js` is rebuilt and committed (Render has no Node).

## Words

**Use:** collection, booklet, course, sealed, released, reference writing, usual range, consistency, inconclusive, a reason for a conversation, notes for your teacher.

**Never use:** verdict, authentic or confirmed authentic, fingerprint, authorship verification or probability, AI score, AI-written, cheating, flagged student, candidate, and any percentage beside a student's name. Where code already bans a word, a test enforces it (for example the ADR-013 wording tests); this list is the wider bar for copy and docs.

## Known gaps against this bar (29 Oct 2026)
These are tracked elsewhere; this list says why each one matters to a teacher. `docs/STATUS.md` and `docs/testing/10-gap-register.md` have the current state.

- The pilot runs a build from 11 Oct, so none of the October polish is live until a Manual Deploy.
- With no email set up, the teacher copies invite links by hand.
- The legal pages are drafts, and the quickstart still has no named support contact.
- Full-screen lockdown has not been checked on an iPhone, and the browser tests run only on desktop Chrome (T-59).
- Four visual styles across the sign-in pages, the teacher frame, the new-collection form and the booklet.
