# Architecture Map — which surface is live

One page to prevent the recurring confusion: this repo contains **two backends
and three frontend generations**. Exactly one of each is live.

## ✅ LIVE — the pilot stack (what professors use)

```
Browser ── demo/*.html  (Oxford-themed dashboards: professor/admin/operator/student)
       ── demo/bluebook/ (secure-exam app; serve index.prod.html in production)
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

## 🧊 DORMANT — the v1 stack (future Postgres path, ADR-004 Route B)

```
frontend/*.html  ←  v1's own UI (own login/dashboards — NOT served anywhere)
original/main.py + original/api/ (v1 package)
  • SQLAlchemy/Postgres/Alembic; own auth (api/v1/auth.py, core/security.py)
  • own LTI: original/canvas/lti.py → routes /canvas/lti/*   ← the OTHER LTI
```

⚠️ The duplicated LTI stack has already caused one real incident: the Canvas
one-pager once documented `/canvas/lti/*` (v1's routes) instead of `/lti/*`
(the pilot's). When touching anything LTI/auth, check which stack you're in.

## 🪦 ABANDONED

- `web/` — React/TSX/PostCSS rewrite attempt; superseded by `demo/`. Not served, not maintained.
- `legacy_mvp/`, `variantexam/` — gitignored local artifacts.
- `deploy/` — pre-Render VPS provisioning (nginx/systemd). The chosen path is Render (`render.yaml` + `docs/OPS_RUNBOOK.md`); see the banner in `deploy/DEPLOY.md`.

## Rules of thumb

1. If it isn't reachable from `run.py --demo` or `render.yaml`, professors never see it.
2. New pilot features go in `original/api.py` + `demo/` — not the v1 package — until the ADR-004 migration decision is made.
3. There are two of several things (LTI, auth, schemas). Grep both before assuming.
