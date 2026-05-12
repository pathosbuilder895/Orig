# Beta Phase 1 — Technical readiness

Phase 1 covers **session lifecycle**, **safe defaults for auth endpoints**, and **operational smoke checks** before a wider beta.

## Auth API

- **`POST /api/v1/auth/logout`** — Body: `{ "refresh_token": "<token>" }`. Revokes that refresh token (idempotent; unknown tokens still return 204).
- **`POST /api/v1/auth/logout-all`** — Requires `Authorization: Bearer <access_token>`. Revokes all refresh tokens for the signed-in user.
- Missing `Authorization` on protected routes returns **401** (not 403).

## Secrets and configuration

- Copy `.env.example` to `.env` and set at least **`SECRET_KEY`**, **`DATABASE_URL`**, and production **`ENVIRONMENT`**.
- Use a strong **`SECRET_KEY`** (see comment in `.env.example` for a one-liner generator).
- Document where keys live (e.g. Docker secrets, platform env vars) for whoever runs production.

## Backups

- **`deploy/backup.sh`** — Dumps PostgreSQL via `pg_dump`, gzips locally, optional S3 upload, retention pruning.
- Schedule with cron (example in script header). Point **`DB_CONTAINER`** at your Postgres container name if it differs from the default.

## Observability

- **`GET /health`** — Liveness (process up).
- **`GET /readiness`** — Readiness (includes DB check).
- **`GET /metrics`** — Prometheus metrics when enabled (`ENABLE_METRICS` in settings).

## Smoke script

From a machine that can reach the API:

```bash
BASE_URL=https://your-host ./scripts/smoke_beta.sh
```

With credentials:

```bash
BASE_URL=https://your-host SMOKE_EMAIL=... SMOKE_PASSWORD='...' ./scripts/smoke_beta.sh
```

## Tests

Run the suite (recommended: same Python version as `Dockerfile`, e.g. 3.11):

```bash
python -m pytest tests/ -q
```

CI may run the same command on push (see `.github/workflows/test.yml` if present).
