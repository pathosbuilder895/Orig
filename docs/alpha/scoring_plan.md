# Scoring plan: post-session batch scoring with labeled ground truth

**Goal (Andrew):** check that the math works in both directions on real writing. Original must **not** flag a person's own work, and it **must** flag work that isn't theirs.

## Why batch scoring
On main, `POST /bluebook/submissions` doesn't score. The only scoring is the **student browser's** call to `/students/{id}/score` during sealing, and #274 (server-side scoring on seal, with labels) isn't merged. So the exams run with writing consistency OFF, and everything is scored afterwards, offline, through the same `/score` code path (`scripts/score_documents.py`).

## Pre-registered pass criteria (fix these before the session)
- **False flags:** at most 1 of about 20 natural papers is flagged (≤5%).
- **Catch rate:** at least 15 of about 20 not-own papers are flagged (≥75%).
- A "flag" is a **strict** action: `schedule_conversation` or `escalate`. `monitor` is reported separately as lenient.
- **INCONCLUSIVE** means the reference writing is below 3 samples or 300 words (the app's own rule). Those papers are excluded from the rates and reported as a rate of their own.
- **Small-sample caveat:** with n≈20 per arm, 0/20 false flags still has a 95% upper bound of about 16% (Wilson). A PASS means "no red flags", not "validated". Don't tune thresholds on this data and then claim the tuned numbers. The threshold sweep is for exploration only.

## Ground truth
- **Exam A:** each person's natural paper → `natural`.
- **Exam B:** each person writes in their consenting partner's style → `not_own`, `true_author` = the partner.
- **Optional injected samples:** another consenting participant's paper, or public-domain prose, placed into a target student's folder → `not_own`, `true_author` = the source.
- `labels.csv` (staff only): `submission_id,label,true_author`. It's built from the two exam exports, and injected files use their filename stem as the id.

## Running it
```
ALPHA_TOKEN=<Andrew's teacher bearer token> python batch_score_alpha.py \
  --base-url https://original-pilot.onrender.com --exam <examA> --exam <examB> \
  --labels labels.csv --repo /path/to/Orig --out alpha_scores/
# add injected texts to alpha_scores/export/<student>/submission/, then re-score offline:
python batch_score_alpha.py --from-dir alpha_scores/export --labels labels.csv --repo /path/to/Orig --out alpha_scores/
```
- **Export (read-only, tenant-scoped):** `GET /bluebook/exams/{id}/export` (CSV with the text), `GET /students` (roster and sample counts) and `GET /students/{id}/samples/{i}/text`.
- **Scoring:** for each student, a subprocess of `score_documents.py` runs on a throwaway SQLite database, with `DATABASE_URL`/`REPO_BACKEND` stripped and `ORIGINAL_ENV=demo`. It never writes to the pilot.
- **Output:** `report.md` and `per_submission.csv`, with opaque ids only. Exit codes: 0 = pass or no labels given, 1 = criteria failed, 2 = NaN, out-of-range or non-deterministic results.
- **Checks:** deviation and probability are within [0,1] with no NaN or inf, a second run matches, timing per paper and per student is recorded, and the baseline-size effect compares all samples against the first 3 only.
- **Report contents:** false-flag rate, catch rate, the strict confusion matrix, the lenient rates, a sweep from 0.05 to 0.95, the INCONCLUSIVE rate, Wilson and student-bootstrap 95% CIs, and PASS/FAIL.

## Local end-to-end test (2026-10-15, about 10:30 AM ET, synthetic data, not real writing)
- **Setup:** a local server (pilot mode, SQLite, consent-mvp + main). `invite_professor --with-original` gave products bluebook and original. There were 5 students, the teacher uploaded 3–5 synthetic reference papers each, and every student sealed papers for Exam A and Exam B. Scripts: `local_setup_original.py` and `local_setup_second_exam.py`.
- **Batch run:** 10 out of 10 scored, with no NaN or out-of-range values, and 10 of 10 matched on rerun. Each paper took up to about 4 s and each student run about 10 s, so 20 students take about 10 min with the rerun.
- **Results:** 0 of 4 natural papers were falsely flagged and 6 of 6 not-own papers were caught. The baseline-size effect averaged 0.04 (max 0.16). See `sample_report_synthetic.md`. **The texts are synthetic and have very different styles, so this proves only that the pipeline works, not that it's accurate.**
- **Deletion:** a dry run, then `--allow-original --execute`, removed the profiles/samples, score tables, submissions, enrollments and student logins (all 0 afterwards); only the teacher remained.
