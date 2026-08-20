# Branch Coverage Part 2 — API & Routers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read `2026-08-17-branch-coverage-index.md` §Global Constraints first — they all apply here.

**Goal:** Close the 162 missing branches in the API cluster (baseline 68.11% — the worst live-stack cluster): every router's untaken request-validation, error-response, and fallback arm becomes a pinned HTTP-level behavior.

**Architecture:** All tests drive the live stack through the session-scoped `live_client` fixture (`tests/conftest.py`) with `store_reset` isolation — the same idiom as the existing API suites (`tests/test_bluebook_api.py` et al.). External integrations (Bbook HTTP, Canvas, LTI platform JWKS) are monkeypatched at the module seam, never actually called.

**Tech Stack:** pytest, FastAPI TestClient, monkeypatch; no new dependencies.

**Baseline data:** `2026-08-17-branch-coverage-baseline.md` §api.

## Global Constraints (additional to the index's)

- **Never bypass the HTTP layer** for router branches — a branch closed by calling the handler function directly does not pin the status code, response shape, or dependency wiring. Call through `live_client`.
- **Auth-gated endpoints:** use the suite's existing login/provisioning helpers (see `tests/test_pilot_lockdown.py` / `tests/test_bluebook_api.py` for staff-login idioms) rather than inventing new fixtures.
- **`LOGIN_THROTTLE_MAX_ATTEMPTS` is process-global and read at import** — tests that deliberately trip the throttle must not run before other login-dependent tests in the same process (see the CI serial-lockout precedent in `.github/workflows/test.yml`). Prefer asserting the counting arms without exhausting the bucket.
- **`lifespan` (12/12 missing) runs at app startup** — its arms are backup-scheduler and env-conditional wiring. Test via `TestClient(app)` context entry with the relevant env vars monkeypatched, not by refactoring lifespan.

## Measured gap tables (2026-08-17)

| File | Missing | Worst functions (missing/total) |
|---|---|---|
| `routers/students_baseline.py` | 36 | `upload_baseline_batch` 24/24, `add_baseline` 6/22, `request_proctored_baseline` 4/4, `_existing_text_hashes` 2/8 |
| `routers/students.py` | 19 | `upload_file` 6/6, `get_sample_text` 4/4, `open_formation` 2/2, `get_student_readiness` 2/18, `advance_formation` 2/2, `list_students` 1/4, `delete_student` 1/2, `student_data_inventory` 1/2 |
| `routers/bluebook.py` | 19 | `bluebook_magic_launch` 8/8, `bluebook_record_submission` 4/16, `bluebook_list_exams` 3/4, `bluebook_list_courses` 3/4, `bluebook_list_submissions` 1/4 |
| `lti.py` | 16 | `_private_key_pem` 4/4, `public_jwks` 2/2, `fetch_jwks` 2/2, `verify_state` 2/6, `verify_launch` 2/10, + 1-missing arms in `principal_from_claims`, `is_exam_launch`, `find_platform`, `build_login_redirect` |
| `api.py` | 16 | `lifespan` 12/12, `_resolve_allowed_origins` 2/6, `security_headers` 1/4, `_resolve_app_version` 1/2 |
| `routers/admin.py` | 12 | `submit_correction` 2/12, `admin_list_corrections` 2/4, `admin_list_calibration_runs` 2/4, six 1-missing arms |
| `routers/auth.py` | 11 | `student_login` 3/6, `demo_login` 3/8, `student_me` 2/2, `auth_register` 2/8, `auth_login` 1/4 |
| `routers/students_scoring.py` | 8 | `score_submission` 5/46, `score_blend` 2/4, `_all_states` 1/2 |
| `routers/imports.py` | 6 | `import_canvas_baseline` 4/16, `fetch_canvas_submission_text` 2/6 |
| `routers/lti_routes.py` | 5 | `lti_launch` 4/4, `lti_login` 1/2 |
| `routers/_shared.py` | 4 | one arm each in `_throttle_login`, `_require_staff`, `_require_guard`, `_authorize_provenance` |
| `routers/proctor.py` / `me.py` / `health.py` / `tenants.py` | 3+3+3+1 | `admin_health` 3/4, `my_formation_advance` 2/2, singles elsewhere |

---

### Task 1: `upload_baseline_batch` — 24/24 missing (worked example)

**Files:**
- Create: `tests/test_students_baseline_batch.py`

**Interfaces:**
- Consumes: `live_client`, `store_reset` fixtures (`tests/conftest.py`); route `POST /students/{student_id}/baseline/upload-batch` (multipart `files` + form `provenance`, `assignment`).
- Produces: the test-file naming pattern `test_students_baseline*` that the pre-push mapper associates with `routers/students_baseline.py`.

Every branch of the batch importer (`students_baseline.py:329-` ) is unexercised: the provenance gate, all four extension arms, empty-text, dedup, feature-failure, and the drift-hold loop.

- [ ] **Step 1: Write the failing tests**

```python
"""Branch tests for POST /students/{id}/baseline/upload-batch (part 2, task 1)."""

from __future__ import annotations

import io

BATCH = "/students/{sid}/baseline/upload-batch"
GOOD_TEXT = (
    "The doctrine of vocation, as articulated in the letters, situates daily labor "
    "within a larger account of providence. " * 30
)


def _post_files(client, sid, files, provenance="verified", assignment=""):
    return client.post(
        BATCH.format(sid=sid),
        files=[("files", f) for f in files],
        data={"provenance": provenance, "assignment": assignment},
    )


class TestUploadBatchBranches:
    def test_unknown_provenance_is_422(self, live_client, store_reset):
        r = _post_files(
            live_client, "s-batch-1",
            [("a.txt", io.BytesIO(GOOD_TEXT.encode()), "text/plain")],
            provenance="notarized",
        )
        assert r.status_code == 422
        assert "provenance" in r.json()["detail"]

    def test_txt_import_and_duplicate_skip(self, live_client, store_reset):
        payload = [("a.txt", io.BytesIO(GOOD_TEXT.encode()), "text/plain")]
        first = _post_files(live_client, "s-batch-2", payload)
        assert first.status_code == 200
        assert first.json()["imported"] == 1

        again = _post_files(
            live_client, "s-batch-2",
            [("b.txt", io.BytesIO(GOOD_TEXT.encode()), "text/plain")],
        )
        body = again.json()
        assert body["imported"] == 0
        assert body["skipped_duplicates"] == 1

    def test_unsupported_extension_is_reported_not_fatal(self, live_client, store_reset):
        r = _post_files(
            live_client, "s-batch-3",
            [
                ("notes.rtf", io.BytesIO(b"whatever"), "application/rtf"),
                ("ok.txt", io.BytesIO(GOOD_TEXT.encode()), "text/plain"),
            ],
        )
        body = r.json()
        assert body["imported"] == 1
        assert any("unsupported type" in e for e in body["errors"])

    def test_empty_text_file_is_reported(self, live_client, store_reset):
        r = _post_files(
            live_client, "s-batch-4",
            [("empty.txt", io.BytesIO(b"   \n"), "text/plain")],
        )
        assert any("no text extracted" in e for e in r.json()["errors"])

    def test_corrupt_docx_hits_the_extraction_error_arm(self, live_client, store_reset):
        r = _post_files(
            live_client, "s-batch-5",
            [("broken.docx", io.BytesIO(b"not a zip archive"), "application/msword")],
        )
        assert any("extraction error" in e for e in r.json()["errors"])

    def test_extensionless_filename_takes_the_no_dot_arm(self, live_client, store_reset):
        r = _post_files(
            live_client, "s-batch-6",
            [("README", io.BytesIO(GOOD_TEXT.encode()), "text/plain")],
        )
        assert any("unsupported type" in e for e in r.json()["errors"])
```

- [ ] **Step 2: Run**

Run: `.venv/bin/python -m pytest tests/test_students_baseline_batch.py -q`
Expected: PASS if the handler matches its documented behavior; any failure is a real finding — verify the response-shape key names (`imported`, `skipped_duplicates`, `errors`) against the handler's return statement (read `students_baseline.py` past line 414) and correct the ASSERTION KEYS only if the shape differs, never the semantics being pinned.

- [ ] **Step 3: Add the remaining arms** the digest lists for this file, same idiom: `add_baseline`'s 6 untaken arms (read its 48-230 range and pin its 202/409 drift arms), `request_proctored_baseline` 4/4 (monkeypatch `original.bbook_client.is_enabled` → `False` for the disabled arm and a stub `request_baseline` for the success arm), `_existing_text_hashes` 2/8 (samples without `text_hash` attributes — legacy paste-added samples).

- [ ] **Step 4: Verify branches**

```bash
.venv/bin/python -m pytest tests/test_students_baseline_batch.py tests/ -k "students_baseline" -q \
  --cov=original.routers.students_baseline --cov-branch --cov-report=term-missing
```

Expected: `upload_baseline_batch` fully covered; file branch % from 37.93 to ≥90.

- [ ] **Step 5: Commit**

```bash
git add tests/test_students_baseline_batch.py
git commit -m "Add upload-batch branch tests covering provenance, extraction, dedup, and error arms"
```

---

### Task 2: `routers/students.py` + `routers/me.py` (22 missing)

- [ ] Extract exact arms (index snippet). Write HTTP-level tests in a new `tests/test_students_router_branches.py`: `upload_file` 6/6 (single-file variant of Task 1's arms), `get_sample_text` 4/4 (found/missing sample, retained/absent text), formation open/advance 2/2 each (state transitions + invalid state), `get_student_readiness`'s 2 untaken arms, the `list_students` filter arm, `delete_student` not-found arm, `my_formation_advance` 2/2 and `my_voice` fallback in `me.py`.
- [ ] Verify with `--cov=original.routers.students --cov-branch`; commit `"Add students/me router branch tests"`.

### Task 3: `routers/bluebook.py` (19 missing)

- [ ] `bluebook_magic_launch` 8/8: all launch-token validation arms (missing/expired/bad-signature token, unknown exam) — mint tokens with `original/student_auth.py`'s helpers exactly as `tests/test_bluebook_api.py` does for its valid-path tests. `bluebook_record_submission`'s 4 untaken arms; the pagination/empty arms of the three list endpoints.
- [ ] Verify + commit `"Add bluebook router branch tests for launch-token and list arms"`.

### Task 4: `lti.py` + `routers/lti_routes.py` (21 missing)

- [ ] `_private_key_pem` 4/4: the three env sources (`LTI_PRIVATE_KEY`, `_FILE`, `_PEM`) and the none-set arm — monkeypatch env per test; `public_jwks`/`fetch_jwks` 2/2 each (configured vs not; stub `httpx` for fetch); `verify_state`/`verify_launch` remaining arms (expired state, wrong audience — build JWTs with the test key the existing LTI tests use); `lti_launch` 4/4 and `lti_login` 1/2 at the HTTP layer with a monkeypatched platform config.
- [ ] Verify + commit `"Add LTI key-resolution and launch-validation branch tests"`.

### Task 5: `api.py` + `routers/_shared.py` + `routers/health.py` (23 missing)

- [ ] `lifespan` 12/12: enter `TestClient(run.load_legacy_demo_app())` context with `BACKUP_DIR`/`BACKUP_INTERVAL_MINUTES` set and unset (both arms of each conditional wire) — assert startup completes and the scheduler object exists/absents. `_resolve_allowed_origins` 2/6: the production-unset fail-closed arm (CLAUDE.md documents it) and the wildcard-rejection arm. `security_headers` HSTS arm under `ENABLE_HSTS`. `admin_health` 3/4: degraded-dependency arms via monkeypatched repo. `_shared.py`'s four single arms (throttle window expiry, guard-token mismatch, provenance denial) — each is a security control; pin the DENY side.
- [ ] Verify + commit `"Add app-lifecycle, CORS fail-closed, and shared-guard branch tests"`.

### Task 6: `routers/auth.py` + `routers/admin.py` + `routers/students_scoring.py` + `routers/imports.py` + `routers/proctor.py` + `routers/tenants.py` (31 missing)

- [ ] Extract arms; write per-router test files following Task 1's idiom. Highest-value: `score_submission`'s 5 untaken arms of 46 (read them — they are flag-interaction arms; assert under the flag env the arm needs, and that default-off output is unchanged), `demo_login`/`student_login` failure arms, `import_canvas_baseline`'s config-absent 400 guidance arm (CLAUDE.md documents the message), `create_tenant` duplicate arm.
- [ ] Verify + commit per router file.

### Task 7: Sweep + part completion

- [ ] Re-measure full suite; `scripts/branch_coverage_report.py coverage.json --cluster api` must show every file ≥95% branch or carry justified `# pragma: no cover` annotations (candidates: defensive `except` guards around store calls).
- [ ] Drain the cluster's partial branches.
- [ ] Update the index dashboard row; apply the CI ratchet step (+1 floor if measured headroom holds); commit `"Record part 2 api-routers branch-coverage completion"`.

## Self-Review Notes

- Task 1's code was written against the actual handler source (`students_baseline.py:329-413`, read 2026-08-17): the provenance gate reads `AUTH_WEIGHTS`, extension parsing lowercases the last dot-suffix (so `README` → `''` → unsupported arm), dedup hashes `text.encode()` against `getattr(s, "text_hash", None)`.
- Response-shape keys in Task 1 Step 2 are the one deliberately-verify-then-fix point; the handler's tail (past line 413) was not read when this plan was written.
- The drift-hold arm (`drift_holds`) needs a student whose existing baseline makes a new upload an outlier — build it with 3 stylistically-uniform baselines then one wildly different text; see `StudentState.check_drift` (threshold 0.25 on main).
