"""bluebook_join_links: forwardable course sign-up links

Additive only: one new table, nothing existing is altered. A row is one
course's shareable sign-up link: anyone who opens it can create their own
student account and join the course. Only the sha256 of the token is
stored. ``voided_at`` is set when the teacher turns the link off or replaces
it; rows are deleted with their course.

Revision ID: b8f4d2a6c9e1
Revises: a7e3c5d9f2b4
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "b8f4d2a6c9e1"
down_revision: str | None = "a7e3c5d9f2b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bluebook_join_links",
        sa.Column("link_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("course_id", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_bluebook_join_links_tenant_id_tenants"),
        ),
        sa.PrimaryKeyConstraint("link_id", name=op.f("pk_bluebook_join_links")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_bluebook_join_links_token_hash")),
    )
    op.create_index(
        "idx_bluebook_join_links_course", "bluebook_join_links", ["course_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("idx_bluebook_join_links_course", table_name="bluebook_join_links")
    op.drop_table("bluebook_join_links")
