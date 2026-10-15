# Alpha test (Collections + Original): setup runbook (DRAFT, nothing run against the pilot)

**Scope:** 20 adult volunteers recruited by Andrew, with Andrew as the teacher. Each volunteer provides 3 or more of their own past papers (300+ words in total) as reference writing. They then write a **natural** paper and a **not-own** paper in Collections. Original scores everything **after** the session, in a batch run (`scoring_plan.md`). Students never see scores. All data is deleted within 14 days.

## What the code actually provides (checked on live pilot = main @59173fd / #287; #286 still open, university-only)
- **Workspace:** `scripts/invite_professor.py <email> --name ... --with-original` creates a private workspace with products `bluebook, original`, a teacher login and a 14-day set-password link. There's no admin UI for this; run it from Render → original-pilot → Shell. Use an email with no account on the pilot yet (e.g. `andrew+alpha@…`).
- **Uploading reference papers (teacher):** the Original reference page `/original/baseline.html` ("Import papers") posts to `POST /students/{id}/baseline/upload-batch` (PDF/DOCX/TXT). There's also a paste-text path, `POST /students/{id}/baseline`. Both run as staff, with provenance `verified`. **Use these:** students email or share their papers with Andrew, and he uploads them for each student.
- **Uploading reference papers (student):** **Collections has no upload screen.** The API does accept a student's own `POST /students/{own id}/baseline` (stored as `unverified`, weight 0.5). That came up in local testing, but nothing in the UI uses it, so don't rely on it.
- **Is there server-side scoring on seal (main)?** No. `POST /bluebook/submissions` only records the seal. On main, the **student's browser** calls `POST /students/{id}/score` while sealing, and that's the request that runs the math. On current main/#287 it only happens when the exam has writing consistency on (older builds scored whenever the workspace had Original). That call writes a stored score row, and the browser forwards an `ai_score` with the seal.
  - **Student visibility:** students' own screens (`/bluebook/me/submissions`) show no score fields. That was checked locally. **But the score JSON is in the student's own browser network response, and a student token can call `/score` directly** (checked locally: 200 with authorship numbers). For the alpha, set the exam's writing consistency **off** (now live on the pilot via #287) and rely on the batch run alone. **Recommended: consistency OFF on the exams + batch scoring.** It's cleaner, and nobody can see a score.
- The roster cap of 200 and the #286 pilot-agreement gate (university workspaces only) don't apply here.

## Steps (Andrew approves first; the operator runs them in the Render shell)
1. `python scripts/invite_professor.py andrew+alpha@<domain> --name "Andrew (Alpha test)" --with-original`. Check that the output says `Database backend: postgres` and `Products: bluebook, original`, and note the `t-…` id. Send the link to Andrew only.
2. Andrew sets a password and accepts the terms. **Course:** `Alpha test` / `ALPHA1`.
3. **Students:** Students → Add students → paste the 20 emails, with email sending off → send each person their own invite link privately.
4. **Reference papers:** collect at least 3 past papers from each person, 300+ words in total, written by them alone. Upload them in `/original/baseline.html` → pick the student → Import papers, or `POST /students/{id}/baseline/upload-batch`. Check that each student shows 3+ samples. The batch report marks anyone below the minimum as INCONCLUSIVE.
5. **Exams.** There are two, because a student can submit only once per exam:
   - **Exam A, "Practice prompt 1":** the natural paper.
   - **Exam B, "Practice prompt 2 (other-style)":** the not-own paper. Each volunteer writes in the style of their assigned partner, who has agreed to it (`prompts.md`).
   - Both: 25 min, Block copy & paste ON, writing consistency OFF (see above; turn it ON only if Andrew accepts the visibility note).
6. **Labels (staff only):** after the session, export both exams and fill in `labels.csv` (`submission_id,label,true_author`), with label `natural` for A and `not_own` for B. Optionally add **injected** known-other-author texts. These are another consenting participant's paper or public-domain prose, dropped into the export folder for a target student with their own row in `labels.csv`. Keep the CSV in Andrew's drive only, and delete it with the data.
7. Run `batch_score_alpha.py` (`scoring_plan.md`).
