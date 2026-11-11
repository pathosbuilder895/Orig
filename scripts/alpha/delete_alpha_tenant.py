#!/usr/bin/env python3
"""Delete the single named alpha workspace, after an explicit confirmation.

Dry-run is the default. Execution requires ``--execute`` and the exact tenant
name ``Andrew (Alpha test)'s workspace``. Other workspaces are never eligible.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from original.repository import backend_name, get_repository  # noqa: E402

ALPHA_TENANT_NAME = "Andrew (Alpha test)'s workspace"


def inventory(repo, tenant_id: str) -> dict:
    courses = repo.list_bluebook_courses(tenant_id)
    exams = repo.list_bluebook_exams(tenant_id)
    students = set(repo.list_ids_for_tenant(tenant_id))
    for course in courses:
        students |= {row["student_id"] for row in repo.list_enrollments_for_course(course["id"])}
    return {"courses": courses, "exams": exams, "students": sorted(students)}


def delete_tenant(repo, tenant_id: str, *, execute: bool, confirm_name: str) -> int:
    tid = tenant_id.strip()
    if not tid or any(ch in tid for ch in "*%?,; ") or tid in {"demo", "ops"}:
        print("refusing: give one exact tenant id", file=sys.stderr)
        return 2
    tenant = repo.get_tenant(tid)
    if not tenant:
        print(f"no tenant {tid}", file=sys.stderr)
        return 1
    if tenant.get("name") != ALPHA_TENANT_NAME:
        print(f"refusing: tenant is not the named alpha workspace ({ALPHA_TENANT_NAME!r})", file=sys.stderr)
        return 3
    if tenant.get("environment") == "pilot":
        print("refusing: pilot tenants are never eligible", file=sys.stderr)
        return 3

    inv = inventory(repo, tid)
    print(f"Tenant {tid}: name={tenant.get('name')!r} env={tenant.get('environment')} products={tenant.get('products') or []}")
    print(f"Would delete: {len(inv['students'])} students, {len(inv['exams'])} exams, {len(inv['courses'])} courses")
    if not execute:
        print("DRY RUN — nothing deleted. Re-run with --execute --confirm-name \"Andrew (Alpha test)'s workspace\".")
        return 0
    if confirm_name != ALPHA_TENANT_NAME:
        print("refusing: --confirm-name must exactly match the named alpha tenant", file=sys.stderr)
        return 4

    result = repo.delete_tenant_students(tid)
    for exam in inv["exams"]:
        repo.delete_bluebook_exam(exam["id"])
    for course in inv["courses"]:
        repo.delete_bluebook_course(course["id"])
    remaining = inventory(repo, tid)
    print(f"Deleted {result['deleted_count']} students; failed: {result['failed_ids']}; {len(inv['exams'])} exams; {len(inv['courses'])} courses")
    print(f"Remaining: {len(remaining['students'])} students, {len(remaining['exams'])} exams, {len(remaining['courses'])} courses")
    return 0 if not result["failed_ids"] and not any(remaining.values()) else 5


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tenant_id", help="exact tenant id printed by invite_professor.py")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="execute", action="store_false", help="show the inventory only (default)")
    mode.add_argument("--execute", dest="execute", action="store_true", help="delete the named alpha tenant")
    parser.set_defaults(execute=False)
    parser.add_argument("--confirm-name", default="", help="must exactly equal the named alpha tenant")
    args = parser.parse_args(argv)
    print(f"Database backend: {backend_name()}")
    return delete_tenant(get_repository(), args.tenant_id, execute=args.execute, confirm_name=args.confirm_name)


if __name__ == "__main__":
    raise SystemExit(main())
