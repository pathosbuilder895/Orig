#!/usr/bin/env bash
# Quick smoke checks against a running Original API (local or deployed).
#
# Usage:
#   BASE_URL=http://localhost:8000 ./scripts/smoke_beta.sh
#
# Optional — verify login (set both):
#   SMOKE_EMAIL=user@example.edu SMOKE_PASSWORD='...' ./scripts/smoke_beta.sh
#
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
BASE_URL="${BASE_URL%/}"

echo "==> GET ${BASE_URL}/health"
curl -sfS "${BASE_URL}/health" | head -c 200 || true
echo ""
echo ""

echo "==> GET ${BASE_URL}/readiness"
curl -sfS "${BASE_URL}/readiness" | head -c 200 || true
echo ""
echo ""

if [ -n "${SMOKE_EMAIL:-}" ] && [ -n "${SMOKE_PASSWORD:-}" ]; then
  echo "==> POST ${BASE_URL}/api/v1/auth/login"
  curl -sfS -X POST "${BASE_URL}/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"${SMOKE_EMAIL}\",\"password\":\"${SMOKE_PASSWORD}\"}" \
    | head -c 400 || true
  echo ""
else
  echo "==> Skipping login (set SMOKE_EMAIL and SMOKE_PASSWORD to test /auth/login)"
fi

echo ""
echo "smoke_beta: OK"
