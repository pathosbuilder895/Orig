#!/usr/bin/env bash
# start.sh — One-command demo launcher for Original.
# Seeds 5 synthetic student profiles and starts the demo on port 8001.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON="$SCRIPT_DIR/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    echo "No .venv found. Create one first:" >&2
    echo "  python3.11 -m venv .venv && .venv/bin/pip install -r requirements-demo.txt" >&2
    exit 1
fi

echo "=== Original — Authorship Verification Demo ==="
echo ""

# Install Python dependencies (demo mode only needs the SQLite-backed set --
# not the full production requirements.txt, which pulls PyTorch).
echo "[1/3] Installing Python dependencies..."
"$PYTHON" -m pip install -r requirements-demo.txt -q

# Download spaCy language model if not already present
echo "[2/3] Checking spaCy language model..."
"$PYTHON" -c "import spacy; spacy.load('en_core_web_sm')" 2>/dev/null || \
    "$PYTHON" -m spacy download en_core_web_sm -q

echo "[3/3] Starting demo server on http://localhost:8001 ..."
echo ""
echo "  Professor dashboard: http://localhost:8001/professor.html"
echo "  Student dashboard:   http://localhost:8001/student.html"
echo "  Onboarding:          http://localhost:8001/onboard.html"
echo "  Bluebook exam room:  http://localhost:8001/bluebook/"
echo ""

exec "$PYTHON" run.py --demo --frontend-dir demo --port 8001
