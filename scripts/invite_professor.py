#!/usr/bin/env python3
"""Invite a professor to an invitation-only Bluebook deploy.

Run where the service's environment is available (Render → original-pilot →
Shell), so it writes to the live database:

    python scripts/invite_professor.py prof@school.edu --name "Dr Name"

Creates a private Bluebook-only workspace and emails a one-time set-password
link when SendGrid is configured. The link is always printed so the operator
can send it by hand if the email does not arrive. It is a credential: send it
only to the professor.

Run it again for a professor who has not set a password yet to issue a new
link to the same workspace (earlier links stop working). The first line
names the database backend it wrote to, so a run against the wrong database
is obvious.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):  # run as a file: make `original` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from original.onboarding import invite_professor, link_is_absolute  # noqa: E402
from original.repository import backend_name  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Invite a professor to Bluebook.")
    parser.add_argument("email")
    parser.add_argument("--name", default="")
    parser.add_argument(
        "--base-url", default="", help="public site URL, used only if PUBLIC_BASE_URL is unset"
    )
    args = parser.parse_args(argv)
    print(f"Database backend: {backend_name()}")
    try:
        out = invite_professor(args.email, args.name, args.base_url)
    except ValueError as exc:
        print(f"invite_professor: {exc}", file=sys.stderr)
        return 1
    if out["reissued"]:
        print("Existing unactivated professor: issued a new link (earlier links no longer work).")
    else:
        print(f"Workspace {out['tenant_id']} created for {out['email']}.")
    if not link_is_absolute(out["invite_link"]):
        print(
            "WARNING: the link is relative because neither PUBLIC_BASE_URL nor --base-url "
            "is set, so it was NOT emailed and will not work as printed. Set PUBLIC_BASE_URL "
            "or pass --base-url https://<host> and run this again (it issues a fresh link).",
            file=sys.stderr,
        )
    elif out["emailed"]:
        print("Invitation emailed.")
    else:
        print("Email NOT sent (mail not configured or rejected): send this link yourself.")
    print(f"Set-password link (single use, expires {out['expires_at']}):")
    print(out["invite_link"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
