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
| GET | `/admin/health` | System health summary for the admin dashboard (backup age, DB status). | None (dashboard-facing; not guard-tokened) |

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
| POST | `/students/{student_id}/baseline/upload-batch` | Bulk-upload baseline samples from files. | Principal (staff), tenant-scoped |
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
| POST | `/admin/calibration/runs/{run_id}/apply` | Persist a new active threshold set sourced from a calibration run. | Guard token |
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
| POST | `/bluebook/exams` | Create an exam. | Principal (staff) — tenant derived from request |
| GET | `/bluebook/exams` | List exams (tenant-scoped; `SUPER_ROLES` see all). | Principal (any), tenant-scoped |
| GET | `/bluebook/exams/{exam_id}` | Get one exam; 403 on cross-tenant access. | Principal (any), tenant-scoped |
| POST | `/bluebook/submissions` | Record one sat examination (the integrity reading for the Results view). | Principal (staff/student per Bluebook flow) |
| GET | `/bluebook/submissions` | List submissions (tenant-scoped). | Principal (any), tenant-scoped |
| POST | `/bluebook/courses` | Create a course. | Principal (staff) |
| GET | `/bluebook/courses` | List courses (tenant-scoped). | Principal (any), tenant-scoped |

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
