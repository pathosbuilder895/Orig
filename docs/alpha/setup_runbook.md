# Alpha test kit runbook (async, open-ended — starts 2026-10-19)

**Scope:** Andrew Clark (teacher, arclark555@gmail.com), one teacher workspace named `Andrew (Alpha test)'s workspace`, and ~20 consenting adult volunteers (18+). **Timing: START TODAY, open-ended, asynchronous** — no fixed end date or single session; volunteers do their parts when they can, the workspace/course stays open, join links stay live until Andrew says the alpha is over, and staff batch-score as submissions arrive. Each volunteer supplies 3+ past papers totalling 300+ words (or, with permission, one long paper split into tagged sections — see §4), then seals one alpha exam with two pasted pieces: their own writing in question 1 and an AI piece on the same topic in question 2 (design since 2026-10-30; see `prompts.md`). Original scoring is OFF in the exam and runs afterwards, offline. Students never see scores.

## Go / No-go
Proceed only when every GO item is true. If any NO-GO item is true, stop before inviting anyone or creating an exam.
| GO | NO-GO |
|---|---|
| Andrew has approved the prompts, targets in `scoring_plan.md`, deletion wording, and data handling in writing. | Anyone under 18, missing consent, or unsure about participation is included. |
| Every volunteer has consented (Google Form in `google_forms_spec.md`) before receiving a join link. | A volunteer's past paper was not written by them, or consent is unclear. |
| The public smoke check passes, `/health` identifies a commit and reports `backend: postgres`, `signup_open: false`. | Any smoke check fails, or the pilot is serving a different/unexpected commit. |
| Andrew has a private, staff-only `labels.csv` (+ `baselines.csv` if any split) plan and a secure place for exports/reports. | Labels or raw papers would be sent to students, committed, or stored in an unapproved location. |
| The alpha exam can be created with **two questions**, **Block copy & paste OFF**, **No AI assistants OFF**, and **Writing consistency OFF**. | Writing consistency is on, the exam settings cannot be verified, or a score appears in a student response. |

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

Collect 3+ papers each volunteer wrote themselves, 300+ words total, in Andrew's approved private storage (formats: PDF, DOCX, TXT — if in doubt, also keep a `.txt` copy). **If a volunteer lacks 3 individual papers:** with their consent (form Q7), split **one** long paper they wrote into sections and import the sections as baseline papers. Record every such file in the staff `baselines.csv` (`student,baseline_file,baseline_source,parent_paper_id`, `baseline_source=split`) — split-derived baselines are never silently pooled with independent ones; the batch report breaks their results out (see `scoring_plan.md`). Never upload another person's writing as that volunteer's baseline.
For each student: **Original** → **Voice Baseline** (`/original/baseline.html`) → choose student → **Import papers** → select files → **Import**. Confirm the count afterwards (the import screen can hold a file that looks very different — "drift hold"). Below 3 papers: that student is recorded as insufficient-baseline / not scored; do not invent replacement writing.

## 5. Create and verify the alpha exam
**Collections** → **+ New collection**, one collection, one submission per student. Setting and the three switches are under **More options**:
| Field | Alpha exam |
|---|---|
| Title | `Alpha test: your piece and an AI piece` |
| Course | `ALPHA1` |
| Questions | Question 1 and Question 2, exact text from `prompts.md` |
| Setting | Take-home (untimed, not full screen: volunteers paste from other windows) |
| Block copy & paste | **Off** (on by default for every new collection; with it on, pasting is refused) |
| No AI assistants | **Off** (on by default; with it on, the briefing tells volunteers not to use AI, which contradicts question 2) |
| Writing consistency (in testing) | Off |
Verify on the saved collection's summary that both questions are there and `conditions` shows `blockCopy: false`, `blockAI: false` and `aiDetect: false` before publishing. Publish and leave it open for the async alpha. If a condition cannot be confirmed, do not publish. Exams A and B from the earlier design are not created any more.

## 6. The volunteer's steps, shadow collection, and privacy (rolling)
Volunteers share their past papers, then open **Examinations** → the alpha exam → **Begin Examination**, paste their own piece into question 1 (Q1) and the AI piece into question 2 (Q2), and **Seal & Submit**. The app's **Instructions** button shows these steps to every student in the alpha workspace. The feedback form asks which AI tool wrote the question 2 piece; that answer is the only record of `generator_tool`. **Shadow papers:** the question 2 piece is the main shadow (`shadow_kind=ai_own`); optional staff-created shadows follow the staff instruction in `prompts.md` (staff/Andrew only, consent Q12=Yes only, never generated by the target student). Label every piece in `labels.csv` (see `scoring_plan.md`). Labels live outside the scored text and are never shown to students or fed to the engine.
A seal shows only a submission confirmation. If any student sees a score or a student-token score call succeeds while consistency is off, stop and report to Andrew (status code + route only, never token or writing).

## 7. Export, label, and batch-score as submissions arrive
Export the alpha exam with the batch scorer (`--exam`, see `scoring_plan.md`), which writes each sealed exam as two files, `<submission_id>-q1` and `<submission_id>-q2`; keep exports in Andrew's private storage. (The **Submissions** screen's CSV has the same pieces in its `answer_1` and `answer_2` columns.) Build `labels.csv` (canonical v2 header in `scoring_plan.md`) from those file names, plus `baselines.csv` if any baseline is split-derived. Run the batch scorer per `scoring_plan.md` §Running it, as submissions arrive (not one final session). Reports go only to Andrew.

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
