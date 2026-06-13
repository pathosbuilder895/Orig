#!/usr/bin/env python3
"""
reset_demo_data.py — purge demo-tenant test artifacts so the database is
presentation-ready before showing universities.

Deletes (demo sandbox only — real/pilot tenants are never touched):
  • bluebook_exams / bluebook_submissions / bluebook_courses where tenant='demo'
  • student_profiles under the reserved 'demo:' namespace
  • stale dev rows in fidelity_scores (the 'student-A' fixtures)

Keeps:
  • the flat-id seeded demo students (re-seeded by `run.py --demo` at startup)
  • all tenants/users/exams/submissions of every non-demo tenant
  • the audit log (FERPA: an audit trail should not be silently erased;
    pass --purge-audit-demo to also drop audit rows tagged tenant 'demo')

Usage:
    .venv/bin/python scripts/reset_demo_data.py            # dry run (default)
    .venv/bin/python scripts/reset_demo_data.py --apply    # actually delete
    .venv/bin/python scripts/reset_demo_data.py --apply --purge-audit-demo
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

DB = Path(os.environ.get("ORIGINAL_DB", Path(__file__).resolve().parent.parent / "profiles.db"))

STATEMENTS = [
    ("bluebook_submissions (demo)", "DELETE FROM bluebook_submissions WHERE tenant_id = 'demo'"),
    ("bluebook_exams (demo)",       "DELETE FROM bluebook_exams       WHERE tenant_id = 'demo'"),
    ("bluebook_courses (demo)",     "DELETE FROM bluebook_courses     WHERE tenant_id = 'demo'"),
    ("student_profiles (demo:*)",   "DELETE FROM student_profiles     WHERE student_id LIKE 'demo:%'"),
    ("fidelity_scores (dev stubs)", "DELETE FROM fidelity_scores      WHERE student_id IN ('student-A')"),
]
AUDIT_STMT = ("audit_log (demo)", "DELETE FROM audit_log WHERE tenant_id = 'demo'")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="actually delete (default is a dry run)")
    ap.add_argument("--purge-audit-demo", action="store_true",
                    help="also delete audit_log rows tagged tenant 'demo'")
    args = ap.parse_args()

    if not DB.exists():
        print(f"No database at {DB} — nothing to reset.")
        return 0

    stmts = STATEMENTS + ([AUDIT_STMT] if args.purge_audit_demo else [])
    conn = sqlite3.connect(str(DB))
    try:
        mode = "APPLY" if args.apply else "DRY RUN"
        print(f"[{mode}] {DB}")
        total = 0
        for label, stmt in stmts:
            count_sql = "SELECT COUNT(*) " + stmt[stmt.index("FROM"):]
            n = conn.execute(count_sql).fetchone()[0]
            total += n
            print(f"  {label:32} {n:4d} row(s)")
            if args.apply and n:
                conn.execute(stmt)
        if args.apply:
            conn.commit()
            conn.execute("VACUUM")
            print(f"Deleted {total} row(s). Demo tenant is clean.")
            print("Note: restart `run.py --demo` to re-seed the flat demo students fresh.")
        else:
            print(f"{total} row(s) would be deleted. Re-run with --apply to do it.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
