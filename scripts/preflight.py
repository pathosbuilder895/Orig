#!/usr/bin/env python3
"""
scripts/preflight.py — local dev-environment sanity checks (WS-2 task 2.6).

Run via `make preflight`. Two checks:
  1. Interpreter version — CI/Render/Docker all run 3.11; anything under 3.10
     silently disagrees with pyproject.toml's `requires-python` and can pass
     locally while failing in CI.
  2. Bluebook bundle freshness — a JSX source newer than the built bundle
     means `npm run build` was never run (CI job 3 would also catch this via
     byte-diff, but failing fast locally saves a round trip).
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def check_python_version() -> bool:
    if sys.version_info < (3, 10):
        print(
            f"FAIL: Python 3.10+ required, got {sys.version_info.major}.{sys.version_info.minor}. "
            f"Rebuild .venv: python3.11 -m venv .venv && "
            f".venv/bin/pip install -r requirements.txt -r requirements-dev.txt",
            file=sys.stderr,
        )
        return False
    print(f"OK: Python {sys.version_info.major}.{sys.version_info.minor}")
    return True


def check_bundle_freshness() -> bool:
    bundle = REPO_ROOT / "demo" / "bluebook" / "bluebook.bundle.js"
    jsx_dir = REPO_ROOT / "demo" / "bluebook"
    if not bundle.exists():
        print(f"FAIL: {bundle} does not exist — run `make bundle`.", file=sys.stderr)
        return False
    bundle_mtime = bundle.stat().st_mtime
    stale = [
        p
        for p in jsx_dir.rglob("*.jsx")
        if "vendor" not in p.parts and p.stat().st_mtime > bundle_mtime
    ]
    if stale:
        names = ", ".join(p.relative_to(REPO_ROOT).as_posix() for p in stale)
        print(
            f"FAIL: JSX newer than bluebook.bundle.js: {names} — run `make bundle`.",
            file=sys.stderr,
        )
        return False
    print("OK: bluebook.bundle.js is newer than all .jsx sources")
    return True


def main() -> int:
    checks = [check_python_version(), check_bundle_freshness()]
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
