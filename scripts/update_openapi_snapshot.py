#!/usr/bin/env python3
"""
update_openapi_snapshot.py — regenerate the committed OpenAPI schema snapshot.

`tests/test_openapi_stability.py` proves `app.openapi()` is byte-identical
across `PYTHONHASHSEED` values (no operationId churn from set-iteration
order); it does not catch a deliberate schema *change*. `tests/snapshots/
openapi.json` is the committed baseline that `tests/test_openapi_snapshot.py`
diffs against on every run, so any schema change becomes a reviewed diff
in the commit instead of a silent drift.

Serialisation must match `tests/test_openapi_snapshot.py` exactly —
`json.dumps(..., sort_keys=True, indent=2)` plus a trailing newline, written
UTF-8 with `ensure_ascii=False` (the schema can contain non-ASCII text, e.g.
in field descriptions, and escaping it would make diffs harder to read).

Usage:
    .venv/bin/python scripts/update_openapi_snapshot.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = REPO_ROOT / "tests" / "snapshots" / "openapi.json"


def main() -> None:
    sys.path.insert(0, str(REPO_ROOT))
    from run import load_legacy_demo_app

    app = load_legacy_demo_app()
    schema = app.openapi()
    text = json.dumps(schema, sort_keys=True, indent=2, ensure_ascii=False) + "\n"

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {SNAPSHOT_PATH.relative_to(REPO_ROOT)} ({len(text)} bytes)")


if __name__ == "__main__":
    main()
