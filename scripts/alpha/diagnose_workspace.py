# ruff: noqa: E501
"""READ-ONLY diagnostic for one Collections workspace (alpha bug 2026-10-20).

Runs in a SET TRANSACTION READ ONLY transaction that is rolled back. Prints
no essay text, password hashes, or tokens; emails show only their domain.

    python scripts/alpha/diagnose_workspace.py t-2c28d5f65bd1
"""

import json
import os
import sys

from sqlalchemy import create_engine, text

T = sys.argv[1] if len(sys.argv) > 1 else "t-2c28d5f65bd1"


def mask(email):
    return "***@" + email.split("@")[-1] if email and "@" in email else email


def main():
    url = os.environ["DATABASE_URL"].replace("postgres://", "postgresql://", 1)
    with create_engine(url).connect() as c:
        c.execute(text("SET TRANSACTION READ ONLY"))

        def q(sql):
            return c.execute(text(sql), {"t": T}).mappings().all()

        print(
            "tenant:",
            [
                dict(r)
                for r in q("select tenant_id, name, created_at from tenants where tenant_id=:t")
            ],
        )
        print("\n# users in tenant")
        for r in q(
            "select user_id, role, email, created_at from users where tenant_id=:t order by created_at"
        ):
            print(" ", r["user_id"], r["role"], mask(r["email"]), r["created_at"])
        print("\n# teacher account(s) for arclark555 in ANY tenant (wrong-workspace check)")
        for r in q(
            "select user_id, role, tenant_id from users where lower(email)='arclark555@gmail.com'"
        ):
            print(" ", dict(r))
        print("\n# courses")
        for r in q(
            "select course_id, code, name, status, created_at from bluebook_courses where tenant_id=:t"
        ):
            print(" ", dict(r))
        print("\n# roster (enrollments)")
        for r in q(
            "select e.course_id, e.student_id, u.role, u.email, e.created_at from bluebook_enrollments e"
            " left join users u on u.user_id=e.student_id where e.tenant_id=:t order by e.created_at"
        ):
            print(
                " ", r["course_id"], r["student_id"], r["role"], mask(r["email"]), r["created_at"]
            )
        print("\n# exams")
        for r in q(
            "select exam_id, title, course_id, status, opens_at, closes_at, results_released_at,"
            " duration, min_words from bluebook_exams where tenant_id=:t order by created_at"
        ):
            print(" ", dict(r))
        print("\n# sittings")
        for r in q(
            "select exam_id, student_key, started_at, deadline_at from bluebook_sessions where tenant_id=:t"
        ):
            print(" ", dict(r))
        print("\n# submissions (no text)")
        for r in q(
            "select submission_id, exam_id, student_id, status, word_count, late, created_at,"
            " coalesce(length(text),0) as text_chars from bluebook_submissions where tenant_id=:t order by created_at"
        ):
            print(" ", dict(r))
        print("\n# all-tenant submission counts for this tenant's students (misfiled-tenant check)")
        for r in q(
            "select s.tenant_id, count(*) n from bluebook_submissions s where s.student_id in"
            " (select student_id from bluebook_enrollments where tenant_id=:t) group by s.tenant_id"
        ):
            print(" ", dict(r))
        print("\n# baselines")
        for r in q("select student_id, data from student_profiles where tenant_id=:t"):
            d = r["data"] if isinstance(r["data"], dict) else json.loads(r["data"] or "{}")
            print(
                " ",
                r["student_id"],
                {
                    k: len(v) if isinstance(v, (list, dict)) else v
                    for k, v in d.items()
                    if not isinstance(v, str)
                },
            )
        for r in q(
            "select status, count(*) n from baseline_requests where tenant_id=:t group by status"
        ):
            print("  baseline_requests:", dict(r))
        c.rollback()
    print("\nread-only diagnostic done")


main()
