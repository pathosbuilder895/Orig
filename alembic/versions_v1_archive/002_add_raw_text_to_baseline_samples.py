"""Add raw_text column to baseline_samples.

Revision ID: 002
Revises: 001
Create Date: 2026-03-17

Stores the original submission text alongside the SHA-256 hash so that
feature vectors can be rebuilt when the extractor pipeline changes.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "baseline_samples",
        sa.Column("raw_text", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("baseline_samples", "raw_text")
