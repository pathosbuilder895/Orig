"""bluebook_exam_drafts: server copy of a student's unsealed exam draft

Additive only: one new table, nothing existing is altered. A row holds the
student's own unsealed writing so a sitting can resume from another
browser; it is deleted when the exam is sealed.

Revision ID: c9f2a4e6b8d1
Revises: b5e1f7c3a9d2
Create Date: 2026-10-21
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "c9f2a4e6b8d1"
down_revision: str | None = "b5e1f7c3a9d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bluebook_exam_drafts",
        sa.Column("exam_id", sa.Text(), nullable=False),
        sa.Column("student_key", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), server_default="", nullable=False),
        sa.Column("answers", sa.Text(), server_default="[]", nullable=False),
        sa.Column("client_saved_at", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("exam_id", "student_key", name=op.f("pk_bluebook_exam_drafts")),
    )


def downgrade() -> None:
    op.drop_table("bluebook_exam_drafts")
