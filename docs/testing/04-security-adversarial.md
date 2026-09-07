# 04 — Security and adversarial tests

Scope: the live stack's auth model (`original/principal.py`,
`original/student_auth.py`, `routers/auth.py`, `routers/_shared.py`), tenant
isolation middleware (`api.py:262–336`), destructive guards
(`GUARD_DESTRUCTIVE` / `MAINTENANCE_TOKEN`), CORS/HSTS, LTI (`original/lti.py`),
imports (`routers/imports.py`), the demo static tree, and secrets handling.

The existing suite is *good at the happy path and the well-formed negative*:
`test_tenant_isolation.py`, `test_tenants_api_coverage.py`,
`test_pilot_lockdown.py` (36 tests, route-table driven),
`test_baseline_provenance_authz.py`, real RSA-signed LTI launches, a real
second-server lockout e2e. What it lacks is an **attacker**. The 2026-09-02
review found five holes by reading routes the way an attacker would. This
document turns that reading into a permanent suite.

Two documents to distrust while doing this: `docs/SECURITY_AUDIT.md` audits the
dormant v1 stack (its rate-limiting PASS is `slowapi` on `/api/v1/*`, which the
live stack never imports), and `docs/phase3-httpOnly-cookie-auth.md` describes
a removed design. `docs/SECURITY_REAUDIT_2026-07-09.md` is the live-stack one.

---

## 1. The abuse-case suite: `tests/security/`

New package, one file per attacker goal, every test written **red first**
against the current code. Mark the package `@pytest.mark.security` (§09) so it
can be run alone before go-live.

### 1.1 `test_cross_tenant_read.py` — "I am staff in B; show me A"

| Test | Setup | Assert |
|---|---|---|
| `test_pending_baseline_requests_scoped` | tenant A has pending requests with magic links; log in as B staff | `GET /baseline-requests/pending` returns zero A rows, and the response text contains no A email and no A link token |
| `test_students_listing_never_leaks_by_prefix` | tenant `demo` and tenant `demo2` | `/students` for `demo` staff contains no `demo2:` ids |
| `test_tenant_stats_scoped` | | `/tenants/{A}/stats` from B → 403, body has no counts |
| `test_data_inventory_scoped` | | `/students/{A-id}/data-inventory` from B → 403 |
| `test_sample_text_scoped` | | `/students/{A-id}/samples/0/text` from B → 403 |
| `test_admin_audit_scoped` | | `/admin/audit` from B contains no A rows |

The first row is a known hole (cross-tenant emails and live magic links). It
fails today.

### 1.2 `test_unauthenticated_writes.py` — "I have no token"

Route-table driven, in the style of
`test_no_admin_route_answers_a_student_principal`: for every route with method
in `{POST, PUT, PATCH, DELETE}`, send a syntactically valid body with **no**
principal and assert 401/403 under `ORIGINAL_ENV=pilot`. Maintain an explicit
allowlist of routes that are *meant* to be anonymous (`/auth/login`,
`/student-auth/login`, `/lti/login`, `/lti/launch`, `/health`,
`/proctor/*/beat`) with a one-line reason each. `POST /bluebook/submissions`
is a known hole and is not on the allowlist.

### 1.3 `test_id_minting.py` — "make the system create a flat id for me"

Turnitin CSV import mints flat (tenant-less) student ids, which then read as
legacy ids and bypass tenant checks. Tests: import a CSV as tenant-A staff;
every created id is `A:`-prefixed; a later anonymous `GET /students/{id}/…`
on each created id is refused. Pair with a `tenancy_shim` property test
(§02 §4) that a flat id never resolves to a pilot tenant.

### 1.4 `test_ssrf.py` — "make the server fetch my URL"

Canvas import accepts a body-supplied base URL. With `httpx.MockTransport`
recording every outbound request: URLs to `localhost`, `127.0.0.1`,
`169.254.169.254`, `file://`, and a private RFC-1918 range must be refused
before any request is made. Also assert a body-supplied URL never carries the
env-configured token (that test exists; move it here or cross-reference).

### 1.5 `test_static_tree.py` — "download the database"

Under `ORIGINAL_ENV=pilot` with `--frontend-dir demo`: `GET /seed.db`,
`/profiles.db`, `/.env`, `/bluebook/bluebook.bundle.js.map` return 404. Under
demo env the seed is allowed — assert that too, so the test documents the
policy rather than just the pilot arm. Build the forbidden list from a glob of
the repo (`*.db`, `*.sqlite*`, `.env*`) so a new database file is covered
automatically.

### 1.6 `test_destructive_guards.py`

- `DELETE /tenants/{id}/students` without `X-Guard-Token` → 403 when
  `GUARD_DESTRUCTIVE=1`; with a wrong token → 403; with the right token from a
  *student* principal → 403 (role and token are both required).
- `GUARD_DESTRUCTIVE=1` with a non-real `ORIGINAL_ENV` refuses to boot
  (REAUDIT follow-up #5 — unimplemented; test is red).
- `MAINTENANCE_TOKEN` login backdoor: succeeds only when the env var is set
  *and* `ORIGINAL_ENV` is real; logs an audit row naming the backdoor.

## 2. Auth matrix

One parametrised test, `tests/security/test_auth_matrix.py`, over
`roles × routes`. Roles: anonymous, student (own tenant), student (other
tenant), professor (own), professor (other), admin, operator, super_admin,
demo, tampered-token, expired-token. Routes: one representative per router.
The expected status lives in a committed table
(`tests/security/auth_matrix.yaml`), so a change to the policy is a reviewed
diff, not a surprise. The test fails if a route exists that is not in the
table — the route-table-driven guard again.

## 3. Transport-layer controls, in-process

- **CORS.** `TestClient` with `Origin: https://evil.example` → no
  `Access-Control-Allow-Origin` header; with an allowed origin → exact echo,
  never `*`. Today this is asserted only against a fake `get` in
  `test_o1_golive_check.py`.
- **HSTS.** Set `ENABLE_HSTS=1` *through the environment* and reload the
  module (the existing test monkeypatches the module global, which does not
  prove the env wiring).
- **Security headers.** `X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy` present on every response including 404s and 500s.
- **Login throttle.** Unit-level: 11th attempt within the window → 429 with
  the documented message; a success resets nothing (the bucket is
  attempt-keyed, not outcome-keyed — assert whichever the code does and name
  it). Add a test that the throttle keys on `X-Forwarded-For` when
  `TRUST_PROXY=1` — REAUDIT follow-up #1 says behind Render every client may
  share one IP; if the code does not support this yet, the test is red and
  the register carries it.
- **No rate limit on `/score`.** Write the test for the limit you want
  (e.g. 30/min per principal) and leave it red with a register entry. Do not
  fake it green.

## 4. LTI

Existing tests are strong (real RSA, nonce, state, unknown issuer). Add:

- **JWKS rotation.** Serve key set K1, launch; rotate to K2; a launch signed
  with K2 must succeed *without restart* (today `_JWKS_CACHE` has no TTL — red).
  A launch signed with a retired key must fail after rotation.
- **Replay.** Capture a valid `(id_token, state)` pair, launch twice. The
  second must be refused within the state TTL. If the product decision is to
  accept replay within 600 s, write the negative-space test saying so.
- **Algorithm pinning.** An `id_token` signed with `ES256` or `HS256` is
  refused even with a valid key. This is the reachability argument for the
  `pip-audit` ignore of PYSEC-2026-1325; it must be a test, not a comment.
- **Deployment binding.** A valid launch from issuer I with deployment D not
  registered under `LTI_PLATFORMS` → 403, and no principal is minted.

## 5. Secrets never leak

`tests/security/test_no_secret_leak.py`: set `SECRET_KEY`, `MAINTENANCE_TOKEN`,
`CANVAS_API_TOKEN`, `BBOOK_EXTERNAL_SECRET`, `SENDGRID_API_KEY` to unique
sentinels; drive every integration failure path (Canvas 502, Bbook timeout,
LTI bad signature, DB error) with `caplog` at DEBUG; assert no sentinel
appears in any log line, any response body, or `/health`. Also assert
`/health` and `/admin/health` never include env var names with values.

## 6. Dependency and supply chain

Already in CI: `pip-audit` on the pilot lockset (blocking, one documented
ignore), gitleaks. Add:

- `pip-audit` on `requirements-dev.lock.txt` as *non-blocking* (dev deps do not
  ship, but a compromised test dependency runs in CI with repo secrets).
- A test that the pilot lockset contains no package absent from
  `requirements.txt` at a different version (lockset drift; §08 §3 has the
  boot half of this).
- `npm audit --audit-level=high` for `demo/bluebook` and `app/`, non-blocking
  for one month, then blocking.

## 7. FERPA deletion as a security property

`delete_student` is documented as the manual FERPA path and was found to miss
four tables. The completeness test lives in `03-api-persistence.md` §2. Add
the *observable* half here: after deletion, every route that previously
returned the student returns 404, the audit log contains the terminal purge
row, and a re-created student with the same id starts from an empty baseline.

## 8. What stays manual

- Real Canvas instructor and student launches (`docs/PILOT_SMOKE_TEST.md`
  §C.2–3). Needs a real LMS. Keep on the checklist.
- Render proxy IP behaviour (REAUDIT #1). Observe in pilot logs; the test in
  §3 covers the code path once the answer is known.
- `MAINTENANCE_TOKEN` rotation cadence (REAUDIT #6). Ops, not test.

## 9. Acceptance for this slice

- `tests/security/` exists with the six abuse files and the auth matrix.
- All five review holes have a red test on the day the suite lands; the
  register tracks each to green.
- `pytest -m security` runs in under 60 s and is a named step in
  `docs/PILOT_SMOKE_TEST.md` §B.
