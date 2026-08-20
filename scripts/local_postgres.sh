#!/usr/bin/env bash
# scripts/local_postgres.sh — Local Postgres 16 for the postgres-marked test suite.
#
# Mirrors CI's service container (.github/workflows/test.yml `services: postgres:`)
# exactly: image postgres:16, user/password/db original/original/original_test,
# port 5432. The 166 postgres-marked tests (`-m postgres`) self-skip unless
# DATABASE_URL points at a reachable postgresql:// instance — this script is
# what makes them run for real locally instead of only in CI.
#
# Usage:
#   bash scripts/local_postgres.sh up       # create/start container, wait healthy
#   bash scripts/local_postgres.sh down     # stop container (data volume kept)
#   bash scripts/local_postgres.sh destroy  # remove container AND data volume
#   bash scripts/local_postgres.sh status   # container + reachability report
#   bash scripts/local_postgres.sh url      # print the DATABASE_URL to export
#
# Typical test run (or just `make test-postgres`):
#   DATABASE_URL=$(bash scripts/local_postgres.sh url) \
#     .venv/bin/python -m pytest tests/ -m postgres -q

set -euo pipefail

CONTAINER=original-postgres
VOLUME=original-postgres-data
IMAGE=postgres:16
PORT=5432
# Same credentials as CI's service container — test-only, never a real secret.
DB_URL="postgresql://original:original@localhost:${PORT}/original_test"

die() { echo "error: $1" >&2; exit 1; }

container_exists() { docker inspect "$CONTAINER" >/dev/null 2>&1; }
container_running() { [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" = "true" ]; }

wait_ready() {
    # pg_isready inside the container avoids needing psql on the host.
    for _ in $(seq 1 30); do
        if docker exec "$CONTAINER" pg_isready -U original -d original_test >/dev/null 2>&1; then
            echo "postgres ready: $DB_URL"
            return 0
        fi
        sleep 1
    done
    die "container is up but Postgres never became ready (docker logs $CONTAINER)"
}

case "${1:-}" in
    up)
        command -v docker >/dev/null 2>&1 || die "docker not found — install Docker Desktop"
        docker info >/dev/null 2>&1 || die "docker daemon not running — start Docker Desktop"
        if container_running; then
            echo "container $CONTAINER already running"
        elif container_exists; then
            docker start "$CONTAINER" >/dev/null
        else
            docker run -d --name "$CONTAINER" \
                -e POSTGRES_USER=original \
                -e POSTGRES_PASSWORD=original \
                -e POSTGRES_DB=original_test \
                -p "${PORT}:5432" \
                -v "${VOLUME}:/var/lib/postgresql/data" \
                --health-cmd "pg_isready -U original" \
                --health-interval 5s --health-timeout 5s --health-retries 10 \
                "$IMAGE" >/dev/null
        fi
        wait_ready
        ;;
    down)
        container_exists && docker stop "$CONTAINER" >/dev/null && echo "stopped $CONTAINER (volume $VOLUME kept)" || echo "container $CONTAINER not found"
        ;;
    destroy)
        container_exists && docker rm -f "$CONTAINER" >/dev/null || true
        docker volume rm "$VOLUME" >/dev/null 2>&1 || true
        echo "removed $CONTAINER and $VOLUME"
        ;;
    status)
        if container_running; then
            echo "container: running ($(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo 'no healthcheck'))"
            docker exec "$CONTAINER" pg_isready -U original -d original_test || true
        elif container_exists; then
            echo "container: stopped (start with: bash scripts/local_postgres.sh up)"
        else
            echo "container: absent (create with: bash scripts/local_postgres.sh up)"
        fi
        ;;
    url)
        echo "$DB_URL"
        ;;
    *)
        echo "usage: $0 {up|down|destroy|status|url}" >&2
        exit 2
        ;;
esac
