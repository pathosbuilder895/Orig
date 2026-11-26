"""student_past_papers: past papers students share for teacher approval

Revision ID: b5e1f7c3a9d2
Revises: a7d3c9e1b5f2
Create Date: 2026-10-20
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "b5e1f7c3a9d2"
down_revision: str | None = "a7d3c9e1b5f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No tenant foreign key, mirroring consumed_attestations — see
    # original/db/models/live.py:StudentPastPaper.
    op.create_table(
        "student_past_papers",
        sa.Column("paper_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("student_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("baseline_source", sa.Text(), server_default="independent", nullable=False),
        sa.Column("parent_title", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("paper_id", name=op.f("pk_student_past_papers")),
    )
    op.create_index(
        "idx_student_past_papers_student",
        "student_past_papers",
        ["tenant_id", "student_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_student_past_papers_student", table_name="student_past_papers")
    op.drop_table("student_past_papers")
