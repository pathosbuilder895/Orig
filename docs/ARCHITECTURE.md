# Architecture Map — which surface is live

One page to prevent the recurring confusion: this repo contains **two
backends**. Exactly one is live. (It used to contain three frontend
generations; the dead `frontend/` and `web/` trees were removed 2026-07-07
(ADR-006) — see git history.)

## ✅ LIVE — the pilot stack (what professors use)

```
Browser ── demo/*.html  (Oxford-themed dashboards: professor/admin/operator/student)
       ── demo/bluebook/ (secure-exam app; index.html, same file dev + prod — React bundled in, no CDN)
            │
            ▼
original/api.py  ←──── THE pilot backend ("legacy demo app", 1 file)
  • loaded by run.py --demo via importlib path-hack (its name is shadowed
    by the original/api/ package below)
  • SQLite via original/store.py (WAL) — no ORM, no Postgres
  • auth: original/users.py + original/principal.py (tenant isolation)
  • LTI 1.3: original/lti.py  →  routes /lti/login /lti/launch /lti/jwks
  • hardening: ORIGINAL_ENV=pilot (see .env.example, render.yaml)
```

Deployed per `render.yaml` (`original-demo` free sandbox, `original-pilot`
paid + disk). Ops: `docs/OPS_RUNBOOK.md`. Canvas: `docs/CANVAS_RUNBOOK.md`.

### The repository seam ([ADR-002](adr/002-data-layer-convergence.md), [ADR-006](adr/006-postgres-convergence.md))

`original/repository.py` defines a `Repository` protocol — every persistence
operation the live API needs, backend-agnostic. `api.py` depends on
`Repository` (via `get_repository(environment)`), never on `original/store.py`
directly. Today the only implementation is `SqliteRepository`, delegating to
`store.py`; a `PostgresRepository` plugs into the same seam once ADR-006's
Postgres convergence lands, without the API layer changing. The seam started
as a 9-method slice covering just the Formation feature; WS-6 Phase P1
widened it to cover essentially every public `store.*` function, so this is
now load-bearing for the whole app, not an optional abstraction — a new
feature that calls `store` directly instead of going through `Repository`
reopens exactly the two-backends-diverge problem ADR-002 exists to prevent.

## 🧊 DORMANT — the v1 stack (future Postgres path, ADR-004 Route B)

```
(v1's own UI, frontend/*.html, was removed 2026-07-07 (ADR-006); see git history)
original/main.py + original/api/ (v1 package)
  • SQLAlchemy/Postgres/Alembic; own auth (api/v1/auth.py, core/security.py)
  • own LTI: original/canvas/lti.py → routes /canvas/lti/*   ← the OTHER LTI
```

⚠️ The duplicated LTI stack has already caused one real incident: the Canvas
one-pager once documented `/canvas/lti/*` (v1's routes) instead of `/lti/*`
(the pilot's). When touching anything LTI/auth, check which stack you're in.

⚠️ **A second, narrower trap: the live `/canvas/baseline/*` routes share a URL
prefix with the dormant `original/canvas/` package.** `original/api.py` (live)
registers `POST /canvas/baseline/{student_id}/list-canvas-submissions` and
`POST /canvas/baseline/{student_id}/import-baseline` — demo-grade Canvas
submission-import stubs on the live pilot backend. These have nothing to do
with `original/canvas/lti.py`'s dormant `/canvas/lti/*` routes above, but the
shared `/canvas` prefix invites exactly the same mistake as the
`original/api.py` vs `original/api/` module-shadowing trap this doc exists to
warn about: seeing a `/canvas/...` path is not enough to tell which stack
you're in. Check which *file* defines the route (`original/api.py` vs
`original/canvas/`), not just the URL prefix.

## 🪦 ABANDONED

- `frontend/`, `web/` — dead frontend trees (v1's HTML UI; a React/TSX rewrite attempt superseded by `demo/`). Removed 2026-07-07 (ADR-006); see git history.
- `legacy_mvp/`, `variantexam/` — gitignored local artifacts.
- `deploy/` — pre-Render VPS provisioning (nginx/systemd). The chosen path is Render (`render.yaml` + `docs/OPS_RUNBOOK.md`); see the banner in `deploy/DEPLOY.md`. The v1 container/deploy artifacts (`Dockerfile`, `docker-compose*.yml`, `docker-entrypoint.sh`, `start-prod.sh`, `fly.toml`) were quarantined to `deploy/legacy-v1/` (audit B15); only `Dockerfile.demo` remains at the repo root.

## Rules of thumb

1. If it isn't reachable from `run.py --demo` or `render.yaml`, professors never see it.
2. New pilot features go in `original/api.py` + `demo/` — not the v1 package — until the ADR-004 migration decision is made.
3. There are two of several things (LTI, auth, schemas). Grep both before assuming.
