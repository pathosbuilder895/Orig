"""Add baseline_kappa + feature_vector_dim columns to baseline_samples.

Revision ID: 006
Revises: 005
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'baseline_samples',
        sa.Column('baseline_kappa', sa.Float(), nullable=True, comment='Catastrophe Index κ computed at baseline-add time')
    )
    op.add_column(
        'baseline_samples',
        sa.Column('feature_vector_dim', sa.Integer(), nullable=True, comment='Dimension of feature vector at time of extraction (for staleness detection)')
    )


def downgrade() -> None:
    op.drop_column('baseline_samples', 'feature_vector_dim')
    op.drop_column('baseline_samples', 'baseline_kappa')
