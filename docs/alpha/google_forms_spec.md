# Google Forms spec — build-ready (browser step, after this PR merges)

Contact on both forms: **Andrew Clark, arclark555@gmail.com**. Responses: collect email addresses ON; limit to the invited volunteers as far as Google allows; response sheet visible only to Andrew; delete response sheets per `deletion_plan.md`. This alpha is asynchronous and open-ended (starts 2026-10-19, no fixed end date): send each form when that volunteer reaches that step, not on one test day.

## Form 1 — "Original alpha test: participation and consent"
**Description (paste verbatim):** the full text of `consent_notice.md`.
**Confirmation message:** "Thank you. Andrew will check this and send your personal join link privately. Questions: arclark555@gmail.com"

| # | Question (exact) | Type | Required | Notes / validation |
|---|---|---|---|---|
| 1 | Full name | Short answer | Yes | — |
| 2 | Email you'll use for the test | Short answer | Yes | Response validation: text contains @ |
| 3 | I am 18 years of age or older. | Checkbox (single option "Yes, I am 18 or older") | Yes | Anyone who cannot tick this does not take part |
| 4 | I have read the participation notice. | Checkbox | Yes | — |
| 5 | I understand that taking part is voluntary, I can stop at any time, and I can ask for early deletion. | Checkbox | Yes | — |
| 6 | I'll share four past papers that I wrote myself (in the app, or by email to Andrew as a fallback), and I agree that they can be analyzed by a writing-consistency feature that is still in testing. | Checkbox | Yes | Four-paper design, 2026-11 |
| 7 | If I don't have four separate past papers, I agree that one long paper I wrote may be split into sections (by me when uploading in the app, or by Andrew) and those sections used as my reference writing, labelled as split-derived in the test data. | Multiple choice: Yes / No | Yes | "No" + fewer than 3 papers = not scored (not enough reference writing) |
| 8 | I understand this is not graded, I won't see any scores, and no conclusions will be drawn about me or anyone else. | Checkbox | Yes | — |
| 9 | I understand that what I write, session events, and request logs (IP address and browser type) are collected, and that my data will be deleted within 14 days after I withdraw or Andrew closes my participation, whichever comes first (encrypted backups age out within about 30 days after that deletion). | Checkbox | Yes | Exact deletion wording — do not shorten |
| 10 | I understand that Andrew will keep three of my papers as reference writing and set one aside, and that, to check the software, he will use an AI writing tool to write one piece imitating my style from my reference papers. It is labelled as his in the test data, never presented as my work, and not shown to other participants. I won't be asked to use an AI tool myself. | Checkbox | Yes | Four-paper design, 2026-11. Replaces the exam question of 2026-10-30. **Needs Andrew's approval** |
| 11 | I agree that one of my papers may be used as a shadow test sample attributed to another participant, so the software can be checked. | Multiple choice: Yes / No | Yes | Optional to agree; use only from Yes |
| 12 | *(Retired 2026-11: folded into question 10.)* On forms answered before then, Yes here is what allows Andrew's imitation for that volunteer. | — | — | Someone who answered No before 2026-11 needs to agree to the new question 10 before an imitation is made |
| 13 | I agree to take part in the alpha test. | Checkbox | Yes | — |
| 14 | Accessibility needs or anything else we should know | Paragraph | No | — |

## Form 2 — "Original alpha test: feedback"
**Description (paste verbatim):** "Thank you for testing Original. This checks the software, not you. There are no grades and no scores to see. Questions: Andrew Clark, arclark555@gmail.com"
Send the link when that volunteer has shared their four papers. (Before 2026-11 question 10 asked which AI tool wrote the volunteer's question 2 piece; volunteers no longer make one, so it is removed.)

| # | Question (exact) | Type | Required |
|---|---|---|---|
| 1 | How easy was it to sign in with your link and set a password? | Linear scale 1–5 (1 = very hard, 5 = very easy) | Yes |
| 2 | While you were uploading, did the page ever feel slow, freeze, or lose anything? | Multiple choice: No / Once / Several times | Yes |
| 3 | If it did, what happened? | Short answer | No |
| 4 | Were the steps clear? | Linear scale 1–5 | Yes |
| 5 | Did sharing your four papers work? | Multiple choice: Yes, first time / After some trouble / No | Yes |
| 6 | What device and browser did you use? | Multiple choice: Laptop–Chrome / Laptop–Safari / Laptop–Firefox / Laptop–Edge / Tablet / Phone / Other | Yes |
| 7 | What was the most confusing or frustrating moment? | Paragraph | Yes |
| 8 | Anything you'd change before this is used with a real class? | Paragraph | No |
| 9 | Anything about providing your past papers (including, if it applied, splitting one long paper) that was unclear or uncomfortable? | Paragraph | No |
