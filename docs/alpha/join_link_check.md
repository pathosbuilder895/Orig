# Join-flow check

## On the pilot (dry run, using 2–3 of Andrew's own test emails)
1. Teacher set-password link opens the set-password screen → set password + accept terms → lands on the dashboard. The Products list shows no Original.
2. Add 2 test emails → an invite link appears for each, and "emailed" stays false while SendGrid is down.
3. In a private window, open link 1 → set a password → the student sees the `Alpha test` course exam.
4. Open the same link again → it must be refused ("invalid, expired, or already used").
5. Sign out → sign back in with email + password → the exam is still listed.
6. Start the exam → paste is blocked → timer shows 25 min → write → submit → you see the submitted confirmation.
7. Teacher → exam → the submission appears with **no score or consistency status**.
8. Delete the test students afterwards (`delete_alpha_tenant.py` dry run first, or remove them from the roster).

## Local verification (done 2026-10-15, ~9:20 AM ET)
Local server on the box (`run.py --demo`, `ORIGINAL_ENV=pilot`, SQLite, consent-mvp branch merged with main @271e044), so nothing touched the pilot. The script is `verify_join_flow_local.py` and the full output is in `join_flow_local_result.txt`.

| Step | Result |
|---|---|
| `invite_professor.py` → workspace with `Products: bluebook` | PASS |
| Invite page `/bluebook/?invite=…` serves the app | PASS |
| Teacher redeem without accepting terms is refused (422); with terms it signs in | PASS |
| Course + 25-min exam with paste blocked, consistency off | PASS |
| Add 20 students without email → 20 invite links, 0 emailed | PASS |
| 3 students: redeem, reused link refused (400), log in, see exam, start, submit | PASS ×3 |
| Teacher sees the 3 submissions, no scores | PASS |

Not covered locally: the browser UI clicks (covered by CI `bundle-e2e`), Postgres, and the live pilot build. The pilot runs older code until it's redeployed.
