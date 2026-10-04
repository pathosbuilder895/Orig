"""Bluebook self-serve: tenant products, rosters, invites, exam windows

Revision ID: e8d2b4a6c1f0
Revises: c3a7e5f19b02
Create Date: 2026-09-28

Every new column is nullable or carries a server default, so the code that
predates this revision keeps working against the upgraded schema. That is
what lets the rollout run this migration before the deploy that reads it
(docs/superpowers/specs/2026-09-17-bluebook-standalone-backend-design.md).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e8d2b4a6c1f0"
down_revision: str | None = "c3a7e5f19b02"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "products_json",
            _JSON,
            server_default=sa.text("""'["original", "bluebook"]'"""),
            nullable=False,
        ),
    )
    op.add_column("bluebook_exams", sa.Column("course_id", sa.Text(), nullable=True))
    op.add_column(
        "bluebook_exams", sa.Column("opens_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "bluebook_exams", sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("bluebook_submissions", sa.Column("text", sa.Text(), nullable=True))
    op.add_column(
        "bluebook_submissions",
        sa.Column("warnings_json", _JSON, server_default=sa.text("'[]'"), nullable=False),
    )
    op.create_table(
        "bluebook_enrollments",
        sa.Column("course_id", sa.Text(), nullable=False),
        sa.Column("student_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_bluebook_enrollments_tenant_id_tenants"),
        ),
        sa.PrimaryKeyConstraint("course_id", "student_id", name=op.f("pk_bluebook_enrollments")),
    )
    op.create_index(
        "idx_bluebook_enrollments_student",
        "bluebook_enrollments",
        ["tenant_id", "student_id"],
        unique=False,
    )
    op.create_table(
        "bluebook_invites",
        sa.Column("invite_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("course_id", sa.Text(), nullable=True),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_bluebook_invites_tenant_id_tenants"),
        ),
        sa.PrimaryKeyConstraint("invite_id", name=op.f("pk_bluebook_invites")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_bluebook_invites_token_hash")),
    )
    op.create_index("idx_bluebook_invites_user", "bluebook_invites", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_bluebook_invites_user", table_name="bluebook_invites")
    op.drop_table("bluebook_invites")
    op.drop_index("idx_bluebook_enrollments_student", table_name="bluebook_enrollments")
    op.drop_table("bluebook_enrollments")
    op.drop_column("bluebook_submissions", "warnings_json")
    op.drop_column("bluebook_submissions", "text")
    op.drop_column("bluebook_exams", "closes_at")
    op.drop_column("bluebook_exams", "opens_at")
    op.drop_column("bluebook_exams", "course_id")
    op.drop_column("tenants", "products_json")
