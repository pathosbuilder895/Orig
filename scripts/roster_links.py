#!/usr/bin/env python3
"""
roster_links.py — turn a class roster into bound, disclosure-stamped Bluebook
launch links, for the no-Canvas same-day path.

Why this exists
---------------
The friction-free way an entire class gets into a bound exam is a Canvas/LTI
launch (each student auto-bound on launch). When a professor wants to run a
baseline *today* but their Canvas developer key isn't registered yet, this
script is the fallback: paste a roster, get one bound launch link per student.

Each link carries ONLY the opaque student id (``sid``) — never name or email —
so it upholds the disclosure promise that "your name and email do not appear in
stored records or URLs." The id is derived with the SAME formula the server
uses (``original.student_auth.derive_student_id``), so a link generated here and
a Canvas launch for the same student resolve to the identical profile.

Two outputs, both spines of the day-one flow:
  • the per-student links the professor distributes privately, and
  • an expected-roster JSON (``--expected-out``) — the {sid, name, email} list a
    "12 of 30 submitted" dashboard view can later diff against who's written.

This script is OFFLINE and non-destructive: it only derives ids and assembles
URLs. It does NOT create the tenant or touch the database. The tenant must
already exist as ``environment=pilot`` (see docs/PROVISIONING_CHECKLIST.md) —
otherwise a student self-login could auto-create it as a world-readable demo
tenant. The script prints that reminder.

Roster format (liberal — one student per line, blank lines / `#` comments
skipped). Any of:
    Jane Doe,jane@school.edu
    jane@school.edu,Jane Doe
    Jane Doe <jane@school.edu>
    jane@school.edu
CSV with a header row (columns named name/email in any order) also works.

Usage:
    .venv/bin/python scripts/roster_links.py \
        --roster roster.csv \
        --institution "Northfield Seminary" \
        --base-url https://original-pilot.onrender.com \
        --exam "Week 1 Writing Sample" \
        --out links.csv --expected-out expected_roster.json

    # bare links to stdout, names included on the briefing (opts out of FERPA
    # URL-minimisation — see --include-name):
    .venv/bin/python scripts/roster_links.py -r roster.txt -i Northfield \
        --format links --include-name
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
from pathlib import Path
from typing import List, NamedTuple, Optional
from urllib.parse import quote, urlencode

# Import the canonical id derivation so links never drift from the server.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
try:
    from original.student_auth import derive_student_id, slugify
except Exception as exc:  # pragma: no cover - environment guard
    sys.stderr.write(
        f"error: cannot import original.student_auth ({exc}).\n"
        f"Run from the repo root with the project venv:\n"
        f"    .venv/bin/python scripts/roster_links.py ...\n"
    )
    raise SystemExit(2)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_DISCLOSURE_DOC = _REPO_ROOT / "docs" / "STUDENT_DISCLOSURE.md"


class Student(NamedTuple):
    name: str
    email: str
    sid: str
    link: str


def _split_name_email(line: str) -> Optional[tuple[str, str]]:
    """Pull (name, email) out of one liberal roster line, or None to skip."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    m = _EMAIL_RE.search(line)
    if not m:
        sys.stderr.write(f"  skipped (no email found): {line!r}\n")
        return None
    email = m.group(0).strip().lower()
    # Everything that isn't the email, stripped of separators/brackets, is the name.
    name = (line[: m.start()] + " " + line[m.end():]).strip(" \t,;<>\"'")
    name = re.sub(r"[\s,;]+", " ", name).strip(" ,;<>\"'")
    return name, email


def parse_roster(text: str) -> List[tuple[str, str]]:
    """Parse a roster blob into [(name, email), ...], de-duped by email.

    Handles CSV-with-header (looks for name/email columns) and the liberal
    one-per-line forms. Order preserved; first occurrence of an email wins.
    """
    rows: List[tuple[str, str]] = []
    seen: set[str] = set()

    # Try CSV-with-header first: if the first non-empty line has an 'email' column.
    sample = "\n".join(text.splitlines()[:1])
    looks_like_header = "email" in sample.lower() and ("," in sample or "\t" in sample)
    if looks_like_header:
        dialect = csv.Sniffer().sniff(text.splitlines()[0]) if text.strip() else csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        cols = {(c or "").strip().lower(): c for c in (reader.fieldnames or [])}
        ecol = next((cols[k] for k in cols if "email" in k or "e-mail" in k), None)
        ncol = next((cols[k] for k in cols if k in ("name", "student", "full name", "fullname")), None)
        if ecol:
            for r in reader:
                email = (r.get(ecol) or "").strip().lower()
                if not _EMAIL_RE.fullmatch(email) or email in seen:
                    if email and email not in seen:
                        sys.stderr.write(f"  skipped (bad email in CSV): {email!r}\n")
                    continue
                name = (r.get(ncol) or "").strip() if ncol else ""
                seen.add(email)
                rows.append((name, email))
            return rows
        # header mentioned email but no usable column — fall through to liberal parse

    for line in text.splitlines():
        parsed = _split_name_email(line)
        if not parsed:
            continue
        name, email = parsed
        if email in seen:
            continue
        seen.add(email)
        rows.append((name, email))
    return rows


def build_link(base_url: str, tenant: str, sid: str, exam: str, name: str, include_name: bool) -> str:
    base = base_url.rstrip("/")
    params = [("sid", sid), ("tenant", tenant)]
    if exam:
        params.append(("exam", exam))
    if include_name and name:
        params.append(("candidate", name))
    return f"{base}/bluebook/?{urlencode(params, quote_via=quote)}"


def syllabus_paragraph() -> Optional[str]:
    """Extract the suggested syllabus paragraph from the disclosure doc (DRY:
    single source of truth). Returns the block-quoted text, or None."""
    if not _DISCLOSURE_DOC.exists():
        return None
    text = _DISCLOSURE_DOC.read_text(encoding="utf-8")
    marker = "## Suggested syllabus paragraph"
    idx = text.find(marker)
    if idx == -1:
        return None
    after = text[idx + len(marker):]
    lines = []
    for ln in after.splitlines():
        s = ln.strip()
        if s.startswith(">"):
            lines.append(s.lstrip("> ").rstrip())
        elif lines and not s:
            break  # blank line after the quote ends it
    return " ".join(l for l in lines if l) or None


def emit(students: List[Student], fmt: str, out) -> None:
    if fmt == "links":
        for s in students:
            out.write(s.link + "\n")
    elif fmt == "csv":
        w = csv.writer(out)
        w.writerow(["candidate", "email", "student_id", "launch_url"])
        for s in students:
            w.writerow([s.name, s.email, s.sid, s.link])
    elif fmt == "md":
        out.write("| Candidate | Email | Student ID | Launch link |\n")
        out.write("|---|---|---|---|\n")
        for s in students:
            out.write(f"| {s.name or '—'} | {s.email} | `{s.sid}` | {s.link} |\n")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("-r", "--roster", required=True,
                    help="path to roster file (CSV or one student per line), or '-' for stdin")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("-i", "--institution", help="institution name → slugified to the tenant id")
    g.add_argument("-t", "--tenant", help="tenant slug directly (use the exact slug the tenant was provisioned with)")
    ap.add_argument("-b", "--base-url", default="",
                    help="pilot host, e.g. https://original-pilot.onrender.com (required for usable links)")
    ap.add_argument("-e", "--exam", default="Week 1 Writing Sample",
                    help="exam title shown on the briefing (default: 'Week 1 Writing Sample')")
    ap.add_argument("--format", choices=["csv", "md", "links"], default="csv",
                    help="output format (default: csv)")
    ap.add_argument("-o", "--out", help="write links to this file (default: stdout)")
    ap.add_argument("--expected-out",
                    help="also write the expected-roster JSON [{sid,name,email}] here "
                         "(the spine for a later 'N of M submitted' view)")
    ap.add_argument("--include-name", action="store_true",
                    help="put the student's name in the URL as candidate= so the briefing greets "
                         "them by name. OPTS OUT of FERPA URL-minimisation — the name then appears "
                         "in the link. Default off: links carry only the opaque sid.")
    ap.add_argument("--no-disclosure", action="store_true",
                    help="suppress the syllabus-disclosure reminder printed to stderr")
    args = ap.parse_args()

    # Resolve tenant slug.
    if args.tenant:
        tenant = slugify(args.tenant)
        if tenant != args.tenant:
            sys.stderr.write(f"note: --tenant normalised to slug '{tenant}'\n")
    else:
        tenant = slugify(args.institution)

    # Read roster.
    if args.roster == "-":
        raw = sys.stdin.read()
    else:
        rpath = Path(args.roster)
        if not rpath.exists():
            sys.stderr.write(f"error: roster file not found: {rpath}\n")
            return 2
        raw = rpath.read_text(encoding="utf-8")

    pairs = parse_roster(raw)
    if not pairs:
        sys.stderr.write("error: no valid (name,email) rows parsed from the roster.\n")
        return 1

    if not args.base_url:
        sys.stderr.write(
            "warning: --base-url is empty; links will be relative (/bluebook/?...) and not "
            "directly clickable. Pass the pilot host to make them usable.\n"
        )

    students = [
        Student(
            name=name,
            email=email,
            sid=derive_student_id(tenant, email),
            link=build_link(args.base_url, tenant, derive_student_id(tenant, email),
                            args.exam, name, args.include_name),
        )
        for (name, email) in pairs
    ]

    # Emit links.
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as f:
            emit(students, args.format, f)
        sys.stderr.write(f"wrote {len(students)} links → {args.out}\n")
    else:
        emit(students, args.format, sys.stdout)

    # Emit expected-roster spine.
    if args.expected_out:
        payload = {
            "tenant": tenant,
            "exam": args.exam,
            "count": len(students),
            "students": [{"sid": s.sid, "name": s.name, "email": s.email} for s in students],
        }
        Path(args.expected_out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        sys.stderr.write(f"wrote expected-roster spine ({len(students)} students) → {args.expected_out}\n")

    # Operator reminders to stderr (never mixed into the links on stdout).
    sys.stderr.write(
        f"\n{len(students)} bound links generated for tenant '{tenant}'"
        + (f" on {args.base_url.rstrip('/')}" if args.base_url else "")
        + ".\n"
    )
    sys.stderr.write(
        "Before distributing:\n"
        f"  1. Confirm tenant '{tenant}' exists as environment=pilot (NOT demo) — "
        "see docs/PROVISIONING_CHECKLIST.md.\n"
        "  2. Send each link to its own student privately; one link == one bound profile.\n"
    )
    if args.include_name:
        sys.stderr.write(
            "  ! --include-name set: student names appear in the URLs (FERPA URL-minimisation off).\n"
        )

    if not args.no_disclosure:
        para = syllabus_paragraph()
        if para:
            sys.stderr.write("\n--- Syllabus disclosure paragraph (put in every participating course) ---\n")
            sys.stderr.write(para + "\n")
            sys.stderr.write("--- Full student disclosure: docs/STUDENT_DISCLOSURE.md ---\n")
        else:
            sys.stderr.write("\n(note: docs/STUDENT_DISCLOSURE.md not found — give students the disclosure manually.)\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
