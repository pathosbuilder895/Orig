"""bluebook sessions + seal idempotency

Exam-day robustness: a ``bluebook_sessions`` table pinning one immutable
server deadline per (exam, student) sitting, and ``submission_uuid``/``late``
on ``bluebook_submissions`` so a retried seal replays idempotently instead
of double-writing. Mirrors the SQLite DDL in original/store.py; models in
original/db/models/live.py (``BluebookSession``).

Revision ID: 7c4d1e88a3b5
Revises: 3f695550f43e
Create Date: 2026-07-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7c4d1e88a3b5"
down_revision: str | None = "3f695550f43e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bluebook_sessions",
        sa.Column("exam_id", sa.Text(), primary_key=True),
        sa.Column("student_key", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.tenant_id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column("bluebook_submissions", sa.Column("submission_uuid", sa.Text(), nullable=True))
    op.add_column(
        "bluebook_submissions",
        sa.Column("late", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "idx_bluebook_subs_uuid",
        "bluebook_submissions",
        ["submission_uuid"],
        unique=True,
        postgresql_where=sa.text("submission_uuid IS NOT NULL"),
        sqlite_where=sa.text("submission_uuid IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_bluebook_subs_uuid", table_name="bluebook_submissions")
    op.drop_column("bluebook_submissions", "late")
    op.drop_column("bluebook_submissions", "submission_uuid")
    op.drop_table("bluebook_sessions")
