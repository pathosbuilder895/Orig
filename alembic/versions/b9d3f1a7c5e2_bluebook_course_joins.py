"""bluebook_course_joins and bluebook_join_requests: students join a course by link

Additive only: two new tables, nothing existing is altered. Current invites,
rosters and logins are untouched.

``bluebook_course_joins`` holds one row per course whose teacher has turned
on its join link: the short join code (unique across every course, since the
link carries no tenant), whether joining is on, an optional email domain
limit, and whether new joiners wait for approval.

``bluebook_join_requests`` holds a student who joined by link while the
course required approval and has not been approved yet. They are kept out of
``bluebook_enrollments`` on purpose, so nothing that reads the roster (exams,
the live view, the student-count cap) sees them until the teacher approves.
Deleted with the student's data on erasure and with the course.

Revision ID: b9d3f1a7c5e2
Revises: a7e3c5d9f2b4
Create Date: 2026-10-26
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "b9d3f1a7c5e2"
down_revision: str | None = "a7e3c5d9f2b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bluebook_course_joins",
        sa.Column("course_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("allowed_domain", sa.Text(), server_default="", nullable=False),
        sa.Column("require_approval", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_bluebook_course_joins_tenant_id_tenants"),
        ),
        sa.PrimaryKeyConstraint("course_id", name=op.f("pk_bluebook_course_joins")),
        sa.UniqueConstraint("code", name=op.f("uq_bluebook_course_joins_code")),
    )
    op.create_table(
        "bluebook_join_requests",
        sa.Column("course_id", sa.Text(), nullable=False),
        sa.Column("student_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_bluebook_join_requests_tenant_id_tenants"),
        ),
        sa.PrimaryKeyConstraint("course_id", "student_id", name=op.f("pk_bluebook_join_requests")),
    )
    op.create_index(
        "idx_bluebook_join_requests_student",
        "bluebook_join_requests",
        ["student_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_bluebook_join_requests_student", table_name="bluebook_join_requests")
    op.drop_table("bluebook_join_requests")
    op.drop_table("bluebook_course_joins")
