# Dry run (day before) and day-of plan

## Dry run, about 1 hour, day before
- [x] Pilot redeployed to current main with #287; `/health` shows commit `59173fd` (identical to `main` tip as of 2026-10-15 ~11:50 ET). #286 (consent MVP) is still open and is not required for the independent-teacher alpha path.
- [ ] Alpha workspace exists, products = bluebook + original.
- [ ] Every volunteer has 3+ reference papers (300+ words) uploaded; partners assigned only among people who said Yes to partner sharing; excerpts sent.
- [ ] `labels.csv` template ready; pass criteria written down (scoring_plan.md).
- [ ] Dry-run batch scoring on the 2–3 test accounts (`batch_score_alpha.py`), then delete them.
- [ ] Exam A (natural) and Exam B (partner's style) published: 25 min, paste blocked, writing consistency OFF.
- [ ] 2–3 test accounts on Andrew's own emails: run every step in `join_link_check.md`, on Chrome and Safari, plus one phone.
- [ ] Delete the test accounts, or keep them as spares.
- [ ] Consent form live; all 20 volunteers have submitted it before they get their links.
- [ ] 20 invite links generated and sent privately (they expire after 14 days, so send at most a few days ahead).
- [ ] Feedback form link ready to paste.

## Day of
- **T-30 min:** open Render dashboard (metrics + logs), the teacher dashboard, and a spreadsheet to track who's joined. Wake the service with `/health`.
- **T-10:** post the start message: "Open your link or sign in, open Practice prompt 1, start when told."
- **T0:** everyone starts Exam A together (load test #1). **T+35:** 10-min break, then Exam B together (load test #2). Watch the live view for who's writing.
- **During:** Andrew answers questions in a group chat/DM. Note the time of any slowness or error.
- **Common fixes:**
  - **Link says used or expired:** Students → reissue invite for that person.
  - **Forgot password:** reissue the invite. The reset link works without email.
  - **Page frozen:** reload. Drafts are saved on the device and resume.
  - **Site down:** check Render logs; pause and tell everyone their drafts are saved locally.
- **T+30:** confirm all submissions are in, send the feedback form, thank everyone.
- **Same day:** note peak response times and errors from Render metrics, and any student issues.
- **Within ~3 days:** export, label, run `batch_score_alpha.py`, share the report with Andrew only.
- **Within 14 days:** run `deletion_plan.md`.
