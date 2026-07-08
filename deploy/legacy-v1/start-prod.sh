#!/usr/bin/env bash
# start-prod.sh — Production startup for Original.
# Runs Alembic migrations then launches the full API on port 8000.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Original — Production Startup ==="
echo ""

# Require .env file
if [ ! -f ".env" ]; then
    echo "ERROR: .env file not found. Copy .env.dev to .env and edit values."
    echo "  cp .env.dev .env"
    exit 1
fi

# Install dependencies
echo "[1/3] Installing dependencies..."
pip install -r requirements.txt -q

# Run database migrations
echo "[2/3] Running database migrations..."
alembic upgrade head

# Start production server
PORT="${PORT:-8000}"
WORKERS="${WORKERS:-2}"
echo "[3/3] Starting production server on http://0.0.0.0:${PORT} (${WORKERS} workers)..."
echo ""
echo "  API docs: http://localhost:${PORT}/api/docs"
echo "  Health:   http://localhost:${PORT}/health"
echo ""

exec uvicorn original.main:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --workers "$WORKERS" \
    --log-level info
