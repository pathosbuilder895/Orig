# Alpha test kit runbook (async, open-ended — starts 2026-10-19)

**Scope:** Andrew Clark (teacher, arclark555@gmail.com), one teacher workspace named `Andrew (Alpha test)'s workspace`, and ~20 consenting adult volunteers (18+). **Timing: START TODAY, open-ended, asynchronous** — no fixed end date or single session; volunteers do their parts when they can, the workspace/course stays open, join links stay live until Andrew says the alpha is over, and staff batch-score as submissions arrive. **Design since 2026-11 (four papers):** each volunteer shares **four past papers they wrote themselves** and nothing else. Andrew approves three as that volunteer's reference writing and holds one out, writes an AI imitation of that volunteer's voice himself, then scores the held-out paper and the imitation against the three approved papers in **Writing State** (see §6). Volunteers no longer write a fourth piece, make an AI piece or sit the two-question exam (the 2026-10-30 design, kept in `prompts.md` for anything already submitted). Original scoring is OFF for students and runs only on Andrew's side. Students never see scores.

## Go / No-go
Proceed only when every GO item is true. If any NO-GO item is true, stop before inviting anyone or creating an exam.
| GO | NO-GO |
|---|---|
| Andrew has approved the prompts, targets in `scoring_plan.md`, deletion wording, and data handling in writing. | Anyone under 18, missing consent, or unsure about participation is included. |
| Every volunteer has consented (Google Form in `google_forms_spec.md`) before receiving a join link. | A volunteer's past paper was not written by them, or consent is unclear. |
| The public smoke check passes, `/health` identifies a commit and reports `backend: postgres`, `signup_open: false`. | Any smoke check fails, or the pilot is serving a different/unexpected commit. |
| Andrew has a private, staff-only `labels.csv` (+ `baselines.csv` if any split) plan and a secure place for exports/reports. | Labels or raw papers would be sent to students, committed, or stored in an unapproved location. |
| No alpha exam is needed since 2026-11. If an older alpha exam is still published in the course, it is unpublished or closed, so volunteers see nothing to sit. | A score, reading or comparison appears anywhere a volunteer can see it. |

Original's result is calibration feedback, not evidence about any person and not a validated claim. This runbook does not authorize a wider launch; Andrew makes that decision.

## 1. Confirm the public service (read-only)
```sh
python scripts/alpha/live_smoke.py --base-url https://original-pilot.onrender.com
```
Success ends with `RESULT: PASS`; `/health` must show a non-empty commit, `backend='postgres'`, and `signup_open=False`. If it fails (a transient disconnect was seen 2026-10-19), rerun; if it keeps failing, stop and check Render → `original-pilot` → **Events**/**Logs**. Do not change settings or restart the service as part of this runbook.

## 2. Create the alpha teacher workspace (browser/Render step — after PR merge)
1. **First re-confirm in the Render dashboard** (Environment for `original-pilot`) that `INVITE_NO_EXPIRY=1` is set — it is not in `render.yaml`, so the repo cannot prove it. If it is missing, set it and redeploy before creating links.
2. In Render → **original-pilot** → **Shell** → **Connect**, from the deployed project root:
   ```sh
   ALPHA_EMAIL='arclark555@gmail.com'
   python scripts/invite_professor.py "$ALPHA_EMAIL" --name "Andrew (Alpha test)" --with-original --no-expiry
   ```
   The email must not already have an account on the pilot. If the script is not found, stop and check the active deploy.
3. Success includes `Database backend: postgres`, `Products: bluebook, original`, a `t-...` workspace id, and a single-use set-password link. Send that link only to Andrew (never into chat, a ticket, a report, or a PR). Andrew sets a password, accepts terms, signs in. The tenant's exact name is the deletion safety check — keep `--name` unchanged.

## 3. Create the course and invite students (rolling)
In Collections: **Courses** → **Add course**: Name `Alpha test`, Code `ALPHA1`.
As each volunteer's consent arrives: **Students** → **Add students**, paste their email/name, turn **Send email OFF** (SendGrid is not used), **Add students**. Send each person their own invite link privately (use `invite_message.md`, with their consent-form step already done); never put links in a shared document. Links do not expire while `INVITE_NO_EXPIRY=1`; they are single-use, and removing a student voids an unused link. Keep a private roster note of who was sent which link and when.

## 4. Collect and import reference papers (rolling)
**Students can now upload their own past papers in the app** (fallback: email to arclark555@gmail.com, then import as below). On their Collections home page, **Share a past paper** takes a PDF, DOCX or TXT file or pasted text, an optional title, and an optional **This is a section of a longer paper** tick with the longer paper's title. A shared paper is stored as *pending*: it is not scored, not read for features, and not in the baseline. The student sees only "Received — your teacher will review it" and each paper's status (*waiting for review* / *accepted* / *not used*).

To review: **Original** → **Voice Baseline** (`/original/baseline.html`) → **Papers students shared** (all students on the overview; one student's on their page). Each row shows the student, title, date, word count and source (*Whole paper (independent)* or *Section of a longer paper: … (split-derived)*). **Approve** adds it to the baseline as a **student upload** (the lowest-trust provenance, never supervised); **Decline** leaves it out. Only approved papers count toward the 3-paper minimum. A paper that differs strongly from the existing baseline is *Held back* (the drift gate; approval does not override it). Check each paper is plausibly the student's own before approving. Split tags for app-shared papers flow into the batch export's `baselines.csv` automatically (`scripts/alpha/batch_score_alpha.py`); hand-tag only papers you import yourself.

Collect the four papers each volunteer wrote themselves (three approved as the baseline, 300+ words in total across those three, plus the held-out paper), in Andrew's approved private storage (formats: PDF, DOCX, TXT — if in doubt, also keep a `.txt` copy). **If a volunteer lacks 3 individual papers:** with their consent (form Q7), split **one** long paper they wrote into sections and import the sections as baseline papers. Record every such file in the staff `baselines.csv` (`student,baseline_file,baseline_source,parent_paper_id`, `baseline_source=split`) — split-derived baselines are never silently pooled with independent ones; the batch report breaks their results out (see `scoring_plan.md`). Never upload another person's writing as that volunteer's baseline.
For each student: **Original** → **Voice Baseline** (`/original/baseline.html`) → choose student → **Import papers** → select files → **Import**. Confirm the count afterwards (the import screen can hold a file that looks very different — "drift hold"). Below 3 papers: that student is recorded as insufficient-baseline / not scored; do not invent replacement writing.

## 5. The alpha exam (not used since 2026-11)
The four-paper design has no exam. Do not create one. If the two-question collection from the 2026-10-30 design (`Alpha test: your piece and an AI piece`) or the older Exams A and B are still published in `ALPHA1`, unpublish or close them so volunteers don't see an exam on their home page. Submissions already sealed stay where they are and can still be exported and labelled as described in `prompts.md` and `scoring_plan.md`.

## 6. The volunteer's steps, the held-out paper and the imitation (rolling)
**What the volunteer does:** shares four past papers they wrote themselves under **Share a past paper**, one at a time, with anything private taken out. That is all. The app's **Instructions** button shows these steps to every student in the alpha workspace, including people who arrive through a forwarded sign-up link and never heard the explanation, so it also says that the person running the test writes one extra piece in their style with an AI writing tool, that it is never shown as their work, and that they see no score. A volunteer never asks an AI tool for anything.

**What Andrew does, per volunteer, once four papers are in:**
1. **Read all four.** Open **Original → Voice Baseline** (`/original/baseline.html`), choose the student, and in **Papers students shared** use **Read this paper** on each. Reading shows the text only; it adds nothing and changes no status. Check each paper is plausibly the volunteer's own.
2. **Approve three, hold one out.** **Approve** three. Leave the fourth *Waiting for approval*: that is the held-out paper. Don't decline it (the volunteer would see *not used*). Pick the held-out paper before approving, and record which one it is in the private `labels.csv`. If the volunteer's papers are sections of one long paper, prefer holding out a paper that isn't a section of the same long paper as the three, and note it if you can't.
3. **Approved the wrong one?** Use **Undo approval** on it. It comes back out of the baseline and is *Waiting for approval* again; nothing else changes (the other papers, any exams or submissions, and other students' baselines stay as they are). Then approve the right one. Undo can be pressed twice safely.
4. **Write the imitation.** Using one or more of the approved papers as the style source, write one piece in that volunteer's voice with an AI writing tool, yourself. Never use the held-out paper as a source. Only for volunteers whose consent covers it (the current consent Q10, or Yes to Q12 on a form answered before 2026-11; see `consent_form_questions.md`). Note the tool's name and which papers you gave it.
5. **Score both in Writing State.** On the held-out paper's row, **Read this paper → Copy text**, then **Open Writing State for [student]**, paste it and run the analysis. Do the same with your imitation. Both are compared with the student's baseline, so first check the student's **Baseline samples** count reads 3 (only the three approved papers; take out anything else, such as an approved booklet from an earlier exam design). Writing State's result is calibration feedback in testing, never proof of anything, and it is only ever seen by Andrew.
6. **Record the results** privately: a row each for the held-out paper (`natural`) and the imitation (`shadow`, `shadow_kind=ai_staff`, `writer_true` = Andrew, `generator_tool` = the tool) in `labels.csv` (see `scoring_plan.md`), with Writing State's outcome for each.

Labels live outside the scored text and are never shown to students or fed to the engine. If any student sees a score, or a student-token score call succeeds, stop and report to Andrew (status code + route only, never token or writing).

## 7. Record and summarise as volunteers finish
For the four-paper design, results come from Writing State (§6, step 5), recorded by hand in Andrew's private storage with `labels.csv` (header in `scoring_plan.md`) and `baselines.csv` if any baseline is split-derived. The batch scorer (`scripts/alpha/batch_score_alpha.py`, see `scoring_plan.md` §Running it) is still how any submission sealed under the earlier exam designs is exported (each two-question exam as `<submission_id>-q1` and `-q2`; the **Submissions** screen's CSV has the same pieces in `answer_1` and `answer_2`). Reports go only to Andrew.

## 8. Close-out and deletion
When Andrew says the alpha (or a person's participation) is over: handle withdrawals first, save the aggregate staff report privately, then follow `deletion_plan.md` (per-person, within 14 days of their participation ending). After the whole alpha closes, remove `INVITE_NO_EXPIRY` from the Render dashboard so later links expire normally again.

## Capacity notes (unchanged from previous runbook)
Pilot is one Uvicorn worker on Render Starter (0.5 CPU / 512 MB at last check); the batch scorer runs one student at a time in throwaway SQLite subprocesses with `--throttle-seconds 2` (5 if the service is busy, never parallel batches). Recheck Render plan/limits before any later, larger test.

## Local rehearsal and tool help
```sh
.venv/bin/python -m pytest tests/alpha/test_alpha_scripts.py -q
.venv/bin/python scripts/alpha/verify_join_flow_local.py --help
.venv/bin/python scripts/alpha/batch_score_alpha.py --help
.venv/bin/python scripts/alpha/delete_alpha_tenant.py --help
```
