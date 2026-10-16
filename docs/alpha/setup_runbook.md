# Alpha test kit runbook

**Scope:** Andrew, one teacher workspace named `Andrew (Alpha test)'s workspace`, and 20 consenting adult volunteers. Each volunteer supplies at least 3 past papers totaling 300+ words, then seals one natural paper and one not-own paper in Collections. Original scoring runs after the exams. Students never see scores. Delete alpha data within 14 days.

## Go / No-go

Proceed only when every GO item is true. If any NO-GO item is true, stop before inviting anyone or creating an exam.

| GO | NO-GO |
|---|---|
| Andrew has approved the session date, prompts, deletion date, and data handling. | Anyone under 18, missing consent, or unsure about participation is included. |
| Every volunteer has consented to the use of their own prior writing and the testing-phase comparison. | A volunteer's past paper was not written by them, or consent is unclear. |
| The public smoke check passes, `/health` identifies a commit and reports `backend: postgres`, `signup_open: false`. | Any smoke check fails, or the pilot is serving a different/unexpected commit. |
| Andrew has a private, staff-only `labels.csv` plan and a secure place for exports/reports. | Labels or raw papers would be sent to students, committed, or stored in an unapproved location. |
| Both exams can be created with **25 minutes**, **Block copy & paste ON**, and **Writing consistency OFF**. | Writing consistency is on, the exam settings cannot be verified, or a score appears in a student response. |
| No pilot exam is currently in progress and the service has enough headroom for the 20-person session. | A live class/exam is running, `/health` is unhealthy, or Render metrics show sustained CPU/memory pressure. |

Original's result is research feedback, not evidence of misconduct or a validated accuracy claim. Small samples may be inconclusive. This runbook does not authorize a pilot launch; Andrew makes that decision.

## 1. Confirm the public service (read-only)

From a local checkout, run:

```sh
python scripts/alpha/live_smoke.py --base-url https://original-pilot.onrender.com
```

Success ends with `RESULT: PASS`; `/health` must show a non-empty commit, `backend='postgres'`, and `signup_open=False`. If it fails, stop. Check the service's public status page and Render → `original-pilot` → **Events** and **Logs**. Do not change settings or restart the service as part of this runbook. Ask Andrew to resolve the failure before proceeding.

## 2. Create the alpha teacher workspace

1. In the Render Dashboard, open **original-pilot** from the Services list.
2. Click **Shell** in the service navigation, then **Connect** to open the running instance's shell. Shell access is available for paid web services; this step writes the invitation to the pilot database.
3. At the shell prompt, paste the following two lines, replacing the email with Andrew's real address. The email must not already have an account on the pilot:

   ```sh
   ALPHA_EMAIL='andrew+alpha@your-real-domain.example'
   python scripts/invite_professor.py "$ALPHA_EMAIL" --name "Andrew (Alpha test)" --with-original
   ```

   The shell runs from the deployed project root; if `scripts/invite_professor.py` is not found, stop and check the active deploy rather than changing directories to an unknown checkout.
4. Success output includes `Database backend: postgres`, `Products: bluebook, original`, a `t-...` workspace id, and a single-use set-password link. Do not paste the link into chat, a ticket, a report, or a PR. Send it only to Andrew.
5. Andrew opens the link, chooses a unique password, accepts the terms, and signs in. Confirm the Collections teacher home loads. If the products line is wrong or the link fails, stop and contact Andrew; do not reissue an invitation to a different account.

The tenant's exact name is the deletion safety check. Keep that `--name` value unchanged.

## 3. Create the course and invite students

In Collections, open **Courses** → **Add course**. Use:

- Name: `Alpha test`
- Code: `ALPHA1`

Open **Students** → **Add students**. Paste the 20 consenting adult volunteers' email addresses and names. Turn **Send email** off, then click **Add students**. Confirm the roster contains exactly 20 rows and each has its own invite link. Send each invite link privately to its matching volunteer; never place the links in a shared document.

Each volunteer opens their one-time link, chooses a password, accepts the terms, and signs in at `/bluebook/`. The teacher checks that the row changes from invited to active. If an invite was sent to the wrong address, stop and reissue only to the intended volunteer from that row.

## 4. Collect and import reference papers

Collect three or more papers that each volunteer wrote themselves, with at least 300 words total per volunteer. Save the consent record and papers in Andrew's approved private storage. Do not upload another person's writing as that volunteer's baseline.

For each student, in the teacher workspace open **Original** → **Voice Baseline** (`/original/baseline.html`), choose that student, click **Import papers**, select the files, and click **Import**. Acceptable file formats are PDF, DOCX, or TXT. The student's baseline must show at least 3 samples before the exams. If a file fails, use a text-only `.txt` copy through the same import screen; if the count or word total remains short, record that student as INCONCLUSIVE and do not invent replacement writing.

## 5. Create and verify both exams

Open **Examinations** → **New examination**. Create these separately so each student can seal once per exam:

| Field | Exam A | Exam B |
|---|---|---|
| Title | `Practice prompt 1` | `Practice prompt 2 (other-style)` |
| Course | `ALPHA1` | `ALPHA1` |
| Duration | `25` minutes | `25` minutes |
| Question | Use the approved natural-writing prompt from `prompts.md` | Use the approved partner-style prompt from `prompts.md` |
| Block copy & paste | On | On |
| Writing consistency (in testing) | Off | Off |

Leave **Writing consistency (in testing)** off. In API records this is `conditions.aiDetect: false`. That setting prevents seal-time scoring; staff batch scoring happens later. Verify the duration and all three conditions on the saved exam summaries before opening either exam. If a condition cannot be confirmed, do not publish the exam.

Open Exam A, confirm the prompt and click **Publish examination**. Repeat for Exam B. Start the session only when all volunteers are ready. Each exam is 25 minutes; do not extend or change the duration after it opens.

## 6. Seal both submissions and confirm student privacy

Students open **Examinations**, start Exam A, write naturally, and click **Seal & submit**. They then start Exam B and write the agreed partner-style piece. A seal should show a submission confirmation; no score, action, probability, or deviation appears in the student's submission list or detail.

If a student sees any score or a score-related API request succeeds with their student token while consistency is off, stop the session and do not continue to batch scoring. Save only the status code and route (never the token or student writing) for Andrew.

## 7. Export and label (staff only)

After all submissions are sealed, open **Submissions** and export Exam A and Exam B separately. Keep the exports in Andrew's approved private storage. Use the exported `submission_id` values to create a UTF-8 CSV named `labels.csv` with this exact header and one row per submission:

```csv
submission_id,label,true_author
<exam-A-submission-id>,natural,<student-id>
<exam-B-submission-id>,not_own,<partner-student-id>
```

Replace all angle-bracket examples with real ids and repeat the two rows for every student. Labels describe the planned task assignment, not a conclusion about a person's conduct. Do not share labels or scores with students. If a participant withdraws, remove their row and paper according to the consent plan before scoring.

## 8. Batch-score from the Render shell

This command reads the selected exam exports and baseline texts through staff-authenticated GET requests, then scores offline in temporary SQLite databases. It does not write scores to the pilot. The scoring work is serial; `--throttle-seconds 2` pauses between every scoring subprocess (including reruns and first-three-baseline checks) to leave CPU time for the web service. Do not run two batches at once.

1. In the Render Dashboard open **original-pilot** → **Shell** → **Connect**.
2. At the shell prompt, set the two exam ids from the teacher's exam pages and the path to the private labels CSV. Then enter the teacher's bearer token without echoing it or saving it in shell history:

   ```sh
   EXAM_A_ID='paste-exam-A-id-here'
   EXAM_B_ID='paste-exam-B-id-here'
   LABELS='/tmp/alpha-labels.csv'
   read -s -p 'Teacher bearer token: ' ALPHA_TOKEN; printf '\n'; export ALPHA_TOKEN
   python scripts/alpha/batch_score_alpha.py \
     --base-url https://original-pilot.onrender.com \
     --exam "$EXAM_A_ID" --exam "$EXAM_B_ID" \
     --labels "$LABELS" --out /tmp/alpha-score-report \
     --throttle-seconds 2
   unset ALPHA_TOKEN
   ```

   Before running, place the prepared `labels.csv` at the `LABELS` path in the shell using the approved secure transfer method. Never type the bearer token directly into a command line. Do not use a student token.
3. Success writes `/tmp/alpha-score-report/report.md` and `per_submission.csv` and prints the report. `0` means the configured point-estimate criteria passed (or no label criteria were requested); `1` means the report was produced but its criteria failed; `2` means invalid input, non-finite scores, or nondeterministic reruns. Any missing labels, unknown ids, NaN/Infinity, or rerun mismatch is a stop-and-review result, not a student-facing conclusion.
4. If the GET export fails, check that the exam ids belong to this workspace and that the token is a teacher token. If a baseline is unavailable, stop and repair the staff-only export rather than making a new API write. If Render metrics show sustained CPU or memory pressure, interrupt the batch, wait for the service to recover, and rerun later with `--throttle-seconds 5`; never increase parallelism.
   If Andrew has not approved a secure way to place `labels.csv` in the Render shell, do not paste labels there. Run the same API export and offline scoring from his private local checkout instead, replacing the exam ids and private label-file path:

   ```sh
   EXAM_A_ID='paste-exam-A-id-here'
   EXAM_B_ID='paste-exam-B-id-here'
   LABELS='/path/to/private/alpha-labels.csv'
   read -s -p 'Teacher bearer token: ' ALPHA_TOKEN; printf '\n'; export ALPHA_TOKEN
   python scripts/alpha/batch_score_alpha.py \
     --base-url https://original-pilot.onrender.com \
     --exam "$EXAM_A_ID" --exam "$EXAM_B_ID" \
     --labels "$LABELS" --repo "$PWD" --out /tmp/alpha-score-report \
     --throttle-seconds 2
   unset ALPHA_TOKEN
   ```

   This fallback still makes only staff-authenticated GETs to export the selected exams and baselines; scoring and report creation stay local. Keep the checkout, export, labels, and report private.
5. Copy the report and CSV to Andrew's approved private storage, then remove the temporary files after confirming the copy:

   ```sh
   python -c 'from pathlib import Path; p=Path("/tmp/alpha-score-report"); print("report:", (p/"report.md").exists(), "csv:", (p/"per_submission.csv").exists())'
   ```

   Delete temporary files only after verifying the private copy. The scores and label CSV never go into a PR.

## 9. Delete alpha data (within 14 days)

After Andrew confirms that the private report is saved and any withdrawal requests are handled, open **original-pilot** → **Shell** → **Connect**. First list tenant ids from Andrew's saved invitation output and run the default dry-run command with the exact id:

```sh
python scripts/alpha/delete_alpha_tenant.py t-REPLACE_WITH_ALPHA_ID
```

Success identifies the exact `Andrew (Alpha test)'s workspace` and prints student, exam, and course counts with `DRY RUN — nothing deleted.` If the name differs, stop; the script will refuse it. Confirm the counts with Andrew, then execute:

```sh
python scripts/alpha/delete_alpha_tenant.py t-REPLACE_WITH_ALPHA_ID \
  --execute --confirm-name "Andrew (Alpha test)'s workspace"
```

Success prints zero remaining students, exams, and courses. The teacher login and named workspace record remain for operator review; deletion removes students, baselines, scores, submissions, sessions, invites, enrollments, exams, and courses. If deletion returns non-zero or any remainder is non-zero, stop and ask Andrew to review; do not retry against a different tenant id.

## Capacity and request limits checked for this runbook

- `render.yaml` selects the legacy **Starter** web plan for `original-pilot`; Render's current mapping is 0.5 CPU and 512 MB RAM per instance. The blueprint does not set multiple instances. `run.py` starts Uvicorn without a worker override, so it runs one worker. Keep it that way for this rehearsal; in-process score throttles assume one worker.
- `original/db/postgres_session.py` defaults to a SQLAlchemy pool of 10 connections plus at most 20 overflow connections, 2-second PostgreSQL connection timeout, and 3600-second recycle. SQLAlchemy's pool checkout timeout remains its 30-second default. The managed `basic-256mb` Postgres plan allows up to 100 connections; one web process has a ceiling of 30.
- No app-wide HTTP request deadline is configured in this repo. Render documents web responses up to 100 minutes; this is an upper platform ceiling, not a target. The health database probe uses a 1.5-second statement timeout, while the alpha export client uses a 60-second per-request timeout. There is no separate Gunicorn timeout because the service starts Uvicorn directly.
- The batch scorer runs one student at a time in short-lived child processes with isolated temporary SQLite databases. The default `--throttle-seconds 1` pauses between each subprocess; use `2` in this runbook, and `5` if CPU is busy. It never uses the web request path for scoring after export, and `--throttle-seconds 0` is for local tests only.
- Render Starter's compute mapping and request limit can change. Check [Render compute plans](https://render.com/docs/compute-plans) and [Render's web service request limits](https://render.com/docs/render-vs-vercel-comparison) before a later session; this runbook makes no Render setting changes.

## Local rehearsal and tool help

From the repository root, the end-to-end rehearsal is:

```sh
.venv/bin/python -m pytest tests/alpha/test_alpha_scripts.py -q
```

The local join-flow helper is restricted to localhost and accepts `--help`; it never targets the pilot by default:

```sh
.venv/bin/python scripts/alpha/verify_join_flow_local.py --help
.venv/bin/python scripts/alpha/batch_score_alpha.py --help
.venv/bin/python scripts/alpha/delete_alpha_tenant.py --help
```

## Alpha-ready settings (alpha-ready-prep)

**Invite links that don't expire.** By default a set-password invite link works once and expires after 14 days (`original/invites.py::INVITE_TTL`). For the alpha:

1. In Render → original-pilot → Environment, set `INVITE_NO_EXPIRY=1` and redeploy. Student links the teacher creates from the roster then stay valid until they are used or revoked. The teacher roster shows "Works once, until you replace it".
2. Create the teacher workspace with `python scripts/invite_professor.py <email> --with-original --no-expiry`.
3. **Revoking a link:** issue a new link for that student ("New invite link" on the roster, which voids the old one), remove the student from the course (this now voids their unused link too), or delete the whole alpha tenant with `scripts/alpha/delete_alpha_tenant.py`. When the alpha ends, remove `INVITE_NO_EXPIRY` so later links expire after 14 days again.
4. `scripts/roster_links.py --no-expiry` makes signed launch links last 100 years. You can't revoke those one at a time (only by rotating `SECRET_KEY` or deleting the tenant), so prefer roster invites for the alpha.

**Three-paper minimum.** Original won't score a student who has fewer than 3 approved baseline papers (`MIN_BASELINE_SAMPLES`, default 3). The score API returns 422 with `detail.code = "insufficient_baseline"`, and readiness reports "Needs more". `batch_score_alpha.py` skips those students and lists them on an "insufficient baseline" line in the report. Check each volunteer has at least 3 papers on `/original/baseline.html` before exam day. The import screen can hold a file that looks very different from the others ("drift hold"), so confirm the count it reports afterwards.

**Seven comparison features stay neutral (on purpose, for now).** The 2 `COMPARISON_CODES` and 5 `MUSICAL_COMPARISON_CODES` compare a text against the student's baseline. They're only computed by `compute_full_features`, which the live scoring path doesn't call. So they're 0.5 for every baseline and submission, and the active-feature mask drops them, which means they have no effect on scores. To turn them on, each baseline paper would need a leave-one-out comparison value. With 3 to 5 papers that estimate is noisy and would change every student's z-scores, so it should wait for calibration on alpha data instead of going in a week before the test.
