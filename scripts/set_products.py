#!/usr/bin/env python3
"""Switch Original on or off for one professor's workspace.

Run where the service's environment is available (Render → original-pilot →
Shell), so it writes to the live database:

    python scripts/set_products.py prof@school.edu --original on
    python scripts/set_products.py prof@school.edu --original off

Bluebook stays on either way. The web service picks the change up within 30
seconds without a restart; open pages pick it up when the professor or
student next loads their home page or signs in. A student whose page still
thinks Original is on can seal as usual.

A professor invited by scripts/invite_professor.py (or who signed up) has a
private workspace. A professor in an institution workspace registered
through POST /tenants shares it, so the switch applies to everyone in it;
the script says so. The first line names the database backend it wrote to,
so a run against the wrong database is obvious.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):  # run as a file: make `original` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from original.onboarding import ORIGINAL_NOT_VALIDATED, set_original  # noqa: E402
from original.repository import backend_name  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Switch Original on or off for a professor's workspace."
    )
    parser.add_argument("email", help="the professor's email")
    parser.add_argument("--original", choices=["on", "off"], required=True)
    args = parser.parse_args(argv)
    print(f"Database backend: {backend_name()}")
    try:
        out = set_original(args.email, args.original == "on")
    except ValueError as exc:
        print(f"set_products: {exc}", file=sys.stderr)
        return 1
    print(f"Workspace {out['tenant_id']} ({out['tenant_name']})")
    if out["shared_workspace"]:
        print(
            "WARNING: this is an institution workspace; the change applies to every "
            "professor and student in it."
        )
    if out["changed"]:
        print(f"Products: {', '.join(out['before'])} -> {', '.join(out['products'])}")
        print(
            "The server applies this within 30 seconds. Open pages pick it up when the "
            "professor or student next loads their home page or signs in."
        )
    else:
        print(f"No change: products are already {', '.join(out['products'])}.")
    if args.original == "on":
        print(ORIGINAL_NOT_VALIDATED)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
