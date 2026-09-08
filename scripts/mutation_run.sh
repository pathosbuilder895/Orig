#!/usr/bin/env bash
# scripts/mutation_run.sh — T-31 mutation baseline (docs/testing/02-unit-property-math.md §5).
#
# Reproduces the mutmut campaign end-to-end against the two modules configured
# in pyproject.toml's [tool.mutmut] section (original/db/tenancy_shim.py,
# original/principal.py), using the runner tests/test_principal_branches.py +
# tests/test_tenant_isolation.py. Weekly, non-blocking — not wired into CI.
#
# Usage:
#   bash scripts/mutation_run.sh
#
# Always starts from a clean mutants/ directory. mutmut 3.x's copy_also_copy_files
# step re-copies tests/ with shutil.copy2 (which chflags the destination to match
# the source) on every run; overwriting an already-flagged file left behind by a
# prior run can raise "Operation not permitted" in some sandboxed/APFS filesystem
# setups. A clean directory sidesteps that — see docs/testing/mutation-baseline.md
# for the failure this produced during T-31's setup.
set -euo pipefail

cd "$(dirname "$0")/.."

# The worktree this was authored in has no local .venv (see CLAUDE.md /
# project memory: "venv path in worktrees") — fall back to the primary
# checkout's absolute path when a relative .venv isn't present.
if [ -x ".venv/bin/python" ]; then
    VENV_BIN=".venv/bin"
else
    VENV_BIN="/Users/andrew/Desktop/Original/.venv/bin"
fi
PIP="$VENV_BIN/pip"
MUTMUT="$VENV_BIN/mutmut"

MUTMUT_VERSION="3.7.0"

installed_version="$("$PIP" show mutmut 2>/dev/null | awk -F': ' '/^Version/{print $2}' || true)"
if [ "$installed_version" != "$MUTMUT_VERSION" ]; then
    echo "Installing mutmut==$MUTMUT_VERSION (found: ${installed_version:-<not installed>}) ..."
    "$PIP" install "mutmut==$MUTMUT_VERSION"
fi

echo "Starting from a clean mutants/ directory..."
rm -rf mutants

echo "Running mutation campaign (original/db/tenancy_shim.py, original/principal.py)..."
echo "Runner: python -m pytest -x -q -p no:cacheprovider tests/test_principal_branches.py tests/test_tenant_isolation.py"
"$MUTMUT" run

echo
echo "=== Surviving / non-killed mutants (mutmut results) ==="
"$MUTMUT" results

echo
echo "=== Full results, including killed (mutmut results --all true) ==="
# Note: mutmut 3.7.0's --all is a click BOOLEAN option, not a bare flag --
# it requires an explicit value ("true"/"false"), not just "--all".
"$MUTMUT" results --all true

echo
echo "Done. Record totals + survivor diffs (mutmut show <mutant_name>) in docs/testing/mutation-baseline.md."
