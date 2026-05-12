"""Add baseline_kappa column to students table.

Revision ID: 005
Revises: 004
Create Date: 2026-04-07

Adds:
  - students.baseline_kappa  Running mean catastrophe index κ across all
                             authenticated (proctored/verified) baseline samples.
                             Populated incrementally as instructors add authenticated
                             baselines; NULL until at least one baseline exists.
"""

from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "students",
        sa.Column(
            "baseline_kappa",
            sa.Float(),
            nullable=True,
            comment="Running mean catastrophe index κ across all authenticated baselines",
        ),
    )


def downgrade() -> None:
    op.drop_column("students", "baseline_kappa")
