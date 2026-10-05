# API Reference (live stack)

> **The canonical, generated reference is FastAPI's live `/docs` (Swagger UI)**
> on the running server — it always matches the deployed code, including
> request/response schemas. This page is a curated, grouped-by-audience
> companion for orienting a new reader; it will drift if endpoints are added
> without updating it, so treat `/docs` as ground truth for anything this page
> doesn't cover.
>
> Scope: the **live stack only** — `original/api.py` (student/professor/admin
> dashboard backend, ~59 routes) plus `original/lti.py`-backed `/lti/*`
> routes. The dormant v1 API (`original/api/`, prefixed `/api/v1/...` except
> where noted below) is a separate, unmaintained surface — see
> [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) for the live-vs-dormant split.
> Endpoints on the live app that happen to share the `/api/v1/` prefix (there
> is exactly one: `POST /api/v1/auth/login`, a legacy-path demo login) are
> listed below under Health/Auth, not the dormant stack.

## Auth model, in one paragraph

Most routes resolve an identity via `original/principal.py`'s middleware,
which reads (in priority order) a **signed principal token** (`Authorization:
Bearer <token>`, minted by `POST /auth/login` or an LTI launch; carries
`{user_id, role, tenant_id}`), a **student session token** (minted by
`POST /student-auth/login`, verified by `original/student_auth.py`), or falls
back to an **anonymous demo principal** with no credentials at all. Tenant
isolation and role checks (`professor`/`admin`/`operator`/`student`,
`SUPER_ROLES` = cross-tenant) are enforced centrally by that middleware for
`/students/*` and `/canvas/baseline/*` paths, and inline per-handler
elsewhere (mirrored `if p and not p.is_demo and p.role not in SUPER_ROLES`
tenant-scoping checks — see `original/api.py`). A **separate mechanism**,
`GUARD_DESTRUCTIVE` + `X-Guard-Token` (`original/api.py:_require_guard`),
gates a handful of high-risk endpoints independent of the principal system —
see [`docs/OPS_RUNBOOK.md`](OPS_RUNBOOK.md) "Destructive-endpoint guard" for
the full semantics (it's also the demo-only admin-login backdoor password
outside real deploys — don't confuse it with `SECRET_KEY`).

In the tables below, **Auth** means:

- **None** — no credentials required; anonymous/demo principal is accepted.
- **Principal (any)** — any authenticated principal (professor/admin/operator/
  student token); demo/anonymous also generally works, scoped to the demo
  tenant.
- **Principal (staff)** — tenant-scoped to `professor`/`admin`/`operator`;
  cross-tenant access denied for non-`SUPER_ROLES`.
- **Student session** — the `/student-auth/login` or `/me/*` session token;
  self-only access enforced (`assert_student_access`, `principal.py`).
- **Guard token** — additionally requires `X-Guard-Token` when
  `GUARD_DESTRUCTIVE=1` (pilot/production); open in demo mode. See
  OPS_RUNBOOK.
- **LTI** — resolved via the LTI 1.3 launch flow, not the principal token.

This describes what the code enforces today, not an aspirational RBAC model —
several endpoints below have looser enforcement than you might expect for
their sensitivity (noted inline).

---

## Health

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/health` | Liveness/readiness probe; used by UptimeRobot/Render. | None |
| GET | `/admin/health` | System health summary for the admin dashboard (backup age, DB status). | Principal (staff); not guard-tokened. Infra probes should use `/health`. |

## Auth (staff + demo)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/auth/login` | Staff (professor/admin/operator) email+password login; returns a principal token. | None (throttled: 10 attempts / 5 min / IP) |
| GET | `/auth/me` | Return the authenticated principal, or 401. | Principal (any) |
| POST | `/auth/register` | Provision a staff user. | None in demo; Guard token in pilot/production |
| POST | `/api/v1/auth/login` | Legacy-path demo login alias (same login logic, different URL for older frontend code). | None (throttled, same as `/auth/login`) |

## LTI (LMS launch)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET/POST | `/lti/login` | LTI 1.3 OIDC login-initiation redirect. | LTI (platform-issued request) |
| POST | `/lti/launch` | LTI 1.3 launch; verifies the platform's signed `id_token` and mints a principal token. | LTI (signed id_token) |
| GET | `/lti/jwks` | Tool's public JWKS for the platform to verify our signed responses. | None (public key material) |

## Students (professor/admin dashboard)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/students` | List students (tenant-scoped roster). | Principal (staff) |
| GET | `/students/{student_id}` | Full student state: baseline vector, sample counts, purity. | Principal (staff), tenant-scoped via middleware |
| GET | `/students/{student_id}/readiness` | Baseline-readiness signal (enough authenticated samples to score reliably?). | Principal (staff), tenant-scoped |
| GET | `/students/{student_id}/samples/{index}/text` | Retrieve raw stored text for one baseline/submission sample. | Principal (staff), tenant-scoped |
| DELETE | `/students/{student_id}` | Permanently delete all stored data for a student (FERPA right-to-erasure). | Principal (staff), tenant-scoped |
| GET | `/students/{student_id}/data-inventory` | FERPA data-access response: structured inventory of everything held for a student. | Principal (staff), tenant-scoped |
| POST | `/students/{student_id}/baseline` | Add one baseline writing sample. | Principal (staff), tenant-scoped |
| POST | `/students/{student_id}/baseline/upload-batch` | Bulk-upload baseline samples from files. | Tenant-scoped; any principal may write, but trusted provenance (`proctored`/`verified`/`canvas`) requires staff or a proctor attestation — otherwise downgraded to `unverified` (T-67) |
| POST | `/students/{student_id}/upload` | Extract plain text from an uploaded `.txt`/`.docx`/`.pdf` (utility endpoint, no persistence). | Principal (staff) |
| POST | `/students/{student_id}/request-baseline` | Provision a magic-link proctored baseline exam in Bluebook. | Principal (staff), tenant-scoped |
| POST | `/students/{student_id}/score` | Score a submission against the student's baseline (the core Layer-7 pipeline). | Principal (staff), tenant-scoped |
| POST | `/students/{student_id}/score/blend` | Score with an alternate Stage 5/6 context-manifest blend (experimental path). | Principal (staff), tenant-scoped |
| GET | `/students/{student_id}/formation` | Return the student's active/most recent formation pathway. | Principal (staff) |
| POST | `/students/{student_id}/formation` | Open a three-session formation pathway. | Principal (staff) |
| POST | `/students/{student_id}/formation/advance` | Advance the open formation pathway by one session. | Principal (staff) |

## Baseline requests / imports (professor/admin)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/baseline-requests/pending` | List currently-pending proctored baseline requests. | None (not tenant-filtered — dashboard-internal) |
| GET | `/baseline-requests` | List every proctored baseline request, any status. | Principal (staff) |
| POST | `/import/courses/{course_id}/turnitin-csv` | Parse a Turnitin admin CSV export into student/submission stubs. | Principal (staff) |
| POST | `/canvas/baseline/{student_id}/list-canvas-submissions` | List a student's past Canvas submissions available for import. | Principal (staff), tenant-scoped via middleware |
| POST | `/canvas/baseline/{student_id}/import-baseline` | Import a Canvas submission as a baseline sample (demo stub — returns "not available in demo server"). | Principal (staff), tenant-scoped |

## Submissions / corrections (professor/admin)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/submissions/{submission_id}/correct` | Record an instructor's correction/override of a scoring decision. | Principal (staff) |
| GET | `/admin/manifests` | List scoring manifests (paginated, filterable by student/action). | Principal (staff) |
| GET | `/admin/manifests/stats` | Aggregate stats over scoring manifests (action distribution, volume). | Principal (staff) |
| GET | `/admin/corrections` | List instructor corrections (paginated, filterable). | Principal (staff) |
| GET | `/admin/audit` | Query the audit log (login, deletion, scoring, and other data-affecting actions). | Principal (staff) |

## Tenants (admin/operator)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/tenants` | Register or update a tenant (institution) record. | Principal (staff/operator) |
| GET | `/tenants` | List all registered tenants, optionally filtered by environment. | None (dashboard-internal; not guard-tokened) |
| GET | `/tenants/{tenant_id}` | Get a single tenant record. | None |
| GET | `/tenants/{tenant_id}/stats` | Aggregate statistics for a tenant (student count, submission volume). | None |
| DELETE | `/tenants/{tenant_id}/students` | FERPA-safe bulk deletion of all students in a tenant. | Guard token (pilot/production); open in demo |

## Calibration / lab (admin, experimental)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/admin/lab/datasets` | List datasets the calibration lab can run against (Federalist, multi-author, …). | Principal (staff) |
| POST | `/admin/calibration/run` | Kick off a calibration run in the background; returns a run id (202). | Principal (staff) |
| GET | `/admin/calibration/runs` | List calibration runs (filterable by status/dataset). | Principal (staff) |
| GET | `/admin/calibration/runs/{run_id}` | Fetch one calibration run, optionally with its full report. | Principal (staff) |
| GET | `/admin/calibration/runs/{run_id}/suggestions` | Threshold-tuning suggestions derived from a finished run + corrections. | Principal (staff) |
| POST | `/admin/calibration/runs/{run_id}/apply` | Persist a new active threshold set sourced from a calibration run. | Principal (staff) + guard token |
| GET | `/admin/tuned-thresholds` | Currently-active tuned threshold set, or null. | Principal (staff) |
| GET | `/admin/tuned-thresholds/history` | Audit list of every tuned-threshold version ever applied. | Principal (staff) |
| POST | `/test/score` | Playground endpoint: run the full adaptive pipeline on inline text, no persistence. | None |

## Students (self-service — student session)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/student-auth/login` | Student sign-in by email + institution; auto-provisions the student record and a demo tenant if new. Returns a session token. | None |
| GET | `/student-auth/me` | Return the signed-in student's basic identity, or 401. | Student session |
| GET | `/me/voice` | The complete, redacted `VoiceView` for the signed-in student (ADR-005: no feature codes, raw scores, or thresholds ever cross the wire). | Student session, self-only |
| POST | `/me/work` | Submit a piece of writing; scores it server-side and returns only the redacted formation-register result. | Student session, self-only |
| POST | `/me/formation/advance` | Advance the student's own formation pathway. | Student session, self-only |

## Bluebook (proctored exam surface)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/bluebook/launch?t={token}` | Redeem a magic-link launch token (minted offline by `scripts/roster_links.py`): mints a short student session + proctor attestation into localStorage and redirects to `/bluebook/`. 400 on an invalid/expired token. | Signed launch token in `t` |
| POST | `/bluebook/exams` | Create an exam. | Principal (staff) — tenant derived from request |
| GET | `/bluebook/exams` | List exams (tenant-scoped; `SUPER_ROLES` see all). | Principal (any), tenant-scoped |
| GET | `/bluebook/exams/{exam_id}` | Get one exam; 403 on cross-tenant access. | Principal (any), tenant-scoped |
| POST | `/bluebook/exams/{exam_id}/session` | Begin or resume a sitting. Body: `student_id` or `candidate`. First call pins `deadline_at = started_at + exam.duration`; every later call returns the same row (reopening never restarts the clock). Returns `{exam_id, started_at, deadline_at, server_now, duration_seconds}`. | Principal (student/demo per Bluebook flow) |
| POST | `/bluebook/submissions` | Record one sat examination (the integrity reading for the Results view). Idempotent on `submission_uuid`; seals > 5 min past `deadline_at` are tagged `late: true`. A submission stays inside the caller's workspace: an `exam_id` naming a stored exam of another workspace → 404 `exam not found` (an id that is not stored, such as the built-in sample, is accepted); staff naming another workspace's `student_id` → 403 `Cross-tenant access denied.`; a signed-in student naming any `student_id` but their own → 403. Sealing never adds to the student's Original baseline (see the baseline routes below). | Principal (staff), or the student's own session |
| GET | `/bluebook/submissions` | List submissions (tenant-scoped). | Principal (any), tenant-scoped |
| POST | `/bluebook/courses` | Create a course. | Principal (staff) |
| GET | `/bluebook/courses` | List courses (tenant-scoped). | Principal (any), tenant-scoped |

### Professor-approved writing baselines (`original/routers/bluebook_baselines.py`)

A sealed exam enters a student's Original baseline only through these routes.
All four require a staff principal (student → 403 `Staff role required.`;
the anonymous demo principal on a real deploy → 401) whose workspace owns the
submission or exam (operators: any workspace), and a workspace whose plan
includes Original. "In baseline" is derived from the profile itself: the
SHA-256 of the exam's answers joined by a blank line (no "Question N."
headings), or of the stored submission text exactly as the old seal-time
write sent it (with headings), is among the hashes of the student's samples.
Approval adds through `POST /students/{id}/baseline`'s handler with provenance
`proctored`, so its validation, seal-replay guard and drift gate apply; the
drift gate is never overridden. Audit details carry ids and counts only, never
student text.

| Method | Path | Returns | Errors |
|---|---|---|---|
| POST | `/bluebook/submissions/{submission_id}/baseline` | Add one sealed exam. `{submission_id, student, status, detail}`, `status` ∈ `added` \| `already_in_baseline` \| `held` (the drift gate did not admit it; `detail` says so). Audit `baseline_approve` with `result` = the status. | 404 `submission not found` (missing, another workspace's, or its student is not in the submission's workspace); 403 `This workspace's plan does not include Original.`; 422 `Nothing written to add.` (no answer text or no student id). |
| DELETE | `/bluebook/submissions/{submission_id}/baseline` | Take the exam out of the baseline. Removes every sample carrying either fingerprint (duplicates included) and recomputes the profile from the remaining samples. `{submission_id, student, status, detail}`, `status` ∈ `removed` \| `not_in_baseline`. Audit `baseline_remove` with `samples_removed`, `sample_count_after`. | 404, 403 as above; 503 if the profile could not be saved. |
| POST | `/bluebook/exams/{exam_id}/baseline` | Add every sealed submission of the examination. `{added, already_in_baseline, held, nothing_written, errors, results: [{submission_id, student, status, detail}]}`; a row that fails is `status: "error"` (with a short `detail`) and does not stop the batch. Audit `baseline_approve_bulk` with the counts and the submission ids per status (`added_ids`, `already_in_baseline_ids`, `held_ids`, `nothing_written_ids`, `error_ids`). | 404 `exam not found`; 403 `This workspace's plan does not include Original.` |
| GET | `/bluebook/exams/{exam_id}/baseline` | `{submissions: [{submission_id, student, in_baseline, has_text}]}` for each submission of the examination. A row whose student is not in its workspace reads `in_baseline: false`. | 404 `exam not found`; 403 `This workspace's plan does not include Original.` |

## Proctor phone-park (`original/routers/proctor.py`; client is `demo/bluebook/parked.html`)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/proctor/park/open` | Open (or re-join) a phone-park for one exam sitting. Body: `{exam_session_id}`. Returns `{park_token, qr_url}`; re-opening a live session returns the SAME token. Sweeps rows past the 24h retention window. | Principal (staff), tenant-scoped |
| POST | `/proctor/park/beat` | One heartbeat from a parked phone. Body: `{park_token, student_hint, state}` with `state` ∈ `parked` \| `foreground_lost` \| `resumed`. **Anonymous by design** — the handler takes no `Request`, so IP/UA are unreachable; the token is the sole capability. 404 for unknown *and* expired tokens alike. | Park token only |
| GET | `/proctor/park/status?exam_session_id=…` | Live tiles: `{tiles: [{student_hint, state, last_seen_seconds_ago, transitions}]}`. `state` is derived — a phone silent > 30s reads `dropped` regardless of its last claim. | Principal (staff), own tenant only |
| DELETE | `/proctor/park/{exam_session_id}` | Delete the park session and all its beats (ephemeral data only — deliberately not behind the ops guard; early deletion is data minimisation). | Principal (staff), own tenant only |

---

## Notes on accuracy and drift

- Route count and paths were re-derived from
  `grep -n "@app\.\(get\|post\|put\|delete\|patch\)\|@app\.api_route" original/api.py`
  plus the three `/lti/*` routes registered against the same `app` — 59 routes
  total on the live app, matching `docs/AUDIT_2026-07-06.md`'s independently
  measured "60 endpoints" (off-by-one from that audit's own count is
  explained by the audit counting slightly differently; both are within
  rounding of the same live surface — re-run the grep above if this page and
  the code disagree).
- "Auth" column reflects what each handler and the request middleware
  (`original/principal.py`) actually check, not a target RBAC design. Several
  endpoints (tenant list/stats, pending baseline requests, `/test/score`) have
  no tenant-scoping or credential check today — this is a known gap, not a
  documentation error; see `docs/AUDIT_2026-07-06.md` §1 (A-series findings)
  and §6 (S-series findings) for the broader consistency audit.
- For request/response schemas, use the running server's `/docs` (Swagger UI)
  or `/openapi.json`.

## Related documents

- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — live vs. dormant stack split.
- [`README.md`](../README.md) — quickstart and the same endpoint groupings at
  a higher level.
- [`docs/OPS_RUNBOOK.md`](OPS_RUNBOOK.md) — `GUARD_DESTRUCTIVE`/
  `MAINTENANCE_TOKEN` semantics referenced throughout the Auth column.
- [`docs/adr/005-student-read-model.md`](adr/005-student-read-model.md) — the
  redaction contract behind `/me/voice` and `/me/work`.
