# Launch-day smoke test and rolling checks (async alpha — replaces the single test-day plan)

The alpha is open-ended and asynchronous (starts 2026-10-19, no fixed end date). There is no single test day or dry-run day. Instead: a **launch-day smoke test** before the first real invite goes out, then **rolling checks** as volunteers arrive.

## Launch-day smoke test (about 1 hour, before first invite)
- [ ] Pilot on the expected commit: `live_smoke.py` PASS; `/health` shows `backend: postgres`, `signup_open: false`. (A transient disconnect was seen 2026-10-19 — rerun until a clean PASS; do not claim PASS from a partial run.)
- [ ] `INVITE_NO_EXPIRY=1` re-confirmed in the Render dashboard (it is not in `render.yaml`), and alpha teacher workspace created with `--no-expiry` (see `setup_runbook.md` §2).
- [ ] Consent + feedback Google Forms built from `google_forms_spec.md`, contact arclark555@gmail.com, tested with a dummy response that is then deleted.
- [ ] 2–3 test accounts on Andrew's own emails: run every step in `join_link_check.md` on Chrome and Safari, plus one phone; import 3 test papers; write both timed writings; batch-score them; confirm no score is visible to the student account.
- [ ] One split-derived test baseline: split a long test paper, tag it in `baselines.csv`, confirm the report's baseline-source breakout shows it separately.
- [ ] Delete the test accounts (or keep clearly-named spares), then generate the first real invite links.

## Rolling checks (each time a volunteer finishes, and a weekly sweep)
- [ ] Consent response received **before** that person's join link is sent; partners only among Q11=Yes; shadow use only per Q12/Q13.
- [ ] Baseline count after import: 3+ papers (drift hold can hold one back — confirm the count the screen reports). Record independent vs split-derived in `baselines.csv`.
- [ ] Both writings sealed, no score visible to the student; staff batch-score as submissions arrive (see `scoring_plan.md`).
- [ ] Feedback form sent to that volunteer; note any slowness/errors with date/time (ET).
- [ ] Withdrawals: delete that person's data within 14 days of withdrawal (see `deletion_plan.md`); Andrew closes a participation the same way.

## If something goes wrong for a volunteer
- **Link says used or expired:** Students → reissue invite for that person (links do not expire while `INVITE_NO_EXPIRY=1`; a used link is single-use by design).
- **Forgot password:** reissue the invite; the reset link works without email.
- **Page frozen:** reload — drafts are saved on the device and resume.
- **Site down:** check Render logs, tell the volunteer their draft is saved locally, and resume later; async means no session is lost.
