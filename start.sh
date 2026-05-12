#!/usr/bin/env bash
# start.sh — One-command demo launcher for Original.
# Seeds 5 synthetic student profiles and starts the demo on port 8001.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Original — Authorship Verification Demo ==="
echo ""

# Install Python dependencies
echo "[1/3] Installing Python dependencies..."
pip install -r requirements.txt -q

# Download spaCy language model if not already present
echo "[2/3] Checking spaCy language model..."
python3 -c "import spacy; spacy.load('en_core_web_sm')" 2>/dev/null || \
    python3 -m spacy download en_core_web_sm -q

echo "[3/3] Starting demo server on http://localhost:8001 ..."
echo ""
echo "  Professor dashboard: http://localhost:8001/professor.html"
echo "  Student dashboard:   http://localhost:8001/student.html"
echo "  Onboarding:          http://localhost:8001/onboard.html"
echo ""

exec python3 run.py --demo --frontend-dir demo --port 8001
