# Deletion plan (within 14 days of the test)

**Target:** day 7 after the test, once the batch report is done; day 14 at the latest.

1. **Keep only the aggregate report.** Keep `report.md`, with opaque ids and no texts, if Andrew wants it. Delete the export directory (all exam texts and reference papers), `per_submission.csv`, `labels.csv`, and any injected-sample files from every machine they were copied to. The batch scorer uses temporary directories for isolated SQLite files and removes them automatically when each scoring process finishes.
2. **App data:** in the Render Shell, from the repository root, first inspect the exact target:

   ```sh
   python scripts/alpha/delete_alpha_tenant.py t-<alpha-tenant-id>
   ```

   It is a dry run by default. Confirm the database backend is Postgres, the tenant name is exactly `Andrew (Alpha test)'s workspace`, the product list includes Original, and the roster count matches the test. The CLI refuses other tenant names and refuses to execute unless the exact name is confirmed.

   To delete, use the precise name printed by the dry run:

   ```sh
   python scripts/alpha/delete_alpha_tenant.py t-<alpha-tenant-id> \
     --execute --confirm-name "Andrew (Alpha test)'s workspace"
   ```

   Success prints zero remaining students, exams, and courses. If the database, tenant name, or counts differ, stop and ask Andrew to identify the correct tenant; do not broaden the script's scope.
3. **What app deletion removes:** the tenant's student profiles and samples, extracted features, score rows, manifests, corrections, display names, submissions, sessions, enrollments, invites, audit rows, student logins, exams, and course, through the repository's tenant deletion and student erasure path.
4. **Teacher login:** leave it (it holds no student data), or delete it by hand.
5. **Google Forms:** delete the consent sheet and label CSV. Anonymize the feedback sheet (drop name and email) or delete it. Delete papers and excerpts shared with partners and ask partners to delete their copies.
6. **Backups and logs:** pre-deletion backups and request logs age out on their configured schedule. Never restore a pre-deletion backup without rerunning step 2.
7. **Record:** note the date, counts printed, and operator in `docs/PILOT_LOG.md`. Tell participants their data is deleted.

**Local regression coverage:** `tests/alpha/test_alpha_scripts.py` exercises dry-run default, exact-name scoping, deletion, and the full local 20-student rehearsal against a temporary SQLite database. Do not use the live pilot for delete testing.
