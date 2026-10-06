"""consumed_attestations table for single-use proctor attestations (T-69)

Revision ID: c3a7e5f19b02
Revises: 9f2c7a1b4d63
Create Date: 2026-09-21
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "c3a7e5f19b02"
down_revision: str | None = "9f2c7a1b4d63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No tenant foreign key, mirroring audit_log: consumption must not be
    # rejected because a tenant row is missing for this student — see
    # original/db/models/live.py:ConsumedAttestation.
    op.create_table(
        "consumed_attestations",
        sa.Column("jti", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("exam", sa.Text(), nullable=True),
        sa.Column("student_id", sa.Text(), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("jti", name=op.f("pk_consumed_attestations")),
    )


def downgrade() -> None:
    op.drop_table("consumed_attestations")
