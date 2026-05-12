#!/bin/sh
# docker-entrypoint.sh — run migrations then start the API server.
#
# Runs `alembic upgrade head` before starting uvicorn so that every
# container restart is always in sync with the current schema.
# Alembic is idempotent — if the database is already up to date it
# simply exits cleanly.
#
# Environment variables expected:
#   DATABASE_URL  — SQLAlchemy connection string (set in docker-compose / k8s)

set -e

echo "[entrypoint] Running Alembic migrations..."
python -m alembic upgrade head
echo "[entrypoint] Migrations complete."

echo "[entrypoint] Starting Original API..."
# uvicorn expects lowercase level names; app settings may use DEBUG/INFO uppercase.
UVICORN_LOG_LEVEL=$(printf '%s' "${LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')
exec uvicorn original.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "${UVICORN_WORKERS:-1}" \
    --log-level "${UVICORN_LOG_LEVEL}"
