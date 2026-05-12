# Original Web

Instructor-facing UI for the Original API: sign-in, student roster, writing-profile summary, and submission scoring.

## Prerequisites

- Backend running at **http://127.0.0.1:8000** (e.g. `docker compose up` from the repo root).
- At least one user (create with `docker compose exec api python -m original.cli create-admin`).

## Development

```bash
cd web
npm install
npm run dev
```

Open **http://localhost:5173**. API requests are proxied to the backend (see `vite.config.ts`), so you do not need to adjust CORS for local work.

## Production build

```bash
npm run build
```

Static files are emitted to `web/dist/`. Serve them behind the same host as the API, or configure your reverse proxy so `/api` routes to the FastAPI service.

## Environment

The UI uses **relative** URLs (`/api/v1/...`). For deployments where the API lives on another origin, set a build-time base URL and wire `fetch` accordingly (not required for the default Docker + Vite dev setup).
