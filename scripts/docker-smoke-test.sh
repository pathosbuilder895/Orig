#!/usr/bin/env bash
# scripts/docker-smoke-test.sh — End-to-end Docker smoke test.
#
# Builds the image, starts the compose stack, runs API health + auth + scoring
# checks, then tears everything down.
#
# Usage:
#   bash scripts/docker-smoke-test.sh
#
# Prerequisites:
#   - Docker Engine + docker compose v2
#   - An .env.dev file (or set POSTGRES_PASSWORD / JWT_SECRET_KEY in env)
#
# Exit codes:
#   0 — all checks passed
#   1 — one or more checks failed (details printed to stderr)

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# ── Colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}✓${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1" >&2; FAILURES=$((FAILURES + 1)); }
info() { echo -e "${YELLOW}→${NC} $1"; }

FAILURES=0

# ── Config ───────────────────────────────────────────────────────────────────
COMPOSE_FILE="docker-compose.yml"
API_URL="http://localhost:8000"
MAX_WAIT=90       # seconds to wait for the API to become healthy
POLL_INTERVAL=3   # seconds between health polls

# Create a temporary .env if none exists (test mode only)
if [[ ! -f .env.dev && ! -f .env ]]; then
  info "No .env found — creating minimal .env for smoke test"
  cat > /tmp/original-smoke.env <<'EOF'
ENVIRONMENT=development
DATABASE_URL=postgresql://original:original@postgres:5432/original_db
REDIS_URL=redis://redis:6379/0
JWT_SECRET_KEY=smoke-test-secret-not-for-production
POSTGRES_PASSWORD=original
DEMO_MODE=true
EOF
  ENV_FLAG="--env-file /tmp/original-smoke.env"
else
  ENV_FLAG=""
fi

# ── Build ─────────────────────────────────────────────────────────────────────
info "Building Docker image..."
docker compose -f "$COMPOSE_FILE" $ENV_FLAG build --quiet
pass "Image built"

# ── Start stack ───────────────────────────────────────────────────────────────
info "Starting compose stack..."
docker compose -f "$COMPOSE_FILE" $ENV_FLAG up -d
trap 'info "Tearing down stack..."; docker compose -f "$COMPOSE_FILE" down -v --remove-orphans 2>/dev/null' EXIT

# ── Wait for API ──────────────────────────────────────────────────────────────
info "Waiting for API to become healthy (up to ${MAX_WAIT}s)..."
elapsed=0
until curl -sf "${API_URL}/health" > /dev/null 2>&1; do
  if [[ $elapsed -ge $MAX_WAIT ]]; then
    fail "API did not become healthy within ${MAX_WAIT}s"
    docker compose -f "$COMPOSE_FILE" logs api | tail -40
    exit 1
  fi
  sleep "$POLL_INTERVAL"
  elapsed=$((elapsed + POLL_INTERVAL))
done
pass "API healthy after ${elapsed}s"

# ── Health endpoints ──────────────────────────────────────────────────────────
info "Checking /health..."
HEALTH=$(curl -sf "${API_URL}/health")
if echo "$HEALTH" | grep -q '"status":"ok"'; then
  pass "/health returns ok"
else
  fail "/health unexpected response: $HEALTH"
fi

info "Checking /readiness..."
READY=$(curl -sf "${API_URL}/readiness")
if echo "$READY" | grep -q '"status":"ready"'; then
  pass "/readiness returns ready"
else
  fail "/readiness unexpected response: $READY"
fi

# ── API docs redirect ─────────────────────────────────────────────────────────
info "Checking / redirects to /api/docs..."
REDIRECT_LOC=$(curl -si "${API_URL}/" | grep -i "^location:" | tr -d '\r' | awk '{print $2}')
if [[ "$REDIRECT_LOC" == *"/api/docs"* ]]; then
  pass "/ redirects to /api/docs"
else
  fail "/ redirect unexpected: $REDIRECT_LOC"
fi

# ── Auth flow ─────────────────────────────────────────────────────────────────
info "Attempting login with demo credentials..."
LOGIN=$(curl -sf -X POST "${API_URL}/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"instructor@demo.edu","password":"Instructor123!"}' || true)

if echo "$LOGIN" | grep -q '"access_token"'; then
  pass "Login succeeded"
  ACCESS_TOKEN=$(echo "$LOGIN" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
else
  fail "Login failed: $LOGIN"
  ACCESS_TOKEN=""
fi

# ── Students endpoint (requires auth) ─────────────────────────────────────────
if [[ -n "$ACCESS_TOKEN" ]]; then
  info "Listing students (authenticated)..."
  STUDENTS=$(curl -sf "${API_URL}/api/v1/students/" \
    -H "Authorization: Bearer $ACCESS_TOKEN" || true)
  if echo "$STUDENTS" | grep -q '"items"'; then
    pass "Students list returned"
  else
    fail "Students list unexpected: $STUDENTS"
  fi
fi

# ── Metrics endpoint ──────────────────────────────────────────────────────────
info "Checking Prometheus /metrics..."
METRICS=$(curl -sf "${API_URL}/metrics" || true)
if echo "$METRICS" | grep -q "http_requests_total"; then
  pass "/metrics endpoint available"
else
  # Metrics may require auth or may not be exposed on port 8000
  info "/metrics not available on port 8000 (may be internal-only) — skipping"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
if [[ $FAILURES -eq 0 ]]; then
  echo -e "${GREEN}All Docker smoke tests passed.${NC}"
  exit 0
else
  echo -e "${RED}${FAILURES} smoke test(s) failed. See above for details.${NC}"
  exit 1
fi
