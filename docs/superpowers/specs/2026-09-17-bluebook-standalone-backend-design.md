# Bluebook as a Standalone Product — Backend Design

**Date:** 2026-09-17, amended 2026-09-28 · **Status:** specified · **Scope:** backend only; the two Bluebook dashboards are a separate spec

> **Read the 2026-09-28 amendment at the end first.** It changes the launch target to a
> public self-serve site and overrides decision 1 for self-serve tenants.

## Problem

Bluebook (the secure-exam product in `demo/bluebook/` and `original/routers/bluebook.py`)
is going to be sold on its own, without Original. Canvas/LTI integration is sidelined
for the initial product. Today nothing in the system can express "this institution
bought Bluebook only":

- **No entitlement.** The tenant record (`tenants` table) holds `tenant_id`, `name`,
  `environment`, and a free-form `meta_json`. Nothing reads `meta_json` to gate a
  feature. All gating is global env flags.
- **Students have no accounts.** A student arrives through a signed launch link
  (`GET /bluebook/launch`), receives a stateless session for one sitting, and is gone.
  There is nowhere for a student to return to. The `users` table is staff only.
- **No roster.** `bluebook_exams.course` is a free-text label, not a link to
  `bluebook_courses`. Nothing records which students belong to a course. The teacher
  "roster" in `Students.jsx` is the set of students who have already sat an exam.
- **No exam window.** Exams have a `status` and a `duration` but no open or close time,
  so "upcoming and open exams" cannot be computed.
- **The seal is coupled to Original.** On every seal the Bluebook client calls
  `POST /students/{id}/score` and `POST /students/{id}/baseline` (with `proctored`
  provenance) before it records the Bluebook submission. Submission text lives only in
  the student's Original profile.

## Decisions taken

These were settled in the brainstorming session and are not re-argued below.

1. **Scoring and baseline writes keep running for every tenant.** A Bluebook-only tenant
   accumulates Original profiles in the background. This makes a later upgrade to
   Original a single tenant edit with history already in place. The dashboards and the
   API responses hide the numbers; the computation does not stop.
2. **Entitlement is a `products` column on the tenant.** One tenant can hold both
   products. No separate tenants or deployments per product.
3. **Students get email + password accounts** in the existing `users` table.
4. **Provisioning is by teacher-issued invite link.** No email sending, no self-signup.
5. **Entitlement is enforced server-side**, with a narrow carve-out for the two
   seal-time calls.
6. **Canvas/LTI code stays**; only its UI entry points are removed.
7. **Approach: extend the live stack in place.** No package carve-out, no relocation of
   working code.

## Enabling facts

- Student ids are already deterministic: `derive_student_id(tenant, email)` gives
  `{tenant_slug}:{sha256(email)[:16]}` (`original/student_auth.py`). Launch links,
  Original profiles, and Bluebook sessions all key on it. Accounts can adopt the same id
  without rekeying anything.
- The tenant-isolation middleware (`original/api.py:tenant_isolation`) already resolves a
  student session token to a `student` principal confined to its own record
  (`principal.assert_student_access`). New student routes inherit that for free.
- `mint_proctor_attestation` (`student_auth.py`) is what makes a sitting land as
  `proctored`; `_authorize_provenance` (`routers/_shared.py:346`) honours it. A
  dashboard-started sitting can mint the same attestation.
- The middleware already has a path-table pattern for staff-only routes
  (`_STAFF_ONLY_EXACT`, `_STAFF_ONLY_PREFIXES`). Product gating adds a second table
  next to it, in the one place that is audited.
- Schema changes have an established shape: an Alembic migration for Postgres
  (`alembic/versions/`, head `9f2c7a1b4d63`) mirrored by guarded
  `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE` in `original/store.py`, plus matching
  methods on the repository protocol (`original/repository.py`) and both backends.
- `bbook_client.py` and `BBOOK_API_URL` / `BBOOK_EXTERNAL_SECRET` are a separate,
  never-configured external integration. They are not the in-repo Bluebook and this
  design does not touch them.

## Section 1 — Entitlement

### Storage

One new column: `tenants.products`, text holding a JSON array. Allowed values:
`"original"`, `"bluebook"`. Migration default is `["original","bluebook"]`, so every
existing tenant keeps today's behaviour with no backfill. A tenant id with no tenant
row (the anonymous demo path can still produce one) also resolves to both products.

### Admin surface

- `POST /tenants` accepts an optional `products` list. Empty or unknown values are a
  422. Omitted means both. `tenant_id` must equal `slugify(tenant_id)`; a 422
  otherwise. (The student-id derivation slugifies the tenant, so a non-slug tenant id
  would produce ids under a different prefix and break isolation. Existing pilot
  tenants already satisfy this or their launch links would not resolve.)
- New `PATCH /tenants/{tenant_id}` with body `{products: [...]}`. Same guard and
  super-role rules as `POST /tenants`. This is the upgrade path: one call, no data
  moves. Audited as `tenant_products_update`.
- `GET /tenants` and `GET /tenants/{tenant_id}` include `products`.

### Principal

`Principal` gains `products: frozenset[str]`. `resolve_principal` fills it from a
per-process cache keyed by tenant id, the same shape as `tenant_environment`'s
`_ENV_CACHE`. The demo principal gets both. `POST /auth/login`, `GET /auth/me`,
`POST /auth/invite/redeem`, and `GET /bluebook/me` all return `products`.

### Enforcement

A second path table in `original/api.py` beside the staff-only one, checked in
`tenant_isolation` on every deploy (not only real deploys; the demo tenant holds both
products so the check is inert there):

```
_ORIGINAL_ONLY_EXACT    = {"/students", "/test/score"}
_ORIGINAL_ONLY_PREFIXES = ("/students/", "/baseline-requests", "/import/",
                           "/canvas/", "/submissions/", "/admin/", "/me/")
_BLUEBOOK_ONLY_PREFIXES = ("/bluebook/", "/proctor/")
```

If the principal's tenant lacks the product a path belongs to, the middleware returns
`403 {"detail": "This institution's plan does not include <Original|Bluebook>."}`.
Super roles (`operator`, `super_admin`) bypass it, as they bypass tenant scoping.

**Seal carve-out.** Exactly two exceptions to the Original table:
`POST /students/{id}/score` and `POST /students/{id}/baseline`, and only when the
principal has role `student` and `{id}` equals `principal.user_id`. That is the shape
of a Bluebook seal, which always runs under the student's own session. Staff in a
Bluebook-only tenant cannot reach any Original route.

Not gated by product: `/auth/*`, `/tenants/*`, `/health`, `/lti/*`, static files.

## Section 2 — Student accounts and login

### Where they live

Rows in `users` with `role = "student"`. No new column: a student row's `user_id` **is**
the derived student id (`tenant:hash`). So `Principal.user_id`, the session `sid`, the
Original profile key, and the account key are one string, and roster lookups are by
that id.

### Creation

`users.create_student_account(tenant_id, email, name) -> dict` inserts the row with the
sentinel `password_hash = "!invited"`. `verify_password` rejects it structurally (it
does not split into four `$`-separated parts), so an invited-but-unredeemed account
cannot log in. The helper also calls `set_display_name(student_id, name or local-part)`
so the roster shows a person, not a hash. Idempotent: an existing row is returned
unchanged.

New repository methods: `get_user(user_id)`, `set_user_password_hash(user_id, hash)`,
`list_users_by_ids(user_ids)` (roster hydration), on the protocol and both backends.

### Login

`POST /auth/login` stays the one login route. After `users.authenticate` succeeds:

- role `student` → `token = student_auth.mint_session(user_id, name)` (existing 7-day
  TTL), response `{token, role: "student", tenant_id, student_id, name, email, products}`.
- any other role → unchanged principal token, plus `products`.

The middleware resolves the student token exactly as it does a launch-link session, so
no isolation code changes. Throttling and audit logging are unchanged.

### Password change

`POST /auth/password` body `{current_password, new_password}`. Any authenticated
non-demo principal, staff or student. Re-verifies the current password against the
stored hash, requires the new one to be at least 8 characters, rewrites the hash,
audits `password_change`. 401 for demo or anonymous callers.

### Forgotten password

No email sending exists, so the reset path is a teacher reissuing an invite (Section 4).
Redeeming an invite always sets a fresh password.

### Constraints carried forward

- `users.email` is globally unique. One email cannot hold accounts at two institutions.
  Staff already live with this; kept for v1.
- The passwordless `/student-auth/login` demo path is untouched. It only
  auto-provisions demo tenants, and demo principals cannot read real data.

## Section 3 — Roster, invites, exam windows

### New tables

```
bluebook_enrollments
  course_id   TEXT NOT NULL
  student_id  TEXT NOT NULL
  tenant_id   TEXT NOT NULL
  created_at  TEXT NOT NULL
  PRIMARY KEY (course_id, student_id)
  INDEX (tenant_id, student_id)

bluebook_invites
  invite_id    TEXT PRIMARY KEY
  tenant_id    TEXT NOT NULL
  student_id   TEXT NOT NULL
  course_id    TEXT            -- nullable; enrolled on redemption when set
  token_hash   TEXT NOT NULL UNIQUE   -- sha256 of the token
  created_by   TEXT NOT NULL   -- staff user_id
  created_at   TEXT NOT NULL
  expires_at   TEXT NOT NULL   -- created_at + 14 days
  redeemed_at  TEXT            -- nullable; set once
  voided_at    TEXT            -- nullable; set when a newer invite is issued
  INDEX (student_id)
```

The token is `secrets.token_urlsafe(32)`. It appears only in the invite path handed to
the teacher; the database stores the hash, so a leaked database cannot mint logins.
Issuing an invite sets `voided_at` on every earlier unredeemed invite for the same
student. A redeem succeeds only when the hash matches, `expires_at` is in the future,
and both `redeemed_at` and `voided_at` are null.

### Exam columns

Three nullable columns on `bluebook_exams`: `course_id`, `opens_at`, `closes_at`
(ISO-8601 UTC text, as every other timestamp in the store). The free-text `course`
label stays for display and old clients. `POST /bluebook/exams` accepts all three.

Rules, implemented in one pure function `exam_state(exam, now) -> "draft" | "upcoming"
| "open" | "closed"`:

- `status == "DRAFT"` → `draft`. Never visible to students.
- `opens_at` set and `now < opens_at` → `upcoming`.
- `closes_at` set and `now >= closes_at` → `closed`.
- otherwise `open`. A null `opens_at` means open as soon as the exam leaves DRAFT; a
  null `closes_at` means it never auto-closes.

Starting a session is refused (409) unless state is `open`. When `closes_at` is set,
the session's effective duration is `min(duration, closes_at - now)`, so the pinned
deadline never passes `closes_at`. The existing `get_or_create_bluebook_session`
helper takes duration in seconds and needs no change.

### Submission text

One nullable `text` column on `bluebook_submissions`. `POST /bluebook/submissions`
accepts an optional `text` (capped at 200,000 characters). The client already holds
the text at seal time. Student history reads it from this column, so a Bluebook-only
tenant's data does not depend on Original's profile store. Rows sealed before this
change return `text: null`.

### DDL

One Alembic migration (`down_revision = "9f2c7a1b4d63"`) for Postgres: the `products`
column, the two tables, the four new columns. Matching guarded DDL in `store.py` for
SQLite, in the style of the existing `_sub_cols` PRAGMA-guarded ALTERs. New repository
methods on the protocol and both backends:

```
put_enrollment / delete_enrollment / list_enrollments_for_course / list_enrollments_for_student
put_invite / get_invite_by_hash / mark_invite_redeemed / void_invites_for_student / latest_invite_for_student
update_bluebook_exam(exam_id, fields)
list_bluebook_submissions_for_student(student_id)
get_bluebook_submission(submission_id)
```

## Section 4 — Routes

All new routes live in `original/routers/bluebook.py` and `original/routers/auth.py`,
using the existing `_require_staff`, `_require_student_session`, `_bluebook_tenant`,
and `_repo` helpers. Every student route derives the student from the principal and
never accepts a student id in the path.

### Teacher roster (staff, tenant-scoped, product `bluebook`)

| Route | Body | Behaviour |
|---|---|---|
| `POST /bluebook/courses/{course_id}/students` | `{students: [{email, name?}]}` (1–500) | For each: `create_student_account` if new, `put_enrollment`, issue invite. Returns `{students: [{student_id, email, name, invite_path, account: "created"\|"existing"}]}`. Covers single add and CSV paste. 404 if the course is not the caller's tenant's. |
| `GET /bluebook/courses/{course_id}/students` | — | Roster: `{student_id, email, name, state: "invited"\|"active", invite_expires_at}`. `active` means the password hash is not the sentinel. |
| `DELETE /bluebook/courses/{course_id}/students/{student_id}` | — | Unenroll. Account and history stay. |
| `POST /bluebook/courses/{course_id}/students/{student_id}/invite` | — | Reissue: voids earlier invites, returns a new `invite_path`. Doubles as password reset. |
| `PATCH /bluebook/exams/{exam_id}` | any of the create fields plus `course_id`, `opens_at`, `closes_at`, `status` | Partial update. `course_id` must belong to the tenant. Audited as `bluebook_exam_update`. |

`invite_path` is `/bluebook/?invite=<token>`. The client composes the absolute URL.

### Invite redemption (public, login-throttled)

`POST /auth/invite/redeem` body `{token, password}`. Validates the hash, expiry, and
single use; requires password length ≥ 8; sets the hash; marks `redeemed_at`; enrolls
in the invite's `course_id` when set (idempotent); audits `invite_redeem`; returns the
same payload as a student login so the dashboard opens immediately. Every failure is a
uniform 400 "This invite link is invalid, expired, or already used." to avoid
enumeration.

### Student dashboard (student principal, product `bluebook`)

| Route | Returns |
|---|---|
| `GET /bluebook/me` | `{student_id, name, email, tenant_id, products, courses: [{course_id, code, name, term}]}` |
| `GET /bluebook/me/exams` | Exams across enrollments where state is not `draft`: `{exam_id, title, course, course_id, duration, min_words, max_words, opens_at, closes_at, state, session: {started_at, deadline_at} \| null, submitted: bool}` |
| `POST /bluebook/me/exams/{exam_id}/start` | 404 if not enrolled or exam is draft; 409 unless `open`. Pins the deadline via `get_or_create_bluebook_session` with the clipped duration. Mints `mint_proctor_attestation(student_id, exam_id)`. Returns `BluebookSessionResponse` fields plus `proctor_token`. Audited as `bluebook_dashboard_start`. |
| `GET /bluebook/me/submissions` | Own rows: `{submission_id, exam_id, exam_title, course, word_count, time_min, status, late, created_at}`. Never includes `stylometric` or `ai_score`, whatever the tenant's products. |
| `GET /bluebook/me/submissions/{submission_id}` | The same row plus `text`. 404 if not the caller's. |

The returned `proctor_token` is used by the exam client exactly as the launch-link
attestation is today (`X-Proctor-Attestation` on the score and baseline calls), so a
dashboard-started sitting lands as `proctored`.

### Changed routes

- `POST /bluebook/submissions` accepts `text`.
- `GET /bluebook/submissions` and `GET /bluebook/exams` pass every record through
  `_shape_for_products(rec, products)`, which deletes `stylometric` and `ai_score` when
  the tenant lacks `original`. One helper, reused by any future list route.
- `POST /bluebook/exams` accepts `course_id`, `opens_at`, `closes_at`.

### Kept

Launch links (`GET /bluebook/launch`) and `scripts/roster_links.py` keep working
unchanged alongside accounts. A launch-link sitting and a dashboard sitting for the
same student and exam share one `bluebook_sessions` row.

## Section 5 — Canvas sidelining, frontend contract, testing, rollout

### Canvas

Backend routes for LTI (`/lti/*`) and Canvas import (`/canvas/*`, `/import/*`) stay
and their tests keep running. Removed: the "Import from Canvas" button and panel in
`demo/professor.html` (around lines 2429–2445 and the `toggleCanvasImport` /
`listCanvasSubmissions` / `importSelectedCanvas` functions from about 2636 on), and
the "Canvas LMS · LTI 1.3" integration tile in `demo/admin.html` (around line 475).
`docs/ARCHITECTURE.md` gets a note marking those route families sidelined for the
initial product. No env flag, no deletions.

### Frontend contract (not frontend work)

This spec delivers the backend. The two Bluebook dashboards are a separate spec and
plan. What this spec fixes so that work can start:

- Login responses and `/auth/me` carry `role` and `products`. The SPA routes
  `role === "student"` to a student shell and staff roles to the teacher shell, and
  hides score columns when `products` lacks `original`.
- A student arriving at `/bluebook/?invite=<token>` gets a set-password screen that
  calls `POST /auth/invite/redeem`.
- The exam screen sends `text` with the record call and uses the `proctor_token` from
  the start route exactly as it uses the launch-link one today.
- The teacher Students screen switches from "students who have sat an exam" to the
  roster route, with an add-students form that shows the returned invite links.

### Testing

Same conventions as `tests/test_bluebook_api.py`, `tests/test_staff_auth.py`, and
`tests/test_tenant_isolation.py`, split by concern:

- **Entitlement:** products default on migration and on `POST /tenants` without the
  field; `PATCH` validation; principal resolution and cache; 403 on every path in the
  Original table for a Bluebook-only tenant (parametrised over the table itself so a new
  Original route cannot be forgotten); seal carve-out allowed for own-id student, refused
  for other-id student and for staff; super-role bypass; demo tenant unaffected.
- **Accounts and invites:** sentinel hash cannot log in; redeem sets password and
  enrolls; second redeem fails; expired fails; reissue voids the old one; student login
  mints a session token that the middleware resolves to a `student` principal; password
  change round-trips; wrong current password is a 401.
- **Roster and windows:** enroll and unenroll; `exam_state` over every combination of
  null and set bounds; start refused when `upcoming` or `closed`; deadline clipped by
  `closes_at`; cross-tenant course id is a 404.
- **Student routes:** only own data; no score fields; text present for new rows, null
  for old ones; other student's submission id is a 404.
- **Shaping:** teacher list drops score fields only for Bluebook-only tenants.
- **Postgres:** `postgres`-marked tests for every new repository method, run locally
  through `make test-postgres` before pushing, since this touches the persistence layer.
- **Byte-identity:** a tenant with both products and none of the new columns set gets
  responses identical to today, so the existing OpenAPI and score snapshot tests hold.

Coverage: CI fails under 98% combined statement and branch coverage on `original/`,
with about 1.6 points of headroom. Every new branch above ships with a test.

### Rollout

1. Run the Alembic migration on Render before deploying the code. Column defaults keep
   the old code working on the new schema.
2. Deploy. Existing tenants change nothing.
3. Create new tenants with explicit `products`; upgrade a Bluebook-only tenant later
   with `PATCH /tenants/{id}`.

### Out of scope

Teacher feedback or grades on submissions, self-signup, email sending, per-tenant
unique emails, billing, the Bluebook dashboards themselves, and any change to
`bbook_client.py`.

## Amendment 2026-09-28 — public self-serve launch

The launch target is now a **public self-serve site, free at launch**. A two-sweep audit
of the live stack (plan: `~/.claude/plans/ok-what-stops-me-keen-zebra.md`) found the
blockers below. These decisions override the sections above wherever they conflict.

### Decisions

1. **Teacher self-signup.** `POST /auth/signup {email, password, name}` is public and
   login-throttled. It creates a tenant `t-<12 hex>` with `environment="production"`,
   `products=["bluebook"]`, `meta={"plan": "self_serve"}`, plus a `professor` user, and
   returns the staff login payload. Operator-provisioned tenants keep using
   `POST /tenants` and `/auth/register`.
2. **One workspace per teacher.** Colleagues at the same school do not share a tenant.
   Merging workspaces into a school tenant is an operator task, out of scope.
3. **Decision 1 is reversed for tenants without `original`.** They never feed Original.
   The seal carve-out in Section 1 applies only to tenants that hold `original`; for
   everyone else the product gate 403s every `/students/*` route, and the SPA skips the
   score and baseline calls. Submissions carry text, timing and warnings only. A school
   that later buys Original starts profiling from that point, without history.
4. **Free-tier caps**, per tenant, enforced in the create routes and returned as a 403
   with a plain message: 200 enrolled students, 50 exams, 500 submissions per calendar
   month. Operator tenants (`meta.plan != "self_serve"`) are uncapped.

### Launch blockers added to scope

- **Exam delivery.** Launch links carry only the exam title, so students are shown the
  built-in sample question. Every path (launch link, invite, dashboard start) now carries
  `exam_id`, and students load the exam from `GET /bluebook/me/exams/{exam_id}`.
  `roster_links.py` gains `--exam-id`.
- **Impersonation.** `POST /student-auth/login` returns 404 on real deploys, like
  `/api/v1/auth/login`. It issued a session for any email at any existing institution
  with no password.
- **Teacher-only lists.** `GET /bluebook/submissions` and `GET /bluebook/courses` require
  staff. Any signed-in student could list the institution's submissions and scores.
- **Warnings reach the server.** `POST /bluebook/submissions` accepts
  `warnings: [{type, at}]` (max 500), stored as JSON.
- **Teacher reads the work.** `GET /bluebook/submissions/{id}` (staff, tenant-owned)
  returns text and warnings. `GET /bluebook/exams/{id}/export.csv` exports one exam.
- **CRUD gaps.** `DELETE /bluebook/exams/{id}`, `PATCH` and `DELETE /bluebook/courses/{id}`.
  Deleting a course or exam that has submissions is a 409; archive it instead.
  List counts (`submissions` on exams, `students`/`exams` on courses) are computed, not 0.
- **Hardening on real deploys.** Uvicorn trusts proxy headers so the login throttle is
  per client, not site-wide. A request-body cap of 5 MB returns 413. `/docs`, `/redoc` and
  `/openapi.json` are off. `/health` omits student counts and the commit.
- **Operator teacher reset.** No email exists, so `POST /admin/users/{user_id}/reset-link`
  (guard token) issues a one-time set-password link for a teacher. It reuses the invite
  table with `course_id = NULL`.
