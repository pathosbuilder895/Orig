# Launch-day smoke test and rolling checks (async alpha — replaces the single test-day plan)

The alpha is open-ended and asynchronous (starts 2026-10-19, no fixed end date). There is no single test day or dry-run day. Instead: a **launch-day smoke test** before the first real invite goes out, then **rolling checks** as volunteers arrive.

## Launch-day smoke test (about 1 hour, before first invite)
- [ ] Pilot on the expected commit: `live_smoke.py` PASS; `/health` shows `backend: postgres`, `signup_open: false`. (A transient disconnect was seen 2026-10-19 — rerun until a clean PASS; do not claim PASS from a partial run.)
- [ ] `INVITE_NO_EXPIRY=1` re-confirmed in the Render dashboard (it is not in `render.yaml`), and alpha teacher workspace created with `--no-expiry` (see `setup_runbook.md` §2).
- [ ] Consent + feedback Google Forms built from `google_forms_spec.md`, contact arclark555@gmail.com, tested with a dummy response that is then deleted.
- [ ] 2–3 test accounts on Andrew's own emails: run every step in `join_link_check.md` on Chrome and Safari, plus one phone; share 3 test papers and approve them; open the alpha exam, paste a test piece into question 1 and another into question 2, and seal; batch-score it and confirm the export holds a `-q1` and a `-q2` file; confirm no score is visible to the student account.
- [ ] One split-derived test baseline: split a long test paper, tag it in `baselines.csv`, confirm the report's baseline-source breakout shows it separately.
- [ ] Delete the test accounts (or keep clearly-named spares), then generate the first real invite links.

## Rolling checks (each time a volunteer finishes, and a weekly sweep)
- [ ] Consent response received **before** that person's join link is sent; shadow use only per consent Q11/Q12.
- [ ] Baseline count after import: 3+ papers (drift hold can hold one back — confirm the count the screen reports). Record independent vs split-derived in `baselines.csv`.
- [ ] Alpha exam sealed with both questions answered, no score visible to the student; staff batch-score as submissions arrive (see `scoring_plan.md`).
- [ ] Feedback form sent to that volunteer; copy the AI tool they name into `labels.csv` as `generator_tool`; note any slowness/errors with date/time (ET).
- [ ] Withdrawals: delete that person's data within 14 days of withdrawal (see `deletion_plan.md`); Andrew closes a participation the same way.

## Course sign-up link (forwardable, optional)
Instead of adding each person by email, Andrew can turn on one sign-up link per course and send it to anyone (they can forward it).
- **Turn on:** Courses → the course's roster → **Sign-up link** → **Turn on sign-up link**, then **Copy**. The link is off until turned on and does not expire.
- **What a student sees:** the course name and Andrew's name, then name, email, password (8+ characters) and the student-notice consent box. Nothing is created until they tick it. They land on the course, signed in, and show up on the roster as active.
- **Already has an account** (email has a password): they are told to sign in and open the link again; signed in, the link offers **Join this course**. The link never changes an existing password.
- **Added by email but never set a password:** the link refuses them and says to use the personal invite link the teacher sent (or ask for it to be resent). Their invite keeps working; reissue it from the roster if they lost it.
- **Turn off** stops new sign-ups; **Replace link** kills the old link and makes a new one. Accounts already made are kept either way.
- **Consent:** people who get a forwarded link will not have heard Andrew's explanation first; the student notice and the consent box are all they see. Collect the consent form response as usual (Rolling checks), or keep the link off and add people by email.
- **Test it** in a private window (signing up in a browser where Andrew is signed in signs him out there).

## If something goes wrong for a volunteer
- **Link says used or expired:** Students → reissue invite for that person (links do not expire while `INVITE_NO_EXPIRY=1`; a used link is single-use by design).
- **Sign-up link says "not active":** it was turned off or replaced. Copy the current one from the roster's **Sign-up link** section.
- **Forgot password:** reissue the invite; the reset link works without email.
- **Page frozen:** reload — drafts are saved on the device and resume.
- **Site down:** check Render logs, tell the volunteer their draft is saved locally, and resume later; async means no session is lost.
