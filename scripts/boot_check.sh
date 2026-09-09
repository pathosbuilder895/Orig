#!/usr/bin/env bash
#
# boot_check.sh — boot the product the way Render boots it, and classify.
#
# The one check in this repo that installs a *lockset* into a venv and runs
# `python run.py` against it. Everything else runs in a dev venv that has every
# dependency, which is exactly why REPO_BACKEND=postgres could brick the pilot
# deploy (T-07) with a green suite.
#
# Usage:
#   scripts/boot_check.sh <expect> <today> [gap] \
#       [--log-fragment TEXT] [--port N] [--timeout SEC] \
#       -- [KEY=VAL ...] [--no-skip-seed]
#
# Known-red semantics (same as Phase A):
#   expect = the outcome we WANT (what a fixed product does)
#   today  = the outcome observed on this branch
#   The check PASSES when observed == today and FAILS when it does not, so a
#   cell flips red the day the product changes in either direction. Fixing the
#   underlying gap means editing `today` in the same PR.
#   When today != expect a `::warning::` names the gap-register id.
#
# Outcomes:
#   up      /health answered 200 within the timeout
#   refuse  the process exited non-zero AND its log contains --log-fragment
#           (a deliberate, named refusal — not a crash)
#   down    anything else that is not up (crash, hang, silent exit)
#
# A `refuse` on either side of the comparison REQUIRES --log-fragment: without
# it "refused on purpose" and "fell over" are the same observation, and a
# refusal test that cannot tell them apart cannot fail for the right reason.

set -euo pipefail

usage() {
    sed -n '3,30p' "$0" >&2
    exit 2
}

# ── Arguments ────────────────────────────────────────────────────────────────
[ $# -ge 3 ] || usage

EXPECT="$1"; shift
TODAY="$1"; shift

GAP=""
case "${1:-}" in
    --*|"") ;;
    *) GAP="$1"; shift ;;
esac

LOG_FRAGMENT=""
PORT="8001"
TIMEOUT="30"

while [ $# -gt 0 ]; do
    case "$1" in
        --log-fragment) LOG_FRAGMENT="${2:-}"; shift 2 ;;
        --port)         PORT="${2:-}"; shift 2 ;;
        --timeout)      TIMEOUT="${2:-}"; shift 2 ;;
        --)             shift; break ;;
        *)              echo "boot_check: unknown option '$1'" >&2; usage ;;
    esac
done

SKIP_SEED=1
ENV_ASSIGNMENTS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --no-skip-seed) SKIP_SEED=0 ;;
        *=*)            ENV_ASSIGNMENTS+=("$1") ;;
        "")             ;;  # an empty `env:` matrix field expands to nothing
        *)              echo "boot_check: expected KEY=VAL or --no-skip-seed, got '$1'" >&2; usage ;;
    esac
    shift
done

for value in "$EXPECT" "$TODAY"; do
    case "$value" in
        up|refuse|down) ;;
        *) echo "boot_check: expect/today must be up|refuse|down, got '$value'" >&2; exit 2 ;;
    esac
done

if [ "$EXPECT" != "$TODAY" ] && [ -z "$GAP" ]; then
    echo "::error::boot_check: expect=$EXPECT != today=$TODAY with no gap id." >&2
    echo "A known-red cell must name its gap-register row (e.g. T-07)." >&2
    exit 2
fi

if { [ "$EXPECT" = "refuse" ] || [ "$TODAY" = "refuse" ]; } && [ -z "$LOG_FRAGMENT" ]; then
    echo "::error::boot_check: a refuse cell requires --log-fragment." >&2
    echo "Without it a deliberate refusal is indistinguishable from a crash." >&2
    exit 2
fi

# ── Workspace ────────────────────────────────────────────────────────────────
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/boot-check.XXXXXX")"
LOG="$WORKDIR/server.log"
SERVER_PID=""

cleanup() {
    # Always kill the server, on every exit path including a failed assertion,
    # so a red cell cannot leave :PORT bound for the next one.
    if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        kill "$SERVER_PID" 2>/dev/null || true
        for _ in $(seq 1 10); do
            kill -0 "$SERVER_PID" 2>/dev/null || break
            sleep 1
        done
        kill -9 "$SERVER_PID" 2>/dev/null || true
    fi
    wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# ── Environment ──────────────────────────────────────────────────────────────
# Each cell gets its own scratch SQLite file. Without this the run inherits
# whatever profiles.db happens to sit in the checkout, and the seeding-safety
# cell (§8) is only meaningful against an EMPTY store — run.py auto-seeds only
# when store.count() == 0, so a populated db would make that cell boot happily
# and the refusal would never be exercised. A caller may still override it.
export ORIGINAL_DB="${ORIGINAL_DB:-$WORKDIR/profiles.db}"
for assignment in ${ENV_ASSIGNMENTS[@]+"${ENV_ASSIGNMENTS[@]}"}; do
    export "${assignment?}"
done

SEED_ARGS=()
[ "$SKIP_SEED" -eq 1 ] && SEED_ARGS+=("--skip-seed")
# `"${SEED_ARGS[@]:-}"` would expand an EMPTY array to one empty-string argv
# entry, which argparse rejects with "unrecognized arguments:" -- i.e. the
# seeding cell would report `down` (bad argv) instead of `refuse` (the seeder's
# hard refusal), silently testing the wrong thing. `${a[@]+"${a[@]}"}` expands
# to nothing at all when the array is empty, and is safe under `set -u`.

PYTHON_BIN="${PYTHON:-python}"

echo "── boot_check: expect=$EXPECT today=$TODAY${GAP:+ gap=$GAP}"
echo "   env: ${ENV_ASSIGNMENTS[*]:-<none>} (ORIGINAL_DB=$ORIGINAL_DB)"
echo "   cmd: $PYTHON_BIN run.py --demo --frontend-dir demo --port $PORT ${SEED_ARGS[*]:-}"

# ── Boot ─────────────────────────────────────────────────────────────────────
"$PYTHON_BIN" run.py --demo --frontend-dir demo --port "$PORT" \
    ${SEED_ARGS[@]+"${SEED_ARGS[@]}"} > "$LOG" 2>&1 &
SERVER_PID=$!

OBSERVED=""
EXIT_CODE=""
for _ in $(seq 1 "$TIMEOUT"); do
    if curl -sf "http://127.0.0.1:$PORT/health" > "$WORKDIR/health.json" 2>/dev/null; then
        OBSERVED="up"
        break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        set +e
        wait "$SERVER_PID"
        EXIT_CODE=$?
        set -e
        SERVER_PID=""
        break
    fi
    sleep 1
done

if [ -z "$OBSERVED" ]; then
    if [ -n "$EXIT_CODE" ] && [ "$EXIT_CODE" -ne 0 ] \
       && [ -n "$LOG_FRAGMENT" ] && grep -qF -- "$LOG_FRAGMENT" "$LOG"; then
        OBSERVED="refuse"
    else
        OBSERVED="down"
    fi
fi

# ── Report ───────────────────────────────────────────────────────────────────
echo "── observed: $OBSERVED${EXIT_CODE:+ (exit $EXIT_CODE)}"
if [ "$OBSERVED" = "up" ]; then
    echo "   /health: $(cat "$WORKDIR/health.json")"
fi
echo "── server log (tail) ────────────────────────────────────────────────"
tail -n 40 "$LOG" || true
echo "─────────────────────────────────────────────────────────────────────"

if [ "$OBSERVED" != "$TODAY" ]; then
    echo "::error::boot_check: observed '$OBSERVED' but this cell records today='$TODAY'."
    echo "The product's boot behaviour changed. If that is the fix, update 'today'"
    echo "(and 'gap'/'expect') in .github/workflows/boot-matrix.yml in the same PR."
    exit 1
fi

if [ "$TODAY" != "$EXPECT" ]; then
    echo "::warning::Known gap ${GAP}: this cell is '$TODAY' but should be '$EXPECT'. See docs/testing/10-gap-register.md."
fi

echo "boot_check: OK (observed == today == $TODAY)"
exit 0
