#!/usr/bin/env bash
# scripts/local_postgres.sh — Local Postgres 16 for the postgres-marked test suite.
#
# Mirrors CI's service container (.github/workflows/test.yml `services: postgres:`)
# exactly: image postgres:16, user/password/db original/original/original_test,
# port 5432. The postgres-marked tests (`-m postgres`) self-skip unless
# DATABASE_URL points at a reachable postgresql:// instance — this script is
# what makes them run for real locally instead of only in CI.
#
# Usage:
#   bash scripts/local_postgres.sh up       # create/start container, wait healthy
#   bash scripts/local_postgres.sh down     # stop container (data volume kept)
#   bash scripts/local_postgres.sh destroy  # remove container AND data volume
#   bash scripts/local_postgres.sh status   # container + reachability report
#   bash scripts/local_postgres.sh url      # print the shared DATABASE_URL
#   bash scripts/local_postgres.sh run -- <command> [args...]
#                                           # run <command> against its own
#                                           # throwaway database (see below)
#
# Typical test run (or just `make test-postgres`):
#   bash scripts/local_postgres.sh run -- .venv/bin/python -m pytest tests/ -m postgres -q
#
# Parallel worktrees share this one container, and tests that drop the live
# schema (tests/test_migration.py's fresh_pg) wipe the tables of any other run
# using the same database. `run` creates original_test_tmp_<pid>_<hex>, sets
# DATABASE_URL to it for <command>, and drops it when <command> exits (also on
# Ctrl-C or SIGTERM; only SIGKILL leaves one behind, safe to drop once the
# <pid> in its name has exited). If it cannot be created, <command> runs
# against the shared original_test with a warning. `url` still prints the
# shared database: a $(...) substitution ends before the tests start, so it
# cannot own a throwaway database's cleanup.

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
    run)
        shift
        [ "${1:-}" = "--" ] && shift
        [ $# -gt 0 ] || { echo "usage: $0 run -- <command> [args...]" >&2; exit 2; }
        scratch="original_test_tmp_$$_$(printf '%04x%04x' "$RANDOM" "$RANDOM")"
        if docker exec "$CONTAINER" createdb -U original "$scratch" >/dev/null; then
            # --force (Postgres 13+) ends connections a killed run left open.
            trap 'docker exec "$CONTAINER" dropdb -U original --force --if-exists "$scratch" >/dev/null \
                || echo "warning: could not drop throwaway database $scratch; drop it by hand" >&2' EXIT
            url="${DB_URL%/*}/${scratch}"
        else
            echo "warning: could not create a throwaway database; using the shared $DB_URL," \
                "where a parallel run can drop tables under this one" >&2
            url="$DB_URL"
        fi
        DATABASE_URL="$url" "$@"
        ;;
    *)
        echo "usage: $0 {up|down|destroy|status|url|run -- <command>}" >&2
        exit 2
        ;;
esac
