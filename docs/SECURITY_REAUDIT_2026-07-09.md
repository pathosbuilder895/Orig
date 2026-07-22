# Security Re-Audit — Live Stack (2026-07-09)

**Date:** 2026-07-09
**Conducted by:** Engineering (self-audit)
**Classification:** Confidential — Internal Use Only
**Scope:** `original/api.py` (the live pilot backend), `original/principal.py`,
`original/store.py`, `original/users.py`, `original/student_auth.py` — auth
throttle, `MAINTENANCE_TOKEN`/`GUARD_DESTRUCTIVE` guard, tenant isolation,
CORS fail-closed behavior.

This report replaces `docs/SECURITY_AUDIT.md` for the live stack. That report
audited the dormant v1 backend (`original/api/`, JWT/SQLAlchemy/nginx) and its
"SECURE for pilot deployment" verdict does not apply to what `original-pilot`
actually runs. This is the deferred re-audit referenced there and in
`docs/AUDIT_2026-07-06.md` (D4) and `docs/OPS_RUNBOOK.md`.

> **Live-editing caveat.** `original/api.py` was under active edit in a
> separate working session while this audit was written. Line numbers below
> were correct at the moment each section was read but **will drift** as
> that edit continues — one region of the file (roughly the admin/calibration
> block preceding the demo-login backdoor, §2b) had already shifted by ~14
> lines between two passes of this same audit. **Treat function/endpoint
> names as the stable reference and line numbers as a secondary pointer only**
> — re-grep the name before trusting a cited line number.

---

## Summary

| Area | Verdict | Notes |
|---|---|---|
| Login throttle | ✅ Adequate, one unverified dependency | Sliding-window per-IP, in-memory, 10 attempts/300s default. Correctness hinges on `request.client.host` being the real client IP — not verified here (§1). |
| `MAINTENANCE_TOKEN` guard | ✅ Guard function itself is sound | `_require_guard` fails closed on missing secret, constant-time compare, confirmed to be the literal first statement in all six of its call sites. ⚠️ Two doc/code mismatches found against `docs/OPS_RUNBOOK.md`'s endpoint list (§2a). Demo-login backdoor dual-role gap confirmed live but inert on `original-pilot` today (§2b). |
| Tenant isolation | ✅ Student-scoped paths are solid / ⚠️ registry routes are not | `{tenant_id}:{local_id}` is enforced as a real per-request check (`assert_student_access`) for every `/students/{id}...` path, not just a naming convention — confirmed by direct code read plus a passing CI gate. **New finding:** the `/tenants/*` registry routes have no equivalent per-request tenant-ownership check (§3). |
| CORS fail-closed | ✅ Confirmed by code | `_resolve_allowed_origins()` returns `[]` on real deploys when `ALLOWED_ORIGINS` is unset, and hard-fails startup if an operator sets `*` on a real deploy. Verified by reading the function, not assumed from CLAUDE.md's table. |

---

## 1. Login throttle (`/auth/login`)

**Mechanism** (`original/api.py`, `_throttle_login`): an in-memory
`dict[ip -> [monotonic timestamps]]` (`_login_attempts`, module-level global).
On each `POST /auth/login`, `_throttle_login()` runs *before* any credential
check, prunes timestamps outside a `_LOGIN_WINDOW_SEC` window (**default
300s**) and rejects with `429` if the remaining count is
`>= _LOGIN_MAX_ATTEMPTS` (**default 10**). The dict is capped: if it grows
past 10,000 distinct IPs it is cleared wholesale — a crude but bounded
defense against unbounded memory growth from address churn.

Both bounds are overridable via `LOGIN_THROTTLE_WINDOW_SEC` /
`LOGIN_THROTTLE_MAX_ATTEMPTS` env vars. In-code comment states this override
exists for the CI e2e job only (verified: `.github/workflows/test.yml` sets
`LOGIN_THROTTLE_MAX_ATTEMPTS: "500"` for that job); pilot/production get the
hardcoded defaults unless an operator deliberately overrides them.

**What it protects against:** online password guessing against
`/auth/login`. Combined with PBKDF2-HMAC-SHA256 at 240,000 iterations
(`original/users.py:26`, confirmed, ~100ms/verify) and account-enumeration
mitigation (a well-formed dummy hash is verified against on unknown email so
timing doesn't distinguish "no such user" from "wrong password",
`users.py:70-76`, confirmed), 10 attempts / 5 minutes per IP makes online
brute force against a single attacker IP impractical.

**Gaps:**

- **IP attribution is unverified against the actual deploy topology.**
  `_throttle_login` keys on `request.client.host` with no `X-Forwarded-For` /
  `Forwarded` header handling anywhere in `api.py` or `run.py`. If Render's
  edge/load balancer terminates TLS and forwards to the app as a reverse
  proxy, `request.client.host` could be Render's internal proxy address for
  *every* request rather than the real requester's IP — which would either
  (a) bucket all real users under one shared counter (self-inflicted lockout
  risk for a busy campus), or (b) behave as intended if the socket passes
  through unmodified. **This audit could not confirm which case applies from
  the code alone** — it depends on Render's networking model for this
  service, which isn't documented in `render.yaml` or `docs/OPS_RUNBOOK.md`.
  **Needs an empirical follow-up** (log `request.client.host` for a few real
  requests against `original-pilot`); if it's a shared proxy IP, switch to
  trusting the first hop of `X-Forwarded-For` from Render's edge only.
- **Single-process-only, by design** — already tracked as finding A4 in
  `docs/AUDIT_2026-07-06.md` (`_login_attempts` is one of the 18 process-local
  globals listed there). `run.py` calls `uvicorn.run(...)` with no
  `--workers`/`workers=` argument, i.e. single-worker by default, so the
  invariant currently holds — but it is not *enforced* anywhere (no
  assertion, no `render.yaml` comment), so a future change to add workers
  would silently divide the effective throttle N-ways with nothing to catch
  it. Not re-litigating A4 here; cross-referencing it as the reason this
  isn't a standalone finding.
- **IP-only, not account-scoped** — a distributed low-and-slow attack (many
  source IPs, one target account) is not rate-limited at all. Acceptable for
  the current pilot threat model (a small number of institutional staff
  logins, not a public signup surface) but worth naming explicitly rather
  than leaving implicit.
- **The demo-login backdoor (`/api/v1/auth/login`, §2b below) has no
  throttle of its own** — it is a separate code path from `/auth/login` and
  does not call `_throttle_login`. It is only reachable when
  `ORIGINAL_ENV` is not `pilot`/`staging`/`production` (404s otherwise), but
  if `MAINTENANCE_TOKEN` were ever set on such a deployment, the backdoor
  password would be brute-forceable at unlimited rate. See §2b for scope.

**Verdict: adequate for pilot scale**, contingent on the IP-attribution
question above being resolved empirically rather than assumed from the code.

---

## 2. `MAINTENANCE_TOKEN` / `GUARD_DESTRUCTIVE` guard

Two independent effects share one env var, as documented in
`docs/OPS_RUNBOOK.md` §"Destructive-endpoint guard." This audit verified both
against current code and found the guard mechanism itself sound, but two
places where the *endpoint list* in the runbook no longer matches the code.

### 2a. Destructive-endpoint guard (`_require_guard`)

- No-ops immediately when `GUARD_DESTRUCTIVE` is unset/`0` (demo default).
- When `GUARD_DESTRUCTIVE=1`: if `_MAINTENANCE_TOKEN` (read once at import
  from the `MAINTENANCE_TOKEN` env var) is empty, every guarded call returns
  **503** — fails closed on misconfiguration rather than silently opening.
  If set, it compares the `X-Guard-Token` header against it with
  `hmac.compare_digest`, the correct constant-time comparison for a
  secret-bearing header.
- **Confirmed by direct read (not docstring grep) — `_require_guard(request)`
  is the literal first statement of every one of its six call sites:**
  `auth_register` (`POST /auth/register` — staff provisioning),
  `delete_student` (`DELETE /students/{id}`),
  `create_tenant` (`POST /tenants`),
  `delete_tenant_students` (`DELETE /tenants/{tenant_id}/students`),
  `list_all_baseline_requests` (`GET /baseline-requests`), and
  `admin_apply_thresholds` (`POST /admin/calibration/runs/{run_id}/apply`).
  There is no code path in any of these six handlers that reaches
  persistence or an audit log before the guard check runs.

**Two mismatches against `docs/OPS_RUNBOOK.md`'s endpoint list**, found by
cross-referencing the runbook's five named categories ("student deletion,
tenant writes, calibration-threshold apply, baseline-request list, admin
corrections") against the six actual call sites above:

1. **"Admin corrections" is not guarded by `_require_guard` at all.**
   `POST /submissions/{submission_id}/correct` (`submit_correction`) —
   the handler the runbook's "admin corrections" almost certainly refers to
   — calls `_require_staff(request)` followed by
   `principal_mod.assert_student_access(principal, owner_id)`, never
   `_require_guard`. This is arguably a *better* control for this specific
   endpoint (it's role- **and** tenant-scoped, where the guard token is
   neither — see §3), but it means the runbook's claim that corrections sit
   behind the `X-Guard-Token` is **not what the code does**. A reader relying
   on the runbook to reason about who can submit a correction on a demo
   deployment (`GUARD_DESTRUCTIVE=0`) would wrongly conclude it's wide open
   when in fact staff-role + tenant checks still apply in real-deploy mode
   via the middleware and `_require_staff`.
2. **`POST /auth/register` (staff provisioning) *is* guarded by
   `_require_guard` but is absent from the runbook's list.** Provisioning a
   new professor/admin/operator account is at least as sensitive as the five
   named categories — arguably more so, since it's a privilege-*creation*
   endpoint — and its protection is undocumented.

- `render.yaml` sets `GUARD_DESTRUCTIVE=1` on `original-pilot` per the
  runbook; not independently re-verified against the live Render dashboard
  in this pass (out of scope for a code-only read), but the repo's
  `render.yaml` file matches this claim as checked into git.

**Verdict: the guard function has no logic gap** (fails closed, constant-time
compare, correct default posture). **Fix:** update
`docs/OPS_RUNBOOK.md`'s endpoint list to (a) drop "admin corrections" or
reframe it as "staff-role + tenant-scoped, not guard-token-scoped," and (b)
add `POST /auth/register` to the guarded list.

### 2b. Demo-login backdoor dual-role (`/api/v1/auth/login`, handler `demo_login`)

Confirmed live in code: `demo_login` accepts `MAINTENANCE_TOKEN` as a
password and grants `role: "admin"` with a warning-level audit log entry
(`_audit_maintenance_access`), reusing the exact same env var as the guard
token. The runbook already flags this as a known dual-role issue and
recommends treating the token as sensitive everywhere, not just where the
guard is active.

**Confirmed disable path:** `demo_login` opens with

```python
if _IS_REAL_DEPLOY:
    raise HTTPException(status_code=404, detail="Not found")
```

and `_IS_REAL_DEPLOY = ORIGINAL_ENV in ("pilot", "staging", "production")`.
So on `original-pilot` (which `render.yaml` sets `ORIGINAL_ENV=pilot` for),
this endpoint 404s and the token cannot be used as a login backdoor there.
Also confirmed: the token this endpoint mints (`"maintenance-token"` /
`"demo-token"`, literal strings) is **not** a signed principal token or
student session — `principal.resolve_principal()` would reject it
immediately (`verify_principal_token` requires a `.` separator the literal
string doesn't have), so even on a deployment where this path is reachable,
its output cannot be replayed against the real tenant-isolation system. The
backdoor's only live effect is what it does inline (return a decorative
`{token, role, name}` payload for the demo dashboard's own client-side
routing) — it does not mint anything the rest of the app trusts.

**Residual gap, confirmed not fully closed:** the backdoor is live on *any*
deployment where `ORIGINAL_ENV` is not one of `pilot`/`staging`/`production`
— e.g. a `demo`-labeled service that someone sets `MAINTENANCE_TOKEN` on for
some other reason, or a future staging environment spun up with
`ORIGINAL_ENV` left at its `demo` default by mistake. The gate is a single
string-match env var with no independent check that guard-mode and
backdoor-mode can't both be misconfigured into being simultaneously live.
There is no code-level assertion that `GUARD_DESTRUCTIVE=1` and a
non-real-deploy `ORIGINAL_ENV` are never both true at once — a configuration
that would put a strong-looking guard token in front of destructive
endpoints while the *same* value also works as this endpoint's admin
password (and, per §1, with no throttle on this specific login path).

**Verdict: gap found, but scoped and already known to operations.** This
audit confirms the runbook's characterization is accurate against current
code and that `original-pilot` itself is not exposed today. **Fix:**
consider a startup assertion refusing to boot if `GUARD_DESTRUCTIVE=1` and
`_IS_REAL_DEPLOY` is false simultaneously (a configuration that should never
happen and currently isn't prevented); turn the runbook's standing "rotate
`MAINTENANCE_TOKEN`" note into a tracked, dated task.

---

## 3. Tenant isolation

**Enforcement path for student-scoped data:** `original/principal.py`
resolves a `Principal` per request (`resolve_principal`) from, in priority
order: a signed principal token (professor/admin/operator, HMAC-SHA256 over
`SECRET_KEY`), a student session token (`student_auth.verify_session`), or an
anonymous demo fallback. The tenant-isolation middleware in `api.py`
(`tenant_isolation`) calls this once per request and:

1. Blocks staff-only paths for demo/student principals **on real deploys
   only** (`_is_staff_only_path`, covering the `/admin/`, `/tenants/`,
   `/baseline-requests/`, `/import/`, `/submissions/` prefixes and four exact
   paths — `/students`, `/tenants`, `/baseline-requests`, `/test/score`).
2. Enforces per-student scoping via `assert_student_access` **unconditionally
   (in both demo and real-deploy mode)**, wherever `extract_scoped_id` finds
   a student id in the path — which only recognizes `/students/{id}/...` and
   `/canvas/baseline/{id}/...`.

`assert_student_access`, read directly:
- Demo/anonymous principals may only touch flat ids, the `demo:` namespace,
  or tenants explicitly registered with `environment="demo"`
  (`tenant_environment()`, cached, fails closed to `None`/deny on any
  repository lookup error). Real tenant data is invisible to anonymous
  callers.
- `operator`/`super_admin` roles bypass tenant scoping by design
  (`SUPER_ROLES`).
- Students may only touch their own `student_id`, never their whole tenant —
  a deliberate anti-horizontal-authorization measure called out in the code
  comments (a logged-in student cannot read a classmate's profile via
  `GET /students/<sameTenant:other>`).
- Staff (professor/admin) may only touch their own `tenant_id` prefix
  (`t == principal.tenant_id`, an **exact string comparison**, not a
  SQL `LIKE`/wildcard match).

**No SQL-wildcard or ID-collision injection found in the prefix scheme
itself:**
- `store.list_ids_for_tenant()` and `store.delete_tenant_students()` use
  Python `str.startswith()` against the in-memory `_STORE` dict keys — an
  exact prefix check, not a SQL pattern, so `%`/`_` in a `tenant_id` cannot
  widen the match.
- `store.tenant_stats()` *does* run a SQL `LIKE` query (for aggregate counts
  from `submission_manifests`) and explicitly escapes `%`, `_`, and `\` via
  `_escape_like()` before building the pattern, with a code comment
  documenting exactly the wildcard-widening scenario this audit was asked to
  check for (`'sem_a'` must not match `'semXa:...'`). This is already fixed,
  not a live gap.
- The tenant portion of every student id that the *login* paths actually
  create is always passed through `student_auth.slugify()`
  (`re.sub(r"[^a-z0-9]+", "-", ...)`) before being used as a prefix — for
  both the email/institution login path and the LTI launch path (which calls
  `derive_student_id(tenant, email)`, and `derive_student_id` slugifies
  internally). A colon or SQL-metacharacter embedded in an institution name
  or LTI platform config cannot produce a student id whose tenant-prefix
  collides with a different tenant's slug, because slugify strips everything
  outside `[a-z0-9-]`.
- The one place a tenant identifier is stored **without** going through
  `slugify()` is the tenant *registry* record itself (`POST /tenants`,
  `create_tenant` — validates only that `tenant_id` is non-empty and ≤80
  chars, no charset restriction). A registry `tenant_id` containing a colon
  or other unusual character doesn't collide with real student-id prefixes
  (which are always slugified), it simply fails to match any of them —
  `tenant_environment(slug)` returns `None` for an unregistered/mismatched
  slug, which is the fail-closed (deny) branch. Low-severity inconsistency,
  not an exploitable boundary crossing.

**New finding — tenant-registry routes have no per-request
tenant-ownership check (unlike `/students/{id}`) — Medium/High.**

`extract_scoped_id()` only recognizes `/students/...` and
`/canvas/baseline/...` paths. It does **not** recognize `/tenants/{tenant_id}`
paths, so `assert_student_access` (the actual tenant-boundary check) is
**never invoked** for any `/tenants/*` route. The only gate on these routes
is the middleware's coarse staff-only check (blocks anonymous/student
principals on real deploys, but does not check that the caller's own
`tenant_id` matches the tenant in the URL) plus, for two of them,
`_require_guard`'s shared `X-Guard-Token`.

Verified concretely, on a real deploy (`ORIGINAL_ENV=pilot`):

- `GET /tenants` (list all registered institutions), `GET /tenants/{id}`
  (single tenant record, including its `meta` dict), and
  `GET /tenants/{id}/stats` (student/submission counts, action breakdown,
  last-active timestamp) require only *a* valid staff principal token — a
  professor's own token for **their own institution** is sufficient to read
  **every other institution's** registry metadata and aggregate stats. No
  `_require_guard` call on any of these three (they're GETs, not in the
  guarded set). This is cross-tenant information disclosure — institution
  names, environment labels, arbitrary `meta` (which the endpoint's own
  docstring says may include "contact email, LMS URL"), and per-tenant
  activity volume — though not individual student records or raw submission
  text.
- `DELETE /tenants/{tenant_id}/students` (bulk-purge every student in a
  tenant, `delete_tenant_students`) **is** behind `_require_guard`, so on
  `original-pilot`'s actual configuration (`GUARD_DESTRUCTIVE=1`) it also
  requires the `X-Guard-Token`. But that guard token check is the *only*
  tenant-related gate — the handler never compares the caller principal's
  `tenant_id` to the `tenant_id` path parameter. Contrast with single-student
  deletion (`DELETE /students/{id}`), which is protected by **both**
  `_require_guard` **and** the middleware's unconditional
  `assert_student_access` call (because `/students/{id}` *is* recognized by
  `extract_scoped_id`). The bulk-tenant path is missing the second layer.
  Practically: whoever holds the `X-Guard-Token` (intended as an
  operator-only secret, not distributed to institutional staff, per
  `docs/OPS_RUNBOOK.md`) can wipe **any** tenant's entire roster with no
  additional check that they're an authorized operator for that specific
  tenant — there is no such role (e.g. no "admin-of-Institution-B-only")
  distinct from "holds the one shared token." If `GUARD_DESTRUCTIVE` is ever
  left at `0` on a deployment that holds real tenant data (a misconfiguration
  the CORS/SECRET_KEY checks don't catch — see §4's note on `ORIGINAL_ENV`
  being a single point of failure for several protections at once), this
  becomes reachable by **any** authenticated staff principal of **any**
  tenant, full stop.

This gap was not exercised by `tests/test_tenant_isolation.py` (the
permanent CI gate) or the three new authz test files
(`test_baseline_provenance_authz.py`, `test_correction_authz.py`,
`test_magic_launch.py`) — all of which target `/students/...` or
`/submissions/.../correct`, never `/tenants/{id}`, `/tenants/{id}/stats`, or
`/tenants/{id}/students`. There is currently no automated regression coverage
that would catch this gap being reintroduced or widened.

**Fix:**
1. Add a tenant-ownership check to `delete_tenant_students` and
   `get_tenant`/`tenant_stats`: reject (403) when the calling principal is
   staff (not `SUPER_ROLES`) and `principal.tenant_id != tenant_id`, mirroring
   `assert_student_access`'s existing logic. The simplest implementation is
   to extend `extract_scoped_id()` to also recognize `/tenants/{id}` and let
   the existing middleware call handle it uniformly, rather than adding
   per-handler checks.
2. Add CI coverage: a cross-tenant professor hitting
   `GET /tenants/{other}/stats` and `DELETE /tenants/{other}/students` should
   403, the same shape as the existing `test_cross_tenant_professor_denied`
   test for `/students/{id}`.
3. Until fixed, treat `MAINTENANCE_TOKEN`/`X-Guard-Token` distribution as the
   only thing standing between any one guard-token holder and every tenant's
   data — consistent with, and reinforcing, `docs/OPS_RUNBOOK.md`'s existing
   "treat the value as sensitive everywhere" guidance.

**Other observations (no gap):**
- `resolve_principal`'s demo fallback trusts an `x-demo-role` request header
  to pick the anonymous principal's role, defaulting to `operator`. This is
  safe *only* because `is_demo=True` is unconditionally set on that branch
  and every real-deploy check tests `is_demo` before role
  (`_require_staff`, the staff-only-path middleware check, and
  `assert_student_access`'s demo branch all gate on `is_demo` first) —
  confirmed by reading all three call sites; a client cannot use this header
  to escalate past the demo sandbox.
- `tenant_environment()`'s `_ENV_CACHE` is an in-process, no-TTL cache — the
  same single-process caveat as A4 in `docs/AUDIT_2026-07-06.md`, not a new
  authorization gap on its own.

**Verdict: secure for every `/students/{id}...`-shaped path** (real,
per-request enforcement, not a naming convention, with direct CI coverage).
**Gap found in the `/tenants/*` registry surface**, scoped as above — Medium
for the read endpoints (institutional metadata disclosure), High-in-effect
for the bulk-delete endpoint if the guard token's distribution or
`GUARD_DESTRUCTIVE`/`ORIGINAL_ENV` configuration is ever looser than the
current documented pilot setup assumes.

---

## 4. CORS fail-closed behavior

Read `_resolve_allowed_origins()` directly, not just the CLAUDE.md flag-table
claim:

```python
def _resolve_allowed_origins():
    raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if raw:
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        if _IS_REAL_DEPLOY and "*" in origins:
            raise RuntimeError(...)   # refuses to boot
        return origins
    if _IS_REAL_DEPLOY:
        return []   # locked down: no origin allowed until configured
    return ["*"]
```

Confirmed:
- **`ALLOWED_ORIGINS` unset on a real deploy → `[]`**, passed straight into
  `CORSMiddleware(allow_origins=[])`. An empty allow-list means the
  middleware never adds `Access-Control-Allow-Origin` for any
  browser-originated cross-origin request — every such request is blocked
  client-side by the browser, not by the server refusing to process it (CORS
  is fundamentally a browser-enforced control: the server still returns a
  response, the browser just won't hand it to page JS without a matching
  header). Same-origin requests and non-browser clients (server-to-server,
  `curl`, LTI POSTs from an LMS backend) are **not** subject to CORS at all —
  expected, universal CORS behavior, not a gap specific to this app.
- **Operator sets `ALLOWED_ORIGINS=*` on a real deploy → hard boot failure**
  (`RuntimeError`), preventing the exact misconfiguration that would
  silently reopen the hole the empty-default closes. This is a
  fail-fast-at-startup control, stronger than a runtime check.
- **Demo (`_IS_REAL_DEPLOY` false) with `ALLOWED_ORIGINS` unset → `["*"]`** —
  intentionally permissive for the zero-login sales sandbox, consistent with
  CLAUDE.md's documented default and `render.yaml`'s `original-demo` service
  (which sets no `ALLOWED_ORIGINS`).

**Verdict: confirmed fail-closed**, independently re-derived from the
function body, not assumed from documentation. No gap found.

**One structural note, not a CORS-specific gap:** the entire fail-closed
story here — and the `SECRET_KEY` fail-fast in `lifespan`, and the guard's
own posture — all key off a single env var, `ORIGINAL_ENV`, being explicitly
set to `pilot`/`staging`/`production` on any deployment that holds real
tenant data. If an operator stands up a real-data deployment and leaves
`ORIGINAL_ENV` at its `demo` default (or never sets it), the app does not
refuse to boot — it silently reverts to CORS `*`, no `SECRET_KEY`
requirement (just a log warning), and the staff-only path middleware check
in §3 disabled entirely. This single-flag concentration of risk is already
named in CLAUDE.md ("the confusing dual `ORIGINAL_ENV`/`ENVIRONMENT`" pair,
WS-7 pending) and in `docs/AUDIT_2026-07-06.md` F3; not re-scored here, but
worth stating plainly: CORS, secret-key stability, and the tenant-isolation
middleware's staff gate all currently share one point of failure.

---

## Cross-references, not re-litigated here

- `docs/AUDIT_2026-07-06.md` A4 (process-local singletons) covers the
  single-worker assumption that both the login throttle and the
  `_ENV_CACHE` tenant-environment cache depend on.
- `docs/AUDIT_2026-07-06.md` A1 (persistence layer swallows write/load
  failures) is orthogonal to auth/authz and out of scope here.
- `docs/AUDIT_2026-07-06.md` F3 documents the `ORIGINAL_ENV`/`ENVIRONMENT`
  naming confusion referenced in §4.
- `docs/OPS_RUNBOOK.md` §"Destructive-endpoint guard" is the operational
  source of truth for `MAINTENANCE_TOKEN` rotation procedure; this audit
  verified its technical claims against code (§2) and found two mismatches
  to fix, but did not restate rotation steps.

## Open follow-ups from this audit

1. Verify empirically whether `request.client.host` reflects the real client
   IP on Render for `original-pilot`, or a shared proxy address (§1).
2. ~~Confirm `_require_guard(request)` is literally the first statement in
   each guarded handler.~~ **Done in this pass** — confirmed for all six
   call sites (§2a).
3. Update `docs/OPS_RUNBOOK.md`'s guarded-endpoint list: remove or reframe
   "admin corrections" (actually `_require_staff` + tenant-scoped, not
   guard-token-scoped) and add `POST /auth/register` (§2a).
4. Add a tenant-ownership check to the `/tenants/*` registry routes
   (`get_tenant`, `tenant_stats`, `delete_tenant_students`) and matching CI
   coverage — currently the only live gap in tenant isolation (§3).
5. Consider a startup assertion refusing `GUARD_DESTRUCTIVE=1` combined with
   a non-real-deploy `ORIGINAL_ENV` (§2b).
6. Turn the runbook's standing "rotate `MAINTENANCE_TOKEN`" action item into
   a tracked, dated task with an owner (§2b).
