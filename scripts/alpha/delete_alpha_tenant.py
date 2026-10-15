#!/usr/bin/env python3
"""DRAFT — delete ONE alpha tenant's student accounts, submissions, courses and exams.

Dry run is the default. Nothing is deleted unless you pass BOTH --execute and
--confirm-name "<exact tenant name>". Refuses a tenant whose environment is 'pilot', and
one holding 'original' unless --allow-original is passed (the real pilot schools),
and refuses an empty / wildcard tenant id.

Copy into the repo's scripts/ before use, then (Render shell, after Andrew OKs):
    python scripts/delete_alpha_tenant.py t-xxxxxxxxxxxx                  # dry run
    python scripts/delete_alpha_tenant.py t-xxxxxxxxxxxx --execute \
        --confirm-name "Andrew (Alpha test)'s workspace"

Uses the repository's own FERPA erasure path (delete_tenant_students ->
delete_student per student: submissions, sessions, enrollments, invites,
audit rows, student login rows). The teacher login is left in place ; delete it by hand (see deletion_plan.md).
Backups taken before deletion age out on their own schedule (~30 days).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for cand in (ROOT, Path("/workspace/orig-audit")):
    if (cand / "original").is_dir():
        sys.path.insert(0, str(cand))
        break

from original.repository import backend_name, get_repository  # noqa: E402


def inventory(repo, tenant_id: str) -> dict:
    courses = repo.list_bluebook_courses(tenant_id)
    exams = repo.list_bluebook_exams(tenant_id)
    students = set(repo.list_ids_for_tenant(tenant_id))
    for c in courses:
        students |= {e["student_id"] for e in repo.list_enrollments_for_course(c["id"])}
    return {"courses": courses, "exams": exams, "students": sorted(students)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tenant_id")
    ap.add_argument("--execute", action="store_true", help="actually delete (default: dry run)")
    ap.add_argument("--confirm-name", default="", help="exact tenant name, required with --execute")
    ap.add_argument("--allow-original", action="store_true",
                    help="allow a workspace that holds Original (the alpha does); pilot-env tenants are always refused")
    a = ap.parse_args(argv)
    tid = a.tenant_id.strip()
    if not tid or any(ch in tid for ch in "*%?,; ") or tid in {"demo", "ops"}:
        print("refusing: give one exact tenant id", file=sys.stderr)
        return 2
    repo = get_repository()
    print(f"Database backend: {backend_name()}")
    t = repo.get_tenant(tid)
    if not t:
        print(f"no tenant {tid}", file=sys.stderr)
        return 1
    products = t.get("products") or []
    print(f"Tenant {tid}: name={t.get('name')!r} env={t.get('environment')} products={products}")
    if t.get("environment") == "pilot":
        print("refusing: pilot-school tenant", file=sys.stderr)
        return 3
    if "original" in products and not a.allow_original:
        print("refusing: tenant holds Original; pass --allow-original if this is the alpha", file=sys.stderr)
        return 3
    inv = inventory(repo, tid)
    print(f"Would delete: {len(inv['students'])} students (with baselines, features, scores, submissions, "
          f"sessions, invites, enrollments), {len(inv['exams'])} exams, {len(inv['courses'])} courses")
    for s in inv["students"]:
        print("  student", s)
    if not a.execute:
        print("DRY RUN — nothing deleted. Re-run with --execute --confirm-name to delete.")
        return 0
    if a.confirm_name != (t.get("name") or ""):
        print("refusing: --confirm-name does not match the tenant name exactly", file=sys.stderr)
        return 4
    out = repo.delete_tenant_students(tid)
    for e in inv["exams"]:
        repo.delete_bluebook_exam(e["id"])
    for c in inv["courses"]:
        repo.delete_bluebook_course(c["id"])
    print(f"Deleted {out['deleted_count']} students; failed: {out['failed_ids']}; "
          f"{len(inv['exams'])} exams; {len(inv['courses'])} courses")
    left = inventory(repo, tid)
    print(f"Remaining: {len(left['students'])} students, {len(left['exams'])} exams, {len(left['courses'])} courses")
    return 0 if not out["failed_ids"] and not any(left.values()) else 5


if __name__ == "__main__":
    sys.exit(main())
