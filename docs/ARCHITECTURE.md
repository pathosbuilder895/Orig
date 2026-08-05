# Architecture Map — which surface is live

One page to prevent the recurring confusion. This repo used to contain **two
backends** (a live pilot stack and a dormant v1/Postgres stack); the v1 stack
was deleted in WS-6 P6 (PR #90) — see the "DELETED" section below and git
history. It also used to contain three frontend generations; the dead
`frontend/` and `web/` trees were removed 2026-07-07 (ADR-006) — see git
history.

## ✅ LIVE — the pilot stack (what professors use)

```
Browser ── demo/*.html  (Oxford-themed dashboards: professor/admin/operator/student)
       ── demo/bluebook/ (secure-exam app; index.html, same file dev + prod — React bundled in, no CDN)
            │
            ▼
original/api.py  ←──── app assembly only (FastAPI instance, lifespan,
  │                     middleware, CORS/security-header setup, route
  │                     splicing) — imported plainly by run.py, no importlib
  │                     hack (that existed only to dodge the now-deleted
  │                     original/api/ package's name collision)
  ▼
original/routers/*.py  ←── the actual route handlers, one module per domain:
  admin, auth, bluebook, health, imports, lti_routes, me, proctor, students,
  students_baseline, students_scoring, tenants (+ shared helpers in _shared.py)
  • persistence: original/repository.py seam — original/store.py (SQLite,
    WAL) is the default backend; original/postgres_repository.py is a full
    Postgres implementation, opt-in only via REPO_BACKEND/REPO_SHADOW (see
    docs/OPS_RUNBOOK.md cutover procedure) — production stays SQLite unless
    an operator flips that switch
  • auth: original/users.py + original/principal.py (tenant isolation)
  • LTI 1.3: original/lti.py  →  routes /lti/login /lti/launch /lti/jwks
  • hardening: ORIGINAL_ENV=pilot (see .env.example, render.yaml)
```

Deployed per `render.yaml` (`original-demo` free sandbox, `original-pilot`
paid + disk). Ops: `docs/OPS_RUNBOOK.md`. Canvas: `docs/CANVAS_RUNBOOK.md`.

## 🪦 DELETED — the v1 stack

`original/main.py`, `original/api/` (the v1 package, including its own
`api/v1/auth.py`/`core/security.py` auth and its own LTI at
`original/canvas/lti.py` → `/canvas/lti/*`) and its ~62 tests were deleted in
WS-6 P6 (PR #90, "decommission & unlock") — see git history, not the working
tree. The router split above (`original/routers/`) is unrelated later work
(WS-7.3) that happened to land in the same file `original/api/` used to
shadow.

**Not everything under the old v1 paths is gone.** `original/db/` (SQLAlchemy
models/session for the Postgres path) and `original/core/` (`config.py`,
`logging.py`, `security.py`) still exist and are in normal lint/ruff scope
(PR #96). Two things keep them alive:
- `original/postgres_repository.py` (the live repository seam's Postgres
  backend, see above) uses the SQLAlchemy models in `original/db/`.
- `original/cli/delete_student.py` (the documented, live manual FERPA-deletion
  CLI — see `README.md`/`SETUP.md`/`docs/data_inventory.md`) and
  `original/cli/security_audit.py` import `original/core/config.py` and
  `original/core/logging.py`, and `delete_student.py` additionally imports
  `original/db/models` + `original/db/session`. PR #96 found these two CLIs
  are real, live dependents — not v1 leftovers — and deleted only what had
  zero importers (`db/models/canvas.py`, `core/config_patch.py`,
  `core/exceptions.py`, `core/limiter.py`).

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
2. New pilot features go in `original/routers/` (or a new router module) + `demo/` — the v1 package is gone, there's nowhere else for them to go.
3. LTI, auth, and schemas are each single-surface now (`original/lti.py`, `original/users.py`+`principal.py`, `original/schemas.py`) — the "grep both, which stack am I in" hazard was v1-era and no longer applies. The persistence seam is the one place two backends still coexist by design (SQLite default, Postgres opt-in) — see `original/repository.py`.
