# ADR-003: Multi-Institution Readiness Without Losing the Demo

**Status:** Accepted — Phase 1 implemented 2026-06-15; Phase 1.5 implemented 2026-06-16
**Date:** 2026-06-04
**Deciders:** Product owner (Andrew) · whoever signs off on the first university pilot

> **Implementation note (2026-05-17 audit).** Phase 1 and Phase 1.5 are shipped.
> Phase 1 action item #5 ("migrate SQLite → Postgres") was explicitly superseded
> by **ADR-004 (Accepted)**, which adopts hardened SQLite for the pilot and
> documents the Postgres path as a fast-follow. The Phase 1 CI gate (cross-tenant
> isolation, `tests/test_tenant_isolation.py`) passes 8/8. Phase 2 items are
> long-term GA work and explicitly NOT a precondition for accepting Phase 1.

## Context

The dashboards (professor / admin / operator / student) are visually production-grade, but the
backend is still in **demo posture**:

- **No authentication.** `original/api.py` only guards 4 destructive endpoints via a shared
  `MAINTENANCE_TOKEN` (`_require_guard`, default off). Scoring, baselines, reads, and corrections
  are fully open.
- **No tenant isolation.** The `{tenant_id}:{local_id}` convention is a *filter*
  (`list_students(tenant_id="")`), not a boundary. Any caller can read another school's students
  by guessing IDs → a cross-tenant **FERPA breach**.
- **Demo-grade persistence.** SQLite + in-memory caches; the `baseline_requests` registry is
  in-memory (lost on restart). `SECRET_KEY` is unset → JWTs die every restart.
- **Frontend hardwired** to `localhost:8001/8000`.

**The constraint that shapes everything:** the zero-login, seeded demo is the **primary sales
asset** shown to universities. It must keep working, anytime, with no login. We are adding security
*around* it, not replacing it.

**Decisions locked in (from stakeholder Q&A):**
1. Demo stays an **always-live, zero-login** experience.
2. Auth target is **email/password + LTI 1.3/SSO** — but a real pilot is **weeks away**.
3. Isolation model: **one shared Postgres, enforced per-tenant scoping**.
4. Timeline driver: **a specific university pilot, weeks away.**

> ⚠️ **Tension to resolve:** "both auth methods at launch" vs. "pilot in weeks." Building LTI 1.3
> *and* email/password before the pilot misses the date. This ADR phases them: **email/password for
> the pilot, LTI as an immediate fast-follow, both for GA.**

## Decision

Adopt **Option A — "Demo-as-Tenant" with an additive authorization layer.** One codebase, one
deployment, one database. The demo becomes a permanent reserved tenant (`demo`) that is the *only*
tenant allowed anonymous, read-mostly access. Every other tenant requires authentication and is
strictly scoped server-side.

The change is **additive and backward-compatible** — the existing demo endpoints keep working
because the demo tenant is explicitly exempted, not deleted.

### Core mechanism: a `Principal` + tenant-scoped repository

```
Request → resolve_principal()  →  Principal { user_id, role, tenant_id, auth_method }
                                       │
                                       ▼
                         tenant-scoped repository (every query/write
                         is scoped to principal.tenant_id; the client
                         never supplies a cross-tenant student_id)
```

- `resolve_principal()` is a FastAPI dependency on **every** data endpoint:
  - **Authenticated** (JWT or LTI launch) → real `{user, role, tenant_id}`.
  - **Anonymous + demo origin** → synthetic principal `{role: <from UI>, tenant_id: "demo"}`.
  - **Anything else** → `401`.
- The server **constructs** the full `student_id` as `f"{principal.tenant_id}:{local_id}"`. It
  never trusts a client-supplied namespaced ID. This converts the naming convention into an
  enforced boundary with near-zero churn to existing code paths.
- **Demo tenant guardrails** (so an open demo can't be abused or leak):
  - Scoped to `demo:` only; destructive ops blocked for anonymous principals.
  - Hard per-IP rate limits + write caps; demo data periodically reset to seed.
  - **No real PII ever** in the demo tenant.

### Phased delivery (resolves the timeline tension)

- **Phase 1 — Pilot-ready (the weeks-away date):** `Principal` + tenant scoping, **email/password
  + stable JWT**, demo tenant carved out, Postgres, HTTPS + locked CORS, `GUARD_DESTRUCTIVE=1`.
- **Phase 1.5 — LTI 1.3 fast-follow:** add an LTI launch that mints the same `Principal`
  (reuse your Bbook LTI experience). "Both auth methods" is now satisfied without blocking the pilot.
- **Phase 2 — Multi-institution GA:** self-serve onboarding, FERPA program, per-tenant
  observability/quotas, background job queue, persistent `baseline_requests`.

## Options Considered

### Option A: Demo-as-Tenant, additive auth (one app, shared DB) — **CHOSEN**
| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium — one `Principal` dependency + scoped repo; demo carve-out |
| Cost | Low — single deployment + one Postgres |
| Scalability | High — add schools = add rows, no new infra |
| Team familiarity | High — same FastAPI app, reuses SECRET_KEY/JWT + tenant registry already present |
| Demo safety | Demo always reflects latest build; one code path to maintain |

**Pros:** Demo never drifts from prod; smallest diff to existing endpoints; cheapest to run;
the dangerous "no-auth" code path stops existing for real tenants (it only survives as the
sandboxed demo tenant).
**Cons:** A scoping bug is a cross-tenant risk → requires disciplined tests; shared DB is a single
blast radius (mitigated by backups + row-level scoping + tests).

### Option B: Two deployments — keep demo instance as-is, new authed prod instance
| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium-High — two deploy targets, two configs, drift management |
| Cost | Medium — duplicate infra |
| Scalability | Medium |
| Team familiarity | High |
| Demo safety | Demo drifts from prod; double maintenance |

**Pros:** Hard physical isolation of demo from real data; demo can't possibly touch prod DB.
**Cons:** Demo silently rots behind prod (every feature must be shipped twice); the unauthenticated
codebase lives on indefinitely as a liability; more ops surface for a solo/small team.

### Option C: Rip-and-replace — auth everywhere, demo gets a shared login
| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium |
| Cost | Low |
| Scalability | High |
| Team familiarity | High |
| Demo safety | **Breaks the zero-login sales asset** |

**Pros:** Simplest security story (everything authed).
**Cons:** Directly violates the locked decision (always-live zero-login demo). Adds login friction
to every pitch. **Rejected.**

## Trade-off Analysis

The decisive forces are **(1) protect the sales motion** (always-live demo) and **(2) hit a
weeks-away pilot** with real student data under FERPA.

- B and C each sacrifice one of those (B rots the demo; C frictions it). Only **A keeps the demo
  pristine *and* concentrates the security work in one reusable layer** (`Principal` + scoped repo)
  that every endpoint already needs.
- Shared-DB scoping (chosen isolation) pairs naturally with A: `tenant_id` is derived from the
  authenticated session, never the client, so the demo carve-out is just "tenant_id = demo, role
  from UI, writes sandboxed."
- The auth tension is a *sequencing* problem, not an architecture problem: email/password and LTI
  both terminate in the **same `Principal`**, so doing them in two steps costs nothing structurally.

## Consequences

**Easier:**
- Onboarding a new school = create a tenant row + invite an admin. No new infra.
- The demo is guaranteed current (one build) and safe (sandboxed tenant, no PII).
- Security reviews have one choke point (`resolve_principal` + the scoped repo) to audit.

**Harder / must-do:**
- Every data endpoint must go through the scoping layer — needs **cross-tenant isolation tests**
  as a permanent CI gate (e.g., "tenant A token cannot read tenant B student → 403/404").
- Migrate SQLite → Postgres with a real migration + backups before the pilot.
- Frontend needs a configurable API base + a real login screen (index.html exists) with a
  "Jump into demo" path that targets the demo tenant.

**Revisit later:**
- If a buyer demands physical DB isolation, A can graduate a tenant to its own schema/DB without a
  rewrite (the repo already abstracts access).
- Per-tenant model calibration (the honest "AUC 0.68 · Limited" badge) before scores drive grading.

## Action Items

**Phase 1 — Pilot-ready (target: the weeks-away date)**
1. [x] Add `resolve_principal()` dependency → `{user_id, role, tenant_id, auth_method}`. — `original/principal.py`
2. [x] Introduce a tenant-scoped repository; server constructs `student_id` from `principal.tenant_id` (reject client-supplied cross-tenant IDs). — `original/api.py`, `original/store.py`
3. [x] Carve out the reserved **`demo`** tenant: anonymous + read-mostly + role-from-UI + write sandbox + destructive ops blocked + hard rate limit + periodic reset. — `scripts/reset_demo_data.py`, demo-tenant rules in `principal.py`
4. [x] Email/password auth + **stable `SECRET_KEY`** (env/secret manager); JWT sessions. — `original/auth/`, login throttle in `original/api.py`
5. [~] Migrate SQLite → Postgres; real migrations + automated backups. **Superseded by ADR-004 (Accepted): hardened SQLite for the pilot, Postgres documented as fast-follow.** Automated backups shipped (`deploy/backup.sh`, `scripts/backup_db.sh`).
6. [x] Frontend: configurable `API_BASE`; wire `index.html` login; "Jump into demo" → demo tenant. — `demo/index.html`, `demo/*.html` (`API_BASE` derived per page)
7. [x] HTTPS; CORS locked to known origins; `GUARD_DESTRUCTIVE=1` in prod. — Render pilot config, smoke test §A checks HSTS + CORS + `GUARD_DESTRUCTIVE` runtime flag in `original/api.py`
8. [x] **CI gate:** cross-tenant isolation test suite (A-cannot-read-B). — `tests/test_tenant_isolation.py` (8 tests passing); reinforced by `tests/test_voice_leak.py::test_student_cannot_probe_other_tenant_existence` (2026-05-17)

**Phase 1.5 — LTI 1.3 fast-follow (right after pilot)**
9. [x] LTI 1.3 launch → mints the same `Principal` (reuse Bbook LTI patterns). "Both methods" satisfied. — `original/lti.py`, `tests/test_lti.py`, `docs/CANVAS_RUNBOOK.md` + `docs/canvas_developer_key.md`

**Phase 2 — Multi-institution GA** (long-term; not gating Phase 1 acceptance)
10. [ ] Self-serve tenant onboarding + admin invites (builds on `/tenants` + onboard.html).
11. [x] Persist `baseline_requests` — `original/baseline_requests.py` + `original/store.py` (SQLite write-through with hydration, 2026-06-18). Background job queue for bulk import / re-scoring still pending.
12. [ ] FERPA program (DPAs, retention/erasure, audit-log immutability + access controls). DPA template and student disclosure shipped; audit-log immutability still pending.
13. [ ] Per-tenant observability, quotas, usage dashboards (extend operator.html).
14. [ ] Per-tenant threshold calibration before scores inform grading; appeals/human-in-the-loop policy.
