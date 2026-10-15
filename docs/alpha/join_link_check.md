# Join-flow check

## Live pilot limits

For this alpha rehearsal, do not open invite links or submit forms on the live pilot. Live checks are limited to unauthenticated GET requests for `/health`, public pages, and their static assets. Run the scripted GET-only check with:

```sh
python scripts/alpha/live_smoke.py --base-url https://original-pilot.onrender.com
```

## Local verification

The local verification CLI validates its input and prints the exact invite redemption and login steps against a local server only:

```sh
python scripts/alpha/verify_join_flow_local.py --help
python run.py --demo --port 8001
python scripts/alpha/verify_join_flow_local.py '/bluebook/?invite=LOCAL_INVITE_TOKEN' --base-url http://127.0.0.1:8001
```

The first command starts the local server; run the verifier in a second terminal after creating a local professor invite. Replace `LOCAL_INVITE_TOKEN` with that throwaway invite token. The verifier rejects non-local hosts so the check cannot accidentally be aimed at the pilot.

## End-to-end rehearsal

`tests/alpha/test_alpha_scripts.py::test_local_runbook_rehearsal_twenty_concurrent_students_full_delete` runs `invite_professor.py --with-original`, creates the course and two 25-minute exams with paste blocked and writing consistency off, enrolls 20 students, adds three baselines each, seals both exams concurrently, checks invite reuse and student score privacy, exports and labels work, runs batch scoring and the report, then deletes the tenant. It uses a temporary SQLite database and synthetic text. It makes no requests to the live pilot.
