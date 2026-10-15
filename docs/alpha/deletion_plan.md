# Deletion plan (within 14 days of the test)

**Target:** day 7 after the test, once the batch report is done; day 14 at the latest.

1. **Keep only the aggregate report.** Keep `report.md`, with opaque ids and no texts, if Andrew wants it. Delete `export/` (all texts and reference papers), `per_submission.csv`, **`labels.csv`** and any injected-sample files from every machine they were copied to. The batch scorer's throwaway SQLite files go in `/tmp/alpha_score_*` and `/tmp/alpha_b3_*`; delete those too.
2. **App data:** in the Render shell:
   - `python scripts/delete_alpha_tenant.py t-<alpha id>` gives a dry run. Check that the backend is postgres, the name is "Andrew (Alpha test)'s workspace", the product list **includes original** (the script refuses an Original workspace unless you pass `--allow-original`, so it can never run against a school by accident) and there are about 20 students.
   - `python scripts/delete_alpha_tenant.py t-<alpha id> --allow-original --execute --confirm-name "<exact name>"` does the deletion. It must print 0 remaining students, exams and courses.
   - What this removes, for each student, through the repo's FERPA erasure path (`delete_tenant_students` → `delete_student`): baseline **profile and samples** (the uploaded papers), extracted **features**, **score rows** (fidelity, likelihood and fused scores), manifests, corrections, display names, submissions, sessions, enrollments, invites, audit rows and the student's login. It also removes the alpha exams and course.
3. **Teacher login:** leave it (it holds no student data), or delete it by hand.
4. **Google Forms:** delete the consent sheet and the label CSV. Anonymize the feedback sheet (drop name and email) or delete it. Delete the papers and excerpts that were shared with partners (email or Drive), and ask partners to delete their copies.
5. **Backups and logs:** pre-deletion backups and request logs (IP and browser) age out on their schedule (~30 days). Never restore a pre-deletion backup without re-running step 2.
6. **Record:** note the date, the counts printed and who ran it in `docs/PILOT_LOG.md`. Tell participants their data is deleted.

**Local test (2026-10-15):** see the bottom of `scoring_plan.md`.
